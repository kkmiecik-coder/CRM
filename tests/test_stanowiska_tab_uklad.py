# -*- coding: utf-8 -*-
"""
Układ zakładki Stanowiska: nagłówek z sumami, podzakładki na stanowisko, panele.

Zakładka ma ten sam wzorzec co „Urządzenia mobilne": przyciski z role="tab", panele
chowane atrybutem `hidden`, wybór pamiętany w sessionStorage. Wszystkie panele są
w HTML od razu (przełącza je JS), więc kontrakty danych sprawdzają inne pliki testów
(test_priorytety_czytelnicy: karta_html po `data-stanowisko`, jedna kropka odłożonych).

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import (  # noqa: F401
    BASE, SZABLON_STANOWISK, app, client, produkt, zrodlo,
)

KOLEJNOSC = ['cutting', 'assembly', 'gluing', 'formatting',
             'edges', 'painting', 'packaging']
EMOJI = (u'🪚', u'🔧', u'🧲', u'📐', u'✨', u'🎨', u'📦')


def _html(client):
    r = client.get(BASE + '/stations-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane['html']


def _wartosc_chipa(html, id_chipa):
    """Tekst wartości chipa z nagłówka (np. „3” albo „0,40 m³”)."""
    wzor = r'id="%s".*?stn-stat-wartosc">\s*([^<]+?)\s*<' % id_chipa
    trafienie = re.search(wzor, html, flags=re.DOTALL)
    assert trafienie, u'brak chipa %s' % id_chipa
    return trafienie.group(1)


def test_kazda_podzakladka_ma_swoj_panel(client, app):
    html = _html(client)
    assert 'role="tablist"' in html
    for kod in KOLEJNOSC:
        assert 'id="stn-sub-%s"' % kod in html, kod
        assert 'aria-controls="stn-panel-%s"' % kod in html, kod
        assert 'id="stn-panel-%s"' % kod in html, kod
        assert 'aria-labelledby="stn-sub-%s"' % kod in html, kod


def test_serwer_pokazuje_tylko_pierwszy_panel(client, app):
    """Bez JS widać jedno stanowisko; reszta jest chowana atrybutem hidden (przełącza je skrypt)."""
    html = _html(client)
    otwarcia = re.findall(r'<section[^>]*data-stanowisko="(\w+)"[^>]*>', html)
    assert otwarcia == KOLEJNOSC
    ukryte = [kod for kod in KOLEJNOSC
              if re.search(r'<section[^>]*data-stanowisko="%s"[^>]*\shidden' % kod, html)]
    assert ukryte == KOLEJNOSC[1:]


def test_naglowek_sumuje_wszystkie_stanowiska(client, app):
    produkt(app, status='czeka_na_krawedzie', numer='25/00001')
    produkt(app, status='czeka_na_krawedzie', numer='25/00002')
    produkt(app, status='czeka_na_lakiernie', numer='25/00003')
    poludnie = datetime.combine(date.today(), time(12, 0))
    produkt(app, status='czeka_na_logistyke', numer='25/00004', edges_completed_at=poludnie)

    html = _html(client)

    assert _wartosc_chipa(html, 'stn-stat-oczekuje') == '3'
    assert _wartosc_chipa(html, 'stn-stat-dzis') == '1'
    # 4 szt. po 0,1 m³; przecinek dziesiętny jak w reszcie panelu
    assert _wartosc_chipa(html, 'stn-stat-objetosc') == u'0,40 m³'
    assert _wartosc_chipa(html, 'stn-stat-odlozone') == '0'
    assert 'stn-stat--uwaga' not in html


def test_sumy_dnia_mowia_ze_licza_przejscia_przez_stanowiska(client, app):
    """„Ukończono dziś” i „Objętość dziś” to suma kolumn domknięć wszystkich stanowisk: wyrób, który dziś
    przeszedł dwa stanowiska, liczy się dwa razy. Etykieta ma to mówić, żeby suma nie uchodziła za liczbę wyrobów."""
    html = _html(client)
    for id_chipa in ('stn-stat-dzis', 'stn-stat-objetosc'):
        chip = re.search(r'<div class="stn-stat[^"]*" id="%s"[^>]*>' % id_chipa, html)
        assert chip, id_chipa
        assert u'liczy się dwa razy' in chip.group(0), id_chipa


def test_bez_emoji_ze_starego_ukladu(client, app):
    html = _html(client)
    for znak in EMOJI:
        assert znak not in html, znak


def test_kazdy_panel_ma_podglad_monitora(client, app):
    assert _html(client).count('Podgląd monitora') == len(KOLEJNOSC)


def test_skrypt_zakladki_nie_ma_const_ani_let_na_najwyzszym_poziomie():
    """Loader podmienia <script> na nowy element, więc skrypt wykonuje się w zasięgu globalnym przy każdym
    odświeżeniu zakładki (co 2 min). Deklaracja const/let na górze rzuciłaby przy drugim wykonaniu
    „already been declared” i cała obsługa zakładki przestałaby działać."""
    skrypt = zrodlo(SZABLON_STANOWISK).split('<script>', 1)[1]
    for linia in skrypt.splitlines():
        assert not re.match(r'(const|let|var)\s', linia), linia


def test_wybor_podzakladki_przezywa_odswiezenie():
    """Odświeżenie co 2 minuty (i po „Zdejmij ze stołu”) podmienia cały HTML; bez zapamiętania wyboru
    biuro wracałoby za każdym razem na pierwsze stanowisko."""
    skrypt = zrodlo(SZABLON_STANOWISK).split('<script>', 1)[1]
    assert 'sessionStorage.setItem(' in skrypt and 'sessionStorage.getItem(' in skrypt
    assert "ev.key === 'ArrowRight'" in skrypt and "ev.key === 'ArrowLeft'" in skrypt
