# -*- coding: utf-8 -*-
"""Kształt migracji przemianowujących lamella_direction na shape_rotation.

Testy jadą na SQLite, która nie zna information_schema ani PREPARE, więc
sprawdzamy to, co da się sprawdzić bez MySQL-a: czy runner w ogóle weźmie
plik pod uwagę i czy podzieli go na oczekiwane polecenia. Samo wykonanie
SQL trzeba potwierdzić na kontenerze db.

Dwie migracje z tego samego dnia (`quote_items_details` z Taska 1,
`prod_products` z Taska 3b) mają identyczny kształt SQL — różni je tylko
nazwa tabeli i pliku. Testy są sparametryzowane po ścieżce, żeby nie
duplikować tych samych dwunastu asercji w dwóch prawie identycznych
plikach; parametr `tabela` odróżnia treść specyficzną dla migracji.
"""

from pathlib import Path

import pytest

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"

SCIEZKA_QUOTE = KATALOG_MIGRACJI / "2026-08-21-obrot-ksztaltu-shape-rotation.sql"
SCIEZKA_PROD = KATALOG_MIGRACJI / "2026-08-21-prod-products-shape-rotation.sql"

PRZYPADKI = [
    pytest.param(SCIEZKA_QUOTE, "quote_items_details", id="quote_items_details"),
    pytest.param(SCIEZKA_PROD, "prod_products", id="prod_products"),
]


def _tresc(sciezka):
    return sciezka.read_text(encoding="utf-8")


@pytest.mark.parametrize("sciezka, tabela", PRZYPADKI)
def test_plik_istnieje(sciezka, tabela):
    assert sciezka.exists(), "brak pliku migracji"


@pytest.mark.parametrize("sciezka, tabela", PRZYPADKI)
def test_runner_rozpoznaje_nazwe_pliku(sciezka, tabela):
    service = MigrationService(db=None)
    assert service._match(sciezka.name) is not None, (
        "nazwa nie pasuje do wzorca runnera — migracja zostałaby POMINIĘTA"
    )


@pytest.mark.parametrize("sciezka, tabela", PRZYPADKI)
def test_nie_uzywa_delimitera(sciezka, tabela):
    assert "DELIMITER" not in _tresc(sciezka).upper(), "runner nie obsługuje DELIMITER"


@pytest.mark.parametrize("sciezka, tabela", PRZYPADKI)
def test_dzieli_sie_na_dziewiec_polecen(sciezka, tabela):
    # 2x SET + PREPARE/EXECUTE/DEALLOCATE dla rename, potem to samo dla zerowania.
    polecenia = MigrationService.split_statements(_tresc(sciezka))
    assert len(polecenia) == 9, [p[:40] for p in polecenia]


@pytest.mark.parametrize("sciezka, tabela", PRZYPADKI)
def test_rename_i_zerowanie_sa_osloniete_warunkiem(sciezka, tabela):
    tresc = _tresc(sciezka)
    assert "information_schema.COLUMNS" in tresc, (
        "brak warunku na istnienie kolumny — migracja nie byłaby idempotentna"
    )
    assert f"TABLE_NAME = '{tabela}'" in tresc
    assert "RENAME COLUMN lamella_direction TO shape_rotation" in tresc
    assert "SET shape_rotation = 0" in tresc
