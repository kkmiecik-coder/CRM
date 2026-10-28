# -*- coding: utf-8 -*-
"""Panel zakładki „Drukarki” (/production/api/drukarki) i dopiski w API agenta v2 (kolejność /kontakt)."""
import io
import json
from datetime import datetime, timedelta

import pytest
from flask_login import AnonymousUserMixin, LoginManager
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from modules.production.drukarki import models as m
from modules.production.drukarki.routers import agent_api, panel_api
from modules.production.drukarki.services import agenci, kolejka, konfiguracja
from modules.production.models import LabelPrintJob, ProductionConfig
from tests.druk_fixtures import app, zadanie  # noqa: F401

PANEL = '/production/api/drukarki'
V2 = '/api/print-agent/v2'
ROLA = {'role': 'admin'}


class Biezacy(AnonymousUserMixin):
    """„Zalogowany” bez sesji (LOGIN_DISABLED); rola zmieniana w teście przez ROLA."""
    id = 7
    is_authenticated = True

    @property
    def role(self):
        return ROLA['role']


@pytest.fixture()
def klient(app, monkeypatch, tmp_path):
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access', lambda *a, **k: (lambda f: f))
    ROLA['role'] = 'admin'
    app.config['LOGIN_DISABLED'] = True
    app.instance_path = str(tmp_path / 'instance')
    menedzer = LoginManager()
    menedzer.anonymous_user = Biezacy
    menedzer.init_app(app)
    menedzer.user_loader(lambda uid: None)
    db.metadata.create_all(bind=db.engine, tables=[
        m.PrintAgent.__table__, m.PrintAgentConfig.__table__, m.PrintAgentConfigChange.__table__,
        m.PrintAgentCommand.__table__, m.PrintAgentRelease.__table__])
    monkeypatch.setattr(kolejka, '_ostatnie_wygaszanie', None)
    sygnaly = []
    monkeypatch.setattr(panel_api.realtime_service, 'publish', lambda kanal, dane: sygnaly.append((kanal, dane)) or True)
    monkeypatch.setattr(panel_api.realtime_service, 'publish_print_signal',
                        lambda n: sygnaly.append(('print', n)) or True)
    app.register_blueprint(panel_api.drukarki_panel_bp, url_prefix=PANEL)
    app.register_blueprint(agent_api.agent_druku_v2_bp, url_prefix=V2)
    c = app.test_client()
    c.sygnaly = sygnaly
    return c


def _agent_online(drukarki=()):
    """Sparowany agent v2, który właśnie się odezwał; `drukarki` wpisane w jego konfiguracji w CRM i zgłoszone
    w kontakcie. Zwraca (agent, nagłówki)."""
    a, token = agenci.sparuj('hala', 1)
    _wpisz_drukarki(a, drukarki)
    agenci.kontakt(a, '2.0.0', [{'nazwa': n, 'stan': 'gotowa', 'opis': ''} for n in drukarki], False)
    db.session.commit()
    return a, {'Authorization': 'Bearer ' + token}


def _wpisz_drukarki(agent, nazwy):
    konf = m.PrintAgentConfig.query.filter_by(agent_id=agent.id).one()
    dane = json.loads(konf.data)
    dane['drukarki'] = [{'nazwa': n, 'ip': '10.0.0.%d' % (i + 1), 'port': 9100, 'odczyt_stanu': 'brak'}
                        for i, n in enumerate(nazwy)]
    konf.data = json.dumps(dane)


def test_tab_content_dla_admina_i_nie_admina(klient):
    for rola, flaga in (('admin', 'true'), ('user', 'false')):
        ROLA['role'] = rola
        r = klient.get(PANEL + '/tab-content')
        assert r.status_code == 200 and 'data-is-admin="%s"' % flaga in r.get_data(as_text=True)


# Pola i znaczniki starego agenta, których po końcu okresu przejściowego nie ma w zakładce dla nikogo.
SLADY_STAREGO_AGENTA = ('drk-panel-stary', 'drk-sub-stary', 'drk-stan-stary', 'drk-obsluga', 'drk-modal-obsluga',
                        'data-drk-akcja="obsluga"', 'label_printer_ip', 'label_printer_port', 'label_printer_timeout',
                        'label_printer_retry', 'label_printer_use_agent', 'label_printer_agent_token',
                        'LABEL_PRINTER_AGENT_TOKEN', 'Stary agent', 'stary agent', 'starego agenta', 'stary-token-xyz')


def test_tab_content_admin_widzi_konfiguracje(klient):
    """Admin: sekcje konfiguracji, agentów i wydań oraz „Ustawienia druku” z samym polem stanowisk uprawnionych;
    bez przełącznika obsługi i bez karty starego agenta (token, tryb TCP)."""
    db.session.add(ProductionConfig(config_key='LABEL_PRINTER_ALLOWED_STATIONS', config_value='formatting',
                                    config_type='string'))
    db.session.add(ProductionConfig(config_key='LABEL_PRINTER_AGENT_TOKEN', config_value='stary-token-xyz',
                                    config_type='string'))
    db.session.commit()
    html = klient.get(PANEL + '/tab-content').get_data(as_text=True)
    for znacznik in ('id="drk-panel-przeglad"', 'id="drk-panel-konfiguracja"', 'id="drk-panel-agenci"',
                     'id="drk-panel-ustawienia"', 'id="drk-zadania-lista"', 'id="drk-modal-token"',
                     'id="label_printer_allowed_stations"', 'Ustawienia druku'):
        assert znacznik in html, znacznik
    assert 'data-klucz="LABEL_PRINTER_ALLOWED_STATIONS"' in html and 'value="formatting"' in html
    for slad in SLADY_STAREGO_AGENTA:
        assert slad not in html, slad
    # Przesunięcia edytuje wyłącznie formularz dokumentu konfiguracji (PUT /konfiguracja).
    for pole in ('label_printer_offset_lt', 'label_printer_offset_ls', 'package_label_offset_x',
                 'package_label_offset_y'):
        assert 'id="%s"' % pole not in html
    assert 'BaseLinker' not in html


def test_tab_content_uzytkownik_bez_konfiguracji(klient):
    """Nie-admin: przegląd (karty stanu, lista zadań), bez sekcji admina."""
    ROLA['role'] = 'user'
    html = klient.get(PANEL + '/tab-content').get_data(as_text=True)
    assert 'id="drk-panel-przeglad"' in html and 'id="drk-zadania-lista"' in html
    for znacznik in ('drk-panel-konfiguracja', 'drk-panel-agenci', 'drk-panel-ustawienia', 'drk-modal-token',
                     'label_printer_allowed_stations') + SLADY_STAREGO_AGENTA:
        assert znacznik not in html, znacznik


def test_ponow_dostepne_dla_uzytkownika_produkcji(klient):
    ROLA['role'] = 'user'
    z = zadanie(status='failed')
    db.session.commit()
    r = klient.post('%s/zadania/%d/ponow' % (PANEL, z.id))
    assert r.status_code == 200
    nowe = LabelPrintJob.query.get(r.get_json()['id'])
    assert nowe.status == 'pending' and nowe.reprint_of_job_id == z.id
    assert ('print', 1) in klient.sygnaly
    assert klient.post('%s/zadania/%d/ponow' % (PANEL, 9999)).status_code == 404
    pending = zadanie(status='pending')
    db.session.commit()
    assert klient.post('%s/zadania/%d/ponow' % (PANEL, pending.id)).status_code == 409


def test_anuluj_tylko_pending(klient):
    ROLA['role'] = 'user'
    p, w = zadanie(status='pending'), zadanie(status='sending')
    db.session.commit()
    assert klient.post('%s/zadania/%d/anuluj' % (PANEL, p.id)).status_code == 200
    assert klient.post('%s/zadania/%d/anuluj' % (PANEL, w.id)).status_code == 409
    db.session.expire_all()
    assert LabelPrintJob.query.get(p.id).status == 'cancelled'


def test_wydruk_probny_dla_uzytkownika(klient):
    ROLA['role'] = 'user'
    r = klient.post(PANEL + '/wydruk-probny/etykiety')
    assert r.status_code == 200 and LabelPrintJob.query.get(r.get_json()['id']).short_product_id == 'TEST-etykiety'
    assert klient.post(PANEL + '/wydruk-probny/nieznana').status_code == 404


def test_lista_zadan_filtry_i_strony(klient):
    ROLA['role'] = 'user'
    for i in range(52):
        zadanie(kod='K-%d' % i)
    zadanie(printer='wysylka', status='failed', kod='W')
    db.session.commit()
    d = klient.get(PANEL + '/zadania').get_json()
    assert d['razem'] == 53 and len(d['zadania']) == 50 and d['zadania'][0]['kod'] == 'W'
    assert set(d['zadania'][0]) == {'id', 'czas', 'drukarka', 'kod', 'stanowisko', 'kto', 'stan', 'blad'}
    assert len(klient.get(PANEL + '/zadania?strona=2').get_json()['zadania']) == 3
    assert klient.get(PANEL + '/zadania?drukarka=wysylka&stan=failed').get_json()['razem'] == 1


def test_parowanie_tylko_admin(klient):
    ROLA['role'] = 'user'
    assert klient.post(PANEL + '/agenci', json={'nazwa': 'x'}).status_code == 403
    assert klient.get(PANEL + '/agenci').status_code == 403
    ROLA['role'] = 'admin'
    r = klient.post(PANEL + '/agenci', json={'nazwa': 'hala'})
    assert r.status_code == 201 and r.get_json()['token'].startswith('wpa_')


def test_token_pokazany_raz(klient):
    token = klient.post(PANEL + '/agenci', json={'nazwa': 'hala'}).get_json()['token']
    lista = klient.get(PANEL + '/agenci')
    assert token not in lista.get_data(as_text=True)
    assert all('token' not in a for a in lista.get_json()['agenci'])
    nowy = klient.post('%s/agenci/%d/token' % (PANEL, lista.get_json()['agenci'][0]['id'])).get_json()['token']
    assert nowy != token and agenci.agent_z_tokenu(token) is None and agenci.agent_z_tokenu(nowy) is not None


def test_uniewaznij_agenta(klient):
    a, token = agenci.sparuj('hala', 1)
    db.session.commit()
    assert klient.post('%s/agenci/%d/uniewaznij' % (PANEL, a.id)).status_code == 200
    assert agenci.agent_z_tokenu(token) is None
    assert klient.post(PANEL + '/agenci/999/uniewaznij').status_code == 404


def test_konfiguracja_bez_aktywnego_agenta_409(klient):
    for metoda, sciezka in (('get', '/konfiguracja'), ('get', '/konfiguracja/historia'),
                            ('put', '/konfiguracja'), ('post', '/kalibracja/etykiety')):
        r = getattr(klient, metoda)(PANEL + sciezka, json={})
        assert r.status_code == 409 and r.get_json() == {'error': 'brak_aktywnego_agenta'}


def test_put_konfiguracji_wysyla_sygnal_config(klient):
    a, _ = _agent_online()
    dane = klient.get(PANEL + '/konfiguracja').get_json()
    assert dane['wersja'] == 1
    nowe = dane['dane']
    nowe['przesuniecia']['etykiety']['lt'] = -20
    r = klient.put(PANEL + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': nowe})
    assert r.status_code == 200
    assert r.get_json()['wersja'] == 2 and r.get_json()['nadpisano'] is None
    assert ('print:agent', {'kind': 'config'}) in klient.sygnaly
    assert ProductionConfig.query.filter_by(config_key='LABEL_PRINTER_OFFSET_LT').one().config_value == '-20'
    assert m.PrintAgentConfig.query.get(a.id).updated_by == 'user:7'
    h = klient.get(PANEL + '/konfiguracja/historia').get_json()['historia']
    assert h[0]['wersja'] == 2 and h[0]['zrodlo'] == 'crm'


def test_put_konfiguracji_nadpisanie_i_blad_bez_sygnalu(klient):
    _agent_online()
    nowe = konfiguracja.domyslna()
    klient.put(PANEL + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': nowe})
    klient.sygnaly.clear()
    r = klient.put(PANEL + '/konfiguracja', json={'wersja_bazowa': 1, 'dane': nowe})
    assert r.get_json()['nadpisano'] == 2
    klient.sygnaly.clear()
    zle = konfiguracja.domyslna()
    zle['przesuniecia']['wysylka']['dx'] = 9999
    r = klient.put(PANEL + '/konfiguracja', json={'wersja_bazowa': 3, 'dane': zle})
    assert r.status_code == 400 and r.get_json()['error'] == 'bledna_konfiguracja' and r.get_json()['bledy']
    assert klient.sygnaly == []


def test_kalibracja_tworzy_polecenie(klient):
    a, _ = _agent_online()
    r = klient.post(PANEL + '/kalibracja/wysylka')
    assert r.status_code == 201
    p = m.PrintAgentCommand.query.one()
    assert (p.agent_id, p.kind, p.printer, p.status, p.created_by_user_id) == (a.id, 'kalibracja', 'wysylka', 'pending', 7)
    assert ('print:agent', {'kind': 'command'}) in klient.sygnaly
    assert klient.post(PANEL + '/kalibracja/nieznana').status_code == 404
    ROLA['role'] = 'user'
    assert klient.post(PANEL + '/kalibracja/wysylka').status_code == 403


def test_wydania_upload_i_przelaczenie(klient):
    r = klient.post(PANEL + '/wydania', data={'plik': (io.BytesIO(b'MZ-instalator'), 'a.exe'), 'wersja': '2.0.0',
                                              'notatki': 'pierwsze'}, content_type='multipart/form-data')
    assert r.status_code == 201 and r.get_json()['aktywne'] is False
    rid = r.get_json()['id']
    assert klient.post(PANEL + '/wydania', data={'plik': (io.BytesIO(b'x'), 'a.exe'), 'wersja': 'zla'},
                       content_type='multipart/form-data').status_code == 400
    assert klient.patch('%s/wydania/%d/aktywne' % (PANEL, rid), json={'aktywne': True}).get_json()['aktywne'] is True
    assert klient.patch('%s/wydania/%d/aktywne' % (PANEL, rid), json={'aktywne': 'tak'}).status_code == 400
    assert [w['wersja'] for w in klient.get(PANEL + '/wydania').get_json()['wydania']] == ['2.0.0']
    ROLA['role'] = 'user'
    assert klient.post(PANEL + '/wydania', data={}).status_code == 403


def test_stan_bez_starego_agenta(klient):
    """Obsługa zawsze „nowy”, bez pola `stary_agent` — także gdy w prod_config zostały wiersze sprzed migracji."""
    for klucz, wartosc in (('STARY_AGENT_OSTATNI_KONTAKT', '2026-10-22T10:00:00'),
                           ('DRUKARKA_OBSLUGA_etykiety', 'stary'), ('DRUKARKA_OBSLUGA_wysylka', 'stary')):
        db.session.add(ProductionConfig(config_key=klucz, config_value=wartosc, config_type='string'))
    db.session.commit()
    ROLA['role'] = 'user'
    d = klient.get(PANEL + '/stan').get_json()
    assert 'stary_agent' not in d
    assert {x['nazwa']: x['obsluga'] for x in d['drukarki']} == {'etykiety': 'nowy', 'wysylka': 'nowy'}
    assert all('stary' not in x['komunikat'] for x in d['drukarki'])


def test_przelacznika_obslugi_nie_ma(klient):
    _agent_online(('etykiety',))
    for drukarka in ('etykiety', 'wysylka'):
        for agent in ('nowy', 'stary'):
            r = klient.put(PANEL + '/obsluga/' + drukarka, json={'agent': agent})
            assert r.status_code in (404, 405)
    assert ProductionConfig.query.filter(ProductionConfig.config_key.like('DRUKARKA_OBSLUGA%')).count() == 0


def test_kontakt_przezywa_blad_bazy_w_najnowsze(klient, monkeypatch):
    a, h = _agent_online()
    stare = datetime.utcnow() - timedelta(hours=1)
    a.last_seen_at = stare
    db.session.commit()

    class Zepsute:
        class query:
            @staticmethod
            def filter_by(**kw):
                raise SQLAlchemyError('awaria')
    monkeypatch.setattr(agent_api.wydania, 'PrintAgentRelease', Zepsute)
    r = klient.post(V2 + '/kontakt', json={'wersja': '2.0.0'}, headers=h)
    assert r.status_code == 200
    db.session.expire_all()
    assert m.PrintAgent.query.get(a.id).last_seen_at > stare + timedelta(minutes=30)


def test_haki_po_commicie_nie_psuja_odpowiedzi(klient, monkeypatch):
    a, h = _agent_online()
    stare = a.last_seen_at

    def zepsute(*_):
        raise RuntimeError('hak')
    monkeypatch.setattr(agent_api.stan, 'po_zmianie_stanu', zepsute)
    r = klient.post(V2 + '/kontakt', json={'wersja': '2.0.0'}, headers=h)
    assert r.status_code == 200
    db.session.expire_all()
    assert m.PrintAgent.query.get(a.id).last_seen_at >= stare
    assert m.PrintAgent.query.get(a.id).version == '2.0.0'


def test_kontakt_przezywa_blad_sprzatania_kolejki(klient, monkeypatch):
    """Wyjątek z wygaszania po commicie kontaktu (np. 1213 przy cofaniu liczników): 200, kontakt zapisany,
    sygnał stanowisk wysłany, w logu ostrzeżenie."""
    a, h = _agent_online()
    stare = datetime.utcnow() - timedelta(hours=1)
    a.last_seen_at = stare
    db.session.commit()
    sygnaly = []
    monkeypatch.setattr(agent_api.stan, 'po_zmianie_stanu', lambda przed, po: sygnaly.append((przed, po)))

    def zepsute(*_a, **_k):
        raise SQLAlchemyError('1213 zakleszczenie')
    monkeypatch.setattr(kolejka, 'wygas', zepsute)
    ostrzezenia = []
    monkeypatch.setattr(agent_api.logger, 'warning', lambda msg, **kw: ostrzezenia.append(msg))
    r = klient.post(V2 + '/kontakt', json={'wersja': '2.0.1'}, headers=h)
    assert r.status_code == 200 and 'polecenia' in r.get_json()
    assert len(sygnaly) == 1 and ostrzezenia
    db.session.expire_all()
    agent = m.PrintAgent.query.get(a.id)
    assert agent.last_seen_at > stare + timedelta(minutes=30) and agent.version == '2.0.1'
