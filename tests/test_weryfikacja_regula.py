# -*- coding: utf-8 -*-
"""Jedna reguła unieważniania etapów (logistyka etap 4, krok 4.3, spec 4.5 ostatni wiersz i 8.5)."""
from datetime import datetime

from sqlalchemy import event

from extensions import db
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import weryfikacja
from modules.production.models import LabelPrintJob, ProductionOrder, ProductionPackage, ProductionProduct
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401

TERAZ = datetime(2026, 10, 1, 9, 0)
DEKLARACJA = datetime(2026, 9, 30, 15, 0)


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, zweryfikowane=False, **kolumny):
    order = zamowienie(sposob='kurier_baselinker', statusy=statusy,
                       packages_declared_at=DEKLARACJA, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=DEKLARACJA,
                               verified_at=DEKLARACJA if zweryfikowane else None)
             for i in range(1, n + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def test_zamowienie_w_calosci_spakowane_bez_zmian(app):
    order, lista = _z_paczkami()
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert all(p.voided_at is None for p in lista)
    assert order.packages_declared_at == DEKLARACJA and LogisticsLog.query.count() == 0


def test_nowa_pozycja_uniewaznia_paczki_weryfikacje_i_wydruki(app):
    order, lista = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True,
                               verified_at=DEKLARACJA, verified_by_worker_id=7)
    zadanie = LabelPrintJob(printer='wysylka', package_id=lista[0].id, short_product_id=lista[0].kod,
                            zpl_payload='^XA^XZ', station_code='packaging',
                            requested_by_type='device', requested_by_id='TAB-1')
    db.session.add(zadanie)
    produkt(order, status='czeka_na_wyciecie')
    db.session.commit()

    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'nowa pozycja z Base.', user_id=5) is True
    db.session.commit()

    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane', 'czeka_na_wyciecie']
    assert (order.packages_declared_at, order.verified_at, order.verified_by_worker_id) == (None, None, None)
    assert [p.voided_at for p in ProductionPackage.query.filter_by(order_id=order.id)] == [TERAZ, TERAZ]
    wygaszone = LabelPrintJob.query.get(zadanie.id)
    assert wygaszone.status == LabelPrintJob.STATUS_EXPIRED
    assert wygaszone.error_message == u'Paczka unieważniona — nowa pozycja z Base.'
    wpisy = {w.action: w for w in LogisticsLog.query.filter_by(order_id=order.id)}
    assert set(wpisy) == {'paczki', 'weryfikacja_cofnieta'}
    assert (wpisy['paczki'].old_value, wpisy['paczki'].new_value, wpisy['paczki'].note,
            wpisy['paczki'].user_id) == (u'2 × paczka', None, u'nowa pozycja z Base.', 5)
    assert wpisy['weryfikacja_cofnieta'].note == u'nowa pozycja z Base.'
    assert all(p.updated_at == TERAZ for p in order.products)   # ETag kolejek tabletów


def test_dostarczone_zostaja_zaladowane_wracaja(app):
    """Decyzja Konrada 30.09: towar u klienta jest u klienta."""
    order, _ = _z_paczkami(statusy=('dostarczone', 'zaladowane'))
    produkt(order, status='czeka_na_formatowanie')
    db.session.commit()
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'doróbka') is True
    assert [p.current_status for p in order.products] == ['dostarczone', 'spakowane', 'czeka_na_formatowanie']


def test_zamowienie_w_produkcji_bez_paczek_bez_zmian(app):
    order = zamowienie(statusy=('czeka_na_pakowanie', 'spakowane'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert LogisticsLog.query.count() == 0


def test_anulowana_pozycja_nie_wraca_zamowienia(app):
    order, lista = _z_paczkami(statusy=('spakowane', 'anulowane'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert all(p.voided_at is None for p in lista)


def test_pozycje_zweryfikowane_bez_deklaracji_tez_wracaja(app):
    """Stan „zweryfikowane bez paczek” (np. po ręcznej zmianie admina) — reguła i tak go czyści."""
    order = zamowienie(statusy=('zweryfikowane', 'czeka_na_pakowanie'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'zmiana statusu w panelu') is True
    assert order.products[0].current_status == 'spakowane'


def test_bez_zapytan_gdy_nie_ma_czego_kasowac(app):
    """Cron woła regułę dla każdego otwartego zamówienia — bez pracy ma nie pytać bazy."""
    zamowienia = [zamowienie(statusy=('czeka_na_wyciecie', 'spakowane')) for _ in range(3)]
    for o in zamowienia:
        assert len(o.products) == 2
    zapytania = []

    def licz(*_a, **_k):
        zapytania.append(1)

    event.listen(db.engine, 'before_cursor_execute', licz)
    try:
        for o in zamowienia:
            assert weryfikacja.uniewaznij_etapy(o, TERAZ, u'kontrola') is False
    finally:
        event.remove(db.engine, 'before_cursor_execute', licz)
    assert zapytania == []


def test_ponowione_zakoncz_pakowania_nie_cofa_statusu_logistyki(app, monkeypatch):
    """Kolejka offline tabletu może dosłać „ZAKOŃCZ” po weryfikacji — pozycja zostaje zweryfikowana,
    załadowana albo dostarczona, a po_spakowaniu się nie odpala. Dla 'spakowane' ponowione ZAKOŃCZ
    nadal woła po_spakowaniu (może zdjąć repack_required i zaległe 138620 oraz przeliczyć zamknięcie) —
    strażnik dotyczy tylko statusów logistycznych."""
    from modules.production.logistics.services import delivery
    wolania = []
    monkeypatch.setattr(delivery, 'po_spakowaniu', lambda *a, **k: wolania.append(a))
    for status in ('zweryfikowane', 'zaladowane', 'dostarczone'):
        order = zamowienie(sposob='kurier_baselinker', statusy=(status,))
        order.products[0].complete_task('packaging')
        assert order.products[0].current_status == status
    assert wolania == []


# --- Reguła sama potwierdza pracę na odczycie bieżącym (fala końcowa 4.3, F10) --------------------------
# SQLite nie ma migawki, więc „stan wołającego” odtwarzamy tak jak tests/weryfikacja_pomocnicze.py: obiekty
# zostają w sesji ORM w starym stanie (bez commitu i odświeżenia), a w bazie ktoś inny już zapisał nowy —
# surowymi UPDATE/INSERT poza ORM. Decyzja reguły ma zapaść na stanie z bazy.

NOWA_DEKLARACJA = datetime(2026, 10, 1, 8, 30)


def test_cron_nie_uniewaznia_swiezej_deklaracji_innego_urzadzenia(app):
    """Cron ma w pamięci migawkę: pozycje w produkcji (doróbka) i stara deklaracja paczek — wygląda na
    pracę. W bazie inne urządzenie zdążyło spakować pozycje i zadeklarować paczki od nowa. Świeża
    deklaracja ma zostać nietknięta, a reguła nic nie zalogować."""
    from modules.production.logistics.services import delivery
    order, stare = _z_paczkami(statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    order_id = order.id
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie'] * 2   # wczytane do pamięci
    # „Drugie urządzenie”: pakuje, unieważnia starą deklarację i deklaruje nową (surowo, poza sesją ORM).
    db.session.execute(ProductionProduct.__table__.update()
                       .where(ProductionProduct.__table__.c.order_id == order_id)
                       .values(current_status='spakowane'))
    db.session.execute(ProductionPackage.__table__.update()
                       .where(ProductionPackage.__table__.c.order_id == order_id)
                       .values(voided_at=NOWA_DEKLARACJA))
    db.session.execute(ProductionPackage.__table__.insert().values(
        order_id=order_id, seq=1, kind='paczka', declared_at=NOWA_DEKLARACJA))
    db.session.execute(ProductionOrder.__table__.update()
                       .where(ProductionOrder.__table__.c.id == order_id)
                       .values(packages_declared_at=NOWA_DEKLARACJA))
    # Migawka crona jest nieświeża: pozycje w produkcji i stara deklaracja.
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie'] * 2
    assert order.packages_declared_at == DEKLARACJA

    delivery.przelicz_otwarte(teraz=TERAZ)
    db.session.commit()

    db.session.expire_all()
    aktualne = ProductionPackage.query.filter_by(order_id=order_id, voided_at=None).all()
    assert [(p.seq, p.declared_at) for p in aktualne] == [(1, NOWA_DEKLARACJA)]   # świeża deklaracja żyje
    assert ProductionOrder.query.get(order_id).packages_declared_at == NOWA_DEKLARACJA
    assert [p.current_status for p in ProductionOrder.query.get(order_id).products] == ['spakowane'] * 2
    assert LogisticsLog.query.count() == 0


def test_cron_nadal_uniewaznia_gdy_praca_jest_tez_w_bazie(app):
    """Kontrola odwrotna: stan z migawki zgadza się z bazą, więc reguła unieważnia jak dotąd."""
    from modules.production.logistics.services import delivery
    order, lista = _z_paczkami(statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    delivery.przelicz_otwarte(teraz=TERAZ)
    db.session.commit()
    assert all(p.voided_at == TERAZ for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert ProductionOrder.query.get(order.id).packages_declared_at is None
    assert [w.action for w in LogisticsLog.query.filter_by(order_id=order.id)] == ['paczki']


def test_regula_potwierdza_prace_na_odczycie_biezacym_a_nie_na_obiekcie_wolajacego(app):
    """Wołający podaje zamówienie ze starym `verified_at` (migawka), a w bazie weryfikacja już została
    cofnięta przez kogoś innego. Reguła nie loguje drugiego `weryfikacja_cofnieta`."""
    order, _lista = _z_paczkami(statusy=('zweryfikowane', 'czeka_na_pakowanie'), zweryfikowane=True,
                                verified_at=DEKLARACJA)
    order_id = order.id
    assert order.verified_at == DEKLARACJA
    db.session.execute(ProductionOrder.__table__.update()
                       .where(ProductionOrder.__table__.c.id == order_id).values(verified_at=None))
    db.session.execute(ProductionProduct.__table__.update()
                       .where(ProductionProduct.__table__.c.order_id == order_id)
                       .values(current_status='czeka_na_pakowanie'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is True      # praca: paczki nadal ważne
    db.session.commit()
    assert [w.action for w in LogisticsLog.query.filter_by(order_id=order_id)] == ['paczki']


def test_regula_nie_gubi_niezapisanych_zmian_wolajacego(app):
    """`populate_existing` nadpisuje obiekty w sesji — jawny flush przed nim zapisuje zmiany wołającego,
    więc odczyt wczytuje z bazy te same wartości (tu: pozycja przestawiona do produkcji tuż przed regułą)."""
    order, _lista = _z_paczkami(statusy=('spakowane', 'spakowane'))
    order.products[0].current_status = 'czeka_na_pakowanie'       # zmiana tylko w pamięci, bez flush
    order.repack_reason = u'Weryfikacja: Inne'
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'test') is True
    db.session.commit()
    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['czeka_na_pakowanie', 'spakowane']
    assert o.repack_reason == u'Weryfikacja: Inne' and o.packages_declared_at is None
