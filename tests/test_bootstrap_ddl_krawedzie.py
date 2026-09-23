# -*- coding: utf-8 -*-
"""Parytet bootstrapowego DDL z modelem po podziale wykanczania.

scripts/create_split_tables.sql i scripts/add_rework_columns.sql stoja POZA
runnerem migracji — swieze srodowisko dostaje schemat wlasnie z nich. Gdy nikt
ich nie ruszy, nowa maszyna wstaje ze STARYM schematem, a migracja
2026-09-15-krawedzie-podzial-wykanczania.sql nie ma czego przemianowac.

Testy czytaja tresc plikow (SQLite nie wykona MySQL-owego DDL) i porownuja ja
z modelem SQLAlchemy, ktory jest zrodlem prawdy po warstwie W1.

Plik nie zaklada tabeli audytu produktu (ProductionProductEvent) i nie tworzy
zadnego modelu — importuje wylacznie definicje kolumn (patrz ograniczenia
globalne planu: listener audytu trzyma globalny cache dostepnosci tabeli).
"""

from pathlib import Path

KATALOG_SKRYPTOW = Path(__file__).resolve().parents[1] / "scripts"
SCIEZKA_SPLIT = KATALOG_SKRYPTOW / "create_split_tables.sql"


def _tresc(sciezka):
    return sciezka.read_text(encoding="utf-8")


def test_bootstrap_ma_status_czeka_na_krawedzie():
    tresc = _tresc(SCIEZKA_SPLIT)
    assert "'czeka_na_krawedzie'" in tresc
    assert "'czeka_na_wykanczanie'" not in tresc


def test_bootstrap_ma_kolumny_krawedzi_zamiast_wykanczania():
    tresc = _tresc(SCIEZKA_SPLIT)
    assert "quantity_done_edges INT NOT NULL DEFAULT 0" in tresc
    assert "edges_completed_at DATETIME NULL" in tresc
    assert "quantity_done_finishing" not in tresc
    assert "finishing_completed_at" not in tresc


def test_bootstrap_zna_wszystkie_wartosci_enuma_modelu():
    from modules.production.models import ProductionProduct

    tresc = _tresc(SCIEZKA_SPLIT)
    for wartosc in ProductionProduct.current_status.type.enums:
        assert "'{}'".format(wartosc) in tresc, wartosc


def test_bootstrap_ma_kolumny_kazdego_stanowiska_z_katalogu():
    """Uogolnienie tests/test_display_monitor_service.py:29 na bootstrapowy DDL."""
    from modules.production.services.station_catalog import STATION_ORDER

    tresc = _tresc(SCIEZKA_SPLIT)
    for kod in STATION_ORDER:
        assert "quantity_done_{}".format(kod) in tresc, kod
        assert "{}_completed_at".format(kod) in tresc, kod


SCIEZKA_REWORK = KATALOG_SKRYPTOW / "add_rework_columns.sql"


def test_bootstrap_dorobki_zna_kod_krawedzi():
    tresc = _tresc(SCIEZKA_REWORK)
    assert "ENUM('formatting','edges','painting','gluing','packaging')" in tresc
    assert "'finishing'" not in tresc


def test_bootstrap_dorobki_zgadza_sie_z_modelem():
    from modules.production.models import ProductionReworkLog

    tresc = _tresc(SCIEZKA_REWORK)
    wartosci = ProductionReworkLog.rejected_at_station.type.enums
    assert set(wartosci) == {"formatting", "edges", "painting", "gluing", "packaging"}
    assert "ENUM({})".format(
        ",".join("'{}'".format(w) for w in wartosci)) in tresc


SCIEZKA_SPLIT_PY = KATALOG_SKRYPTOW / "migrate_prod_items_to_split_tables.py"


def test_insert_pisze_do_kolumn_krawedzi():
    """Lista kolumn INSERT-a to kolumny DOCELOWE (prod_products) — po rename."""
    tresc = _tresc(SCIEZKA_SPLIT_PY)
    assert ("quantity_done_gluing, quantity_done_formatting, quantity_done_edges,"
            in tresc)
    assert ("gluing_completed_at, formatting_completed_at, edges_completed_at,"
            in tresc)


def test_select_czyta_ze_starej_tabeli_pod_stara_nazwa():
    """STRAZNIK: prod_items NIE jest migrowane — aliasy i.* musza zostac przy
    'finishing', inaczej skrypt leci bledem 1054 Unknown column."""
    tresc = _tresc(SCIEZKA_SPLIT_PY)
    assert ("i.quantity_done_gluing, i.quantity_done_formatting, "
            "i.quantity_done_finishing," in tresc)
    assert ("i.gluing_completed_at, i.formatting_completed_at, "
            "i.finishing_completed_at," in tresc)
    assert "i.quantity_done_edges" not in tresc
    assert "i.edges_completed_at" not in tresc


def test_liczba_kolumn_insertu_zgadza_sie_z_liczba_kolumn_selecta():
    """WZMOCNIENIE ponad brief. Testy wyzej pilnuja NAZW, ale nie tego, czy
    obie listy sa dalej rownoliczne. Podmiana, ktora zjadlaby jedna nazwe albo
    dolozyla przecinek, daje blad 1136 dopiero na zywej bazie przy imporcie —
    nigdy w pakiecie testow."""
    tresc = _tresc(SCIEZKA_SPLIT_PY)
    naglowek = tresc.split("INSERT INTO prod_products", 1)[1]
    lista_docelowa, reszta = naglowek.split(")", 1)[0], naglowek.split(")", 1)[1]
    lista_zrodlowa = reszta.split("SELECT", 1)[1].split("FROM prod_items", 1)[0]

    docelowe = [f.strip() for f in lista_docelowa.split(",") if f.strip()]
    zrodlowe = [f.strip() for f in lista_zrodlowa.split(",") if f.strip()]
    assert len(docelowe) == len(zrodlowe), (len(docelowe), len(zrodlowe))
