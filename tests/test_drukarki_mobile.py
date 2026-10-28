# -*- coding: utf-8 -*-
"""Stan drukarek dla tabletów (`/api/mobile/printers/status`) i sygnały po zmianie stanu."""
import json
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.drukarki import models as m
from modules.production.drukarki.routers import agent_api
from modules.production.drukarki.routers.mobile_api import drukarki_mobile_bp
from modules.production.drukarki.services import agenci, stan
from modules.production.models import LabelPrintJob, ProductionConfig, ProductionDevice
from modules.production.services.mobile_api_service import generate_token
from tests.druk_fixtures import app, zadanie  # noqa: F401


@pytest.fixture()
def klient(app, monkeypatch):
    app.config['API_MOBILE'] = {'jwt_secret': 'x' * 64, 'jwt_expiry_days': 365, 'ip_whitelist': [],
                                'min_supported_app_version': '0.0.0'}
    db.metadata.create_all(bind=db.engine, tables=[
        m.PrintAgent.__table__, m.PrintAgentConfig.__table__, m.PrintAgentConfigChange.__table__,
        m.PrintAgentCommand.__table__, m.PrintAgentRelease.__table__, ProductionDevice.__table__])
    sygnaly = []
    monkeypatch.setattr(stan.realtime_service, 'publish', lambda kanal, dane: sygnaly.append((kanal, dane)))
    app.register_blueprint(drukarki_mobile_bp, url_prefix='/api/mobile/printers')
    c = app.test_client()
    c.sygnaly = sygnaly
    return c


def _naglowki(stanowisko):
    urzadzenie = ProductionDevice(device_id='T-' + stanowisko, device_name='Tablet', station_code=stanowisko)
    db.session.add(urzadzenie)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(urzadzenie), 'X-App-Version': '1.0.0'}


def _agent(drukarki, sekund_temu=0, push=True):
    a, _ = agenci.sparuj('hala', 1)
    agenci.kontakt(a, '2.0.0', drukarki, push)
    a.last_seen_at = datetime.utcnow() - timedelta(seconds=sekund_temu)
    db.session.commit()
    return a


def _po_nazwie(dane):
    return {d['nazwa']: d for d in dane['drukarki']}


def test_migawka_agent_offline_wszystko_nieznany(klient):
    _agent([{'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': ''}], sekund_temu=500)
    dane = stan.migawka()
    assert dane['agent']['online'] is False
    for d in dane['drukarki']:
        assert d['stan'] == 'nieznany' and d['komunikat'] == 'Agent druku nie odpowiada'


def test_migawka_bez_agenta_i_stan_zgloszony(klient):
    assert stan.migawka()['agent'] is None
    _agent([{'nazwa': 'etykiety', 'stan': 'brak_papieru', 'opis': ''}])
    zadanie(printer='etykiety')
    dane = stan.migawka()
    assert dane['agent']['online'] is True and dane['agent']['push'] is True and dane['agent']['wersja'] == '2.0.0'
    p = _po_nazwie(dane)
    assert p['etykiety']['stan'] == 'brak_papieru'
    assert p['etykiety']['komunikat'] == 'Drukarka etykiet: brak etykiet'
    assert p['etykiety']['w_kolejce'] == 1 and p['etykiety']['obsluga'] == 'nowy'
    # agent nie zgłosił XP-410B (nie ma jej w konfiguracji) -> nie „gotowa”, tylko nieznany z powodem
    assert p['wysylka']['stan'] == 'nieznany'
    assert p['wysylka']['komunikat'] == 'Drukarka paczek: agent druku jej nie obsługuje'


def test_wysylka_gotowa_tylko_gdy_zgloszona(klient):
    """XP-410B nie ma odczytu stanu: „gotowa” tylko wtedy, gdy żywy agent ją zgłosił (choćby jako nieznany)."""
    a = _agent([{'nazwa': 'wysylka', 'stan': 'nieznany', 'opis': ''}])
    p = _po_nazwie(stan.migawka())
    assert p['wysylka']['stan'] == 'gotowa' and p['wysylka']['komunikat'] == ''
    assert p['etykiety']['stan'] == 'nieznany'
    assert p['etykiety']['komunikat'] == 'Drukarka etykiet: agent druku jej nie obsługuje'
    agenci.kontakt(a, '2.0.0', [{'nazwa': 'wysylka', 'stan': 'offline', 'opis': ''}], True)
    db.session.commit()
    assert _po_nazwie(stan.migawka())['wysylka']['stan'] == 'offline'


def test_dzis_liczy_wydrukowane_od_polnocy_lokalnej(klient):
    _agent([])
    teraz = datetime(2026, 7, 1, 10, 0)  # 12:00 w Warszawie, północ lokalna = 22:00 UTC poprzedniego dnia
    for kod, kiedy in (('a', datetime(2026, 6, 30, 21, 59)), ('b', datetime(2026, 6, 30, 22, 0)),
                       ('c', datetime(2026, 7, 1, 9, 0))):
        zadanie(printer='etykiety', status='printed', kod=kod).printed_at = kiedy
    db.session.commit()
    assert _po_nazwie(stan.migawka(teraz=teraz))['etykiety']['dzis'] == 2
    assert stan._poczatek_dnia_utc(datetime(2026, 1, 1, 10, 0)) == datetime(2025, 12, 31, 23, 0)


def test_obsluga_zawsze_nowy(klient):
    """Pole `obsluga` zostaje dla zgodności z appką, ale zawsze „nowy” — także gdy w prod_config został wiersz
    przełącznika sprzed migracji; stan drukarki liczy się wtedy normalnie ze zgłoszenia agenta."""
    db.session.add(ProductionConfig(config_key='DRUKARKA_OBSLUGA_wysylka', config_value='stary', config_type='string'))
    db.session.commit()
    _agent([{'nazwa': 'wysylka', 'stan': 'blad', 'opis': ''}])
    p = _po_nazwie(stan.migawka())
    assert {d['obsluga'] for d in p.values()} == {'nowy'}
    assert p['wysylka']['stan'] == 'blad' and p['wysylka']['komunikat'] == 'Drukarka paczek: błąd'
    assert not hasattr(stan, 'KOMUNIKAT_STARY_AGENT')


def test_pakowanie_widzi_tylko_wysylke(klient):
    _agent([])
    db.session.add(ProductionConfig(config_key='LABEL_PRINTER_ALLOWED_STATIONS', config_value='formatting',
                                    config_type='string'))
    db.session.commit()
    odp = klient.get('/api/mobile/printers/status', headers=_naglowki('packaging'))
    assert odp.status_code == 200 and odp.headers['Cache-Control'] == 'no-store'
    assert set(_po_nazwie(odp.get_json())) == {'wysylka'}
    odp = klient.get('/api/mobile/printers/status', headers=_naglowki('formatting'))
    assert set(_po_nazwie(odp.get_json())) == {'etykiety'}
    odp = klient.get('/api/mobile/printers/status', headers=_naglowki('edges'))
    assert odp.get_json()['drukarki'] == []


def test_etykiety_domyslnie_na_formatowaniu_i_pakowaniu(klient):
    odp = klient.get('/api/mobile/printers/status', headers=_naglowki('packaging'))
    assert set(_po_nazwie(odp.get_json())) == {'etykiety', 'wysylka'}


def test_status_wymaga_tokenu_urzadzenia(klient):
    assert klient.get('/api/mobile/printers/status').status_code == 401
    assert klient.get('/api/mobile/printers/status', headers={'Authorization': 'Bearer zly'}).status_code == 401


def test_sygnal_tylko_dla_zmienionych_drukarek(klient):
    stan.po_zmianie_stanu({'etykiety': 'gotowa', 'wysylka': 'gotowa'}, {'etykiety': 'gotowa', 'wysylka': 'gotowa'})
    assert klient.sygnaly == []
    stan.po_zmianie_stanu({'etykiety': 'gotowa', 'wysylka': 'gotowa'}, {'etykiety': 'gotowa', 'wysylka': 'blad'})
    assert klient.sygnaly == [('station:packaging', {'kind': 'printers'})]
    klient.sygnaly.clear()
    stan.po_zmianie_stanu({'etykiety': 'gotowa'}, {'etykiety': 'pauza'})
    assert {k for k, _ in klient.sygnaly} == {'station:formatting', 'station:packaging'}
    assert all(d == {'kind': 'printers'} for _, d in klient.sygnaly)


def test_kontakt_agenta_wysyla_sygnal_po_commicie(app, klient, monkeypatch):
    app.register_blueprint(agent_api.agent_druku_v2_bp, url_prefix='/api/print-agent/v2')
    from modules.production.drukarki.services import kolejka
    monkeypatch.setattr(kolejka, '_ostatnie_wygaszanie', None)
    a, token = agenci.sparuj('hala', 1)
    db.session.commit()
    h = {'Authorization': 'Bearer ' + token}
    cialo = {'wersja': '2.0.0', 'push': False, 'drukarki': [{'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': ''}]}
    # Pierwszy kontakt: z martwego/nieznanego na gotowa -> sygnał.
    assert klient.post('/api/print-agent/v2/kontakt', json=cialo, headers=h).status_code == 200
    assert ('station:formatting', {'kind': 'printers'}) in klient.sygnaly
    klient.sygnaly.clear()
    # Ten sam stan: bez sygnału.
    klient.post('/api/print-agent/v2/kontakt', json=cialo, headers=h)
    assert klient.sygnaly == []
    cialo['drukarki'][0]['stan'] = 'brak_papieru'
    klient.post('/api/print-agent/v2/kontakt', json=cialo, headers=h)
    assert {k for k, _ in klient.sygnaly} == {'station:formatting', 'station:packaging'}
    assert json.loads(m.PrintAgent.query.get(a.id).printers_state)[0]['stan'] == 'brak_papieru'
