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
from datetime import date

from modules.production.kierownik.services import zamowienia as zam
from modules.production.models import get_local_now
from modules.production.services import daily_report_service as dzienny
from modules.production.services import reports_service
from modules.production.services.station_catalog import station_label

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
    }
