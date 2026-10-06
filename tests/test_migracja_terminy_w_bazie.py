# -*- coding: utf-8 -*-
"""Migracja terminów w bazie: wiersze `DEADLINE_DEFAULT_DAYS` = 10 i `DEADLINE_FINISHED_DAYS` = 14 w `prod_config`
(decyzja Konrada 5.10, spec priorytetów 2026-10-04, 4.3).

Jak tests/test_migracja_priorytety_stol.py: sprawdzamy treść pliku (czy runner go weźmie, czy to wyłącznie
`INSERT IGNORE` — istniejących wierszy nie nadpisuje) i wykonanie na SQLite. Wykonanie na MySQL dwa razy potwierdza
się osobno na kopii produkcji (raport pakietu wdrożenia).

Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import re
from pathlib import Path

from sqlalchemy import text

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.models import ProductionConfig
from tests.logistyka_fixtures import app  # noqa: F401

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-10-07-terminy-w-bazie.sql"


def _polecenia():
    assert SCIEZKA.exists(), "brak pliku migracji"
    tresc = SCIEZKA.read_text(encoding="utf-8")
    return [" ".join(p.split()) for p in MigrationService.split_statements(tresc)]


def test_runner_rozpoznaje_nazwe_i_wykona_po_migracjach_priorytetow():
    assert SCIEZKA.exists(), "brak pliku migracji"
    assert MigrationService(db=None)._match(SCIEZKA.name) is not None
    poprzednie = sorted(p.name for p in KATALOG_MIGRACJI.glob("2026-*.sql") if p.name != SCIEZKA.name)
    assert SCIEZKA.name > poprzednie[-1]


def test_nie_uzywa_delimiter():
    assert "DELIMITER" not in SCIEZKA.read_text(encoding="utf-8").upper()


def test_jedno_insert_ignore_z_dwoma_wierszami_10_i_14():
    """Tylko `INSERT IGNORE` — wartość zmieniona już w Konfiguracji (albo dzisiejsze 10 na produkcji) zostaje."""
    polecenia = _polecenia()
    assert len(polecenia) == 1, polecenia
    p = polecenia[0]
    assert p.startswith("INSERT IGNORE INTO prod_config (config_key, config_value, config_description, "
                        "config_type, created_at, updated_at) VALUES"), p
    assert "('DEADLINE_DEFAULT_DAYS', '10'," in p
    assert "('DEADLINE_FINISHED_DAYS', '14'," in p
    assert p.count("'integer'") == 2
    for zakazane in (r"\bUPDATE\s", r"\bDELETE\b", r"\bREPLACE\b", r"\bON DUPLICATE\b"):
        assert not re.search(zakazane, p.upper()), zakazane


def _wykonaj(sql):
    # SQLite zna INSERT OR IGNORE zamiast INSERT IGNORE i nie zna NOW() — reszta polecenia bez zmian.
    sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE").replace("NOW()", "CURRENT_TIMESTAMP")
    db.session.execute(text(sql))
    db.session.commit()


def _wiersze():
    return {w.config_key: (w.config_value, w.config_type) for w in ProductionConfig.query.filter(
        ProductionConfig.config_key.in_(("DEADLINE_DEFAULT_DAYS", "DEADLINE_FINISHED_DAYS"))).all()}


def test_wykonanie_zaklada_brakujace_i_nie_rusza_istniejacych(app):  # noqa: F811
    with app.app_context():
        ProductionConfig.query.filter(ProductionConfig.config_key.like("DEADLINE_%")).delete(
            synchronize_session=False)
        # jak na produkcji: surowe ustawione (tu celowo inna wartość niż 10), z wykończeniem brak
        db.session.add(ProductionConfig(config_key="DEADLINE_DEFAULT_DAYS", config_value="12",
                                        config_type="integer"))
        db.session.commit()
        sql = _polecenia()[0]
        _wykonaj(sql)
        assert _wiersze() == {"DEADLINE_DEFAULT_DAYS": ("12", "integer"),
                              "DEADLINE_FINISHED_DAYS": ("14", "integer")}
        _wykonaj(sql)   # drugi przebieg: bez zmian
        assert _wiersze() == {"DEADLINE_DEFAULT_DAYS": ("12", "integer"),
                              "DEADLINE_FINISHED_DAYS": ("14", "integer")}
        ProductionConfig.query.filter(ProductionConfig.config_key.like("DEADLINE_%")).delete(
            synchronize_session=False)
        _wykonaj(sql)   # pusta baza: oba wiersze 10 / 14
        assert _wiersze() == {"DEADLINE_DEFAULT_DAYS": ("10", "integer"),
                              "DEADLINE_FINISHED_DAYS": ("14", "integer")}
