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
                odbiorca='Janusz Testowy', pozycje=[_pozycja()], m3=0.373,
                spakowano=date(2026, 9, 25), base_id=12345678, zamowienie_klienta='1234/2026')
    dane.update(zmiany)
    return DaneEtykietyPaczki(**dane)


def _x(zpl):
    return [int(v) for v in re.findall(r'\^FO(-?\d+),', zpl)]


def _y(zpl):
    return [int(v) for v in re.findall(r'\^FO-?\d+,(-?\d+)', zpl)]


def _dol_pol(zpl):
    """Dolna krawędź każdego pola: tekst (wysokość czcionki), ramka (^GB) i QR (21 modułów —
    krótki kod paczki mieści się w wersji 1)."""
    doly = []
    for y, tresc in re.findall(r'\^FO-?\d+,(-?\d+)(.*)', zpl):
        y = int(y)
        if '^A0N,' in tresc:
            doly.append(y + int(re.search(r'\^A0N,(\d+)', tresc).group(1)))
        elif '^GB' in tresc:
            doly.append(y + int(re.search(r'\^GB\d+,(\d+)', tresc).group(1)))
        elif '^BQN' in tresc:
            doly.append(y + 21 * int(re.search(r'\^BQN,2,(\d+)', tresc).group(1)))
    return doly


def _pola_stopki(zpl):
    return [tresc for y, tresc in re.findall(r'\^FO-?\d+,(-?\d+)(.*)', zpl)
            if int(y) >= pl.GORA_STOPKI]


@pytest.mark.parametrize('nazwa, wynik', [
    ('Janusz Testowy', 'Jan*** Tes***'),
    ('Łucja Żak', 'Luc*** Zak'),
    ('Jan Maria Rokita', 'Jan Mar***'),
    ('  TESTBUD   Sp. z o.o. ', 'TES*** Sp.'),
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


def test_numery_pod_numerem_zamowienia_bez_opisow():
    """Pod numerem zamówienia: numer Base. i numer zamówienia klienta, same numery (Konrad 8.10)."""
    zpl = pl.generate_package_label_zpl(_dane())
    assert '^FO32,166^FB396,1,0,L^A0N,28,26^FD12345678 | 1234/2026^FS' in zpl
    assert 'Base.' not in zpl and 'Zam. klienta' not in zpl and 'Bachorz' not in zpl
    assert '^FD1234/2026^FS' in pl.generate_package_label_zpl(_dane(base_id=None))
    assert '^FD12345678^FS' in pl.generate_package_label_zpl(_dane(zamowienie_klienta=None))
    bez_numerow = pl.generate_package_label_zpl(_dane(base_id=None, zamowienie_klienta=None))
    assert ' | ' not in bez_numerow and '^FO32,166' not in bez_numerow


def test_numer_zamowienia_klienta_uciety_do_15_znakow():
    zpl = pl.generate_package_label_zpl(_dane(zamowienie_klienta='A' * 30))
    assert '12345678 | ' + 'A' * 12 + '...' in zpl
    assert 'A' * 13 not in zpl


def test_stopka_3_cm_z_qr_numerami_i_sposobem_dostawy():
    """Stopka w dolnych 3 cm etykiety sama wystarcza do rozpoznania paczki: drugi QR, wszystkie
    numery i pas sposobu dostawy (Konrad 8.10)."""
    zpl = pl.generate_package_label_zpl(_dane(rodzaj='paczka', typ_palety=None, numer=2, z_ilu=3,
                                              sposob='TRASA: Rzeszow 07.10'))
    stopka = '\n'.join(_pola_stopki(zpl))
    assert pl.WYSOKOSC - pl.GORA_STOPKI <= 240          # najwyżej 3 cm od dolnej krawędzi
    assert '^BQN,2,7^FDLA,P-12345^FS' in stopka
    for tekst in ('^FD1450^FS', '^FDPACZKA 2 / 3^FS', '^FDP-12345^FS',
                  '^FD12345678 | 1234/2026^FS', '^FR^FDTRASA: Rzeszow 07.10^FS'):
        assert tekst in stopka, tekst
    assert '^BQN,2,11^FDLA,P-12345^FS' in zpl          # duży QR na środku zostaje


def test_lista_pozycji_nie_wchodzi_na_stopke():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(40)]))
    y_reszty = int(re.search(r'\^FO\d+,(\d+)\^A0N,27,25\^FD\+ ', zpl).group(1))
    assert y_reszty + 27 < pl.GORA_STOPKI


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


def test_dlugi_opis_pozycji_ucina_do_60_znakow():
    # Limit dobrany na wydruku próbnym 2.10 (wiersz z 60 znakami wyglądał najlepiej).
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(
        technologia='mikrowczep', dlugosc_cm=300, szerokosc_cm=65,
        wykonczenie='lakierowane bezbarwne mat olejowosk twardy')]))
    wiersz = re.search(r'\^FD(1\. Dab[^^]*)\^FS', zpl).group(1)
    assert len(wiersz) <= 60  # obcięcie zdejmuje spację przed „...”
    assert wiersz == '1. Dab mikrowczep A/B 300x65x4 cm, lakierowane bezbarwne...'


def test_surowe_bez_dopisku():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(wykonczenie='surowe')]))
    assert 'surowe' not in zpl


def test_11_pozycji_miesci_sie_cala_lista():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(11)]))
    assert '11. Dab' in zpl and 'pozycji (' not in zpl


def test_12_pozycji_ucina_do_10_i_dopisuje_reszte():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja(ilosc=1) for _ in range(12)]))
    assert '10. Dab' in zpl and '11. Dab' not in zpl
    assert '+ 2 pozycji (2 szt.) - pelna lista w CRM' in zpl


def test_tresc_miesci_sie_w_marginesach():
    zpl = pl.generate_package_label_zpl(_dane(pozycje=[_pozycja() for _ in range(40)]))
    assert min(_x(zpl)) >= pl.MARGINES
    assert min(_y(zpl)) >= pl.MARGINES
    assert max(_dol_pol(zpl)) <= pl.WYSOKOSC - pl.MARGINES


def test_dane_nie_wstrzykuja_komend_zpl():
    zpl = pl.generate_package_label_zpl(_dane(sposob='TRASA: ^XZ~JA', zamowienie_klienta='12^FS',
                                              odbiorca='^Jan ~Nowak', numer_zamowienia='14~50'))
    assert zpl.count('^XZ') == 1 and '~' not in zpl


def test_dlugi_numer_zamowienia_mniejsza_czcionka():
    assert '^A0N,116,100^FD1450^FS' in pl.generate_package_label_zpl(_dane())
    assert '^A0N,92,76^FD123456^FS' in pl.generate_package_label_zpl(_dane(numer_zamowienia='123456'))


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


def test_numer_base_jako_liczba():
    """Numer Base. idzie do ZPL przez int() — pole przyjmuje tylko liczbę."""
    assert '^FD12345678 | 1234/2026^FS' in pl.generate_package_label_zpl(_dane())
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
