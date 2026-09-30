# -*- coding: utf-8 -*-
"""Etykieta paczki 100x150 (logistyka etap 4, krok 4.1, spec 6.3)."""
import re
from datetime import date

import pytest

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.services import package_label as pl
from modules.production.services.package_label import DaneEtykietyPaczki, PozycjaEtykiety
from tests.druk_fixtures import app  # noqa: F401


def _pozycja(**zmiany):
    dane = dict(gatunek='dąb', technologia='lity', klasa='A/B', dlugosc_cm=97,
                szerokosc_cm=29, grubosc_cm=4, ilosc=5)
    dane.update(zmiany)
    return PozycjaEtykiety(**dane)


def _dane(**zmiany):
    dane = dict(numer_zamowienia='1450', kod_paczki='P-12345', rodzaj='paleta',
                typ_palety='eur', numer=1, z_ilu=1, sposob='TRANSPORT WOODPOWER',
                odbiorca='Dariusz Kowalczyk', pozycje=[_pozycja()], m3=0.373,
                spakowano=date(2026, 9, 25), base_id=49915386, zamowienie_klienta='2149/2026')
    dane.update(zmiany)
    return DaneEtykietyPaczki(**dane)


def _x(zpl):
    return [int(v) for v in re.findall(r'\^FO(-?\d+),', zpl)]


def _y(zpl):
    return [int(v) for v in re.findall(r'\^FO-?\d+,(-?\d+)', zpl)]


@pytest.mark.parametrize('nazwa, wynik', [
    ('Dariusz Kowalczyk', 'Dar*** Kow***'),
    ('Łucja Żak', 'Luc*** Zak'),
    ('Jan Maria Rokita', 'Jan Mar***'),
    ('  STOLBUD   Sp. z o.o. ', 'STO*** Sp.'),
    ('', ''),
    (None, ''),
])
def test_anonimizacja_odbiorcy(nazwa, wynik):
    assert pl.anonimizuj_odbiorce(nazwa) == wynik


def test_bez_pelnej_nazwy_i_tylko_ascii():
    zpl = pl.generate_package_label_zpl(_dane(odbiorca='Łukasz Źdźbło-Wiśniewski',
                                              sposob='TRASA: Łódź – Śląsk „wt"'))
    assert 'Luk***' in zpl and 'Lukasz' not in zpl and 'Zdzblo' not in zpl
    assert all(ord(z) < 128 for z in zpl)


def test_pusty_odbiorca():
    zpl = pl.generate_package_label_zpl(_dane(odbiorca=None))
    assert '^FDODBIORCA^FS' in zpl


def test_rozmiar_i_kod_qr():
    zpl = pl.generate_package_label_zpl(_dane())
    assert zpl.startswith('^XA') and zpl.rstrip().endswith('^XZ')
    assert '^PW800' in zpl and '^LL1200' in zpl
    assert '^BQN,2,11^FDLA,P-12345^FS' in zpl


def test_predkosc_druku_3_cale_na_sekunde_w_obu_etykietach():
    """Test 30.09 na XP-410B: 3 cale/s daje lepszą czerń niż domyślne 6 (kod QR skanuje telefon)."""
    assert pl.PREDKOSC_DRUKU_CALE_S == 3
    assert pl.generate_package_label_zpl(_dane()).startswith('^XA\n^PR3\n')
    assert pl.generate_test_label_zpl((0, 0)).startswith('^XA\n^PR3\n')


def test_stopka_z_adresem_firmy():
    zpl = pl.generate_package_label_zpl(_dane())
    assert '^FDBase.: 49915386   Zam. klienta: 2149/2026   WoodPower, Bachorz 14N^FS' in zpl
    bez_danych = pl.generate_package_label_zpl(_dane(base_id=None, zamowienie_klienta=None))
    assert '^FDBase.: -   Zam. klienta: -   WoodPower, Bachorz 14N^FS' in bez_danych


def test_stopka_ucina_numer_zamowienia_klienta_do_15_znakow():
    zpl = pl.generate_package_label_zpl(_dane(zamowienie_klienta='A' * 30))
    assert 'Zam. klienta: ' + 'A' * 12 + '...   WoodPower, Bachorz 14N' in zpl
    assert 'A' * 13 not in zpl


def test_rodzaj_i_numer_paczki():
    assert 'PALETA EUR 120x80' in pl.generate_package_label_zpl(_dane())
    zpl = pl.generate_package_label_zpl(_dane(rodzaj='paczka', typ_palety=None, numer=2, z_ilu=3))
    assert '^FR^FDPACZKA^FS' in zpl and '^FR^FD2 / 3^FS' in zpl and '^FDPACZKA^FS' in zpl
    zpl = pl.generate_package_label_zpl(_dane(typ_palety='niestandardowa', dlugosc_cm=150,
                                              szerokosc_cm=100))
    assert 'PALETA 150x100' in zpl


def test_waga_i_podsumowanie():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(ilosc=5), _pozycja(ilosc=3)],
                                              m3=0.373))
    assert 'Waga szac.: ok. 298 kg' in zpl
    assert '2 poz. / 8 szt. / 0,373 m3' in zpl
    assert 'Spakowano: 25.09.2026' in zpl


def test_wiersz_pozycji():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(
        dlugosc_cm=101.5, szerokosc_cm=29.0, grubosc_cm=4, wykonczenie='olejowane')]))
    assert '^FD1. Dab lity A/B 101.5x29x4 cm, olejowane^FS' in zpl
    assert '^FD5 szt.^FS' in zpl


def test_surowe_bez_dopisku():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(wykonczenie='surowe')]))
    assert 'surowe' not in zpl


def test_14_pozycji_miesci_sie_cala_lista():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(14)]))
    assert '14. Dab' in zpl and 'pozycji (' not in zpl


def test_15_pozycji_ucina_do_13_i_dopisuje_reszte():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(ilosc=1) for _ in range(15)]))
    assert '13. Dab' in zpl and '14. Dab' not in zpl
    assert '+ 2 pozycji (2 szt.) - pelna lista w CRM' in zpl


def test_tresc_miesci_sie_w_marginesach():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(40)]))
    assert min(_x(zpl)) >= pl.MARGINES
    assert min(_y(zpl)) >= pl.MARGINES
    assert max(_y(zpl)) <= 1108          # stopka startuje na 1108 i kończy się przed 1130


def test_dane_nie_wstrzykuja_komend_zpl():
    zpl = pl.generate_package_label_zpl(_dane(sposob='TRASA: ^XZ~JA', zamowienie_klienta='12^FS',
                                              odbiorca='^Jan ~Nowak', numer_zamowienia='14~50'))
    assert zpl.count('^XZ') == 1 and '~' not in zpl


def test_dlugi_numer_zamowienia_mniejsza_czcionka():
    assert '^A0N,140,120^FD1450^FS' in pl.generate_package_label_zpl(_dane())
    assert '^A0N,110,90^FD123456^FS' in pl.generate_package_label_zpl(_dane(numer_zamowienia='123456'))


def test_przesuniecie_przesuwa_wszystkie_pola():
    zero = pl.generate_package_label_zpl(_dane())
    przes = pl.generate_package_label_zpl(_dane(), przesuniecie=(8, -8))
    assert [x + 8 for x in _x(zero)] == _x(przes)
    assert [y - 8 for y in _y(zero)] == _y(przes)


def test_przesuniecie_nie_schodzi_ponizej_zera():
    zpl = pl.generate_package_label_zpl(_dane(), przesuniecie=(-120, -120))
    assert min(_x(zpl)) >= 0 and min(_y(zpl)) >= 0


def test_etykieta_probna():
    zpl = pl.generate_test_label_zpl((0, -8))
    assert '^FO24,16^GB752,1152,4^FS' in zpl          # ramka 3 mm, przesunięta o 1 mm w górę
    assert 'WYDRUK PROBNY' in zpl and 'X=0, Y=-8' in zpl
    assert all(ord(z) < 128 for z in zpl) and zpl.count('^XZ') == 1


@pytest.mark.parametrize('x, y, oczekiwane', [
    (None, None, (0, 0)),
    ('8', '-8', (8, -8)),
    ('abc', '', (0, 0)),
    ('500', '-500', (120, -120)),
])
def test_wczytaj_przesuniecie(app, x, y, oczekiwane):
    for klucz, wartosc in ((pl.KLUCZ_PRZESUNIECIA_X, x), (pl.KLUCZ_PRZESUNIECIA_Y, y)):
        if wartosc is not None:
            db.session.add(ProductionConfig(config_key=klucz, config_value=wartosc,
                                            config_type='integer'))
    db.session.commit()
    assert pl.wczytaj_przesuniecie() == oczekiwane


def test_stopka_numer_base_jako_liczba():
    """Numer Base. idzie do ZPL przez int() — pole przyjmuje tylko liczbę."""
    assert '^FDBase.: 49915386   Zam. klienta: 2149/2026' in pl.generate_package_label_zpl(_dane())
    assert '^FDBase.: -   Zam. klienta:' in pl.generate_package_label_zpl(_dane(base_id=None))
    with pytest.raises(ValueError):
        pl.generate_package_label_zpl(_dane(base_id='12^FS'))


def test_kod_paczki_i_pozycje_nie_wstrzykuja_komend_zpl():
    """Kod paczki (QR i tekst) i pola pozycji też idą przez _ascii — wszystkie pola tekstowe."""
    zpl = pl.generate_package_label_zpl(_dane(
        kod_paczki='P-1^XZ~JA',
        pozycje=[_pozycja(gatunek='^XA', technologia='~JA', klasa='^FS', wykonczenie='~DG')]))
    assert zpl.count('^XZ') == 1 and zpl.count('^XA') == 1 and '~' not in zpl


def test_tekst_ascii_publiczny():
    assert pl.tekst_ascii(u'Łódź ^ ~ „x”', 26) == 'Lodz "x"'


def test_waga_ta_sama_co_w_logistyce():
    from modules.production.logistics import sposoby
    assert pl.WAGA_KG_NA_M3 == sposoby.WAGA_KG_NA_M3
