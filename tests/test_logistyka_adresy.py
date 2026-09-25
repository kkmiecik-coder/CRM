# -*- coding: utf-8 -*-
import pytest

from modules.production.logistics import adresy


@pytest.mark.parametrize('adres, oczekiwane', [
    ('ul. Floriańska 10/5', ('10', '5', 'Floriańska')),
    ('Floriańska 10 m. 5', ('10', '5', 'Floriańska')),
    ('al. Tadeusza Rejtana 16C', ('16C', '', 'al. Tadeusza Rejtana')),
    ('Bachórz 14N', ('14N', '', 'Bachórz')),
    ('12/3 Długa', ('12', '3', 'Długa')),
    ('Rynek', ('', '', 'Rynek')),
    ('', ('', '', '')),
])
def test_rozbicie_adresu(adres, oczekiwane):
    assert adresy.extract_house_and_apartment_number(adres) == oczekiwane


def test_raporty_uzywaja_tej_samej_funkcji():
    from modules.reports import routers
    assert routers.extract_house_and_apartment_number is adresy.extract_house_and_apartment_number
    assert routers.clean_street_name is adresy.clean_street_name


@pytest.mark.parametrize('tekst, oczekiwane', [
    ('36-068 Bachórz 14N', 'Bachórz 14N'),
    ('Floriańska 10, 31-021', 'Floriańska 10'),
    ('Floriańska 10', 'Floriańska 10'),
])
def test_usun_kod_pocztowy(tekst, oczekiwane):
    assert adresy.usun_kod_pocztowy(tekst) == oczekiwane
