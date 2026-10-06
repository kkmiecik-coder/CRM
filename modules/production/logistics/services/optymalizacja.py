# -*- coding: utf-8 -*-
"""
Optymalizacja kolejności przystanków trasy roboczej (krok 4.4d, spec etapu 4, sekcja 9.9).

Tylko PODGLĄD: nic nie zapisuje i nie bierze blokady tras. Proponowaną kolejność logistyk stosuje
istniejącym `PUT /routes/<id>/stops/order` (routes.zmien_kolejnosc — blokada tras, status, zestaw przystanków).

Przebieg:
1. Przystanki dzielimy na optymalizowane (zamówienie z nieanulowaną pozycją i DOKŁADNYM punktem,
   `OrderGeo.quality == 'dokladna'`) i pozostałe (punkt przybliżony, brak punktu, anulowane w całości).
   Pozostałe idą na koniec, w dotychczasowej kolejności — ich miejsce zna tylko logistyk.
2. ORS Snap przyciąga do najbliższej drogi punkty przystanków jadących w przebiegu (dokładne i przybliżone;
   I1 po przeglądzie 4.4d). Punkt, do którego ORS nie umie dojechać (gospodarstwo w lesie, pinezka w polu), dawał
   HTTP 500 całej optymalizacji, a Directions — 404 „routable point” mimo `radiuses: -1` (sprawdzone 3.10: ORS
   przyciąga do ok. 3 km od drogi, dalej nie). Snap zwraca dla takiego punktu `null` — wtedy szukamy punktu na
   drodze najbliższego pinezce (routing.szukaj_drogi, ten sam „punkt do odbicia” co w przebiegu trasy; runda
   poprawek po przeglądzie końcowym): znaleziony idzie do VROOM i do km (po drogach do niego + odcinek prosty tam
   i z powrotem, pole `odcinki_proste`). Bez drogi w promieniu szukania przystanek pomijamy (powód
   `daleko_od_drogi`, na koniec jak inne pominięte) i nie liczymy go do km i czasu obu kolejności
   (`poza_przebiegiem`). Do VROOM idą współrzędne przyciągnięte do drogi. Snap niedostępny (błąd, zła odpowiedź) →
   optymalizujemy na oryginalnych punktach.
3. ORS Optimization (VROOM): jeden pojazd, start = koniec = magazyn, zadania = przystanki optymalizowane.
   Gdy mimo to odpowie błędem wskazującym punkt („location [lng,lat]” albo „coordinate N”), pomijamy ten
   przystanek (`daleko_od_drogi`) i ponawiamy RAZ; drugi błąd → 502.
4. Km i czas obecnej i proponowanej kolejności — ORS Directions (routing.zapytaj_przebieg), tak samo jak
   przebieg trasy: magazyn → przystanki z punktem (także przybliżonym, bez `daleko_od_drogi`, z punktem do odbicia
   zamiast pinezki) → magazyn. Obecną bierzemy z zapisanego przebiegu, gdy jest po drogach i policzony dla tych
   samych punktów (bez dodatkowego zapytania).

Bez automatu przy każdej zmianie — nadpisywałby ręczną kolejność i zużywał limit ORS (decyzja Konrada).
"""
import re
import time

import requests

from modules.logging import get_structured_logger
from modules.production.logistics.services import delivery, geocoding, routes, routing
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.logistics.services.geocoding import MAGAZYN

logger = get_structured_logger('production.logistics.optymalizacja')

ORS_OPTIMIZATION_URL = 'https://api.openrouteservice.org/optimization'
ORS_SNAP_URL = routing.ORS_SNAP_URL
# Promień szukania drogi w Snap. Prawdziwy ORS (sprawdzone 3.10) przyciąga punkty do ok. 3 km od drogi także przy
# większym promieniu, dalej zwraca null — wtedy szukamy punktu do odbicia (routing.szukaj_drogi).
PROMIEN_SNAP_M = routing.PROMIEN_SNAP_M
# Do 5 zapytań ORS w jednym żądaniu (Snap, optymalizacja i jej jedno ponowienie, przebieg obecny i proponowany;
# z przystankiem daleko od drogi jeszcze 2 × Snap szukania punktu do odbicia — razem 7),
# a gunicorn ma 30 s. Każde zapytanie dostaje tyle czasu odczytu, ile zostało z BUDZET_S (najwyżej MAKS_ODCZYT_S,
# Snap — MAKS_SNAP_S); gdy zostało mniej niż MIN_ODCZYT_S, przerywamy z komunikatem zamiast ryzykować zabicie
# workera.
BUDZET_S = 22.0
POLACZENIE_S = 3.05
MAKS_ODCZYT_S = 10.0
MAKS_SNAP_S = 5.0
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
POWOD_DALEKO = 'daleko_od_drogi'      # Snap nie znalazł drogi albo Optimization wskazała punkt w błędzie

# Błąd Optimization wskazujący punkt: „Unfound route(s) from location [22.565000,49.090500]” (VROOM, sprawdzone
# na prawdziwym ORS 3.10) albo „… routable point … coordinate N” (ORS, opis z forum — numer w liście miejsc VROOM).
_WZOR_LOKALIZACJA = re.compile(r'location\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]')
_WZOR_WSPOLRZEDNA = re.compile(r'coordinate\s+(\d+)')
_TOLERANCJA_STOPNI = 5e-6   # VROOM wypisuje współrzędne z 6 miejscami po przecinku


class _BladOrs(Exception):
    """`tresc` — treść odpowiedzi z błędem HTTP (do rozpoznania punktu, do którego ORS nie umiał dojechać)."""

    def __init__(self, limit=False, tresc=''):
        super().__init__('limit' if limit else 'blad')
        self.limit = limit
        self.tresc = tresc or ''


class _Zegar(object):
    """
    Budżet czasu na wszystkie zapytania ORS jednego żądania (patrz BUDZET_S).

    (M1) To NIE jest twardy limit. `requests` mierzy odczyt jako przerwę między kolejnymi porcjami bajtów, a nie
    czas całej odpowiedzi; limit połączenia liczy się osobno dla każdego adresu z DNS (IPv4 i IPv6), a samo
    rozwiązanie nazwy nie ma limitu. Wolno sącząca się odpowiedź albo dwa nieosiągalne adresy mogą więc zjeść część
    zapasu do 30 s gunicorna. Ryzyko jest niskie: ORS wysyła odpowiedź w całości po policzeniu (małe JSON-y),
    zapasu jest 8 s ponad budżet, a awaria ORS kończy się zwykle szybkim błędem połączenia, nie powolnym sączeniem.
    """

    def __init__(self, zrodlo=time.monotonic):
        self.zrodlo = zrodlo
        self.start = zrodlo()

    def timeout(self, maks=MAKS_ODCZYT_S):
        zostalo = BUDZET_S - (self.zrodlo() - self.start) - POLACZENIE_S
        if zostalo < MIN_ODCZYT_S:
            raise _BladOrs()
        return (POLACZENIE_S, min(maks, zostalo))


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


def _post(http_post, url, cialo, klucz, zegar, maks=MAKS_ODCZYT_S):
    try:
        odp = http_post(url, json=cialo, headers={'Authorization': klucz, 'Content-Type': 'application/json'},
                        timeout=zegar.timeout(maks))
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
        tresc = getattr(odp, 'text', '')
        raise _BladOrs(tresc=tresc[:2000] if isinstance(tresc, str) else '')


def _w_przebiegu(p):
    """Czy przystanek liczy się do km i czasu: ma punkt, nie jest anulowany i ORS do niego dojeżdża."""
    return p['punkt'] is not None and p['powod'] not in (POWOD_ANULOWANE, POWOD_DALEKO)


def _snap(klucz, http_post, zegar):
    """Funkcja Snap jak routing.snap_ors, ale przez _post (budżet optymalizacji, 429 → komunikat limitu)."""
    def snap(punkty):
        cialo = {'locations': [[p[1], p[0]] for p in punkty], 'radius': PROMIEN_SNAP_M}
        lokalizacje = _post(http_post, ORS_SNAP_URL, cialo, klucz, zegar, maks=MAKS_SNAP_S)['locations']
        if not isinstance(lokalizacje, list) or len(lokalizacje) != len(punkty):
            raise ValueError('inna liczba punktow')
        return [None if m is None else (float(m['location'][1]), float(m['location'][0])) for m in lokalizacje]
    return snap


def _przyciagnij(przystanki, klucz, http_post, zegar):
    """
    ORS Snap dla przystanków z punktem: ustawia `p['vroom']` ([lng, lat] dla VROOM — przyciągnięte do drogi albo
    oryginalne) i zwraca przystanki, dla których nie ma drogi ani w zasięgu Snap, ani punktu do odbicia (_odbicia).
    Błąd albo zła odpowiedź Snap → oryginalne punkty i nikt nie jest pominięty (zabezpieczeniem zostaje ponowienie
    w _kolejnosc_vroom); limit zapytań (429) przerywa.
    """
    for p in przystanki:
        p['vroom'] = [p['punkt'][1], p['punkt'][0]]
    snap = _snap(klucz, http_post, zegar)
    try:
        przyciagniete = snap([p['punkt'] for p in przystanki])
    except _BladOrs as e:
        if e.limit:
            raise
        return []   # _post już zalogował
    except Exception as e:
        logger.warning('Optymalizacja trasy: nieczytelna odpowiedz ORS Snap', extra={'error': str(e)})
        return []
    daleko = []
    for p, wsp in zip(przystanki, przyciagniete):
        if wsp is None:
            daleko.append(p)
        else:
            p['vroom'] = [wsp[1], wsp[0]]
    return _odbicia(daleko, snap)


def _odbicia(daleko, snap):
    """
    Punkt do odbicia (routing.szukaj_drogi) dla przystanków, których Snap nie przyciąga: znaleziony → `p['odbicie']`
    (lat, lng) i `p['vroom']`; zwraca przystanki bez drogi w promieniu szukania. Więcej niż routing.MAKS_DALEKICH,
    błąd albo zła odpowiedź → wszystkie zostają daleko od drogi (jak przed poprawką); limit zapytań przerywa.
    """
    if not daleko or len({p['punkt'] for p in daleko}) > routing.MAKS_DALEKICH:
        return daleko
    # (M6 po re-review) Ta sama pinezka kilku przystanków — szukamy raz.
    pinezki = []
    for p in daleko:
        if p['punkt'] not in pinezki:
            pinezki.append(p['punkt'])
    try:
        po_pinezce = routing.szukaj_drogi(pinezki, snap)
        drogi = {nr: po_pinezce[pinezki.index(p['punkt'])] for nr, p in enumerate(daleko)
                 if pinezki.index(p['punkt']) in po_pinezce}
    except _BladOrs as e:
        if e.limit:
            raise
        drogi = {}
    except Exception as e:
        logger.warning('Optymalizacja trasy: nie znaleziono punktu do odbicia', extra={'error': str(e)})
        drogi = {}
    zostaja = []
    for nr, p in enumerate(daleko):
        if nr in drogi:
            p['odbicie'] = drogi[nr]
            p['vroom'] = [drogi[nr][1], drogi[nr][0]]
        else:
            zostaja.append(p)
    return zostaja


def _miejsca_vroom(zadania):
    """Lista miejsc VROOM: magazyn (start = koniec, jedno miejsce), potem zadania bez powtórzeń współrzędnych."""
    miejsca = [[MAGAZYN['lng'], MAGAZYN['lat']]]
    for p in zadania:
        if p['vroom'] not in miejsca:
            miejsca.append(p['vroom'])
    return miejsca


def _winne_z_bledu(tresc, zadania):
    """
    Przystanki wskazane w treści błędu Optimization: po współrzędnych („location [lng,lat]”), a gdy ich nie ma —
    po numerze („coordinate N”) w liście miejsc VROOM (_miejsca_vroom). Tej numeracji nie da się dziś sprawdzić
    (prawdziwy ORS podaje współrzędne); zła zgadywanka kończy się najwyżej drugim błędem i 502, bo winny punkt
    zostaje w ponowieniu. Magazyn i nieznany punkt → [] (bez ponowienia).
    """
    def blisko(a, b):
        return abs(a[0] - b[0]) <= _TOLERANCJA_STOPNI and abs(a[1] - b[1]) <= _TOLERANCJA_STOPNI

    wskazane = [[float(lng), float(lat)] for lng, lat in _WZOR_LOKALIZACJA.findall(tresc)]
    if not wskazane:
        miejsca = _miejsca_vroom(zadania)
        wskazane = [miejsca[int(n)] for n in _WZOR_WSPOLRZEDNA.findall(tresc) if 0 < int(n) < len(miejsca)]
    return [p for p in zadania if any(blisko(p['vroom'], w) for w in wskazane)]


def _kolejnosc_vroom(zadania, klucz, http_post, zegar):
    """
    [order_id] w kolejności VROOM i [order_id] zadań, których ORS nie przydzielił (nieosiągalne). Błąd wskazujący
    punkt: przystanek dostaje powód `daleko_od_drogi` i jedno ponowienie bez niego. Mniej niż 2 zadania — kolejność
    bez pytania ORS.
    """
    for proba in (1, 2):
        if len(zadania) < 2:
            return [p['order_id'] for p in zadania], []
        try:
            return _zapytaj_vroom(zadania, klucz, http_post, zegar)
        except _BladOrs as e:
            winne = [] if (e.limit or proba == 2) else _winne_z_bledu(e.tresc, zadania)
            if not winne:
                raise
            logger.warning('Optymalizacja trasy: ORS nie dojechal do przystanku - pomijamy go i ponawiamy',
                           extra={'order_ids': [p['order_id'] for p in winne]})
            for p in winne:
                p['powod'] = POWOD_DALEKO
            zadania = [p for p in zadania if p['powod'] is None]


def _zapytaj_vroom(zadania, klucz, http_post, zegar):
    magazyn = [MAGAZYN['lng'], MAGAZYN['lat']]
    cialo = {
        'jobs': [{'id': p['order_id'], 'location': p['vroom']} for p in zadania],
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
    znane = {p['order_id'] for p in zadania}
    # Odpowiedź musi pokryć dokładnie nasze zadania (każde raz) — inaczej to nie nasza kolejność.
    if (len(kolejnosc) + len(nieprzydzielone) != len(znane)
            or set(kolejnosc) | set(nieprzydzielone) != znane):
        logger.warning('Optymalizacja trasy: ORS zwrocil inne zadania niz wyslane')
        raise _BladOrs()
    return kolejnosc, nieprzydzielone


def _odcinki_proste(przystanki):
    """
    [(punkt do odbicia, pinezka)] w kolejności przebiegu — jak routing.przebieg_po_drogach: z punktem do odbicia
    po drogach do niego, dalej odcinek prosty tam i z powrotem; (M6) kolejne przystanki pod tą samą pinezką — jeden
    odcinek (kierowca idzie do niej raz). Ta sama liczba idzie do odpowiedzi (`odcinki_proste`).
    """
    w_przebiegu = [p for p in przystanki if _w_przebiegu(p)]
    return [(p['odbicie'], p['punkt']) for i, p in enumerate(w_przebiegu)
            if p.get('odbicie') and (i == 0 or w_przebiegu[i - 1]['punkt'] != p['punkt'])]


def _przebieg(przystanki, klucz, http_post, zegar):
    """
    {km, minuty} dla przystanków w podanej kolejności (anulowane i bez punktu pomijamy, jak routing._punkty; także
    `daleko_od_drogi` — Directions do nich nie dojedzie i odpowie 404 dla całej trasy).
    """
    magazyn = (MAGAZYN['lat'], MAGAZYN['lng'])
    w_przebiegu = [p for p in przystanki if _w_przebiegu(p)]
    # Punkt do Directions: punkt do odbicia, a gdy go nie ma — punkt ze Snap (`vroom`, [lng, lat]; dokładka po
    # re-review, odpowiednik M5: pinezka w pasie ok. 3 km — Snap ją przyciąga, Directions nie, 404/2010 → 502).
    # Bez Snap (błąd usługi) `vroom` = pinezka.
    srodek = [p.get('odbicie') or ((p['vroom'][1], p['vroom'][0]) if p.get('vroom') else p['punkt'])
              for p in w_przebiegu]
    odcinki = _odcinki_proste(przystanki)
    try:
        cecha = routing.zapytaj_przebieg([magazyn] + srodek + [magazyn], klucz, http_post, timeout=zegar.timeout())
        km, minuty = routing.km_i_minuty(cecha)
        km = round(km + routing.dlugosc_odcinkow_km(odcinki), 1)
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
    # Przystanek daleko od drogi: zapisany przebieg ma go w skrócie (i zwykle jest liniami prostymi) — nie pasuje.
    punkty = [magazyn] + [p['punkt'] for p in przystanki if _w_przebiegu(p)] + [magazyn]
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
        z_punktem_w_trasie = [p for p in przystanki if p['powod'] in (None, POWOD_PRZYBLIZONY)]
        for p in _przyciagnij(z_punktem_w_trasie, klucz, http_post, zegar):
            p['powod'] = POWOD_DALEKO
        kolejnosc, nieprzydzielone = _kolejnosc_vroom([p for p in optymalizowane if p['powod'] is None],
                                                      klucz, http_post, zegar)
        po_id = {p['order_id']: p for p in przystanki}
        for order_id in nieprzydzielone:
            po_id[order_id]['powod'] = POWOD_NIEOSIAGALNY
        # Nieosiągalne i daleko od drogi zostają w swojej dotychczasowej kolejności razem z innymi pominiętymi, na końcu.
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
        # Przystanki daleko od drogi: km i czas obu kolejności liczone bez nich.
        'poza_przebiegiem': sum(1 for p in nowe if p['powod'] == POWOD_DALEKO),
        # Odcinki proste w proponowanej kolejności (jak `podsumowanie.odcinki_proste` trasy): km przybliżone.
        'odcinki_proste': len(_odcinki_proste(nowe)),
    }
