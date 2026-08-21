# -*- coding: utf-8 -*-
"""Kształt migracji przemianowującej lamella_direction na shape_rotation.

Testy jadą na SQLite, która nie zna information_schema ani PREPARE, więc
sprawdzamy to, co da się sprawdzić bez MySQL-a: czy runner w ogóle weźmie
plik pod uwagę i czy podzieli go na oczekiwane polecenia. Samo wykonanie
SQL trzeba potwierdzić na kontenerze db.
"""

from pathlib import Path

from migrations.migration_service import MigrationService

SCIEZKA = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "2026-08-21-obrot-ksztaltu-shape-rotation.sql"
)


def _tresc():
    return SCIEZKA.read_text(encoding="utf-8")


def test_plik_istnieje():
    assert SCIEZKA.exists(), "brak pliku migracji"


def test_runner_rozpoznaje_nazwe_pliku():
    service = MigrationService(db=None)
    assert service._match(SCIEZKA.name) is not None, (
        "nazwa nie pasuje do wzorca runnera — migracja zostałaby POMINIĘTA"
    )


def test_nie_uzywa_delimitera():
    assert "DELIMITER" not in _tresc().upper(), "runner nie obsługuje DELIMITER"


def test_dzieli_sie_na_dziewiec_polecen():
    # 2x SET + PREPARE/EXECUTE/DEALLOCATE dla rename, potem to samo dla zerowania.
    polecenia = MigrationService.split_statements(_tresc())
    assert len(polecenia) == 9, [p[:40] for p in polecenia]


def test_rename_i_zerowanie_sa_osloniete_warunkiem():
    tresc = _tresc()
    assert "information_schema.COLUMNS" in tresc, (
        "brak warunku na istnienie kolumny — migracja nie byłaby idempotentna"
    )
    assert "RENAME COLUMN lamella_direction TO shape_rotation" in tresc
    assert "SET shape_rotation = 0" in tresc
