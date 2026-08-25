# -*- coding: utf-8 -*-
"""
Agregat dziennego raportu produkcji.

Zasada nadrzędna: NIE liczymy tu niczego, co panel już liczy. Każda metryka,
która ma odpowiednik na ekranie, pochodzi z tej samej funkcji co on — inaczej
mail i panel prędzej czy później pokażą dwie różne liczby na to samo pytanie,
a wtedy nikt nie będzie wiedział, której wierzyć.

Nowe zapytania powstają wyłącznie tam, gdzie panel nie ma odpowiednika:
kolejki w sztukach, cofnięcia, liczba zdarzeń per pracownik i trakownia.

Zero Flaska (jak reports_service) — serwis ma być wołany zarówno z komendy
CLI, jak i z testu bez kontekstu żądania.
"""

from datetime import date, datetime, time

from sqlalchemy import func

from extensions import db
from ..models import (
    ProductionOrder, ProductionProduct, ProductionStationEvent,
    ProductionStationEventWorker, get_local_now,
)
from .reports_service import _koszyk_terminu
from .station_catalog import (
    STATION_LABELS, STATION_ORDER, STATION_PENDING_STATUS,
)
from .station_events_service import ZRODLA_AUTOMATU, get_station_work_per_day
from .worker_stats_service import raport_wydajnosci


def _granice_doby(dzien):
    """
    (początek, koniec) doby jako naive datetime w czasie lokalnym.

    Ta sama konwencja co worker_stats_service.granice_zakresu(): koniec to
    23:59:59.999999, więc zdarzenie z ostatniej sekundy dnia jeszcze się łapie.
    """
    return (datetime.combine(dzien, time.min),
            datetime.combine(dzien, time.max))


# Statusy, które nie są zaległością: praca skończona albo odwołana.
# 'wstrzymane' NIE jest tu celowo — panel (reports_service.STATUSY_ZAMKNIETE:116)
# wyklucza tylko te dwa i trzyma wstrzymane jako osobny segment, żeby wstrzymana
# pozycja po terminie była widoczna. Mail ma pokazywać to samo co panel.
_STATUSY_POZA_BACKLOGIEM = ('spakowane', 'anulowane')


def _cofniecia_stanowisk(dzien):
    """
    {kod_stanowiska: liczba cofniętych sztuk} — wartość DODATNIA.

    Osobne zapytanie, bo panel nie ma odpowiednika: get_station_work_per_day()
    zwraca wyłącznie netto, w którym cofnięcia są niewidoczne.
    """
    poczatek, koniec = _granice_doby(dzien)

    wiersze = db.session.query(
        ProductionStationEvent.station_code,
        func.sum(ProductionStationEvent.delta),
    ).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ProductionStationEvent.delta < 0,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).group_by(ProductionStationEvent.station_code).all()

    return {kod: abs(int(suma or 0)) for kod, suma in wiersze}


def _kolejki_stanowisk():
    """
    {kod_stanowiska: {'sztuki': int, 'm3': float}} — stan na TERAZ.

    Definicja 1:1 z panelem (reports_service.dni_zapasu_stanowisk:313-321):
    pozycja czeka jako całość, z pełnym quantity, także wtedy gdy jest
    w połowie zrobiona. To zawyża kolejkę i jest świadome — dashboard liczy
    tak samo, a dwie różne definicje kolejki byłyby gorsze niż jedna
    niedoskonała.
    """
    wiersze = db.session.query(
        ProductionProduct.current_status,
        func.coalesce(func.sum(ProductionProduct.quantity), 0),
        func.coalesce(func.sum(func.coalesce(ProductionProduct.volume_m3, 0)
                               * ProductionProduct.quantity), 0),
    ).filter(
        ProductionProduct.current_status.in_(list(STATION_PENDING_STATUS.values()))
    ).group_by(ProductionProduct.current_status).all()

    po_statusie = {status: (int(szt or 0), float(m3 or 0))
                   for status, szt, m3 in wiersze}

    wynik = {}
    for kod, status_kolejki in STATION_PENDING_STATUS.items():
        sztuki, metry = po_statusie.get(status_kolejki, (0, 0.0))
        wynik[kod] = {'sztuki': sztuki, 'm3': metry}
    return wynik


def _koszyki_terminow(dzien):
    """
    Liczba pozycji w każdym koszyku terminu — to, co ZOSTAŁO do zrobienia.

    Koszyki liczy _koszyk_terminu() z reports_service, ta sama funkcja co
    wykres „Termin vs postęp". Dwie kopie tej definicji (jedna w SQL, druga
    w Pythonie) rozjechałyby się na granicy „dziś" — ostrzega o tym wprost
    docstring tamtej funkcji.
    """
    koszyki = {'po_terminie': 0, 'dzis': 0, '1_2_dni': 0,
               '3_7_dni': 0, '8_dni_plus': 0, 'bez_terminu': 0}

    terminy = db.session.query(ProductionProduct.deadline_date).filter(
        ~ProductionProduct.current_status.in_(_STATUSY_POZA_BACKLOGIEM)
    ).all()

    for (deadline,) in terminy:
        koszyki[_koszyk_terminu(deadline, dzien)] += 1

    return koszyki


def _przerob_stanowisk(dzien, cofniecia, kolejki):
    """
    Sztuki, m³ i wartość netto per stanowisko za jeden dzień, wzbogacone
    o cofnięcia i stan kolejki.

    get_station_work_per_day() zwraca komplet trzech liczb w jednym zapytaniu
    i ma już w środku filtr źródeł oraz wzór wartości (total_value_net * delta
    / quantity). Wołamy je siedem razy, po jednym na stanowisko — przy jednym
    przebiegu dziennie koszt jest bez znaczenia, a alternatywą byłoby
    przepisanie tych samych trzech sum drugi raz.
    """
    wynik = []
    for kod in STATION_ORDER:
        dzienne = get_station_work_per_day(kod, dzien, dzien).get(dzien, {})
        kolejka = kolejki.get(kod, {'sztuki': 0, 'm3': 0.0})
        wynik.append({
            'kod': kod,
            'etykieta': STATION_LABELS[kod],
            'sztuki': int(dzienne.get('pieces', 0) or 0),
            'm3': float(dzienne.get('m3', 0) or 0),
            'wartosc_netto': float(dzienne.get('value_net', 0) or 0),
            'cofniecia': cofniecia.get(kod, 0),
            'kolejka_szt': kolejka['sztuki'],
            'kolejka_m3': kolejka['m3'],
        })
    return wynik


def _zdarzenia_pracownikow(dzien):
    """
    {worker_id: liczba zdarzeń} za dobę.

    raport_wydajnosci() podaje liczbę zdarzeń wyłącznie zbiorczo (klucz
    summary.station_events), a arkusz „Ludzie" ma kolumnę per osoba — stąd
    osobne zapytanie. Liczy ZDARZENIA, nie sumę delt: doba, w której tyle
    samo odhaczono co cofnięto, ma netto zero, a pracowano.
    """
    poczatek, koniec = _granice_doby(dzien)

    wiersze = db.session.query(
        ProductionStationEventWorker.worker_id,
        func.count(ProductionStationEvent.id),
    ).join(
        ProductionStationEvent,
        ProductionStationEvent.id == ProductionStationEventWorker.event_id,
    ).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).group_by(ProductionStationEventWorker.worker_id).all()

    return {wid: int(ile or 0) for wid, ile in wiersze}


def _zasieg_dnia(dzien):
    """
    (liczba pozycji, liczba zamówień) dotkniętych w ciągu doby.

    Świadomie liczymy POZYCJE DOTKNIĘTE, a nie „pozycje z dodatnim netto"
    jak get_station_work_in_range(): tamta funkcja działa w obrębie jednego
    stanowiska, a netto liczone globalnie przez wszystkie stanowiska naraz
    nie ma sensownej interpretacji. „Dotknięta" znaczy: było przy niej
    przynajmniej jedno zdarzenie człowieka.
    """
    poczatek, koniec = _granice_doby(dzien)

    return db.session.query(
        func.count(func.distinct(ProductionStationEvent.production_item_id)),
        func.count(func.distinct(ProductionOrder.baselinker_order_id)),
    ).join(
        ProductionProduct,
        ProductionProduct.id == ProductionStationEvent.production_item_id,
    ).join(
        ProductionOrder, ProductionOrder.id == ProductionProduct.order_id,
    ).filter(
        ProductionStationEvent.created_at >= poczatek,
        ProductionStationEvent.created_at <= koniec,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).one()


def _ludzie(dzien):
    """
    Wiersze arkusza „Ludzie" plus liczby zbiorcze.

    Wszystko poza kolumną „Zdarzenia" pochodzi z raport_wydajnosci() — tej
    samej funkcji, która zasila zakładkę „Pracownicy" w panelu.

    `tempo` zostaje None dla pracownika bez atrybucji: arkusz pokaże pustą
    komórkę, nie zero. Zero przy nazwisku człowieka, o którym raport nic nie
    wie, byłoby zarzutem bezczynności postawionym z braku danych.
    """
    raport = raport_wydajnosci(dzien, dzien)
    zdarzenia = _zdarzenia_pracownikow(dzien)

    wiersze = [{
        'nazwa': w['worker_name'],
        'stanowiska': ', '.join(w['stations']),
        'sztuki': w['pieces'],
        'm3': w['m3'],
        'zdarzenia': zdarzenia.get(w['worker_id'], 0),
        'godziny': w['hours'],
        'tempo': w['pace_m3_per_hour'],
    } for w in raport['worker_totals']]

    podsumowanie = raport['summary']
    return {
        'osoby': podsumowanie['workers_count'],
        'godziny': podsumowanie['hours'],
        'pokrycie_proc': podsumowanie['attribution_coverage_pct'],
        'wiersze': wiersze,
        'nieprzypisane': {
            'sztuki': podsumowanie['unassigned_pieces'],
            'm3': podsumowanie['unassigned_m3'],
        },
    }


def _wykonanie(stanowiska, dzien):
    """Sumy nagłówkowe — składane z policzonych już wierszy stanowisk."""
    pozycje, zamowienia = _zasieg_dnia(dzien)
    return {
        'sztuki': sum(s['sztuki'] for s in stanowiska),
        'm3': sum(s['m3'] for s in stanowiska),
        'wartosc_netto': sum(s['wartosc_netto'] for s in stanowiska),
        'cofniecia': sum(s['cofniecia'] for s in stanowiska),
        'pozycje': int(pozycje or 0),
        'zamowienia': int(zamowienia or 0),
    }


def zbierz_dane(dzien=None):
    """
    Komplet danych dziennego raportu jako czysty dict.

    Args:
        dzien: date. Domyślnie dziś (czas lokalny) — raport idzie o 18:00
               tego samego dnia, kiedy doba produkcyjna jest już zamknięta.

    Returns:
        dict o stabilnym kształcie — kontrakt dla daily_report_export
        i report_mailer, które NIE sięgają po dane samodzielnie.
    """
    dzien = dzien or get_local_now().date()

    stanowiska = _przerob_stanowisk(dzien, _cofniecia_stanowisk(dzien),
                                    _kolejki_stanowisk())

    return {
        'dzien': dzien,
        'wykonanie': _wykonanie(stanowiska, dzien),
        'ludzie': _ludzie(dzien),
        'stanowiska': stanowiska,
        'terminy': _koszyki_terminow(dzien),
    }
