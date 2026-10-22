import pytest

from agent_druku import sciezki
from agent_druku.dziennik import Dziennik


@pytest.fixture(autouse=True)
def katalog(tmp_path, monkeypatch):
    monkeypatch.setattr(sciezki, 'katalog_danych', lambda: tmp_path)


def test_dziennik_po_restarcie_nie_wysyla_ponownie():
    d = Dziennik()
    d.zapisz(10, 'etykiety', 'K1', 'wysylam')
    assert d.czy_wysylane(10) is True
    d.zamknij()
    nowy = Dziennik()
    assert nowy.czy_wysylane(10) is True
    assert nowy.czy_wysylane(11) is False


def test_niepotwierdzone_tylko_stany_koncowe_bez_potwierdzenia():
    d = Dziennik()
    d.zapisz(1, 'etykiety', 'A', 'pobrane')
    d.zapisz(2, 'etykiety', 'B', 'wysylam')
    d.zapisz(3, 'etykiety', 'C', 'wydrukowane')
    d.zapisz(4, 'wysylka', 'D', 'blad')
    d.zapisz(5, 'wysylka', 'E', 'niewyslane')
    assert [w['job_id'] for w in d.niepotwierdzone()] == [3, 4, 5]
    d.oznacz_wyslane([(w['job_id'], w['rewizja']) for w in d.niepotwierdzone() if w['job_id'] in (3, 5)])
    assert [w['job_id'] for w in d.niepotwierdzone()] == [4]
    # po restarcie to samo
    d.zamknij()
    assert [w['job_id'] for w in Dziennik().niepotwierdzone()] == [4]


def test_zmiana_stanu_unieważnia_potwierdzenie():
    d = Dziennik()
    d.zapisz(1, 'etykiety', 'A', 'blad')
    d.oznacz_wyslane([(1, 1)])
    d.zapisz(1, 'etykiety', 'A', 'wydrukowane')
    assert [w['job_id'] for w in d.niepotwierdzone()] == [1]


def test_ostatnie_i_nieznany_stan():
    d = Dziennik()
    for i in range(5):
        d.zapisz(i, 'etykiety', 'K%d' % i, 'wydrukowane')
    assert len(d.ostatnie(3)) == 3
    with pytest.raises(ValueError):
        d.zapisz(9, 'etykiety', 'X', 'dziwny')


def test_zmiana_stanu_po_odczycie_nie_oznaczona_jako_wyslana():
    d = Dziennik()
    d.zapisz(1, 'etykiety', 'A', 'blad')
    odczyt = d.niepotwierdzone()
    d.zapisz(1, 'etykiety', 'A', 'wydrukowane')  # zmiana między odczytem a potwierdzeniem
    d.oznacz_wyslane([(w['job_id'], w['rewizja']) for w in odczyt])
    reszta = d.niepotwierdzone()
    assert [(w['job_id'], w['stan']) for w in reszta] == [(1, 'wydrukowane')]


def test_przerwana_wysylka_po_restarcie_to_nieznany():
    d = Dziennik()
    d.zapisz(1, 'etykiety', 'K1', 'wysylam')
    d.zapisz(2, 'etykiety', 'K2', 'wydrukowane')
    d.zamknij()

    d = Dziennik()
    assert d.oznacz_przerwane() == 1
    assert {w['job_id']: w['stan'] for w in d.ostatnie(10)} == {1: 'nieznany', 2: 'wydrukowane'}
    assert d.czy_wysylane(1)            # nadal nie wysyłamy drugi raz
    assert [w['job_id'] for w in d.niepotwierdzone()] == [2]   # bez wyniku do CRM


def test_uszkodzony_dziennik_odlozony_i_pusty(tmp_path, caplog):
    plik = tmp_path / 'dziennik.db'
    plik.write_bytes(b'to nie jest baza SQLite' * 100)
    with caplog.at_level('CRITICAL', logger='agent_druku.dziennik'):
        d = Dziennik(plik)
    try:
        assert d.niepotwierdzone() == [] and d.ostatnie(5) == []
        d.zapisz(1, 'etykiety', 'K1', 'wydrukowane')
        assert [w['job_id'] for w in d.niepotwierdzone()] == [1]
    finally:
        d.zamknij()
    odlozone = list(tmp_path.glob('dziennik.db.uszkodzony-*'))
    assert len(odlozone) == 1 and odlozone[0].read_bytes().startswith(b'to nie jest')
    assert any(r.levelname == 'CRITICAL' for r in caplog.records)
