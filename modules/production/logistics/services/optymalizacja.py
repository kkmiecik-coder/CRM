# -*- coding: utf-8 -*-
"""
Optymalizacja kolejności przystanków trasy roboczej (krok 4.4d, spec etapu 4, sekcja 9.9).

Tylko PODGLĄD: nic nie zapisuje i nie bierze blokady tras. Proponowaną kolejność logistyk stosuje
istniejącym `PUT /routes/<id>/stops/order` (routes.zmien_kolejnosc — blokada tras, status, zestaw przystanków).

Przebieg:
1. Przystanki dzielimy na optymalizowane (zamówienie z nieanulowaną pozycją i DOKŁADNYM punktem,
   `OrderGeo.quality == 'dokladna'`) i pozostałe (punkt przybliżony, brak punktu, anulowane w całości).
   Pozostałe idą na koniec, w dotychczasowej kolejności — ich miejsce zna tylko logistyk.
2. ORS Optimization (VROOM): jeden pojazd, start = koniec = magazyn, zadania = przystanki optymalizowane.
3. Km i czas obecnej i proponowanej kolejności — ORS Directions (routing.zapytaj_przebieg), tak samo jak
   przebieg trasy: magazyn → przystanki z punktem (także przybliżonym) → magazyn. Obecną bierzemy z zapisanego
   przebiegu, gdy jest dokładny i policzony dla tych samych punktów (bez dodatkowego zapytania).

Bez automatu przy każdej zmianie — nadpisywałby ręczną kolejność i zużywał limit ORS (decyzja Konrada).
"""
import time

import requests

from modules.logging import get_structured_logger
from modules.production.logistics.services import delivery, geocoding, routes, routing
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.logistics.services.geocoding import MAGAZYN

logger = get_structured_logger('production.logistics.optymalizacja')

ORS_OPTIMIZATION_URL = 'https://api.openrouteservice.org/optimization'
# Do 3 zapytań ORS (optymalizacja + przebieg obecny + proponowany) w jednym żądaniu, a gunicorn ma 30 s.
# Każde zapytanie dostaje tyle czasu odczytu, ile zostało z BUDZET_S (najwyżej MAKS_ODCZYT_S); gdy zostało
# mniej niż MIN_ODCZYT_S, przerywamy z komunikatem zamiast ryzykować zabicie workera.
BUDZET_S = 22.0
POLACZENIE_S = 3.05
MAKS_ODCZYT_S = 10.0
MIN_ODCZYT_S = 3.0
MAKS_PRZYSTANKOW = routing.MAKS_PRZYSTANKOW   # ORS Directions: do 50 punktów, dwa zajmuje magazyn

KOMUNIKAT_BEZ_KLUCZA = u'Brak klucza OpenRouteService — optymalizacja niedostępna.'
KOMUNIKAT_NIC = u'Nie ma czego optymalizować'
KOMUNIKAT_LIMIT = (u'OpenRouteService odmówił — wyczerpany limit zapytań. Spróbuj później; '
                   u'kolejność trasy bez zmian.')
KOMUNIKAT_BLAD = (u'OpenRouteService nie policzył optymalizacji — spróbuj ponownie za chwilę; '
                  u'kolejność trasy bez zmian.')

# Dlaczego przystanek nie idzie do optymalizacji (pole `powod` w odpowiedzi).
POWOD_PRZYBLIZONY = 'przyblizony'
POWOD_BRAK = 'brak_punktu'
POWOD_ANULOWANE = 'anulowane'
POWOD_NIEOSIAGALNY = 'nieosiagalny'   # ORS nie umiał dojechać (zadanie w `unassigned`)


class _BladOrs(Exception):
    def __init__(self, limit=False):
        super().__init__('limit' if limit else 'blad')
        self.limit = limit


class _Zegar(object):
    """Budżet czasu na wszystkie zapytania ORS jednego żądania (patrz BUDZET_S)."""

    def __init__(self, zrodlo=time.monotonic):
        self.zrodlo = zrodlo
        self.start = zrodlo()

    def timeout(self):
        zostalo = BUDZET_S - (self.zrodlo() - self.start) - POLACZENIE_S
        if zostalo < MIN_ODCZYT_S:
            raise _BladOrs()
        return (POLACZENIE_S, min(MAKS_ODCZYT_S, zostalo))


def _punkt(geo):
    """(lat, lng) albo None."""
    if geo is None or geo.lat is None or geo.lng is None:
        return None
    return (float(geo.lat), float(geo.lng))


def _podziel(route, zamowienia, punkty):
    """
    Przystanki trasy w obecnej kolejności: [{order_id, order, punkt, powod}] — `powod` None = optymalizowany.
    Przystanek bez zamówienia (skasowane w międzyczasie) zostaje na końcu jak anulowany: kolejność wysyłana do
    PUT musi zawierać WSZYSTKIE przystanki trasy.
    """
    po_id = {o.id: o for o in zamowienia}
    wynik = []
    for stop in route.stops:
        order = po_id.get(stop.order_id)
        geo = punkty.get(stop.order_id)
        punkt = _punkt(geo)
        if order is None or not delivery.aktywne_produkty(order):
            powod = POWOD_ANULOWANE
        elif punkt is None:
            powod = POWOD_BRAK
        elif geo.quality != 'dokladna':
            powod = POWOD_PRZYBLIZONY
        else:
            powod = None
        wynik.append({'order_id': stop.order_id, 'order': order, 'punkt': punkt, 'powod': powod})
    return wynik


def _post(http_post, url, cialo, klucz, zegar):
    try:
        odp = http_post(url, json=cialo, headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                        timeout=zegar.timeout())
    except _BladOrs:
        raise
    except Exception as e:
        logger.warning('Optymalizacja trasy: ORS nie odpowiedzial', extra={'error': str(e)})
        raise _BladOrs()
    if getattr(odp, 'status_code', None) == 429:
        raise _BladOrs(limit=True)
    try:
        odp.raise_for_status()
        return odp.json()
    except Exception as e:
        logger.warning('Optymalizacja trasy: blad odpowiedzi ORS', extra={'error': str(e)})
        raise _BladOrs()


def _kolejnosc_vroom(optymalizowane, klucz, http_post, zegar):
    """[order_id] w kolejności VROOM i [order_id] zadań, których ORS nie przydzielił (nieosiągalne)."""
    magazyn = [MAGAZYN['lng'], MAGAZYN['lat']]
    cialo = {
        'jobs': [{'id': p['order_id'], 'location': [p['punkt'][1], p['punkt'][0]]} for p in optymalizowane],
        'vehicles': [{'id': 1, 'profile': 'driving-car', 'start': magazyn, 'end': magazyn}],
    }
    dane = _post(http_post, ORS_OPTIMIZATION_URL, cialo, klucz, zegar)
    try:
        if dane.get('code', 0) != 0:
            raise ValueError('code {}'.format(dane.get('code')))
        kroki = dane['routes'][0]['steps'] if dane.get('routes') else []
        kolejnosc = [int(k['job'] if 'job' in k else k['id']) for k in kroki if k.get('type') == 'job']
        nieprzydzielone = [int(z['id']) for z in (dane.get('unassigned') or [])]
    except Exception as e:
        logger.warning('Optymalizacja trasy: nieczytelna odpowiedz ORS', extra={'error': str(e)})
        raise _BladOrs()
    znane = {p['order_id'] for p in optymalizowane}
    # Odpowiedź musi pokryć dokładnie nasze zadania (każde raz) — inaczej to nie nasza kolejność.
    if (len(kolejnosc) + len(nieprzydzielone) != len(znane)
            or set(kolejnosc) | set(nieprzydzielone) != znane):
        logger.warning('Optymalizacja trasy: ORS zwrocil inne zadania niz wyslane')
        raise _BladOrs()
    return kolejnosc, nieprzydzielone


def _przebieg(przystanki, klucz, http_post, zegar):
    """{km, minuty} dla przystanków w podanej kolejności (anulowane i bez punktu pomijamy, jak routing._punkty)."""
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    srodek = [p['punkt'] for p in przystanki if p['powod'] != POWOD_ANULOWANE and p['punkt'] is not None]
    try:
        cecha = routing.zapytaj_przebieg([magazyn] + srodek + [magazyn], klucz, http_post, timeout=zegar.timeout())
        km, minuty = routing.km_i_minuty(cecha)
    except _BladOrs:
        raise
    except Exception as e:
        if isinstance(e, requests.HTTPError) and getattr(e.response, 'status_code', None) == 429:
            raise _BladOrs(limit=True)
        logger.warning('Optymalizacja trasy: ORS nie policzyl przebiegu', extra={'error': str(e)})
        raise _BladOrs()
    return {'km': km, 'minuty': minuty}


def _zapisany_przebieg(route, przystanki):
    """
    Km i czas z zapisanego przebiegu trasy, gdy to przebieg PO DROGACH policzony dla dokładnie tych punktów
    (ten sam skrót co routing.przelicz, bez przystanków bez punktu); inaczej None.
    """
    if route.geometry_approx or route.distance_km is None or route.duration_min is None:
        return None
    if any(p['punkt'] is None and p['powod'] != POWOD_ANULOWANE for p in przystanki):
        return None
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    punkty = [magazyn] + [p['punkt'] for p in przystanki if p['powod'] != POWOD_ANULOWANE] + [magazyn]
    if route.geometry_hash != routing._sha1(routing.skrot_przebiegu(punkty)):
        return None
    return {'km': float(route.distance_km), 'minuty': int(route.duration_min)}


def _opis(p, pozycja_obecna, pozycja_nowa):
    order = p['order']
    return {
        'order_id': p['order_id'],
        'numer': order.internal_order_number if order is not None else None,
        'klient': order.client_name if order is not None else None,
        'miasto': order.delivery_city if order is not None else None,
        'pozycja_obecna': pozycja_obecna,
        'pozycja_nowa': pozycja_nowa,
        'optymalizowany': p['powod'] is None,
        'powod': p['powod'],
    }


def zaproponuj(route, http_post=None, zegar=None):
    """
    Podgląd optymalizacji trasy roboczej. Zwraca słownik odpowiedzi (patrz trasy_api.route_optimize, spec 9.9);
    odmowy jako LogistykaBlad: status (409), brak klucza (503), < 2 przystanki z dokładnym punktem
    i za dużo przystanków (422), błąd albo limit ORS (502). Niczego nie zmienia w sesji.
    `http_post` — podmiana HTTP w testach (domyślnie requests.post w chwili wołania); `zegar` — budżet czasu.
    """
    http_post = http_post or requests.post
    routes._wymagaj_statusu(route, 'robocza')
    klucz = routing.klucz_ors()
    if not klucz:
        raise LogistykaBlad(KOMUNIKAT_BEZ_KLUCZA, status=503)
    zamowienia = routes.zamowienia_trasy(route)
    punkty = geocoding.geo_zamowien([s.order_id for s in route.stops])
    przystanki = _podziel(route, zamowienia, punkty)
    optymalizowane = [p for p in przystanki if p['powod'] is None]
    pozostale = [p for p in przystanki if p['powod'] is not None]
    if len(optymalizowane) < 2:
        raise LogistykaBlad(
            KOMUNIKAT_NIC + u' — do optymalizacji potrzeba co najmniej 2 przystanków z dokładnym punktem na mapie.',
            status=422, dane={'pominiete': len(pozostale)})
    z_punktem = sum(1 for p in przystanki if p['powod'] != POWOD_ANULOWANE and p['punkt'] is not None)
    if z_punktem > MAKS_PRZYSTANKOW:
        raise LogistykaBlad(u'Za dużo przystanków do optymalizacji (najwyżej {}).'.format(MAKS_PRZYSTANKOW),
                            status=422)
    zegar = zegar or _Zegar()
    try:
        kolejnosc, nieprzydzielone = _kolejnosc_vroom(optymalizowane, klucz, http_post, zegar)
        po_id = {p['order_id']: p for p in przystanki}
        for order_id in nieprzydzielone:
            po_id[order_id]['powod'] = POWOD_NIEOSIAGALNY
        # Nieosiągalne zostają w swojej dotychczasowej kolejności razem z innymi pominiętymi, na końcu.
        nowe = [po_id[i] for i in kolejnosc] + [p for p in przystanki if p['powod'] is not None]
        obecna = _zapisany_przebieg(route, przystanki) or _przebieg(przystanki, klucz, http_post, zegar)
        zmieniona = [p['order_id'] for p in nowe] != [p['order_id'] for p in przystanki]
        proponowana = _przebieg(nowe, klucz, http_post, zegar) if zmieniona else dict(obecna)
    except _BladOrs as e:
        raise LogistykaBlad(KOMUNIKAT_LIMIT if e.limit else KOMUNIKAT_BLAD, status=502)
    pozycje_obecne = {p['order_id']: i for i, p in enumerate(przystanki, start=1)}
    return {
        'route_id': route.id,
        'obecne_order_ids': [p['order_id'] for p in przystanki],
        'order_ids': [p['order_id'] for p in nowe],
        'zmieniona': zmieniona,
        'obecna': obecna,
        'proponowana': proponowana,
        'zysk': {'km': round(obecna['km'] - proponowana['km'], 1),
                 'minuty': obecna['minuty'] - proponowana['minuty']},
        'przystanki': [_opis(p, pozycje_obecne[p['order_id']], i) for i, p in enumerate(nowe, start=1)],
        'optymalizowane': len(kolejnosc),
        'pominiete': sum(1 for p in nowe if p['powod'] is not None),
    }
