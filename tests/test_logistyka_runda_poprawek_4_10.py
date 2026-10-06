# -*- coding: utf-8 -*-
"""
Runda poprawek po przeglądzie końcowym gałęzi logistyki (4.10.2026). Punkt przeglądu (A-I1, B-4, …)
w nagłówku każdej sekcji.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, delivery, geocoding
from modules.production.models import LabelPrintJob, ProductionOrder, ProductionPackage
from modules.production.services import blokady_zamowien
from modules.production.services.label_print_service import rollback_label_count_for_jobs
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, indeks_blokady_tras, zapis,
)
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_tla(monkeypatch):
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: True)


# ── A-I1: „Wydane klientowi” decyduje na zamówieniu i pozycjach z blokady ────

def _wydanie(client, oid):
    return client.post(BASE + '/orders/%d/handed-over' % oid)


def test_a_i1_wydanie_blokuje_trasy_potem_zamowienie_i_pozycje_przed_zapisem(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'zweryfikowane')).id
        with Zapytania() as z:
            r = _wydanie(client, oid)
        assert r.status_code == 200, r.get_json()
        trasy = indeks_blokady_tras(z)
        zamowienia = z.pierwsze(blokada_zamowien)
        pozycje = z.pierwsze(blokada_pozycji)
        assert trasy < zamowienia < pozycje < z.pierwsze(zapis)
        assert ProductionOrder.query.get(oid).handed_over_at is not None


def test_a_i1_wydanie_odmawia_gdy_weryfikacja_cofnela_do_pakowania_przed_blokada(client, app, monkeypatch):
    """
    Telefon Weryfikacji („Cofnij do pakowania”) blokady tras nie bierze: jego commit może wejść między migawką
    a blokadą zamówienia. Symulacja: cudzy zapis pozycji tuż przed blokadą zamówienia — decyzja ma zapaść na
    stanie z blokady (odmowa), nie na wcześniej przeczytanym.
    """
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'spakowane')).id
    oryginal = blokady_zamowien.zablokuj_zamowienie

    def cofniecie_przed_blokada(order_id):
        db.session.execute(text("UPDATE prod_products SET current_status = 'czeka_na_pakowanie' "
                                "WHERE order_id = :o"), {'o': order_id})
        return oryginal(order_id)

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienie', cofniecie_przed_blokada)
    r = _wydanie(client, oid)
    assert r.status_code == 409 and u'nie jest jeszcze w całości spakowane' in r.get_json()['error']
    with app.app_context():
        order = ProductionOrder.query.get(oid)
        assert order.handed_over_at is None and order.bl_status_pending_id is None


def test_a_i1_p2_decyzja_na_obiekcie_z_blokady(client, app, monkeypatch):
    """P2: `wydaj_klientowi` dostaje dokładnie zamówienie zwrócone przez blokadę (pozycje z tego samego odczytu)."""
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    zablokowane, wydane = [], []
    oryginal_blokada, oryginal_wydanie = blokady_zamowien.zablokuj_zamowienie, delivery.wydaj_klientowi

    def blokada(order_id):
        zablokowane.append(oryginal_blokada(order_id))
        return zablokowane[-1]

    def wydanie(order, **kw):
        wydane.append((order, list(order.products)))
        return oryginal_wydanie(order, **kw)

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienie', blokada)
    monkeypatch.setattr(delivery, 'wydaj_klientowi', wydanie)
    assert _wydanie(client, oid).status_code == 200
    assert len(zablokowane) == 1 and wydane[0][0] is zablokowane[0]
    assert all(p.order is zablokowane[0] for p in wydane[0][1])


def test_a_i1_wydanie_nieznanego_zamowienia_404(client):
    assert _wydanie(client, 999999).status_code == 404


# ── B-4: nieudany albo wygasły druk etykiety paczki cofa jej znacznik wydruku ──

TOKEN_AGENTA = 'token-agenta-testowy'
T_DRUKU = datetime(2026, 10, 4, 9, 0)


@pytest.fixture()
def agent(app, client, monkeypatch):
    from modules.production.routers.api import print_agent_api
    monkeypatch.setattr(print_agent_api, '_get_agent_token', lambda: TOKEN_AGENTA)
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')
    return client


def _paczka_z_wydrukiem(liczba=1, napis='TRANSPORT WOODPOWER'):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    paczka = ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=T_DRUKU,
                               label_printed_at=T_DRUKU, label_print_count=liczba, label_delivery_text=napis)
    db.session.add(paczka)
    db.session.flush()
    job = LabelPrintJob(short_product_id='P-%d' % paczka.id, zpl_payload='^XA^XZ', station_code='packaging',
                        requested_by_type='user', requested_by_id='1', status='pending',
                        printer=LabelPrintJob.DRUKARKA_WYSYLKA, package_id=paczka.id,
                        requested_at=datetime.utcnow())
    db.session.add(job)
    db.session.commit()
    return paczka.id, job.id


def test_b4_cofanie_jedynego_wydruku_paczki_czysci_znacznik(app):
    pid, jid = _paczka_z_wydrukiem()
    rollback_label_count_for_jobs([LabelPrintJob.query.get(jid)])
    db.session.commit()
    paczka = ProductionPackage.query.get(pid)
    assert (paczka.label_print_count, paczka.label_printed_at, paczka.label_delivery_text) == (0, None, None)


def test_b4_nieudany_przedruk_zostawia_wczesniejszy_wydruk(app):
    pid, jid = _paczka_z_wydrukiem(liczba=2)
    rollback_label_count_for_jobs([LabelPrintJob.query.get(jid)])
    db.session.commit()
    paczka = ProductionPackage.query.get(pid)
    assert paczka.label_print_count == 1 and paczka.label_printed_at == T_DRUKU
    # (M4 po re-review) napis wydruku nieznany — panel pokaże etykietę do przedruku
    assert paczka.label_delivery_text is None


def test_b4_ack_z_bledem_drukarki_cofa_wydruk_paczki(agent, app):
    pid, jid = _paczka_z_wydrukiem()
    r = agent.post('/api/print-agent/ack', headers={'Authorization': 'Bearer ' + TOKEN_AGENTA},
                   json={'results': [{'id': jid, 'success': False, 'error': 'brak papieru'}]})
    assert r.status_code == 200 and r.get_json()['updated'] == 1
    paczka = ProductionPackage.query.get(pid)
    assert paczka.label_print_count == 0 and paczka.label_printed_at is None


def test_b4_wygasle_zadanie_paczki_cofa_wydruk(app):
    from modules.production.routers.api import print_agent_api
    pid, jid = _paczka_z_wydrukiem()
    LabelPrintJob.query.get(jid).requested_at = datetime.utcnow() - timedelta(hours=3)
    db.session.commit()
    assert print_agent_api._expire_stale_pending(force=True) == 1
    paczka = ProductionPackage.query.get(pid)
    assert LabelPrintJob.query.get(jid).status == 'expired'
    assert paczka.label_print_count == 0 and paczka.label_printed_at is None


def test_b4_udany_wydruk_paczki_bez_zmian(agent, app):
    pid, jid = _paczka_z_wydrukiem()
    agent.post('/api/print-agent/ack', headers={'Authorization': 'Bearer ' + TOKEN_AGENTA},
               json={'results': [{'id': jid, 'success': True}]})
    paczka = ProductionPackage.query.get(pid)
    assert paczka.label_print_count == 1 and paczka.label_printed_at == T_DRUKU


# ── B-5: token agenta druku porównywany stałoczasowo ──────────────────────────

def test_b5_token_agenta_porownywany_stalo_czasowo(agent, monkeypatch):
    from modules.production.routers.api import print_agent_api
    porownania = []
    oryginal = print_agent_api.hmac.compare_digest

    def podglad(a, b):
        porownania.append((a, b))
        return oryginal(a, b)

    monkeypatch.setattr(print_agent_api.hmac, 'compare_digest', podglad)
    zly = agent.get('/api/print-agent/jobs', headers={'Authorization': 'Bearer zly-token'})
    dobry = agent.get('/api/print-agent/jobs', headers={'Authorization': 'Bearer ' + TOKEN_AGENTA})
    assert zly.status_code == 401 and dobry.status_code == 200
    assert len(porownania) == 2


def test_b5_token_spoza_ascii_to_401_nie_500(agent):
    r = agent.get('/api/print-agent/jobs', headers={'Authorization': u'Bearer tökén'})
    assert r.status_code == 401


# ── B-7: przykładowa konfiguracja agenta bez adresu z sieci hali ──────────────

def test_b7_przyklad_konfiguracji_agenta_z_adresem_dokumentacyjnym():
    import os
    import re
    sciezka = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'tools', 'print_agent', 'config.example.ini')
    adresy = re.findall(r'^ip\s*=\s*(\S+)', open(sciezka, encoding='utf-8').read(), re.M)
    assert adresy and all(a.startswith('192.0.2.') for a in adresy)   # RFC 5737, TEST-NET-1


# ── C-1, C-2: panel produkcji (skróty przy starszej przeglądarce, błąd zakładki Logistyka) ──

def _plik(*czesci):
    import os
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *czesci),
                encoding='utf-8').read()


def _metoda_js(js, nazwa):
    poczatek = js.index('    ' + nazwa + '(')
    return js[poczatek:js.index('\n    }\n', poczatek)]


def test_c1_skroty_bez_wsparcia_modal_nie_rzucaja():
    """`:modal` rzuca SyntaxError w querySelector starszych przeglądarek — try/catch z zapasem `dialog[open]`."""
    skroty = _metoda_js(_plik('modules', 'production', 'static', 'js', 'production-app-loader.js'),
                        'handleKeyboardShortcuts')
    proba = skroty[skroty.index('try {'):skroty.index('catch')]
    assert "querySelector('dialog:modal')" in proba
    zapas = skroty[skroty.index('catch'):]
    assert "querySelector('dialog[open]')" in zapas[:300]


def test_c2_zakladka_logistyka_ma_blok_bledu():
    import re
    html = _plik('modules', 'production', 'templates', 'panel', 'dashboard.html')
    poczatek = html.index('id="logistics-tab-content"')
    blok = html[poczatek:html.index('<!-- Sawmill', poczatek) if '<!-- Sawmill' in html[poczatek:]
                else html.index('id="sawmill-tab-content"', poczatek)]
    for fraza in ('id="logistics-tab-wrapper"', 'id="logistics-tab-error"', 'id="logistics-tab-error-message"',
                  'ProductionApp.forceRefresh()'):
        assert fraza in blok, fraza
    zaladuj = _metoda_js(_plik('modules', 'production', 'static', 'js', 'production-app-loader.js'),
                         'async loadLogisticsTab')
    # Treść trafia do wrappera (innerHTML kontenera skasowałby blok błędu), sukces chowa błąd.
    assert "getElementById('logistics-tab-wrapper')" in zaladuj
    assert "this.hideTabError('logistics-tab')" in zaladuj
    assert "this.showTabError('logistics-tab'" in zaladuj
    m = re.search(r"js/production-app-loader\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) > '20260928a'


# ── C-3: vendorowany leaflet.js bez odwołania do niewendorowanej mapy źródeł ──

def test_c3_leaflet_bez_source_map_z_notatka():
    js = _plik('modules', 'production', 'static', 'vendor', 'leaflet', 'leaflet.js')
    assert 'sourceMappingURL' not in js and 't.version="1.9.4"' in js
    notatka = _plik('modules', 'production', 'static', 'vendor', 'leaflet', 'README.txt')
    assert 'sourceMappingURL' in notatka and '1.9.4' in notatka
    html = _plik('modules', 'production', 'logistics', 'templates', 'logistics', 'tab_content.html')
    assert "vendor/leaflet/leaflet.js') }}?v=1.9.4a" in html   # wersja podbita po zmianie pliku


# ── A-M2: napisy w dynamicznym SQL nowych migracji w apostrofach (konwencja D6) ──

MIGRACJE_LOGISTYKI = [
    '2026-09-25-logistyka-sposob-dostawy.sql', '2026-09-26-logistyka-geolokalizacja.sql',
    '2026-09-26-logistyka-zmiana-adresu.sql', '2026-09-27-logistyka-trasy-flota.sql',
    '2026-09-28-logistyka-kierowcy.sql', '2026-09-30-druk-dwie-drukarki.sql',
    '2026-09-30-druk-klucze-przesuniecia.sql', '2026-09-30-logistyka-paczki-blokada.sql',
    '2026-09-30-logistyka-paczki.sql', '2026-09-30-logistyka-weryfikacja.sql',
    '2026-10-01-analiza-planowana-trasa.sql', '2026-10-01-logistyka-dostawa.sql',
    '2026-10-02-logistyka-niedostarczone-na-trasie.sql', '2026-10-02-raport-planowana-trasa.sql',
]


@pytest.mark.parametrize('plik', MIGRACJE_LOGISTYKI)
def test_a_m2_napisy_w_migracjach_w_apostrofach(plik):
    """Przy `sql_mode` z ANSI_QUOTES `"…"` jest identyfikatorem (1054 w gałęzi „już jest”). Polecenia po podziale
    runnera — bez komentarzy."""
    from migrations.migration_service import MigrationService
    for polecenie in MigrationService.split_statements(_plik('migrations', plik)):
        assert '"' not in polecenie, ' '.join(polecenie.split())[:120]


# ── Dokładka po re-review rundy: M3 (zapis warunkowy), M4 (napis po nieudanym przedruku) ──

def test_m3_licznik_paczki_wyrazeniem_sql_nie_nadpisuje_rownoleglego_przedruku(app):
    """Paczka w sesji ma licznik 1, a równoległy przedruk (inna transakcja) podbił go do 2 — cofnięcie nieudanego
    zadania zdejmuje jeden wydruk z wartości w bazie, nie zapisuje 0 z nieaktualnego odczytu."""
    pid, jid = _paczka_z_wydrukiem()
    w_sesji = ProductionPackage.query.get(pid)   # silna referencja: obiekt zostaje w mapie tożsamości
    assert w_sesji.label_print_count == 1
    db.session.execute(text('UPDATE prod_packages SET label_print_count = 2 WHERE id = :p'), {'p': pid})
    rollback_label_count_for_jobs([LabelPrintJob.query.get(jid)])
    db.session.commit()
    paczka = ProductionPackage.query.get(pid)
    assert paczka.label_print_count == 1 and paczka.label_printed_at is not None


def test_m3_ack_po_wygasnieciu_przez_inny_worker_nic_nie_cofa(agent, app):
    """Zadanie w sesji jeszcze `pending`, a inny worker już je wygasił (i cofnął wydruk) — ACK z błędem nie cofa drugi
    raz i nie nadpisuje statusu (zapis warunkowy WHERE status = 'pending')."""
    pid, jid = _paczka_z_wydrukiem(liczba=2)
    w_sesji = LabelPrintJob.query.get(jid)   # silna referencja: ACK dostaje z mapy tożsamości stary status
    assert w_sesji.status == 'pending'
    db.session.execute(text("UPDATE prod_print_queue SET status = 'expired' WHERE id = :j"), {'j': jid})
    db.session.execute(text('UPDATE prod_packages SET label_print_count = 1 WHERE id = :p'), {'p': pid})
    r = agent.post('/api/print-agent/ack', headers={'Authorization': 'Bearer ' + TOKEN_AGENTA},
                   json={'results': [{'id': jid, 'success': False, 'error': 'brak papieru'}]})
    assert r.status_code == 200 and r.get_json()['updated'] == 0
    db.session.expire_all()
    assert LabelPrintJob.query.get(jid).status == 'expired'
    assert ProductionPackage.query.get(pid).label_print_count == 1


def test_m4_nieudany_przedruk_zostawia_ikone_etykiety_nieaktualnej(app):
    """Przedruk po zmianie sposobu nie wyszedł: na paczce leży stara etykieta, więc panel dalej ma pokazać „etykieta
    sprzed zmiany” — napis wydruku czyścimy (nieznany), choć licznik i czas zostają."""
    from modules.production.logistics.services import lista
    pid, jid = _paczka_z_wydrukiem(liczba=2, napis='TRANSPORT WOODPOWER')
    rollback_label_count_for_jobs([LabelPrintJob.query.get(jid)])
    db.session.commit()
    paczka = ProductionPackage.query.get(pid)
    assert paczka.label_print_count == 1 and paczka.label_printed_at == T_DRUKU
    assert paczka.label_delivery_text is None
    assert lista._etykiety_paczek_sprzed_zmiany(paczka.order, None, [paczka]) is True


# ── Dokładka po re-review: zapisy warunkowe zadań druku w stałej kolejności (bez 1213 wygasanie ↔ ACK) ──

def _id_zapisow_zadan(z):
    return [parametry[-2] if isinstance(parametry, tuple) else None
            for sql, parametry in z.lista if sql.startswith('UPDATE prod_print_queue')]


def test_ack_przestawia_zadania_rosnaco_po_id(agent, app):
    ids = [_paczka_z_wydrukiem()[1] for _ in range(3)]
    with Zapytania() as z:
        r = agent.post('/api/print-agent/ack', headers={'Authorization': 'Bearer ' + TOKEN_AGENTA},
                       json={'results': [{'id': i, 'success': False, 'error': 'x'} for i in reversed(ids)]})
    assert r.status_code == 200 and r.get_json()['updated'] == 3
    assert _id_zapisow_zadan(z) == sorted(ids)


def test_wygasanie_przestawia_zadania_rosnaco_po_id(app):
    from modules.production.routers.api import print_agent_api
    ids = [_paczka_z_wydrukiem()[1] for _ in range(3)]
    for i in ids:
        LabelPrintJob.query.get(i).requested_at = datetime.utcnow() - timedelta(hours=3)
    db.session.commit()
    with Zapytania() as z:
        assert print_agent_api._expire_stale_pending(force=True) == 3
    wybor = [sql for sql, _ in z.lista if sql.startswith('SELECT') and 'FROM prod_print_queue' in sql][0]
    assert 'ORDER BY prod_print_queue.id' in wybor
    assert _id_zapisow_zadan(z) == sorted(ids)


# ── Decyzja Konrada 4.10 (wyścigi wydane-weryfikacja): „Wydane klientowi” przy otwartym problemie — pytać ──

def _odbior_z_problemem(**kolumny):
    from modules.production.models import get_local_now
    order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane', 'zweryfikowane'), **kolumny)
    order.problem_reason, order.problem_note = 'uszkodzenie', u'Pęknięty blat <b>'
    order.problem_at = get_local_now()
    db.session.commit()
    return order.id


def test_wydanie_z_otwartym_problemem_bez_potwierdzenia_409(client, app):
    from modules.production.logistics.models import LogisticsLog
    oid = _odbior_z_problemem()
    r = client.post(BASE + '/orders/%d/handed-over' % oid, json={})
    assert r.status_code == 409
    dane = r.get_json()
    assert dane['kod'] == 'wymaga_potwierdzenia_problemu'
    assert dane['problem']['reason_label'] == 'Uszkodzenie' and dane['problem']['note'] == u'Pęknięty blat <b>'
    order = ProductionOrder.query.get(oid)
    assert order.handed_over_at is None and order.bl_status_pending_id is None
    assert {p.current_status for p in order.products} == {'spakowane', 'zweryfikowane'}
    assert LogisticsLog.query.filter_by(order_id=oid, action='wydane').count() == 0


def test_wydanie_z_otwartym_problemem_z_potwierdzeniem_200(client, app):
    from modules.production.logistics.models import LogisticsLog
    oid = _odbior_z_problemem()
    r = client.post(BASE + '/orders/%d/handed-over' % oid, json={'potwierdz_problem': True})
    assert r.status_code == 200, r.get_json()
    order = ProductionOrder.query.get(oid)
    assert order.handed_over_at is not None and order.problem_at is not None   # problem zostaje w danych
    log = LogisticsLog.query.filter_by(order_id=oid, action='wydane').one()
    assert u'mimo problemu' in (log.note or '') and 'Uszkodzenie' in log.note


@pytest.mark.parametrize('cialo', [{'potwierdz_problem': 'true'}, {'potwierdz_problem': 1}, [True]])
def test_wydanie_zle_potwierdzenie_422(client, app, cialo):
    oid = _odbior_z_problemem()
    assert client.post(BASE + '/orders/%d/handed-over' % oid, json=cialo).status_code == 422
    assert ProductionOrder.query.get(oid).handed_over_at is None


def test_wydanie_bez_problemu_bez_zmian(client, app):
    oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    assert client.post(BASE + '/orders/%d/handed-over' % oid).status_code == 200
    assert ProductionOrder.query.get(oid).handed_over_at is not None


def test_wydanie_problem_zgloszony_przed_blokada_decyduje_obiekt_z_blokady(client, app, monkeypatch):
    """P2: Weryfikacja zgłasza problem między migawką a blokadą zamówienia — decyzja na stanie z blokady (409)."""
    oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    oryginal = blokady_zamowien.zablokuj_zamowienie

    def zgloszenie_przed_blokada(order_id):
        db.session.execute(text("UPDATE prod_orders SET problem_reason = 'inne', problem_at = CURRENT_TIMESTAMP "
                                "WHERE id = :o"), {'o': order_id})
        return oryginal(order_id)

    monkeypatch.setattr(blokady_zamowien, 'zablokuj_zamowienie', zgloszenie_przed_blokada)
    r = client.post(BASE + '/orders/%d/handed-over' % oid, json={})
    assert r.status_code == 409 and r.get_json()['kod'] == 'wymaga_potwierdzenia_problemu'


def test_front_wydanie_pyta_o_problem():
    import re
    js = _plik('modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
    wydaj = js[js.index('async function wydaj('):]
    wydaj = wydaj[:wydaj.index('\n    }\n')]
    assert "'wymaga_potwierdzenia_problemu'" in wydaj and 'potwierdz_problem: true' in wydaj
    assert "' ma zgłoszony problem z Weryfikacji: '" in wydaj and "'. Wydać klientowi mimo to?'" in wydaj
    assert 'window.confirm(' in wydaj
    html = _plik('modules', 'production', 'logistics', 'templates', 'logistics', 'tab_content.html')
    m = re.search(r"js/logistics\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) > '20261002i'
