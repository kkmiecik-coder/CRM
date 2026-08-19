# modules/production/services/station_catalog.py
"""
Jedyne źródło nazw i kolejności stanowisk produkcyjnych.

Powód powstania: te same kody miały w module pięć różnych zestawów etykiet —
MONITOR_STATION_MAP (routers/stations), STATION_LABELS (reports_api),
STATION_NAMES (product_history_service), _STATION_NAMES (dashboard_api)
i station_label() (worker_service). Efekt widoczny gołym okiem: w JEDNYM
widgecie użytkownik wybierał z listy „Wycinanie", a w kolumnie obok czytał
„Wycinanie - mikro". Do tego Lakiernia była w dwóch listach, w trzeciej nie,
a formularz pracownika w ogóle jej nie oferował — mimo że raport pozwalał po
niej filtrować.

Ten moduł celowo NIE zna Flaska ani blueprintów: importuje go i router,
i serwis, i szablon przez kontekst — cykl importów byłby tu łatwy do zrobienia.

Nazwy są w formie PEŁNEJ ('Wycinanie - mikro', nie 'Wycinanie'), bo takimi
mówią monitory na hali i historia produktu. Panel ma mówić do ludzi tym samym
językiem co ekran, na który patrzą przy maszynie.
"""

# Kolejność procesu, nie alfabetyczna — listy rozwijane mają odwzorowywać
# drogę produktu przez halę.
STATION_ORDER = (
    'cutting',
    'assembly',
    'gluing',
    'formatting',
    'finishing',
    'painting',
    'packaging',
)

STATION_LABELS = {
    'cutting': 'Wycinanie - mikro',
    'assembly': 'Składanie - lite',
    'gluing': 'Sklejanie',
    'formatting': 'Formatowanie',
    'finishing': 'Wykańczanie',
    'painting': 'Lakiernia',
    'packaging': 'Pakowanie',
    # Poza pipeline'em produktów — rejestr surowca. Pracownik może mieć tu
    # sesję, więc nazwa jest potrzebna, ale w listach stanowisk produkcyjnych
    # (STATION_ORDER) świadomie jej nie ma.
    'sawmill': 'Trakownia',
}


# Stanowisko → status pozycji CZEKAJĄCEJ na tym stanowisku (kolejka).
#
# Ta mapa miała dwie kopie: STATION_STATUS_MAP w mobile_api_service (7 pozycji)
# i _STATION_PENDING_STATUS w dashboard_api (6 — bez lakierni). Skutek był
# widoczny w liczbach: dashboard nie pokazywał kolejki lakierni w ogóle, mimo
# że to na niej stoi dziś najdłuższy zapas (raport „Dni zapasu przed
# stanowiskiem" liczy jej 6,6 dnia). Obie kopie czytają teraz stąd.
#
# 'sawmill' celowo nie występuje — trakownia nie ma statusów ProductionProduct,
# liczy się z własnych tabel prod_sawmill_*.
STATION_PENDING_STATUS = {
    'cutting': 'czeka_na_wyciecie',
    'assembly': 'czeka_na_skladanie',
    'gluing': 'czeka_na_sklejanie',
    'formatting': 'czeka_na_formatowanie',
    'finishing': 'czeka_na_wykanczanie',
    'painting': 'czeka_na_lakiernie',
    'packaging': 'czeka_na_pakowanie',
}


def station_label(station_code):
    """Kod → nazwa po polsku. Nieznany kod zwracamy surowo, zamiast wywracać widok."""
    if not station_code:
        return '—'
    return STATION_LABELS.get(station_code, station_code)


def station_choices(include_sawmill=False):
    """
    [(kod, nazwa)] w kolejności procesu — do wszystkich list rozwijanych
    i checkboxów, żeby żadna nie miała własnej, rozjeżdżającej się kopii.
    """
    wybor = [(kod, STATION_LABELS[kod]) for kod in STATION_ORDER]
    if include_sawmill:
        wybor.append(('sawmill', STATION_LABELS['sawmill']))
    return wybor


# Skrócone nazwy — WYŁĄCZNIE do miejsc, gdzie etykieta musi zmieścić się
# w wąskiej pigułce obok innej treści (dziś: kafel „Alerty terminów" na
# dashboardzie produkcji, gdzie w jednej linii stoją już numer zamówienia
# i liczba produktów).
#
# Stoją TUTAJ, a nie w widoku, dokładnie z powodu opisanego na górze pliku:
# każda kopia nazw stanowisk poza tym modułem po jakimś czasie rozjeżdża się
# z resztą. Kto zmienia STATION_LABELS, ma obie mapy przed oczami.
#
# Formy pełne ('Wycinanie - mikro', 'Składanie - lite') zostają domyślne —
# krótkiej wersji używa się świadomie, wołając station_short_label().
STATION_SHORT_LABELS = {
    'cutting': 'Wycinanie',
    'assembly': 'Składanie',
}


def station_short_label(station_code):
    """
    Kod → krótka nazwa do wąskich elementów UI. Gdy skrótu nie ma,
    zwraca nazwę pełną — czyli zawsze coś sensownego.
    """
    if not station_code:
        return '—'
    return STATION_SHORT_LABELS.get(station_code, station_label(station_code))


def is_production_station(station_code):
    return station_code in STATION_ORDER
