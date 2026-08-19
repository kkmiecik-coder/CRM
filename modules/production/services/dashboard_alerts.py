# modules/production/services/dashboard_alerts.py
# -*- coding: utf-8 -*-
"""
Alerty terminów na dashboardzie produkcji — jedno źródło danych dla kafla
„Alerty terminów".

Powód powstania: alerty budowały się w DWÓCH miejscach o różnym kształcie.
Pierwszy render strony (main_routers) dawał jeden alert na POZYCJĘ, z limitem
pięciu; odświeżanie w tle (dashboard_api) grupowało pozycje po ZAMÓWIENIU
i limitu nie miało. Użytkownik widział więc, jak po kilkunastu sekundach od
wejścia lista sama się przebudowuje — kafle zlewają się w zamówienia, a zamiast
pięciu pozycji pojawia się siedem alertów. Obie ścieżki wołają teraz to samo.

Stanowisko w alercie: alert dotyczy CAŁEGO zamówienia, a jego pozycje potrafią
stać na różnych stanowiskach. Pokazujemy NAJMNIEJ zaawansowane, bo to ono
wyznacza, kiedy zamówienie wyjedzie z hali — reszta i tak czeka na nie.
"""

from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from ..models import ProductionItem
from .station_catalog import station_short_label

# Status pozycji → (ranga w pipelinie, kod stanowiska).
#
# Ranga rośnie wraz z drogą produktu przez halę, w kolejności odwzorowującej
# next_status_map z ProductionProduct.complete_task. Niższa ranga = dalej do
# końca = to jest wąskie gardło zamówienia.
#
# 'wstrzymane' ma rangę 0, PRZED wycinaniem: wstrzymana pozycja jest ważniejszą
# informacją dla planisty niż to, że reszta zamówienia poszła dalej — jej nikt
# nie ruszy, dopóki ktoś świadomie nie zdejmie blokady.
#
# Kody stanowisk są te same, których używa grid „Stanowiska produkcyjne"
# (data-station w dashboard-tab-content.html) — dzięki temu pigułka w alercie
# bierze kolor z tej samej palety co kafelek stanowiska wyżej na stronie.
_STATUS_RANK = {
    'wstrzymane': (0, 'hold'),
    'czeka_na_wyciecie': (1, 'cutting'),
    'czeka_na_skladanie': (2, 'assembly'),
    'czeka_na_sklejanie': (3, 'gluing'),
    'czeka_na_formatowanie': (4, 'formatting'),
    'czeka_na_wykanczanie': (5, 'finishing'),
    'czeka_na_lakiernie': (6, 'painting'),
    'czeka_na_logistyke': (7, 'logistics'),
    'czeka_na_pakowanie': (8, 'packaging'),
}

# Etykiety dla pozycji spoza pipeline'u stanowisk. 'logistics' nie jest
# stanowiskiem w station_catalog (nie ma tabletu na hali), ale jest etapem,
# na którym pozycja realnie stoi — i ma swój kafelek na dashboardzie.
_EXTRA_LABELS = {
    'hold': 'Wstrzymane',
    'logistics': 'Logistyka',
}

# Ranga dla statusów, których nie ma w mapie ('w_realizacji', 'anulowane',
# cokolwiek dojdzie do enuma później). Wysoka, więc taka pozycja wygrywa
# wyłącznie wtedy, gdy w zamówieniu nie ma nic rozpoznanego — kafel pokazuje
# wtedy czytelną nazwę statusu zamiast zniknąć albo wypisać surowy enum.
_UNKNOWN_RANK = 99


def _station_of(item):
    """Pozycja → (ranga, kod stanowiska, etykieta)."""
    ranga, kod = _STATUS_RANK.get(item.current_status, (None, None))
    if kod is None:
        return _UNKNOWN_RANK, 'unknown', item.status_display_name
    if kod in _EXTRA_LABELS:
        return ranga, kod, _EXTRA_LABELS[kod]
    return ranga, kod, station_short_label(kod)


def build_deadline_alerts(days_ahead=3, limit=None):
    """
    Zamówienia z terminem w ciągu `days_ahead` dni (lub po terminie),
    posortowane od najbardziej palących.

    Zwraca listę dictów gotowych dla szablonu i dla JS-a — oba renderują
    ten sam kafel, więc oba dostają identyczny zestaw kluczy.
    """
    # date.today(), a nie get_local_now() — świadome przeniesienie 1:1 z obu
    # starych ścieżek. Kontener chodzi w UTC, więc między północą a 02:00 czasu
    # warszawskiego ta data jest o dzień do tyłu (pułapka opisana szerzej
    # w reports_service.py). Poprawianie tego przy okazji przesunęłoby okno
    # alertów o dobę bez związku z tą zmianą — na osobny task.
    today = date.today()

    items = ProductionItem.query.options(
        joinedload(ProductionItem.order),
    ).filter(
        ProductionItem.deadline_date <= (today + timedelta(days=days_ahead)),
        # 'anulowane' obok 'spakowane': przez lata filtr odsiewał tylko to
        # drugie, więc anulowane zamówienia wisiały na górze kafla na czerwono
        # („-68 DNI") i przebijały realnie zagrożone terminy. Widać to było
        # dopiero, gdy kafel zaczął pokazywać stanowisko.
        ProductionItem.current_status.notin_(('spakowane', 'anulowane'))
    ).order_by(ProductionItem.deadline_date.asc()).all()

    orders_map = {}
    for item in items:
        # Pozycja bez zamówienia (osierocona przez sync) trafia do kafla jako
        # własna grupa — lepiej pokazać ją bez numeru niż zgubić termin.
        oid = (item.order.baselinker_order_id if item.order else None) or item.short_product_id

        if oid not in orders_map:
            orders_map[oid] = {
                'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                'client_name': (item.order.client_name if item.order else None) or 'Brak danych',
                'deadline_date': item.deadline_date,
                'deadline_date_formatted': item.deadline_date.strftime('%d.%m.%Y') if item.deadline_date else '',
                'days_remaining': (item.deadline_date - today).days if item.deadline_date else 0,
                'products_count': 0,
                '_stations': {},
            }

        alert = orders_map[oid]
        alert['products_count'] += 1

        ranga, kod, etykieta = _station_of(item)
        alert['_stations'][kod] = (ranga, etykieta)

        # Termin zamówienia to termin jego najpilniejszej pozycji.
        if item.deadline_date and (alert['deadline_date'] is None or item.deadline_date < alert['deadline_date']):
            alert['deadline_date'] = item.deadline_date
            alert['deadline_date_formatted'] = item.deadline_date.strftime('%d.%m.%Y')
            alert['days_remaining'] = (item.deadline_date - today).days

    for alert in orders_map.values():
        stations = alert.pop('_stations')
        # Sortujemy po (ranga, kod) — sam kod jako drugi klucz, żeby przy
        # nierozpoznanych statusach o tej samej randze wynik był powtarzalny.
        ranga, kod, etykieta = min(
            ((r, k, e) for k, (r, e) in stations.items()),
            key=lambda s: (s[0], s[1]),
        )
        alert['station_code'] = kod
        alert['station_label'] = etykieta
        # Licznik "+N" mówi o STANOWISKACH, nie o pozycjach: trzy deski
        # czekające razem przy pakowaniu to jedno miejsce na hali, nie trzy.
        alert['other_stations_count'] = len(stations) - 1

    alerts = sorted(orders_map.values(), key=lambda a: a.get('days_remaining', 0))
    return alerts[:limit] if limit else alerts
