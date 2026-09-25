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


# ── R10 (kontroler): adres dla geokodera — oznaczenie lokalu nie może udawać numeru domu ──
# Zmierzone 25.09.2026: „Kraków, Floriańska 10 lok 5” → GUGiK oddawał Floriańską 5
# (accuracy 0.74) i geokoder zapisywał zły budynek jako „dokladna”.

@pytest.mark.parametrize('adres, miasto, numer, ulica', [
    ('Floriańska 10 lok. 5', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10 lok 5', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10 mieszk. 5', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10 mieszkanie 5', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10, m. 5', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 5, lokal 3', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 kl. 2', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 klatka 2', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 p. 2', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 piętro 2', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 apt. 4', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 LOK. 4', 'Kraków', '5', 'Floriańska'),
    ('Floriańska 5 kl. 2 m. 7', 'Kraków', '5', 'Floriańska'),
    ('Długa 12 lok. U2', 'Kraków', '12', 'Długa'),
    ('Floriańska 12/14 m. 3', 'Kraków', '12', 'Floriańska'),
    ('Floriańska 10/5, 31-021 Kraków', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10 m. 5, Kraków', 'Kraków', '10', 'Floriańska'),
    ('Floriańska 10, KRAKÓW ', ' kraków ', '10', 'Floriańska'),
    ('Parkowa 3', 'Rzeszów', '3', 'Parkowa'),
    ('Kolejowa 7 m 2', 'Rzeszów', '7', 'Kolejowa'),
    ('Plac Kościuszki 1/2', 'Rzeszów', '1', 'Plac Kościuszki'),
    ('Floriańska 12 B', 'Kraków', '12B', 'Floriańska'),
    ('Floriańska 12 B m. 3', 'Kraków', '12B', 'Floriańska'),
])
def test_adres_do_geokodowania_daje_numer_budynku(adres, miasto, numer, ulica):
    wynik = adresy.extract_house_and_apartment_number(adresy.adres_do_geokodowania(adres, miasto))
    assert (wynik[0], wynik[2]) == (numer, ulica)


@pytest.mark.parametrize('adres, miasto, oczekiwane', [
    ('Floriańska 10 lok. 5', 'Kraków', 'Floriańska 10'),
    ('Floriańska 10/5, 31-021 Kraków', 'Kraków', 'Floriańska 10/5'),
    ('36-068 Bachórz 14N', 'Bachórz', 'Bachórz 14N'),
    # Inne miasto niż w zamówieniu — to nie jest powtórzona miejscowość, zostaje.
    ('Floriańska 10, Kraków', 'Wieliczka', 'Floriańska 10, Kraków'),
    # Granice słów: końcówki nazw ulic nie są oznaczeniami lokalu.
    ('Parkowa 3', 'Rzeszów', 'Parkowa 3'),
    ('Kolejowa 7', 'Rzeszów', 'Kolejowa 7'),
    ('Plac Kościuszki 1/2', 'Rzeszów', 'Plac Kościuszki 1/2'),
    ('Mickiewicza 12 B', 'Kraków', 'Mickiewicza 12B'),
    ('Mickiewicza 12 b/4', 'Kraków', 'Mickiewicza 12b/4'),
    ('', 'Kraków', ''),
    (None, 'Kraków', ''),
    # Dopiski w nawiasie (zmierzone 25.09.2026 na zamówieniach z listy logistyki).
    ('Handlowa 2a (fizjosfera)', 'Białystok', 'Handlowa 2a'),
    ('Józefowska 19 (dom z czerwonej cegły)', 'Opole Lubelskie', 'Józefowska 19'),
    ('(biuro) Floriańska 10', 'Kraków', 'Floriańska 10'),
])
def test_adres_do_geokodowania(adres, miasto, oczekiwane):
    assert adresy.adres_do_geokodowania(adres, miasto) == oczekiwane


def test_eksport_routimo_bez_zmian():
    """R10: nowa funkcja jest tylko dla geokodera — rozbijanie adresu dla Routimo zostaje 1:1."""
    assert adresy.extract_house_and_apartment_number('Floriańska 10 lok. 5') == (
        '5', '', 'Floriańska 10 lok')
