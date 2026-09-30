# -*- coding: utf-8 -*-
"""Kolejkowanie ZPL i wydruk próbny (logistyka etap 4, krok 4.1, spec 6.1)."""
import pytest
from flask_login import LoginManager, UserMixin

from extensions import db
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.production.services import print_queue_service as pqs
from modules.production.services.config_service import get_config_service
from tests.druk_fixtures import app  # noqa: F401


class _Uzytkownik(UserMixin):
    def __init__(self, uid, role):
        self.id = uid
        self.role = role


UZYTKOWNICY = {'1': _Uzytkownik('1', 'admin'), '2': _Uzytkownik('2', 'user')}


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


@pytest.fixture()
def panel(app, sygnaly):
    menedzer = LoginManager()
    menedzer.init_app(app)
    menedzer.user_loader(lambda uid: UZYTKOWNICY.get(uid))
    from modules.production.routers.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/production/api')
    return app.test_client()


def _zaloguj(klient, uid):
    with klient.session_transaction() as sesja:
        sesja['_user_id'] = uid
        sesja['_fresh'] = True


def test_zakolejkuj_zpl_zapisuje_drukarke_i_nie_commituje(app):
    job = pqs.zakolejkuj_zpl('wysylka', '^XA^XZ', 'P-7', 'packaging',
                             {'type': 'device', 'id': 3}, baselinker_order_id=99, package_id=7)
    assert job.id is not None                      # flush nadał id
    db.session.rollback()                          # bez commita zadanie znika
    assert LabelPrintJob.query.count() == 0


def test_zakolejkuj_zpl_pola(app):
    job = pqs.zakolejkuj_zpl('wysylka', '^XA^XZ', 'P-7', 'packaging',
                             {'type': 'device', 'id': 3}, package_id=7)
    db.session.commit()
    j = LabelPrintJob.query.get(job.id)
    assert (j.printer, j.short_product_id, j.package_id, j.status,
            j.requested_by_type, j.requested_by_id) == ('wysylka', 'P-7', 7, 'pending', 'device', '3')


@pytest.mark.parametrize('drukarka', ['laserowa', '', None, 'WYSYLKA'])
def test_zakolejkuj_zpl_odrzuca_nieznana_drukarke(app, drukarka):
    with pytest.raises(pqs.NieznanaDrukarka):
        pqs.zakolejkuj_zpl(drukarka, '^XA^XZ', 'X', 'panel', {'type': 'user', 'id': 1})


def test_wydruk_probny_drukarki_paczek(app, sygnaly):
    job = pqs.wydruk_probny('wysylka', {'type': 'user', 'id': 1})
    j = LabelPrintJob.query.get(job.id)
    assert (j.printer, j.short_product_id, j.station_code) == ('wysylka', 'TEST-wysylka', 'panel')
    assert '^PW800' in j.zpl_payload and 'WYDRUK PROBNY' in j.zpl_payload
    assert sygnaly == [1]                          # agent obudzony po commicie


def test_wydruk_probny_bierze_zapisane_przesuniecie(app, sygnaly):
    db.session.add(ProductionConfig(config_key='PACKAGE_LABEL_OFFSET_Y_DOTS', config_value='-8',
                                    config_type='integer'))
    db.session.commit()
    job = pqs.wydruk_probny('wysylka', {'type': 'user', 'id': 1})
    assert '^FO24,16^GB752,1152,4^FS' in job.zpl_payload


def test_wydruk_probny_etykiet_z_przesunieciami_etykiet_produktow(app, sygnaly):
    db.session.add_all([
        ProductionConfig(config_key='LABEL_PRINTER_OFFSET_LT', config_value='-10', config_type='integer'),
        ProductionConfig(config_key='LABEL_PRINTER_OFFSET_LS', config_value='100', config_type='integer'),
    ])
    db.session.commit()
    job = pqs.wydruk_probny('etykiety', {'type': 'user', 'id': 1})
    assert job.printer == 'etykiety'
    assert '^PW480' in job.zpl_payload and '^LT-10' in job.zpl_payload
    assert '^FO100,0^GB480,320,4^FS' in job.zpl_payload


def test_wydruk_probny_wymaga_admina(panel):
    assert panel.post('/production/api/print-test', json={'printer': 'wysylka'}).status_code == 401
    _zaloguj(panel, '2')
    assert panel.post('/production/api/print-test', json={'printer': 'wysylka'}).status_code == 403
    assert LabelPrintJob.query.count() == 0


def test_wydruk_probny_z_panelu(panel):
    _zaloguj(panel, '1')
    resp = panel.post('/production/api/print-test', json={'printer': 'wysylka'})
    assert resp.status_code == 200
    dane = resp.get_json()
    assert dane['success'] is True and 'drukarka paczek' in dane['message']
    job = LabelPrintJob.query.get(dane['job_id'])
    assert job.printer == 'wysylka' and job.requested_by_id == '1'


@pytest.mark.parametrize('cialo', [{}, {'printer': 'laserowa'}, {'printer': None}, {'printer': ['wysylka']}])
def test_wydruk_probny_nieznana_drukarka(panel, cialo):
    _zaloguj(panel, '1')
    resp = panel.post('/production/api/print-test', json=cialo)
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False and 'drukark' in resp.get_json()['error'].lower()
    assert LabelPrintJob.query.count() == 0


@pytest.mark.parametrize('klucz', ['PACKAGE_LABEL_OFFSET_X_DOTS', 'PACKAGE_LABEL_OFFSET_Y_DOTS'])
def test_walidacja_przesuniecia(app, klucz):
    serwis = get_config_service()
    assert serwis.validate_config_batch({klucz: -8})['invalid'] == []
    assert serwis.validate_config_batch({klucz: 120})['invalid'] == []
    assert serwis.validate_config_batch({klucz: 121})['invalid'] != []
    assert serwis.validate_config_batch({klucz: -121})['invalid'] != []


def test_panel_zapisuje_przesuniecie(panel):
    _zaloguj(panel, '1')
    # Endpoint wymaga nagłówka XMLHttpRequest (ochrona CSRF) — panel zawsze go wysyła.
    resp = panel.post('/production/api/update-configs',
                      json={'configs': {'PACKAGE_LABEL_OFFSET_Y_DOTS': -8}},
                      headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200 and resp.get_json()['success'] is True
    wiersz = ProductionConfig.query.filter_by(config_key='PACKAGE_LABEL_OFFSET_Y_DOTS').one()
    assert wiersz.config_value == '-8'
