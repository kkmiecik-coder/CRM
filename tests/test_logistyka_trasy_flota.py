# -*- coding: utf-8 -*-
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import fleet
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import app, kierowca, pojazd, zamowienie  # noqa: F401


def test_zapis_pojazdu_normalizuje_dane(app):
    with app.app_context():
        v = fleet.zapisz_pojazd({'name': '  Iveco Daily ', 'registration': ' rze 12345 ',
                                 'capacity_kg': '1200'})
        db.session.commit()
        assert fleet.serializuj_pojazd(v) == {'id': v.id, 'name': 'Iveco Daily',
                                              'registration': 'RZE 12345', 'capacity_kg': 1200,
                                              'is_active': True}


@pytest.mark.parametrize('dane', [
    {'name': ''}, {'name': 'x' * 101}, {'name': 'A', 'capacity_kg': '-5'},
    {'name': 'A', 'capacity_kg': 'dużo'}, {'name': 'A', 'registration': 'x' * 21},
    # fix-1, Ruling C: typy spoza JSON-owych oczekiwań (bool/float/int) -> 422, nie 500.
    {'name': 5}, {'name': 'A', 'registration': 7},
    {'name': 'A', 'capacity_kg': True}, {'name': 'A', 'capacity_kg': 1e400},
])
def test_walidacja_pojazdu(app, dane):
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            fleet.zapisz_pojazd(dane)
        assert e.value.status == 422


def test_wylaczenie_nie_kasuje(app):
    with app.app_context():
        v = pojazd()
        fleet.ustaw_aktywnosc(v, False)
        db.session.commit()
        assert v.deactivated_at is not None
        assert [p['id'] for p in fleet.lista_pojazdow(tylko_aktywne=True)] == []
        assert [p['id'] for p in fleet.lista_pojazdow()] == [v.id]
        fleet.ustaw_aktywnosc(v, True)
        assert v.deactivated_at is None


def test_kierowcy_tylko_aktywni(app):
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        kierowca(imie='Ex', aktywny=False)
        assert fleet.kierowcy() == [{'id': k.id, 'nazwa': 'Adam Nowak'}]


# --- R4: zmiana nazwy pojazdu musi podbić pozycje zamówień na aktywnych trasach ---
# (tablet pokazuje transport.vehicle_name, a ETag jego kolejki liczy się z MAX(updated_at)
# pozycji — bez podbicia tablet zostanie ze starą nazwą, patrz spec 6.5).

def _trasa_z_przystankiem(vehicle_id, order_id, status='robocza'):
    trasa = Route(name='Trasa', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1),
                  vehicle_id=vehicle_id, status=status)
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order_id, position=1))
    return trasa


def test_zmiana_nazwy_podbija_pozycje_na_aktywnej_trasie(app):
    with app.app_context():
        v = pojazd(name='Iveco 1')
        o = zamowienie(sposob=s.TRANSPORT)
        _trasa_z_przystankiem(v.id, o.id, status='robocza')
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()

        fleet.zapisz_pojazd({'name': 'Iveco 2', 'registration': v.registration}, pojazd=v)
        db.session.commit()

        for p in o.products:
            assert p.updated_at > datetime(2026, 1, 1)


def test_niezmieniona_nazwa_nie_podbija_pozycji(app):
    with app.app_context():
        v = pojazd(name='Iveco 1')
        o = zamowienie(sposob=s.TRANSPORT)
        _trasa_z_przystankiem(v.id, o.id, status='robocza')
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()

        fleet.zapisz_pojazd({'name': 'Iveco 1', 'registration': v.registration}, pojazd=v)
        db.session.commit()

        for p in o.products:
            assert p.updated_at == datetime(2026, 1, 1)


def test_trasa_wykonana_nie_podbija_pozycji(app):
    with app.app_context():
        v = pojazd(name='Iveco 1')
        o = zamowienie(sposob=s.TRANSPORT)
        _trasa_z_przystankiem(v.id, o.id, status='wykonana')
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()

        fleet.zapisz_pojazd({'name': 'Iveco 2', 'registration': v.registration}, pojazd=v)
        db.session.commit()

        for p in o.products:
            assert p.updated_at == datetime(2026, 1, 1)
