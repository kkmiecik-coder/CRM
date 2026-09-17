"""Straznik kontraktu cenowego dla sklepu (docs/bot-api-contract.md).

Dokument opisuje zespolowi PrestaShop, jak CRM dobiera mnoznik marzy. Sklep ma
NIE trzymac tych liczb u siebie, ale i tak je czyta, zeby je wyswietlic. Gdyby
ktos zmienil progi w kodzie i zapomnial o dokumencie, sklep dostalby sprzeczne
informacje — a nic innego tego dokumentu nie pilnuje.
"""
import io
import os
import re

from modules.calculator.services.pricing_service import (
    AUTO_MULTIPLIER_PROG_NETTO, AUTO_MULTIPLIER_PONIZEJ_PROGU,
    AUTO_MULTIPLIER_OD_PROGU,
    auto_multiplier_for_base,
)

SCIEZKA_DOKUMENTU = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'bot-api-contract.md',
)


def _dokument():
    return io.open(SCIEZKA_DOKUMENTU, encoding='utf-8').read()


def test_dokument_kontraktu_istnieje():
    assert os.path.exists(SCIEZKA_DOKUMENTU), (
        'Zniknal kontrakt dla sklepu — sklep nie ma skad wziac zasad cenowych.')


def test_progi_w_dokumencie_zgodne_z_kodem():
    tresc = _dokument()
    blok = re.search(r'"auto_multiplier":\s*\{(.+?)\}', tresc, re.S)
    assert blok, 'Brak przykladu auto_multiplier w sekcji /options'
    wnetrze = blok.group(1)
    assert f'"prog_netto": {AUTO_MULTIPLIER_PROG_NETTO}' in wnetrze
    assert f'"ponizej_progu": {AUTO_MULTIPLIER_PONIZEJ_PROGU}' in wnetrze
    assert f'"od_progu": {AUTO_MULTIPLIER_OD_PROGU}' in wnetrze
    # Klucz cena_progowa_netto zniknal razem z plateau (2026-09-15). Gdyby wrocil
    # do dokumentu, sklep zaczalby czytac pole, ktorego /options juz nie zwraca.
    assert 'cena_progowa_netto' not in wnetrze


def test_regula_slowna_zgodna_z_kodem():
    """Sekcja 0 podaje progi takze slownie — te liczby tez musza sie zgadzac."""
    tresc = _dokument()
    prog = int(AUTO_MULTIPLIER_PROG_NETTO)
    assert f'poniżej {prog} zł netto** → mnożnik **{AUTO_MULTIPLIER_PONIZEJ_PROGU}' in tresc
    assert f'→ mnożnik **{AUTO_MULTIPLIER_OD_PROGU}' in tresc
    # regula opisana slownie musi odpowiadac temu, co faktycznie robi kod
    assert auto_multiplier_for_base(prog - 0.01) == AUTO_MULTIPLIER_PONIZEJ_PROGU
    assert auto_multiplier_for_base(prog) == AUTO_MULTIPLIER_OD_PROGU


def test_dokument_ostrzega_ze_cena_moze_spasc_na_progu():
    """To jest TERAZ niespodzianka dla konfiguratora: szerszy produkt bywa tanszy
    od wezszego, gdy przekroczy prog. Zaakceptowane biznesowo (2026-09-15), ale
    sklep musi o tym wiedziec, zeby nie zglaszal tego jako bledu CRM.

    Wczesniej dokument obiecywal cos odwrotnego (plateau, "cena nigdy nie spada").
    Ta asercja pilnuje, ze obietnica nie wroci do dokumentu bez powrotu do kodu."""
    tresc = _dokument()
    assert 'może być tańszy' in tresc
    # Pilnujemy OBIETNICY, nie slowa "plateau" — notka historyczna z tym terminem
    # ma prawo zostac, bo wlasnie po nim ktos bedzie kiedys szukal wyjasnienia.
    assert 'nigdy nie spadła przy' not in tresc, (
        'dokument znowu obiecuje, ze cena nie spada — kod tego nie robi')


def test_uskok_faktycznie_wystepuje_w_kodzie():
    """Dokument mowi sklepowi, ze cena potrafi spasc na progu. To musi byc prawda,
    inaczej kontrakt klamie — tak samo jak klamal, gdy obiecywal plateau."""
    tuz_ponizej = (AUTO_MULTIPLIER_PROG_NETTO - 0.01) * auto_multiplier_for_base(
        AUTO_MULTIPLIER_PROG_NETTO - 0.01)
    na_progu = AUTO_MULTIPLIER_PROG_NETTO * auto_multiplier_for_base(
        AUTO_MULTIPLIER_PROG_NETTO)
    assert tuz_ponizej > na_progu

    # ...i zadnego trzeciego pasma: mnoznik to zawsze dokladnie jedna z dwoch stawek
    baza = 1.0
    while baza <= 3000.0:
        assert auto_multiplier_for_base(baza) in (
            AUTO_MULTIPLIER_PONIZEJ_PROGU, AUTO_MULTIPLIER_OD_PROGU), baza
        baza += 0.5


def test_dokument_zabrania_duplikowania_mnoznika_w_sklepie():
    """Sedno kontraktu: modul Presty nie trzyma wlasnego mnoznika."""
    tresc = _dokument()
    assert 'CRM jest jedynym źródłem prawdy o cenie' in tresc
    assert 'auto_multiplier: false' in tresc   # furtka na okres przejsciowy
