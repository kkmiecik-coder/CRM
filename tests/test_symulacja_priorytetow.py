# -*- coding: utf-8 -*-
"""
Skrypt symulacji priorytetów (`scripts/symulacja_priorytetow.py`) na małej bazie SQLite.

Skrypt celowo nie importuje aplikacji (patrz jego docstring), więc i ten test nie buduje Flaska:
tworzy tabele gołym DDL z kolumnami, które skrypt czyta, i sprawdza reguły ze specu
2026-10-04-priorytety-produkcji-design.md (3.1, 3.2, 5.6) oraz odporność na brak tabel logistyki.
"""
import importlib.util
import os
import sqlite3
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKRYPT = os.path.join(KORZEN, 'scripts', 'symulacja_priorytetow.py')


def _modul():
    spec = importlib.util.spec_from_file_location('symulacja_priorytetow', SKRYPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules['symulacja_priorytetow'] = m
    spec.loader.exec_module(m)
    return m


DDL = """
CREATE TABLE prod_orders(id INTEGER PRIMARY KEY, internal_order_number TEXT, payment_date TEXT, created_at TEXT,
  delivery_method TEXT, baselinker_status_id INTEGER);
CREATE TABLE prod_configurations(id INTEGER PRIMARY KEY, species TEXT, technology TEXT, wood_class TEXT);
CREATE TABLE prod_products(id INTEGER PRIMARY KEY, order_id INTEGER, short_product_id TEXT, product_sequence_in_order INTEGER,
  current_status TEXT, deadline_date TEXT, priority_rank INTEGER, is_priority INTEGER, quantity INTEGER,
  parsed_length_cm REAL, parsed_width_cm REAL, parsed_thickness_cm REAL, parsed_finish_type TEXT, configuration_id INTEGER,
  created_at TEXT, original_product_id INTEGER, cut_to_size INTEGER,
  cutting_completed_at TEXT, assembly_completed_at TEXT, gluing_completed_at TEXT, formatting_completed_at TEXT,
  edges_completed_at TEXT, painting_completed_at TEXT, packaging_completed_at TEXT);
CREATE TABLE prod_station_events(id INTEGER PRIMARY KEY, production_item_id INTEGER, station_code TEXT, delta INTEGER,
  created_at TEXT, source TEXT);
"""

DZIS = date(2026, 10, 5)   # poniedziałek


def _pozycja(cur, pid, oid, seq, status, termin, rank, dl, sz, gr, cfg=1, dorobka=None, **kw):
    kol = ['id', 'order_id', 'short_product_id', 'product_sequence_in_order', 'current_status', 'deadline_date',
           'priority_rank', 'is_priority', 'quantity', 'parsed_length_cm', 'parsed_width_cm', 'parsed_thickness_cm',
           'parsed_finish_type', 'configuration_id', 'created_at', 'original_product_id', 'cut_to_size'] + list(kw)
    wart = [pid, oid, '%d_%d' % (1200 + oid, seq), seq, status, termin, rank, 0, 1, dl, sz, gr, 'surowe', cfg,
            '2026-09-20 10:00:00', dorobka, 1] + list(kw.values())
    cur.execute('INSERT INTO prod_products(%s) VALUES(%s)' % (','.join(kol), ','.join('?' * len(kol))), wart)


@pytest.fixture
def baza(tmp_path):
    sciezka = str(tmp_path / 'sym.db')
    c = sqlite3.connect(sciezka)
    cur = c.cursor()
    cur.executescript(DDL)
    cur.executemany('INSERT INTO prod_configurations VALUES(?,?,?,?)',
                    [(1, 'dąb', 'lity', 'A/B'), (2, 'dąb', 'mikrowczep', 'A/B'), (3, 'buk', 'lity', 'B')])
    for oid in range(1, 7):
        cur.execute('INSERT INTO prod_orders VALUES(?,?,?,?,?,?)',
                    (oid, str(1200 + oid), '2026-09-20 10:00:00', '2026-09-20 10:00:00', 'Kurier', 155824))
    # Zam. 1: bez tagu, 3 pozycje na Sklejaniu — grupowanie po grubości/długości (przykład Konrada).
    _pozycja(cur, 1, 1, 1, 'czeka_na_sklejanie', '2026-10-30', 10, 180, 40, 3)
    _pozycja(cur, 2, 1, 2, 'czeka_na_sklejanie', '2026-10-30', 11, 190, 50, 4)
    _pozycja(cur, 3, 1, 3, 'czeka_na_sklejanie', '2026-10-30', 12, 170, 78, 3)
    # Zam. 2: po terminie, jedna pozycja na Sklejaniu — ma być przed zam. 1 mimo gorszej rangi dziś.
    _pozycja(cur, 4, 2, 1, 'czeka_na_sklejanie', '2026-10-01', 50, 140, 50, 4)
    # Zam. 3: rozpoczęte — jedna pozycja już na Formatowaniu, druga na Sklejaniu.
    _pozycja(cur, 5, 3, 1, 'czeka_na_formatowanie', '2026-10-28', 20, 180, 60, 3)
    _pozycja(cur, 6, 3, 2, 'czeka_na_sklejanie', '2026-10-28', 21, 180, 70, 4)
    # Zam. 4: doróbka na Sklejaniu (ranga 1, jak dziś nadaje rework_service) + oryginał spakowany.
    _pozycja(cur, 7, 4, 1, 'spakowane', '2026-10-20', None, 180, 60, 4,
             packaging_completed_at='2026-10-01 12:00:00', gluing_completed_at='2026-09-25 09:00:00')
    _pozycja(cur, 8, 4, 9, 'czeka_na_sklejanie', '2026-10-20', 1, 180, 60, 4, dorobka=7)
    # Zam. 5: kompletne na Formatowaniu (2 pozycje), termin daleko.
    _pozycja(cur, 9, 5, 1, 'czeka_na_formatowanie', '2026-11-05', 30, 200, 50, 4)
    _pozycja(cur, 10, 5, 2, 'czeka_na_formatowanie', '2026-11-05', 31, 200, 50, 4)
    # Zam. 6: blisko terminu (środa 7.10 przy progu 2 dni rob. od poniedziałku), na Składaniu.
    _pozycja(cur, 11, 6, 1, 'czeka_na_skladanie', '2026-10-07', 40, 180, 60, 4, cfg=3)
    # Historia: zam. 5 — dwie pozycje weszły na Formatowanie 30 h od siebie (rozrzut).
    cur.execute("UPDATE prod_products SET gluing_completed_at='2026-10-01 08:00:00' WHERE id=9")
    cur.execute("UPDATE prod_products SET gluing_completed_at='2026-10-02 14:00:00' WHERE id=10")
    cur.execute("INSERT INTO prod_station_events(production_item_id,station_code,delta,created_at,source) VALUES(9,'gluing',1,'2026-10-01 08:00:00','mobile')")
    c.commit()
    c.close()
    return sciezka


def _symulacja(baza, **kw):
    m = _modul()
    engine = create_engine('sqlite:///' + baza)
    dane = m.wczytaj(engine, DZIS, 60)
    wyn = m.symuluj(dane, k=kw.get('k', 2), blisko_dni=kw.get('blisko', 2), gwiazdki=kw.get('gwiazdki'),
                    drabina=kw.get('drabina'), top=25)
    hist = m.historia(dane)
    return m, wyn, hist


def test_brak_tabel_logistyki_nie_przerywa(baza):
    _, wyn, _ = _symulacja(baza)
    assert wyn['srodowisko']['logistyka_tabele'] is False
    assert wyn['srodowisko']['logistyka_kolumny'] is False
    assert wyn['zamowienia']['na_trasie'] == 0


def test_tagi_i_szczeble(baza):
    _, wyn, _ = _symulacja(baza)
    z = wyn['zamowienia']
    assert z['aktywnych'] == 6
    assert z['po_terminie'] == 1          # zam. 2
    assert z['blisko_terminu'] == 1       # zam. 6 (7.10 ≤ pon 5.10 + 2 dni rob.)
    assert z['rozpoczete'] == 2           # zam. 3 (Formatowanie czeka) i zam. 4 (spakowane + doróbka → Pakowanie czeka)
    assert z['z_dorobka'] == 1


def test_kolejka_sklejania_dorobka_tagi_grupowanie(baza):
    _, wyn, _ = _symulacja(baza)
    sk = wyn['stanowiska']['gluing']
    pozycje = [w['pozycja'] for w in sk['kolejka']]
    # doróbka pierwsza, potem po terminie (zam. 2), potem rozpoczęte (zam. 3), potem zam. 1 pogrupowane:
    # grubość malejąco (4 cm przed 3 cm), w 3 cm długość malejąco (180 przed 170).
    assert pozycje == ['1204_9', '1202_1', '1203_2', '1201_2', '1201_1', '1201_3']
    assert sk['kolejka'][0]['dorobka'] is True
    assert sk['kolejka'][1]['tagi'] == ['po_terminie']
    assert sk['kolejka'][2]['tagi'] == ['rozpoczete']
    assert [w['pozycja'] for w in sk['stol']] == ['1204_9', '1202_1']
    # „Dziś #” pochodzi z priority_rank: zam. 2 (ranga 50) było dziś ostatnie.
    assert sk['kolejka'][1]['obecna'] == 6


def test_gwiazdki_i_drabina_zmieniaja_kolejnosc(baza):
    _, wyn, _ = _symulacja(baza, gwiazdki={'1201': 5})
    pozycje = [w['pozycja'] for w in wyn['stanowiska']['gluing']['kolejka']]
    # ★★★★★ stoi nad „Po terminie” w drabinie domyślnej → zam. 1 przed zam. 2; doróbka nadal pierwsza.
    assert pozycje[:4] == ['1204_9', '1201_2', '1201_1', '1201_3']
    _, wyn2, _ = _symulacja(baza, gwiazdki={'1201': 5},
                            drabina=['po_terminie', 'g5', 'g4', 'rozpoczete', 'blisko_terminu', 'g3', 'g2', 'g1', 'g0'])
    assert [w['pozycja'] for w in wyn2['stanowiska']['gluing']['kolejka']][:2] == ['1204_9', '1202_1']


def test_formatowanie_kompletne_na_stol_niekompletne_osobno(baza):
    _, wyn, _ = _symulacja(baza)
    f = wyn['stanowiska']['formatting']
    assert f['jednostka'] == 'zamowienie'
    assert f['kompletnych'] == 1 and f['niekompletnych'] == 1
    assert [w['zamowienie'] for w in f['stol']] == ['1205']
    niek = f['niekompletne'][0]
    assert niek['zamowienie'] == '1203' and niek['na_stanowisku'] == 1 and niek['pozycji_aktywnych'] == 2
    assert niek['brakuje'] == [{'pozycja': '1203_2', 'status': 'czeka_na_sklejanie'}]
    # w kolejce zamówień rozpoczęte 1203 stoi przed 1205 (szczebel „Rozpoczęte” nad „bez gwiazdek”),
    # ale na stół wchodzi tylko kompletne.
    assert [w['zamowienie'] for w in f['kolejka']] == ['1203', '1205']


def test_historia_rozrzut_i_zdarzenia(baza):
    _, _, hist = _symulacja(baza)
    r = hist['rozrzut_zamowien']['formatting']
    assert r['zamowien'] == 1 and r['mediana_h'] == 30.0 and r['udzial_ponad_24h'] == 1.0
    assert hist['zdarzenia']['gluing']['zdarzen'] == 1 and hist['zdarzenia']['gluing']['z_tabletow'] == 1
    # Wycinanie liczy tylko pozycje mikrowczepu; w danych nic nie zakończono na Wycinaniu.
    assert hist['omijanie']['cutting']['zakonczen'] == 0


def test_raport_markdown_bez_nazw_klientow(baza, tmp_path):
    m, wyn, hist = _symulacja(baza)
    md = m.raport_md(wyn, hist, 'sqlite:///x')
    assert '# Symulacja priorytetów produkcji — 2026-10-05' in md
    assert '### Sklejanie (kafel = pozycja)' in md
    assert '1204_9 (doróbka)' in md
    assert 'Niekompletne (do K): 1203 1/2' in md
    assert 'client' not in md.lower() and 'klient' not in md.lower()


def test_opis_bazy_bez_hasla():
    m = _modul()
    assert m._opis_bazy('mysql+pymysql://user:tajne@127.0.0.1/baza') == 'mysql+pymysql://127.0.0.1/baza'
    assert m._opis_bazy('sqlite:////tmp/a.db') == 'sqlite:////tmp/a.db'
