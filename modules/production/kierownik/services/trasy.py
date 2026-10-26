# -*- coding: utf-8 -*-
"""
Trasy transportu własnego na tablecie kierownika hali (kontrakt: docs/api-mobile-kierownik.md §8.1 i §8.2).

To CZYSTE ODCZYTY. Panel tras (`trasy_api`) przelicza przebieg w samym GET (`routing.przelicz` może zapytać
OpenRouteService po HTTP, a potem commituje) — tu nic takiego się nie dzieje: przebieg to ostatnia geometria
zapisana w trasie (`routing.przebieg`), a to, czy jeszcze pasuje do przystanków, mówi czysta funkcja
`routing.przebieg_nieaktualny` (skrót punktów, bez sieci i bez zapisu). Jedyny zapis żądania kierownika to znacznik
kontaktu urządzenia w `require_device_token`.

Kierownik widzi więcej niż telefon kierowcy: także trasę `robocza` (telefon jej nie widzi) i przystanki zamówień
anulowanych. DTO budujemy od zera, pole po polu: przystanek ma klienta, firmę, miasto i punkt na mapie, a NIGDY ulicy,
telefonu ani e-maila (biała lista: `biala_lista.ZAKAZANE_KLUCZE`). Dane przystanków z `dostawa_widok.wczytaj`
(ten sam czysty odczyt, co GET Dostawy), nagłówek trasy z `routes.serializuj_trase` (ten sam, co lista panelu).
"""
import hashlib
import json

from extensions import db
from modules.production.kierownik.services import zamowienia as zam
from modules.production.logistics.models import STATUSY_TRASY
from modules.production.logistics.services import delivery, dostawa, dostawa_widok, geocoding, paczki, routes, routing
from modules.production.models import ProductionOrder
from modules.production.utils.cache import make_weak_etag

# Wersja kształtu odpowiedzi: wchodzi do ETagu, więc zmiana DTO unieważnia pamięć podręczną tabletów.
KSZTALT_TRAS = 2

# Kolejność sekcji listy (kontrakt §8.1): najpierw to, co dzieje się teraz. Inna niż w panelu tras
# (`routes.KOLEJNOSC_STATUSOW`: robocze na górze) — kierownik zaczyna od tras w drodze.
KOLEJNOSC_STATUSOW = {'w_trasie': 0, 'zaladowana': 1, 'zatwierdzona': 2, 'robocza': 3, 'wykonana': 4}

# Klucze `podsumowania` z kontraktu; reszta (liczba anulowanych, liczba odcinków prostych) zostaje w panelu.
KLUCZE_PODSUMOWANIA = ('przystanki', 'm3', 'waga_kg', 'bez_lokalizacji', 'przekroczona_ladownosc')


class BladParametru(zam.BladParametru):
    """Zły parametr zapytania; komunikat jest zdaniem po polsku do pokazania (odpowiedź 400 `dane_niepoprawne`)."""


# ── parametry ────────────────────────────────────────────────────────────────────────────────────────────────────

def _data(surowa, nazwa):
    tekst = (surowa or '').strip()
    if not tekst:
        return None
    try:
        return routes.parsuj_date(tekst)
    except ValueError:
        raise BladParametru(u'Parametr %s musi być datą w formacie RRRR-MM-DD.' % nazwa)


def wczytaj_parametry(args):
    """Parametry zapytania (`request.args`) → argumenty `lista()`; zły parametr = `BladParametru`."""
    status = (args.get('status') or '').strip() or None
    if status is not None and status not in STATUSY_TRASY:
        raise BladParametru(u'Nieznany status trasy: %s.' % status)
    od, do = _data(args.get('od'), 'od'), _data(args.get('do'), 'do')
    if od is not None and do is not None and od > do:
        raise BladParametru(u'Data od nie może być późniejsza niż do.')
    return {'status': status, 'od': od, 'do': do}


# ── klocki DTO ───────────────────────────────────────────────────────────────────────────────────────────────────

# Klucze `postep` z kontraktu §8.1; nowe pola panelu nie trafiają na tablet bez decyzji.
KLUCZE_POSTEPU = ('przystanki', 'zaladowane', 'dostarczone', 'niedostarczone', 'zdjete')


def _kierowca(kierowca):
    """Kierowca z §8.1: tylko `id` i `nazwa`, pole po polu (telefon czy inne dane kierowcy nigdy nie wchodzą)."""
    if kierowca is None:
        return None
    return {'id': kierowca['id'], 'nazwa': kierowca['nazwa']}


def _postep(postep):
    """Postęp Dostawy z §8.1: wyłącznie klucze z `KLUCZE_POSTEPU`."""
    return {klucz: postep[klucz] for klucz in KLUCZE_POSTEPU}


def _dto_trasy(dane):
    """Nagłówek trasy z §8.1 z wyniku `routes.serializuj_trase` (z podsumowaniem i postępem)."""
    podsumowanie, pojazd = dane['podsumowanie'], dane['pojazd']
    przyblizony = bool(podsumowanie['przyblizony'])
    return {
        'id': dane['id'],
        'nazwa': dane['nazwa'],
        'date_from': dane['date_from'],
        'date_to': dane['date_to'],
        'status': dane['status'],
        'status_etykieta': dostawa.NAZWY_STATUSOW_TRASY.get(dane['status'], dane['status']),
        'pojazd': {'nazwa': pojazd['name'], 'rejestracja': pojazd['registration']} if pojazd is not None else None,
        'kierowca': _kierowca(dane['kierowca']),
        'notatka': dane['notatka'],
        # Jak w panelu: przy liniach prostych `km` to suma odcinków w linii prostej (liczba zaniżona wobec jazdy drogami),
        # `minuty` są null (brak czasu dla linii prostych), a `przyblizony` ostrzega czytelnika (kontrakt §8.1).
        'podsumowanie': dict({k: podsumowanie[k] for k in KLUCZE_PODSUMOWANIA},
                             km=podsumowanie['km'], minuty=podsumowanie['minuty'], przyblizony=przyblizony),
        'postep': _postep(dane['postep']),
        'zatwierdzona': dane['zatwierdzona'],
        'zaladowana': dane['zaladowana'],
        'wyjazd': dane['wyjazd'],
        'wykonana': dane['wykonana'],
    }


def _geo(punkt):
    """Punkt na mapę {lat, lng, dokladnosc} albo None (adres nie znaleziony, brak wiersza punktu)."""
    if punkt is None or punkt.lat is None or punkt.lng is None or punkt.quality not in ('dokladna', 'przyblizona'):
        return None
    return {'lat': float(punkt.lat), 'lng': float(punkt.lng), 'dokladnosc': punkt.quality}


def _przystanek(stop, order, numer, pakunki_zamowienia, punkt, trasa):
    """
    Przystanek trasy z §8.2. `numer` — pozycja wśród aktywnych przystanków (None dla anulowanego). Pozycje zamówienia
    (`order.products`) są już wczytane jednym zapytaniem dla całej trasy (`dostawa_widok.wczytaj`, selectinload).
    """
    aktywne = delivery.aktywne_produkty(order)
    stan, etykieta = dostawa_widok.stan_i_etykieta(order, aktywne, stop)
    # Jak routes.podsumowanie: suma m³ przystanków daje m³ trasy.
    m3 = round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4)
    klient = zam.klient(order)
    zostaje = None
    if stop.stays_reason:
        zostaje = {'powod': stop.stays_reason,
                   'etykieta': dostawa.POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason),
                   'notatka': stop.stays_note}
    niedostarczone = None
    if stop.not_delivered_at is not None:
        niedostarczone = {'powod': stop.not_delivered_reason,
                          'etykieta': dostawa.etykieta_powodu(stop.not_delivered_reason),
                          'notatka': stop.not_delivered_note, 'kiedy': stop.not_delivered_at.isoformat()}
    return {
        'pozycja': numer,
        'order_id': order.id,
        'numer': order.internal_order_number,
        'klient': klient['nazwa'],
        'firma': klient['firma'],
        'miasto': klient['miasto'],
        'm3': m3,
        'waga_kg': int(round(m3 * routes.WAGA_KG_NA_M3)),
        'paczki': {'liczba': len(pakunki_zamowienia),
                   'zaladowane': sum(1 for p in pakunki_zamowienia if dostawa_widok.paczka_zaladowana(p, trasa))},
        'stan': stan,
        'stan_etykieta': etykieta,
        # Status produkcyjny jak w karcie zamówienia (§5.2): ta sama funkcja, wszystkie pozycje (także anulowane).
        'status_zbiorczy': zam._status_zbiorczy(order.products),
        'zostaje': zostaje,
        'niedostarczone': niedostarczone,
        'dostarczono': stop.delivered_at.isoformat() if stop.delivered_at else None,
        'geo': _geo(punkt),
    }


def _niedostarczone_zdjete(wpisy):
    """
    Zamówienia, które zeszły z trasy jako niedostarczone (`dostawa.niedostarczone_zdjete`): numer, klient i miasto
    z samych kolumn zamówienia (zwykły odczyt; zamówienia nie ma już na trasie).
    """
    ids = [w['order_id'] for w in wpisy]
    dane = {}
    if ids:
        dane = {i: (numer, imie, klient, miasto) for i, numer, imie, klient, miasto in db.session.query(
            ProductionOrder.id, ProductionOrder.internal_order_number, ProductionOrder.delivery_fullname,
            ProductionOrder.client_name, ProductionOrder.delivery_city).filter(ProductionOrder.id.in_(ids))}
    wynik = []
    for w in wpisy:
        numer, imie, klient, miasto = dane.get(w['order_id'], (None, None, None, None))
        wynik.append({'order_id': w['order_id'], 'numer': numer,
                      'klient': (imie or '').strip() or (klient or '').strip() or None,
                      'miasto': (miasto or '').strip() or None, 'powod_etykieta': w['etykieta'],
                      'notatka': w['notatka'], 'kiedy': w['kiedy'].isoformat()})
    return wynik


# ── przebieg ─────────────────────────────────────────────────────────────────────────────────────────────────────

def przebieg_aktualny(route, punkty=None, zamowienia=None):
    """
    (ostatni zapisany przebieg trasy jako GeoJSON albo None, czy jest nieaktualny). Niczego nie przelicza i nie
    zapisuje (porównaj `trasy_api._szczegoly`, które woła `routing.przelicz`). Nieaktualny: przystanki albo ich
    punkty zmieniły się od ostatniego przeliczenia, a trasa nigdy nieprzeliczona jest nieaktualna z natury
    (`routing.przebieg_nieaktualny`). `punkty` ({order_id: OrderGeo}) i `zamowienia` (w kolejności przystanków) —
    gdy wołający już je wczytał; inaczej czytamy je z bazy.
    """
    if punkty is None:
        punkty = geocoding.geo_zamowien([s.order_id for s in route.stops])
    return routing.przebieg(route), routing.przebieg_nieaktualny(route, punkty, zamowienia)


# ── odpowiedzi ───────────────────────────────────────────────────────────────────────────────────────────────────

def lista(status=None, od=None, do=None):
    """
    `GET /manager/routes` (§8.1): {trasy: [...]}. Domyślnie wszystkie aktywne trasy (także robocze) i wykonane
    z ostatnich 30 dni (`routes.wczytaj_trasy`, ta sama logika co lista panelu). Kilka zapytań zbiorczych na całą listę.
    """
    wczytane, zamowienia_wg_trasy, punkty = routes.wczytaj_trasy(status, od, do)
    wczytane = sorted(wczytane, key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    pakunki = paczki.aktualne_paczki_zamowien(
        [o.id for kolejne in zamowienia_wg_trasy.values() for o in kolejne])
    historia = dostawa.zdjete_do_postepu(dostawa.niedostarczone_zdjete(wczytane))
    return {'trasy': [
        _dto_trasy(routes.serializuj_trase(t, zamowienia_wg_trasy[t.id], punkty, pakunki, historia[t.id]))
        for t in wczytane]}


def szczegoly(route_id):
    """
    `GET /manager/routes/<id>` (§8.2): {trasa: {...nagłówek, magazyn, przystanki, niedostarczone_zdjete, przebieg,
    przebieg_nieaktualny, odcinki_proste}} albo None, gdy trasy nie ma (404 `trasa_nieznana`). Także dla trasy
    `robocza`. Przystanki z `dostawa_widok.wczytaj` — czystego odczytu GET Dostawy.
    """
    wczytane = dostawa_widok.wczytaj(route_id)
    if wczytane is None:
        return None
    trasa, zamowienia_po_id, pakunki, punkty, (wpisy, _numery) = wczytane
    kolejne = [zamowienia_po_id[s.order_id] for s in trasa.stops if s.order_id in zamowienia_po_id]
    przystanki_trasy = {s.order_id: s for s in trasa.stops}
    zdjete_do_postepu = dostawa.zdjete_do_postepu({trasa.id: wpisy})[trasa.id]

    dane = _dto_trasy(routes.serializuj_trase(trasa, kolejne, punkty, pakunki, zdjete_do_postepu))
    przebieg, nieaktualny = przebieg_aktualny(trasa, punkty, kolejne)
    # Odcinki proste (przystanki daleko od drogi) siedzą w zapisanej geometrii; w odpowiedzi to osobne pole.
    odcinki_proste = []
    if przebieg is not None:
        przebieg = dict(przebieg)
        odcinki_proste = przebieg.pop('odcinki_proste', None) or []
    dane.update({
        'magazyn': dict(geocoding.MAGAZYN),
        'przystanki': [_przystanek(przystanki_trasy[o.id], o, numer, pakunki.get(o.id, []), punkty.get(o.id), trasa)
                       for o, numer, _anulowane in routes.numeracja_przystankow(kolejne)],
        'niedostarczone_zdjete': _niedostarczone_zdjete(wpisy),
        'przebieg': przebieg,
        'przebieg_nieaktualny': nieaktualny,
        'odcinki_proste': odcinki_proste,
    })
    return {'trasa': dane}


def odcisk(dane):
    """Skrót treści odpowiedzi do ETagu: zmiana czegokolwiek, co widzi kierownik, zmienia ETag."""
    tekst = json.dumps(dane, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(tekst.encode('utf-8')).hexdigest()[:20]


def etag_listy(dane):
    return make_weak_etag('kier-trasy', KSZTALT_TRAS, odcisk(dane))


def etag_szczegolow(route_id, dane):
    return make_weak_etag('kier-trasa', KSZTALT_TRAS, route_id, odcisk(dane))
