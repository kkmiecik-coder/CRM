# -*- coding: utf-8 -*-
"""Dokument konfiguracji agenta druku v2: domyślna, walidacja, wersje, konflikty i historia."""
import copy

import pytest

from extensions import db
from modules.production.drukarki import models as m
from modules.production.drukarki.services import agenci, konfiguracja
from modules.production.models import ProductionConfig
from modules.production.services import package_label
from tests.logistyka_fixtures import app  # noqa: F401


@pytest.fixture(autouse=True)
def _tabele(app):
    db.metadata.create_all(bind=db.engine, tables=[
        m.PrintAgent.__table__, m.PrintAgentConfig.__table__, m.PrintAgentConfigChange.__table__])


def _drukarka(**kw):
    d = {'nazwa': 'etykiety', 'ip': '10.0.0.5', 'port': 9100, 'model': 'XP-423B',
         'odczyt_stanu': 'snmp', 'limit_wysylki_s': 30}
    d.update(kw)
    return d


def _cfg(lt=-16, dx=0, **kw):
    c = konfiguracja.domyslna()
    c['przesuniecia']['etykiety']['lt'] = lt
    c['przesuniecia']['wysylka']['dx'] = dx
    c.update(kw)
    return c


def _wartosc(klucz):
    return ProductionConfig.query.filter_by(config_key=klucz).first().config_value


def test_domyslna_jest_poprawna(app):
    d = konfiguracja.domyslna()
    assert d['drukarki'] == [] and d['godziny']['pn_pt'] == ['05:30', '15:30']
    assert d['przesuniecia']['etykiety'] == {'lt': -16, 'ls': 112}
    assert konfiguracja.waliduj(d) == []


def test_walidacja_komunikaty_po_polsku(app):
    c = _cfg()
    c['drukarki'] = [_drukarka(ip='999.1.1.1'), _drukarka(port=70000, nazwa='wysylka'),
                     _drukarka(nazwa='inna'), _drukarka()]
    c['przesuniecia']['wysylka']['dy'] = package_label.MAKS_PRZESUNIECIA + 1
    c['godziny']['pn_pt'] = ['16:00', '15:00']
    c['godziny']['sobota'] = ['7:00', '12:00']
    tekst = ' | '.join(konfiguracja.waliduj(c))
    for fragment in ('niepoprawny adres IP', 'port musi być', 'Nieznana nazwa drukarki', 'występuje więcej niż raz',
                     'Przesunięcie paczek dy', 'początek musi być wcześniej niż koniec', 'HH:MM'):
        assert fragment in tekst
    assert konfiguracja.waliduj({'drukarki': [_drukarka()], **{k: v for k, v in _cfg().items() if k != 'drukarki'}}) == []
    assert konfiguracja.waliduj('x') == ['Konfiguracja musi być obiektem.']


def test_zapis_podbija_wersje_i_przesuniecia_w_prod_config(app):
    agent, _ = agenci.sparuj('Hala', 1)
    db.session.commit()
    c = _cfg(lt=-20, dx=8)
    c['przesuniecia']['etykiety']['ls'] = 100
    c['przesuniecia']['wysylka']['dy'] = -4
    wiersz, nadpisana = konfiguracja.zapisz(agent.id, c, 1, 'crm', 'user:1')
    db.session.commit()
    assert wiersz.version == 2 and nadpisana is None
    assert _wartosc('LABEL_PRINTER_OFFSET_LT') == '-20' and _wartosc('LABEL_PRINTER_OFFSET_LS') == '100'
    assert _wartosc(package_label.KLUCZ_PRZESUNIECIA_X) == '8'
    assert _wartosc(package_label.KLUCZ_PRZESUNIECIA_Y) == '-4'
    assert package_label.wczytaj_przesuniecie() == (8, -4)


def test_konflikt_wygrywa_pozniejsza_i_historia(app):
    agent, _ = agenci.sparuj('Hala', 1)
    db.session.commit()
    _, n1 = konfiguracja.zapisz(agent.id, _cfg(lt=-10), 1, 'crm', 'user:1')
    db.session.commit()
    wiersz, n2 = konfiguracja.zapisz(agent.id, _cfg(lt=-30), 1, 'agent', 'agent:%s' % agent.id)
    db.session.commit()
    assert n1 is None and n2 == 2 and wiersz.version == 3
    assert wiersz.updated_source == 'agent'
    assert _wartosc('LABEL_PRINTER_OFFSET_LT') == '-30'
    h = konfiguracja.historia(agent.id)
    assert [x['wersja'] for x in h] == [3, 2]
    assert h[0]['nadpisana_wersja'] == 2 and h[0]['wersja_bazowa'] == 1 and h[0]['zrodlo'] == 'agent'
    assert h[0]['przed']['przesuniecia']['etykiety']['lt'] == -10
    assert h[0]['po']['przesuniecia']['etykiety']['lt'] == -30
    assert h[1]['nadpisana_wersja'] is None
