# -*- coding: utf-8 -*-
"""
Stanowiska w API tabletu kierownika hali (kontrakt: docs/api-mobile-kierownik.md §7.1, §7.2 i §7.5).

Same ZWYKŁE odczyty: bez blokad, bez zapisów, bez commitów i — przede wszystkim — BEZ dopełniania stołu. Stół
dopełnia wyłącznie `GET desk` tabletów stanowisk (CLAUDE.md, „Dopełnianie tylko w `GET desk`”): podgląd kierownika
nie może przesunąć cudzej pracy ani brać blokad stanowiska, zamówień i pozycji. Dlatego tu wołamy wyłącznie
`widok.stol_i_kolejka` (to samo co `stoly_panelu` + `kolejka_stanowiska`, ale jeden przebieg `_dane_stanowiska`) i
`statystyki_stanowisk` (też zwykłe odczyty), a nigdy `stol.*`.

Kafle przepisujemy z widoku pole po polu (te same nazwy co w monitorze i na tablecie stanowiska); DTO budujemy od
zera, z białej listy pól — nic spoza kontraktu nie wycieka.
"""
from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import get_local_now
from modules.production.priorytety.services import ustawienia, widok
from modules.production.services import statystyki_stanowisk, worker_stats_service
from modules.production.services.station_catalog import STATION_ORDER, station_label

logger = get_structured_logger('production.kierownik.stanowiska')

LIMIT_DOMYSLNY = 50
LIMIT_MAKSIMUM = widok.LIMIT_KOLEJKI_MAX

# Kolejność w „Kto teraz pracuje” (kontrakt §4.1, §7.5): stanowiska procesu, potem te poza procesem.
KOLEJNOSC_OBSADY = tuple(STATION_ORDER) + ('sawmill', 'verification', 'delivery', 'manager')

# Pola kafli widoku przepisywane 1:1 (kontrakt §7.2). Kafel pozycji i kafel zamówienia mają różne końcówki.
_POLA_WSPOLNE = ('order_id', 'numer', 'gwiazdki', 'szczebel', 'termin')
_POLA_POZYCJI = ('product_id', 'short_id', 'rozpoczete', 'dorobka', 'material', 'wymiary')
_POLA_ZAMOWIENIA = ('pozycji', 'sposob_dostawy_ustawiony')
_POLA_STOLU = ('pobrano', 'zrodlo', 'wyslal', 'wroci_przy_dopelnieniu')
_POLA_ODLOZONEGO = ('powod', 'powod_etykieta', 'notatka', 'odlozono', 'pracownik', 'pracownik_krotko')
_POLA_WIDMA = ('unit_key', 'order_id', 'numer', 'product_id', 'short_id', 'zrodlo', 'pobrano', 'odlozony', 'opis')
_POLA_NIEKOMPLETNEGO = ('order_id', 'numer', 'na_stanowisku', 'pozycji', 'brakuje')


class BladLimitu(ValueError):
    """Zły `limit` kolejki; komunikat jest zdaniem po polsku do pokazania (odpowiedź 400 `dane_niepoprawne`)."""


def wczytaj_limit(surowy):
    """`limit` z zapytania: brak → 50, inaczej liczba całkowita od 1 do 500 (`widok.LIMIT_KOLEJKI_MAX`)."""
    tekst = (surowy or '').strip()
    if not tekst:
        return LIMIT_DOMYSLNY
    try:
        limit = int(tekst)
    except ValueError:
        limit = 0
    if not 1 <= limit <= LIMIT_MAKSIMUM:
        raise BladLimitu(u'Parametr limit musi być liczbą od 1 do %d.' % LIMIT_MAKSIMUM)
    return limit


def _teraz():
    return get_local_now().replace(microsecond=0)


def _osoba_w_przegladzie(osoba):
    """Osoba przy stanowisku w §7.1 i §7.2: bez `pierwsze_dzis` (jak w przykładzie kontraktu)."""
    return {'id': osoba['id'], 'imie': osoba['imie'], 'nazwisko': osoba['nazwisko'], 'inicjaly': osoba['inicjaly'],
            'kolor': osoba['kolor'], 'od': osoba['od'], 'ostatnia_aktywnosc': osoba['ostatnia_aktywnosc'],
            'bezczynnosc_min': osoba['temu']}


def _osoba_pelna(osoba):
    """Osoba w „Kto teraz pracuje” (§7.5): jak w przeglądzie plus `pierwsze_dzis`."""
    wynik = _osoba_w_przegladzie(osoba)
    wynik['pierwsze_dzis'] = osoba['pierwsze_dzis']
    return wynik


def _obsada():
    """{kod stanowiska: [osoby]} z sesji otwartych dziś; czasy ISO i bezczynność w minutach (`temu`)."""
    return worker_stats_service.obsada_stanowisk(szczegoly=True)


def _przepisz(zrodlo, pola):
    return {pole: zrodlo[pole] for pole in pola}


def _pola_kafla(jednostka):
    return _POLA_WSPOLNE + (_POLA_ZAMOWIENIA if jednostka == 'zamowienie' else _POLA_POZYCJI)


def _kafel_kolejki(kafel, jednostka):
    return _przepisz(kafel, _pola_kafla(jednostka))


def _kafel_stolu(kafel, jednostka):
    return _przepisz(kafel, ('unit_key',) + _pola_kafla(jednostka) + _POLA_STOLU)


def _kafel_odlozony(kafel, jednostka):
    return _przepisz(kafel, ('unit_key',) + _pola_kafla(jednostka) + _POLA_STOLU + _POLA_ODLOZONEGO)


def _statystyki(kod, dzis, ma_stol, stol=None, kolejka=None):
    """
    Liczniki stanowiska (§7.1). Liczby dnia z jednej definicji z zakładką Stanowiska (`statystyki_stanowisk`),
    stół i kolejka z widoku. Lakiernia nie ma stołu: wszystkie jej oczekujące pozycje są „w kolejce dalej”.
    Gdy warstwa priorytetów padła (`stol` i `kolejka` to None, a `ma_stol` prawda), liczniki stołu są null:
    nie znamy ich, a zera udawałyby pusty stół.
    """
    liczby = statystyki_stanowisk.statystyki(kod, dzis)
    wynik = {
        'oczekuje': liczby['total_pending'],
        'ukonczono_dzis': liczby['today_completed'],
        'm3_dzis': round(liczby['today_volume'], 4),
    }
    if ma_stol and stol is None:
        wynik.update({
            'na_stole': None, 'miejsca': None, 'odlozone': None, 'limit_odlozen': None,
            'kolejka_dalej': None, 'widm': None, 'niekompletnych': None,
        })
    elif ma_stol:
        wynik.update({
            'na_stole': len(stol['stol']), 'miejsca': stol['miejsca'],
            'odlozone': len(stol['odlozone']), 'limit_odlozen': stol['limit_odlozen'],
            'kolejka_dalej': stol['kolejka_dalej'], 'widm': len(stol['widma']),
            'niekompletnych': len(kolejka['niekompletne']),
        })
    else:
        wynik.update({
            'na_stole': 0, 'miejsca': 0, 'odlozone': 0, 'limit_odlozen': 0,
            'kolejka_dalej': liczby['total_pending'], 'widm': 0, 'niekompletnych': 0,
        })
    return wynik


def _naglowek(kod, ma_stol, stol=None):
    """
    kod, nazwa, tryb, jednostka, ma_stol. Lakiernia: zawsze `stary` (jej stołu nie ma, `ustawienia` nie pytamy).
    Stanowisko ze stołem bez wiersza `stol` (warstwa priorytetów padła) ma `tryb` i `jednostka` null.
    """
    if ma_stol and stol is None:
        return {'kod': kod, 'nazwa': station_label(kod), 'tryb': None, 'jednostka': None, 'ma_stol': True}
    if ma_stol:
        return {'kod': kod, 'nazwa': station_label(kod), 'tryb': stol['tryb'], 'jednostka': stol['jednostka'],
                'ma_stol': True}
    return {'kod': kod, 'nazwa': station_label(kod), 'tryb': 'stary', 'jednostka': 'pozycja', 'ma_stol': False}


def _warstwa_priorytetow(funkcja, lagodnie, kod):
    """
    Wynik `funkcja()` (odczyt z warstwy priorytetów) albo `None`, gdy ta padła, a `lagodnie` jest prawdą. Tak samo jak
    zakładka Stanowiska w webie (`stations_api._priorytety_stanowisk`): wyjątek → rollback zepsutej migawki sesji,
    log i ekran bez stołu i kolejki zamiast 500. Rollback wolno robić WYŁĄCZNIE w czystym odczycie (GET po commicie
    `require_device_token`); w transakcji zapisu stołu cofnąłby sam zapis, więc tam `lagodnie=False` i wyjątek idzie
    dalej (dekorator idempotencji cofa całość i odpowiada błędem).
    """
    if not lagodnie:
        return funkcja()
    try:
        return funkcja()
    except Exception as e:
        db.session.rollback()
        logger.error('Kierownik: stół i kolejka stanowiska niedostępne', extra={'station': kod, 'error': str(e)})
        return None


def _stol_i_kolejka(kod, lagodnie):
    """(wiersz stołu, kolejka) jednego stanowiska z jednego przebiegu widoku; (None, None) po awarii (patrz wyżej)."""
    wynik = _warstwa_priorytetow(lambda: widok.stol_i_kolejka(kod, limit=LIMIT_MAKSIMUM), lagodnie, kod)
    return wynik if wynik is not None else (None, None)


def przeglad():
    """
    §7.1: przegląd 7 stanowisk (nagłówki, liczniki, obsada) bez list kafli, suma i czas wyliczenia. To czysty odczyt,
    więc awaria warstwy priorytetów jednego stanowiska nie psuje całego ekranu: ono dostaje `blad_priorytetow: true`
    i liczniki dnia (reszta stanowisk liczy się normalnie).
    """
    dzis = get_local_now().date()
    ludzie = _obsada()
    stanowiska = []
    for kod in STATION_ORDER:
        ma_stol = kod not in ustawienia.STANOWISKA_BEZ_STOLU
        stol, kolejka = _stol_i_kolejka(kod, lagodnie=True) if ma_stol else (None, None)
        wiersz = _naglowek(kod, ma_stol, stol)
        wiersz['statystyki'] = _statystyki(kod, dzis, ma_stol, stol, kolejka)
        wiersz['blad_priorytetow'] = ma_stol and stol is None
        wiersz['obsada'] = [_osoba_w_przegladzie(o) for o in ludzie.get(kod, [])]
        stanowiska.append(wiersz)
    suma = {
        'oczekuje': sum(s['statystyki']['oczekuje'] for s in stanowiska),
        'ukonczono_dzis': sum(s['statystyki']['ukonczono_dzis'] for s in stanowiska),
        'm3_dzis': round(sum(s['statystyki']['m3_dzis'] for s in stanowiska), 4),
        'odlozone': sum(s['statystyki']['odlozone'] or 0 for s in stanowiska),
    }
    return {'stanowiska': stanowiska, 'suma': suma, 'wyliczono': _teraz().isoformat()}


def pelne(kod, limit=LIMIT_DOMYSLNY, lagodnie=False):
    """
    §7.2: pełne stanowisko `kod` — stół, odłożone, widma, niekompletne i kolejka do `limit` kafli. Nieznany kod → None
    (odpowiedź 404 `stanowisko_nieznane`). Stół i kolejka z `widok.stol_i_kolejka` (jeden przebieg
    `_dane_stanowiska`; wartości te same co `widok.stoly_panelu` i `widok.kolejka_stanowiska`): ta sama definicja co
    zakładka Stanowiska i tablet. Widma: wszystkie trzy rodzaje, jak w panelu (pozycja już nie czeka, zamówienie bez
    pozycji na stanowisku, kafel innej jednostki).

    `lagodnie=True` (tylko `GET`, czysty odczyt): awaria warstwy priorytetów daje stanowisko z licznikami dnia,
    `blad_priorytetow: true` i pustymi listami zamiast wyjątku. Odpowiedzi zapisów stołu (liczone w transakcji pod
    blokadą stanowiska) wołają z `lagodnie=False`: rollback cofnąłby tam sam zapis.
    """
    if kod not in STATION_ORDER:
        return None
    dzis = get_local_now().date()
    osoby = [_osoba_w_przegladzie(o) for o in _obsada().get(kod, [])]

    if kod in ustawienia.STANOWISKA_BEZ_STOLU:
        wiersz = _naglowek(kod, False)
        wiersz['statystyki'] = _statystyki(kod, dzis, False)
        wiersz['obsada'] = osoby
        kafle = _warstwa_priorytetow(lambda: statystyki_stanowisk.lista_lakierni(dzis, limit), lagodnie, kod)
        wiersz['blad_priorytetow'] = kafle is None
        wiersz.update({
            'stol': [], 'odlozone': [], 'widma': [], 'niekompletne': [],
            # Lista Lakierni obejmuje wszystkie oczekujące pozycje, więc `lacznie` = licznik oczekujących.
            'kolejka': {'lacznie': wiersz['statystyki']['oczekuje'], 'kafle': kafle or []},
        })
        return wiersz

    stol, kolejka = _stol_i_kolejka(kod, lagodnie)
    if stol is None:
        wiersz = _naglowek(kod, True)
        wiersz['statystyki'] = _statystyki(kod, dzis, True)
        wiersz['blad_priorytetow'] = True
        wiersz['obsada'] = osoby
        wiersz.update({'stol': [], 'odlozone': [], 'widma': [], 'niekompletne': [],
                       'kolejka': {'lacznie': None, 'kafle': []}})
        return wiersz
    jednostka = stol['jednostka']
    wiersz = _naglowek(kod, True, stol)
    wiersz['statystyki'] = _statystyki(kod, dzis, True, stol, kolejka)
    wiersz['blad_priorytetow'] = False
    wiersz['obsada'] = osoby
    wiersz.update({
        'stol': [_kafel_stolu(k, jednostka) for k in stol['stol']],
        'odlozone': [_kafel_odlozony(k, jednostka) for k in stol['odlozone']],
        'widma': [_przepisz(w, _POLA_WIDMA) for w in stol['widma']],
        'niekompletne': [_przepisz(n, _POLA_NIEKOMPLETNEGO) for n in kolejka['niekompletne']],
        'kolejka': {'lacznie': kolejka['lacznie'],
                    'kafle': [_kafel_kolejki(k, jednostka) for k in kolejka['kafle'][:limit]]},
    })
    return wiersz


def obsada():
    """§7.5: „Kto teraz pracuje” — wszystkie stanowiska (także puste) w kolejności procesu, potem poza procesem."""
    ludzie = _obsada()
    stanowiska = [{'kod': kod, 'nazwa': station_label(kod),
                   'osoby': [_osoba_pelna(o) for o in ludzie.get(kod, [])]}
                  for kod in KOLEJNOSC_OBSADY]
    unikalne = {o['id'] for s in stanowiska for o in s['osoby']}
    return {'stanowiska': stanowiska, 'lacznie_osob': len(unikalne), 'wyliczono': _teraz().isoformat()}
