# -*- coding: utf-8 -*-
"""
Stanowiska w API tabletu kierownika hali (kontrakt: docs/api-mobile-kierownik.md §7.1, §7.2 i §7.5).

Same ZWYKŁE odczyty: bez blokad, bez zapisów, bez commitów i — przede wszystkim — BEZ dopełniania stołu. Stół
dopełnia wyłącznie `GET desk` tabletów stanowisk (CLAUDE.md, „Dopełnianie tylko w `GET desk`”): podgląd kierownika
nie może przesunąć cudzej pracy ani brać blokad stanowiska, zamówień i pozycji. Dlatego tu wołamy wyłącznie
`widok.stoly_panelu`, `widok.kolejka_stanowiska` i `statystyki_stanowisk` (też zwykłe odczyty), a nigdy `stol.*`.

Kafle przepisujemy z widoku pole po polu (te same nazwy co w monitorze i na tablecie stanowiska); DTO budujemy od
zera, z białej listy pól — nic spoza kontraktu nie wycieka.
"""
from modules.production.models import get_local_now
from modules.production.priorytety.services import ustawienia, widok
from modules.production.services import statystyki_stanowisk, worker_stats_service
from modules.production.services.station_catalog import STATION_ORDER, station_label

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
    """
    liczby = statystyki_stanowisk.statystyki(kod, dzis)
    wynik = {
        'oczekuje': liczby['total_pending'],
        'ukonczono_dzis': liczby['today_completed'],
        'm3_dzis': round(liczby['today_volume'], 4),
    }
    if ma_stol:
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
    """kod, nazwa, tryb, jednostka, ma_stol. Lakiernia: zawsze `stary` (jej stołu nie ma, `ustawienia` nie pytamy)."""
    if ma_stol:
        return {'kod': kod, 'nazwa': station_label(kod), 'tryb': stol['tryb'], 'jednostka': stol['jednostka'],
                'ma_stol': True}
    return {'kod': kod, 'nazwa': station_label(kod), 'tryb': 'stary', 'jednostka': 'pozycja', 'ma_stol': False}


def _stoly_i_kolejki():
    """
    ({kod: wiersz `widok.stoly_panelu`}, {kod: `widok.kolejka_stanowiska` ze wszystkimi niekompletnymi}) dla
    stanowisk ze stołem. Kolejka z limitem maksymalnym, żeby `niekompletne` było pełne (liczy je statystyka);
    wołający przycina kafle do własnego limitu.
    """
    stoly = {wiersz['stanowisko']: wiersz for wiersz in widok.stoly_panelu()}
    kolejki = {kod: widok.kolejka_stanowiska(kod, limit=LIMIT_MAKSIMUM) for kod in stoly}
    return stoly, kolejki


def przeglad():
    """§7.1: przegląd 7 stanowisk (nagłówki, liczniki, obsada) bez list kafli, suma i czas wyliczenia."""
    dzis = get_local_now().date()
    stoly, kolejki = _stoly_i_kolejki()
    ludzie = _obsada()
    stanowiska = []
    for kod in STATION_ORDER:
        stol = stoly.get(kod)
        ma_stol = stol is not None
        wiersz = _naglowek(kod, ma_stol, stol)
        wiersz['statystyki'] = _statystyki(kod, dzis, ma_stol, stol, kolejki.get(kod))
        wiersz['obsada'] = [_osoba_w_przegladzie(o) for o in ludzie.get(kod, [])]
        stanowiska.append(wiersz)
    suma = {
        'oczekuje': sum(s['statystyki']['oczekuje'] for s in stanowiska),
        'ukonczono_dzis': sum(s['statystyki']['ukonczono_dzis'] for s in stanowiska),
        'm3_dzis': round(sum(s['statystyki']['m3_dzis'] for s in stanowiska), 4),
        'odlozone': sum(s['statystyki']['odlozone'] for s in stanowiska),
    }
    return {'stanowiska': stanowiska, 'suma': suma, 'wyliczono': _teraz().isoformat()}


def pelne(kod, limit=LIMIT_DOMYSLNY):
    """
    §7.2: pełne stanowisko `kod` — stół, odłożone, widma, niekompletne i kolejka do `limit` kafli. Nieznany kod → None
    (odpowiedź 404 `stanowisko_nieznane`). Stół i kolejka z `widok.stoly_panelu` i `widok.kolejka_stanowiska`: ta sama
    definicja co zakładka Stanowiska i tablet. Widma: wszystkie trzy rodzaje, jak w panelu (pozycja już nie czeka,
    zamówienie bez pozycji na stanowisku, kafel innej jednostki).
    """
    if kod not in STATION_ORDER:
        return None
    dzis = get_local_now().date()
    osoby = [_osoba_w_przegladzie(o) for o in _obsada().get(kod, [])]

    if kod in ustawienia.STANOWISKA_BEZ_STOLU:
        wiersz = _naglowek(kod, False)
        wiersz['statystyki'] = _statystyki(kod, dzis, False)
        wiersz['obsada'] = osoby
        wiersz.update({
            'stol': [], 'odlozone': [], 'widma': [], 'niekompletne': [],
            # Lista Lakierni obejmuje wszystkie oczekujące pozycje, więc `lacznie` = licznik oczekujących.
            'kolejka': {'lacznie': wiersz['statystyki']['oczekuje'],
                        'kafle': statystyki_stanowisk.lista_lakierni(dzis, limit)},
        })
        return wiersz

    stol = widok.stoly_panelu([kod])[0]
    kolejka = widok.kolejka_stanowiska(kod, limit=LIMIT_MAKSIMUM)
    jednostka = stol['jednostka']
    wiersz = _naglowek(kod, True, stol)
    wiersz['statystyki'] = _statystyki(kod, dzis, True, stol, kolejka)
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
