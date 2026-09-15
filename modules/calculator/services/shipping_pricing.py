# -*- coding: utf-8 -*-
"""
Wyliczanie ceny wysyłki: narzut procentowy na pakowanie + kwotowa dopłata
zależna od progu.

JEDYNE miejsce w repozytorium z tą formułą. Wcześniej żyła w trzech kopiach —
dwóch w JS (calculator-core.js, calculator-delivery.js) i jednej w Pythonie
(shipping_service.PACKING_MULTIPLIER) — więc zmiana narzutu wymagała deployu,
a rozjechanie się którejkolwiek kopii oznaczało, że bot podaje klientowi inną
cenę wysyłki niż handlowiec w CRM. Nie dopisuj tu drugiej ścieżki liczenia
ani nie przenoś arytmetyki do JS.
"""

VAT_MULTIPLIER = 1.23

SIDE_BELOW = 'below'
SIDE_ABOVE = 'above'
_SIDES = (SIDE_BELOW, SIDE_ABOVE)

# Górna granica narzutu. Nie jest regułą biznesową, tylko bezpiecznikiem na
# literówkę w panelu (3000 zamiast 30) i na śmieci w bazie.
MAX_PERCENT = 500.0

DEFAULT_CONFIG = {
    'percent': 30.0,
    'threshold_brutto': 0.0,
    'surcharge_brutto': 0.0,
    'side': SIDE_BELOW,
}

# Mapowanie pól konfiguracji na klucze w tabeli calculator_settings.
SETTING_KEYS = {
    'percent': 'shipping_markup_percent',
    'threshold_brutto': 'shipping_threshold_brutto',
    'surcharge_brutto': 'shipping_surcharge_brutto',
    'side': 'shipping_surcharge_side',
}


def _liczba_lub_none(wartosc):
    """Liczba nieujemna i skończona albo None (wartość do odrzucenia)."""
    try:
        liczba = float(wartosc)
    except (TypeError, ValueError):
        return None
    # NaN nie jest równy sam sobie; inf odsiewamy osobno, bo float('inf') > 0.
    if liczba != liczba or liczba in (float('inf'), float('-inf')):
        return None
    if liczba < 0:
        return None
    return liczba


def _liczba(wartosc, domyslna, maksimum=None):
    """Jak wyżej, ale zamiast None zwraca wartość domyślną. Nigdy nie rzuca."""
    liczba = _liczba_lub_none(wartosc)
    if liczba is None:
        return domyslna
    if maksimum is not None and liczba > maksimum:
        return domyslna
    return liczba


def sanitize_shipping_config(surowe):
    """Surowe wartości (stringi z bazy) -> poprawna konfiguracja.

    Każde nieczytelne pole wraca do wartości domyślnej i NIE przerywa działania:
    zepsuty wiersz w calculator_settings nie może wywrócić wyceny wysyłki
    handlowcowi w środku rozmowy z klientem. Panel Ustawień ma inne wymagania —
    tam błędny wpis musi wrócić do administratora, patrz validate_shipping_settings.
    """
    surowe = surowe or {}
    strona = surowe.get('side')
    strona = strona.strip().lower() if isinstance(strona, str) else None
    return {
        'percent': _liczba(surowe.get('percent'),
                           DEFAULT_CONFIG['percent'], MAX_PERCENT),
        'threshold_brutto': _liczba(surowe.get('threshold_brutto'),
                                    DEFAULT_CONFIG['threshold_brutto']),
        'surcharge_brutto': _liczba(surowe.get('surcharge_brutto'),
                                    DEFAULT_CONFIG['surcharge_brutto']),
        'side': strona if strona in _SIDES else DEFAULT_CONFIG['side'],
    }


def load_shipping_config():
    """Konfiguracja z tabeli calculator_settings. Wymaga kontekstu aplikacji.

    Tabela jest składnikiem odcisku cache'u cennika (pricing_service), więc
    zmiana w panelu wchodzi w życie na wszystkich workerach w ≤15 s.
    """
    from modules.calculator.models import CalculatorSetting

    surowe = {}
    for pole, klucz in SETTING_KEYS.items():
        try:
            surowe[pole] = CalculatorSetting.get_value(klucz)
        except Exception:
            # Baza niedostępna albo brak tabeli — lepiej policzyć po staremu
            # (wartości domyślne = dzisiejsze +30%) niż wywalić wycenę.
            surowe[pole] = None
    return sanitize_shipping_config(surowe)


def apply_shipping_markup(raw_brutto, config=None):
    """Rozkład ceny wysyłki dla jednej oferty kuriera (cena brutto z GlobKuriera).

    Kolejność jest istotna: najpierw procent, POTEM porównanie z progiem, na
    końcu dopłata. Progiem mierzymy cenę PO procencie, nie surową — decyzja
    z 15.09.2026. Cena dokładnie równa progowi należy do „od progu w górę".
    """
    config = config if config is not None else load_shipping_config()
    surowa = _liczba(raw_brutto, 0.0)

    po_procencie = surowa * (1.0 + config['percent'] / 100.0)

    prog = config['threshold_brutto']
    if config['side'] == SIDE_ABOVE:
        nalezy_sie = po_procencie >= prog
    else:
        nalezy_sie = po_procencie < prog
    doplata = config['surcharge_brutto'] if nalezy_sie else 0.0

    koncowa = po_procencie + doplata
    return {
        'raw_brutto': round(surowa, 2),
        'raw_netto': round(surowa / VAT_MULTIPLIER, 2),
        'markup_brutto': round(po_procencie - surowa, 2),
        'surcharge_brutto': round(doplata, 2),
        'final_brutto': round(koncowa, 2),
        'final_netto': round(koncowa / VAT_MULTIPLIER, 2),
    }


def _kwota(wartosc):
    """12.3 -> '12,30 zł'. Przecinek dziesiętny, jak w reszcie komunikatów."""
    return '{:.2f}'.format(wartosc).replace('.', ',') + ' zł'


def _procent(wartosc):
    """30.0 -> '30%', 27.5 -> '27,5%'. Bez zbędnych zer po przecinku."""
    tekst = '{:.2f}'.format(wartosc).rstrip('0').rstrip('.')
    return tekst.replace('.', ',') + '%'


def describe_shipping_markup(config=None):
    """Zdanie dla modala dostawy — co dokładnie doliczono do cen kuriera."""
    config = config if config is not None else load_shipping_config()
    zdanie = 'Do cen wysyłki doliczono {} na pakowanie'.format(
        _procent(config['percent']))
    if config['surcharge_brutto'] > 0:
        granica = 'poniżej' if config['side'] == SIDE_BELOW else 'od'
        zdanie += ' oraz {} przy cenie {} {}'.format(
            _kwota(config['surcharge_brutto']), granica,
            _kwota(config['threshold_brutto']))
    return zdanie + '.'


def build_markup_payload(gross_prices, config):
    """Odpowiedź endpointu /calculator/api/shipping-markup.

    Kolejność `items` odpowiada kolejności wejścia — front wiąże pozycje po
    indeksie z nazwą i logo przewoźnika, więc nie wolno tu sortować.
    """
    return {
        'items': [apply_shipping_markup(cena, config) for cena in gross_prices],
        'info': describe_shipping_markup(config),
        'config': config,
    }


def validate_shipping_settings(data):
    """Waliduje wartości przysłane z panelu Ustawień.

    Zwraca (czyste_wartosci, None) albo (None, komunikat_bledu). Klucze
    nieobecne w żądaniu są pomijane — panel zapisuje też inne ustawienia
    kalkulatora tym samym endpointem.

    W odróżnieniu od sanitize_shipping_config tutaj błąd MUSI wrócić do
    administratora: cicha podmiana jego wpisu na wartość domyślną byłaby
    gorsza niż odmowa zapisu, bo zobaczyłby „Zapisano!" i inne ceny.
    """
    data = data or {}
    czyste = {}

    klucz = 'shipping_markup_percent'
    if klucz in data:
        liczba = _liczba_lub_none(data[klucz])
        if liczba is None or liczba > MAX_PERCENT:
            return None, 'Narzut musi być liczbą z zakresu 0–{}.'.format(
                int(MAX_PERCENT))
        czyste[klucz] = liczba

    for klucz, etykieta in (('shipping_threshold_brutto', 'Próg'),
                            ('shipping_surcharge_brutto', 'Kwota dopłaty')):
        if klucz in data:
            liczba = _liczba_lub_none(data[klucz])
            if liczba is None:
                return None, '{} musi być liczbą nieujemną.'.format(etykieta)
            czyste[klucz] = liczba

    klucz = 'shipping_surcharge_side'
    if klucz in data:
        strona = data[klucz]
        strona = strona.strip().lower() if isinstance(strona, str) else None
        if strona not in _SIDES:
            return None, 'Nieznana strona progu — wybierz jedną z opcji listy.'
        czyste[klucz] = strona

    return czyste, None


def parse_markup_request(payload):
    """Wyciąga listę cen brutto z ciała żądania /api/shipping-markup.

    Zwraca (ceny, None) albo (None, komunikat_błędu). Ciało żądania bywa
    czymkolwiek — brakiem JSON-a, gołą listą, liczbą — więc sprawdzamy typ,
    zamiast zakładać słownik i wywracać się na AttributeError.
    """
    if not isinstance(payload, dict):
        return None, 'Brak cen do przeliczenia.'
    ceny = payload.get('gross_prices')
    if not isinstance(ceny, list) or not ceny:
        return None, 'Brak cen do przeliczenia.'
    return ceny, None
