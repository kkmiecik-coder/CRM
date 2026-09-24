# -*- coding: utf-8 -*-
"""Kształt migracji dodającej UNIQUE(order_id, bl_order_product_id)
do `sales_order_items`.

Testy jadą na SQLite, która nie zna ani information_schema, ani PREPARE.
Sprawdzamy więc to, co da się sprawdzić bez MySQL-a: czy runner w ogóle
weźmie plik pod uwagę, na ile poleceń go podzieli, czy pary
PREPARE/EXECUTE/DEALLOCATE się zgadzają i czy ALTER stoi WYŁĄCZNIE w gałęzi
"tabela istnieje i indeksu jeszcze nie ma". Samo WYKONANIE SQL na czystej
bazie roboczej (dwukrotnie, żeby sprawdzić idempotencję) potwierdza się
osobno, na kontenerze `db` — patrz raport-fala5-klucze.md.

Wzorzec: tests/test_migracja_clients_na_leads.py
"""

from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-09-23-unikalnosc-klucza-pozycji.sql"


def _tresc():
    return SCIEZKA.read_text(encoding="utf-8")


def _polecenia():
    return MigrationService.split_statements(_tresc())


def _bez_bialych(tekst):
    """Skleja polecenie w jedną linię — split_statements wycina komentarze,
    ale zostawia po nich znaki nowej linii w środku polecenia."""
    return " ".join(tekst.split())


def test_plik_istnieje():
    assert SCIEZKA.exists(), "brak pliku migracji"


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAŻNIK: przechodzi już teraz (_match patrzy na nazwę, nie na plik).
    Pilnuje, żeby przyszła zmiana nazwy nie wyciszała migracji po cichu."""
    service = MigrationService(db=None)
    assert service._match(SCIEZKA.name) is not None, (
        "nazwa nie pasuje do wzorca runnera — migracja zostałaby POMINIĘTA"
    )


def test_sortuje_sie_po_migracji_zakladajacej_tabele():
    """STRAŻNIK: runner wykonuje pliki w kolejności sorted() po nazwie —
    `sales_order_items` musi już istnieć, zanim ten plik dostanie szansę."""
    assert SCIEZKA.name > "2026-09-22-sales-tabele.sql"


def test_nie_uzywa_zmiany_separatora_polecen():
    """Runner dzieli plik wyłącznie po średniku. Szukamy słowa w CAŁEJ
    treści, razem z komentarzami — nagłówek migracji celowo go nie wymawia."""
    assert "DELIMITER" not in _tresc().upper()


def test_dzieli_sie_na_6_polecen():
    """3 SET-y (tabela_istnieje, indeks_istnieje, sql = CASE) + trójka
    PREPARE/EXECUTE/DEALLOCATE wykonująca ALTER = 3 + 3 = 6.

    Oba odczyty (tabela, indeks) są ZWYKŁYMI SET-ami, bez PREPARE: pytają
    information_schema, nie `sales_order_items` samą, więc błąd 1146 im nie
    grozi nawet na bazie bez tej tabeli (patrz komentarz w migracji)."""
    polecenia = _polecenia()
    assert len(polecenia) == 6, [_bez_bialych(p)[:60] for p in polecenia]


def test_odczyty_tabeli_i_indeksu_nie_uzywaja_prepare():
    """WZMOCNIENIE ponad brief. Gdyby ktoś kiedyś owinął te odczyty w PREPARE
    'na wszelki wypadek', dodałby złożoność bez żadnej korzyści — to jedyny
    powód, dla którego ta migracja jest prostsza niż clients-na-leads."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    odczyt_tabeli = next(p for p in polecenia if p.startswith("SET @tabela_istnieje"))
    odczyt_indeksu = next(p for p in polecenia if p.startswith("SET @indeks_istnieje"))
    assert "information_schema.TABLES" in odczyt_tabeli
    assert "information_schema.STATISTICS" in odczyt_indeksu
    assert "INDEX_NAME = 'uq_soi_order_bl_product'" in odczyt_indeksu
    assert "TABLE_NAME = 'sales_order_items'" in odczyt_tabeli
    assert "TABLE_NAME = 'sales_order_items'" in odczyt_indeksu


def test_kazdy_prepare_ma_swoje_execute_i_deallocate_pod_ta_sama_nazwa():
    """Zapomniane DEALLOCATE zostawia nazwę zajętą na całym połączeniu; dwa
    PREPARE pod tą samą nazwą to nadpisanie, a drugi DEALLOCATE leci błędem
    1243. Migracja ma JEDNO przygotowanie (dodaj_unique) — tylko ALTER
    wymaga dynamicznego SQL-a, odczyty idą zwykłym SET-em (patrz wyżej)."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    przygotowania = [p for p in polecenia if p.upper().startswith("PREPARE ")]
    wykonania = [p for p in polecenia if p.upper().startswith("EXECUTE ")]
    zwolnienia = [p for p in polecenia if p.upper().startswith("DEALLOCATE PREPARE ")]

    assert len(przygotowania) == len(wykonania) == len(zwolnienia) == 1

    nazwa = przygotowania[0].split()[1]
    assert nazwa == "dodaj_unique"
    assert "EXECUTE {}".format(nazwa) in polecenia
    assert "DEALLOCATE PREPARE {}".format(nazwa) in polecenia


def test_alter_wystepuje_wylacznie_w_galezi_tabela_istnieje_i_brak_indeksu():
    """Rdzeń zadania: ALTER TABLE nie może pojawić się nigdzie indziej niż
    w gałęzi CASE wymagającej JEDNOCZEŚNIE @tabela_istnieje = 1 (niejawnie,
    przez brak wcześniejszego WHEN dla tabeli) i @indeks_istnieje = 0.

    Patrzymy na POLECENIA po split_statements (komentarze już wycięte) —
    nagłówek migracji tłumaczy mechanizm słowami "ALTER TABLE" po ludzku
    kilka razy, więc surowy tekst pliku dałby fałszywy alarm."""
    polecenia = _polecenia()
    wystapienia = [p for p in polecenia if "ALTER TABLE" in p.upper()]
    assert len(wystapienia) == 1, [_bez_bialych(p)[:80] for p in wystapienia]

    alter_polecenie = _bez_bialych(wystapienia[0])
    assert alter_polecenie.strip().startswith("SET @sql = CASE")
    assert "ALTER TABLE sales_order_items ADD UNIQUE KEY" in alter_polecenie
    assert "uq_soi_order_bl_product (order_id, bl_order_product_id)" in alter_polecenie

    # ALTER stoi wyłącznie w gałęzi ELSE, PO obu warunkach WHEN — nie jest
    # wartością żadnej z dwóch gałęzi "pomijam".
    galaz_alter = alter_polecenie.rsplit("ELSE", 1)[1]
    assert "ALTER TABLE" in galaz_alter.upper()
    galaz_when = alter_polecenie.split("ELSE", 1)[0]
    assert "ALTER TABLE" not in galaz_when.upper()


def test_wszystkie_galezie_decyzyjne_sa_obecne():
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql = CASE")
    )
    assert "tabela sales_order_items nie istnieje" in polecenie
    assert "ograniczenie uq_soi_order_bl_product juz istnieje" in polecenie
    assert "ALTER TABLE sales_order_items ADD UNIQUE KEY" in polecenie


def test_galaz_brak_tabeli_stoi_przed_galezia_indeksu_w_case():
    """WZMOCNIENIE ponad brief. CASE ocenia WHEN po kolei — gdyby warunek
    na indeks stał pierwszy, nie zmieniłby wyniku semantycznie (indeks nie
    może istnieć bez tabeli), ale kolejność w pliku ma odzwierciedlać
    kolejność rozumowania z komentarza (najpierw tabela, potem indeks)."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql = CASE")
    )
    indeks_tabeli = polecenie.index("@tabela_istnieje = 0")
    indeks_indeksu = polecenie.index("@indeks_istnieje > 0")
    assert indeks_tabeli < indeks_indeksu


def test_uzywa_wylacznie_set_prepare_execute_deallocate_do_sterowania():
    """Ograniczenie repo: bez DELIMITER-a nie da się wgrać procedur ani
    triggerów, więc cała logika sterująca ma stać na SET/PREPARE/EXECUTE/
    DEALLOCATE (plus zwykłe SELECT/ALTER wewnątrz przygotowanych napisów)."""
    dozwolone_prefiksy = ("SET", "PREPARE", "EXECUTE", "DEALLOCATE")
    for polecenie in _polecenia():
        pierwsze_slowo = _bez_bialych(polecenie).split(" ", 1)[0].upper()
        assert pierwsze_slowo in dozwolone_prefiksy, polecenie[:60]


def test_zaden_drop_ani_truncate():
    """Ograniczenie schematu jest DODAWANE, nigdy niczego nie kasuje."""
    gora = _tresc().upper()
    assert "DROP TABLE" not in gora
    assert "DROP COLUMN" not in gora
    assert "TRUNCATE" not in gora


def test_klucz_zgadza_sie_z_kolumnami_modelu():
    """UNIQUE musi objąć DOKŁADNIE te same nazwy kolumn, które model
    SQLAlchemy naprawdę ma — inaczej migracja i ORM rozjadą się cicho."""
    from modules.reports.models_sales import SalesOrderItem

    assert hasattr(SalesOrderItem, "order_id")
    assert hasattr(SalesOrderItem, "bl_order_product_id")

    alter = next(_bez_bialych(p) for p in _polecenia() if "ALTER TABLE" in p.upper())
    assert "(order_id, bl_order_product_id)" in alter
