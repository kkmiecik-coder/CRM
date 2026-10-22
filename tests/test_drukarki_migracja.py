# -*- coding: utf-8 -*-
"""Schemat agenta druku v2 (Task 1). Testy jadą na SQLite, więc sprawdzają modele (create_all), nazwę i
składnię pliku migracji; wykonanie samej migracji na MySQL weryfikuje się osobno na kontenerze `db`."""
import os

from sqlalchemy import inspect

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.drukarki import stale
from modules.production.drukarki import models as m_drukarki
from modules.production.drukarki.models import PrintAgent, PrintAgentRelease
from modules.production.models import LabelPrintJob
from tests.logistyka_fixtures import app  # noqa: F401

KATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
PLIK = '2026-10-23-agent-druku-v2.sql'

TABELE = ('prod_print_agents', 'prod_print_agent_config', 'prod_print_agent_config_changes',
          'prod_print_agent_commands', 'prod_print_agent_releases')
KOLUMNY_KOLEJKI = ('lease_until', 'claimed_by_agent_id', 'sending_at', 'reprint_of_job_id')
MODELE = (m_drukarki.PrintAgent, m_drukarki.PrintAgentConfig, m_drukarki.PrintAgentConfigChange,
          m_drukarki.PrintAgentCommand, m_drukarki.PrintAgentRelease)


def _zaloz_tabele():
    # Wspólna fixture `app` zakłada tylko tabele logistyki; tabele agenta druku dokładamy tu.
    db.metadata.create_all(bind=db.engine, tables=[m.__table__ for m in MODELE])


def test_migracja_idempotentna_i_kompletna(app):
    # Nazwa pliku rozpoznawana przez runner.
    assert MigrationService(db=None)._match(PLIK) is not None
    # Plik rozcina się na polecenia i zawiera wszystkie tabele oraz kolumny kolejki.
    tresc = open(os.path.join(KATALOG, PLIK), encoding='utf-8').read()
    assert MigrationService.split_statements(tresc)
    for t in TABELE:
        assert f'CREATE TABLE IF NOT EXISTS {t} ' in tresc
    for k in KOLUMNY_KOLEJKI:
        assert k in tresc
    # Modele zakładają te same tabele i kolumny (create_all).
    _zaloz_tabele()
    insp = inspect(db.engine)
    for t in TABELE:
        assert insp.has_table(t), t
    kolumny = {c['name'] for c in insp.get_columns('prod_print_queue')}
    assert set(KOLUMNY_KOLEJKI) <= kolumny


def test_status_kolejki_ma_osiem_wartosci_w_kolejnosci():
    enum = LabelPrintJob.__table__.c.status.type
    assert tuple(enum.enums) == ('pending', 'claimed', 'sending', 'printed', 'failed', 'expired',
                                 'unknown', 'cancelled')
    assert (LabelPrintJob.STATUS_CLAIMED, LabelPrintJob.STATUS_SENDING,
            LabelPrintJob.STATUS_UNKNOWN, LabelPrintJob.STATUS_CANCELLED) == \
        ('claimed', 'sending', 'unknown', 'cancelled')


def test_stale_i_latest_active(app):
    assert stale.AGENT_CISZA_S == 120 and stale.DZIERZAWA_S == 120
    assert set(stale.ROLE) == {'etykiety', 'wysylka'}
    assert 'gotowa' in stale.STANY_DRUKARKI and len(stale.STANY_DRUKARKI) == 7
    _zaloz_tabele()
    assert PrintAgentRelease.latest_active() is None
    db.session.add(PrintAgentRelease(version_name='2.0.0', file_path='x', file_size_bytes=1, sha256='a' * 64))
    db.session.add(PrintAgent(name='hala', token_sha256='b' * 64))
    db.session.commit()
    assert PrintAgentRelease.latest_active().version_name == '2.0.0'
