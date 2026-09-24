# -*- coding: utf-8 -*-
"""Ksztalt migracji `clients` -> `leads` (samoleczaca sie wersja z 22.09.2026).

Testy jada na SQLite, ktora nie zna ani information_schema, ani PREPARE.
Sprawdzamy wiec to, co da sie sprawdzic bez MySQL-a: czy runner w ogole
wezmie plik pod uwage, na ile polecen go podzieli, czy pary PREPARE/EXECUTE/
DEALLOCATE sie zgadzaja i czy DROP TABLE leads stoi wylacznie w galezi
samoleczenia (clients istnieje + leads istnieje + leads jest pusta). Samo
WYKONANIE SQL na szesciu stanach bazy potwierdza sie osobno, na kontenerze
db (raport w .superpowers/sdd/analiza-sprzedazowa/samoleczenie-migracji-report.md).

Wzorzec: tests/test_migracja_krawedzie.py
"""

from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-09-22-clients-na-leads.sql"


def _tresc():
    return SCIEZKA.read_text(encoding="utf-8")


def _polecenia():
    return MigrationService.split_statements(_tresc())


def _bez_bialych(tekst):
    """Skleja polecenie w jedna linie — split_statements wycina komentarze,
    ale zostawia po nich znaki nowej linii w srodku polecenia."""
    return " ".join(tekst.split())


def test_plik_istnieje():
    assert SCIEZKA.exists(), "brak pliku migracji"


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAZNIK: przechodzi juz teraz (_match patrzy na nazwe, nie na plik).
    Pilnuje, zeby przyszla zmiana nazwy nie wycisza migracji po cichu."""
    service = MigrationService(db=None)
    assert service._match(SCIEZKA.name) is not None, (
        "nazwa nie pasuje do wzorca runnera — migracja zostalaby POMINIETA"
    )


def test_nie_uzywa_zmiany_separatora_polecen():
    """Runner dzieli plik wylacznie po sredniku (migration_service.py). Szukamy
    slowa w CALEJ tresci, razem z komentarzami — naglowek migracji celowo go
    nie wymawia."""
    assert "DELIMITER" not in _tresc().upper()


def test_dzieli_sie_na_22_polecenia():
    """4 odczyty istnienia tabeli (SET), jeden SET zerujacy licznik, cztery
    trojki PREPARE/EXECUTE/DEALLOCATE (licz, uzdrow, zmien, dodaj) budowane
    kazda z wlasnego SET-a budujacego SQL, plus SET liczacy brak kolumny —
    22 polecenia razem."""
    polecenia = _polecenia()
    assert len(polecenia) == 22, [_bez_bialych(p)[:60] for p in polecenia]


def test_kazdy_prepare_ma_swoje_execute_i_deallocate_pod_ta_sama_nazwa():
    """Zapomniane DEALLOCATE zostawia nazwe zajeta na calym polaczeniu; dwa
    PREPARE pod ta sama nazwa to nadpisanie, a drugi DEALLOCATE leci bledem
    1243. Migracja ma cztery przygotowania (licz/uzdrow/zmien/dodaj), kazde
    z unikalna nazwa."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    przygotowania = [p for p in polecenia if p.upper().startswith("PREPARE ")]
    wykonania = [p for p in polecenia if p.upper().startswith("EXECUTE ")]
    zwolnienia = [p for p in polecenia if p.upper().startswith("DEALLOCATE PREPARE ")]

    assert len(przygotowania) == len(wykonania) == len(zwolnienia) == 4

    nazwy = [p.split()[1] for p in przygotowania]
    assert set(nazwy) == {"licz", "uzdrow", "zmien", "dodaj"}
    assert len(set(nazwy)) == len(nazwy), nazwy

    for nazwa in nazwy:
        assert "EXECUTE {}".format(nazwa) in polecenia
        assert "DEALLOCATE PREPARE {}".format(nazwa) in polecenia


def test_liczenie_wierszy_leads_jest_warunkowe():
    """Gole 'SELECT COUNT(*) FROM leads' na bazie bez tej tabeli konczy sie
    bledem 1146 i przerywa cala migracje — zapytanie MUSI byc budowane
    warunkowo (IF na @leads_istnieje), nie wykonywane jako osobne polecenie.

    Patrzymy na polecenia PO split_statements (komentarze juz wyciete), zeby
    opis mechanizmu w komentarzu migracji (ktory tez wymawia te fraze) nie
    dawal falszywego alarmu."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    assert not any(p.upper() == "SELECT COUNT(*) FROM LEADS" for p in polecenia)

    polecenie = next(p for p in polecenia if p.strip().startswith("SET @sql_licz"))
    assert "IF(@leads_istnieje = 1" in polecenie
    assert "'SELECT COUNT(*) INTO @leads_wierszy FROM leads'" in polecenie
    assert "'SELECT 0 INTO @leads_wierszy'" in polecenie


def test_licznik_wierszy_ma_domyslna_wartosc_zero():
    """Gdy leads nie istnieje, PREPARE wykonuje 'SELECT 0 INTO @leads_wierszy'
    — ale samo SET @leads_wierszy = 0 PRZED tym jest siatka bezpieczenstwa,
    gdyby kolejnosc polecen kiedys sie rozjechala."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    assert "SET @leads_wierszy = 0" in polecenia


def test_drop_table_leads_wystepuje_tylko_w_galezi_samoleczenia():
    """Rdzen zadania: DROP TABLE leads nie moze pojawic sie nigdzie indziej
    niz w warunku wymagajacym JEDNOCZESNIE clients=1, leads=1, leads_wierszy=0.
    Gdyby DROP wyciekl do innej galezi (albo byl bezwarunkowy), samoleczenie
    zamienioby sie w cichy dropper cudzych danych."""
    polecenia = _polecenia()
    wystapienia = [p for p in polecenia if "DROP TABLE" in p.upper()]
    assert len(wystapienia) == 1, [_bez_bialych(p)[:80] for p in wystapienia]

    drop_polecenie = _bez_bialych(wystapienia[0])
    assert "DROP TABLE leads" in drop_polecenie
    assert "@clients_istnieje = 1 AND @leads_istnieje = 1 AND @leads_wierszy = 0" in drop_polecenie

    # I odwrotnie: nigdzie indziej w pliku nie ma drugiego DROP-a ani
    # bezwarunkowego zdania z DROP TABLE poza ta jedna, oslonieta linia.
    tresc_bez_tej_linii = _tresc().replace("DROP TABLE leads", "", 1)
    assert "DROP TABLE" not in tresc_bez_tej_linii.upper()


def test_samoleczenie_wymaga_wszystkich_trzech_warunkow_naraz():
    """WZMOCNIENIE ponad brief. Kazdy z trzech warunkow osobno (sam
    clients_istnieje, sam leads_istnieje, sam leads_wierszy=0) NIE wystarcza
    — usuniecie ktoregokolwiek z AND-ow zamienioby samoleczenie w operacje,
    ktora moze skasowac leads z danymi albo dzialac bez clients."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql_uzdrow")
    )
    warunek = polecenie.split("IF(", 1)[1].split(",", 1)[0]
    assert "@clients_istnieje = 1" in warunek
    assert "@leads_istnieje = 1" in warunek
    assert "@leads_wierszy = 0" in warunek
    assert warunek.count(" AND ") == 2, warunek


def test_leads_istnieje_jest_odczytywane_ponownie_po_samoleczeniu():
    """Flaga @leads_istnieje musi byc przeliczona z information_schema PO
    ewentualnym DROP-ie z kroku 3 — w przeciwnym razie krok 5/6 dzialalby na
    nieaktualnej informacji i albo nie zrobilby RENAME-u po udanym
    samoleczeniu, albo (gorzej) trafilby w galaz bledu mimo ze leads juz nie
    istnieje."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    indeks_dropa = next(i for i, p in enumerate(polecenia) if "DROP TABLE leads" in p)

    kolejne_odczyty_leads = [
        i for i, p in enumerate(polecenia)
        if p.startswith("SET @leads_istnieje = ( SELECT COUNT(*) FROM information_schema.TABLES")
    ]
    # Sa (przynajmniej) trzy odczyty @leads_istnieje w calym pliku: przed
    # samoleczeniem (krok 1), po nim (krok 4) i po ewentualnym renamie.
    assert len(kolejne_odczyty_leads) >= 3, kolejne_odczyty_leads

    odczyt_po_dropie = next(i for i in kolejne_odczyty_leads if i > indeks_dropa)
    assert odczyt_po_dropie > indeks_dropa


def test_wszystkie_galezie_decyzyjne_renamu_sa_obecne():
    """Cztery stany po kroku 4: sam RENAME, legalne pominiecie (leads juz
    istnieje), blad na tabeli-sygnale (leads ma dane, clients tez istnieje)
    i czysta instalacja bez zadnej z tabel."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql = CASE")
    )
    assert "THEN 'RENAME TABLE clients TO leads'" in polecenie
    assert "leads juz istnieje - pomijam rename" in polecenie
    assert "BLAD_MIGRACJI_leads_ma_dane_a_clients_wciaz_istnieje" in polecenie
    assert "brak clients i leads - pomijam rename" in polecenie


def test_galaz_bledu_wymaga_obu_tabel_naraz_po_kroku_4():
    """Nazwa tabeli-sygnalu ma mowic prawde: pada TYLKO gdy clients i leads
    istnieja jednoczesnie PO probie samoleczenia — czyli leads mialo dane."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql = CASE")
    )
    fragment = polecenie.split(
        "THEN 'SELECT * FROM BLAD_MIGRACJI_leads_ma_dane_a_clients_wciaz_istnieje'"
    )[0]
    ostatni_warunek = fragment.rsplit("WHEN", 1)[1]
    assert "@clients_istnieje = 1" in ostatni_warunek
    assert "@leads_istnieje = 1" in ostatni_warunek


def test_signal_uzywa_nieistniejacej_tabeli_bo_signal_nie_dziala_przez_prepare():
    """SIGNAL nie da sie przygotowac przez PREPARE, wiec blad 1146 (Table
    doesn't exist) jest wymuszany odwolaniem do tabeli o samoopisujacej sie
    nazwie — to jest ZAMIERZONY mechanizm przerwania, nie pomylka w SQL-u."""
    tresc = _tresc()
    assert "SIGNAL" not in tresc.upper()
    assert "SELECT * FROM BLAD_MIGRACJI_leads_ma_dane_a_clients_wciaz_istnieje" in tresc


def test_created_at_dodawane_tylko_gdy_leads_istnieje_i_brakuje_kolumny():
    """Krok 7 bez zmian wobec poprzedniej wersji: ALTER tylko gdy leads
    istnieje (inaczej 1146) i kolumny jeszcze nie ma."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if p.strip().startswith("SET @sql2 = CASE")
    )
    assert "WHEN @leads_istnieje = 0" in polecenie
    assert "tabela leads nie istnieje - pomijam dodanie created_at" in polecenie
    assert "WHEN @brak_kolumny" in polecenie
    assert "ALTER TABLE leads ADD COLUMN created_at DATETIME NULL" in polecenie
    assert "created_at juz istnieje - pomijam" in polecenie


def test_brak_kolumny_liczony_z_information_schema_columns():
    tresc = _tresc()
    assert "information_schema.COLUMNS" in tresc
    assert "COLUMN_NAME = 'created_at'" in tresc


def test_zaden_alter_ani_drop_nie_dotyka_tabeli_clients():
    """Migracja nigdy nie kasuje ani nie modyfikuje `clients` bezposrednio —
    `clients` znika WYLACZNIE jako efekt uboczny RENAME TABLE."""
    for polecenie in _polecenia():
        gora = _bez_bialych(polecenie).upper()
        if gora.startswith("ALTER TABLE CLIENTS") or gora.startswith("DROP TABLE CLIENTS"):
            raise AssertionError(polecenie)


def test_uzywa_wylacznie_set_prepare_execute_deallocate_i_select_do_sterowania():
    """Ograniczenie repo: bez DELIMITER-a nie da sie wgrac procedur ani
    triggerow, wiec cala logika sterujaca ma stac na SET/PREPARE/EXECUTE/
    DEALLOCATE (plus zwykle SELECT/ALTER/RENAME/DROP wewnatrz przygotowanych
    napisow)."""
    dozwolone_prefiksy = ("SET", "PREPARE", "EXECUTE", "DEALLOCATE")
    for polecenie in _polecenia():
        pierwsze_slowo = _bez_bialych(polecenie).split(" ", 1)[0].upper()
        assert pierwsze_slowo in dozwolone_prefiksy, polecenie[:60]
