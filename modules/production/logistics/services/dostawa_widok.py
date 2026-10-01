# -*- coding: utf-8 -*-
"""
Odczyty telefonu kierowcy (logistyka etap 4, krok 4.4, spec 9.2): „Moje trasy” i trasa z przystankami, paczkami
i stanami zamówień — kształt z kontraktu API Dostawy (plan kroku 4.4b, sekcja „Kontrakt API Dostawy”). Bez zapisów.
"""
import hashlib
import json

from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload

from modules.production.logistics.models import Route
from modules.production.logistics.services import delivery, dostawa, geocoding, paczki, routes, weryfikacja
from modules.production.models import ProductionOrder

ETYKIETY_STANU = {
    'zweryfikowane': u'Zweryfikowane',
    'niezweryfikowane': u'NIEZWERYFIKOWANE',
    'niespakowane': u'NIESPAKOWANE',
    'zaladowane': u'Załadowane',
    'dostarczone': u'Dostarczone',
    'anulowane': u'Anulowane',
}


def moje_trasy(kierowca_id, dzis):
    """
    „Moje trasy” (spec 9.2 z odstępstwem z planu 4.4b): trasy kierowcy zatwierdzone z `date_to >= dziś` oraz
    załadowane i w drodze bez względu na datę — rozpoczęta trasa nie może zniknąć z telefonu o północy.
    Najbliższa `date_from` pierwsza.
    """
    return (Route.query.options(selectinload(Route.stops), selectinload(Route.vehicle))
            .filter(Route.driver_worker_id == kierowca_id,
                    or_(and_(Route.status == 'zatwierdzona', Route.date_to >= dzis),
                        Route.status.in_(('zaladowana', 'w_trasie'))))
            .order_by(Route.date_from, Route.id).all())


def _zamowienia(ids):
    if not ids:
        return {}
    return {o.id: o for o in ProductionOrder.query.options(selectinload(ProductionOrder.products))
            .filter(ProductionOrder.id.in_(ids))}


def _zaladowana(p, trasa):
    return p.loaded_at is not None and p.loaded_route_id == trasa.id


def serializuj_paczke(p, trasa):
    """PaczkaDostawy z kontraktu; `loaded` — załadowana na TĘ trasę."""
    return {'id': p.id, 'code': p.kod, 'seq': p.seq, 'kind': p.kind, 'pallet_type': p.pallet_type,
            'length_cm': p.length_cm, 'width_cm': p.width_cm, 'verified': p.verified_at is not None,
            'loaded': _zaladowana(p, trasa), 'loaded_at': p.loaded_at.isoformat() if p.loaded_at else None,
            'loaded_method': p.loaded_method}


def _stan(order, aktywne):
    """Stan zamówienia dla kierowcy (spec 9.2)."""
    if not aktywne:
        return 'anulowane'
    statusy = {p.current_status for p in aktywne}
    if statusy == {'dostarczone'}:
        return 'dostarczone'
    if statusy == {'zaladowane'}:
        return 'zaladowane'
    if order.problem_at is not None:
        return 'problem'
    if not delivery.wszystkie_spakowane(order):
        return 'niespakowane'
    if statusy == {'zweryfikowane'}:
        return 'zweryfikowane'
    return 'niezweryfikowane'


def _aktywne_przystanki(trasa, zamowienia):
    return [s for s in trasa.stops if s.order_id in zamowienia and delivery.aktywne_produkty(zamowienia[s.order_id])]


def _krotko(trasa, zamowienia, pakunki):
    """TrasaKrotko z kontraktu: liczniki na przystankach aktywnych i ich aktualnych paczkach."""
    stopy = _aktywne_przystanki(trasa, zamowienia)
    paczki_trasy = [p for s in stopy for p in pakunki.get(s.order_id, [])]
    return {
        'id': trasa.id, 'name': trasa.name,
        'date_from': trasa.date_from.isoformat(), 'date_to': trasa.date_to.isoformat(),
        'status': trasa.status, 'status_label': dostawa.NAZWY_STATUSOW_TRASY.get(trasa.status, trasa.status),
        'vehicle_name': trasa.vehicle.name if trasa.vehicle is not None else None,
        'stops_total': len(stopy),
        'stops_delivered': sum(1 for s in stopy if s.delivered_at is not None),
        'packages_total': len(paczki_trasy),
        'packages_loaded': sum(1 for p in paczki_trasy if _zaladowana(p, trasa)),
    }


def lista_moich_tras(kierowca_id, dzis):
    """„Moje trasy” w kształcie TrasaKrotko — kilka zapytań zbiorczych na całą listę."""
    trasy = moje_trasy(kierowca_id, dzis)
    ids = list({s.order_id for t in trasy for s in t.stops})
    zamowienia = _zamowienia(ids)
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    return [_krotko(t, zamowienia, pakunki) for t in trasy]


def _przystanek(stop, order, numer, pakunki_zamowienia, punkt, trasa):
    aktywne = delivery.aktywne_produkty(order)
    stan = _stan(order, aktywne)
    etykieta = ETYKIETY_STANU.get(stan)
    if stan == 'problem':
        etykieta = u'PROBLEM: ' + weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason or u'')
    m3 = round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4)
    return {
        'position': numer,
        'order_id': order.id,
        'internal_order_number': order.internal_order_number,
        'client_name': order.client_name,
        # Osoba do odbioru: osoba z adresu dostawy, potem firma, na końcu klient.
        'recipient': order.delivery_fullname or order.delivery_company or order.client_name,
        'phone': order.client_phone,
        'address': {'street': order.delivery_address, 'postcode': order.delivery_postcode,
                    'city': order.delivery_city, 'country_code': order.delivery_country_code},
        # Tylko punkt dokładny — przybliżony (miejscowość) prowadziłby nawigację w złe miejsce.
        'geo': ({'lat': float(punkt.lat), 'lng': float(punkt.lng)}
                if punkt is not None and punkt.quality == 'dokladna' and punkt.lat is not None else None),
        'order_notes': order.order_notes,
        'm3': m3,
        'weight_kg': int(round(m3 * routes.WAGA_KG_NA_M3)),
        'packages': [serializuj_paczke(p, trasa) for p in pakunki_zamowienia],
        'packages_total': len(pakunki_zamowienia),
        'packages_loaded': sum(1 for p in pakunki_zamowienia if _zaladowana(p, trasa)),
        'state': stan,
        'state_label': etykieta,
        'problem': ({'reason': order.problem_reason,
                     'reason_label': weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
                     'note': order.problem_note} if order.problem_at is not None else None),
        'stays': ({'reason': stop.stays_reason,
                   'reason_label': dostawa.POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason),
                   'note': stop.stays_note} if stop.stays_reason else None),
        'delivered_at': stop.delivered_at.isoformat() if stop.delivered_at else None,
    }


def serializuj(trasa, zamowienia, pakunki, punkty):
    """Trasa z kontraktu. `zamowienia` — {order_id: zamówienie}, `pakunki` — {order_id: [aktualne paczki]}."""
    dane = _krotko(trasa, zamowienia, pakunki)
    kolejne = [zamowienia[s.order_id] for s in trasa.stops if s.order_id in zamowienia]
    przystanki = {s.order_id: s for s in trasa.stops}
    dane.update({
        'vehicle_registration': trasa.vehicle.registration if trasa.vehicle is not None else None,
        'notes': trasa.notes,
        'loaded_at': trasa.loaded_at.isoformat() if trasa.loaded_at else None,
        'departed_at': trasa.departed_at.isoformat() if trasa.departed_at else None,
        'completed_at': trasa.completed_at.isoformat() if trasa.completed_at else None,
        # Trasa odhaczona w panelu — telefon nie cofa wtedy ostatniego dostarczenia (decyzja Konrada 3).
        'completed_by_panel': trasa.status == 'wykonana' and trasa.completed_by is not None,
        'stops': [_przystanek(przystanki[o.id], o, numer, pakunki.get(o.id, []), punkty.get(o.id), trasa)
                  for o, numer, _anulowane in routes.numeracja_przystankow(kolejne)],
    })
    return dane


def wczytaj(route_id):
    """(trasa, zamówienia, paczki, punkty) do GET — kilka zapytań zbiorczych; brak trasy → None."""
    trasa = Route.query.options(selectinload(Route.stops), selectinload(Route.vehicle)).get(route_id)
    if trasa is None:
        return None
    ids = [s.order_id for s in trasa.stops]
    return trasa, _zamowienia(ids), paczki.aktualne_paczki_zamowien(ids), geocoding.geo_zamowien(ids)


def trasa_po_zapisie(trasa):
    """
    Pełna trasa w odpowiedzi zapisu z telefonu — z odczytu bieżącego: dostawa.zablokuj drugi raz w tej samej
    transakcji (blokady już trzymane, nic nie czeka). Zwykły odczyt pokazałby migawkę sprzed czekania na blokady,
    np. paczki załadowane w tym czasie drugim telefonem. Krotkę z zablokuj trzymamy w zmiennych do końca
    serializacji (silne referencje — docstring modułu dostawa).
    """
    trasa, zamowienia, pakunki = dostawa.zablokuj(trasa)
    return serializuj(trasa, zamowienia, pakunki, geocoding.geo_zamowien(list(zamowienia)))


def podpis(dane):
    """Skrót treści trasy do ETagu: zmiana czegokolwiek, co widzi kierowca, zmienia ETag."""
    tekst = json.dumps(dane, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()[:20]
