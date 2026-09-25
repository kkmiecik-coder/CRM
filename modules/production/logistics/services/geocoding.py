# -*- coding: utf-8 -*-
"""
Geokodowanie adresów dostawy (spec, sekcja 7.1).

Kolejność: GUGiK UUG (oficjalne punkty adresowe PRG, tylko PL) → Nominatim →
przybliżenie do miejscowości → „nie znaleziono”. Do usług wysyłamy WYŁĄCZNIE
adres. Pułapki zmierzone 24.09.2026: kod pocztowy albo numer mieszkania
w zapytaniu GUGiK daje 0 trafień albo zły budynek; „Bachórz, Bachórz 14N”
nic nie znajduje, a „Bachórz 14N” trafia.

Ten moduł woła usługi wyłącznie z wątku w tle (timeout gunicorna 30 s).

Druga połowa modułu (od `KLUCZ_DZIERZAWY`) to geokoder ZAMÓWIEŃ: zapis wyniku
do `prod_order_geo`, dzierżawa „jeden proces na serwer” (jak `bl_sync`), wątek
w tle i ręczna korekta punktu z panelu logistyki.
"""
import hashlib
import threading
import time
import traceback
from collections import namedtuple
from datetime import datetime, timedelta

import requests
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics.adresy import (
    extract_house_and_apartment_number, usun_kod_pocztowy,
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


# ── Zamówienia: zapis, dzierżawa, wątek w tle, ręczna korekta (spec, sekcja 7.1) ──

KLUCZ_DZIERZAWY = 'logistyka_geo_dzierzawa'
CZAS_DZIERZAWY_S = 300  # jak bl_sync.CZAS_DZIERZAWY_S (przegląd etapu 1)
MAKS_PROB = 3
# R2 (kontroler): 3 awarie usług z rzędu w jednym przebiegu = usługi nie działają;
# zamówienia idą w kolejności id, więc bez tego limitu jedno zawieszone na starcie
# zamówienie głodziłoby WSZYSTKIE kolejne do końca przebiegu (same timeouty).
MAKS_BLEDOW_Z_RZEDU = 3


def _norm(tekst):
    return ' '.join((tekst or '').lower().split())


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
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    wynik = []
    for order in otwarte:
        punkt = geo.get(order.id)
        if punkt is None:
            wynik.append(order)
        elif punkt.source == 'reczna':
            continue
        elif punkt.address_hash != skrot_adresu(order):
            wynik.append(order)
        elif punkt.quality == 'nie_znaleziono' and punkt.attempts < MAKS_PROB:
            wynik.append(order)
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
                               http_get=http_get, spij=spij)
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
        for order in do_zlokalizowania(limit):
            try:
                punkt = zlokalizuj_zamowienie(order, http_get=http_get, spij=spij)
            except BladUslugi:
                db.session.rollback()
                wynik['bledy'] += 1
                bledy_z_rzedu += 1
            else:
                try:
                    db.session.commit()
                except IntegrityError:
                    # R6c: punkt ręczny na to samo zamówienie wszedł RÓWNOLEGLE
                    # (INSERT w innym procesie) między naszym odczytem z blokadą
                    # a tym commitem — nie licz jako błąd, po prostu pomiń.
                    db.session.rollback()
                else:
                    bledy_z_rzedu = 0
                    wynik['zamowienia'] += 1
                    wynik[_KLUCZE_WYNIKU[punkt.quality]] += 1
            # R2: dzierżawę odnawiamy PO KAŻDYM zamówieniu (sukces i błąd) — jedno
            # zamówienie w czasie awarii może zająć ~45 s samych timeoutów prób
            # (3 × GUGiK + Nominatim), a dzierżawa ma 300 s (odnawiana MIĘDZY
            # zamówieniami, nie w trakcie jednego, tak samo jak w bl_sync).
            znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
            if znacznik is None:
                break
            if bledy_z_rzedu >= MAKS_BLEDOW_Z_RZEDU:
                # Usługi nie odpowiadają — kolejne zamówienia w tym przebiegu i tak
                # by tylko paliły czas na timeoutach. Kolejny cron spróbuje od nowa.
                break
    finally:
        if znacznik:
            # sesja mogła trafić w stan błędu (nieobsłużony wyjątek nad tym try) —
            # bez rollbacku samo zwolnienie dzierżawy by się wywróciło i przepadła
            # na CZAS_DZIERZAWY_S zamiast zostać zwolniona od razu (jak w bl_sync)
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
    otwarte = _otwarte()
    geo = geo_zamowien([o.id for o in otwarte])
    return sum(1 for o in otwarte
               if geo.get(o.id) is None or geo[o.id].quality == 'nie_znaleziono')
