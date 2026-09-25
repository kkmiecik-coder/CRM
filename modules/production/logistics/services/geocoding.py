# -*- coding: utf-8 -*-
"""
Geokodowanie adresów dostawy (spec, sekcja 7.1).

Kolejność: GUGiK UUG (oficjalne punkty adresowe PRG, tylko PL) → Nominatim →
przybliżenie do miejscowości → „nie znaleziono”. Do usług wysyłamy WYŁĄCZNIE
adres. Pułapki zmierzone 24.09.2026: kod pocztowy albo numer mieszkania
w zapytaniu GUGiK daje 0 trafień albo zły budynek; „Bachórz, Bachórz 14N”
nic nie znajduje, a „Bachórz 14N” trafia.

Ten moduł woła usługi wyłącznie z wątku w tle (timeout gunicorna 30 s).
"""
import time
from collections import namedtuple

import requests

from modules.logging import get_structured_logger
from modules.production.logistics.adresy import (
    extract_house_and_apartment_number, usun_kod_pocztowy,
)

logger = get_structured_logger('production.logistics.geocoding')

MAGAZYN = {'lat': 49.840438, 'lng': 22.254053, 'nazwa': u'WoodPower — Bachórz 14N'}
GUGIK_URL = 'https://services.gugik.gov.pl/uug/'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'WoodPowerCRM/1.0 (+https://crm.woodpower.pl)'
TIMEOUT_S = 10
ODSTEP_NOMINATIM_S = 1.1
ODSTEP_GUGIK_S = 0.2
MIN_DOKLADNOSC_GUGIK = 0.6
# place_rank Nominatim: 30 = budynek, 28–29 = adres/obiekt, 26–27 = ulica, niżej obszar.
MIN_RANGA_DOKLADNA = 28

Wynik = namedtuple('Wynik', 'lat lng source quality')
NIE_ZNALEZIONO = Wynik(None, None, None, 'nie_znaleziono')


class BladUslugi(Exception):
    """Usługa nie odpowiedziała — to nie jest „nie znaleziono”, nie zużywa próby."""


def _naglowki():
    return {'User-Agent': USER_AGENT, 'Accept-Language': 'pl'}


def zapytania_gugik(adres, miasto):
    """Kandydaci zapytań do GUGiK (bez kodu i bez numeru mieszkania) oraz numer domu."""
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(usun_kod_pocztowy(adres))
    if not numer:
        return [], ''
    miasto = (miasto or '').strip()
    ulica = (ulica or '').strip()
    if not ulica or ulica.lower() == miasto.lower():
        # Miejscowość bez ulic: „Bachórz 14N”. Powtórzenie nazwy psuje wynik.
        return [u'{} {}'.format(miasto or ulica, numer)], numer
    if miasto:
        return [u'{}, {} {}'.format(miasto, ulica, numer)], numer
    return [u'{} {}'.format(ulica, numer)], numer


def _dokladnosc(trafienie):
    try:
        return float(trafienie.get('accuracy') or 0)
    except (TypeError, ValueError):
        return 0.0


def wybierz_trafienie(odpowiedz, numer, kod):
    """Trafienie z tym samym numerem: najpierw zgodny kod pocztowy, potem najwyższa dokładność."""
    if not odpowiedz or odpowiedz.get('type') != 'address':
        return None
    trafienia = list((odpowiedz.get('results') or {}).values())
    pasujace = [t for t in trafienia if (t.get('number') or '').lower() == (numer or '').lower()]
    if kod:
        z_kodem = [t for t in pasujace if t.get('code') == kod]
        if z_kodem:
            return z_kodem[0]
    pewne = [t for t in pasujace if _dokladnosc(t) >= MIN_DOKLADNOSC_GUGIK]
    return max(pewne, key=_dokladnosc) if pewne else None


def _gugik(zapytanie, http_get):
    odp = http_get(GUGIK_URL, params={'request': 'GetAddress', 'address': zapytanie, 'srid': '4326'},
                   timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    return odp.json() or {}


def _nominatim(parametry, http_get):
    """(lat, lng, dokładny) albo None."""
    params = {k: v for k, v in parametry.items() if v}
    params.update({'format': 'jsonv2', 'limit': 1})
    odp = http_get(NOMINATIM_URL, params=params, timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    dane = odp.json() or []
    if not dane:
        return None
    return (float(dane[0]['lat']), float(dane[0]['lon']),
            int(dane[0].get('place_rank') or 0) >= MIN_RANGA_DOKLADNA)


def geokoduj_adres(adres, miasto, kod, kraj, http_get=requests.get, spij=time.sleep):
    kraj = (kraj or 'PL').upper()
    miasto = (miasto or '').strip()
    kod = (kod or '').strip() or None
    awaria = False

    # 1. GUGiK — dokładny punkt adresowy (tylko Polska).
    if kraj == 'PL':
        kandydaci, numer = zapytania_gugik(adres, miasto)
        for zapytanie in kandydaci:
            spij(ODSTEP_GUGIK_S)
            try:
                trafienie = wybierz_trafienie(_gugik(zapytanie, http_get), numer, kod)
            except Exception as e:
                awaria = True
                logger.warning("GUGiK nie odpowiedzial", extra={'error': str(e)})
                continue
            if trafienie:
                return Wynik(float(trafienie['y']), float(trafienie['x']), 'gugik', 'dokladna')

    # 2. Nominatim — adres strukturalny. Wynik dokładny wracamy zawsze (nawet po
    # awarii GUGiK-a wyżej) — to wciąż najlepszy możliwy do zdobycia w tym wywołaniu.
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(usun_kod_pocztowy(adres))
    ulica_z_numerem = (u'{} {}'.format(ulica, numer) if numer else (ulica or '')).strip()
    if ulica_z_numerem:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'street': ulica_z_numerem, 'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            logger.warning("Nominatim nie odpowiedzial", extra={'error': str(e)})
        if punkt:
            if punkt[2]:
                return Wynik(punkt[0], punkt[1], 'nominatim', 'dokladna')
            if not awaria:
                return Wynik(punkt[0], punkt[1], 'nominatim', 'przyblizona')

    # R3 (kontroler): od tego miejsca może paść już tylko wynik PRZYBLIŻONY (krok 3)
    # albo brak wyniku. Jeśli po drodze padła już jakakolwiek usługa, takiego wyniku
    # NIE zapisujemy — automat cykliczny nie ponawia samych przybliżeń, więc chwilowa
    # awaria zdegradowałaby na trwałe adres, który przy sprawnym GUGiK-u dałoby się
    # przypiąć dokładnie. Kończymy od razu (mniej zapytań do Nominatim) — zamówienie
    # wróci do geokodowania w kolejnym przebiegu, bez zużywania próby.
    if awaria:
        raise BladUslugi(u'Usługa geokodowania nie odpowiedziała')

    # 3. Przybliżenie do miejscowości.
    if kraj == 'PL' and miasto:
        spij(ODSTEP_GUGIK_S)
        try:
            odp = _gugik(miasto, http_get)
            if odp.get('type') == 'city' and odp.get('results'):
                pierwszy = list(odp['results'].values())[0]
                return Wynik(float(pierwszy['y']), float(pierwszy['x']), 'gugik', 'przyblizona')
        except Exception as e:
            awaria = True
            logger.warning("GUGiK (miejscowosc) nie odpowiedzial", extra={'error': str(e)})
    if miasto or kod:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            logger.warning("Nominatim (miejscowosc) nie odpowiedzial", extra={'error': str(e)})
        if punkt:
            return Wynik(punkt[0], punkt[1], 'nominatim', 'przyblizona')

    if awaria:
        raise BladUslugi(u'Usługa geokodowania nie odpowiedziała')
    return NIE_ZNALEZIONO
