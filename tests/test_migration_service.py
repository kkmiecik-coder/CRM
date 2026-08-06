# -*- coding: utf-8 -*-
"""
Runner migracji — rozpoznawanie nazw i dzielenie plików SQL.

Do 2026-08-06 wzorzec nazw akceptował wyłącznie `001_nazwa.sql`, więc CZTERY
migracje datowane były pomijane po cichu: bez błędu, bez ostrzeżenia, bez
śladu w logu. Schemat trzeba było wgrywać ręcznie i nikt nie wiedział dlaczego.
Te testy pilnują obu formatów naraz oraz tego, że nierozpoznany plik krzyczy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations.migration_service import MigrationService


class _Log:
    """Zbiera komunikaty zamiast pisać na stderr."""

    def __init__(self):
        self.wpisy = []

    def info(self, msg):
        self.wpisy.append(('info', msg))

    def warning(self, msg):
        self.wpisy.append(('warning', msg))

    def error(self, msg):
        self.wpisy.append(('error', msg))


def _serwis():
    return MigrationService(db=None, logger=_Log())


# ── Rozpoznawanie nazw ──────────────────────────────────────────────────────

def test_format_numeryczny_dziala_jak_dotad():
    assert _serwis()._match('021_quote_product_type.sql') == \
        ('021', 'quote_product_type', 'sql')


def test_format_datowany_jest_rozpoznawany():
    """Regresja na cztery pominięte migracje."""
    assert _serwis()._match('2026-08-06-sawmill.sql') == \
        ('2026-08-06-sawmill', '2026-08-06-sawmill', 'sql')


def test_wersja_datowana_zawiera_nazwe_nie_sama_date():
    """
    Dwie migracje z tego samego dnia muszą mieć różne wersje — na samej dacie
    kolidowałyby na UNIQUE(version) i druga nigdy by się nie wykonała.
    """
    s = _serwis()
    a = s._match('2026-08-06-sawmill.sql')[0]
    b = s._match('2026-08-06-inna-zmiana.sql')[0]
    assert a != b


def test_migracje_python_tez_w_obu_formatach():
    s = _serwis()
    assert s._match('022_partner_academy_drop_pesel.py')[2] == 'py'
    assert s._match('2026-08-06-cos.py')[2] == 'py'


def test_nierozpoznane_nazwy_zwracaja_none():
    s = _serwis()
    for nazwa in ('notatki.txt', 'sawmill.sql', '12_za_krotki.sql',
                  '2026-8-6-zla-data.sql'):
        assert s._match(nazwa) is None, nazwa


def test_kolejnosc_numeryczne_przed_datowanymi():
    """sorted() po nazwie pliku: '0' < '2', więc stare migracje idą pierwsze."""
    pliki = sorted(['2026-08-06-sawmill.sql', '001_edges.sql', '021_quote.sql'])
    assert pliki[0].startswith('001')
    assert pliki[-1].startswith('2026')


# ── Dzielenie plików SQL ────────────────────────────────────────────────────

def test_srednik_w_stringu_nie_dzieli_poleceń():
    """
    Seed trakowni wstawia JSON do prod_config. Średnik w wartości rozciąłby
    polecenie w środku i wywalił migrację na produkcji.
    """
    sql = """INSERT INTO cfg VALUES ('{"opis": "krok1; krok2"}');
CREATE TABLE a (x INT);"""
    polecenia = MigrationService.split_statements(sql)
    assert len(polecenia) == 2
    assert 'krok1; krok2' in polecenia[0]


def test_komentarze_sa_usuwane():
    sql = """-- komentarz; ze średnikiem
CREATE TABLE a (x INT);
/* blok; komentarz */
SELECT 1;"""
    polecenia = MigrationService.split_statements(sql)
    assert len(polecenia) == 2
    assert not any(p.startswith('--') for p in polecenia)
    assert 'komentarz' not in ' '.join(polecenia)


def test_apostrof_w_stringu_nie_konczy_cytowania():
    sql = "INSERT INTO a VALUES ('D\\'Artagnan; x'); SELECT 1;"
    polecenia = MigrationService.split_statements(sql)
    assert len(polecenia) == 2


def test_backticki_sa_traktowane_jak_cytowanie():
    sql = 'CREATE TABLE `dziwna;nazwa` (x INT); SELECT 1;'
    polecenia = MigrationService.split_statements(sql)
    assert len(polecenia) == 2


def test_ostatnie_polecenie_bez_srednika_nie_ginie():
    polecenia = MigrationService.split_statements('SELECT 1; SELECT 2')
    assert polecenia == ['SELECT 1', 'SELECT 2']


def test_pusty_plik_daje_pusta_liste():
    assert MigrationService.split_statements('-- tylko komentarz\n') == []


# ── Realne pliki repo ───────────────────────────────────────────────────────

def test_wszystkie_pliki_w_katalogu_migracji_sa_rozpoznawane():
    """
    Najważniejszy test tego pliku: plik migracji o nazwie, której runner nie
    rozumie, jest pomijany bez błędu — dokładnie tak zniknęły cztery migracje.
    """
    s = _serwis()
    nierozpoznane = []
    for plik in sorted(s.MIGRATIONS_DIR.iterdir()):
        if plik.is_dir() or plik.name in s.NON_MIGRATION_FILES:
            continue
        if plik.name.endswith(('.pyc',)) or plik.name == '__pycache__':
            continue
        if s._match(plik.name) is None:
            nierozpoznane.append(plik.name)
    assert nierozpoznane == [], \
        u'pliki niewidoczne dla runnera migracji: {}'.format(nierozpoznane)


def test_migracja_trakowni_jest_idempotentna():
    """Runner chodzi przy KAŻDYM deployu — drugi przebieg nie może paść."""
    s = _serwis()
    plik = s.MIGRATIONS_DIR / '2026-08-06-sawmill.sql'
    tresc = plik.read_text(encoding='utf-8')
    polecenia = MigrationService.split_statements(tresc)
    for p in polecenia:
        gora = p.upper()
        if gora.startswith('CREATE TABLE'):
            assert 'IF NOT EXISTS' in gora, p[:60]
        if gora.startswith('INSERT'):
            assert gora.startswith('INSERT IGNORE'), p[:60]


def test_podkatalogi_sa_pomijane():
    """
    migrations/archive/ trzyma migracje, których nie da się już wykonać
    (operują na tabelach, które zniknęły). Runner nie może w nie wchodzić.
    """
    s = _serwis()
    archiwum = s.MIGRATIONS_DIR / 'archive'
    assert archiwum.is_dir(), 'brak katalogu archiwum'
    pliki_archiwum = {p.name for p in archiwum.iterdir() if p.suffix == '.sql'}
    assert pliki_archiwum, 'archiwum jest puste — test straciłby sens'

    # Żaden plik archiwum nie może pojawić się na liście do wykonania.
    widziane = set()
    for plik in s.MIGRATIONS_DIR.iterdir():
        if plik.is_dir():
            continue
        if s._match(plik.name):
            widziane.add(plik.name)
    assert not (widziane & pliki_archiwum)
