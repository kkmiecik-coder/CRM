# -*- coding: utf-8 -*-
"""Migracja cofająca wdrożenie 8.10 (logistyka etapy 1–4 i priorytety produkcji) — kształt pliku.

Migrację wykonuje stary kod (`main` sprzed wdrożenia) przy deployu gałęzi wycofania, PRZED restartem. Na tej gałęzi
nie ma modeli logistyki ani priorytetów, a SQLite nie zna information_schema ani PREPARE — sprawdzamy więc treść:
czy runner weźmie plik po wszystkich migracjach wdrożenia, czy każdy przepis jest osłonięty (baza bez tabel
logistyki nie może zablokować deployu błędem 1146/1054) i czy są wszystkie przepisy ze specyfikacji logistyki.
Wykonanie na MySQL (dwa razy, kopia produkcji z danymi w nowych stanach) — raport pakietu wdrożenia.
"""
import re
from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-10-08-wycofanie-logistyki.sql"
# Ostatnia migracja wdrożenia 8.10 (gałąź wdrożeniowa) — tu jej pliku nie ma, runner zna tylko wpis w schema_migrations.
OSTATNIA_MIGRACJA_WDROZENIA = "2026-10-07-terminy-w-bazie.sql"


def _tresc():
    assert SCIEZKA.exists(), "brak pliku migracji"
    return SCIEZKA.read_text(encoding="utf-8")


def _polecenia():
    return [" ".join(p.split()) for p in MigrationService.split_statements(_tresc())]


def test_runner_rozpoznaje_nazwe_i_wykona_po_migracjach_wdrozenia():
    assert MigrationService(db=None)._match(SCIEZKA.name) is not None
    assert SCIEZKA.name > OSTATNIA_MIGRACJA_WDROZENIA
    assert SCIEZKA.name == sorted(p.name for p in KATALOG_MIGRACJI.glob("*.sql"))[-1]


def test_bez_delimiter_i_bez_zmian_schematu():
    """Tylko dane: ENUM-y, kolumny i tabele zostają (spec etapu 4, sekcja 14; spec priorytetów 11)."""
    tresc = _tresc().upper()
    assert "DELIMITER" not in tresc
    for polecenie in _polecenia():
        gorne = polecenie.upper()
        assert not re.match(r"(ALTER|DROP|CREATE|TRUNCATE|RENAME)\b", gorne), polecenie[:80]


def test_bez_parametrow_wiazanych():
    """Runner woła db.text(polecenie): `:slowo` zostałoby wzięte za parametr i polecenie by padło."""
    for polecenie in _polecenia():
        assert not re.search(r"(?<!:):[A-Za-z_]", polecenie), polecenie[:120]


def test_kazdy_zapis_osloniety_information_schema():
    """Żadnego gołego UPDATE/DELETE — każde idzie przez PREPARE po sprawdzeniu katalogu (baza bez tabel logistyki,
    np. po nieudanym wdrożeniu, nie może zablokować deployu wycofania)."""
    polecenia = _polecenia()
    for polecenie in polecenia:
        assert polecenie.startswith(("SET @", "PREPARE ", "EXECUTE ", "DEALLOCATE PREPARE ")), polecenie[:80]
    assert sum(p.startswith("SET @sql") for p in polecenia) == sum(p.startswith("EXECUTE ") for p in polecenia)


def _przepisy():
    return [p for p in _polecenia() if p.startswith("SET @sql")]


def _jest(fragment):
    return any(fragment in p for p in _przepisy())


def test_przepis_statusy_pozycji_spec_etap4_14_pkt3():
    assert _jest("UPDATE prod_products SET current_status = ''spakowane'' WHERE current_status IN "
                 "(''zweryfikowane'', ''zaladowane'', ''dostarczone'')")
    assert _jest("DELETE FROM prod_config WHERE config_key = ''logistyka_wydane_dostarczone''")


def test_przepis_trasy_i_log_dostawy_spec_etap4_14_pkt4():
    assert _jest("UPDATE prod_routes SET status = ''zatwierdzona'' WHERE status IN (''zaladowana'', ''w_trasie'')")
    assert _jest("UPDATE prod_logistics_log SET action = ''trasa_status'' WHERE action IN (''zaladunek'', "
                 "''zostaje'', ''wyjazd'', ''dostarczone'', ''niedostarczone'', ''dostarczenie_cofniete'')")


def test_przepis_u10_spec_etap4_14_pkt6():
    assert _jest("UPDATE prod_route_stops SET not_delivered_at = NULL, not_delivered_reason = NULL, "
                 "not_delivered_note = NULL, not_delivered_by_worker_id = NULL WHERE not_delivered_at IS NOT NULL")
    assert _jest("UPDATE prod_logistics_log SET action = ''trasa_status'', note = LEFT(CONCAT(''cofniete "
                 "niedostarczenie: '', COALESCE(old_value, '''')), 255) WHERE action = ''niedostarczenie_cofniete''")


def test_przepis_etykiety_paczek_w_kolejce_druku():
    """Stary `GET /print-agent/jobs` nie filtruje drukarki — oczekujące etykiety paczek 100×150 poszłyby na drukarkę
    etykiet produktów 60×40. Wygaszamy je (status znany staremu Enum)."""
    assert _jest("UPDATE prod_print_queue SET status = ''expired''")
    assert _jest("WHERE status = ''pending'' AND (printer <> ''etykiety'' OR package_id IS NOT NULL)")


def test_przepis_blokada_dorobek_jak_stary_kod():
    """Stary kod: doróbka do czasu Formatowania ma lock_priority(1) — ranga 1, blokada, ramka. Nowy kod blokady
    zdejmuje (rangi z drabiny), a stare przeliczenie pomija tylko zablokowane."""
    assert _jest("UPDATE prod_products SET priority_rank = 1, priority_manual_override = 1, is_priority = 1 "
                 "WHERE original_product_id IS NOT NULL AND current_status IN (''czeka_na_wyciecie'', "
                 "''czeka_na_skladanie'', ''czeka_na_sklejanie'')")


def test_przepis_kopia_priorytetow_sprzed_wdrozenia_opcjonalny():
    """Ręczne flagi `is_priority` i blokady rang sprzed wdrożenia nadpisuje pierwsze przeliczenie nowego kodu.
    Jeśli przed wdrożeniem zrobiono kopię (runbook K7), migracja je przywraca; bez kopii — pomija."""
    tabela = "zz_przed_wdrozeniem_2026_10_08_priorytety"
    assert any(p.startswith("SET @kopia") and "TABLE_NAME = '%s'" % tabela in p for p in _polecenia())
    assert _jest("UPDATE prod_products p JOIN %s k ON k.id = p.id SET p.priority_rank = k.priority_rank, "
                 "p.priority_manual_override = k.priority_manual_override, p.is_priority = k.is_priority" % tabela)
