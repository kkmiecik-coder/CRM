# -*- coding: utf-8 -*-
"""Parowanie i tokeny agenta druku v2, kontakt, przełącznik obsługi (SQLite; tabele zakłada test)."""
import hashlib
import json
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.drukarki import models as m, stale
from modules.production.drukarki.services import agenci
from tests.logistyka_fixtures import app  # noqa: F401


@pytest.fixture(autouse=True)
def _tabele(app):
    db.metadata.create_all(bind=db.engine, tables=[
        m.PrintAgent.__table__, m.PrintAgentConfig.__table__, m.PrintAgentConfigChange.__table__])


def test_sparuj_token_tylko_jako_skrot(app):
    agent, token = agenci.sparuj('Hala', 1)
    db.session.commit()
    assert token.startswith('wpa_') and len(token) > 40
    assert agent.token_sha256 == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps([agent.token_sha256, agent.name])
    assert m.PrintAgentConfig.query.get(agent.id).version == 1
    assert agenci.agent_z_tokenu(token).id == agent.id
    assert agenci.agent_z_tokenu(token + 'x') is None
    assert agenci.agent_z_tokenu('') is None


def test_token_uniewazniony_nie_dziala(app):
    agent, token = agenci.sparuj('Hala', 1)
    db.session.commit()
    agenci.uniewaznij(agent.id, 1)
    db.session.commit()
    assert agenci.agent_z_tokenu(token) is None


def test_nowy_token_zastepuje_stary(app):
    agent, token = agenci.sparuj('Hala', 1)
    db.session.commit()
    nowy = agenci.nowy_token(agent.id, 1)
    db.session.commit()
    assert agenci.agent_z_tokenu(token) is None
    assert agenci.agent_z_tokenu(nowy).id == agent.id


def test_czy_online_po_120s(app):
    agent, _ = agenci.sparuj('Hala', 1)
    assert agenci.czy_online(agent) is False
    agenci.kontakt(agent, '2.0.0', [{'nazwa': 'etykiety', 'stan': 'gotowa'}], True)
    assert agent.push_connected is True and agent.version == '2.0.0'
    assert json.loads(agent.printers_state)[0]['stan'] == 'gotowa'
    t = agent.last_seen_at
    assert agenci.czy_online(agent, t + timedelta(seconds=stale.AGENT_CISZA_S))
    assert not agenci.czy_online(agent, t + timedelta(seconds=stale.AGENT_CISZA_S + 1))


def test_aktywny_v2_dopiero_po_kontakcie(app):
    agent, _ = agenci.sparuj('Hala', 1)
    db.session.commit()
    assert agenci.aktywny_v2() is None
    agenci.kontakt(agent, '2.0.0', [], False)
    db.session.commit()
    assert agenci.aktywny_v2().id == agent.id
    agenci.uniewaznij(agent.id, 1)
    db.session.commit()
    assert agenci.aktywny_v2() is None
