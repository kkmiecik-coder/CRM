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


def is_production_station(station_code):
    return station_code in STATION_ORDER
