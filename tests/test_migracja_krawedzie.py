# -*- coding: utf-8 -*-
"""Ksztalt migracji dzielacej Wykanczanie na Krawedzie i Lakiernie.

Testy jada na SQLite, ktora nie zna ani ENUM-a MySQL-a, ani information_schema,
ani PREPARE. Sprawdzamy wiec to, co da sie sprawdzic bez MySQL-a: czy runner
w ogole wezmie plik pod uwage, na ile polecen go podzieli i czy kolejnosc sekcji
jest ta, ktora zaklada plan. Samo WYKONANIE SQL potwierdza sie osobno, na
kontenerze db (zadania 13 i 14).

Plik nie zaklada tabeli audytu produktu (ProductionProductEvent) i nie tworzy
zadnego modelu — czyta wylacznie tresc plikow z dysku. Powod: listener audytu
w models.py trzyma globalny cache dostepnosci tabeli, wiec zalozenie jej w
jednym pliku testowym sypie pozostale (patrz ograniczenia globalne planu).

Wzorzec: tests/test_migracja_shape_rotation.py
"""

import re
from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-09-15-krawedzie-podzial-wykanczania.sql"


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


def test_sortuje_sie_po_migracji_trakowni():
    """STRAZNIK: runner wykonuje pliki w kolejnosci sorted() po nazwie."""
    assert SCIEZKA.name > "2026-09-12-sawmill-srednica.sql"


def test_nie_uzywa_zmiany_separatora_polecen():
    """Runner dzieli plik wylacznie po sredniku (migration_service.py:173-174).
    Szukamy slowa w CALEJ tresci, razem z komentarzami — dlatego naglowek
    migracji celowo go nie wymawia."""
    assert "DELIMITER" not in _tresc().upper()


def test_tworzy_tabele_kopii_idempotentnie():
    tresc = _tresc()
    assert "CREATE TABLE IF NOT EXISTS prod_migracja_krawedzie_kopia" in tresc
    assert "PRIMARY KEY (tabela, rekord_id)" in tresc


def test_kopia_obejmuje_cztery_tabele():
    """Bez kopii przepisanie historii na 'painting' jest nieodwracalne."""
    wstawki = [p for p in _polecenia() if p.upper().startswith("INSERT")]
    assert len(wstawki) == 4, [p[:60] for p in wstawki]
    for polecenie in wstawki:
        assert polecenie.upper().startswith("INSERT IGNORE"), polecenie[:60]
    sklejone = " ".join(_bez_bialych(p) for p in wstawki)
    for tabela in ("prod_products", "prod_station_events",
                   "prod_devices", "prod_worker_sessions"):
        assert "'{}'".format(tabela) in sklejone, tabela


def test_kopia_zapisuje_tylko_wiersze_do_przeniesienia():
    """WZMOCNIENIE ponad brief. Kopia bez WHERE zapisalaby CALE tabele —
    2687 wierszy historii zamienia sie w 25 829, a bilans z zapytania B5
    przestaje cokolwiek dowodzic. Kazda wstawka ma filtrowac po STAREJ
    wartosci."""
    wstawki = [_bez_bialych(p) for p in _polecenia()
               if p.upper().startswith("INSERT")]
    for polecenie in wstawki:
        gora = polecenie.upper()
        assert " WHERE " in gora, polecenie[:80]
        warunek = gora.split(" WHERE ", 1)[1]
        assert "FINISHING" in warunek or "WYKANCZANIE" in warunek, polecenie[:80]


def test_kopia_powstaje_przed_pierwszym_przepisaniem():
    """WZMOCNIENIE ponad brief. Sekcja 0 wykonana PO sekcji 1 zapisalaby pusta
    kopie — bez bledu, bez ostrzezenia — i rollback nie mialby z czego cofac.
    Zaden inny test nie pilnuje, ze kopia stoi na poczatku pliku."""
    polecenia = [_bez_bialych(p).upper() for p in _polecenia()]
    ostatnia_wstawka = max(i for i, p in enumerate(polecenia)
                           if p.startswith("INSERT"))
    pierwsza_zmiana = min(i for i, p in enumerate(polecenia)
                          if p.startswith("UPDATE") or p.startswith("ALTER"))
    assert ostatnia_wstawka < pierwsza_zmiana, (ostatnia_wstawka, pierwsza_zmiana)


def test_alter_dodajacy_czeka_na_krawedzie_stoi_przed_pierwszym_update():
    """Stary kod chodzi jeszcze w gunicornie — nowa wartosc musi byc w enumie
    ZANIM pierwszy UPDATE sprobuje ja zapisac."""
    polecenia = _polecenia()
    indeks_alter = next(
        i for i, p in enumerate(polecenia)
        if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_PRODUCTS")
        and "czeka_na_krawedzie" in p and "czeka_na_wykanczanie" in p
    )
    indeks_update = next(
        i for i, p in enumerate(polecenia)
        if _bez_bialych(p).upper().startswith("UPDATE PROD_PRODUCTS")
    )
    assert indeks_alter < indeks_update


def test_kolejka_dzieli_sie_na_lakiernie_i_krawedzie():
    """Najpierw przypadek waski (bez krawedzi + olej/lakier), potem catch-all.

    SPROSTOWANIE WOBEC BRIEFU (zadanie 2 zakladalo tu dwa UPDATE-y): sekcja 5
    powtarza te sama pare jako sweep wyscigu, wiec w gotowym pliku jest ich
    cztery. Sprawdzamy pierwsza pare — tej z sekcji 5 pilnuje
    test_sweep_wyscigu_powtarza_regule_przed_zwezeniem_enuma.

    Sekcja sweepu byla pierwotnie sekcja 6 (po renameie kolumn). Recenzja
    2026-09-15 przestawila ja PRZED rename (dzis sekcja 5) — zwezajacy ALTER
    enuma jest jednym z kilku polecen, ktore moga pasc z przyczyn
    niezwiazanych z trescia (1205/1206), i jak one wszystkie stoi teraz przed
    renameem. Jego porazka PRZED renameem zostawia aplikacje dzialajaca na
    schemacie, ktory stary kod dalej czyta; PO renameie (dawna kolejnosc)
    zostawialaby przemianowane kolumny pod starym kodem gunicorna.
    Patrz test_zwezajacy_alter_enuma_stoi_przed_pierwszym_renamem_kolumny."""
    updaty = [_bez_bialych(p) for p in _polecenia()
              if _bez_bialych(p).upper().startswith("UPDATE PROD_PRODUCTS")]
    assert len(updaty) == 4, updaty

    wasky = updaty[0]
    assert "SET current_status = 'czeka_na_lakiernie'" in wasky
    assert "parsed_edge_processing = 0" in wasky
    assert "parsed_finish_type IN ('olejowane','lakierowane')" in wasky

    catch_all = updaty[1]
    assert "SET current_status = 'czeka_na_krawedzie'" in catch_all
    assert "parsed_edge_processing" not in catch_all


def test_enum_migracji_zgadza_sie_z_enumem_modelu():
    """MODIFY COLUMN musi objac wszystko, co zna models.py, inaczej ORM zapisze
    wartosc, ktorej baza nie zna (blad 1265 pod STRICT_TRANS_TABLES)."""
    from modules.production.models import ProductionProduct

    wartosci_modelu = set(ProductionProduct.current_status.type.enums)
    assert "czeka_na_krawedzie" in wartosci_modelu
    assert "czeka_na_wykanczanie" not in wartosci_modelu

    rozszerzajacy = next(
        _bez_bialych(p) for p in _polecenia()
        if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_PRODUCTS")
        and "czeka_na_wykanczanie" in p
    )
    for wartosc in wartosci_modelu:
        assert "'{}'".format(wartosc) in rozszerzajacy, wartosc


def test_regula_eventow_joinuje_prod_products():
    """Regula trojdzielna liczy sie z BIEZACYCH pol produktu, nie zgaduje."""
    updaty = [_bez_bialych(p) for p in _polecenia()
              if _bez_bialych(p).upper().startswith("UPDATE PROD_STATION_EVENTS")]
    assert len(updaty) == 2, updaty

    wasky = updaty[0]
    assert "JOIN prod_products p ON p.id = e.production_item_id" in wasky
    assert "SET e.station_code = 'painting'" in wasky
    assert "e.station_code = 'finishing'" in wasky
    assert "p.parsed_edge_processing = 0" in wasky
    assert "p.parsed_finish_type IN ('olejowane','lakierowane')" in wasky


def test_catch_all_eventow_stoi_po_regule_waskiej():
    """Odwrotna kolejnosc przepisalaby wszystko na 'edges' i zgubila Lakiernie."""
    updaty = [_bez_bialych(p) for p in _polecenia()
              if _bez_bialych(p).upper().startswith("UPDATE PROD_STATION_EVENTS")]
    catch_all = updaty[1]
    assert "SET station_code = 'edges'" in catch_all
    assert "WHERE station_code = 'finishing'" in catch_all
    assert "parsed_finish_type" not in catch_all


def test_regula_eventow_jest_ta_sama_co_regula_kolejki():
    """WZMOCNIENIE ponad brief. Plan wymaga JEDNEJ reguly dla kolejki i dla
    historii. Gdyby ktos poprawil warunek tylko w jednym miejscu (np. dodal
    'surowe' do listy wykonczen w sekcji 1), oba testy szczegolowe dalej by
    przechodzily, a dane rozjechalyby sie miedzy kolejka a historia."""
    def _warunek(prefiks):
        polecenie = next(_bez_bialych(p) for p in _polecenia()
                         if _bez_bialych(p).upper().startswith(prefiks))
        return polecenie.upper().split(" WHERE ", 1)[1]

    warunek_kolejki = _warunek("UPDATE PROD_PRODUCTS")
    warunek_historii = _warunek("UPDATE PROD_STATION_EVENTS")
    for fragment in ("PARSED_EDGE_PROCESSING = 0",
                     "PARSED_FINISH_TYPE IN ('OLEJOWANE','LAKIEROWANE')"):
        assert fragment in warunek_kolejki, fragment
        assert fragment in warunek_historii, fragment


def test_przepisuje_urzadzenia_sesje_i_wydruki():
    """prod_worker_sessions musi isc TA SAMA migracja co eventy — inaczej
    badge 'Trwa nauka' wraca i wyglada jak awaria (ryzyko R20)."""
    sklejone = " ".join(_bez_bialych(p) for p in _polecenia())
    assert ("UPDATE prod_devices SET station_code = 'edges' "
            "WHERE station_code = 'finishing'") in sklejone
    assert ("UPDATE prod_worker_sessions SET station_code = 'edges' "
            "WHERE station_code = 'finishing'") in sklejone
    assert ("UPDATE prod_print_queue SET station_code = 'edges' "
            "WHERE station_code = 'finishing'") in sklejone


def test_csv_uprawnien_pracownika_ma_przecinki_wartownikow():
    """Bez CONCAT(',', ..., ',') REPLACE trafilby w podciag innego kodu."""
    polecenie = next(_bez_bialych(p) for p in _polecenia()
                     if _bez_bialych(p).upper().startswith("UPDATE PROD_WORKERS "))
    assert "CONCAT(',', allowed_stations, ',')" in polecenie
    assert "',finishing,', ',edges,'" in polecenie
    assert "TRIM(BOTH ',' FROM" in polecenie
    assert "WHERE allowed_stations LIKE '%finishing%'" in polecenie


def test_obie_konwencje_kluczy_prod_config_sa_obsluzone():
    """config_service.py:98 sklada klucz z SUFIKSEM ({KEY}_FINISHING), ale
    w prod_config zyje tez konwencja z nazwa stanowiska w SRODKU
    (STATION_CUTTING_PRIORITY_SORT, config_api.py:514-515). Pominiecie
    ktorejkolwiek = stanowisko po cichu spada na wartosc globalna, bez bledu
    i bez logu."""
    sklejone = " ".join(_bez_bialych(p) for p in _polecenia())
    assert "RIGHT(config_key, 10) = '_FINISHING'" in sklejone
    assert "'_EDGES'" in sklejone
    assert "LEFT(config_key, 18) = 'STATION_FINISHING_'" in sklejone
    assert "'STATION_EDGES_'" in sklejone


def test_dlugosci_w_arytmetyce_kluczy_prod_config_sa_poprawne():
    """WZMOCNIENIE ponad brief. Testy powyzej sprawdzaja, ze liczby 10 i 18
    w ogole padaja, ale nie to, czy sa PRAWDZIWE. Zle policzona dlugosc nie
    wywala niczego — po cichu produkuje klucz 'STATION_ALLOWED_IPS_ED' albo
    'STATION_EDGES_INISHING_PRIORITY_SORT'."""
    assert len("_FINISHING") == 10
    assert len("STATION_FINISHING_") == 18
    assert len("_EDGES") == 6
    assert len("STATION_EDGES_") == 14

    sklejone = " ".join(_bez_bialych(p) for p in _polecenia())
    # SUBSTRING liczy od 1, wiec przy sufiksie ucinamy CHAR_LENGTH - 10,
    # a przy prefiksie zaczynamy od znaku 19 (18 + 1).
    assert ("SUBSTRING(config_key, 1, CHAR_LENGTH(config_key) - 10), '_EDGES'"
            in sklejone)
    assert "CONCAT('STATION_EDGES_', SUBSTRING(config_key, 19))" in sklejone


def test_csv_drukarki_etykiet_jest_przepisany():
    """LABEL_PRINTER_ALLOWED_STATIONS to wartosc runtime — grep po repo jej
    nie znajdzie, a po rename wydruk leci 403 StationNotAllowed."""
    polecenie = next(
        _bez_bialych(p) for p in _polecenia()
        if "LABEL_PRINTER_ALLOWED_STATIONS" in p
    )
    assert "CONCAT(',', config_value, ',')" in polecenie
    assert "',finishing,', ',edges,'" in polecenie
    assert "LIKE '%,finishing,%'" in polecenie


def test_rozszerza_i_zweza_enum_stanowiska_dorobki():
    """Ten sam schemat co dla statusu: rozszerz, przepisz, zwez. Zwezenie przy
    istniejacej niepasujacej wartosci konczy sie bledem 1265 i PRZERYWA deploy."""
    altery = [_bez_bialych(p) for p in _polecenia()
              if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_REWORK_LOG")]
    assert len(altery) == 2, altery

    assert "ENUM('formatting','edges','finishing','painting')" in altery[0]
    assert "ENUM('formatting','edges','painting')" in altery[1]
    assert "'finishing'" not in altery[1]


def test_przepisanie_dorobki_stoi_miedzy_alterami():
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    indeksy_alter = [i for i, p in enumerate(polecenia)
                     if p.upper().startswith("ALTER TABLE PROD_REWORK_LOG")]
    indeks_update = next(i for i, p in enumerate(polecenia)
                         if p.upper().startswith("UPDATE PROD_REWORK_LOG"))
    assert indeksy_alter[0] < indeks_update < indeksy_alter[1]
    assert ("SET rejected_at_station = 'edges' "
            "WHERE rejected_at_station = 'finishing'") in polecenia[indeks_update]


def test_enum_dorobki_zgadza_sie_z_modelem():
    from modules.production.models import ProductionReworkLog

    wartosci = set(ProductionReworkLog.rejected_at_station.type.enums)
    assert wartosci == {"formatting", "edges", "painting"}

    zwezajacy = [_bez_bialych(p) for p in _polecenia()
                 if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_REWORK_LOG")][1]
    for wartosc in wartosci:
        assert "'{}'".format(wartosc) in zwezajacy, wartosc


def test_zmienia_nazwy_obu_kolumn_produktu():
    """RENAME COLUMN (nie CHANGE) zachowuje typ, NOT NULL, DEFAULT i komentarz.

    Po recenzji 2026-09-15 oba renamey sa KLAUZULAMI jednego ALTER-a, wiec
    w tresci pliku stoja bez prefiksu — dokleja go CONCAT przy skladaniu
    polecenia. Prefiks sprawdzamy osobno, zeby zmiana nazwy tabeli nie
    przeszla niezauwazona."""
    tresc = _tresc()
    assert ("RENAME COLUMN quantity_done_finishing "
            "TO quantity_done_edges") in tresc
    assert ("RENAME COLUMN finishing_completed_at "
            "TO edges_completed_at") in tresc
    assert "CONCAT('ALTER TABLE prod_products ', @klauzule_renamu)" in tresc


def test_renamey_sa_osloniete_information_schema():
    """Runner puszcza katalog przy KAZDYM deployu — drugi przebieg nie moze pasc."""
    tresc = _tresc()
    assert tresc.count("information_schema.COLUMNS") == 2
    assert "COLUMN_NAME = 'quantity_done_finishing'" in tresc
    assert "COLUMN_NAME = 'finishing_completed_at'" in tresc
    assert tresc.count("TABLE_SCHEMA = DATABASE()") == 2


def test_kazdy_prepare_ma_swoje_deallocate():
    """Zapomniane DEALLOCATE zostawia nazwe zajeta na calym polaczeniu.

    Po recenzji 2026-09-15 para jest JEDNA, nie dwie: oba renamey kolumn ida
    jednym ALTER-em, wiec jedno PREPARE, jedno EXECUTE i jedno DEALLOCATE.
    Liczba jest czescia asercji — drugie PREPARE w tym pliku znaczyloby, ze
    ktos rozdzielil renamey z powrotem na dwa polecenia."""
    polecenia = [_bez_bialych(p).upper() for p in _polecenia()]
    przygotowania = [p for p in polecenia if p.startswith("PREPARE ")]
    wykonania = [p for p in polecenia if p.startswith("EXECUTE ")]
    zwolnienia = [p for p in polecenia if p.startswith("DEALLOCATE PREPARE ")]
    assert len(przygotowania) == len(wykonania) == len(zwolnienia) == 1


def test_kazdy_rename_uzywa_wlasnej_nazwy_polecenia():
    """WZMOCNIENIE ponad brief. Po recenzji 2026-09-15 PREPARE jest w pliku
    JEDEN, wiec ten test stoi na warcie na przyszlosc: dwa PREPARE pod TA SAMA
    nazwa to nie blad skladni — drugie nadpisuje pierwsze, a DEALLOCATE nr 2
    leci bledem 1243 i przerywa plik na sekcji 6. Liczenie samych wystapien
    (test wyzej) tego nie lapie."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    nazwy = [p.split()[1] for p in polecenia if p.upper().startswith("PREPARE ")]
    assert len(set(nazwy)) == len(nazwy), nazwy
    for nazwa in nazwy:
        assert "EXECUTE {}".format(nazwa) in polecenia
        assert "DEALLOCATE PREPARE {}".format(nazwa) in polecenia


def test_rename_dokancza_polowiczny_stan_kolumn():
    """Przerwany POPRZEDNI przebieg zostawia jedna z dwoch kolumn juz
    przemianowana, druga nietknieta. Taki stan powstaje, gdy migracje ubije
    cos niezaleznego od jej tresci (zerwane polaczenie, restart mysqld, ubity
    deploy.sh). Nastepny przebieg runnera musi wtedy dokonczyc sama brakujaca
    kolumne: nie pasc na tej juz przemianowanej (1054 w ALTER-ze przerywa plik
    i deploy) i nie pominac tej nietknietej (schemat zostaje rozjechany,
    a wpis w schema_migrations moglby ta migracje wyciszyc na zawsze).

    Test jest statyczny — patrzy na tresc pliku, bo SQLite nie zna ani
    information_schema, ani PREPARE."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]

    indeks_ilosci = next(i for i, p in enumerate(polecenia)
                         if p.startswith("SET @kolumna_ilosci"))
    indeks_daty = next(i for i, p in enumerate(polecenia)
                       if p.startswith("SET @kolumna_daty"))
    indeks_klauzul = next(i for i, p in enumerate(polecenia)
                          if "CONCAT_WS" in p.upper())

    # OBA liczniki musza stac PRZED zbudowaniem klauzul. Licznik policzony po
    # wykonaniu renamu patrzylby na schemat, ktorego to polecenie wlasnie
    # dotknelo — po scaleniu obu renameow w jeden ALTER byloby to cichym bledem.
    assert indeks_ilosci < indeks_klauzul, (indeks_ilosci, indeks_klauzul)
    assert indeks_daty < indeks_klauzul, (indeks_daty, indeks_klauzul)

    # Kazda kolumna ma WLASNY warunek, na WLASNYM liczniku: cztery stany
    # schematu (obie stare, kazda z dwoch osobno, obie nowe) sa obsluzone,
    # bo CONCAT_WS pomija NULL-e.
    klauzule = polecenia[indeks_klauzul]
    assert ("IF(@kolumna_ilosci > 0, 'RENAME COLUMN quantity_done_finishing "
            "TO quantity_done_edges', NULL)") in klauzule, klauzule
    assert ("IF(@kolumna_daty > 0, 'RENAME COLUMN finishing_completed_at "
            "TO edges_completed_at', NULL)") in klauzule, klauzule

    # Puste klauzule (drugi przebieg, obie kolumny juz nowe) nie moga zlozyc
    # sie w goly 'ALTER TABLE prod_products'.
    skladanie = polecenia[indeks_klauzul + 1]
    assert skladanie.startswith("SET @sql_renamu"), skladanie
    assert "'SELECT 1'" in skladanie, skladanie


def test_nazwy_kolumn_zgadzaja_sie_z_modelem():
    from modules.production.models import ProductionProduct

    assert hasattr(ProductionProduct, "quantity_done_edges")
    assert hasattr(ProductionProduct, "edges_completed_at")
    assert not hasattr(ProductionProduct, "quantity_done_finishing")
    assert not hasattr(ProductionProduct, "finishing_completed_at")

    tresc = _tresc()
    assert "TO quantity_done_edges" in tresc
    assert "TO edges_completed_at" in tresc


def test_sweep_wyscigu_powtarza_regule_przed_zwezeniem_enuma():
    """Stary kod chodzi w gunicornie do restartu i mogl dopisac status miedzy
    sekcja 1 a tym miejscem. Bez sweepu ALTER leci bledem 1265."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    updaty = [i for i, p in enumerate(polecenia)
              if p.upper().startswith("UPDATE PROD_PRODUCTS")]
    assert len(updaty) == 4, updaty

    indeks_zwezajacego = max(
        i for i, p in enumerate(polecenia)
        if p.upper().startswith("ALTER TABLE PROD_PRODUCTS")
    )
    assert updaty[2] < indeks_zwezajacego
    assert updaty[3] < indeks_zwezajacego
    assert "'czeka_na_lakiernie'" in polecenia[updaty[2]]
    assert "'czeka_na_krawedzie'" in polecenia[updaty[3]]


def test_zwezajacy_alter_enuma_stoi_przed_pierwszym_renamem_kolumny():
    """STRAZNIK NOWEJ KOLEJNOSCI (recenzja 2026-09-15: przestawienie sekcji 5 i 6).

    Zwezajacy ALTER enuma current_status wymusza ALGORITHM=COPY i moze pasc
    z przyczyn NIEZWIAZANYCH z trescia (1205/1206 — metadata lock na zywej
    tabeli). Nie jest w tym pliku jedyny — to samo dotyczy UPDATE-u
    przepisujacego historie stanowiskowa, obu ALTER-ow enuma prod_rework_log
    i samego RENAME COLUMN — ale jest ostatnim takim poleceniem przed sekcja
    renameow i to jego pozycje da sie sprawdzic relacja indeksow.

    Gdyby stal PO renameie kolumn (dawna kolejnosc), jego porazka zostawialaby
    schemat juz przemianowany pod starym kodem gunicorna: quantity_done_finishing
    juz by nie istnialo, wiec kazde zapytanie o prod_products lecialoby 1054,
    a caly modul produkcji byl martwy do recznego rollbacku. Stojac PRZED
    renameem, ta sama porazka przerywa caly plik migracji, ZANIM SCHEMAT
    PRZESTANIE BYC CZYTELNY DLA STAREGO KODU — nie "zanim cokolwiek sie
    zmieni": enum current_status jest w tym momencie juz zwezony, a enum
    prod_rework_log przebudowany. Zadnej kolumny nie ubylo, wiec stary kod
    ODPYTUJE ten schemat bez bledu — ale to NIE znaczy, ze modul dziala
    normalnie: current_status ma juz wiersze na 'czeka_na_krawedzie', ktorej
    stary Enum(...) w models.py nie zna, wiec kazdy ODCZYT takiego wiersza
    wywraca sie LookupError-em (SQLAlchemy 1.4.54, Enum._object_value_for_elem
    w result_processor). To awaria DANYCH, nie schematu — mniejsza niz
    porazka PO renameie (tam kazde zapytanie o prod_products leci 1054), ale
    nie zerowa."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]

    indeks_zwezajacego = next(
        i for i, p in enumerate(polecenia)
        if p.upper().startswith("ALTER TABLE PROD_PRODUCTS MODIFY")
        and "'CZEKA_NA_KRAWEDZIE'" in p.upper()
        and "'CZEKA_NA_WYKANCZANIE'" not in p.upper()
    )
    indeks_pierwszego_renamu = next(
        i for i, p in enumerate(polecenia)
        if "RENAME COLUMN" in p.upper()
    )
    assert indeks_zwezajacego < indeks_pierwszego_renamu


def test_ostatni_alter_nie_zawiera_czeka_na_wykanczanie():
    altery = [_bez_bialych(p) for p in _polecenia()
              if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_PRODUCTS")]
    assert len(altery) == 2, altery
    assert "'czeka_na_wykanczanie'" in altery[0]
    assert "'czeka_na_wykanczanie'" not in altery[1]
    assert "'czeka_na_krawedzie'" in altery[1]


def test_zwezajacy_alter_zgadza_sie_z_enumem_modelu():
    """WZMOCNIENIE ponad brief. Test wyzej pilnuje tylko dwoch wartosci.
    Zgubiona przy przepisywaniu listy wartosc (np. 'wstrzymane') przeszlaby
    przez oba testy, a w bazie skasowalaby status kilkudziesieciu pozycji —
    MySQL zamienia niepasujaca wartosc enuma na pusty string."""
    from modules.production.models import ProductionProduct

    zwezajacy = [_bez_bialych(p) for p in _polecenia()
                 if _bez_bialych(p).upper().startswith("ALTER TABLE PROD_PRODUCTS")][1]
    lista = zwezajacy.split("ENUM(", 1)[1].split(")", 1)[0]
    wartosci_migracji = set(re.findall(r"'([^']+)'", lista))
    # Dokladna rownosc, nie zawieranie: brakujaca wartosc kasuje status
    # pozycjom (MySQL wstawia pusty string), nadmiarowa zostawia martwy kod.
    assert wartosci_migracji == set(ProductionProduct.current_status.type.enums)


def test_dzieli_sie_na_30_polecen():
    """32 z planu migracji w specyfikacji + jedno na druga konwencje kluczy
    prod_config (STATION_FINISHING_* z nazwa stanowiska w srodku) = 33,
    minus trzy zdjete przez recenzje 2026-09-15: scalenie dwoch blokow
    SET/PREPARE/EXECUTE/DEALLOCATE renamu kolumn w jeden atomiczny ALTER
    zabiera jedno SET, jedno PREPARE, jedno EXECUTE i jedno DEALLOCATE,
    a doklada jedno SET budujace klauzule."""
    polecenia = _polecenia()
    assert len(polecenia) == 30, [_bez_bialych(p)[:45] for p in polecenia]


def test_kazdy_update_ma_warunek_na_stara_wartosc():
    """Runner puszcza katalog przy KAZDYM deployu. UPDATE bez warunku na stara
    wartosc przy drugim przebiegu ruszylby wiersze, ktorych nie powinien."""
    for polecenie in _polecenia():
        jedna_linia = _bez_bialych(polecenie)
        if not jedna_linia.upper().startswith("UPDATE"):
            continue
        assert " WHERE " in jedna_linia.upper(), jedna_linia[:60]
        warunek = jedna_linia.upper().split(" WHERE ", 1)[1]
        assert "FINISHING" in warunek or "WYKANCZANIE" in warunek, jedna_linia[:80]


def test_tworzenie_i_wstawki_sa_idempotentne():
    for polecenie in _polecenia():
        gora = _bez_bialych(polecenie).upper()
        if gora.startswith("CREATE TABLE"):
            assert "IF NOT EXISTS" in gora, polecenie[:60]
        if gora.startswith("INSERT"):
            assert gora.startswith("INSERT IGNORE"), polecenie[:60]


def test_zaden_alter_nie_kasuje_kolumny_ani_tabeli():
    """Migracja ma byc odwracalna skryptem rollbacku — zadnego DROP-a."""
    gora = _tresc().upper()
    assert "DROP TABLE" not in gora
    assert "DROP COLUMN" not in gora
    assert "TRUNCATE" not in gora


KATALOG_SKRYPTOW = Path(__file__).resolve().parents[1] / "scripts"
SCIEZKA_ROLLBACK = KATALOG_SKRYPTOW / "rollback-2026-09-15-krawedzie.sql"


def _tresc_rollbacku():
    return SCIEZKA_ROLLBACK.read_text(encoding="utf-8")


def test_rollback_istnieje_i_lezy_poza_katalogiem_migracji():
    """W migrations/ nazwa RRRR-MM-DD-*.sql zostalaby rozpoznana przez runner
    i wykonana przy najblizszym deployu. Precedens: scripts/rollback_rework_columns.sql."""
    assert SCIEZKA_ROLLBACK.exists()
    assert not (KATALOG_MIGRACJI / SCIEZKA_ROLLBACK.name).exists()


def test_runner_nie_rozpoznalby_nazwy_rollbacku():
    """STRAZNIK: prefiks 'rollback-' lamie oba wzorce _match. Przechodzi juz teraz."""
    service = MigrationService(db=None)
    assert service._match(SCIEZKA_ROLLBACK.name) is None


def test_rollback_cofa_obie_nazwy_kolumn_pod_oslona():
    """Po scaleniu (ta sama recenzja co w migracji) oba renamey sa KLAUZULAMI
    jednego ALTER-a, wiec w tresci pliku stoja bez prefiksu 'ALTER TABLE
    prod_products' -- dokleja go CONCAT przy skladaniu polecenia. Prefiks
    sprawdzamy osobno, zeby zmiana nazwy tabeli nie przeszla niezauwazona."""
    tresc = _tresc_rollbacku()
    assert ("RENAME COLUMN quantity_done_edges "
            "TO quantity_done_finishing") in tresc
    assert ("RENAME COLUMN edges_completed_at "
            "TO finishing_completed_at") in tresc
    assert "CONCAT('ALTER TABLE prod_products ', @klauzule_renamu)" in tresc
    assert tresc.count("information_schema.COLUMNS") == 2
    assert "COLUMN_NAME = 'quantity_done_edges'" in tresc
    assert "COLUMN_NAME = 'edges_completed_at'" in tresc


def test_rollback_kazdy_prepare_ma_swoje_deallocate():
    """Po scaleniu para jest JEDNA: oba renamey ida jednym ALTER-em, wiec
    jedno PREPARE, jedno EXECUTE i jedno DEALLOCATE. Zapomniane DEALLOCATE
    zostawia nazwe zajeta na calym polaczeniu -- w rollbacku odpalanym pod
    presja na zepsutej produkcji to szczegolnie kosztowne do zdiagnozowania."""
    polecenia = [_bez_bialych(p).upper() for p in
                 MigrationService.split_statements(_tresc_rollbacku())]
    przygotowania = [p for p in polecenia if p.startswith("PREPARE ")]
    wykonania = [p for p in polecenia if p.startswith("EXECUTE ")]
    zwolnienia = [p for p in polecenia if p.startswith("DEALLOCATE PREPARE ")]
    assert len(przygotowania) == len(wykonania) == len(zwolnienia) == 1


def test_rollback_dokancza_polowiczny_stan_kolumn():
    """Przerwany POPRZEDNI przebieg ROLLBACKU (nie migracji) zostawia jedna
    z dwoch kolumn juz cofnieta do starej nazwy, druga jeszcze pod nowa.
    Taki stan powstaje, gdy rollback ubije cos niezaleznego od jego tresci --
    zerwane polaczenie, restart mysqld -- a w rollbacku dzieje sie to na
    produkcji JUZ zepsutej i naprawianej pod presja. Nastepny przebieg musi
    wtedy dokonczyc sama brakujaca kolumne: nie pasc na tej juz cofnietej
    (1054 w ALTER-ze przerywa skrypt w polowie) i nie pominac tej nietknietej
    (schemat zostaje rozjechany).

    Test jest statyczny -- patrzy na tresc pliku, bo SQLite nie zna ani
    information_schema, ani PREPARE."""
    polecenia = [_bez_bialych(p) for p in
                 MigrationService.split_statements(_tresc_rollbacku())]

    indeks_ilosci = next(i for i, p in enumerate(polecenia)
                         if p.startswith("SET @kolumna_ilosci"))
    indeks_daty = next(i for i, p in enumerate(polecenia)
                       if p.startswith("SET @kolumna_daty"))
    indeks_klauzul = next(i for i, p in enumerate(polecenia)
                          if "CONCAT_WS" in p.upper())

    # OBA liczniki musza stac PRZED zbudowaniem klauzul. Licznik policzony po
    # wykonaniu renamu patrzylby na schemat, ktorego to polecenie wlasnie
    # dotknelo -- po scaleniu obu renameow w jeden ALTER byloby to cichym bledem.
    assert indeks_ilosci < indeks_klauzul, (indeks_ilosci, indeks_klauzul)
    assert indeks_daty < indeks_klauzul, (indeks_daty, indeks_klauzul)

    # Kazda kolumna ma WLASNY warunek, na WLASNYM liczniku: cztery stany
    # schematu (obie nowe, kazda z dwoch osobno cofnieta, obie stare) sa
    # obsluzone, bo CONCAT_WS pomija NULL-e.
    klauzule = polecenia[indeks_klauzul]
    assert ("IF(@kolumna_ilosci > 0, 'RENAME COLUMN quantity_done_edges "
            "TO quantity_done_finishing', NULL)") in klauzule, klauzule
    assert ("IF(@kolumna_daty > 0, 'RENAME COLUMN edges_completed_at "
            "TO finishing_completed_at', NULL)") in klauzule, klauzule

    # Puste klauzule (drugi przebieg, obie kolumny juz stare) nie moga zlozyc
    # sie w goly 'ALTER TABLE prod_products'.
    skladanie = polecenia[indeks_klauzul + 1]
    assert skladanie.startswith("SET @sql_renamu"), skladanie
    assert "'SELECT 1'" in skladanie, skladanie


def test_rollback_korzysta_z_tabeli_kopii():
    """Bez JOIN-a po kopii nie odroznimy eventow przeniesionych na 'painting'
    od tych, ktore byly tam wczesniej."""
    tresc = _tresc_rollbacku()
    assert "prod_migracja_krawedzie_kopia" in tresc
    assert "k.tabela = 'prod_products'" in tresc
    assert "k.tabela = 'prod_station_events'" in tresc
    assert "DROP TABLE" not in tresc.upper()


def test_rollback_krok3_cofa_krawedzie_bezwarunkowo_a_lakiernie_tylko_pod_waska_regula():
    """Scenariusz z hali (recenzja 2026-09-15): produkt, ktorego migracja
    postawila na 'czeka_na_krawedzie', odbija sie REALNIE na stanowisku
    Krawedzie i pod nowym kodem trafia na 'czeka_na_lakiernie'
    (modules/production/models.py:566-568) — to nie efekt uboczny migracji,
    tylko wykonana praca. Tabela kopii tych dwoch przypadkow (ten i produkt,
    ktorego migracja wyslala na 'czeka_na_lakiernie' WPROST, sekcja 1 migracji)
    nie odroznia: oba maja stara_wartosc = 'czeka_na_wykanczanie'. Bez waskiej
    reguly krok 3 cofnalby OBA do kolejki wykanczania, mimo ze jeden z nich ma
    juz quantity_done_edges rowne quantity i date zakonczenia ustawiona —
    wracalby do kolejki z licznikiem mowiacym "zrobione"."""
    polecenie = next(
        _bez_bialych(p) for p in
        MigrationService.split_statements(_tresc_rollbacku())
        if "prod_migracja_krawedzie_kopia" in p
        and _bez_bialych(p).upper().startswith("UPDATE PROD_PRODUCTS")
    )
    warunek = polecenie.split(" WHERE ", 1)[1]

    # Bezwarunkowe cofniecie: kazda pozycja na 'czeka_na_krawedzie' wraca,
    # bez dodatkowych ograniczen -- to catch-all dla galezi, ktora migracja
    # zawsze wysylala na to samo miejsce.
    assert warunek.startswith("p.current_status = 'czeka_na_krawedzie'")

    # Waskie cofniecie: 'czeka_na_lakiernie' wraca WYLACZNIE pod ta sama regula,
    # ktorej migracja uzyla do rozdzielenia kolejki (sekcja 1 pliku migracji) --
    # inaczej nie da sie odroznic wiersza wyslanego tam WPROST od produktu po
    # realnie wykonanej Krawedzi.
    assert "OR (p.current_status = 'czeka_na_lakiernie'" in warunek
    assert "p.parsed_edge_processing = 0" in warunek
    assert "p.parsed_finish_type IN ('olejowane','lakierowane')" in warunek


def test_rollback_zdejmuje_enum_dopiero_po_wszystkich_updatach():
    polecenia = [_bez_bialych(p) for p in
                 MigrationService.split_statements(_tresc_rollbacku())]
    indeks_zwezajacego = next(
        i for i, p in enumerate(polecenia)
        if p.upper().startswith("ALTER TABLE PROD_PRODUCTS MODIFY")
        and "'czeka_na_krawedzie'" not in p
    )
    ostatni_update = max(
        i for i, p in enumerate(polecenia)
        if p.upper().startswith("UPDATE PROD_PRODUCTS")
    )
    assert ostatni_update < indeks_zwezajacego


def test_rollback_kasuje_wpis_w_schema_migrations():
    """Bez tego poprawiona migracja JUZ NIGDY sie nie wykona."""
    tresc = _tresc_rollbacku()
    assert ("DELETE FROM schema_migrations WHERE version = "
            "'2026-09-15-krawedzie-podzial-wykanczania'") in tresc


def test_rollback_obsluguje_obie_konwencje_kluczy_prod_config():
    tresc = _tresc_rollbacku()
    assert "RIGHT(config_key, 6) = '_EDGES'" in tresc
    assert "LEFT(config_key, 14) = 'STATION_EDGES_'" in tresc


def test_rollback_cofa_kazda_tabele_ruszona_przez_migracje():
    """WZMOCNIENIE ponad brief. Testy powyzej sprawdzaja kolumny, kopie, enum
    i rejestr — zadna nie zauwazylaby rollbacku, ktory zapomnial o tabletach
    albo o sesjach. Tablet z kodem stanowiska, ktorego cofniety kod nie zna,
    to hala bez dostepu do panelu."""
    polecenia_rollbacku = " ".join(
        _bez_bialych(p) for p in
        MigrationService.split_statements(_tresc_rollbacku()))
    for tabela in ("prod_devices", "prod_worker_sessions", "prod_print_queue",
                   "prod_workers", "prod_rework_log", "prod_config",
                   "prod_station_events", "prod_products"):
        assert "UPDATE {}".format(tabela) in polecenia_rollbacku, tabela


def test_rollback_nie_zostawia_kodu_krawedzi_w_zadnej_tabeli():
    """WZMOCNIENIE ponad brief. Kazde cofniecie ma szukac NOWEJ wartosci
    i zapisywac STARA — odwrotny kierunek (albo skopiowany z migracji warunek
    na 'finishing') nie ruszylby ani jednego wiersza i nie zglosil bledu."""
    for polecenie in MigrationService.split_statements(_tresc_rollbacku()):
        jedna_linia = _bez_bialych(polecenie)
        if not jedna_linia.upper().startswith("UPDATE"):
            continue
        if "prod_migracja_krawedzie_kopia" in jedna_linia:
            continue  # odtworzenie z kopii, warunek jest na tabeli kopii
        assert " WHERE " in jedna_linia.upper(), jedna_linia[:60]
        warunek = jedna_linia.upper().split(" WHERE ", 1)[1]
        assert "EDGES" in warunek or "KRAWEDZIE" in warunek, jedna_linia[:80]


SCIEZKA_WERYFIKACJI_PRZED = KATALOG_SKRYPTOW / "weryfikacja-2026-09-15-krawedzie-przed.sql"
SCIEZKA_WERYFIKACJI_PO = KATALOG_SKRYPTOW / "weryfikacja-2026-09-15-krawedzie-po.sql"


def test_skrypty_weryfikacyjne_sa_wylacznie_do_odczytu():
    """Oba pliki operator wkleja na PRODUKCJI. Maja nie miec zadnego zapisu."""
    for sciezka in (SCIEZKA_WERYFIKACJI_PRZED, SCIEZKA_WERYFIKACJI_PO):
        polecenia = MigrationService.split_statements(
            sciezka.read_text(encoding="utf-8"))
        assert polecenia, "{} nie ma ani jednego polecenia".format(sciezka.name)
        for polecenie in polecenia:
            gora = _bez_bialych(polecenie).upper()
            assert gora.startswith("SELECT") or gora.startswith("SHOW"), (
                sciezka.name, polecenie[:60])


def test_weryfikacja_przed_sprawdza_wartosci_runtime():
    """LABEL_PRINTER_ALLOWED_STATIONS, obie konwencje kluczy, allowed_stations —
    grep po repo zadnej z tych wartosci nie znajdzie."""
    tresc = SCIEZKA_WERYFIKACJI_PRZED.read_text(encoding="utf-8")
    assert "LABEL_PRINTER_ALLOWED_STATIONS" in tresc
    assert "RIGHT(config_key, 10) = '_FINISHING'" in tresc
    assert "LEFT(config_key, 18) = 'STATION_FINISHING_'" in tresc
    assert "allowed_stations" in tresc


def test_weryfikacja_przed_pilnuje_warunkow_zwezenia_enumow():
    """Trzy miejsca, w ktorych migracja moze pasc i przerwac deploy: niepasujaca
    wartosc w prod_rework_log (1265), kolizja kluczy prod_config (1062)
    i produkt wstrzymany z wykanczania (ryzyko R10)."""
    tresc = SCIEZKA_WERYFIKACJI_PRZED.read_text(encoding="utf-8")
    assert "rejected_at_station" in tresc
    assert "RIGHT(config_key, 6) = '_EDGES'" in tresc
    assert "'wstrzymane'" in tresc
    assert "parsed_edge_processing" in tresc


def test_weryfikacja_przed_nie_dotyka_nowych_kolumn():
    """WZMOCNIENIE ponad brief — lustro testu dla skryptu 'po'. Skrypt 'przed'
    operator wkleja na STARYM schemacie; odwolanie do kolumny, ktora powstanie
    dopiero po migracji, konczy sie bledem 1054 i przerywa caly plik."""
    tresc = SCIEZKA_WERYFIKACJI_PRZED.read_text(encoding="utf-8")
    assert "quantity_done_edges" not in tresc
    assert "edges_completed_at" not in tresc


def test_weryfikacja_po_nie_dotyka_starych_kolumn():
    """Gdyby dotykala, na nowym schemacie poleciala by bledem 1054 i przerwala
    plik. To jest powod, dla ktorego sa dwa skrypty, a nie jeden."""
    tresc = SCIEZKA_WERYFIKACJI_PO.read_text(encoding="utf-8")
    assert "quantity_done_finishing" not in tresc
    assert "finishing_completed_at" not in tresc


def test_weryfikacja_po_sprawdza_bilans_eventow():
    """Jedyna asercja lapiaca ZGUBIENIE wiersza: liczba wierszy w tabeli kopii
    musi rownac sie sumie przeniesionych na 'edges' i na 'painting'."""
    tresc = SCIEZKA_WERYFIKACJI_PO.read_text(encoding="utf-8")
    assert "w_kopii" in tresc
    assert "trafilo_na_krawedzie" in tresc
    assert "trafilo_na_lakiernie" in tresc


def test_bilans_eventow_liczy_sie_z_jednego_polecenia():
    """WZMOCNIENIE ponad brief. Trzy liczby rozrzucone po trzech poleceniach
    nadal daja sie porownac recznie, ale tylko jedno polecenie gwarantuje, ze
    wszystkie trzy pochodza z tego samego momentu i z tej samej tabeli kopii.
    Test wyzej przeszedlby rownie dobrze na trzech osobnych SELECT-ach."""
    polecenia = MigrationService.split_statements(
        SCIEZKA_WERYFIKACJI_PO.read_text(encoding="utf-8"))
    bilans = [p for p in polecenia if "w_kopii" in p]
    assert len(bilans) == 1, [p[:60] for p in bilans]
    jedno = _bez_bialych(bilans[0])
    assert "trafilo_na_krawedzie" in jedno
    assert "trafilo_na_lakiernie" in jedno
    assert jedno.count("prod_migracja_krawedzie_kopia") == 3, jedno


def test_weryfikacja_po_sprawdza_schemat_i_rejestr():
    tresc = SCIEZKA_WERYFIKACJI_PO.read_text(encoding="utf-8")
    assert "SHOW COLUMNS FROM prod_products LIKE '%finishing%'" in tresc
    assert "SHOW COLUMNS FROM prod_products LIKE '%edges%'" in tresc
    assert "schema_migrations" in tresc
