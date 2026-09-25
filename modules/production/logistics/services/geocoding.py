# -*- coding: utf-8 -*-
"""
Geokodowanie adresów dostawy (spec, sekcja 7.1).

Kolejność: GUGiK UUG (oficjalne punkty adresowe PRG, tylko PL) → Nominatim →
przybliżenie do miejscowości → „nie znaleziono”. Do usług wysyłamy WYŁĄCZNIE
adres. Pułapki zmierzone 24.09.2026: kod pocztowy albo numer mieszkania
w zapytaniu GUGiK daje 0 trafień albo zły budynek; „Bachórz, Bachórz 14N”
nic nie znajduje, a „Bachórz 14N” trafia. Zmierzone 25.09.2026: „Wola 12”
to 5 wsi w 5 województwach (każda accuracy 1), a „Floriańska 10 lok 5”
dawało budynek nr 5 — stąd R9 (wybór trafienia) i R10 (adres dla geokodera).

Ten moduł woła usługi wyłącznie z wątku w tle (timeout gunicorna 30 s).

Druga połowa modułu (od `KLUCZ_DZIERZAWY`) to geokoder ZAMÓWIEŃ: zapis wyniku
do `prod_order_geo`, dzierżawa „jeden proces na serwer” (jak `bl_sync`), wątek
w tle, postęp dla przycisku „Zlokalizuj teraz” i ręczna korekta punktu z panelu.
"""
import hashlib
import json
import math
import re
import threading
import time
import traceback
from collections import namedtuple
from datetime import datetime, timedelta

import requests
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics.adresy import (
    adres_do_geokodowania, extract_house_and_apartment_number,
)
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import dzierzawa
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, get_local_now

logger = get_structured_logger('production.logistics.geocoding')

MAGAZYN = {'lat': 49.840438, 'lng': 22.254053, 'nazwa': u'WoodPower — Bachórz 14N'}
GUGIK_URL = 'https://services.gugik.gov.pl/uug/'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'WoodPowerCRM/1.0 (+https://crm.woodpower.pl)'
TIMEOUT_S = 10
ODSTEP_NOMINATIM_S = 1.1
ODSTEP_GUGIK_S = 0.2
MIN_DOKLADNOSC_GUGIK = 0.6
# R9(b): kod klienta podany, ale żadne trafienie nie ma identycznego — zostają tylko
# trafienia z tym samym 2-cyfrowym prefiksem kodu i prawie pewne (np. „Bachórz 14N”
# z kodem 36-068 w Base., a w PRG 36-065). Niżej = zbyt często inna ulica / inna wieś.
MIN_DOKLADNOSC_BEZ_KODU = 0.9
# place_rank Nominatim: 30 = budynek, 28–29 = adres/obiekt, 26–27 = ulica, niżej obszar.
MIN_RANGA_DOKLADNA = 28
# Adres bez kodu pocztowego: Nominatim dostaje kilka wyników i jeśli leżą dalej od siebie
# niż ten próg, to adres jest niejednoznaczny — nie bierzemy żadnego. Zmierzone 25.09.2026:
# „Józefów” bez kodu → Nominatim oddał Józefów w lubelskim, a klient mieszka pod Otwockiem.
LIMIT_NOMINATIM_BEZ_KODU = 5
PROG_NIEJEDNOZNACZNOSCI_KM = 5
# Przedrostki pomijane przy porównaniu nazwy ulicy z nazwą z PRG (_ta_sama_ulica).
_PRZEDROSTKI_ULICY = frozenset(('ul', 'al', 'aleja', 'aleje', 'os', 'osiedle', 'pl', 'plac'))

Wynik = namedtuple('Wynik', 'lat lng source quality')
NIE_ZNALEZIONO = Wynik(None, None, None, 'nie_znaleziono')


class BladUslugi(Exception):
    """
    Usługa nie odpowiedziała — to nie jest „nie znaleziono”, nie zużywa próby.

    `pelna_awaria` (R7, kontroler): True, gdy w TYM wywołaniu `geokoduj_adres` ŻADNE
    zapytanie HTTP nie dostało odpowiedzi (realna awaria usług) — tylko taki przypadek
    ma się liczyć do serii przerywającej przebieg `lokalizuj` (patrz tam). False dla
    awarii CZĘŚCIOWEJ (np. GUGiK trwale pada dla jednego adresu, ale Nominatim
    odpowiedział — tylko przybliżeniem, które R3 każe odrzucić) — taki błąd nadal
    liczy się do `wynik['bledy']`, ale nie wydłuża ani nie zeruje serii: garstka
    trwale wadliwych starych zamówień inaczej zagłodziłaby wszystkie nowsze w tym
    samym przebiegu. Domyślnie True — bezpieczny (pesymistyczny) wariant dla wywołań
    spoza `geokoduj_adres` bez podania flagi.
    """

    def __init__(self, komunikat, pelna_awaria=True):
        super().__init__(komunikat)
        self.pelna_awaria = pelna_awaria


def _naglowki():
    return {'User-Agent': USER_AGENT, 'Accept-Language': 'pl'}


def _norm(tekst):
    return ' '.join((tekst or '').lower().split())


def _ostrzez_o_awarii(komunikat, blad, order_id):
    """
    M3 (prywatność logów): tekst wyjątku requests niesie pełny URL, a w nim adres
    klienta z query stringu — logujemy tylko klasę wyjątku i kod HTTP (jeśli jest).
    `order_id` pozwala odszukać zamówienie bez adresu w logu.
    """
    odpowiedz = getattr(blad, 'response', None)
    logger.warning(komunikat, extra={'blad': type(blad).__name__,
                                     'status_http': getattr(odpowiedz, 'status_code', None),
                                     'order_id': order_id})


def zapytania_gugik(adres, miasto):
    """Kandydaci zapytań do GUGiK (bez kodu i bez numeru/oznaczenia lokalu — R10) oraz numer domu."""
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(
        adres_do_geokodowania(adres, miasto))
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


def _wspolrzedne(lat, lng):
    """(lat, lng) jako float albo None — I1: puste, nieliczbowe, NaN i spoza zakresu odpadają."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    # NaN nie spełnia żadnego porównania, więc odpada tu razem z wartościami spoza zakresu.
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _wspolrzedne_trafienia(trafienie):
    return _wspolrzedne(trafienie.get('y'), trafienie.get('x'))


def _trafienia(odpowiedz, typ):
    """
    Trafienia GUGiK danego typu z poprawnymi współrzędnymi. I1: trafienie bez
    czytelnych x/y pomijamy (rzucało ValueError poza try i przerywało cały przebieg,
    a następny przebieg — ta sama kolejność — znów na nim).
    """
    if not isinstance(odpowiedz, dict) or odpowiedz.get('type') != typ:
        return []
    wyniki = odpowiedz.get('results')
    if isinstance(wyniki, dict):
        wyniki = list(wyniki.values())
    elif not isinstance(wyniki, list):
        return []
    return [t for t in wyniki if isinstance(t, dict) and _wspolrzedne_trafienia(t) is not None]


def _cyfry_kodu(kod):
    return re.sub(r'\D', '', str(kod or ''))


def _miejscowosc(trafienie):
    """
    Klucz miejscowości trafienia (R9): teryt, gdy GUGiK go podaje, inaczej nazwa.
    Para (teryt, nazwa), a nie sam teryt: dwie różne wsie o tym samym teryt (jeśli
    to kod gminy) też są niejednoznaczne. Floriańska i Ariańska (obie Kraków, 126101)
    zostają jedną miejscowością.
    """
    return (str(trafienie.get('teryt') or '').strip(), _norm(str(trafienie.get('city') or '')))


def _jednoznaczne(trafienia):
    """Najdokładniejsze trafienie, gdy wszystkie leżą w jednej miejscowości; inaczej None."""
    if not trafienia or len({_miejscowosc(t) for t in trafienia}) > 1:
        return None
    return max(trafienia, key=_dokladnosc)


def _slowa_ulicy(tekst):
    return [s for s in re.findall(r'\w+', (tekst or '').lower()) if s not in _PRZEDROSTKI_ULICY]


def _ta_sama_ulica(trafienie, ulica, miasto):
    """
    Ta sama miejscowość i ta sama ulica zapisana pełniej albo krócej: słowa krótszej
    nazwy kończą dłuższą („Jana Onufrego Zagłoby” ↔ „Zagłoby” z PRG). GUGiK liczy
    `accuracy` z podobieństwa tekstu, więc pełna nazwa ulicy zaniża ją poniżej progu
    (zmierzone 25.09.2026: 0.59 dla właściwego punktu w Józefowie).
    """
    miasto = _norm(miasto)
    if not miasto or _norm(str(trafienie.get('city') or '')) != miasto:
        return False
    z_prg, z_zamowienia = _slowa_ulicy(trafienie.get('street')), _slowa_ulicy(ulica)
    if not z_prg or not z_zamowienia:
        return False
    krotsza, dluzsza = sorted((z_prg, z_zamowienia), key=len)
    return dluzsza[-len(krotsza):] == krotsza


def wybierz_trafienie(odpowiedz, numer, kod, ulica=None, miasto=None):
    """
    Punkt adresowy GUGiK z tym samym numerem domu — R9 (kontroler, wiążące):
    (a) są trafienia z identycznym kodem → najlepsza dokładność spośród nich;
    (b) kod podany, żadne trafienie go nie ma → tylko ten sam 2-cyfrowy prefiks kodu
        i dokładność >= MIN_DOKLADNOSC_BEZ_KODU;
    (c) kod niepodany → dokładność >= MIN_DOKLADNOSC_GUGIK albo ta sama miejscowość
        i ulica (`_ta_sama_ulica`, gdy podano `ulica` i `miasto` zamówienia).
    W (b) i (c) trafienia w więcej niż jednej miejscowości = brak wyniku (None) —
    wtedy Nominatim z kodem. Kody porównujemy po cyfrach („31021” == „31-021”).
    """
    numer = str(numer or '').lower()
    if not numer:
        return None
    pasujace = [t for t in _trafienia(odpowiedz, 'address')
                if str(t.get('number') or '').lower() == numer]
    kod = _cyfry_kodu(kod)
    if kod:
        z_kodem = [t for t in pasujace if _cyfry_kodu(t.get('code')) == kod]
        if z_kodem:
            return max(z_kodem, key=_dokladnosc)
        kandydaci = [t for t in pasujace
                     if _cyfry_kodu(t.get('code'))[:2] == kod[:2]
                     and _dokladnosc(t) >= MIN_DOKLADNOSC_BEZ_KODU]
    else:
        kandydaci = [t for t in pasujace if _dokladnosc(t) >= MIN_DOKLADNOSC_GUGIK
                     or _ta_sama_ulica(t, ulica, miasto)]
    return _jednoznaczne(kandydaci)


def wybierz_miejscowosc(odpowiedz):
    """Przybliżenie do miejscowości z GUGiK — tylko przy jednej miejscowości (R9(e))."""
    return _jednoznaczne(_trafienia(odpowiedz, 'city'))


def _gugik(zapytanie, http_get):
    odp = http_get(GUGIK_URL, params={'request': 'GetAddress', 'address': zapytanie, 'srid': '4326'},
                   timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    return odp.json() or {}


def odleglosc_km(a, b):
    """Przybliżenie równoprostokątne — na skalę kraju wystarcza do progu kilku km."""
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371 * math.hypot(x, y)


# Alias dla wstecznej kompatybilności — używany przez testy etapu 2
_odleglosc_km = odleglosc_km


def _nominatim(parametry, http_get):
    """
    (lat, lng, dokładny) albo None. Bez kodu pocztowego pytamy o kilka wyników:
    rozrzucone dalej niż PROG_NIEJEDNOZNACZNOSCI_KM = adres niejednoznaczny = None.
    """
    params = {k: v for k, v in parametry.items() if v}
    bez_kodu = not params.get('postalcode')
    params.update({'format': 'jsonv2', 'limit': LIMIT_NOMINATIM_BEZ_KODU if bez_kodu else 1})
    odp = http_get(NOMINATIM_URL, params=params, timeout=TIMEOUT_S, headers=_naglowki())
    odp.raise_for_status()
    dane = odp.json()
    # I1: odpowiedź, której nie umiemy odczytać (słownik z błędem, brak lat/lon, tekst
    # zamiast liczby), to ODPOWIEDŹ usługi = brak wyniku, a nie awaria. Awaria nie
    # zużywa próby, więc taki adres wracałby do usług w każdym przebiegu bez końca.
    if not isinstance(dane, list) or not dane or not isinstance(dane[0], dict):
        return None
    punkt = _wspolrzedne(dane[0].get('lat'), dane[0].get('lon'))
    if punkt is None:
        return None
    if bez_kodu:
        inne = [_wspolrzedne(d.get('lat'), d.get('lon')) for d in dane[1:] if isinstance(d, dict)]
        if any(p is not None and odleglosc_km(punkt, p) > PROG_NIEJEDNOZNACZNOSCI_KM
               for p in inne):
            return None
    try:
        ranga = int(dane[0].get('place_rank') or 0)
    except (TypeError, ValueError):
        ranga = 0
    return punkt[0], punkt[1], ranga >= MIN_RANGA_DOKLADNA


def geokoduj_adres(adres, miasto, kod, kraj, http_get=requests.get, spij=time.sleep,
                   order_id=None):
    # M2: „ pl” / „PL ” z Base. to też Polska; countrycodes dla Nominatim bez spacji.
    kraj = (kraj or '').strip().upper() or 'PL'
    miasto = (miasto or '').strip()
    kod = (kod or '').strip() or None
    awaria = False
    # R7 (kontroler): czy JAKAKOLWIEK usługa w tym wywołaniu w ogóle odpowiedziała —
    # odróżnia PEŁNĄ awarię (nic nie odpowiedziało, prawdziwy outage) od awarii
    # CZĘŚCIOWEJ (np. trwale wadliwy jeden adres w GUGiK, usługi ogólnie działają).
    # Patrz `BladUslugi.pelna_awaria`.
    byla_odpowiedz = False
    numer, _mieszkanie, ulica = extract_house_and_apartment_number(
        adres_do_geokodowania(adres, miasto))

    # 1. GUGiK — dokładny punkt adresowy (tylko Polska). R9(d): bez miasta i bez kodu
    # zapytanie jest ogólnopolskie, a więc niejednoznaczne — wtedy od razu Nominatim.
    if kraj == 'PL' and (miasto or kod):
        kandydaci, numer_gugik = zapytania_gugik(adres, miasto)
        for zapytanie in kandydaci:
            spij(ODSTEP_GUGIK_S)
            try:
                odpowiedz = _gugik(zapytanie, http_get)
            except Exception as e:
                awaria = True
                _ostrzez_o_awarii("GUGiK nie odpowiedzial", e, order_id)
                continue
            byla_odpowiedz = True
            trafienie = wybierz_trafienie(odpowiedz, numer_gugik, kod, ulica=ulica, miasto=miasto)
            if trafienie:
                lat, lng = _wspolrzedne_trafienia(trafienie)
                return Wynik(lat, lng, 'gugik', 'dokladna')

    # 2. Nominatim — adres strukturalny. Wynik dokładny wracamy zawsze (nawet po
    # awarii GUGiK-a wyżej) — to wciąż najlepszy możliwy do zdobycia w tym wywołaniu.
    ulica_z_numerem = (u'{} {}'.format(ulica, numer) if numer else (ulica or '')).strip()
    if ulica_z_numerem:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'street': ulica_z_numerem, 'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            _ostrzez_o_awarii("Nominatim nie odpowiedzial", e, order_id)
        else:
            byla_odpowiedz = True
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
        raise BladUslugi(u'Usługa geokodowania nie odpowiedziała', pelna_awaria=not byla_odpowiedz)

    # 3. Przybliżenie do miejscowości. R9(e): z GUGiK tylko przy jednej miejscowości
    # („Nowa Wieś” to wiele wsi) — inaczej Nominatim z miastem i kodem.
    if kraj == 'PL' and miasto:
        spij(ODSTEP_GUGIK_S)
        try:
            odpowiedz = _gugik(miasto, http_get)
        except Exception as e:
            awaria = True
            _ostrzez_o_awarii("GUGiK (miejscowosc) nie odpowiedzial", e, order_id)
        else:
            byla_odpowiedz = True
            miejscowosc = wybierz_miejscowosc(odpowiedz)
            if miejscowosc:
                lat, lng = _wspolrzedne_trafienia(miejscowosc)
                return Wynik(lat, lng, 'gugik', 'przyblizona')
            if not kod and _trafienia(odpowiedz, 'city'):
                # Kilka miejscowości o tej nazwie, a kodu brak — Nominatim wskazałby
                # którąkolwiek z nich. Zły punkt „przybliżony” myli bardziej niż brak
                # punktu: logistyk ustawi go ręcznie („Bez lokalizacji”).
                return NIE_ZNALEZIONO

        # R3 (poprawka po przeglądzie, runda 1): krok 3 ma DWIE usługi z rzędu —
        # awaria pierwszej (GUGiK-miejscowość) nie może zostać zamaskowana sukcesem
        # drugiej (Nominatim-miejscowość). Bez tej kontroli kod niżej i tak zwróciłby
        # przybliżenie z Nominatim, mimo że w tym wywołaniu już coś padło. Kończymy
        # od razu — jedno zapytanie do Nominatim mniej.
        if awaria:
            raise BladUslugi(u'Usługa geokodowania nie odpowiedziała', pelna_awaria=not byla_odpowiedz)
    if miasto or kod:
        spij(ODSTEP_NOMINATIM_S)
        try:
            punkt = _nominatim({'city': miasto, 'postalcode': kod,
                                'countrycodes': kraj.lower()}, http_get)
        except Exception as e:
            awaria, punkt = True, None
            _ostrzez_o_awarii("Nominatim (miejscowosc) nie odpowiedzial", e, order_id)
        else:
            byla_odpowiedz = True
        if punkt:
            return Wynik(punkt[0], punkt[1], 'nominatim', 'przyblizona')

    if awaria:
        raise BladUslugi(u'Usługa geokodowania nie odpowiedziała', pelna_awaria=not byla_odpowiedz)
    return NIE_ZNALEZIONO


# ── Zamówienia: zapis, dzierżawa, wątek w tle, ręczna korekta (spec, sekcja 7.1) ──

KLUCZ_DZIERZAWY = 'logistyka_geo_dzierzawa'
# UF3: postęp trwającego przebiegu dla przycisku „Zlokalizuj teraz” — JSON
# {"wszystkie": N, "zrobione": k, "od": "<ISO>"}, '' gdy nic nie biegnie.
KLUCZ_POSTEPU = 'logistyka_geo_postep'
CZAS_DZIERZAWY_S = 300  # jak bl_sync.CZAS_DZIERZAWY_S (przegląd etapu 1)
MAKS_PROB = 3
# R2 (kontroler): 3 PEŁNE awarie usług z rzędu w jednym przebiegu = usługi nie
# działają; bez tego limitu jedno zawieszone na starcie zamówienie głodziłoby
# WSZYSTKIE kolejne do końca przebiegu (same timeouty). R7 (kontroler): liczą się
# TYLKO pełne awarie (BladUslugi.pelna_awaria) — awaria częściowa i nieoczekiwany
# wyjątek jednego zamówienia serii nie wydłużają.
MAKS_BLEDOW_Z_RZEDU = 3
# Ile razy przebieg dobiera zamówienia dodane albo zmienione w jego trakcie (patrz
# `lokalizuj`). Zwykle wystarcza jedno–dwa dobrania; limit tylko na wypadek adresu,
# który zmienia się w kółko, żeby przebieg nie trzymał dzierżawy bez końca.
MAKS_DOBRAN = 10


def skrot_adresu(order):
    tekst = '|'.join(_norm(x) for x in (order.delivery_address, order.delivery_postcode,
                                         order.delivery_city, order.delivery_country_code))
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()


def _ma_adres(order):
    return any((x or '').strip() for x in (order.delivery_address, order.delivery_city,
                                            order.delivery_postcode))


def geo_zamowien(order_ids):
    if not order_ids:
        return {}
    return {geo.order_id: geo for geo in
            OrderGeo.query.filter(OrderGeo.order_id.in_(list(order_ids))).all()}


def _otwarte():
    return (ProductionOrder.query.filter(ProductionOrder.logistics_closed_at.is_(None))
            .order_by(ProductionOrder.id).all())


def oznacz_zmienione_reczne():
    """Punkt ręczny + inny adres w Base. → tylko ikona. Zwraca liczbę nowo oznaczonych."""
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    zmienione = 0
    for order in otwarte:
        punkt = geo.get(order.id)
        if (punkt is not None and punkt.source == 'reczna'
                and not punkt.address_changed_after_manual
                and punkt.address_hash != skrot_adresu(order)):
            punkt.address_changed_after_manual = True
            zmienione += 1
    return zmienione


def do_zlokalizowania(limit=None):
    """
    R11 (kontroler): najpierw zamówienia bez punktu i ze zmienionym adresem, potem
    ponowienia „nie znaleziono” (attempts < MAKS_PROB); w obrębie grup po id. Świeże
    zamówienia nie czekają za stertą starych adresów, których usługi i tak nie znają.
    """
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    nowe, ponowienia = [], []
    for order in otwarte:
        punkt = geo.get(order.id)
        if punkt is None:
            nowe.append(order)
        elif punkt.source == 'reczna':
            continue
        elif punkt.address_hash != skrot_adresu(order):
            nowe.append(order)
        elif punkt.quality == 'nie_znaleziono' and punkt.attempts < MAKS_PROB:
            ponowienia.append(order)
    wynik = nowe + ponowienia
    return wynik[:limit] if limit else wynik


def zlokalizuj_zamowienie(order, http_get=requests.get, spij=time.sleep):
    """
    Zapisuje wynik do sesji (bez commita). BladUslugi przechodzi wyżej.

    R6 (kontroler): `do_zlokalizowania()` liczy się na starcie przebiegu, który
    może trwać minuty — logistyk w tym czasie może kliknąć „Ustaw na mapie”
    akurat na zamówieniu z tej listy (bez punktu → jest na liście). Punkt
    ręczny nie może zostać nadpisany, więc sprawdzamy go DWA razy: na wejściu
    (bez pytania usług) i tuż przed zapisem, świeżym odczytem z blokadą. Nowy
    wiersz dodajemy do sesji DOPIERO po tym drugim sprawdzeniu (nie wcześniej) —
    wcześniejsze `db.session.add()` z niewypełnionym jeszcze `quality` (NOT NULL)
    padłoby na autoflushu, gdyby coś po drodze (np. `ustaw_recznie` wywołane
    w międzyczasie) odpytało tę samą tabelę.
    """
    punkt = OrderGeo.query.get(order.id)
    if punkt is not None and punkt.source == 'reczna':
        return punkt

    skrot = skrot_adresu(order)
    proby = (punkt.attempts or 0) if (punkt is not None and punkt.address_hash == skrot) else 0
    if not _ma_adres(order):
        # Brak adresu (np. odbiór osobisty) — nie pytamy usług i nie próbujemy w kółko.
        wynik = NIE_ZNALEZIONO
        nowe_proby = MAKS_PROB
    else:
        wynik = geokoduj_adres(order.delivery_address, order.delivery_city,
                               order.delivery_postcode, order.delivery_country_code,
                               http_get=http_get, spij=spij, order_id=order.id)
        nowe_proby = proby + 1 if wynik.quality == 'nie_znaleziono' else 0

    # R6: usługi (zwłaszcza przy awarii — do ~10 s timeoutu na próbę) mogły trwać
    # długo — logistyk mógł w tym czasie ustawić punkt ręcznie na TYM zamówieniu.
    # Świeży odczyt z blokadą, mimo identity map (populate_existing): w InnoDB
    # odczyt z FOR UPDATE widzi ostatni ZACOMMITOWANY wiersz mimo REPEATABLE READ;
    # w SQLite (testy) FOR UPDATE jest ignorowane, co tu nie szkodzi.
    swiezy = (OrderGeo.query.filter_by(order_id=order.id)
              .with_for_update().populate_existing().first())
    if swiezy is not None and swiezy.source == 'reczna':
        return swiezy

    punkt = swiezy
    if punkt is None:
        punkt = OrderGeo(order_id=order.id)
        db.session.add(punkt)
    punkt.attempts = nowe_proby
    punkt.lat, punkt.lng = wynik.lat, wynik.lng
    punkt.source, punkt.quality = wynik.source, wynik.quality
    punkt.address_hash = skrot
    punkt.address_changed_after_manual = False
    return punkt


_KLUCZE_WYNIKU = {'dokladna': 'dokladne', 'przyblizona': 'przyblizone',
                  'nie_znaleziono': 'nie_znaleziono'}


def _ostrzez_o_zawieszonej_dzierzawie(teraz=None):
    """Jak bl_sync._ostrzez_o_zawieszonej_dzierzawie — ta sama logika i powód,
    patrz tam docstring. Osobna funkcja: własny klucz i log dla geokodera."""
    teraz = teraz or get_local_now()
    wartosc = dzierzawa.wiersz(KLUCZ_DZIERZAWY).config_value
    try:
        waznosc = datetime.fromisoformat(wartosc)
    except (TypeError, ValueError):
        return
    if waznosc > teraz + timedelta(seconds=2 * CZAS_DZIERZAWY_S):
        logger.warning("Dzierzawa geokodera zawieszona w przyszlosci - "
                       "geokodowanie stoi do jej wygasniecia", extra={
                           'klucz': KLUCZ_DZIERZAWY, 'waznosc_do': wartosc,
                           'teraz': teraz.replace(microsecond=0).isoformat()})


def _zapisz_postep(postep):
    dzierzawa.zapisz(KLUCZ_POSTEPU, json.dumps(postep))


def _przetworz_zamowienie(order_id, order, wynik, http_get, spij):
    """
    Jedno zamówienie przebiegu `lokalizuj` razem z commitem. Zwraca zmianę serii
    pełnych awarii: 'awaria' (seria +1), 'sukces' (seria od zera) albo None (bez zmian).

    I1: nieoczekiwany wyjątek jednego zamówienia (np. zły rekord, równoległe usunięcie
    zamówienia) nie przerywa przebiegu — inaczej każdy kolejny przebieg padałby na tym
    samym zamówieniu i nowsze nie dostałyby punktu nigdy. Nie liczy się do serii
    pełnych awarii (to nie jest awaria usług).
    """
    try:
        punkt = zlokalizuj_zamowienie(order, http_get=http_get, spij=spij)
        # I1: źródło i jakość czytamy PRZED commitem — po nim obiekt jest wygaszony,
        # a równoległy reset (DELETE z panelu) dałby przy odczycie ObjectDeletedError.
        zrodlo, jakosc = punkt.source, punkt.quality
        try:
            db.session.commit()
        except IntegrityError as e:
            # R6c: punkt ręczny na to samo zamówienie wszedł RÓWNOLEGLE (INSERT
            # w innym procesie) między naszym odczytem z blokadą a tym commitem — nie
            # licz jako błąd, po prostu pomiń. Log, żeby błąd systematyczny (nie tylko
            # ten rzadki wyścig) zostawił ślad.
            db.session.rollback()
            logger.warning("Zapis geokodowania odrzucony (IntegrityError) - pominieto "
                           "zamowienie", extra={'order_id': order_id, 'error': str(e)})
            return None
    except BladUslugi as e:
        db.session.rollback()
        wynik['bledy'] += 1
        # R7: tylko PEŁNA awaria (żadna usługa w tym wywołaniu nie odpowiedziała)
        # liczy się do serii przerywającej przebieg. Awaria częściowa nadal trafia do
        # 'bledy', ale ani nie wydłuża, ani nie zeruje serii — patrz BladUslugi.
        return 'awaria' if e.pelna_awaria else None
    except Exception as e:
        db.session.rollback()
        wynik['bledy'] += 1
        logger.error("Geokodowanie zamowienia przerwane bledem - pominieto, przebieg trwa",
                     extra={'order_id': order_id, 'blad': type(e).__name__,
                            'traceback': traceback.format_exc()})
        return None
    # R6(c): zlokalizuj_zamowienie mogła oddać ISTNIEJĄCY punkt ręczny bez żadnego
    # zapisu (na wejściu albo po świeżym odczycie z blokadą — ona sama NIGDY nie
    # zapisuje source='reczna'). To nie jest geokodowanie: nie liczymy go do wyników
    # i zostawiamy serię błędów bez zmian (ani nie rośnie, ani się nie zeruje).
    if zrodlo == 'reczna':
        return None
    wynik['zamowienia'] += 1
    wynik[_KLUCZE_WYNIKU[jakosc]] += 1
    return 'sukces'


def lokalizuj(limit=None, http_get=requests.get, spij=time.sleep):
    wynik = {'zamowienia': 0, 'dokladne': 0, 'przyblizone': 0, 'nie_znaleziono': 0,
             'bledy': 0, 'dzierzawa': False}
    znacznik = dzierzawa.przejmij(KLUCZ_DZIERZAWY, CZAS_DZIERZAWY_S)
    if znacznik is None:
        _ostrzez_o_zawieszonej_dzierzawie()
        return wynik
    wynik['dzierzawa'] = True
    bledy_z_rzedu = 0
    try:
        oznacz_zmienione_reczne()
        db.session.commit()
        # Identyfikatory i skróty adresów od razu, póki obiekty są świeże: po commicie
        # każdego zamówienia reszta listy jest wygaszona, a odczyt `order.id` usuniętego
        # zamówienia rzuciłby.
        kolejka = [(o.id, o, skrot_adresu(o)) for o in do_zlokalizowania(limit)]
        # order_id → skrót adresu, z którym zamówienie weszło do tego przebiegu
        przerobione = {}
        postep = {'wszystkie': len(kolejka), 'zrobione': 0,
                  'od': get_local_now().replace(microsecond=0).isoformat()}
        _zapisz_postep(postep)
        dobrania = przetworzono = 0
        while kolejka:
            przerwano = False
            for order_id, order, skrot in kolejka:
                przerobione[order_id] = skrot
                przetworzono += 1
                zmiana = _przetworz_zamowienie(order_id, order, wynik, http_get, spij)
                if zmiana == 'awaria':
                    bledy_z_rzedu += 1
                elif zmiana == 'sukces':
                    bledy_z_rzedu = 0
                # R2: dzierżawę odnawiamy PO KAŻDYM zamówieniu (sukces i błąd) — jedno
                # zamówienie w czasie awarii może zająć ~45 s samych timeoutów prób
                # (3 × GUGiK + Nominatim), a dzierżawa ma 300 s (odnawiana MIĘDZY
                # zamówieniami, nie w trakcie jednego, tak samo jak w bl_sync).
                znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
                if znacznik is None:
                    przerwano = True
                    break
                # UF3: po KAŻDYM zamówieniu, niezależnie od wyniku (sukces, nie
                # znaleziono, błąd, pominięty punkt ręczny). Po odnowieniu dzierżawy —
                # gdy ją straciliśmy, postęp należy już do innego procesu.
                postep['zrobione'] += 1
                _zapisz_postep(postep)
                if bledy_z_rzedu >= MAKS_BLEDOW_Z_RZEDU:
                    # Usługi nie odpowiadają — kolejne zamówienia w tym przebiegu i tak
                    # by tylko paliły czas na timeoutach. Kolejny cron spróbuje od nowa.
                    logger.warning("Seria pelnych awarii uslug geokodowania - przebieg przerwany",
                                   extra={'bledy_z_rzedu': bledy_z_rzedu})
                    przerwano = True
                    break
            if przerwano or dobrania >= MAKS_DOBRAN:
                break
            # R11: przebieg trwa minuty — zamówienie dodane, zresetowane albo z adresem
            # poprawionym w tym czasie (dwuklik w adres na liście) nie czeka godziny do
            # następnego crona. Dobieramy tak długo, aż nic nie przybędzie. Przerobione
            # w tym przebiegu wracają TYLKO ze zmienionym od tamtej pory adresem — to
            # samo zamówienie z błędem usługi czy „nie znaleziono” czeka na kolejny.
            dobrania += 1
            pozostalo = limit - przetworzono if limit else None
            if pozostalo is not None and pozostalo <= 0:
                break
            kolejka = []
            for o in do_zlokalizowania():
                skrot = skrot_adresu(o)
                if przerobione.get(o.id) != skrot:
                    kolejka.append((o.id, o, skrot))
            if pozostalo is not None:
                kolejka = kolejka[:pozostalo]
            if kolejka:
                postep['wszystkie'] += len(kolejka)
                _zapisz_postep(postep)
    finally:
        if znacznik:
            # sesja mogła trafić w stan błędu (nieobsłużony wyjątek nad tym try) —
            # bez rollbacku samo zwolnienie dzierżawy by się wywróciło i przepadła
            # na CZAS_DZIERZAWY_S zamiast zostać zwolniona od razu (jak w bl_sync)
            try:
                if not db.session.is_active:
                    db.session.rollback()
                # UF3: postęp czyścimy PRZED zwolnieniem dzierżawy — po zwolnieniu
                # pisze go już następny przebieg (inny proces), a my byśmy mu go wymazali.
                dzierzawa.zapisz(KLUCZ_POSTEPU, '')
            except Exception as e:
                # nieudane czyszczenie nie może zablokować zwolnienia dzierżawy niżej
                # (ona ma własny rollback); osierocony wpis i tak jest niewidoczny,
                # bo postep() wymaga żywej dzierżawy
                logger.error("Nie udalo sie wyczyscic postepu geokodera", extra={
                    'error': str(e), 'traceback': traceback.format_exc()})
            try:
                if not db.session.is_active:
                    db.session.rollback()
                dzierzawa.zwolnij(KLUCZ_DZIERZAWY, znacznik)
            except Exception as e:
                # nigdy nie maskujemy oryginalnego wyjątku (jeśli jakiś leci) — tylko log
                logger.error("Nie udalo sie zwolnic dzierzawy geokodera", extra={
                    'error': str(e), 'traceback': traceback.format_exc()})
    logger.info("Geokodowanie zamowien zakonczone", extra=wynik)
    return wynik


def geokoder_dziala(teraz=None):
    teraz = teraz or get_local_now()
    db.session.expire_all()
    try:
        return datetime.fromisoformat(dzierzawa.wiersz(KLUCZ_DZIERZAWY).config_value) > teraz
    except ValueError:
        return False


def postep(teraz=None):
    """
    UF3: {'zrobione': k, 'wszystkie': N} trwającego przebiegu albo None. Tylko przy
    żywej dzierżawie — wpis osierocony przez padnięty proces (bez `finally`) znika
    sam, gdy dzierżawa wygaśnie. Nieczytelna wartość to też None, nie błąd listy.
    """
    if not geokoder_dziala(teraz):
        return None
    try:
        dane = json.loads(dzierzawa.wiersz(KLUCZ_POSTEPU).config_value or '')
        zrobione, wszystkie = dane['zrobione'], dane['wszystkie']
    except (TypeError, ValueError, KeyError):
        return None
    # bool to podklasa int — true/false w JSON-ie nie jest licznikiem
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0
               for x in (zrobione, wszystkie)):
        return None
    return {'zrobione': zrobione, 'wszystkie': wszystkie}


_watek = None
_blokada_watku = threading.Lock()


def uruchom_w_tle(app):
    """Jeden wątek na proces; między procesami porządku pilnuje dzierżawa."""
    global _watek
    with _blokada_watku:
        if _watek is not None and _watek.is_alive():
            return False

        def _praca():
            with app.app_context():
                try:
                    lokalizuj()
                except Exception as e:
                    # StructuredLogger.error ignoruje exc_info (jak w bl_sync) —
                    # traceback wprost w extra, żeby wątek w tle zostawił ślad.
                    logger.error("Geokoder logistyki przerwany", extra={
                        'error': str(e), 'traceback': traceback.format_exc()})
                finally:
                    db.session.remove()

        _watek = threading.Thread(target=_praca, name='logistyka-geo', daemon=True)
        _watek.start()
        return True


def ustaw_recznie(order, lat, lng):
    # M1: bool to podklasa int — true/false z JSON-a przeszłyby jako 1.0/0.0
    # (to samo zabezpieczenie co identyfikatory w delivery_method).
    if isinstance(lat, bool) or isinstance(lng, bool):
        raise LogistykaBlad(u'Nieprawidłowe współrzędne.', status=422)
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise LogistykaBlad(u'Nieprawidłowe współrzędne.', status=422)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise LogistykaBlad(u'Współrzędne poza zakresem.', status=422)
    punkt = OrderGeo.query.get(order.id)
    if punkt is None:
        punkt = OrderGeo(order_id=order.id)
        db.session.add(punkt)
    punkt.lat, punkt.lng = round(lat, 6), round(lng, 6)
    punkt.source, punkt.quality = 'reczna', 'dokladna'
    punkt.address_hash = skrot_adresu(order)
    punkt.address_changed_after_manual = False
    punkt.attempts = 0
    return punkt


def resetuj(order):
    """Usuwa punkt (też ręczny) — zamówienie wraca do automatu przy najbliższym przebiegu."""
    OrderGeo.query.filter_by(order_id=order.id).delete(synchronize_session=False)


def bez_lokalizacji():
    """
    Otwarte zamówienia bez punktu albo z „nie znaleziono”. M5: jedno COUNT z outer
    joinem zamiast ładowania wszystkich otwartych zamówień jako pełnych wierszy ORM —
    otwarta zakładka Logistyka odpytuje listę co kilka sekund.
    """
    return (db.session.query(func.count(ProductionOrder.id))
            .outerjoin(OrderGeo, OrderGeo.order_id == ProductionOrder.id)
            .filter(ProductionOrder.logistics_closed_at.is_(None),
                    or_(OrderGeo.order_id.is_(None), OrderGeo.quality == 'nie_znaleziono'))
            .scalar()) or 0
