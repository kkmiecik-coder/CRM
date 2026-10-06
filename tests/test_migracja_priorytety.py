# -*- coding: utf-8 -*-
"""Kształt migracji priorytetów produkcji P1 (spec 2026-10-04, sekcja 8).

Testy jadą na SQLite, która nie zna information_schema, PREPARE ani INSERT IGNORE. Sprawdzamy więc to, co da się
sprawdzić bez MySQL-a: czy runner weźmie plik pod uwagę, czy każdy ALTER jest osłonięty, czy są trzy tabele, seed
dziewięciu szczebli w kolejności z 3.1 i 38 wierszy `prod_config` z kluczami ze specu 8.6. Samo WYKONANIE SQL
potwierdza się osobno, dwa razy, na kontenerze db (plan K1, Task 1 Step 3).

Plik nie zakłada tabeli audytu produktu i nie tworzy żadnego modelu — czyta wyłącznie treść plików z dysku
(konwencja pakietu). Wzorzec: tests/test_migracja_krawedzie.py.
"""

import re
from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-10-05-priorytety-produkcji.sql"

STANOWISKA = ("cutting", "assembly", "gluing", "formatting", "edges", "painting", "packaging")
KOLUMNY_ZAMOWIENIA = ("priority_stars", "priority_stars_set_at", "priority_stars_set_by",
                      "priority_rank", "priority_rung")
TABELE = ("prod_priority_rungs", "prod_priority_log", "prod_station_desk")
SILNIK = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"


def _tresc():
    assert SCIEZKA.exists(), "brak pliku migracji"
    return SCIEZKA.read_text(encoding="utf-8")


def _bez_bialych(tekst):
    """Skleja polecenie w jedną linię — split_statements wycina komentarze, ale zostawia znaki nowej linii."""
    return " ".join(tekst.split())


def _polecenia():
    return [_bez_bialych(p) for p in MigrationService.split_statements(_tresc())]


def _tabela(nazwa):
    """Polecenie CREATE TABLE podanej tabeli (jedno); brak → test pada."""
    pasujace = [p for p in _polecenia() if p.startswith("CREATE TABLE IF NOT EXISTS {} (".format(nazwa))]
    assert len(pasujace) == 1, (nazwa, [p[:60] for p in pasujace])
    return pasujace[0]


def wiersze_konfiguracji(tresc=None):
    """{klucz: (wartość, typ)} z poleceń `INSERT IGNORE INTO prod_config` migracji.

    Używa go też tests/test_priorytety_ustawienia.py: klucze stanowiskowe migracji muszą być dosłownie tymi,
    które składa `priorytety.stale.klucz_*`.
    """
    polecenia = ([_bez_bialych(p) for p in MigrationService.split_statements(tresc)]
                 if tresc is not None else _polecenia())
    wiersze = {}
    for polecenie in polecenia:
        if not polecenie.startswith("INSERT IGNORE INTO prod_config"):
            continue
        assert "(config_key, config_value, config_description, config_type, created_at, updated_at)" in polecenie
        for klucz, wartosc, typ in re.findall(
                r"\(\s*'([A-Za-z_]+)'\s*,\s*'([^']*)'\s*,\s*'[^']*'\s*,\s*'(string|integer)'\s*,\s*NOW\(\)\s*,"
                r"\s*NOW\(\)\s*\)", polecenie):
            assert klucz not in wiersze, "klucz dwa razy: {}".format(klucz)
            wiersze[klucz] = (wartosc, typ)
    return wiersze


def test_plik_istnieje():
    assert SCIEZKA.exists(), "brak pliku migracji"


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAŻNIK: _match patrzy na nazwę, nie na plik. Nazwa spoza wzorca = migracja POMINIĘTA bez błędu."""
    assert MigrationService(db=None)._match(SCIEZKA.name) is not None


def test_sortuje_sie_po_ostatniej_migracji_logistyki():
    """Runner wykonuje pliki w kolejności sorted() po nazwie; FK do prod_routes wymaga tabel logistyki."""
    assert SCIEZKA.name > "2026-10-02-raport-planowana-trasa.sql"


def test_nie_uzywa_delimiter():
    """Runner dzieli plik wyłącznie po średniku. Szukamy słowa w CAŁEJ treści, razem z komentarzami."""
    assert "DELIMITER" not in _tresc().upper()


def test_kolumny_prod_orders_osloniete_information_schema():
    """Pięć kolumn 8.1 i indeks rangi: każdy ALTER tylko przez PREPARE, po sprawdzeniu w information_schema."""
    polecenia = _polecenia()
    assert not [p for p in polecenia if p.upper().startswith("ALTER")], "goły ALTER nie jest idempotentny"

    definicje = {
        "priority_stars": "ADD COLUMN priority_stars TINYINT NOT NULL DEFAULT 0",
        "priority_stars_set_at": "ADD COLUMN priority_stars_set_at DATETIME NULL",
        "priority_stars_set_by": "ADD COLUMN priority_stars_set_by INT NULL",
        "priority_rank": "ADD COLUMN priority_rank INT NULL",
        "priority_rung": "ADD COLUMN priority_rung INT NULL",
    }
    assert set(definicje) == set(KOLUMNY_ZAMOWIENIA)
    for kolumna, definicja in definicje.items():
        sprawdzenie = next(
            i for i, p in enumerate(polecenia)
            if p.startswith("SET @brak") and "information_schema.COLUMNS" in p
            and "TABLE_NAME = 'prod_orders'" in p and "COLUMN_NAME = '{}'".format(kolumna) in p)
        zmiana = polecenia[sprawdzenie + 1]
        assert zmiana.startswith("SET @sql = IF(@brak, 'ALTER TABLE prod_orders {}'".format(definicja)), zmiana
        assert polecenia[sprawdzenie + 2:sprawdzenie + 5] == [
            "PREPARE krok FROM @sql", "EXECUTE krok", "DEALLOCATE PREPARE krok"], kolumna

    indeks = next(
        i for i, p in enumerate(polecenia)
        if p.startswith("SET @brak") and "information_schema.STATISTICS" in p
        and "TABLE_NAME = 'prod_orders'" in p and "INDEX_NAME = 'ix_prod_orders_priority_rank'" in p)
    assert polecenia[indeks + 1].startswith(
        "SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD INDEX ix_prod_orders_priority_rank (priority_rank)'")
    assert polecenia[indeks + 2:indeks + 5] == ["PREPARE krok FROM @sql", "EXECUTE krok", "DEALLOCATE PREPARE krok"]
    # Indeks po kolumnie: ADD INDEX na nieistniejącej kolumnie wywróciłby pierwszy przebieg.
    kolumna_rangi = next(i for i, p in enumerate(polecenia) if "COLUMN_NAME = 'priority_rank'" in p)
    assert kolumna_rangi < indeks


def test_trzy_tabele_create_if_not_exists():
    for nazwa in TABELE:
        assert _tabela(nazwa).endswith(SILNIK), nazwa

    szczeble = _tabela("prod_priority_rungs")
    assert "kind ENUM('stars','tag','route') NOT NULL" in szczeble
    assert "position INT NOT NULL" in szczeble
    assert "UNIQUE KEY uq_prod_priority_rungs_stars (kind, stars)" in szczeble
    assert "UNIQUE KEY uq_prod_priority_rungs_tag (kind, tag)" in szczeble
    assert "UNIQUE KEY uq_prod_priority_rungs_route (route_id)" in szczeble
    assert ("CONSTRAINT fk_prod_priority_rungs_route FOREIGN KEY (route_id) REFERENCES prod_routes (id) "
            "ON DELETE CASCADE") in szczeble

    log = _tabela("prod_priority_log")
    assert ("action ENUM('gwiazdki','szczebel','odlozenie','odlozenie_zamkniete','ustawienia','przeliczenie') "
            "NOT NULL") in log
    for kolumna in ("order_id", "route_id", "station_code", "created_at"):
        assert "KEY ix_prod_priority_log_{0} ({0})".format(kolumna) in log, kolumna
    assert "FOREIGN KEY (order_id) REFERENCES prod_orders (id) ON DELETE CASCADE" in log
    assert "created_at DATETIME NOT NULL" in log

    stol = _tabela("prod_station_desk")
    assert "unit_key VARCHAR(24) NOT NULL" in stol
    assert "UNIQUE KEY uq_prod_station_desk_unit (station_code, unit_key)" in stol
    assert "FOREIGN KEY (order_id) REFERENCES prod_orders (id) ON DELETE CASCADE" in stol
    assert "FOREIGN KEY (product_id) REFERENCES prod_products (id) ON DELETE CASCADE" in stol
    assert "pulled_at DATETIME NOT NULL" in stol
    assert "postponed_at DATETIME NULL" in stol


def test_seed_dziewieciu_szczebli_w_kolejnosci_3_1():
    """Jedno INSERT IGNORE z dziewięcioma krotkami: ★★★★★, Po terminie, ★★★★, Blisko terminu, Rozpoczęte, ★★★…"""
    wstawki = [p for p in _polecenia() if p.startswith("INSERT IGNORE INTO prod_priority_rungs")]
    assert len(wstawki) == 1, [p[:60] for p in wstawki]
    assert "(kind, stars, tag, position, created_at, updated_at)" in wstawki[0]
    krotki = re.findall(r"\(\s*'(stars|tag|route)'\s*,\s*(\d+|NULL)\s*,\s*(?:'(\w+)'|NULL)\s*,\s*(\d+)\s*,"
                        r"\s*NOW\(\)\s*,\s*NOW\(\)\s*\)", wstawki[0])
    assert krotki == [
        ("stars", "5", "", "1"),
        ("tag", "NULL", "po_terminie", "2"),
        ("stars", "4", "", "3"),
        ("tag", "NULL", "blisko_terminu", "4"),
        ("tag", "NULL", "rozpoczete", "5"),
        ("stars", "3", "", "6"),
        ("stars", "2", "", "7"),
        ("stars", "1", "", "8"),
        ("stars", "0", "", "9"),
    ]
    # Seed po tabeli: INSERT do nieistniejącej tabeli wywróciłby pierwszy przebieg.
    polecenia = _polecenia()
    assert polecenia.index(_tabela("prod_priority_rungs")) < polecenia.index(wstawki[0])


def test_38_wierszy_prod_config():
    oczekiwane = {
        "priorytety_blisko_terminu_dni": ("3", "integer"),
        "priorytety_min_app_version_code": ("0", "integer"),
        "DEADLINE_DAY_TYPE": ("robocze", "string"),
    }
    for kod in STANOWISKA:
        oczekiwane["priorytety_tryb_" + kod] = ("stary", "string")
        oczekiwane["priorytety_stol_" + kod] = ("2", "integer")
        oczekiwane["priorytety_jednostka_" + kod] = (
            "zamowienie" if kod in ("formatting", "packaging") else "pozycja", "string")
        oczekiwane["priorytety_limit_odlozen_" + kod] = ("10", "integer")
        oczekiwane["priorytety_blokada_" + kod] = ("", "string")
    assert len(oczekiwane) == 38

    wiersze = wiersze_konfiguracji()
    assert wiersze == oczekiwane

    # Każdy zapis do prod_config to INSERT IGNORE — biuro mogło już zmienić wartość, drugi przebieg jej nie rusza.
    for polecenie in _polecenia():
        if "prod_config" in polecenie:
            assert polecenie.startswith("INSERT IGNORE INTO prod_config"), polecenie[:80]


def test_brak_zmian_enum_istniejacych_tabel():
    """Spec 8.7: stary worker w oknie wdrożenia nie może zobaczyć nowej wartości ENUM ani zmienionej kolumny."""
    gora = _tresc().upper()
    assert "MODIFY" not in gora
    assert " CHANGE " not in gora
    assert "DROP " not in gora
    for polecenie in _polecenia():
        if "ALTER TABLE" not in polecenie.upper():
            continue
        # Jedyne ALTER-y to ADD COLUMN / ADD INDEX na prod_orders, w napisie dla PREPARE.
        assert "ALTER TABLE prod_orders ADD " in polecenie, polecenie[:120]
        assert "ENUM" not in polecenie.upper(), polecenie[:120]
        for tabela in ("prod_products", "prod_logistics_log", "prod_routes", "prod_config"):
            assert "ALTER TABLE {}".format(tabela) not in polecenie, polecenie[:120]
