# -*- coding: utf-8 -*-
"""
Przebieg trasy po drogach — OpenRouteService (spec 8.2).

Magazyn → przystanki w kolejności → magazyn. Klucz OPENROUTESERVICE_API_KEY
z config/core.json (bez wartości domyślnej). Brak klucza, błąd, przystanek
bez współrzędnych albo za dużo punktów → linie proste, odległość w linii
prostej, czas nieznany, geometry_approx = True. Jedno zapytanie z timeoutem
8 s na zapis trasy (limit gunicorna 30 s).
"""
import hashlib
import json

import requests
from flask import current_app

from modules.logging import get_structured_logger
from modules.production.logistics.services import routes
from modules.production.logistics.services.geocoding import MAGAZYN, odleglosc_km  # noqa: F401

logger = get_structured_logger('production.logistics.routing')

ORS_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'
TIMEOUT_S = 8
MAKS_PRZYSTANKOW = 48  # ORS: do 50 punktów, dwa zajmuje magazyn


def klucz_ors():
    klucz = current_app.config.get('OPENROUTESERVICE_API_KEY')
    return klucz.strip() if isinstance(klucz, str) and klucz.strip() else None


def skrot_przebiegu(punkty):
    tekst = json.dumps([[round(p[0], 6), round(p[1], 6)] for p in punkty])
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _punkty(route, punkty_zamowien):
    """[(lat, lng)] magazyn → przystanki z współrzędnymi → magazyn, oraz czy któregoś brakuje."""
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    srodek, braki = [], False
    for order in routes.zamowienia_trasy(route):
        punkt = punkty_zamowien.get(order.id)
        if punkt is None or punkt.lat is None:
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


def przelicz(route, punkty_zamowien, http_post=requests.post, wymus=False):
    punkty, braki, liczba = _punkty(route, punkty_zamowien)
    skrot = skrot_przebiegu(punkty) + ('-braki' if braki else '')
    skrot = hashlib.sha1(skrot.encode('utf-8')).hexdigest()
    if not wymus and route.geometry_hash == skrot:
        return False
    route.geometry_hash = skrot
    if liczba == 0:
        route.geometry_json = route.distance_km = route.duration_min = None
        route.geometry_approx = braki
        return True
    klucz = klucz_ors()
    if klucz and not braki and liczba <= MAKS_PRZYSTANKOW:
        try:
            odp = http_post(ORS_URL, json={'coordinates': [[p[1], p[0]] for p in punkty]},
                            headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                            timeout=TIMEOUT_S)
            odp.raise_for_status()
            cecha = odp.json()['features'][0]
            podsumowanie = cecha['properties']['summary']
            route.geometry_json = json.dumps(cecha['geometry'])
            route.distance_km = round(float(podsumowanie['distance']) / 1000.0, 1)
            route.duration_min = int(round(float(podsumowanie['duration']) / 60.0))
            route.geometry_approx = False
            return True
        except Exception as e:
            logger.warning("ORS nie policzyl przebiegu - linie proste", extra={
                'route_id': route.id, 'error': str(e)})
    _linie_proste(route, punkty)
    return True


def przebieg(route):
    return json.loads(route.geometry_json) if route.geometry_json else None
