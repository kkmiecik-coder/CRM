# -*- coding: utf-8 -*-
"""API panelu trakowni — zlecenia, pomiary i rozliczenia."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal

from extensions import db
from modules.production.sawmill.models import (
    STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_SETTLED,
    SawmillAudit, SawmillDelivery, SawmillLog, SawmillOrder,
    SawmillSpecies, SawmillSupplier,
)
from modules.production.sawmill.services.orders import add_log, write_audit
from tests.sawmill_fixtures import BASE, app, client  # noqa: F401

POMIAR_JSON = {
    'mid_circumference_cm': 125.6, 'length_cm': 410.0,
}
POMIAR_DEC = {k: Decimal(str(v)) for k, v in POMIAR_JSON.items()}


def _zlecenie(app, deklaracja='80.000', cena='1200.00', pomiarow=0, status=None):
    with app.app_context():
        supplier = SawmillSupplier(name='Tartak Nowak')
        species = SawmillSpecies.query.first()
        db.session.add(supplier)
        db.session.flush()
        delivery = SawmillDelivery(supplier_id=supplier.id,
                                   delivery_date=date(2026, 8, 5),
                                   invoice_number='FV/2026/0451')
        db.session.add(delivery)
        db.session.flush()
        order = SawmillOrder(
            order_number='TRK/2026/001', delivery_id=delivery.id,
            species_id=species.id, declared_volume_m3=Decimal(deklaracja),
            price_per_m3=Decimal(cena) if cena else None,
            declared_value=Decimal(deklaracja) * Decimal(cena) if cena else None,
        )
        db.session.add(order)
        db.session.flush()
        for _ in range(pomiarow):
            add_log(order, POMIAR_DEC, datetime(2026, 8, 5, 9, 0, 0), device_id='TRAK-1')
        # Po add_log — pierwszy pomiar sam przełącza new -> in_progress,
        # więc status wymuszamy dopiero na końcu.
        if status is not None:
            order.status = status
        db.session.commit()
        return order.id


def test_lista_zlecen_ma_roznice(client, app):
    _zlecenie(app, pomiarow=2, status=STATUS_COMPLETED)
    r = client.get(BASE + '/orders')
    assert r.status_code == 200
    order = r.get_json()['orders'][0]
    assert order['logs_count'] == 2
    assert order['measured_volume_m3'] == 1.029398
    assert order['difference_m3'] == -78.971
    assert order['is_deviation'] is True


def test_szczegoly_zawieraja_klody_i_audyt(client, app):
    oid = _zlecenie(app, pomiarow=1)
    r = client.get(BASE + '/orders/{}'.format(oid))
    data = r.get_json()
    assert len(data['logs']) == 1
    assert data['logs'][0]['device_id'] == 'TRAK-1'
    assert any(a['action'] == 'log_create' for a in data['audit'])


def test_filtr_tylko_odchylenia(client, app):
    # deklaracja=0.500 wobec zmierzonych ~1.029 m3 (2 kłody z POMIAR_DEC) daje
    # różnicę ~101% — jednoznacznie ponad próg 5% z ustawień fixture'a.
    # Wartość 1.000 z referencyjnego briefu dawała różnicę ~0.5%, czyli
    # PONIŻEJ progu — is_deviation byłoby False i test nie sprawdzałby tego,
    # co deklaruje (potwierdzone przeliczeniem compute_differences).
    _zlecenie(app, deklaracja='0.500', cena=None, pomiarow=2, status=STATUS_COMPLETED)
    assert len(client.get(BASE + '/orders?only_deviation=1').get_json()['orders']) == 1


def test_filtr_odchylen_pomija_zlecenia_otwarte(client, app):
    """
    To samo zlecenie co wyżej, ale jeszcze niezakończone — pomiar trwa, więc
    nie ma o czym mówić. Bez tego filtr „tylko odchylenia" łapałby KAŻDE
    otwarte zlecenie (zero pomiarów wobec deklaracji to zawsze -100%).
    """
    _zlecenie(app, deklaracja='0.500', cena=None, pomiarow=2)
    assert client.get(BASE + '/orders?only_deviation=1').get_json()['orders'] == []


def test_otwarte_zlecenie_ma_puste_roznice(client, app):
    _zlecenie(app, pomiarow=2)
    order = client.get(BASE + '/orders').get_json()['orders'][0]
    assert order['differences_pending'] is True
    assert order['difference_m3'] is None
    assert order['difference_pct'] is None
    assert order['difference_value'] is None
    assert order['is_deviation'] is False


def test_filtr_po_statusie(client, app):
    _zlecenie(app, pomiarow=1)
    assert client.get(BASE + '/orders?status=settled').get_json()['orders'] == []


def test_filtry_dzialaja_w_kombinacji(client, app):
    """
    Regresja na duplikowany JOIN: supplier_id + date_from + date_to + q naraz
    nie może wywalić się błędem SQL (ambiguous column / wielokrotny JOIN).
    """
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        supplier_id = order.delivery.supplier_id
    r = client.get(BASE + '/orders', query_string={
        'supplier_id': supplier_id,
        'date_from': '2026-08-01',
        'date_to': '2026-08-31',
        'q': 'TRK',
    })
    assert r.status_code == 200
    assert len(r.get_json()['orders']) == 1


def test_admin_dodaje_pomiar_recznie(client, app):
    oid = _zlecenie(app)
    r = client.post(BASE + '/orders/{}/logs'.format(oid),
                    json=dict(POMIAR_JSON, measured_at='2026-08-05T09:31:12'))
    assert r.status_code == 201
    with app.app_context():
        assert SawmillAudit.query.filter_by(action='log_create_manual').count() == 1
        assert SawmillLog.query.first().device_id is None


def test_admin_edytuje_pomiar_po_zakonczeniu(client, app, monkeypatch):
    """
    update_log() rozstrzyga panel/tablet po tym, czy user_id != None (kontrakt
    zamrożony w Zadaniu 6). W produkcji guard() (login_required +
    require_module_access) gwarantuje realnie zalogowanego current_user, więc
    _current_user_id() zawsze zwraca prawdziwe id. Ta minimalna apka testowa
    (sawmill_fixtures.py) nie rejestruje żadnego LoginManagera i ma
    LOGIN_DISABLED=True — current_user.id zawsze rozwiązuje się do None,
    więc bez tej podmiany trafialibyśmy w gałąź tabletu (OPEN_STATUSES) i
    dostali 409 zamiast testować faktyczną ścieżkę panelu (completed
    dozwolone). Podmieniamy WYŁĄCZNIE w tym teście, żeby zasymulować
    zalogowanego użytkownika — nie dotykamy sawmill_fixtures.py.
    """
    import modules.production.sawmill.routers.panel_api as panel_api
    monkeypatch.setattr(panel_api, '_current_user_id', lambda: 999)

    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        order.status = STATUS_COMPLETED
        log_id = SawmillLog.query.first().id
        db.session.commit()
    r = client.patch(BASE + '/logs/{}'.format(log_id),
                     json=dict(POMIAR_JSON, length_cm=420.0))
    assert r.status_code == 200


def test_edycja_rozliczonego_zablokowana(client, app, monkeypatch):
    """
    Bez podmiany _current_user_id (fixture nie ma prawdziwej sesji
    Flask-Login, więc funkcja zawsze zwraca None) test szedłby ścieżką
    TABLETU, a nie panelu — dowodziłby wtedy tylko, że tablet nie może
    pisać w 'settled', co jest prawdą niezależnie od tego, czy
    PANEL_WRITABLE_STATUSES poprawnie wyklucza 'settled'. Podmieniamy na
    zalogowanego usera (user_id=999), żeby faktycznie przejść przez gałąź
    panelu w _guard_writable() i sprawdzić WŁAŚCIWĄ regułę: nawet panel,
    któremu wolno pisać w completed, nie może pisać w settled.
    """
    import modules.production.sawmill.routers.panel_api as panel_api
    monkeypatch.setattr(panel_api, '_current_user_id', lambda: 999)

    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        order.status = STATUS_SETTLED
        log_id = SawmillLog.query.first().id
        db.session.commit()
    r = client.patch(BASE + '/logs/{}'.format(log_id),
                     json=dict(POMIAR_JSON, length_cm=420.0))
    assert r.status_code == 409


def test_usuniecie_pomiaru_w_zakonczonym_dozwolone_z_panelu(client, app, monkeypatch):
    """
    Podmiana _current_user_id symuluje realnie zalogowanego użytkownika
    panelu (fixture bez sesji Flask-Login zawsze zwraca None, czyli bez
    tej podmiany request poszedłby ścieżką TABLETU, która w ogóle nie
    dopuszcza statusu completed — test dostałby 409 i nic by nie
    udowodnił o panelu). Sprawdzamy właśnie to, co wolno panelowi:
    usunięcie pomiaru w zleceniu zakończonym (completed).
    """
    import modules.production.sawmill.routers.panel_api as panel_api
    monkeypatch.setattr(panel_api, '_current_user_id', lambda: 999)

    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        order.status = STATUS_COMPLETED
        log_id = SawmillLog.query.first().id
        db.session.commit()

    r = client.delete(BASE + '/logs/{}'.format(log_id))
    assert r.status_code == 200
    with app.app_context():
        log = db.session.query(SawmillLog).get(log_id)
        assert log.is_deleted is True


def test_usuniecie_pomiaru_w_rozliczonym_zablokowane(client, app, monkeypatch):
    """
    Jak wyżej — bez podmiany _current_user_id trafialibyśmy w gałąź
    tabletu (user_id=None) i test dowodziłby tylko, że TABLET nie może
    kasować pomiaru w 'settled', a nie że nie wolno tego panelowi. Panel
    ma szerszy dostęp (także completed), więc dopiero podmiana na
    zalogowanego użytkownika sprawdza właściwą regułę: nawet panel nie
    może usuwać pomiaru w zleceniu rozliczonym.
    """
    import modules.production.sawmill.routers.panel_api as panel_api
    monkeypatch.setattr(panel_api, '_current_user_id', lambda: 999)

    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        order.status = STATUS_SETTLED
        log_id = SawmillLog.query.first().id
        db.session.commit()

    r = client.delete(BASE + '/logs/{}'.format(log_id))
    assert r.status_code == 409
    with app.app_context():
        log = db.session.query(SawmillLog).get(log_id)
        assert log.is_deleted is False


def test_dodanie_pomiaru_recznie_w_rozliczonym_zablokowane(client, app):
    """
    Bez monkeypatcha celowo: add_log() z manual=True (ta ścieżka, czyli
    ręczne dodanie pomiaru z panelu) wymusza tryb panelu niezależnie od
    user_id — _guard_writable(order, panel=manual) w
    services/orders.py — więc podmiana _current_user_id nic by tu nie
    zmieniła. Test sprawdza wyłącznie zachowanie przez HTTP: ręczne
    dodanie pomiaru do zlecenia rozliczonego (settled) ma dać 409.
    """
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        db.session.query(SawmillOrder).get(oid).status = STATUS_SETTLED
        db.session.commit()

    r = client.post(BASE + '/orders/{}/logs'.format(oid),
                    json=dict(POMIAR_JSON, measured_at='2026-08-05T09:31:12'))
    assert r.status_code == 409


def test_patch_zerowa_lub_ujemna_deklaracja_odrzucona_lista_dziala(client, app):
    """
    Regresja na recenzję finalną: PATCH /orders/<id> z declared_volume_m3
    niedodatnim (0 albo ujemna) musi wracać 422, symetrycznie do
    delivery_create — bez tej walidacji zero trafiało do bazy i
    compute_differences() dzielił przez nie przy KAŻDYM kolejnym odczycie
    listy (GET /orders zwracał 500 dla WSZYSTKICH zleceń, nie tylko
    feralnego — realny przebieg z recenzji: panel_api.py:510 →
    _panel_payload → orders.py:68 → decimal.InvalidOperation:
    DivisionUndefined). Sprawdzamy oba niedodatnie warianty, a na końcu, że
    lista zleceń nadal się normalnie otwiera.
    """
    oid = _zlecenie(app)

    r = client.patch(BASE + '/orders/{}'.format(oid), json={'declared_volume_m3': '0'})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'declared_volume_m3'

    r = client.patch(BASE + '/orders/{}'.format(oid), json={'declared_volume_m3': '-5'})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'declared_volume_m3'

    with app.app_context():
        # Odrzucone wartości nie trafiły do bazy — deklaracja bez zmian.
        order = db.session.query(SawmillOrder).get(oid)
        assert order.declared_volume_m3 == Decimal('80.000')

    r = client.get(BASE + '/orders')
    assert r.status_code == 200
    assert len(r.get_json()['orders']) == 1


def test_pelna_sciezka_rozliczenia(client, app):
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        db.session.query(SawmillOrder).get(oid).status = STATUS_COMPLETED
        db.session.commit()

    r = client.post(BASE + '/orders/{}/settle'.format(oid),
                    json={'agreed_volume_m3': '76.500', 'settlement_notes': 'reklamacja'})
    assert r.status_code == 200
    assert r.get_json()['order']['status'] == STATUS_SETTLED

    r = client.post(BASE + '/orders/{}/unsettle'.format(oid))
    assert r.status_code == 200
    assert r.get_json()['order']['status'] == STATUS_COMPLETED
    assert r.get_json()['order']['agreed_volume_m3'] == 76.5


def test_rozliczenie_bez_uzgodnionej_objetosci_odrzucone(client, app):
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        db.session.query(SawmillOrder).get(oid).status = STATUS_COMPLETED
        db.session.commit()
    assert client.post(BASE + '/orders/{}/settle'.format(oid), json={}).status_code == 409


def test_reopen_odblokowuje_tablet(client, app):
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        db.session.query(SawmillOrder).get(oid).status = STATUS_COMPLETED
        db.session.commit()
    r = client.post(BASE + '/orders/{}/reopen'.format(oid))
    assert r.status_code == 200
    assert r.get_json()['order']['status'] == STATUS_IN_PROGRESS


def test_usuniecie_zlecenia_bez_pomiarow(client, app):
    oid = _zlecenie(app)
    assert client.delete(BASE + '/orders/{}'.format(oid)).status_code == 200


def test_usuniecie_zlecenia_z_pomiarami_zablokowane(client, app):
    oid = _zlecenie(app, pomiarow=1)
    assert client.delete(BASE + '/orders/{}'.format(oid)).status_code == 409


def test_soft_skasowane_pomiary_nadal_blokuja_usuniecie(client, app):
    """Jedyne miejsce, gdzie soft-delete NIE jest pomijany."""
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        log = SawmillLog.query.first()
        log.is_deleted = True
        db.session.commit()
    assert client.delete(BASE + '/orders/{}'.format(oid)).status_code == 409


def test_statystyki_kafelka(client, app):
    # _zlecenie() domyślnie datuje pomiary na sztywne 2026-08-05 09:00 —
    # w referencyjnym briefie to było „dziś" w dniu pisania testu, ale
    # `sawmill_dashboard_stats` liczy „dziś" względem datetime.now() w
    # chwili URUCHOMIENIA testu, więc sztywna data jest krucha (przestaje
    # być dniem bieżącym już następnego dnia). Dokładamy dwa pomiary z
    # rzeczywistym „teraz", żeby test sprawdzał regułę, a nie kalendarz.
    oid = _zlecenie(app)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        add_log(order, POMIAR_DEC, datetime.now(), device_id='TRAK-1')
        add_log(order, POMIAR_DEC, datetime.now(), device_id='TRAK-1')
        db.session.commit()
    data = client.get(BASE + '/dashboard-stats').get_json()
    assert data['open_orders'] == 1
    assert data['logs_today'] == 2
    assert data['to_settle'] == 0


def test_statystyki_licza_dzis_po_measured_at(client, app):
    """
    „Dziś" liczy się po measured_at, nie created_at — tablet potrafi rano
    wysłać pomiary z wczorajszego popołudnia (kolejka offline).
    """
    from datetime import timedelta
    oid = _zlecenie(app)
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        wczoraj = datetime.now() - timedelta(days=1)
        add_log(order, POMIAR_DEC, wczoraj, device_id='TRAK-1')
        db.session.commit()
    data = client.get(BASE + '/dashboard-stats').get_json()
    assert data['logs_today'] == 0


def test_odczyt_ustawien(client):
    data = client.get(BASE + '/settings').get_json()['settings']
    assert data['max_length_cm'] == 20000.0
    assert data['decimal_places'] == 1


def test_zapis_ustawien_dziala_natychmiast(client):
    """Bez cache — zmiana limitu ma obowiązywać od razu, nie po godzinie."""
    client.patch(BASE + '/settings', json={'max_circumference_cm': 150.0})
    assert client.get(BASE + '/settings').get_json()['settings']['max_circumference_cm'] == 150.0


def test_decimal_places_nie_da_sie_nadpisac(client):
    client.patch(BASE + '/settings', json={'decimal_places': 2})
    assert client.get(BASE + '/settings').get_json()['settings']['decimal_places'] == 1


def test_audyt_zwraca_nazwisko_autora(client, app):
    """
    Panel pokazuje historię ludziom z biura — sam user_id ("użytkownik #1")
    nie mówi nic. Nazwisko rozwiązuje backend, żeby nie robić tego w JS
    osobnym żądaniem na wiersz.
    """
    from modules.users.models import User
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        user = User(email='anna.kowalska@woodpower.pl', password='x',
                    first_name='Anna', last_name='Kowalska')
        db.session.add(user)
        db.session.flush()
        write_audit(oid, 'order_update', user_id=user.id)
        db.session.commit()

    audit = client.get(BASE + '/orders/{}'.format(oid)).get_json()['audit']
    wpis = [a for a in audit if a['action'] == 'order_update'][0]
    assert wpis['user_name'] == 'Anna Kowalska'


def test_audyt_urzadzenia_nie_ma_nazwiska(client, app):
    """Pomiar z tabletu nie ma autora-człowieka — pole zostaje puste, nie zmyślone."""
    oid = _zlecenie(app, pomiarow=1)
    audit = client.get(BASE + '/orders/{}'.format(oid)).get_json()['audit']
    wpis = [a for a in audit if a['action'] == 'log_create'][0]
    assert wpis['user_name'] is None
    assert wpis['device_id'] == 'TRAK-1'


# ── Walidacja wejścia (przegląd całej gałęzi) ───────────────────────────────

def test_smieciowy_filtr_daje_400_a_nie_klada_listy(client, app):
    """
    Parametry filtrów przychodzą z URL-a — ręcznie sklejony link albo stara
    zakładka. Bez osłony `?supplier_id=abc` kładło CAŁĄ listę zleceń błędem
    500, bez drogi wyjścia w interfejsie.
    """
    _zlecenie(app, pomiarow=1)
    for query in ('supplier_id=abc', 'species_id=x', 'date_from=2026-13-99',
                  'date_to=wczoraj'):
        r = client.get(BASE + '/orders?' + query)
        assert r.status_code == 400, query
        assert r.get_json()['error'] == 'invalid_filter'


def test_smieciowy_filtr_nie_wywraca_eksportu(client, app):
    """export.xlsx woła orders_list() wprost — musi dziedziczyć tę samą osłonę."""
    _zlecenie(app, pomiarow=1)
    r = client.get(BASE + '/export.xlsx?supplier_id=abc')
    assert r.status_code == 400
    assert r.get_json()['error'] == 'invalid_filter'


def test_nieistniejacy_gatunek_przy_edycji_daje_422(client, app):
    oid = _zlecenie(app, pomiarow=0)
    r = client.patch(BASE + '/orders/{}'.format(oid), json={'species_id': 99999})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'species_id'


def test_pusty_gatunek_przy_edycji_daje_422(client, app):
    oid = _zlecenie(app, pomiarow=0)
    r = client.patch(BASE + '/orders/{}'.format(oid), json={'species_id': None})
    assert r.status_code == 422


def test_nieaktywny_gatunek_wolno_zostawic_przy_edycji(client, app):
    """
    Miękkie kasowanie istnieje po to, żeby historyczne zlecenia dalej
    wskazywały na swój gatunek — edycja innego pola nie może się o niego
    wywalić.
    """
    oid = _zlecenie(app, pomiarow=0)
    with app.app_context():
        gatunek = SawmillSpecies.query.first()
        gatunek.is_active = False
        db.session.commit()
        species_id = gatunek.id
    r = client.patch(BASE + '/orders/{}'.format(oid),
                     json={'species_id': species_id, 'notes': 'zmiana'})
    assert r.status_code == 200


def test_nan_w_deklaracji_daje_422_a_nie_500(client, app):
    oid = _zlecenie(app, pomiarow=0)
    for wartosc in ('NaN', 'Infinity', '-Infinity'):
        r = client.patch(BASE + '/orders/{}'.format(oid),
                         json={'declared_volume_m3': wartosc})
        assert r.status_code == 422, wartosc


def test_nieliczbowa_liczba_klod_daje_422(client, app):
    oid = _zlecenie(app, pomiarow=0)
    r = client.patch(BASE + '/orders/{}'.format(oid),
                     json={'declared_logs_count': 'abc'})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'declared_logs_count'


def test_zmiana_nazwy_dostawcy_na_istniejaca_daje_422(client, app):
    with app.app_context():
        db.session.add_all([SawmillSupplier(name='Tartak A'),
                            SawmillSupplier(name='Tartak B')])
        db.session.commit()
        drugi_id = SawmillSupplier.query.filter_by(name='Tartak B').first().id
    r = client.patch(BASE + '/suppliers/{}'.format(drugi_id), json={'name': 'Tartak A'})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'name'


def test_zmiana_nazwy_gatunku_na_istniejaca_daje_422(client, app):
    with app.app_context():
        db.session.add_all([SawmillSpecies(name='Modrzew'), SawmillSpecies(name='Sosna')])
        db.session.commit()
        sosna_id = SawmillSpecies.query.filter_by(name='Sosna').first().id
    r = client.patch(BASE + '/species/{}'.format(sosna_id), json={'name': 'Modrzew'})
    assert r.status_code == 422


def test_zapis_wlasnej_nazwy_bez_zmiany_przechodzi(client, app):
    """Regresja: sprawdzenie duplikatu nie może blokować zapisu samego siebie."""
    with app.app_context():
        db.session.add(SawmillSupplier(name='Tartak C'))
        db.session.commit()
        sid = SawmillSupplier.query.filter_by(name='Tartak C').first().id
    r = client.patch(BASE + '/suppliers/{}'.format(sid),
                     json={'name': 'Tartak C', 'phone': '600100200'})
    assert r.status_code == 200


def test_ujemna_objetosc_uzgodniona_odrzucona(client, app):
    """Trafiłaby na protokół PDF idący do dostawcy."""
    oid = _zlecenie(app, pomiarow=1, status=STATUS_COMPLETED)
    r = client.post(BASE + '/orders/{}/settle'.format(oid),
                    json={'agreed_volume_m3': '-5'})
    assert r.status_code == 409
    r = client.post(BASE + '/orders/{}/settle'.format(oid),
                    json={'agreed_volume_m3': '0'})
    assert r.status_code == 409


def test_kosz_ukryty_gdy_zlecenie_ma_skasowane_pomiary(client, app):
    """
    can_delete liczy WSZYSTKIE wiersze, także miękko skasowane — tym samym
    warunkiem, którym order_delete blokuje usunięcie. Inaczej interfejs
    pokazywał przycisk, który zawsze kończył się 409.
    """
    oid = _zlecenie(app, pomiarow=1)
    with app.app_context():
        log = SawmillLog.query.filter_by(order_id=oid).first()
        log.is_deleted = True
        db.session.commit()

    order = client.get(BASE + '/orders').get_json()['orders'][0]
    assert order['logs_count'] == 0
    assert order['can_delete'] is False
    assert client.delete(BASE + '/orders/{}'.format(oid)).status_code == 409


def test_kosz_widoczny_gdy_zlecenie_nigdy_nie_mialo_pomiarow(client, app):
    oid = _zlecenie(app, pomiarow=0)
    order = client.get(BASE + '/orders').get_json()['orders'][0]
    assert order['can_delete'] is True
    assert client.delete(BASE + '/orders/{}'.format(oid)).status_code == 200
