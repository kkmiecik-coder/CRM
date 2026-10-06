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

Przystanek daleko od drogi (runda poprawek po przeglądzie końcowym, decyzja Konrada 4.10). ORS przyciąga punkt
do drogi najwyżej na ok. 3 km (sprawdzone 4.10 na prawdziwym ORS: Snap 3,04 km tak, 3,32 km null; Directions
z `radiuses: -1` tak samo), dalej Directions odpowiada 404 (kod 2010) dla CAŁEJ trasy. Wtedy:
1. jeden Snap wszystkich przystanków — `null` = przystanek daleko od drogi (najwyżej MAKS_DALEKICH);
2. szukaj_drogi: Snap punktów-kandydatów na okręgach wokół pinezki (zgrubnie co KROK_ZGRUBNY_KM do
   MAKS_ODBICIA_KM, potem co KROK_DOKLADNY_KM w pasie, w którym może leżeć najbliższa droga) — wszystkie
   przystanki w jednym zapytaniu na przejście; wynik = punkt na drodze najbliższy pinezce („punkt do odbicia”);
3. Directions z punktem do odbicia w miejscu pinezki. Od niego do pinezki — odcinek prosty: w `geometry_json`
   jako `odcinki_proste` [[[lng, lat] drogi, [lng, lat] pinezki]] (front rysuje go przerywaną). Km = po drogach
   + odcinki proste tam i z powrotem, czas — tylko po drogach (oba przybliżone; UI: „część trasy w linii prostej”).
   `geometry_approx` zostaje False (trasa idzie po drogach), skrót — zwykły (wynik zależy tylko od punktów).
Pinezki nie ruszamy. Brak drogi w zasięgu, za dużo dalekich przystanków albo kolejny błąd → linie proste całej
trasy jak przy błędzie ORS. Zapytania jednego przeliczenia mieszczą się w budżecie Zegar (BUDZET_S; gunicorn
ubija żądanie po 30 s), a po pierwszym Directions szukamy dalej tylko po szybkiej odpowiedzi 404/2010.
"""
import hashlib
import json
import math
import time

import requests
from flask import current_app, g, has_request_context

from modules.logging import get_structured_logger
from modules.production.logistics.services import delivery, routes
from modules.production.logistics.services.geocoding import MAGAZYN, odleglosc_km  # noqa: F401
from modules.production.models import get_local_now

logger = get_structured_logger('production.logistics.routing')

ORS_URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'
ORS_SNAP_URL = 'https://api.openrouteservice.org/v2/snap/driving-car'
# (M12) (połączenie, odczyt) — sama liczba dotyczyłaby każdego z nich osobno; połączenie
# ograniczamy mocniej, bo przy niedostępnym ORS to ono wisi.
TIMEOUT_S = (3.05, 8)
MAKS_PRZYSTANKOW = 48  # ORS: do 50 punktów, dwa zajmuje magazyn

# Przystanek daleko od drogi (patrz docstring modułu).
KOD_PUNKT_BEZ_DROGI = 2010    # ORS Directions: „Could not find routable point within … of specified coordinate N”
PROMIEN_SNAP_M = 10000        # ORS i tak przyciąga najwyżej ok. 3 km (sprawdzone 4.10)
# Zgrubnie: okręgi co 3 km, punkty po obwodzie co ≤ 3 km — każdy punkt koła leży ≤ 2,12 km (połowa przekątnej
# kwadratu 3 km) od kandydata, czyli w zasięgu Snap. Snap kandydata daje drogę najbliższą KANDYDATOWI, więc
# zgrubny wynik może być do 2 × 2,12 km dalszy od najlepszego — dokładne przejście przeszukuje ten pas co 1 km
# (błąd ≤ 2 × 0,71 km). Prawdziwy ORS: ~350 kandydatów w zgrubnym przejściu, Snap 5000 punktów w 0,5 s.
KROK_ZGRUBNY_KM = 3.0
KROK_DOKLADNY_KM = 1.0
PAS_DOKLADNY_KM = 2 * KROK_ZGRUBNY_KM / math.sqrt(2) + 0.05
MAKS_ODBICIA_KM = 30.0        # dalej pinezka jest raczej pomyłką — linie proste całej trasy
MAKS_DALEKICH = 5
BUDZET_S = 20.0               # wszystkie zapytania ORS jednego przeliczenia poza żądaniem panelu
# (M1 po re-review) W żądaniu panelu budżet liczymy od POCZĄTKU żądania (zapamietaj_start_zadania w before_request
# blueprintu): zapis mógł już czekać na blokadę tras i ponawiać po 1213, a gunicorn ubija żądanie po 30 s. Zapas
# 6 s na commit, serializację odpowiedzi i nietwardy limit odczytu `requests`.
BUDZET_ZADANIA_S = 24.0
MAKS_SNAP_S = 5.0
MIN_ODCZYT_S = 2.0
_PROMIEN_ZIEMI_KM = 6371.0

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


class PunktBezDrogi(Exception):
    """ORS Directions: 404 z kodem 2010 — któryś punkt leży dalej od drogi, niż ORS przyciąga (ok. 3 km)."""


class BrakCzasu(Exception):
    """Budżet czasu przeliczenia wyczerpany — kolejnego zapytania nie wysyłamy."""


class Zegar(object):
    """
    Budżet czasu na zapytania ORS jednego przeliczenia (BUDZET_S). Jak optymalizacja._Zegar: to nie twardy limit
    (`requests` mierzy odczyt jako przerwę między porcjami bajtów), ale każde zapytanie dostaje najwyżej tyle czasu
    odczytu, ile zostało, a gdy zostało mniej niż MIN_ODCZYT_S — BrakCzasu zamiast zapytania.
    """

    def __init__(self, budzet=BUDZET_S, zrodlo=None, start=None):
        self.budzet, self.zrodlo = budzet, zrodlo or _monotoniczny
        self.start = self.zrodlo() if start is None else start

    def timeout(self, maks=TIMEOUT_S[1]):
        zostalo = self.budzet - (self.zrodlo() - self.start) - TIMEOUT_S[0]
        if zostalo < MIN_ODCZYT_S:
            raise BrakCzasu()
        return (TIMEOUT_S[0], min(maks, zostalo))


def _monotoniczny():
    return time.monotonic()


def zapamietaj_start_zadania():
    """before_request blueprintu panelu logistyki: chwila startu żądania dla budżetu przeliczenia (M1)."""
    g.logistyka_start_zadania = _monotoniczny()


def zegar_zadania():
    """Zegar przeliczenia: w żądaniu panelu od początku żądania (BUDZET_ZADANIA_S), poza nim — od teraz (BUDZET_S)."""
    if has_request_context():
        start = g.get('logistyka_start_zadania')
        if start is not None:
            return Zegar(budzet=BUDZET_ZADANIA_S, start=start)
    return Zegar()


def _kod_bledu(odp):
    try:
        return int(odp.json()['error']['code'])
    except Exception:
        return None


def zapytaj_przebieg(punkty, klucz, http_post=None, timeout=TIMEOUT_S):
    """
    Jedno zapytanie ORS Directions dla punktów [(lat, lng)] w podanej kolejności → pierwsza cecha GeoJSON
    (geometria + summary). Błąd HTTP i zła odpowiedź rzucają wyjątek — decyzję zostawiamy wołającemu
    (przelicz: punkt do odbicia albo linie proste; optymalizacja kolejności: komunikat, krok 4.4d).
    404 z kodem 2010 (punkt dalej od drogi, niż ORS przyciąga) → PunktBezDrogi.
    """
    # (I2 po przeglądzie 4.4d) requests.post brany w chwili wołania, nie przy imporcie — podmiana w testach działa.
    http_post = http_post or requests.post
    wspolrzedne = [[p[1], p[0]] for p in punkty]
    # (M12) radiuses -1 = szukaj najbliższej drogi bez limitu odległości — przy
    # domyślnych 350 m jedno gospodarstwo daleko od drogi zamieniało całą trasę
    # w linie proste.
    odp = http_post(ORS_URL, json={'coordinates': wspolrzedne, 'radiuses': [-1] * len(wspolrzedne)},
                    headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                    timeout=timeout)
    if getattr(odp, 'status_code', None) == 404 and _kod_bledu(odp) == KOD_PUNKT_BEZ_DROGI:
        tresc = getattr(odp, 'text', '')
        raise PunktBezDrogi(tresc[:300] if isinstance(tresc, str) else '')
    odp.raise_for_status()
    return odp.json()['features'][0]


def snap_ors(klucz, http_post, zegar):
    """
    Funkcja Snap dla szukaj_drogi i przebieg_po_drogach: [(lat, lng)] → [(lat, lng) na drodze albo None].
    Błąd HTTP, zła odpowiedź i inna liczba punktów rzucają wyjątek.
    """
    def snap(punkty):
        odp = http_post(ORS_SNAP_URL, json={'locations': [[p[1], p[0]] for p in punkty], 'radius': PROMIEN_SNAP_M},
                        headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                        timeout=zegar.timeout(MAKS_SNAP_S))
        odp.raise_for_status()
        miejsca = odp.json()['locations']
        if not isinstance(miejsca, list) or len(miejsca) != len(punkty):
            raise ValueError('Snap: inna liczba punktow')
        return [None if m is None else (float(m['location'][1]), float(m['location'][0])) for m in miejsca]
    return snap


def _okregi(p, od_km, do_km, krok_km):
    """Kandydaci (lat, lng) na okręgach wokół p o promieniach od_km..do_km co krok_km, po obwodzie co ≤ krok_km."""
    wynik = []
    promien = od_km
    while promien <= do_km + 1e-9:
        n = max(6, int(math.ceil(2 * math.pi * promien / krok_km)))
        katowo = promien / _PROMIEN_ZIEMI_KM
        for i in range(n):
            kat = 2 * math.pi * i / n
            wynik.append((p[0] + math.degrees(katowo * math.cos(kat)),
                          p[1] + math.degrees(katowo * math.sin(kat) / math.cos(math.radians(p[0])))))
        promien += krok_km
    return wynik


def _najblizsze(punkty, kandydaci, snap):
    """Jedno zapytanie Snap dla kandydatów wszystkich punktów → {indeks punktu: najbliższy mu punkt na drodze}."""
    plaskie = [q for lista in kandydaci for q in lista]
    przyciagniete = snap(plaskie) if plaskie else []
    wynik, poczatek = {}, 0
    for nr, lista in enumerate(kandydaci):
        for droga in przyciagniete[poczatek:poczatek + len(lista)]:
            if droga is not None and (nr not in wynik or
                                      odleglosc_km(punkty[nr], droga) < odleglosc_km(punkty[nr], wynik[nr])):
                wynik[nr] = droga
        poczatek += len(lista)
    return wynik


def szukaj_drogi(punkty, snap):
    """
    {indeks: (lat, lng)} — punkt na drodze najbliższy każdemu z `punkty` (pinezki, których Snap nie przyciąga),
    w promieniu MAKS_ODBICIA_KM; punkt bez drogi w tym promieniu nie ma wpisu. `snap` — funkcja jak snap_ors.
    Najwyżej dwa zapytania Snap (zgrubne i dokładne), każde dla wszystkich punktów naraz.
    """
    zgrubne = _najblizsze(punkty, [_okregi(p, KROK_ZGRUBNY_KM, MAKS_ODBICIA_KM, KROK_ZGRUBNY_KM) for p in punkty],
                          snap)
    if not zgrubne:
        return {}
    numery = sorted(zgrubne)
    pasy = []
    for nr in numery:
        odl = odleglosc_km(punkty[nr], zgrubne[nr])
        pasy.append(_okregi(punkty[nr], max(KROK_DOKLADNY_KM, odl - PAS_DOKLADNY_KM), odl, KROK_DOKLADNY_KM))
    dokladne = _najblizsze([punkty[nr] for nr in numery], pasy, snap)
    wynik = dict(zgrubne)
    for j, droga in dokladne.items():
        nr = numery[j]
        if odleglosc_km(punkty[nr], droga) < odleglosc_km(punkty[nr], wynik[nr]):
            wynik[nr] = droga
    return wynik


def przebieg_po_drogach(punkty, klucz, http_post, zegar, snap=None):
    """
    (cecha ORS Directions, odcinki proste [((lat, lng) drogi, (lat, lng) pinezki)]) dla punktów magazyn → przystanki
    → magazyn. Bez przystanku daleko od drogi — jedno zapytanie i pusta lista odcinków. Po 404/2010: Snap
    przystanków, szukaj_drogi dla tych z `null` i drugie Directions z punktami do odbicia. Każda porażka po drodze
    (brak drogi w zasięgu, za dużo dalekich, błąd, budżet) rzuca wyjątek — wołający rysuje linie proste.
    """
    try:
        return zapytaj_przebieg(punkty, klucz, http_post, timeout=zegar.timeout(TIMEOUT_S[1])), []
    except PunktBezDrogi as e:
        logger.info("ORS: przystanek daleko od drogi - szukamy punktu do odbicia", extra={'error': str(e)})
    snap = snap or snap_ors(klucz, http_post, zegar)
    srodek = list(punkty[1:-1])
    przyciagniete = snap(srodek)
    # (M6) Ta sama pinezka kilku przystanków (dwa zamówienia pod jednym adresem) — szukamy raz.
    dalekie = []
    for i, droga in enumerate(przyciagniete):
        if droga is None and srodek[i] not in dalekie:
            dalekie.append(srodek[i])
    if len(dalekie) > MAKS_DALEKICH:
        raise ValueError('Za duzo przystankow daleko od drogi: {}'.format(len(dalekie)))
    drogi = szukaj_drogi(dalekie, snap) if dalekie else {}
    if len(drogi) != len(dalekie):
        raise ValueError('Brak drogi w promieniu {} km od pinezki'.format(MAKS_ODBICIA_KM))
    odbicia = {pinezka: drogi[j] for j, pinezka in enumerate(dalekie)}
    # (M5) Drugie Directions z punktami ze Snap dla WSZYSTKICH przystanków: pinezka w pasie ok. 3 km (Directions
    # 404/2010, a Snap ją przyciąga — progi obu usług nie są identyczne) jedzie do punktu ze Snap zamiast linii
    # prostych całej trasy. Odcinek prosty rysujemy tylko od punktu do odbicia (pinezka poza zasięgiem Snap),
    # tak jak przebieg dokładny nie rysuje odcinka od drogi, do której przyciągnął ORS.
    nowe, odcinki = list(punkty), []
    for i, pinezka in enumerate(srodek):
        if pinezka in odbicia:
            nowe[i + 1] = odbicia[pinezka]
            # (M6) Kolejne przystanki pod tą samą pinezką — kierowca idzie do niej raz.
            if i == 0 or srodek[i - 1] != pinezka:
                odcinki.append((odbicia[pinezka], pinezka))
        else:
            nowe[i + 1] = przyciagniete[i]
    return zapytaj_przebieg(nowe, klucz, http_post, timeout=zegar.timeout()), odcinki


def dlugosc_odcinkow_km(odcinki):
    """Odcinki proste tam i z powrotem (kierowca wraca do punktu do odbicia)."""
    return 2 * sum(odleglosc_km(droga, pinezka) for droga, pinezka in odcinki)


def km_i_minuty(cecha):
    """(km z jednym miejscem po przecinku, minuty) z summary cechy ORS Directions."""
    podsumowanie = cecha['properties']['summary']
    return (round(float(podsumowanie['distance']) / 1000.0, 1),
            int(round(float(podsumowanie['duration']) / 60.0)))


def przelicz(route, punkty_zamowien, http_post=None, wymus=False, teraz=None, zegar=None):
    """
    Przelicza przebieg, gdy cache (geometry_hash) nie pasuje do bieżących punktów i warunków
    (patrz docstring modułu). Zwraca True, gdy coś zapisało się w trasie (wołający commituje).
    `wymus` — przelicz bez patrzenia na cache; `teraz` — chwila dla skrótu błędu (testy); `http_post` — podmiana
    HTTP w testach (domyślnie requests.post w chwili wołania, patrz zapytaj_przebieg); `zegar` — budżet czasu.
    """
    global _klucz_ors_ostrzezono
    zegar = zegar or zegar_zadania()
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
        try:
            zegar.timeout(TIMEOUT_S[1])
        except BrakCzasu:
            # (M1) Żądanie zużyło już budżet (np. czekało na blokadę tras) — nie pytamy ORS i nie ruszamy cache:
            # skrót się nie zgadza, więc przeliczy kolejne otwarcie trasy albo mapy.
            logger.warning("Przebieg trasy odlozony - zadanie zuzylo budzet czasu", extra={'route_id': route.id})
            return False
        try:
            cecha, odcinki = przebieg_po_drogach(punkty, klucz, http_post or requests.post, zegar)
            geometria = dict(cecha['geometry'])
            if odcinki:
                geometria['odcinki_proste'] = [[[d[1], d[0]], [p[1], p[0]]] for d, p in odcinki]
            route.geometry_json = json.dumps(geometria)
            km, route.duration_min = km_i_minuty(cecha)
            route.distance_km = round(km + dlugosc_odcinkow_km(odcinki), 1)
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


def liczba_odcinkow_prostych(route):
    """Liczba odcinków prostych od punktu do odbicia do pinezki (przystanki daleko od drogi; kolejne przystanki pod
    tą samą pinezką — jeden odcinek). To samo znaczy pole `odcinki_proste` w odpowiedzi optymalizacji."""
    try:
        return len((przebieg(route) or {}).get('odcinki_proste') or [])
    except (ValueError, TypeError, AttributeError):
        return 0
