# -*- coding: utf-8 -*-
"""
Stary timer ponowień statusu po stanowisku (baselinker_status_sync) a logistyka
równoległa — przegląd całej gałęzi, pozycja I1.

Pierwsza próba setOrderStatus po stanowisku idzie synchronicznie, a przy błędzie
Base. timer ponawia ją do ~19 min (RETRY_DELAYS_S). Cel policzony przy pierwszej
próbie może się w tym czasie zestarzeć: logistyk zmienia sposób dostawy albo wydaje
zamówienie, a dopychacz logistyki (bl_sync) wysyła już NOWSZY status. Ponowienie ze
starym celem nadpisałoby go w Base. Dlatego każde ponowienie czyta zamówienie od
nowa i pomija wysyłkę, gdy cel przestał być aktualny.

Wywołania Base. i planowanie timera są podmienione: `_schedule_retry` zapisuje
argumenty zamiast uruchamiać wątek, a test sam odpala `_retry_attempt` z tymi
argumentami — tak, jak zrobiłby to threading.Timer.
"""
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, delivery
from modules.production.models import ProductionOrder
from modules.production.services import baselinker_status_sync as bss
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401


@pytest.fixture()
def base(monkeypatch):
    """
    `wyslane` — statusy, które ścieżka timera próbowała wysłać do Base.
    `odpowiedzi` — skrypt wyników kolejnych prób (brak = sukces).
    `zaplanowane` — ponowienia, które zaplanowałby timer (argumenty `_schedule_retry`).
    """
    stan = {'wyslane': [], 'odpowiedzi': [], 'zaplanowane': []}

    def wywolaj(baselinker_order_id, status_id):
        stan['wyslane'].append(status_id)
        return stan['odpowiedzi'].pop(0) if stan['odpowiedzi'] else True

    def zaplanuj(app_, baselinker_order_id, target_status_id, **kwargs):
        stan['zaplanowane'].append(dict(kwargs, baselinker_order_id=baselinker_order_id,
                                        target_status_id=target_status_id))

    monkeypatch.setattr(bss, '_call_set_order_status', wywolaj)
    monkeypatch.setattr(bss, '_schedule_retry', zaplanuj)
    return stan


def _odpal_ponowienie(app, zaplanowane):
    """
    Robi to, co threading.Timer: woła `_retry_attempt` z argumentami, które dostał
    `_schedule_retry` (attempt o jeden większy). UWAGA: `_retry_attempt` otwiera
    własny app_context, a jego teardown zamyka sesję — obiekty wczytane wcześniej
    w teście są potem odłączone, więc po tym wywołaniu tylko czytamy `base`.
    """
    kwargs = {k: v for k, v in zaplanowane.items()
              if k not in ('attempt', 'baselinker_order_id', 'target_status_id')}
    bss._retry_attempt(app=app, baselinker_order_id=zaplanowane['baselinker_order_id'],
                       target_status_id=zaplanowane['target_status_id'],
                       attempt=zaplanowane['attempt'] + 1, **kwargs)


def _pierwsza_proba_pada(app, base, order, stanowisko):
    """Pierwsza (synchroniczna) próba po stanowisku pada → timer planuje ponowienie."""
    base['odpowiedzi'] = [False]
    bss._process_pending(app, order.internal_order_number, stanowisko)
    assert len(base['zaplanowane']) == 1
    return base['zaplanowane'][0]


# ── I1a: ponowienie czyta zamówienie od nowa ───────────────────────────────

def test_ponowienie_po_zmianie_sposobu_nie_wysyla_starego_celu(app, base):
    """Sonda P4: kurier spakowany, 1. próba pada (cel 138623); logistyk zmienia na
    odbiór, dopychacz wysyła 149777 i czyści znacznik. Ponowienie NIE może wysłać
    138623 na wierzch 149777."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        plan = _pierwsza_proba_pada(app, base, order, 'packaging')
        assert plan['target_status_id'] == s.STATUS_SPAKOWANE

        delivery.ustaw_sposob_dostawy(order, s.ODBIOR)
        db.session.commit()
        assert order.bl_status_pending_id == s.STATUS_CZEKA_NA_ODBIOR
        order.bl_status_pending_id = None  # dopychacz wysłał 149777 i wyczyścił znacznik
        db.session.commit()

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_SPAKOWANE]  # tylko nieudana 1. próba
    assert len(base['zaplanowane']) == 1  # pominięte ponowienie nie planuje kolejnego


def test_ponowienie_po_wydaniu_klientowi_nie_nadpisuje_149779(app, base):
    """Odbiór spakowany przy wolnym Base.: 1. próba (149777) pada, logistyk klika
    „Wydane klientowi”, dopychacz wysyła 149779. Ponowienie 149777 byłoby na wierzchu."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        plan = _pierwsza_proba_pada(app, base, order, 'packaging')
        assert plan['target_status_id'] == s.STATUS_CZEKA_NA_ODBIOR

        delivery.wydaj_klientowi(order)
        db.session.commit()
        order.bl_status_pending_id = None  # dopychacz wysłał 149779
        db.session.commit()

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_CZEKA_NA_ODBIOR]


def test_ponowienie_pomija_status_nalezacy_do_dopychacza(app, base):
    """Cel się nie zmienił, ale na zamówieniu czeka znacznik statusu logistyki —
    wtedy status należy do dopychacza, a timer się nie wtrąca."""
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        plan = _pierwsza_proba_pada(app, base, order, 'packaging')
        bl_sync.oznacz_wyslane(order)  # furtka kierowcy: znacznik 149763
        db.session.commit()

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_PLANOWANA_TRASA]


def test_ponowienie_138620_po_spakowaniu_jest_pomijane(app, base):
    """„Produkcja zakończona” ponawiana po tym, jak pakowacz spakował całe zamówienie
    (i poszedł status po spakowaniu), cofnęłaby Base. do 138620."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        plan = _pierwsza_proba_pada(app, base, order, 'edges')
        assert plan['target_status_id'] == s.STATUS_PRODUKCJA_ZAKONCZONA

        order.products[0].complete_task('packaging')
        db.session.commit()
        bss._process_pending(app, order.internal_order_number, 'packaging')
        assert base['wyslane'][-1] == s.STATUS_SPAKOWANE

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_PRODUKCJA_ZAKONCZONA, s.STATUS_SPAKOWANE]


def test_ponowienie_pomijane_gdy_warunek_stanowiska_przestal_obowiazywac(app, base):
    """Base. dołożył pozycję do spakowanego zamówienia — „spakowane” już nieprawdziwe."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        plan = _pierwsza_proba_pada(app, base, order, 'packaging')
        produkt(order, status='czeka_na_wyciecie')
        db.session.commit()

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_SPAKOWANE]


def test_aktualne_ponowienie_nadal_wysyla_i_przy_bledzie_planuje_kolejne(app, base):
    """Regresja mechanizmu timera (spec 6.3: ponawianie zostaje): cel wciąż aktualny →
    ponowienie wysyła; kolejny błąd → następne ponowienie z tym samym stanowiskiem."""
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        plan = _pierwsza_proba_pada(app, base, order, 'packaging')
        base['odpowiedzi'] = [False]

        _odpal_ponowienie(app, plan)
    assert base['wyslane'] == [s.STATUS_PLANOWANA_TRASA, s.STATUS_PLANOWANA_TRASA]
    assert len(base['zaplanowane']) == 2
    drugi = base['zaplanowane'][1]
    assert drugi['target_status_id'] == s.STATUS_PLANOWANA_TRASA
    assert drugi['attempt'] == 1
    assert drugi.get('station_code') == 'packaging'


# ── I1b: pozycje anulowane nie blokują statusu po stanowisku ────────────────

@pytest.mark.parametrize('sposob, statusy, stanowisko, cel', [
    # Sonda P6: odbiór z jedną anulowaną pozycją nigdy nie dostawał 149777.
    (s.ODBIOR, ('anulowane', 'spakowane'), 'packaging', s.STATUS_CZEKA_NA_ODBIOR),
    (s.KURIER, ('anulowane', 'czeka_na_pakowanie'), 'edges', s.STATUS_PRODUKCJA_ZAKONCZONA),
])
def test_anulowana_pozycja_nie_blokuje_statusu(app, base, sposob, statusy, stanowisko, cel):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=statusy)
        bss._process_pending(app, order.internal_order_number, stanowisko)
    assert base['wyslane'] == [cel]


@pytest.mark.parametrize('stanowisko', ['packaging', 'edges'])
def test_zamowienie_w_calosci_anulowane_nie_dostaje_statusu(app, base, stanowisko):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('anulowane', 'anulowane'))
        bss._process_pending(app, order.internal_order_number, stanowisko)
    assert base['wyslane'] == []


# ── I1c: odbiór już wydany — 149779 jest ostateczny ─────────────────────────

def test_pakowanie_po_wydaniu_nie_wysyla_statusu_po_spakowaniu(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        delivery.wydaj_klientowi(order)
        db.session.commit()
        bss._process_pending(app, order.internal_order_number, 'packaging')
        assert ProductionOrder.query.get(order.id).handed_over_at is not None
    assert base['wyslane'] == []
