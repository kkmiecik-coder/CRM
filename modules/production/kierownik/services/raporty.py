# -*- coding: utf-8 -*-
"""
Raporty na tablecie kierownika hali (kontrakt: docs/api-mobile-kierownik.md §8.5, §8.6 i §8.7).

CZYSTE ODCZYTY: bez blokad i bez commitów (jedyny zapis żądania to znacznik kontaktu urządzenia w
`require_device_token`). Wszystkie trzy raporty mają wspólny zakres dat (`zakres`): oba końce albo żaden, domyślnie
dziś, włącznie, najwyżej 92 dni.

Liczby biorą się z tych samych funkcji co raport dzienny i zakładki panelu, żeby tablet i panel nie pokazywały dwóch
różnych odpowiedzi na to samo pytanie. DTO budujemy od zera, pole po polu; liczymy w serwisach także wartość netto
(żywi XLSX raportu dziennego), ale tutaj nie wychodzi żadna kwota (kontrakt §11).

DANE SĄ ORIENTACYJNE tam, gdzie wchodzi pracownik: profil na tablecie wybiera się bez PIN-u, więc podpis pod pracą
nie jest dowodem.
"""
import re
from datetime import date, timedelta

from sqlalchemy import func

from extensions import db
from modules.production.kierownik.services import zamowienia as zam
from modules.production.models import ProductionProduct, get_local_now
from modules.production.services import daily_report_service as dzienny
from modules.production.services import reports_service, station_events_service, worker_stats_service
from modules.production.services.reports_service import STANOWISKO_LAKIERNI
from modules.production.services.station_catalog import STATION_ORDER, resolve_station_code, station_label

# Najdłuższy zakres raportów w dniach (obie granice włącznie).
MAKS_ZAKRES_DNI = 92

_WZORZEC_DATY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class BladZakresu(ValueError):
    """Zły zakres dat; komunikat jest zdaniem po polsku do pokazania (odpowiedź 400 `zakres_niepoprawny`)."""


class BladParametru(zam.BladParametru):
    """Zły parametr raportu inny niż zakres (np. nieznane `station`); odpowiedź 400 `dane_niepoprawne`."""


# ── zakres ───────────────────────────────────────────────────────────────────────────────────────────────────

def _data(surowa, nazwa):
    """Data `RRRR-MM-DD` (ściśle, z zerami) albo `BladZakresu`."""
    if not _WZORZEC_DATY.match(surowa):
        raise BladZakresu(u'Parametr %s musi być datą w formacie RRRR-MM-DD.' % nazwa)
    try:
        return date(int(surowa[:4]), int(surowa[5:7]), int(surowa[8:10]))
    except ValueError:
        raise BladZakresu(u'Parametr %s nie jest prawdziwą datą.' % nazwa)


def zakres(args):
    """
    (start, koniec) z `start_date` i `end_date` zapytania (`request.args`), obie granice włącznie.

    Oba parametry albo żaden: bez nich zakres to dziś–dziś (czas lokalny). Podanie jednego z nich, zły format, start
    późniejszy niż koniec albo zakres dłuższy niż `MAKS_ZAKRES_DNI` dni to `BladZakresu`. Daty z przyszłości
    przechodzą (raport pokaże same zera), bo to nie jest błąd tabletu.
    """
    surowy_start = (args.get('start_date') or '').strip()
    surowy_koniec = (args.get('end_date') or '').strip()
    if not surowy_start and not surowy_koniec:
        dzis = get_local_now().date()
        return dzis, dzis
    if not surowy_start or not surowy_koniec:
        raise BladZakresu(u'Podaj obie daty zakresu (start_date i end_date) albo żadnej.')
    start, koniec = _data(surowy_start, 'start_date'), _data(surowy_koniec, 'end_date')
    if start > koniec:
        raise BladZakresu(u'Data start_date nie może być późniejsza niż end_date.')
    if (koniec - start).days + 1 > MAKS_ZAKRES_DNI:
        raise BladZakresu(u'Zakres raportu to najwyżej %d dni.' % MAKS_ZAKRES_DNI)
    return start, koniec


def _m3(wartosc):
    """m³ w DTO: zaokrąglone do 4 miejsc (kontrakt §2)."""
    return round(float(wartosc or 0), 4)


def _wstrzymane():
    """
    {pozycji, sztuki, m3} pozycji w statusie `wstrzymane`, stan TERAZ (niezależny od zakresu dat).

    Wstrzymana pozycja nie stoi w kolejce żadnego stanowiska (`STATION_PENDING_STATUS` nie ma dla niej wpisu), więc
    nie wchodzi do `kolejka_*`; tu wychodzi osobno, żeby łączna niespakowana praca dała się zsumować
    z kolejkami stanowisk. Wzór m³ jak w kolejce: `volume_m3 * quantity`, pusta objętość to 0.
    """
    pozycji, sztuki, m3 = db.session.query(
        func.count(ProductionProduct.id),
        func.coalesce(func.sum(ProductionProduct.quantity), 0),
        func.coalesce(func.sum(func.coalesce(ProductionProduct.volume_m3, 0) * ProductionProduct.quantity), 0),
    ).filter(ProductionProduct.current_status == 'wstrzymane').one()
    return {'pozycji': int(pozycji or 0), 'sztuki': int(sztuki or 0), 'm3': _m3(m3)}


# ── przerób stanowisk (§8.5) ─────────────────────────────────────────────────────────────────────────────────

def _dni_zapasu():
    """
    {kod: dni zapasu} z tej samej funkcji co wykres panelu `Dni zapasu przed stanowiskiem`
    (`reports_service.dni_zapasu_stanowisk`): kolejka STAN TERAZ dzielona przez średni dzienny przerób z ostatnich
    14 dni roboczych hali, niezależnie od zakresu raportu. Stanowisko z kolejką i bez przerobu w oknie dostaje
    `None` (brak danych, nie nieskończoność), a hala bez żadnych dni roboczych — `None` dla wszystkich.
    """
    return {s['station_code']: s['days_of_supply'] for s in reports_service.dni_zapasu_stanowisk()['stations']}


def stanowiska(start, end):
    """
    §8.5: przerób stanowisk w zakresie `start`..`end` (włącznie) plus `hala`, `zakonczone` i `trakownia`.

    Liczy z helperów raportu dziennego (`daily_report_service`), uogólnionych z doby na zakres, więc jeden dzień daje
    dokładnie te same liczby co XLSX. Ważne dla czytającego:

    - `sztuki` i `m3` stanowiska to praca LUDZI, netto po cofnięciach, bez automatycznych przejść (`auto_skip`,
      `system`);
    - `zamowien` i `pozycji` stanowiska NIE sumują się do `hala`: jedno zamówienie przechodzi przez kilka
      stanowisk, a unikaty liczy wyłącznie `hala`;
    - `hala.sztuki` i `hala.m3` sumują wszystkie stanowiska, więc ta sama sztuka, która przeszła pięć stanowisk,
      liczy się pięć razy. To miara ruchu na hali, NIE wynik zakresu; wynik (co zeszło z produkcji) to
      `zakonczone`, czyli Pakowanie, gdzie sztuka liczy się raz;
    - trakownia mierzy surowiec przed produkcją, więc stoi osobno i nie wchodzi do `hala`;
    - `wstrzymane` ({pozycji, sztuki, m3}) to stan TERAZ pozycji w statusie `wstrzymane`: nie stoją w kolejce żadnego
      stanowiska, więc nie ma ich w `kolejka_*`;
    - `kolejka_szt`, `kolejka_m3` i `dni_zapasu` to stan TERAZ, niezależny od zakresu;
    - `wartosc_netto` liczy się dla XLSX, ale tu nie wychodzi.
    """
    poczatek, koniec = dzienny.granice_zakresu(start, end)
    przerob = dzienny._przerob_stanowisk(
        poczatek, koniec, dzienny._cofniecia_stanowisk(poczatek, koniec), dzienny._kolejki_stanowisk(),
        dzienny._zamowienia_stanowisk(poczatek, koniec))
    pozycje = dzienny._pozycje_stanowisk(poczatek, koniec)
    zapas = _dni_zapasu()
    wykonanie = dzienny._wykonanie(przerob, poczatek, koniec)
    zakonczone = dzienny._zakonczone(przerob)
    trakownia = dzienny._trakownia(poczatek, koniec)
    return {
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'stanowiska': [{
            'kod': s['kod'],
            'nazwa': station_label(s['kod']),
            'sztuki': s['sztuki'],
            'm3': _m3(s['m3']),
            'pozycji': pozycje.get(s['kod'], 0),
            'zamowien': s['zamowienia'],
            'cofniecia': s['cofniecia'],
            'kolejka_szt': s['kolejka_szt'],
            'kolejka_m3': _m3(s['kolejka_m3']),
            'dni_zapasu': zapas.get(s['kod']),
        } for s in przerob],
        'hala': {
            'sztuki': wykonanie['sztuki'],
            'm3': _m3(wykonanie['m3']),
            'pozycji': wykonanie['pozycje'],
            'zamowien': wykonanie['zamowienia'],
            'cofniecia': wykonanie['cofniecia'],
        },
        'zakonczone': {'sztuki': zakonczone['sztuki'], 'm3': _m3(zakonczone['m3'])},
        'trakownia': {'klody': trakownia['klody'], 'm3': _m3(trakownia['m3'])},
        'wstrzymane': _wstrzymane(),
    }


# ── wydajność pracowników (§8.6) ─────────────────────────────────────────────────────────────────────────────

def _kolejnosc_procesu(kod):
    """Klucz sortowania kodów stanowisk: kolejność procesu, nieznane kody na końcu."""
    return STATION_ORDER.index(kod) if kod in STATION_ORDER else len(STATION_ORDER)


def pracownicy(start, end, station=None):
    """
    §8.6: wydajność pracowników w zakresie `start`..`end` (włącznie), opcjonalnie na jednym stanowisku procesu.

    Zły `station` (spoza `STATION_ORDER`) to `BladParametru` (400 `dane_niepoprawne`). Liczby pochodzą z
    `worker_stats_service.raport_wydajnosci`, czyli z tej samej funkcji co zakładka „Pracownicy" w panelu i arkusz
    „Ludzie" raportu dziennego. Ważne dla czytającego:

    - `sztuki` i `m3` to UDZIAŁ pracownika: przy pracy zespołowej (N osób na jednym zdarzeniu) każdy dostaje 1/N, stąd
      ułamki; `nieprzypisane` to praca bez wybranego profilu na tablecie;
    - `godziny` to OBECNOŚĆ, czyli suma wszystkich sesji pracownika (także kierownika i trakowni); otwarta sesja liczy
      się do teraz, najwyżej do limitu bezczynności i godziny nocnego zamknięcia;
    - `m2` ({olejowane, lakierowane}) ma tylko pracownik z pracą na Lakierni; to jej właściwa jednostka;
    - `tempo_m3_h` dzieli m³ przez godziny z sesji na stanowiskach procesu, więc sesja kierownika albo trakowni go nie
      zaniża; to `None` (nie zero), gdy pracownik nie ma przypisanej pracy albo ani minuty na stanowisku procesu;
    - tempa NIE porównujemy między stanowiskami: m³ na różnych stanowiskach to różna praca, dlatego lista jest po
      nazwisku, a nie po wydajności;
    - dane są orientacyjne, bo profil na tablecie wybiera się bez PIN-u (`pokrycie_atrybucji_proc` mówi, ile pracy ma
      podpis).
    """
    stanowisko = (station or '').strip() or None
    if stanowisko is not None and stanowisko not in STATION_ORDER:
        raise BladParametru(u'Nieznane stanowisko: %s.' % stanowisko)
    raport = worker_stats_service.raport_wydajnosci(start, end, stanowisko)

    # Praca wg stanowisk z wierszy dzień × pracownik × stanowisko (po kodach; `stations` w sumach to etykiety).
    wg_stanowisk = {}
    for wiersz in raport['rows']:
        kod = resolve_station_code(wiersz['station_code'])
        suma = wg_stanowisk.setdefault(wiersz['worker_id'], {}).setdefault(kod, [0.0, 0.0])
        suma[0] += wiersz['pieces']
        suma[1] += wiersz['m3']

    ludzie = []
    for w in raport['worker_totals']:
        praca = wg_stanowisk.get(w['worker_id'], {})
        kody = sorted(praca, key=_kolejnosc_procesu)
        wpis = {
            'id': w['worker_id'],
            'nazwa': w['worker_name'],
            'sztuki': w['pieces'],
            'm3': _m3(w['m3']),
            'godziny': w['hours'],
            'tempo_m3_h': w['pace_m3_per_hour'],
            'stanowiska': kody,
            'otwarta_sesja': w['open_sessions'] > 0,
            'wg_stanowisk': [{'stanowisko': kod, 'sztuki': round(praca[kod][0], 2), 'm3': _m3(praca[kod][1])}
                             for kod in kody],
        }
        # Lakiernia mierzy robotę w m2, nie w m3. Klucz tylko dla pracownika z pracą na Lakierni (jak `m2` w wierszu
        # Lakierni panelu); mapa nazw: serwis `painting_m2` {oiled, lacquered} -> {olejowane, lakierowane}.
        if STANOWISKO_LAKIERNI in praca:
            wpis['m2'] = {'olejowane': w['painting_m2']['oiled'], 'lakierowane': w['painting_m2']['lacquered']}
        ludzie.append(wpis)

    podsumowanie = raport['summary']
    return {
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'station': stanowisko,
        'pracownicy': ludzie,
        'nieprzypisane': {'sztuki': podsumowanie['unassigned_pieces'], 'm3': _m3(podsumowanie['unassigned_m3'])},
        'podsumowanie': {
            'osoby': podsumowanie['workers_count'],
            'godziny': podsumowanie['hours'],
            'sztuki': podsumowanie['pieces'],
            'm3': _m3(podsumowanie['m3']),
            'pokrycie_atrybucji_proc': podsumowanie['attribution_coverage_pct'],
        },
    }


# ── przerób dzień po dniu (§8.7) ─────────────────────────────────────────────────────────────────────────────

def dzien_po_dniu(start, end):
    """
    §8.7: przerób dzień po dniu w zakresie `start`..`end` (włącznie). Lista ma KAŻDY dzień zakresu, także dni bez pracy
    (zera), a `stanowiska` klucze wszystkich 7 stanowisk procesu.

    Źródło to `station_events_service.get_station_work_per_day` (siedem zapytań, po jednym na stanowisko; ta sama
    funkcja, która żywi raport dzienny), więc to praca ludzi netto po cofnięciach, bez automatycznych przejść.
    `value_net` tej funkcji nie wychodzi (kontrakt §11).

    UWAGA dla czytającego: `sztuki` i `m3` dnia SUMUJĄ stanowiska, więc sztuka, która tego dnia przeszła pięć
    stanowisk, liczy się pięć razy. To miara ruchu na hali, nie wynik dnia; wynik (co zeszło z produkcji) to
    `zakonczone_m3`, czyli Pakowanie, gdzie sztuka liczy się raz.
    """
    praca = {kod: station_events_service.get_station_work_per_day(kod, start, end) for kod in STATION_ORDER}
    dni = []
    for przesuniecie in range((end - start).days + 1):
        dzien = start + timedelta(days=przesuniecie)
        stanowiska = {}
        for kod in STATION_ORDER:
            wpis = praca[kod].get(dzien) or {}
            stanowiska[kod] = {'sztuki': int(wpis.get('pieces', 0) or 0), 'm3': float(wpis.get('m3', 0) or 0)}
        dni.append({
            'data': dzien.isoformat(),
            'sztuki': sum(s['sztuki'] for s in stanowiska.values()),
            'm3': _m3(sum(s['m3'] for s in stanowiska.values())),
            'zakonczone_m3': _m3(stanowiska['packaging']['m3']),
            'stanowiska': {kod: {'sztuki': s['sztuki'], 'm3': _m3(s['m3'])} for kod, s in stanowiska.items()},
        })
    return {'start_date': start.isoformat(), 'end_date': end.isoformat(), 'dni': dni}
