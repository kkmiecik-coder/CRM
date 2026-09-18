# -*- coding: utf-8 -*-
"""
Widget „Przegląd produkcji" na dashboardzie głównym.

chart_service.get_production_overview() trzyma JEDYNĄ w aplikacji mapę statusów
produkcji całkowicie odciętą od station_catalog — moduł dashboardu celowo nie
importuje modułu produkcji, więc nic nie pilnuje zgodności tych dwóch list.

Brakujący klucz nie wywala wykresu: segment dostaje SUROWY enum jako nazwę
('czeka_na_krawedzie' w legendzie) i szary kolor rezerwowy #94a3b8. Psuje się
po cichu, dlatego mapa potrzebuje testu, a nie tylko komentarza.

UWAGA przy pisaniu asercji: kolor rezerwowy #94a3b8 jest IDENTYCZNY z kolorem
przypisanym 'czeka_na_wyciecie', więc „brak koloru rezerwowego w wyniku" nie
jest wiarygodnym sitem. Sprawdzamy dokładną mapę nazwa → kolor.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.dashboard.services import chart_service
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession,
)
from modules.production.services.station_catalog import STATION_PENDING_STATUS
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

_licznik_zamowien = [0]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


def _produkt(status):
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=1, volume_m3=0.5, current_status=status,
        created_at=datetime(2026, 8, 10, 9, 0))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_kazda_kolejka_stanowiska_ma_polska_nazwe(app):
    """
    Sygnatura brakującego klucza jest jednoznaczna: nazwą segmentu staje się
    surowy enum. Test porównuje zbiór nazw ze zbiorem enumów — przecięcie musi
    być puste.
    """
    with app.app_context():
        for status in STATION_PENDING_STATUS.values():
            _produkt(status)

        dane = chart_service.get_production_overview()

        nazwy = {s['name'] for s in dane['statuses']}
        assert not (nazwy & set(STATION_PENDING_STATUS.values())), nazwy
        assert len(nazwy) == len(STATION_PENDING_STATUS)
        assert dane['total_items'] == len(STATION_PENDING_STATUS)


def test_krawedzie_lakiernia_i_logistyka_maja_wlasne_nazwy_i_kolory(app):
    """
    Trzy segmenty, które po zmianie trasy urosną: Krawędzie (nowa nazwa),
    Lakiernia i Logistyka (dziś w ogóle nieznane tej mapie).
    """
    with app.app_context():
        _produkt('czeka_na_krawedzie')
        _produkt('czeka_na_lakiernie')
        _produkt('czeka_na_logistyke')

        dane = chart_service.get_production_overview()

        assert {s['name']: s['color'] for s in dane['statuses']} == {
            'Czeka na krawędzie': '#06b6d4',
            'Czeka na lakiernię': '#ec4899',
            'Czeka na logistykę': '#0d9488',
        }


# ============================================================================
# ROZROZNIALNOSC KOLOROW SEGMENTOW
# ============================================================================

# Prog odleglosci barw w przestrzeni CIE Lab (wzor CIE76). Dla orientacji:
# ~2,3 to granica dostrzegalnosci dwoch probek obok siebie, a segmenty kola
# leza obok siebie tylko czasem — stad prog znacznie wyzszy.
#
# 25 to najnizsza okragla wartosc, ktora LAPIE kolizje, dla ktorej ten test
# powstal: 'czeka_na_lakiernie' #e11d48 i 'anulowane' #ef4444 dzielilo 13,90,
# czyli dwa czerwone segmenty nie do odroznienia — a jeden znaczyl
# „w produkcji", drugi „anulowane".
PROG_ROZROZNIALNOSCI = 25.0

# Dwie pary siedza ponizej progu OD DAWNA, sprzed rozdzielenia Wykanczania,
# i nie sa przedmiotem tej naprawy: bursztyn/zolc kolejki pakowania obok
# „W realizacji" (16,42) oraz dwa odcienie slate wycinania i skladania
# (18,25). Sa wypisane imiennie, zeby test mowil prawde o stanie mapy
# zamiast udawac, ze prog trzyma wszedzie.
#
# TA LISTA NIE MA ROSNAC. Nowy status dokladany do mapy ma trafic w wolne
# miejsce na kole barw, a nie dopisac sie tutaj.
PARY_HISTORYCZNE = {
    frozenset(('Czeka na pakowanie', 'W realizacji')),
    frozenset(('Czeka na wycięcie', 'Czeka na składanie')),
}


def _lab(hex_koloru):
    """#RRGGBB -> (L*, a*, b*). sRGB D65, bez zadnej biblioteki zewnetrznej."""
    h = hex_koloru.lstrip('#')
    kanaly = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    kanaly = [k / 12.92 if k <= 0.04045 else ((k + 0.055) / 1.055) ** 2.4
              for k in kanaly]
    r, g, b = kanaly
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722)
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t):
        return t ** (1 / 3.0) if t > 0.008856 else (7.787 * t + 16 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _odleglosc(a, b):
    """Odleglosc euklidesowa w Lab (CIE76) miedzy dwoma kolorami #RRGGBB."""
    return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** 0.5


def test_segmenty_przegladu_produkcji_daja_sie_rozroznic_kolorem(app):
    """
    Wykres kolowy „Przeglad produkcji" rysuje kazdy status wlasnym kolorem
    i tylko kolor mowi, ktory segment jest ktory. Sama roznica hexow tego
    NIE gwarantuje: do tej rundy lakiernia miala #e11d48, a anulowane
    #ef4444 — dwa rozne literaly, jeden krok odcienia, a na zywych danych
    oba segmenty niepuste (21 i 7 sztuk).

    Test przechodzi po WSZYSTKICH wartosciach enuma statusu, a nie po liscie
    wpisanej z palca, wiec kolejny status dolozony do produkcji zapali go sam.
    Status bez wpisu w mapie dostaje kolor rezerwowy #94a3b8 — identyczny
    z 'czeka_na_wyciecie' — wiec wpada juz w pierwsza asercje.

    chart_service lezy poza modules/production, wiec nie obejmuje go straznik
    literalu 'finishing' ani zaden inny test katalogu stanowisk.
    """
    import itertools

    with app.app_context():
        statusy = ProductionProduct.__table__.c.current_status.type.enums
        for status in statusy:
            _produkt(status)

        dane = chart_service.get_production_overview()
        kolory = {s['name']: s['color'] for s in dane['statuses']}
        assert len(kolory) == len(statusy), kolory

        powtorzone = sorted(
            nazwa for nazwa, kolor in kolory.items()
            if list(kolory.values()).count(kolor) > 1)
        assert powtorzone == [], (
            'Segmenty dzielace ten sam kolor (albo brak wpisu w mapie): {}'
            .format(powtorzone))

        zbyt_blisko = []
        for (na, ka), (nb, kb) in itertools.combinations(kolory.items(), 2):
            if frozenset((na, nb)) in PARY_HISTORYCZNE:
                continue
            odleglosc = _odleglosc(ka, kb)
            if odleglosc < PROG_ROZROZNIALNOSCI:
                zbyt_blisko.append('{} ({}) vs {} ({}): {:.2f}'
                                   .format(na, ka, nb, kb, odleglosc))
        assert zbyt_blisko == [], (
            'Segmenty nie do odroznienia na wykresie (prog {}): {}'
            .format(PROG_ROZROZNIALNOSCI, zbyt_blisko))

        # Para historyczna, ktora znika z mapy, ma zniknac takze z listy
        # wyjatkow — inaczej lista zgnije i przestanie cokolwiek znaczyc.
        nazwy = set(kolory)
        martwe = sorted(''.join(sorted(para)) for para in PARY_HISTORYCZNE
                        if not para <= nazwy)
        assert martwe == [], (
            'PARY_HISTORYCZNE wymienia segmenty, ktorych juz nie ma: {}'
            .format(martwe))


# ============================================================================
# CZWARTA MAPA KOLOROW — SZABLON RAPORTU MIX
# ============================================================================

# Ta mapa zyje w JavaScripcie wewnatrz szablonu Jinja modulu produkcji
# (components/reports/mix.html), a nie w Pythonie, wiec zaden straznik
# katalogu stanowisk jej nie widzi. Test siedzi TUTAJ, a nie w testach
# produkcji, bo tu leza prog rozroznialnosci i przelicznik CIE76 — dwie
# kopie tych samych progow rozjechalyby sie przy pierwszej zmianie.

SZABLON_MIX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'templates', 'components', 'reports', 'mix.html')

# Cztery pary siedza ponizej progu OD DAWNA, sprzed rozdzielenia Wykanczania.
# Jak w PARY_HISTORYCZNE wyzej: TA LISTA NIE MA ROSNAC.
PARY_HISTORYCZNE_MIX = {
    frozenset(('czeka_na_wyciecie', 'czeka_na_pakowanie')),
    frozenset(('czeka_na_skladanie', 'w_realizacji')),
    frozenset(('czeka_na_formatowanie', 'wstrzymane')),
    frozenset(('czeka_na_pakowanie', 'spakowane')),
}


def _mapa_kolorow_mix():
    """Wyciaga colorMap z JS-a w szablonie raportu mix."""
    with open(SZABLON_MIX, encoding='utf-8') as f:
        tresc = f.read()
    blok = tresc.split('const colorMap = {')[1].split('};')[0]
    return dict(re.findall(r"'(\w+)':\s*'(#[0-9a-fA-F]{6})'", blok))


def test_lakiernia_w_raporcie_mix_nie_jest_druga_czerwienia():
    """
    Podzial Wykanczania dolozyl do tej mapy 'czeka_na_lakiernie'. Pierwsza
    wersja dala jej '#e11d48', czyli 18,8 od 'anulowane' — dwa czerwone
    segmenty tego samego kola, jeden znaczacy „w produkcji", drugi
    „anulowane". Na zrzucie produkcji oba byly niepuste (21 i 7 sztuk).

    Straznik literalu chodzi wylacznie po modules/production w Pythonie,
    a ta mapa to JavaScript w szablonie — zadna z pozostalych trzech map
    kolorow nie zlapalaby tej kolizji za nia.
    """
    mapa = _mapa_kolorow_mix()

    assert 'czeka_na_lakiernie' in mapa
    assert 'czeka_na_krawedzie' in mapa

    for nazwa, kolor in mapa.items():
        if nazwa == 'czeka_na_lakiernie':
            continue
        odleglosc = _odleglosc(mapa['czeka_na_lakiernie'], kolor)
        assert odleglosc >= PROG_ROZROZNIALNOSCI, (
            'czeka_na_lakiernie {} i {} {} dzieli tylko {:.2f}'
            .format(mapa['czeka_na_lakiernie'], nazwa, kolor, odleglosc))


def test_mapa_mix_nie_doklada_nowych_kolizji():
    """
    Cztery pary ponizej progu sa zastane i wypisane imiennie. Kazda nowa
    kolizja ma ten test zapalic, zamiast dopisac sie do listy wyjatkow.
    """
    mapa = _mapa_kolorow_mix()
    nazwy = sorted(mapa)

    kolizje = []
    for i, na in enumerate(nazwy):
        for nb in nazwy[i + 1:]:
            if frozenset((na, nb)) in PARY_HISTORYCZNE_MIX:
                continue
            odleglosc = _odleglosc(mapa[na], mapa[nb])
            if odleglosc < PROG_ROZROZNIALNOSCI:
                kolizje.append('{}/{} {:.2f}'.format(na, nb, odleglosc))

    assert kolizje == [], 'nowe kolizje kolorow w mix.html: {}'.format(kolizje)

    martwe = sorted(''.join(sorted(p)) for p in PARY_HISTORYCZNE_MIX
                    if not p <= set(nazwy))
    assert martwe == [], (
        'PARY_HISTORYCZNE_MIX wymienia statusy, ktorych juz nie ma: {}'
        .format(martwe))
