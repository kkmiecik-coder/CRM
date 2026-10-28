# -*- coding: utf-8 -*-
"""API agenta druku v2 (/api/print-agent/v2)."""
import pytest

from extensions import db
from modules.production.drukarki import models as m
from modules.production.drukarki.routers import agent_api
from modules.production.drukarki.services import agenci, kolejka, konfiguracja
from modules.production.models import LabelPrintJob, ProductionConfig
from tests.druk_fixtures import app, zadanie  # noqa: F401

V2 = '/api/print-agent/v2'


@pytest.fixture()
def klient(app, monkeypatch):
    db.metadata.create_all(bind=db.engine, tables=[
        m.PrintAgent.__table__, m.PrintAgentConfig.__table__, m.PrintAgentConfigChange.__table__,
        m.PrintAgentCommand.__table__, m.PrintAgentRelease.__table__])
    monkeypatch.setattr(kolejka, '_ostatnie_wygaszanie', None)
    sygnaly = []
    monkeypatch.setattr(agent_api.realtime_service, 'publish', lambda kanal, dane: sygnaly.append((kanal, dane)))
    app.register_blueprint(agent_api.agent_druku_v2_bp, url_prefix=V2)
    c = app.test_client()
    c.sygnaly = sygnaly
    return c


@pytest.fixture()
def agent(klient):
    a, token = agenci.sparuj('hala', 1)
    db.session.commit()
    return a, {'Authorization': 'Bearer ' + token}


def _pobierz(klient, naglowki, drukarka, **kw):
    return klient.post(V2 + '/zadania/pobierz', json={'drukarka': drukarka, 'limit': 10, **kw}, headers=naglowki)


def test_pelny_obieg_pobierz_wysylam_wyniki(klient, agent):
    a, h = agent
    z = zadanie(kod='K-1')
    db.session.commit()
    odp = _pobierz(klient, h, 'etykiety')
    assert odp.status_code == 200
    (j,) = odp.get_json()['zadania']
    assert j['id'] == z.id and j['drukarka'] == 'etykiety' and j['zpl'] == '^XA^XZ' and j['kod'] == 'K-1'
    assert j['stanowisko'] == 'packaging' and j['zlecono']
    assert klient.post(f'{V2}/zadania/{z.id}/wysylam', headers=h).status_code == 200
    r = klient.post(V2 + '/zadania/wyniki', json={'wyniki': [{'id': z.id, 'wynik': 'wydrukowane'}]}, headers=h)
    assert r.get_json() == {'zmienione': 1}
    db.session.expire_all()
    assert LabelPrintJob.query.get(z.id).status == 'printed'


def test_wysylam_cudzego_zadania_409(klient, agent):
    _, h = agent
    z = zadanie()
    db.session.commit()
    r = klient.post(f'{V2}/zadania/{z.id}/wysylam', headers=h)
    assert r.status_code == 409 and r.get_json() == {'error': 'nie_twoje_zadanie'}


def test_401_dla_braku_zlego_i_uniewaznionego_tokenu(klient, agent):
    a, h = agent
    assert klient.post(V2 + '/kontakt', json={}).status_code == 401
    r = klient.post(V2 + '/kontakt', json={}, headers={'Authorization': 'Bearer zly'})
    assert r.status_code == 401 and r.get_json() == {'error': 'nieznany_agent'}
    assert klient.post(V2 + '/kontakt', json={}, headers=h).status_code == 200
    agenci.uniewaznij(a.id, 1)
    db.session.commit()
    assert klient.post(V2 + '/kontakt', json={}, headers=h).status_code == 401


def test_pobierz_bledny_limit_i_drukarka(klient, agent):
    _, h = agent
    for limit in (0, 51, -1, 'x', True, 2.5):
        r = _pobierz(klient, h, 'etykiety', limit=limit)
        assert r.status_code == 400 and r.get_json() == {'error': 'bledny_limit'}
    assert _pobierz(klient, h, 'nieznana').status_code == 400
    assert _pobierz(klient, h, 'etykiety', limit=50).status_code == 200


def test_pobierz_zawsze_dzierzawi_bez_galezi_obslugi(klient, agent):
    """Bez okresu przejściowego: wiersze przełącznika, które zostały w prod_config (także świeże „_OD”), niczego
    nie wstrzymują, a odpowiedź nie ma pola `obsluga`."""
    from datetime import datetime
    _, h = agent
    for klucz, wartosc in (('DRUKARKA_OBSLUGA_etykiety', 'stary'), ('DRUKARKA_OBSLUGA_wysylka', 'stary'),
                           ('DRUKARKA_OBSLUGA_wysylka_OD', datetime.utcnow().isoformat())):
        db.session.add(ProductionConfig(config_key=klucz, config_value=wartosc, config_type='string'))
    e = zadanie(kod='E')
    w = zadanie(printer='wysylka', kod='W')
    db.session.commit()
    for drukarka, oczekiwane in (('etykiety', e.id), ('wysylka', w.id)):
        odp = _pobierz(klient, h, drukarka).get_json()
        assert set(odp) == {'zadania'}
        assert [j['id'] for j in odp['zadania']] == [oczekiwane]
    db.session.expire_all()
    assert {j.status for j in LabelPrintJob.query.all()} == {'claimed'}


def test_kontakt_zapisuje_stan_agenta(klient, agent):
    a, h = agent
    r = klient.post(V2 + '/kontakt', headers=h, json={
        'wersja': '2.0.0', 'push': True, 'wersja_konfiguracji': 1,
        'drukarki': [{'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': ''}, 'śmieć']})
    assert r.status_code == 200
    odp = r.get_json()
    assert odp['wersja_konfiguracji'] == 1 and odp['aktualizacja'] is None and odp['polecenia'] == []
    db.session.expire_all()
    a = m.PrintAgent.query.get(a.id)
    assert a.last_seen_at is not None and a.version == '2.0.0' and a.push_connected is True
    assert 'gotowa' in a.printers_state and 'śmieć' not in a.printers_state


def test_kontakt_zwraca_aktualizacje_gdy_nowsza(klient, agent):
    _, h = agent
    db.session.add(m.PrintAgentRelease(version_name='2.1.0', file_path='agent_releases/a.exe',
                                       file_size_bytes=123, sha256='c' * 64, is_active=True))
    db.session.add(m.PrintAgentRelease(version_name='2.10.0', file_path='agent_releases/b.exe',
                                       file_size_bytes=5, sha256='d' * 64, is_active=False))
    db.session.commit()
    akt = klient.post(V2 + '/kontakt', json={'wersja': '2.0.0'}, headers=h).get_json()['aktualizacja']
    assert akt == {'wersja': '2.1.0', 'sha256': 'c' * 64, 'rozmiar': 123,
                   'url': V2 + '/wydania/2.1.0/plik'}
    assert klient.post(V2 + '/kontakt', json={'wersja': '2.1.0'}, headers=h).get_json()['aktualizacja'] is None
    assert klient.post(V2 + '/kontakt', json={'wersja': '3.0.0'}, headers=h).get_json()['aktualizacja'] is None


def test_plik_wydania_tylko_aktywne(klient, agent, app, tmp_path):
    _, h = agent
    app.instance_path = str(tmp_path)
    (tmp_path / 'agent_releases').mkdir()
    (tmp_path / 'agent_releases' / 'a.exe').write_bytes(b'MZ-instalator')
    db.session.add(m.PrintAgentRelease(version_name='2.1.0', file_path='agent_releases/a.exe',
                                       file_size_bytes=13, sha256='c' * 64, is_active=True))
    db.session.add(m.PrintAgentRelease(version_name='2.0.5', file_path='agent_releases/a.exe',
                                       file_size_bytes=13, sha256='c' * 64, is_active=False))
    db.session.commit()
    r = klient.get(V2 + '/wydania/2.1.0/plik', headers=h)
    assert r.status_code == 200 and r.data == b'MZ-instalator'
    assert klient.get(V2 + '/wydania/2.0.5/plik', headers=h).status_code == 404
    assert klient.get(V2 + '/wydania/9.9.9/plik', headers=h).status_code == 404
    assert klient.get(V2 + '/wydania/2.1.0/plik').status_code == 401


def test_kontakt_zwraca_polecenia_pending_i_wynik(klient, agent):
    a, h = agent
    inny, _ = agenci.sparuj('inny', 1)
    p = m.PrintAgentCommand(agent_id=a.id, kind='kalibracja', printer='etykiety')
    zrobione = m.PrintAgentCommand(agent_id=a.id, kind='kalibracja', printer='wysylka', status='done')
    cudze = m.PrintAgentCommand(agent_id=inny.id, kind='kalibracja', printer='etykiety')
    db.session.add_all([p, zrobione, cudze])
    db.session.commit()
    assert klient.post(V2 + '/kontakt', json={}, headers=h).get_json()['polecenia'] == [
        {'id': p.id, 'rodzaj': 'kalibracja', 'drukarka': 'etykiety'}]
    assert klient.post(f'{V2}/polecenia/{cudze.id}/wynik', json={'ok': True}, headers=h).status_code == 404
    assert klient.post(f'{V2}/polecenia/{p.id}/wynik', json={'ok': False, 'opis': 'brak papieru'},
                       headers=h).status_code == 200
    db.session.expire_all()
    p = m.PrintAgentCommand.query.get(p.id)
    assert p.status == 'failed' and p.result == 'brak papieru' and p.done_at is not None
    assert m.PrintAgentCommand.query.get(cudze.id).status == 'pending'
    assert klient.post(V2 + '/kontakt', json={}, headers=h).get_json()['polecenia'] == []


def test_put_konfiguracji_zapisuje_i_budzi_agenta(klient, agent):
    a, h = agent
    klient.post(V2 + '/kontakt', json={'wersja': '2.0.0'}, headers=h)  # aktywny = taki, który się odezwał
    dane = klient.get(V2 + '/konfiguracja', headers=h).get_json()
    assert dane['wersja'] == 1
    nowa = dane['dane']
    nowa['przesuniecia']['etykiety']['lt'] = -20
    r = klient.put(V2 + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': nowa}, headers=h)
    assert r.status_code == 200
    assert r.get_json()['wersja'] == 2 and r.get_json()['nadpisano'] is None
    assert klient.sygnaly == [('print:agent', {'kind': 'config'})]
    r = klient.put(V2 + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': nowa}, headers=h)
    assert r.get_json()['nadpisano'] == 2 and len(klient.sygnaly) == 2


def test_put_konfiguracji_400_po_polsku(klient, agent):
    _, h = agent
    klient.post(V2 + '/kontakt', json={}, headers=h)
    zla = konfiguracja.domyslna()
    zla['przesuniecia']['etykiety']['lt'] = 99999
    r = klient.put(V2 + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': zla}, headers=h)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'bledna_konfiguracja'
    assert any('Przesunięcie etykiet' in b for b in r.get_json()['bledy'])
    assert klient.sygnaly == []
    assert klient.get(V2 + '/konfiguracja', headers=h).get_json()['wersja'] == 1


def test_put_konfiguracji_409_dla_nieaktywnego_agenta(klient, agent):
    a, h = agent
    klient.post(V2 + '/kontakt', json={}, headers=h)
    drugi, token2 = agenci.sparuj('drugi', 1)
    db.session.commit()
    h2 = {'Authorization': 'Bearer ' + token2}
    klient.post(V2 + '/kontakt', json={}, headers=h2)  # świeższy kontakt = aktywny jest drugi
    dane = klient.get(V2 + '/konfiguracja', headers=h).get_json()['dane']
    r = klient.put(V2 + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': dane}, headers=h)
    assert r.status_code == 409 and r.get_json() == {'error': 'agent_nieaktywny'}
    assert klient.sygnaly == []


def test_wyjatek_daje_500_i_rollback(klient, agent, monkeypatch):
    _, h = agent

    def wybuch(*a, **k):
        raise RuntimeError('boom')
    monkeypatch.setattr(agent_api.kolejka, 'wynik', wybuch)
    r = klient.post(V2 + '/zadania/wyniki', json={'wyniki': []}, headers=h)
    assert r.status_code == 500 and r.get_json() == {'error': 'blad_serwera'}


def test_realtime_token_wylaczony_503(klient, agent, monkeypatch):
    _, h = agent
    monkeypatch.setattr(agent_api.realtime_service, 'is_enabled', lambda: False)
    assert klient.get(V2 + '/realtime-token', headers=h).status_code == 503


def test_uniewaznienie_paczki_gasi_zadanie_claimed(klient, agent):
    """Nowa deklaracja paczek gasi także zadanie już pobrane przez agenta (`claimed`, np. budzi uśpioną
    drukarkę): jego „wysyłam” dostaje 409, a późne „niewyslane” nie przywraca go do kolejki."""
    from datetime import datetime
    from types import SimpleNamespace

    from modules.production.logistics.services import paczki

    a, h = agent
    z = zadanie(printer='wysylka', kod='P-1')
    z.package_id = 777
    db.session.commit()
    assert [j['id'] for j in _pobierz(klient, h, 'wysylka').get_json()['zadania']] == [z.id]
    paczka = SimpleNamespace(id=777, voided_at=None)
    assert paczki.uniewaznij([paczka], datetime.utcnow()) == 1
    db.session.commit()
    db.session.expire_all()
    assert LabelPrintJob.query.get(z.id).status == 'expired'
    r = klient.post(V2 + '/zadania/%d/wysylam' % z.id, headers=h)
    assert r.status_code == 409 and r.get_json() == {'error': 'nie_twoje_zadanie'}
    r = klient.post(V2 + '/zadania/wyniki', json={'wyniki': [{'id': z.id, 'wynik': 'niewyslane'}]}, headers=h)
    assert r.get_json() == {'zmienione': 0}
    db.session.expire_all()
    assert LabelPrintJob.query.get(z.id).status == 'expired'
