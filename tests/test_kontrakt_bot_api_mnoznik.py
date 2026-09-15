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
    AUTO_MULTIPLIER_OD_PROGU, auto_multiplier_for_base,
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


def test_regula_slowna_zgodna_z_kodem():
    """Sekcja 0 podaje progi takze slownie — te liczby tez musza sie zgadzac."""
    tresc = _dokument()
    prog = int(AUTO_MULTIPLIER_PROG_NETTO)
    assert f'poniżej {prog} zł netto** → mnożnik **{AUTO_MULTIPLIER_PONIZEJ_PROGU}' in tresc
    assert f'od {prog} zł netto** → mnożnik **{AUTO_MULTIPLIER_OD_PROGU}' in tresc
    # regula opisana slownie musi odpowiadac temu, co faktycznie robi kod
    assert auto_multiplier_for_base(prog - 0.01) == AUTO_MULTIPLIER_PONIZEJ_PROGU
    assert auto_multiplier_for_base(prog) == AUTO_MULTIPLIER_OD_PROGU


def test_dokument_ostrzega_o_uskoku_na_progu():
    """Uskok (wiekszy blat tanszy) to niespodzianka dla konfiguratora sklepu —
    ostrzezenie ma zostac w dokumencie, nawet jesli ktos bedzie go skracal."""
    tresc = _dokument().lower()
    assert 'uskok' in tresc
    assert 'tańszy' in tresc or 'tanszy' in tresc


def test_dokument_zabrania_duplikowania_mnoznika_w_sklepie():
    """Sedno kontraktu: modul Presty nie trzyma wlasnego mnoznika."""
    tresc = _dokument()
    assert 'CRM jest jedynym źródłem prawdy o cenie' in tresc
    assert 'auto_multiplier: false' in tresc   # furtka na okres przejsciowy
