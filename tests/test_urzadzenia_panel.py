# -*- coding: utf-8 -*-
"""Serwis panelu „Urządzenia mobilne” — lista i akcje admina (spec 2026-10-12, sekcja 5)."""
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import MobileAppRelease, ProductionDevice, get_local_now
from modules.production.services import device_access_service as dostep
from modules.users.models import User
from tests.urzadzenia_fixtures import MAC_A, MAC_B, app, urzadzenie  # noqa: F401


def _swiezy(pk):
    return ProductionDevice.query.populate_existing().get(pk)


def _blad(funkcja, *args):
    with pytest.raises(dostep.BladPanelu) as e:
        funkcja(*args)
    return e.value


# ---- lista ---------------------------------------------------------------------------------------------------

def test_lista_rozdziela_stany_i_pomija_przeterminowane(app):
    urzadzenie('P1', status='oczekuje', mac=MAC_A, nazwa='Nowy')
    urzadzenie('P-STARA', status='oczekuje', mac=MAC_B, requested_at=get_local_now() - timedelta(days=8))
    urzadzenie('Z1', nazwa='Pakowanie 1')
    urzadzenie('B1', status='zablokowane', nazwa='Stary', approved_at=get_local_now())
    dane = dostep.lista_dla_panelu()
    assert [p['nazwa'] for p in dane['prosby']] == ['Nowy']
    assert [u['nazwa'] for u in dane['urzadzenia']] == ['Pakowanie 1']
    assert [(u['nazwa'], u['odrzucona']) for u in dane['zablokowane']] == [('Stary', False)]


def test_lista_nie_wynosi_device_id(app):
    urzadzenie('TAJNY-ID', status='oczekuje', mac=MAC_A)
    urzadzenie('TAJNY-ID-2')
    assert 'TAJNY-ID' not in json.dumps(dostep.lista_dla_panelu(), default=str)


def test_lista_rozpoznaje_reinstalacje(app):
    urzadzenie('STARE', nazwa='Pakowanie 1', mac=MAC_A)
    urzadzenie('NOWE', status='oczekuje', mac=MAC_A, nazwa='gg')
    prosba = dostep.lista_dla_panelu()['prosby'][0]
    assert prosba['to_samo_co'] == [{'nazwa': 'Pakowanie 1', 'status': 'zatwierdzone'}]
    assert prosba['proponowana_nazwa'] == 'Pakowanie 1'


def test_lista_pokazuje_kto_zatwierdzil(app):
    db.session.add(User(id=5, email='admin@test.local', password='x', role='admin', first_name='Ala', last_name='Nowak'))
    db.session.commit()
    urzadzenie('Z1', approved_by=5, approved_at=get_local_now())
    assert dostep.lista_dla_panelu()['urzadzenia'][0]['zatwierdzil'] == 'Ala Nowak'


# ---- zatwierdź / odrzuć ---------------------------------------------------------------------------------------

def test_zatwierdz_prosbe(app):
    d = urzadzenie('P1', status='oczekuje', mac=MAC_A, nazwa='gg')
    assert dostep.zatwierdz(d.id, '  Pakowanie 2  ', 7) == {'zastapione': []}
    db.session.commit()
    d = _swiezy(d.id)
    assert (d.status, d.is_active, d.device_name, d.approved_by) == ('zatwierdzone', True, 'Pakowanie 2', 7)


def test_zatwierdz_reinstalacje_blokuje_stary_wpis(app):
    stary = urzadzenie('STARE', nazwa='Pakowanie 1', mac=MAC_A)
    wersja = stary.token_version
    nowy = urzadzenie('NOWE', status='oczekuje', mac=MAC_A)
    assert dostep.zatwierdz(nowy.id, 'Pakowanie 1', 7) == {'zastapione': ['Pakowanie 1']}
    db.session.commit()
    stary = _swiezy(stary.id)
    assert (stary.status, stary.is_active, stary.token_version) == ('zablokowane', False, wersja + 1)


def test_zatwierdz_odrzucona_prosbe(app):
    d = urzadzenie('P1', status='zablokowane', mac=MAC_A)   # approved_at = None → odrzucona prośba
    dostep.zatwierdz(d.id, 'Sklejanie', 7)
    db.session.commit()
    assert _swiezy(d.id).status == 'zatwierdzone'


def test_zatwierdz_z_niewlasciwego_stanu(app):
    d = urzadzenie('Z1')
    assert _blad(dostep.zatwierdz, d.id, 'X', 7).kod == 'stan_zmieniony'
    d2 = urzadzenie('B1', status='zablokowane', approved_at=get_local_now())
    assert _blad(dostep.zatwierdz, d2.id, 'X', 7).status == 409


@pytest.mark.parametrize('nazwa', ['', '   ', None, 5, 'x' * 129])
def test_zatwierdz_zla_nazwa(app, nazwa):
    """Review Focus 2."""
    d = urzadzenie('P1', status='oczekuje', mac=MAC_A, nazwa='gg')
    blad = _blad(dostep.zatwierdz, d.id, nazwa, 7)
    assert (blad.kod, blad.status) == ('nazwa_niepoprawna', 400)
    db.session.rollback()
    assert (_swiezy(d.id).status, _swiezy(d.id).device_name) == ('oczekuje', 'gg')


def test_zatwierdz_prosby_skasowanej_w_miedzyczasie(app):
    """Review Focus 3: prośba wygasła i zniknęła, zanim admin kliknął."""
    d = urzadzenie('P1', status='oczekuje', mac=MAC_A, requested_at=get_local_now() - timedelta(days=8))
    pk = d.id
    dostep.usun_przeterminowane_prosby()
    db.session.commit()
    blad = _blad(dostep.zatwierdz, pk, 'Pakowanie', 7)
    assert (blad.kod, blad.status) == ('nie_znaleziono', 404)


def test_odrzuc(app):
    d = urzadzenie('P1', status='oczekuje', mac=MAC_A)
    dostep.odrzuc(d.id, 7)
    db.session.commit()
    d = _swiezy(d.id)
    assert (d.status, d.approved_at, d.blocked_by) == ('zablokowane', None, 7)
    assert _blad(dostep.odrzuc, urzadzenie('Z1').id, 7).kod == 'stan_zmieniony'


# ---- zablokuj / odblokuj / nazwa / MAC -------------------------------------------------------------------------

def test_zablokuj_i_odblokuj(app):
    d = urzadzenie('Z1', approved_at=get_local_now())   # zatwierdzone urządzenie ma approved_at (migracja uzupełnia stare)
    wersja = d.token_version
    dostep.zablokuj(d.id, 7)
    db.session.commit()
    assert (_swiezy(d.id).status, _swiezy(d.id).token_version) == ('zablokowane', wersja + 1)
    assert _blad(dostep.zablokuj, d.id, 7).kod == 'stan_zmieniony'
    dostep.odblokuj(d.id, 8)
    db.session.commit()
    d = _swiezy(d.id)
    assert (d.status, d.is_active, d.blocked_at, d.token_version) == ('zatwierdzone', True, None, wersja + 1)


def test_odblokuj_odrzuconej_prosby_odmawia(app):
    d = urzadzenie('P1', status='zablokowane', mac=MAC_A)   # approved_at = None
    assert _blad(dostep.odblokuj, d.id, 7).kod == 'stan_zmieniony'


def test_zmien_nazwe(app):
    d = urzadzenie('Z1', nazwa='gg')
    dostep.zmien_nazwe(d.id, 'Formatowanie')
    db.session.commit()
    assert _swiezy(d.id).device_name == 'Formatowanie'
    assert _blad(dostep.zmien_nazwe, d.id, '   ').kod == 'nazwa_niepoprawna'


def test_przyjmij_mac(app):
    d = urzadzenie('Z1', mac=MAC_A, mac_conflict=MAC_B)
    dostep.przyjmij_mac(d.id)
    db.session.commit()
    assert (_swiezy(d.id).mac_address, _swiezy(d.id).mac_conflict) == (MAC_B, None)
    assert _blad(dostep.przyjmij_mac, d.id).kod == 'stan_zmieniony'


# ---- bez MAC ---------------------------------------------------------------------------------------------------

def test_podglad_i_blokada_bez_mac(app):
    bez = urzadzenie('BEZ', mac=None, nazwa='dev')
    z_mac = urzadzenie('Z-MAC', mac=MAC_A)
    w_miedzyczasie = urzadzenie('POZNIEJ', mac=None, nazwa='Pakowanie')
    assert sorted(u['nazwa'] for u in dostep.podglad_bez_mac()['urzadzenia']) == ['Pakowanie', 'dev']
    w_miedzyczasie.mac_address = MAC_B          # dosłał MAC po otwarciu podglądu
    db.session.commit()
    wynik = dostep.zablokuj_bez_mac([bez.id, w_miedzyczasie.id, z_mac.id, 9999], 7)
    db.session.commit()
    assert wynik == {'zablokowane': [bez.id], 'pominiete': sorted([w_miedzyczasie.id, z_mac.id, 9999])}
    assert _swiezy(bez.id).status == 'zablokowane'
    assert _swiezy(w_miedzyczasie.id).status == 'zatwierdzone'


# ---- wydania ---------------------------------------------------------------------------------------------------

def test_wydania_licza_zatwierdzone_urzadzenia(app):
    db.session.add(MobileAppRelease(version_code=47, version_name='1.9.0', file_path='x.apk', file_size_bytes=1,
                                    sha256='a' * 64, is_active=True))
    db.session.commit()
    urzadzenie('A', last_app_version_code=47)
    urzadzenie('B', last_app_version_code=47)
    urzadzenie('C', last_app_version_code=46)
    urzadzenie('D', status='zablokowane', last_app_version_code=47)
    wydanie = dostep.wydania_z_liczbami()[0]
    assert (wydanie['version_code'], wydanie['urzadzen']) == (47, 2)
