# -*- coding: utf-8 -*-
"""
Przebieg trasy po drogach — OpenRouteService (spec 8.2).

Magazyn → przystanki w kolejności → magazyn. Klucz OPENROUTESERVICE_API_KEY
z config/core.json (bez wartości domyślnej). Brak klucza, błąd, przystanek
bez współrzędnych albo za dużo punktów → linie proste, odległość w linii
prostej, czas nieznany, geometry_approx = True. Jedno zapytanie na zapis
trasy, z limitem czasu TIMEOUT_S (limit gunicorna 30 s).

Cache (geometry_hash) — (I2) skrót zależy od tego, DLACZEGO wyszły linie proste:
- przebieg dokładny i przybliżenia „strukturalne” (przystanek bez współrzędnych,
  więcej niż MAKS_PRZYSTANKOW, brak punktów) — zwykły skrót punktów: póki punkty
  się nie zmienią, liczyć nie ma czego;
- brak klucza — skrót z dopiskiem „bez klucza”: gdy klucz się pojawi, pierwsze
  otwarcie trasy przeliczy ją po drogach (bez klucza nic nie kosztuje);
- błąd ORS — skrót z dopiskiem godziny błędu: trasa próbuje znów najwyżej raz na
  godzinę, więc awaria ORS nie kosztuje 8 s przy każdym otwarciu trasy.
"""
import hashlib
import json

import requests
from flask import current_app

from modules.logging import get_structured_logger
from modules.production.logistics.services import delivery, routes
from modules.production.logistics.services.geocoding import MAGAZYN, odleglosc_km  # noqa: F401
from modules.production.models import get_local_now

logger = get_structured_logger('production.logistics.routing')

ORS_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'
# (M12) (połączenie, odczyt) — sama liczba dotyczyłaby każdego z nich osobno; połączenie
# ograniczamy mocniej, bo przy niedostępnym ORS to ono wisi.
TIMEOUT_S = (3.05, 8)
MAKS_PRZYSTANKOW = 48  # ORS: do 50 punktów, dwa zajmuje magazyn

# Ostrzezenie o braku klucza ORS najwyzej raz na proces (modul-poziom
# flaga) — brak klucza degraduje trasy do linii prostych, ale mapa dalej
# pracuje, wiec to WARNING (nie CRITICAL).
_klucz_ors_ostrzezono = False


def klucz_ors():
    klucz = current_app.config.get('OPENROUTESERVICE_API_KEY')
    return klucz.strip() if isinstance(klucz, str) and klucz.strip() else None


def skrot_przebiegu(punkty):
    tekst = json.dumps([[round(p[0], 6), round(p[1], 6)] for p in punkty])
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _sha1(tekst):
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _punkty(route, punkty_zamowien):
    """[(lat, lng)] magazyn → przystanki z współrzędnymi → magazyn, oraz czy któregoś brakuje."""
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    srodek, braki = [], False
    for order in routes.zamowienia_trasy(route):
        if not delivery.aktywne_produkty(order):
            # (I5) Zamówienie anulowane w całości — Routimo go pomija, kierowca tam nie
            # jedzie, więc nie liczy się ani do przebiegu, ani do braków współrzędnych.
            continue
        punkt = punkty_zamowien.get(order.id)
        if punkt is None or punkt.lat is None or punkt.lng is None:
            braki = True
            continue
        srodek.append((float(punkt.lat), float(punkt.lng)))
    return [magazyn] + srodek + [magazyn], braki, len(srodek)


def _linie_proste(route, punkty):
    route.geometry_json = json.dumps({'type': 'LineString',
                                      'coordinates': [[p[1], p[0]] for p in punkty]})
    route.distance_km = round(sum(odleglosc_km(a, b) for a, b in zip(punkty, punkty[1:])), 1)
    route.duration_min = None
    route.geometry_approx = True


def przelicz(route, punkty_zamowien, http_post=requests.post, wymus=False, teraz=None):
    """
    Przelicza przebieg, gdy cache (geometry_hash) nie pasuje do bieżących punktów i warunków
    (patrz docstring modułu). Zwraca True, gdy coś zapisało się w trasie (wołający commituje).
    `wymus` — przelicz bez patrzenia na cache; `teraz` — chwila dla skrótu błędu (testy).
    """
    global _klucz_ors_ostrzezono
    punkty, braki, liczba = _punkty(route, punkty_zamowien)
    skrot = _sha1(skrot_przebiegu(punkty) + ('-braki' if braki else ''))
    strukturalne = liczba == 0 or braki or liczba > MAKS_PRZYSTANKOW
    klucz = klucz_ors()
    skrot_bez_klucza = _sha1(skrot + '-bez-klucza')
    skrot_bledu = _sha1(skrot + '-blad-' + (teraz or get_local_now()).strftime('%Y%m%d%H'))
    if not wymus:
        # Zwykły skrót pasuje zawsze — także przebieg dokładny policzony z kluczem, którego
        # już nie ma (droga się nie zmieniła). Dopisek „bez klucza” pasuje tylko dopóki klucza
        # nie ma, „błąd” — tylko w tej samej godzinie.
        aktualne = {skrot}
        if not strukturalne:
            aktualne.add(skrot_bledu if klucz else skrot_bez_klucza)
        if route.geometry_hash in aktualne:
            return False
    if liczba == 0:
        route.geometry_hash = skrot
        route.geometry_json = route.distance_km = route.duration_min = None
        route.geometry_approx = braki
        return True
    if not klucz and not _klucz_ors_ostrzezono:
        _klucz_ors_ostrzezono = True
        logger.warning("Brak OPENROUTESERVICE_API_KEY w config/core.json - przebiegi tras "
                       "liczone liniami prostymi")
    if strukturalne:
        route.geometry_hash = skrot
    elif not klucz:
        route.geometry_hash = skrot_bez_klucza
    else:
        wspolrzedne = [[p[1], p[0]] for p in punkty]
        try:
            # (M12) radiuses -1 = szukaj najbliższej drogi bez limitu odległości — przy
            # domyślnych 350 m jedno gospodarstwo daleko od drogi zamieniało całą trasę
            # w linie proste.
            odp = http_post(ORS_URL, json={'coordinates': wspolrzedne, 'radiuses': [-1] * len(wspolrzedne)},
                            headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                            timeout=TIMEOUT_S)
            odp.raise_for_status()
            cecha = odp.json()['features'][0]
            podsumowanie = cecha['properties']['summary']
            route.geometry_json = json.dumps(cecha['geometry'])
            route.distance_km = round(float(podsumowanie['distance']) / 1000.0, 1)
            route.duration_min = int(round(float(podsumowanie['duration']) / 60.0))
            route.geometry_approx = False
            route.geometry_hash = skrot
            return True
        except Exception as e:
            logger.warning("ORS nie policzyl przebiegu - linie proste, ponowna proba za godzine",
                           extra={'route_id': route.id, 'error': str(e)})
            route.geometry_hash = skrot_bledu
    _linie_proste(route, punkty)
    return True


def przebieg(route):
    return json.loads(route.geometry_json) if route.geometry_json else None
