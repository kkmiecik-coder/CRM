# -*- coding: utf-8 -*-
"""
Konfiguracja zamówienia dla checkoutu klienckiego.

Panel BaseLinkera składa `config` w JavaScripcie (baselinker.js:1568-1601)
i wysyła go w żądaniu. Checkout klienta nie ma skąd go wziąć, więc buduje
go tutaj — serwerowo, bez sesji zalogowanego użytkownika.

Świadomie NIE ustawiamy client_data: podanie go zastępuje dane z bazy
w całości, a checkout zapisuje dane klienta na obiekcie Client zanim
utworzy zamówienie.

JEDNO ŹRÓDŁO PRAWDY O SPOSOBIE DOSTAWY
======================================
Adres, pod który zamówienie faktycznie pojedzie, bierze się WYŁĄCZNIE
z danych zapisanych na kliencie (service.py — delivery_address, delivery_city
itd.). Pole `is_self_pickup` z formularza nie ma jak tam trafić: dane dostawy
zapisuje tylko akceptacja wyceny, a dla wyceny zaakceptowanej wcześniej
akceptacja się już nie wykonuje. Dlatego dane klienta są jedynym źródłem
adresu, a formularz nie jest ich drugą, równoległą wersją: może co najwyżej
adres ZDJĄĆ (odbiór osobisty), nigdy go wymyślić.

Stąd dwa kierunki sprzeczności rozstrzygnięte niesymetrycznie:

* formularz „odbiór osobisty" + realny adres na kliencie — składamy jako
  odbiór osobisty i JEDNOCZEŚNIE zdejmujemy adres z zamówienia
  (`delivery_override`). Dawniej zamówienie szło z metodą „Odbiór osobisty",
  zerowym kosztem dostawy I pełnym adresem kurierskim: magazyn dostawał
  sprzeczne zlecenie, a przesyłka mogła pojechać za darmo. Wybór klienta
  honorujemy, bo to jego pieniądze i jego świeża decyzja — ale musi być
  spójny w całym zamówieniu. Danych na kliencie NIE ruszamy: adres należy
  też do innych jego wycen;

* formularz „kurier" + adres „ODBIÓR OSOBISTY" na kliencie — rozstrzyga
  WYCENA. Gdy niesie własne dane dostawy (kuriera albo jego koszt), zamówienie
  jedzie kurierem jak w wycenie, a adres bierzemy z tego samego formularza
  (pełny: ulica, miasto, kod). Gdy wycena nic o dostawie nie mówi ALBO
  formularz nie niesie pełnego adresu — zamówienia NIE SKŁADAMY
  (KonfliktDostawy). Dawniej po cichu wygrywał odbiór osobisty, więc klient
  czekał na przesyłkę, która nigdy nie wyjechała; potem odmawialiśmy zawsze,
  co trafiało też w wyceny kurierskie klienta, który KIEDYKOLWIEK odebrał coś
  osobiście — bo znacznik siedzi na współdzielonym rekordzie klienta.

Sytuacja jest przy tym rzadka: przy wycenie akceptowanej TERAZ akceptacja
zapisuje dane dostawy prosto z tego samego formularza, więc oba źródła
zgadzają się z definicji. Modal zaznacza „odbiór osobisty" z góry, gdy na
kliencie siedzi znacznik odbioru — ale już NIE wtedy, gdy wycena niesie
własnego kuriera albo koszt dostawy (client_accept_modal.js:
wycenaJedzieKurierem). Bez tego wyjątku wycena kurierska klienta, który
kiedykolwiek odebrał coś osobiście, jechała do BaseLinkera z zerową dostawą.
"""


# Realne id źródła „Dębuś VPS" w panelu BaseLinkera (Ustawienia -> Źródła
# zamówień). Ta sama wartość, którą wstawia migracja
# migrations/2026-08-30-zrodlo-zamowien-debus.sql — i po NIEJ, a nie po nazwie,
# szuka się źródła w bazie. Nazwa jest polem redagowalnym w panelu: dopóki
# wiązała nas nazwa, samo przemianowanie źródła kładło cały checkout.
ID_ZRODLA_DEBUS = 85727


# Nazwa metody dostawy dla odbioru osobistego — ta sama, którą wstawia panel
# handlowca (baselinker.js:1004), żeby BaseLinker widział jedną wartość
# niezależnie od tego, kto złożył zamówienie.
ODBIOR_OSOBISTY = "Odbiór osobisty"

# Znacznik zapisywany na kliencie przy odbiorze osobistym
# (client_accept_quote_with_data: delivery_address = 'ODBIÓR OSOBISTY').
_ZNACZNIKI_ODBIORU = ("odbiór osobisty", "odbior osobisty")


class KonfliktDostawy(Exception):
    """Formularz mówi co innego o dostawie niż dane zapisane na kliencie.

    Świadomie wyjątek, a nie „wybierz jedno i jedź dalej": to jedyny sposób,
    żeby ta sprzeczność nie zamieniła się w milczącą decyzję o cudzych
    pieniądzach. Łapie go checkout_service i zamienia na odmowę z prośbą
    o kontakt.
    """


def _na_float(wartosc):
    """Decimal/None/str -> float. Brak wartości = 0.0 (a nie wyjątek)."""
    if wartosc is None:
        return 0.0
    return float(wartosc)


def _adres_dostawy(quote):
    """Adres dostawy zapisany na kliencie wyceny (przycięty, może być pusty)."""
    client = getattr(quote, 'client', None)
    return (getattr(client, 'delivery_address', None) or '').strip()


def _adres_wskazuje_odbior_osobisty(quote):
    """Czy adres dostawy zapisany na kliencie to znacznik odbioru osobistego."""
    return _adres_dostawy(quote).lower() in _ZNACZNIKI_ODBIORU


def _wycena_wskazuje_kuriera(quote):
    """Czy sama WYCENA niesie dostawę kurierską — czyli NAZWĘ kuriera.

    To jedyna informacja o dostawie, która należy do konkretnej wyceny, a nie
    do współdzielonego rekordu klienta. Nazwa „Odbiór osobisty" w polu kuriera
    (tak wpisuje ją panel handlowca) kurierem oczywiście nie jest.

    Sam koszt wysyłki bez nazwy kuriera NIE wystarcza: nie byłoby czego wpisać
    w `delivery_method` i zamówienie pojechałoby jako „Odbiór osobisty"
    z niezerowym kosztem dostawy — czyli dokładnie ta sprzeczność, przed którą
    broni ten moduł. Taka wycena zostaje przy odmowie. Modal jest ostrożniejszy
    i nie zaznacza odbioru już przy samym koszcie (client_accept_modal.js:
    wycenaJedzieKurierem) — bo to zaznaczenie kasuje koszt po cichu, a odmowa
    kończy się rozmową z człowiekiem.
    """
    kurier = (getattr(quote, 'courier_name', None) or '').strip()
    return bool(kurier) and kurier.lower() not in _ZNACZNIKI_ODBIORU


def _adres_z_formularza(dane_dostawy):
    """Komplet adresu wpisany w formularzu zamówienia albo None.

    Wymagamy adresu, miasta I kodu pocztowego: przesyłka kurierska bez
    któregokolwiek z nich i tak nie dojdzie, a niekompletny adres byłby
    gorszy od odmowy, bo wyglądałby na zamówienie zrobione poprawnie.
    """
    dane_dostawy = dane_dostawy or {}
    pola = {klucz: (dane_dostawy.get(klucz) or '').strip()
            for klucz in ('delivery_name', 'delivery_company', 'delivery_address',
                          'delivery_postcode', 'delivery_city', 'delivery_region')}
    if not (pola['delivery_address'] and pola['delivery_city']
            and pola['delivery_postcode']):
        return None
    nadpisanie = {klucz: pola[klucz] for klucz in
                  ('delivery_address', 'delivery_postcode', 'delivery_city',
                   'delivery_region', 'delivery_company')}
    if pola['delivery_name']:
        # Pustej nazwy NIE wysyłamy: nadpisanie kasuje to, co jest na kliencie.
        nadpisanie['delivery_name'] = pola['delivery_name']
    return nadpisanie


def rozstrzygnij_odbior_osobisty(quote, is_self_pickup,
                                 dane_dostawy_z_formularza=None):
    """(czy odbiór osobisty, nadpisanie danych dostawy). Rzuca KonfliktDostawy.

    Drugi element to gotowy `delivery_override` albo None. Powstaje w dwóch
    sytuacjach — i w obu chodzi o to samo: żeby zamówienie nie niosło adresu
    sprzecznego z metodą dostawy.

    Brak adresu na kliencie NIE jest sprzecznością z niczym: nie ma dwóch
    źródeł, które mówiłyby co innego, więc decyduje formularz. Ten przypadek
    zdarza się przy wycenach zaakceptowanych wewnętrznie, bez danych dostawy.

    TRZECIE WYJŚCIE Z KONFLIKTU „kurier w formularzu, odbiór na kliencie".
    Znacznik odbioru siedzi na rekordzie KLIENTA, więc zostaje tam po każdej
    wycenie odebranej osobiście i obowiązuje wszystkie następne. Sama odmowa
    trafiała przez to również w wyceny, które z odbiorem osobistym nie mają nic
    wspólnego: klient dostawał telefon do biura, a jedyną alternatywą było
    zamówienie z zerowym kosztem dostawy (bo modal zaznaczał odbiór za niego).
    Gdy wycena niesie WŁASNE dane dostawy — kuriera albo jego koszt — to ona
    rozstrzyga i zamówienie jedzie kurierem, jak w wycenie.

    Adres wciąż nie jest WYMYŚLANY: bierzemy ten wpisany w tym samym
    formularzu, przepuszczonym przez tę samą bramkę tożsamości (email LUB
    telefon zgodny z klientem), którą akceptacja uznaje za wystarczającą, żeby
    ten adres klientowi ZAPISAĆ. Gdy formularz adresu nie niesie, zostaje
    odmowa — przesyłka pod adres „ODBIÓR OSOBISTY" byłaby gorsza niż jej brak.
    """
    zapisany_odbior = _adres_wskazuje_odbior_osobisty(quote)
    ma_realny_adres = bool(_adres_dostawy(quote)) and not zapisany_odbior
    z_formularza = bool(is_self_pickup)

    if not z_formularza and zapisany_odbior:
        if not _wycena_wskazuje_kuriera(quote):
            raise KonfliktDostawy(
                "formularz wskazuje dostawę kurierem, a na kliencie zapisany "
                "jest odbiór osobisty i sama wycena nie niesie danych dostawy")
        adres = _adres_z_formularza(dane_dostawy_z_formularza)
        if adres is None:
            raise KonfliktDostawy(
                "formularz wskazuje dostawę kurierem, a na kliencie zapisany "
                "jest odbiór osobisty i formularz nie niesie pełnego adresu")
        return False, adres

    if z_formularza and ma_realny_adres:
        # Zamówienie z metodą „Odbiór osobisty" nie może nieść adresu
        # kurierskiego — ten sam znacznik, który przy odbiorze zapisuje
        # akceptacja wyceny (client_accept_quote_with_data).
        return True, {
            "delivery_address": ODBIOR_OSOBISTY.upper(),
            "delivery_city": ODBIOR_OSOBISTY.upper(),
            "delivery_postcode": "",
            "delivery_region": "",
            "delivery_company": "",
        }

    return (z_formularza or zapisany_odbior), None


def build_checkout_order_config(quote, order_source_id, is_self_pickup=False,
                                dane_dostawy_z_formularza=None):
    """Konfiguracja dla BaselinkerService.create_order_from_quote.

    quote                      — obiekt Quote (albo dowolny z polami quote_type,
                                 courier_name, shipping_cost_netto/brutto)
    order_source_id            — baselinker_id źródła „Dębuś VPS"
                                 (ID_ZRODLA_DEBUS)
    is_self_pickup             — wybór klienta z formularza zamówienia
    dane_dostawy_z_formularza  — pola dostawy z tego samego formularza; używane
                                 WYŁĄCZNIE wtedy, gdy wycena kurierska musi
                                 przebić znacznik odbioru z rekordu klienta

    Rzuca KonfliktDostawy, gdy formularz przeczy danym dostawy zapisanym
    na kliencie, a wycena nie ma czym tego rozstrzygnąć.
    """
    # Tryb cen czytamy tak samo jak serwis (service.py:527): getattr z domyślnym
    # 'brutto', bo pusta wartość w kolumnie też ma znaczyć brutto.
    tryb_cen = getattr(quote, 'quote_type', 'brutto') or 'brutto'

    # Wycena netto ma pozycje netto — koszt dostawy musi jechać tą samą stroną,
    # inaczej suma w BaseLinkerze rozjedzie się z zaakceptowaną wyceną.
    if tryb_cen == 'netto':
        wysylka = _na_float(quote.shipping_cost_netto)
    else:
        wysylka = _na_float(quote.shipping_cost_brutto)

    odbior_osobisty, nadpisanie_dostawy = rozstrzygnij_odbior_osobisty(
        quote, is_self_pickup, dane_dostawy_z_formularza)
    if odbior_osobisty:
        dostawa = ODBIOR_OSOBISTY
        wysylka = 0.0
    else:
        dostawa = quote.courier_name or ODBIOR_OSOBISTY

    config = {
        "order_source_id": order_source_id,
        "payment_method": "Przelew bankowy",
        "delivery_method": dostawa,
        "delivery_country": "PL",
        "shipping_cost_override": wysylka,
        "include_attachment": True,
    }

    if nadpisanie_dostawy:
        # Adres zamówienia musi być spójny z metodą dostawy — patrz
        # rozstrzygnij_odbior_osobisty.
        config["delivery_override"] = nadpisanie_dostawy

    return config
