# -*- coding: utf-8 -*-
"""Panel Logistyki po kroku 4.3 (spec 11): etap po spakowaniu, paczki, problem, filtry
„Do weryfikacji”, „Problem”, „Bez paczek”."""
import os
import re
from datetime import timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import lista
from modules.production.models import ProductionPackage, get_local_now
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(KORZEN, 'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(LOG, *czesci), encoding='utf-8') as f:
        return f.read()


def _spakowane(sposob=s.KURIER, statusy=('spakowane',), dni_temu=0, zamkniete=False, paczek=0, **kolumny):
    teraz = get_local_now()
    order = zamowienie(sposob=sposob, statusy=statusy,
                       logistics_closed_at=teraz if zamkniete else None, **kolumny)
    for p in order.products:
        p.packaging_completed_at = teraz - timedelta(days=dni_temu)
    if paczek:
        order.packages_declared_at = teraz
        db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=teraz,
                                              verified_at=teraz if i == 1 else None)
                            for i in range(1, paczek + 1)])
    db.session.commit()
    return order


@pytest.mark.parametrize('status, nazwa', [
    ('spakowane', u'Spakowane — czeka na weryfikację'), ('zweryfikowane', 'Zweryfikowane'),
    ('zaladowane', u'Załadowane'), ('dostarczone', 'Dostarczone')])
def test_etap_po_spakowaniu(app, status, nazwa):
    wiersz = lista.serializuj(zamowienie(statusy=(status,)))
    assert wiersz['etap'] == {'status': status, 'nazwa': nazwa}


def test_etap_zamowienia_to_najbardziej_zalegla_pozycja(app):
    wiersz = lista.serializuj(zamowienie(statusy=('zweryfikowane', 'spakowane', 'dostarczone')))
    assert wiersz['etap']['status'] == 'spakowane'


def test_paczki_problem_i_bez_paczek_w_wierszu(app):
    teraz = get_local_now()
    z_paczkami = _spakowane(paczek=2, problem_reason='uszkodzenie', problem_note=u'róg', problem_at=teraz)
    wiersz = lista.serializuj(z_paczkami)
    assert wiersz['paczki'] == {'opis': u'2 × paczka', 'liczba': 2, 'zweryfikowane': 1}
    assert wiersz['problem'] == {'powod': 'uszkodzenie', 'etykieta': 'Uszkodzenie', 'notatka': u'róg',
                                 'kiedy': teraz.isoformat()}
    assert wiersz['bez_paczek'] is False
    bez = lista.serializuj(_spakowane())
    assert (bez['paczki'], bez['bez_paczek'], bez['problem']) == (None, True, None)
    w_produkcji = lista.serializuj(zamowienie(statusy=('czeka_na_pakowanie',)))
    assert w_produkcji['bez_paczek'] is False


def test_filtry_weryfikacji(app, client):
    teraz = get_local_now()
    do_weryfikacji = _spakowane(zamkniete=True, paczek=1)           # kurier zamknięty, świeży
    bez_paczek = _spakowane(sposob=s.TRANSPORT)                      # otwarty, bez deklaracji
    stare = _spakowane(zamkniete=True, dni_temu=12)                  # poza oknem
    problem = _spakowane(statusy=('zweryfikowane',), paczek=1, problem_reason='etykieta', problem_at=teraz)
    numery = lambda stan: {w['numer'] for w in client.get(BASE + '/orders?stan=' + stan).get_json()['orders']}
    assert numery('do_weryfikacji') == {do_weryfikacji.internal_order_number, bez_paczek.internal_order_number}
    assert numery('bez_paczek') == {bez_paczek.internal_order_number}
    assert numery('problem') == {problem.internal_order_number}
    assert stare.internal_order_number not in numery('do_weryfikacji')
    dane = client.get(BASE + '/orders').get_json()
    assert dane['weryfikacja'] == {'do_weryfikacji': 2, 'problem': 1, 'bez_paczek': 1}


def test_nieznany_stan_422(app, client):
    assert client.get(BASE + '/orders?stan=pogoda').status_code == 422


def test_front_zna_nowe_etapy_i_filtry():
    js = _plik('static', 'js', 'logistics.js')
    kolejnosc = re.search(r"KOLEJNOSC_ETAPOW = \[([^\]]*)\]", js).group(1)
    wartosci = re.findall(r"'(\w+)'", kolejnosc)
    i = wartosci.index('spakowane')
    assert wartosci[i:i + 4] == list(s.STATUSY_PO_SPAKOWANIU)
    assert re.search(r"const STATUSY_PO_SPAKOWANIU = \['spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone'\]", js)
    for plik in ('logistics.js', 'logistics-map.js', 'logistics-routes.js'):
        tresc = _plik('static', 'js', plik)
        assert not re.search(r"(etap\.status|status)\s*===\s*'spakowane'", tresc), plik
    assert "params.set('stan'" in js
    szablon = _plik('templates', 'logistics', 'tab_content.html')
    for stan in ('do_weryfikacji', 'problem', 'bez_paczek'):
        assert 'data-lg-stan="%s"' % stan in szablon, stan
    css = _plik('static', 'css', 'logistics.css')
    for status in s.STATUSY_LOGISTYCZNE:
        assert '[data-etap="%s"]' % status in css, status


def test_endpoint_listy_ma_stala_liczbe_zapytan(app, client):
    """Paczki, problem i liczniki Weryfikacji mają stały koszt: liczba zapytań endpointu nie rośnie
    z liczbą wierszy (paczki jednym zapytaniem na listę, liczniki to trzy COUNT-y)."""
    from sqlalchemy import event

    def zapytania(adres):
        db.session.expire_all()
        licznik = []
        sluchacz = lambda *a, **k: licznik.append(1)  # noqa: E731
        event.listen(db.engine, 'before_cursor_execute', sluchacz)
        try:
            assert client.get(adres).status_code == 200
        finally:
            event.remove(db.engine, 'before_cursor_execute', sluchacz)
        return len(licznik)

    teraz = get_local_now()
    for _ in range(2):
        _spakowane(paczek=2, problem_reason='inne', problem_at=teraz)
    for adres in (BASE + '/orders', BASE + '/orders?stan=do_weryfikacji', BASE + '/orders?stan=problem'):
        zapytania(adres)            # rozgrzewka: pierwsze żądanie dokłada jednorazowe odczyty (np. sprawdzenie tabel)
        male = zapytania(adres)
        for _ in range(6):
            _spakowane(paczek=2, problem_reason='inne', problem_at=teraz)
        assert zapytania(adres) == male, adres


def test_filtr_weryfikacji_laczy_sie_z_wyszukiwarka_i_sposobem(app, client):
    """Filtr `stan` zostaje filtrem SQL przed limitem: q i sposob zawężają wynik, a zamkniete=1
    nie obcina go do LIMIT_ZAMKNIETYCH."""
    a = _spakowane(sposob=s.KURIER, zamkniete=True, paczek=1)
    b = _spakowane(sposob=s.TRANSPORT, paczek=1)
    numery = lambda zapytanie: {w['numer'] for w in client.get(BASE + '/orders?' + zapytanie).get_json()['orders']}  # noqa: E731
    assert numery('stan=do_weryfikacji&sposob=' + s.KURIER) == {a.internal_order_number}
    assert numery('stan=do_weryfikacji&q=' + b.internal_order_number) == {b.internal_order_number}
    assert numery('stan=do_weryfikacji&zamkniete=1&q=' + a.internal_order_number) == {a.internal_order_number}


def test_front_filtry_weryfikacji_w_logice_listy():
    js = _plik('static', 'js', 'logistics.js')
    # Przyciski filtrów idą własną gałęzią kliknięcia (nie przez data-lg-sposob) i wykluczają się.
    assert "e.target.closest('[data-lg-stan]')" in js
    assert 'stan.filtr.stan === nowy ? \'\' : nowy' in js
    # „Zdejmij filtry” i pusty stan listy znają nowy filtr, widok zawężony także.
    zdejmij = js[js.index('function zdejmijFiltry'):]
    assert "stan.filtr.stan = ''" in zdejmij[:zdejmij.index('\n    }\n')]
    assert 'PUSTE_STANY[f.stan]' in js and "case 'zdejmij-stan'" in js
    assert 'stan.filtr.stan);' in js[js.index('const zawezonyWidok'):js.index('const bezGeoWWidoku')]
    # Liczby przy filtrach z odpowiedzi listy, a problem ma ikonę z dymkiem „Problem: …”.
    assert 'stan.weryfikacja = dane.weryfikacja' in js
    assert "ikona('fa-triangle-exclamation', 'lg-ikona--problem', opisProblemu(w.problem))" in js
    assert "'Problem: '" in js
