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

from ..models import get_local_now
from .station_catalog import STATION_LABELS, STATION_ORDER
from .station_events_service import get_station_work_per_day


def _granice_doby(dzien):
    """
    (początek, koniec) doby jako naive datetime w czasie lokalnym.

    Ta sama konwencja co worker_stats_service.granice_zakresu(): koniec to
    23:59:59.999999, więc zdarzenie z ostatniej sekundy dnia jeszcze się łapie.
    """
    return (datetime.combine(dzien, time.min),
            datetime.combine(dzien, time.max))


def _przerob_stanowisk(dzien):
    """
    Sztuki, m³ i wartość netto per stanowisko za jeden dzień.

    get_station_work_per_day() zwraca komplet trzech liczb w jednym zapytaniu
    i ma już w środku filtr źródeł oraz wzór wartości (total_value_net * delta
    / quantity). Wołamy je siedem razy, po jednym na stanowisko — przy jednym
    przebiegu dziennie koszt jest bez znaczenia, a alternatywą byłoby
    przepisanie tych samych trzech sum drugi raz.
    """
    wynik = []
    for kod in STATION_ORDER:
        dzienne = get_station_work_per_day(kod, dzien, dzien).get(dzien, {})
        wynik.append({
            'kod': kod,
            'etykieta': STATION_LABELS[kod],
            'sztuki': int(dzienne.get('pieces', 0) or 0),
            'm3': float(dzienne.get('m3', 0) or 0),
            'wartosc_netto': float(dzienne.get('value_net', 0) or 0),
            # Wypełniane przez kolejne kroki agregatu.
            'cofniecia': 0,
            'kolejka_szt': None,
            'kolejka_m3': None,
        })
    return wynik


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

    return {
        'dzien': dzien,
        'stanowiska': _przerob_stanowisk(dzien),
    }
