# -*- coding: utf-8 -*-
"""Kolejka druku z dzierżawą (agent druku v2, Task 2). SQLite; tabele agenta zakłada test (jak w migracji)."""
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.drukarki import models as m_drukarki, stale
from modules.production.drukarki.services import kolejka
from modules.production.models import LabelPrintJob
from tests.logistyka_fixtures import app  # noqa: F401

AGENT = 7
INNY_AGENT = 8
AKTOR = {'type': 'user', 'id': 1}


@pytest.fixture(autouse=True)
def _tabele(app):
    db.metadata.create_all(bind=db.engine, tables=[m_drukarki.PrintAgent.__table__])


def _zadanie(drukarka='etykiety', minut_temu=0, **kw):
    j = LabelPrintJob(printer=drukarka, short_product_id=kw.pop('kod', 'K1'), zpl_payload='^XA^XZ',
                      station_code='panel', requested_by_type='user', requested_by_id='1',
                      requested_at=datetime.utcnow() - timedelta(minutes=minut_temu), **kw)
    db.session.add(j)
    db.session.flush()
    return j


def _stan(job):
    db.session.expire_all()
    return LabelPrintJob.query.get(job.id)


def test_pobierz_dzierzawi_fifo_tylko_swojej_drukarki(app):
    a, b, c = (_zadanie(minut_temu=m) for m in (30, 20, 10))
    w = _zadanie('wysylka', minut_temu=40)
    db.session.commit()
    przed = datetime.utcnow()
    wziete = kolejka.pobierz(AGENT, 'etykiety', 2)
    assert [j.id for j in wziete] == [a.id, b.id]
    for j in wziete:
        assert j.status == 'claimed' and j.claimed_by_agent_id == AGENT
        assert abs((j.lease_until - przed).total_seconds() - stale.DZIERZAWA_S) < 5
    assert _stan(c).status == 'pending' and _stan(w).status == 'pending'
    # drugie pobranie nie oddaje już wydzierżawionych
    assert [j.id for j in kolejka.pobierz(INNY_AGENT, 'etykiety', 5)] == [c.id]


def test_wynik_niewyslane_wraca_do_pending(app):
    j = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'niewyslane'}]) == 1
    j = _stan(j)
    assert j.status == 'pending'
    assert j.claimed_by_agent_id is None and j.lease_until is None and j.sending_at is None


def test_wynik_wydrukowane_i_wysylam(app):
    j = _zadanie()
    db.session.commit()
    assert kolejka.wysylam(AGENT, j.id) is False          # jeszcze nie pobrane
    kolejka.pobierz(AGENT, 'etykiety', 1)
    assert kolejka.wysylam(INNY_AGENT, j.id) is False     # cudza dzierżawa
    assert kolejka.wysylam(AGENT, j.id) is True
    assert _stan(j).status == 'sending' and _stan(j).sending_at is not None
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'wydrukowane'}]) == 1
    assert _stan(j).status == 'printed' and _stan(j).printed_at is not None


def test_wynik_blad_cofa_liczniki(app, monkeypatch):
    j = _zadanie(product_id=5, label_index=2)
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append([x.id for x in jobs]))
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'blad', 'blad': 'brak papieru'}]) == 1
    assert wolane == [[j.id]]
    j = _stan(j)
    assert j.status == 'failed' and j.error_message == 'brak papieru'


def test_wynik_cudzego_agenta_ignorowany(app):
    j = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    assert kolejka.wynik(INNY_AGENT, [{'id': j.id, 'wynik': 'wydrukowane'}]) == 0
    assert _stan(j).status == 'claimed' and _stan(j).claimed_by_agent_id == AGENT


def test_wynik_powtorzony_bez_zmian(app, monkeypatch):
    j = _zadanie(product_id=5, label_index=2)
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append(1))
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'blad', 'blad': 'x'}]) == 1
    # powtórka tego samego i sprzeczna — nic się nie zmienia, liczniki cofnięte raz
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'blad', 'blad': 'x'}]) == 0
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'wydrukowane'}]) == 0
    assert _stan(j).status == 'failed' and wolane == [1]


def test_wygasla_dzierzawa_claimed_do_pending(app):
    j = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    teraz = datetime.utcnow()
    assert kolejka.wygas(teraz)['claimed_do_pending'] == 0       # dzierżawa jeszcze trwa
    r = kolejka.wygas(teraz + timedelta(seconds=stale.DZIERZAWA_S + 5))
    assert r['claimed_do_pending'] == 1
    j = _stan(j)
    assert j.status == 'pending' and j.claimed_by_agent_id is None and j.lease_until is None


def test_wygasla_dzierzawa_sending_to_unknown(app, monkeypatch):
    j = _zadanie(product_id=5, label_index=2)
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    kolejka.wysylam(AGENT, j.id)
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs',
                        lambda jobs: pytest.fail('unknown nie cofa liczników'))
    r = kolejka.wygas(datetime.utcnow() + timedelta(seconds=stale.DZIERZAWA_S + 5))
    assert r['sending_do_unknown'] == 1
    assert _stan(j).status == 'unknown'


def test_pending_po_godzinie_expired_z_cofnieciem(app, monkeypatch):
    stare = _zadanie(minut_temu=90, product_id=5, label_index=2)
    swieze = _zadanie(minut_temu=10)
    db.session.commit()
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append([x.id for x in jobs]))
    assert kolejka.wygas()['expired'] == 1
    assert wolane == [[stare.id]]
    assert _stan(stare).status == 'expired' and _stan(swieze).status == 'pending'


def test_dzierzawa_ignoruje_czas_agenta(app):
    # Pola czasu w wynikach agenta nic nie zmieniają; o wygaśnięciu decyduje wyłącznie `teraz` serwera.
    j = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    lease = _stan(j).lease_until
    kolejka.wynik(AGENT, [{'id': 99999, 'wynik': 'wydrukowane', 'lease_until': '2000-01-01', 'teraz': 'x'}])
    assert _stan(j).lease_until == lease
    assert kolejka.wygas(lease - timedelta(seconds=1))['claimed_do_pending'] == 0
    assert kolejka.wygas(lease + timedelta(seconds=1))['claimed_do_pending'] == 1
    with pytest.raises(TypeError):
        kolejka.wysylam(AGENT, j.id, teraz=datetime.utcnow())


def test_ponow_tworzy_kopie_bez_label_index(app):
    j = _zadanie(product_id=5, label_index=2, baselinker_order_id=11, kod='ABC')
    j.status = 'failed'
    db.session.commit()
    nowe = kolejka.ponow(j.id, AKTOR)
    assert nowe.id != j.id and nowe.status == 'pending'
    assert nowe.zpl_payload == j.zpl_payload and nowe.printer == 'etykiety'
    assert nowe.product_id == 5 and nowe.label_index is None and nowe.reprint_of_job_id == j.id
    assert nowe.short_product_id == 'ABC' and nowe.station_code == 'panel' and nowe.baselinker_order_id == 11
    for stan in ('pending', 'claimed', 'sending', 'cancelled'):
        x = _zadanie()
        x.status = stan
        with pytest.raises(ValueError):
            kolejka.ponow(x.id, AKTOR)
    for stan in ('expired', 'unknown', 'printed'):
        x = _zadanie()
        x.status = stan
        assert kolejka.ponow(x.id, AKTOR).reprint_of_job_id == x.id


def test_anuluj_tylko_pending(app, monkeypatch):
    p = _zadanie(product_id=5, label_index=2)
    c = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 5)           # oba claimed
    p.status = 'pending'                            # jedno z powrotem do pending
    db.session.commit()
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append([x.id for x in jobs]))
    assert kolejka.anuluj(c.id, AKTOR) is False
    assert kolejka.anuluj(p.id, AKTOR) is True
    assert _stan(p).status == 'cancelled' and _stan(c).status == 'claimed'
    assert wolane == [[p.id]]
    assert kolejka.anuluj(p.id, AKTOR) is False


def test_wysylam_powtorzone_idempotentne(app):
    j = _zadanie()
    db.session.commit()
    kolejka.pobierz(AGENT, 'etykiety', 1)
    assert kolejka.wysylam(AGENT, j.id) is True
    # cofamy znaczniki, żeby odnowienie dzierżawy było mierzalne
    j = _stan(j)
    sending_at = j.sending_at
    j.lease_until = datetime.utcnow() + timedelta(seconds=10)
    db.session.commit()
    assert kolejka.wysylam(AGENT, j.id) is True
    j = _stan(j)
    assert j.status == 'sending' and j.sending_at == sending_at
    assert (j.lease_until - datetime.utcnow()).total_seconds() > stale.DZIERZAWA_S - 5
    assert kolejka.wysylam(INNY_AGENT, j.id) is False


def test_pobierz_nie_wydaje_pending_starszego_niz_ttl(app, monkeypatch):
    """Po przerwie agenta pending sprzed ponad godziny nie wychodzi na drukarkę — czeka na `wygas` (expired
    z cofnięciem liczników)."""
    stare = _zadanie(minut_temu=120, product_id=5, label_index=2)
    swieze = _zadanie(minut_temu=30)
    db.session.commit()
    assert [j.id for j in kolejka.pobierz(AGENT, 'etykiety', 10)] == [swieze.id]
    assert kolejka.pobierz(AGENT, 'etykiety', 10) == []
    assert _stan(stare).status == 'pending' and _stan(stare).claimed_by_agent_id is None
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append([x.id for x in jobs]))
    assert kolejka.wygas()['expired'] == 1 and wolane == [[stare.id]]
    assert _stan(stare).status == 'expired'


def test_pobierz_granica_ttl_liczy_zegar_serwera(app):
    j = _zadanie(minut_temu=50)
    db.session.commit()
    assert kolejka.pobierz(AGENT, 'etykiety', 1, teraz=datetime.utcnow() + timedelta(minutes=20)) == []
    assert [x.id for x in kolejka.pobierz(AGENT, 'etykiety', 1)] == [j.id]


def _w_unknown(j):
    kolejka.pobierz(AGENT, 'etykiety', 1)
    kolejka.wysylam(AGENT, j.id)
    kolejka.wygas(datetime.utcnow() + timedelta(seconds=stale.DZIERZAWA_S + 5))
    assert _stan(j).status == 'unknown'


def test_spozniony_wynik_wydrukowane_z_unknown(app, monkeypatch):
    j = _zadanie(product_id=5, label_index=2)
    db.session.commit()
    _w_unknown(j)
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs',
                        lambda jobs: pytest.fail('wydrukowane nie cofa liczników'))
    assert kolejka.wynik(INNY_AGENT, [{'id': j.id, 'wynik': 'wydrukowane'}]) == 0   # tylko agent z dzierżawy
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'wydrukowane'}]) == 1
    j = _stan(j)
    assert j.status == 'printed' and j.printed_at is not None and j.error_message is None


def test_spozniony_wynik_blad_z_unknown_cofa_liczniki(app, monkeypatch):
    j = _zadanie(product_id=5, label_index=2)
    db.session.commit()
    _w_unknown(j)
    wolane = []
    monkeypatch.setattr(kolejka, 'rollback_label_count_for_jobs', lambda jobs: wolane.append([x.id for x in jobs]))
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'blad', 'blad': 'drukarka zerwała połączenie'}]) == 1
    assert wolane == [[j.id]]
    j = _stan(j)
    assert j.status == 'failed' and j.error_message == 'drukarka zerwała połączenie'


def test_spozniony_wynik_niewyslane_zostawia_unknown(app):
    j = _zadanie()
    db.session.commit()
    _w_unknown(j)
    assert kolejka.wynik(AGENT, [{'id': j.id, 'wynik': 'niewyslane'}]) == 0
    assert _stan(j).status == 'unknown'
