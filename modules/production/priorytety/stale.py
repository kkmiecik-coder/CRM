# -*- coding: utf-8 -*-
"""
Stałe priorytetów produkcji — jedno miejsce na listy statusów, tagi, domyślną drabinę i klucze `prod_config`
(spec 2026-10-04, sekcje 3.1, 4.1, 5.3, 8.6).

Klucze ustawień składają funkcje `klucz_*` — te same napisy zakłada migracja 2026-10-05-priorytety-produkcji.sql
i z nich korzysta panel. Nie wpisuj kluczy literałami poza tym plikiem.
"""
from modules.production.logistics import sposoby
from modules.production.services import station_catalog

# Pozycja „w produkcji” = czeka w kolejce któregoś stanowiska. Zamówienie jest AKTYWNE, gdy ma choć jedną taką
# pozycję. `w_realizacji` nikt nie nadaje, a `czeka_na_logistyke` to status archiwalny (cron logistyki przenosi
# takie pozycje do pakowania) — oba poza listą.
STATUSY_PRODUKCJI = (
    'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie', 'czeka_na_formatowanie',
    'czeka_na_krawedzie', 'czeka_na_lakiernie', 'czeka_na_pakowanie',
)
# Pozycja spakowana albo dalej — liczy się jako zrobiona (jedna lista na cały CRM: sposoby.py).
STATUSY_ZROBIONE = sposoby.STATUSY_PO_SPAKOWANIU

# Etap pozycji wg statusu — do porównań „wcześniej / dalej” (tag „Rozpoczęte”, kompletność zamówienia na
# Formatowaniu i Pakowaniu). Wycinanie i Składanie to dwie równoległe technologie tego samego etapu.
ETAP_STATUSU = {
    'czeka_na_wyciecie': 0, 'czeka_na_skladanie': 0,
    'czeka_na_sklejanie': 1,
    'czeka_na_formatowanie': 2,
    'czeka_na_krawedzie': 3,
    'czeka_na_lakiernie': 4,
    'czeka_na_logistyke': 5, 'czeka_na_pakowanie': 5,
}
ETAP_STATUSU.update({status: 6 for status in STATUSY_ZROBIONE})

ETAP_STANOWISKA = {
    'cutting': 0, 'assembly': 0, 'gluing': 1, 'formatting': 2, 'edges': 3, 'painting': 4, 'packaging': 5,
}

STANOWISKA = station_catalog.STATION_ORDER
# Stanowiska, na których kaflem jest całe zamówienie (zbierają pozycje i puszczają dalej tylko komplet).
STANOWISKA_ZAMOWIENIOWE = ('formatting', 'packaging')

TAG_PO_TERMINIE = 'po_terminie'
TAG_BLISKO_TERMINU = 'blisko_terminu'
TAG_ROZPOCZETE = 'rozpoczete'
TAGI = (TAG_PO_TERMINIE, TAG_BLISKO_TERMINU, TAG_ROZPOCZETE)

RODZAJE_SZCZEBLA = ('stars', 'tag', 'route')
GWIAZDKI_MAX = 5
# Trasa ma szczebel na drabinie (i decyduje o szczeblu zamówienia) tylko jako robocza albo zatwierdzona. To zbiór
# WĘŻSZY niż logistics.models.STATUSY_TRASY_AKTYWNE: trasa załadowana albo w drodze już nie czeka na produkcję.
STATUSY_TRASY_NA_DRABINIE = ('robocza', 'zatwierdzona')
# Pozycje pomijane przy tagu „Rozpoczęte” i kompletności zamówienia: biuro zabrało je z kolejki.
STATUSY_POZA_KOLEJKA = ('anulowane', 'wstrzymane')
# Ranga pozycji = ranga zamówienia × MNOZNIK_RANGI + kolejność pozycji w zamówieniu (doróbki 0).
MNOZNIK_RANGI = 100

# Drabina po migracji (spec 3.1, decyzja Konrada 5.10): pięć gwiazdek, Po terminie, cztery gwiazdki, Blisko
# terminu, Rozpoczęte, trzy, dwie, jedna, bez gwiazdek. Szczeble tras dochodzą razem z trasami.
DRABINA_DOMYSLNA = (
    ('stars', 5), ('tag', TAG_PO_TERMINIE), ('stars', 4), ('tag', TAG_BLISKO_TERMINU), ('tag', TAG_ROZPOCZETE),
    ('stars', 3), ('stars', 2), ('stars', 1), ('stars', 0),
)

POWODY_ODLOZENIA = ('brak_materialu', 'awaria_maszyny', 'brak_miejsca', 'czeka_na_biuro', 'inne')
# Powód odłożenia po polsku — dla panelu i monitorów hali (jedno miejsce; JS monitora dostaje gotowy tekst).
ETYKIETY_POWODOW_ODLOZENIA = {
    'brak_materialu': u'brak materiału',
    'awaria_maszyny': u'awaria maszyny',
    'brak_miejsca': u'brak miejsca',
    'czeka_na_biuro': u'czeka na biuro',
    'inne': u'inne',
}
JEDNOSTKI = ('pozycja', 'zamowienie')
TRYBY = ('stary', 'stol')
# Kolejność jak w ENUM kolumny `prod_priority_log.action` (migracje 2026-10-05 i 2026-10-06): nowe akcje na końcu.
AKCJE_LOGU = ('gwiazdki', 'szczebel', 'odlozenie', 'odlozenie_zamkniete', 'ustawienia', 'przeliczenie',
              'wyslanie', 'zdjecie', 'start_stolow')

# Skąd kafel wziął się na stole (spec 5.1, kolumna `prod_station_desk.zrodlo`): pobrany przez dopełnienie, doróbka
# (pierwsza z kolejki, w ramach K), wysłany przez biuro (5.7, ponad K), rozpoczęty przed przejściem na stoły (5.8,
# ponad K).
ZRODLO_KOLEJKA = 'kolejka'
ZRODLO_DOROBKA = 'dorobka'
ZRODLO_BIURO = 'biuro'
ZRODLO_START = 'start'
ZRODLA_KAFLA = (ZRODLO_KOLEJKA, ZRODLO_DOROBKA, ZRODLO_BIURO, ZRODLO_START)
# Kolejność kafli NA STOLE (spec 5.1): doróbki, wysłane przez biuro, startowe, pobrane z kolejki.
KOLEJNOSC_ZRODEL_NA_STOLE = (ZRODLO_DOROBKA, ZRODLO_BIURO, ZRODLO_START, ZRODLO_KOLEJKA)
TYPY_DNI = ('robocze', 'kalendarzowe')

# Wartości domyślne — te same, które wpisuje migracja.
STOL_K = 2
LIMIT_ODLOZEN = 10
BLISKO_TERMINU_DNI = 3
MIN_APP_VERSION_CODE = 0
DEADLINE_DAY_TYPE_DOMYSLNY = 'robocze'
# Największy hurt zamówień w jednym żądaniu — jak w panelu Logistyki (logistics/routers/panel_api.LIMIT_HURTU);
# serwis nie importuje routera, równości pilnuje test.
LIMIT_HURTU = 500

KLUCZ_BLISKO = 'priorytety_blisko_terminu_dni'
KLUCZ_MIN_APP = 'priorytety_min_app_version_code'
KLUCZ_TYP_DNI = 'DEADLINE_DAY_TYPE'
# Liczba dni terminu nowych zamówień (spec 4.3): surowe i z wykończeniem. Zapis z panelu tylko przez
# `PUT /production/api/priorytety/ustawienia` (karta „Terminy”, krok K4b); czyta je import z Base. przez config_service.
KLUCZ_TERMIN_SUROWE = 'DEADLINE_DEFAULT_DAYS'
KLUCZ_TERMIN_WYKONCZONE = 'DEADLINE_FINISHED_DAYS'
# Wartości domyślne — te same co `config_service._default_values` i domyślne w `sync_service` (pilnuje test).
TERMIN_SUROWE_DNI = 10
TERMIN_WYKONCZONE_DNI = 14


def klucz_tryb(stanowisko):
    """Tryb stanowiska: `stary` (pełna lista, bez bramki) albo `stol`."""
    return 'priorytety_tryb_' + stanowisko


def klucz_stol(stanowisko):
    """Liczba miejsc na stole stanowiska."""
    return 'priorytety_stol_' + stanowisko


def klucz_jednostka(stanowisko):
    """Jednostka kafla stanowiska: `pozycja` albo `zamowienie`."""
    return 'priorytety_jednostka_' + stanowisko


def klucz_limit(stanowisko):
    """Limit otwartych odłożeń stanowiska."""
    return 'priorytety_limit_odlozen_' + stanowisko


def klucz_blokady(stanowisko):
    """Wiersz `prod_config` blokowany FOR UPDATE przy pobieraniu na stół (jeden pobierający na stanowisko)."""
    return 'priorytety_blokada_' + stanowisko
