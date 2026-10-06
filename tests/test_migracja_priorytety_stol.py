# -*- coding: utf-8 -*-
"""Kształt migracji K3 priorytetów produkcji: źródło kafla na stole i nowe akcje logu (spec 2026-10-04, 8.3–8.4).

Jak tests/test_migracja_priorytety.py: SQLite nie zna information_schema ani PREPARE, więc sprawdzamy treść pliku
(czy runner go weźmie, czy kolumny są osłonięte, czy lista akcji zgadza się ze stałymi) i zgodność modelu. Samo
WYKONANIE SQL potwierdza się osobno, dwa razy, na kontenerze db (raport kroku K3).

Plik nie zakłada tabeli audytu produktu (konwencja pakietu).
"""
import re
from pathlib import Path

from migrations.migration_service import MigrationService
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, StationDesk

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-10-06-priorytety-stol-zrodlo.sql"
MIGRACJA_K1 = "2026-10-05-priorytety-produkcji.sql"


def _polecenia():
    assert SCIEZKA.exists(), "brak pliku migracji"
    tresc = SCIEZKA.read_text(encoding="utf-8")
    return [" ".join(p.split()) for p in MigrationService.split_statements(tresc)]


def test_runner_rozpoznaje_nazwe_pliku_i_wykona_go_po_migracji_k1():
    """Runner bierze pliki w kolejności sorted() po nazwie: kolumny dochodzą do tabel z migracji K1."""
    assert SCIEZKA.exists(), "brak pliku migracji"
    assert MigrationService(db=None)._match(SCIEZKA.name) is not None
    assert (KATALOG_MIGRACJI / MIGRACJA_K1).exists()
    assert SCIEZKA.name > MIGRACJA_K1


def test_nie_uzywa_delimiter():
    assert "DELIMITER" not in SCIEZKA.read_text(encoding="utf-8").upper()


def test_kolumny_stolu_osloniete_information_schema():
    """`zrodlo` i `sent_by_user_id`: ADD COLUMN tylko przez PREPARE, po sprawdzeniu w information_schema — drugi
    przebieg niczego nie zmienia."""
    polecenia = _polecenia()
    definicje = {
        "zrodlo": "ADD COLUMN zrodlo VARCHAR(16) NOT NULL DEFAULT ''kolejka''",
        "sent_by_user_id": "ADD COLUMN sent_by_user_id INT NULL",
    }
    for kolumna, definicja in definicje.items():
        sprawdzenie = next(
            i for i, p in enumerate(polecenia)
            if p.startswith("SET @brak") and "information_schema.COLUMNS" in p
            and "TABLE_NAME = 'prod_station_desk'" in p and "COLUMN_NAME = '{}'".format(kolumna) in p)
        zmiana = polecenia[sprawdzenie + 1]
        assert zmiana.startswith("SET @sql = IF(@brak, 'ALTER TABLE prod_station_desk {}'".format(definicja)), zmiana
        assert polecenia[sprawdzenie + 2:sprawdzenie + 5] == [
            "PREPARE krok FROM @sql", "EXECUTE krok", "DEALLOCATE PREPARE krok"], kolumna
    # Poza tymi dwiema kolumnami żadnego gołego ADD COLUMN.
    assert not [p for p in polecenia if p.upper().startswith("ALTER") and "ADD COLUMN" in p.upper()]


def test_akcje_logu_pelna_lista_w_kolejnosci_stalych():
    """MODIFY podaje PEŁNĄ listę wartości — brakująca skasowałaby akcję istniejącym wpisom; nowe na końcu."""
    zmiany = [p for p in _polecenia() if p.startswith("ALTER TABLE prod_priority_log MODIFY action")]
    assert len(zmiany) == 1, zmiany
    wartosci = re.findall(r"'([a-z_]+)'", zmiany[0])
    assert tuple(wartosci) == stale.AKCJE_LOGU
    assert zmiany[0].endswith("NOT NULL")
    assert stale.AKCJE_LOGU[:6] == ('gwiazdki', 'szczebel', 'odlozenie', 'odlozenie_zamkniete', 'ustawienia',
                                    'przeliczenie')
    assert stale.AKCJE_LOGU[6:] == ('wyslanie', 'zdjecie', 'start_stolow')


def test_jedyne_polecenia_to_dwie_kolumny_i_lista_akcji():
    """Migracja nie dotyka niczego poza `prod_station_desk` i `prod_priority_log` (tabele nowe w tym samym
    wdrożeniu — stary kod ich nie zna)."""
    for polecenie in _polecenia():
        assert polecenie.startswith(("SET @brak", "SET @sql", "PREPARE krok", "EXECUTE krok", "DEALLOCATE PREPARE",
                                     "ALTER TABLE prod_priority_log MODIFY action")), polecenie[:80]


def test_model_stolu_ma_zrodlo_i_wysylajacego():
    kolumny = StationDesk.__table__.c
    assert kolumny.zrodlo.nullable is False
    assert kolumny.zrodlo.type.length == 16
    assert kolumny.zrodlo.default.arg == 'kolejka'
    assert kolumny.zrodlo.server_default.arg == 'kolejka'
    assert kolumny.sent_by_user_id.nullable is True
    assert stale.ZRODLA_KAFLA == ('kolejka', 'dorobka', 'biuro', 'start')
    assert stale.ZRODLO_KOLEJKA == 'kolejka' and stale.ZRODLO_DOROBKA == 'dorobka'
    assert stale.ZRODLO_BIURO == 'biuro' and stale.ZRODLO_START == 'start'


def test_model_logu_zna_nowe_akcje():
    assert tuple(PriorityLog.__table__.c.action.type.enums) == stale.AKCJE_LOGU
