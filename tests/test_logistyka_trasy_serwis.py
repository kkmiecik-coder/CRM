# -*- coding: utf-8 -*-
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, RouteStop
from modules.production.logistics.services import routes
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import app, kierowca, pojazd, zamowienie  # noqa: F401


def _trasa(od='2026-10-01', do=None, **dane):
    dane.setdefault('name', 'Trasa %s' % od)
    trasa = routes.utworz(dict(dane, date_from=od, date_to=do or od))
    db.session.commit()
    return trasa


def _transport(**kolumny):
    return zamowienie(sposob=s.TRANSPORT, **kolumny)


def test_utworzenie_i_walidacja(app):
    with app.app_context():
        t = _trasa(name='  Kraków + Tarnów ', od='2026-10-01', do='2026-10-02')
        assert (t.name, t.status, t.date_to) == ('Kraków + Tarnów', 'robocza', date(2026, 10, 2))
        for zle in ({'name': ''}, {'name': 'A', 'date_from': 'jutro'},
                    {'name': 'A', 'date_from': '2026-10-02', 'date_to': '2026-10-01'}):
            dane = dict({'date_from': '2026-10-01'}, **zle)
            with pytest.raises(LogistykaBlad) as e:
                routes.utworz(dane)
            assert e.value.status == 422


@pytest.mark.parametrize('od, do, zajety', [
    ('2026-10-03', '2026-10-05', True),   # wspólny dzień 3.10
    ('2026-09-28', '2026-10-01', True),
    ('2026-10-04', '2026-10-05', False),
    ('2026-09-28', '2026-09-30', False),
])
def test_zajetosc_na_granicy_dat(app, od, do, zajety):
    """Review Focus 1."""
    with app.app_context():
        v, k = pojazd(), kierowca()
        _trasa(od='2026-10-01', do='2026-10-03', vehicle_id=v.id, driver_worker_id=k.id)
        z = routes.zajetosc(date.fromisoformat(od), date.fromisoformat(do))
        assert (v.id in z['pojazdy']) is zajety and (k.id in z['kierowcy']) is zajety
        d = routes.dostepnosc(date.fromisoformat(od), date.fromisoformat(do))
        assert d['pojazdy'][0]['zajety'] is zajety


def test_zajety_pojazd_odrzucony_a_wykonana_trasa_nie_blokuje(app):
    with app.app_context():
        v = pojazd()
        t = _trasa(vehicle_id=v.id)
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'Druga', 'date_from': '2026-10-01', 'vehicle_id': v.id})
        assert e.value.status == 409 and t.name in e.value.komunikat
        t.status = 'wykonana'
        db.session.commit()
        assert routes.utworz({'name': 'Druga', 'date_from': '2026-10-01', 'vehicle_id': v.id})


def test_edycja_nie_koliduje_sama_ze_soba(app):
    with app.app_context():
        v = pojazd()
        t = _trasa(vehicle_id=v.id)
        routes.edytuj(t, {'name': 'Nowa', 'date_from': '2026-10-01', 'date_to': '2026-10-02',
                          'vehicle_id': v.id})
        assert t.name == 'Nowa'


def test_wylaczony_pojazd_odrzucony(app):
    with app.app_context():
        v = pojazd(is_active=False)
        with pytest.raises(LogistykaBlad):
            routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'vehicle_id': v.id})


def test_dodanie_duplikatow_i_zajetych(app):
    """Review Focus 5."""
    with app.app_context():
        t1, t2 = _trasa(name='Pierwsza'), _trasa(name='Druga')
        a, b = _transport(), _transport()
        kurier = zamowienie(sposob=s.KURIER)
        routes.dodaj_przystanki(t1, [b.id])
        wynik = routes.dodaj_przystanki(t2, [a.id, a.id, b.id, kurier.id, 999999])
        db.session.commit()
        assert wynik['dodane'] == [a.id]
        komunikaty = {x['order_id']: x['komunikat'] for x in wynik['bledy']}
        assert 'Pierwsza' in komunikaty[b.id]
        assert 'transportu własnego' in komunikaty[kurier.id]
        assert 999999 in komunikaty


def test_przystanki_numerowane_i_kolejnosc(app):
    with app.app_context():
        t = _trasa()
        a, b, c = _transport(), _transport(), _transport()
        routes.dodaj_przystanki(t, [a.id, b.id, c.id])
        routes.zmien_kolejnosc(t, [c.id, a.id, b.id])
        db.session.commit()
        assert [x.order_id for x in t.stops] == [c.id, a.id, b.id]
        routes.usun_przystanek(t, a.id)
        db.session.commit()
        assert [(x.order_id, x.position) for x in t.stops] == [(c.id, 1), (b.id, 2)]
        with pytest.raises(LogistykaBlad):
            routes.zmien_kolejnosc(t, [c.id])


def test_dodanie_podbija_pozycje_i_loguje(app):
    with app.app_context():
        t = _trasa()
        o = _transport()
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        routes.dodaj_przystanki(t, [o.id])
        db.session.commit()
        assert all(p.updated_at > datetime(2026, 1, 1) for p in o.products)
        log = LogisticsLog.query.filter_by(order_id=o.id, action='trasa_dodane').one()
        assert log.route_id == t.id


def test_zatwierdzona_jest_zablokowana(app):
    with app.app_context():
        t = _trasa()
        with pytest.raises(LogistykaBlad):
            routes.zatwierdz(t)  # bez przystanków
        o = _transport()
        routes.dodaj_przystanki(t, [o.id])
        routes.zatwierdz(t)
        db.session.commit()
        assert t.status == 'zatwierdzona' and t.approved_at is not None
        for akcja in (lambda: routes.dodaj_przystanki(t, [_transport().id]),
                      lambda: routes.usun_przystanek(t, o.id),
                      lambda: routes.edytuj(t, {'name': 'X', 'date_from': '2026-10-01'})):
            with pytest.raises(LogistykaBlad) as e:
                akcja()
            assert e.value.status == 409
        routes.cofnij_do_roboczej(t)
        assert t.status == 'robocza'


def test_niedostarczony_wraca_do_puli(app):
    """Review Focus 3."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        b = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id, b.id])
        for p in b.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        wynik = routes.wykonaj(t, dostarczone_ids=[a.id])
        db.session.commit()
        assert wynik == {'dostarczone': [a.id], 'niedostarczone': [b.id]}
        assert t.status == 'wykonana' and t.completed_at is not None
        assert a.logistics_closed_at is not None
        assert b.logistics_closed_at is None
        assert RouteStop.query.filter_by(order_id=b.id).first() is None
        # fix-1, Ruling B: b wraca do puli — tablet musi to zobaczyć (ETag z updated_at).
        assert all(p.updated_at > datetime(2026, 1, 1) for p in b.products)
        notatka = LogisticsLog.query.filter_by(order_id=b.id, action='trasa_usuniete').one().note
        assert notatka == 'niedostarczone'


def test_przywrocenie_otwiera_zamowienia(app):
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        routes.wykonaj(t, [a.id])
        db.session.commit()
        assert a.logistics_closed_at is not None
        routes.przywroc(t)
        db.session.commit()
        assert t.status == 'zatwierdzona' and a.logistics_closed_at is None


def test_usuniecie_roboczej(app):
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        routes.usun(t)
        db.session.commit()
        assert routes.przystanek_zamowienia(a.id) is None


def test_podsumowanie_i_ladownosc(app):
    with app.app_context():
        v = pojazd(capacity_kg=100)
        t = _trasa(vehicle_id=v.id)
        o = _transport(statusy=('spakowane', 'spakowane'))   # 2 × 0.024 m³ × 2 szt.
        routes.dodaj_przystanki(t, [o.id])
        db.session.commit()
        sumy = routes.podsumowanie(t, routes.zamowienia_trasy(t), {})
        assert sumy['przystanki'] == 1
        assert sumy['m3'] == pytest.approx(0.096)
        assert sumy['waga_kg'] == 77
        assert sumy['przekroczona_ladownosc'] is False
        assert sumy['bez_lokalizacji'] == 1


def test_mapa_tras_aktywnych(app):
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        assert routes.mapa_tras_aktywnych() == {a.id: t}
        t.status = 'wykonana'
        db.session.commit()
        assert routes.mapa_tras_aktywnych() == {}


# --- Ruling R3: dodaj_przystanki/zmien_kolejnosc/wykonaj przyjmują Z ZEWNĄTRZ (JSON) ---
# wyłącznie listę/krotkę Pythonowych int-ów. bool jest podklasą int w Pythonie, więc
# [True] musi być odrzucone jawnie — inaczej przeszłoby jako id=1. Inny typ elementu
# (string, float, dict) trafiłby surowy do ProductionOrder.id.in_(...) i SQLAlchemy/baza
# rzuciłyby błąd programistyczny (500) zamiast czytelnej odmowy 422 — ten sam wzorzec co
# panel_api.py:117 w API etapu 2. Walidacja siedzi w jednej pomocniczej funkcji i działa
# PRZED jakąkolwiek zmianą w sesji.

def test_zle_id_w_dodaj_przystanki_napis(app):
    with app.app_context():
        t = _trasa()
        with pytest.raises(LogistykaBlad) as e:
            routes.dodaj_przystanki(t, ['x'])
        assert e.value.status == 422
        assert t.stops == []


def test_zle_id_w_dodaj_przystanki_bool(app):
    with app.app_context():
        t = _trasa()
        with pytest.raises(LogistykaBlad) as e:
            routes.dodaj_przystanki(t, [True])
        assert e.value.status == 422
        assert t.stops == []


def test_zle_id_w_zmien_kolejnosc_nie_lista(app):
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.zmien_kolejnosc(t, 'abc')
        assert e.value.status == 422
        # kolejność bez zmian — walidacja poszła przed jakimkolwiek zapisem
        assert [x.order_id for x in t.stops] == [a.id]


def test_zle_id_w_wykonaj_float(app):
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.wykonaj(t, dostarczone_ids=[1.5])
        assert e.value.status == 422
        assert t.status == 'robocza'


# --- fix-1, Ruling B: każda zmiana widoczna na tablecie musi podbić updated_at ---
# pozycji zamówień (ETag kolejki liczy się z MAX(updated_at) — bez podbicia tablet
# dostaje 304 i nie widzi zmiany). `zmien_kolejnosc` celowo pominięta: pozycja
# przystanku nie jest niczym, co tablet pokazuje.

def _trasa_ze_statusem(status):
    t = _trasa()
    o = _transport(statusy=('spakowane',))
    routes.dodaj_przystanki(t, [o.id])
    if status in ('zatwierdzona', 'wykonana'):
        routes.zatwierdz(t)
    if status == 'wykonana':
        routes.wykonaj(t, [o.id])
    db.session.commit()
    return t, o


@pytest.mark.parametrize('status, operacja', [
    ('robocza', lambda t: routes.edytuj(t, {'name': 'Nowa', 'date_from': '2026-10-01'})),
    ('robocza', lambda t: routes.zatwierdz(t)),
    ('zatwierdzona', lambda t: routes.cofnij_do_roboczej(t)),
    ('zatwierdzona', lambda t: routes.wykonaj(t, [s.order_id for s in t.stops])),
    ('wykonana', lambda t: routes.przywroc(t)),
    ('robocza', lambda t: routes.usun(t)),
], ids=['edytuj', 'zatwierdz', 'cofnij_do_roboczej', 'wykonaj', 'przywroc', 'usun'])
def test_kazda_zmiana_trasy_podbija_pozycje(app, status, operacja):
    with app.app_context():
        t, o = _trasa_ze_statusem(status)
        for p in o.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        operacja(t)
        db.session.commit()
        assert all(p.updated_at > datetime(2026, 1, 1) for p in o.products)


# --- fix-1, Ruling C: dane spoza spodziewanych typów (np. z JSON API etapu 6) ---
# muszą dać 422, nie AttributeError/OverflowError (500).

@pytest.mark.parametrize('zle', [
    {'name': 5},
    {'name': 'A', 'notes': ['x']},
    {'name': 'A', 'vehicle_id': True},
    {'name': 'A', 'vehicle_id': 1e400},
    {'name': 'A', 'vehicle_id': 'abc'},
    {'name': 'A', 'date_from': 5},
    # fix-2, Minor 3 residual: str.isdigit() łapie cyfry Unicode („²”, „①”), na
    # których goły int() rzuca ValueError (500); brak limitu długości daje ten sam
    # ValueError dla >4300 cyfr (CPython 3.11+). O4: float ZAWSZE 422, także 0.0.
    {'name': 'A', 'vehicle_id': '²'},
    {'name': 'A', 'vehicle_id': '①'},
    {'name': 'A', 'vehicle_id': '9' * 5000},
    {'name': 'A', 'vehicle_id': 0.0},
])
def test_zle_typy_w_danych_trasy(app, zle):
    with app.app_context():
        dane = dict({'date_from': '2026-10-01'}, **zle)
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz(dane)
        assert e.value.status == 422


def test_vehicle_id_zero_string_to_brak_pojazdu(app):
    """fix-2, O4: '00' (i '0', 0) po sparsowaniu oznaczają „brak pojazdu" (None),
    nigdy vehicle_id=0 — literalne 0 złamałoby FK do prod_vehicles przy flushu."""
    with app.app_context():
        t = routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'vehicle_id': '00'})
        db.session.commit()
        assert t.vehicle_id is None


def test_notatka_limit_2000_znakow(app):
    """fix-2 (dodatek z przeglądu Task 6): prod_routes.notes to TEXT w MySQL
    (limit 65 535 B) — bez limitu w serwisie zbyt długa notatka rzuciłaby dopiero
    przy commicie MySQL 1406 (500); SQLite testów tego nie widzi, więc granicę
    sprawdzamy tu wprost, po stronie Pythona."""
    with app.app_context():
        t = routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'notes': 'x' * 2000})
        db.session.commit()
        assert t.notes == 'x' * 2000
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'B', 'date_from': '2026-10-01', 'notes': 'x' * 2001})
        assert e.value.status == 422


# --- fix-1, Ruling A: blokada globalna „jeden piszący trasy naraz" ---

def _szpieg_blokady(monkeypatch):
    """Podmienia routes.zablokuj_trasy na szpiega, który woła oryginał (działanie
    bez zmian) i zapisuje id trasy każdego wywołania (None dla utworz())."""
    wywolania = []
    oryginal = routes.zablokuj_trasy

    def podglad(route=None):
        wywolania.append(route.id if route is not None else None)
        return oryginal(route)

    monkeypatch.setattr(routes, 'zablokuj_trasy', podglad)
    return wywolania


def test_zablokuj_trasy_na_starcie_kazdej_funkcji_zmieniajacej(app, monkeypatch):
    """Ruling A3/A9: zablokuj_trasy() jest pierwszą rzeczą, którą robi każda funkcja
    zmieniająca trasę — sprawdzone na całym cyklu życia trasy."""
    with app.app_context():
        wywolania = _szpieg_blokady(monkeypatch)

        t = routes.utworz({'name': 'A', 'date_from': '2026-10-01'})
        db.session.commit()
        assert wywolania == [None]

        routes.edytuj(t, {'name': 'B', 'date_from': '2026-10-01'})
        assert wywolania[-1] == t.id

        o1, o2 = _transport(statusy=('spakowane',)), _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [o1.id, o2.id])
        assert wywolania[-1] == t.id

        routes.zmien_kolejnosc(t, [o2.id, o1.id])
        assert wywolania[-1] == t.id

        routes.usun_przystanek(t, o2.id)
        assert wywolania[-1] == t.id

        routes.zatwierdz(t)
        assert wywolania[-1] == t.id

        routes.cofnij_do_roboczej(t)
        assert wywolania[-1] == t.id

        routes.zatwierdz(t)
        przed = len(wywolania)
        routes.wykonaj(t, [o1.id])
        assert t.id in wywolania[przed:]

        routes.przywroc(t)
        assert wywolania[-1] == t.id

        routes.cofnij_do_roboczej(t)
        assert wywolania[-1] == t.id

        routes.usun(t)
        assert t.id in wywolania[-2:]   # własne wywołanie + re-entrantne z usun_przystanek


def test_zablokuj_trasy_widzi_swiezy_status_mimo_identity_mapy(app):
    """Ruling A9 (dowód na populate_existing): zwykły odczyt obiektu już w identity
    mapie NIE odświeża jego atrybutów po surowym UPDATE „za plecami" ORM-a — tylko
    with_for_update().populate_existing() to robi. Bez tego dodaj_przystanki
    działałby na przeterminowanym route.status."""
    with app.app_context():
        t = _trasa()
        o = _transport()
        db.session.execute(text("UPDATE prod_routes SET status='zatwierdzona' WHERE id=:i"),
                           {'i': t.id})
        assert t.status == 'robocza'   # identity mapa jeszcze nie wie o zmianie
        with pytest.raises(LogistykaBlad) as e:
            routes.dodaj_przystanki(t, [o.id])
        assert e.value.status == 409


def test_zablokuj_trasy_nieistniejaca_trasa_404(app):
    """Trasa usunięta przez kogoś innego w międzyczasie (np. usun() w innej sesji)."""
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            routes.zablokuj_trasy(SimpleNamespace(id=999999))
        assert e.value.status == 404


def test_zablokuj_trasy_bez_wiersza_blokady_dziala_z_ostrzezeniem(app, monkeypatch):
    """Świeża baza bez wiersza 'logistyka_trasy_blokada' (migracja go zakłada, ale
    fixture testowy tworzy tylko schemat, nie dane — dokładnie ten scenariusz na
    KAŻDYM teście tego pliku) nie wywraca zapisu — fail-open z ostrzeżeniem raz na
    proces, nie wyjątkiem."""
    with app.app_context():
        monkeypatch.setattr(routes, '_blokada_ostrzezono', False)
        t = routes.utworz({'name': 'A', 'date_from': '2026-10-01'})
        db.session.commit()
        assert t.status == 'robocza'
        assert routes._blokada_ostrzezono is True


# --- fix-2, O1: po zablokuj_trasy(route) jedynym źródłem prawdy o przystankach ---
# jest ŚWIEŻA route.stops (załadowana pod blokadą) — żadnego expire()+zwykłego
# zapytania później w tej samej funkcji/transakcji. Realny wyścig dwóch sesji
# MySQL potwierdził fałszywe 404 (wykonaj na przystanku dodanym równolegle) i
# StaleDataError (podwójne usunięcie); testy niżej sprawdzają kontrakt na SQLite
# (identity mapa vs. surowy SQL) — samej migawki MVCC z dwóch transakcji SQLite
# (jedno połączenie) nie odtworzy, tak samo jak testy blokady w fix-1.

def test_usun_przystanek_gdy_wiersz_zniknal_za_plecami_orm_daje_404(app):
    """Wiersz przystanku usunięty surowym SQL-em (symulacja: druga sesja go
    skasowała) — usun_przystanek musi się oprzeć na ŚWIEŻEJ route.stops i zgłosić
    czyste 404, nie StaleDataError (500) na DELETE nieistniejącego wiersza."""
    with app.app_context():
        t = _trasa()
        a = _transport()
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        db.session.execute(text("DELETE FROM prod_route_stops WHERE order_id = :oid"),
                           {'oid': a.id})
        # BEZ commit: identity mapa (t.stops w pamięci) jeszcze "widzi" przystanek.
        with pytest.raises(LogistykaBlad) as e:
            routes.usun_przystanek(t, a.id)
        assert e.value.status == 404


def test_przenumeruj_uzywa_swiezych_pozycji_po_zablokuj_trasy(app):
    """Pozycje zmienione surowym SQL-em "za plecami" ORM-a (symulacja drugiej,
    już zacommitowanej transakcji, której zmian identity mapa jeszcze nie
    widziała) muszą być widoczne po zablokuj_trasy — usuwając jeden przystanek,
    _przenumeruj musi renumerować z ŚWIEŻEGO porządku [c, a] (z bazy), nie ze
    starego porządku wczytanego przed surowym UPDATE-em."""
    with app.app_context():
        t = _trasa()
        a, b, c = _transport(), _transport(), _transport()
        routes.dodaj_przystanki(t, [a.id, b.id, c.id])
        db.session.commit()
        assert [s.order_id for s in t.stops] == [a.id, b.id, c.id]
        db.session.execute(text("UPDATE prod_route_stops SET position = 10 WHERE order_id = :oid"),
                           {'oid': c.id})
        db.session.execute(text("UPDATE prod_route_stops SET position = 20 WHERE order_id = :oid"),
                           {'oid': a.id})
        db.session.execute(text("UPDATE prod_route_stops SET position = 30 WHERE order_id = :oid"),
                           {'oid': b.id})
        routes.usun_przystanek(t, b.id)
        db.session.commit()
        assert [(s.order_id, s.position) for s in t.stops] == [(c.id, 1), (a.id, 2)]


# ═══ Fala poprawek po przeglądzie końcowym ═══════════════════════════════════

# --- I1: odhaczenie nie oznacza jako dostarczonego zamówienia, które nie jest spakowane ---

def test_odhaczenie_odmawia_niespakowanych_dostarczonych(app):
    """I1: dostarczone zamyka zamówienie na zawsze — niespakowane oznaczone jako dostarczone
    zniknęłoby z logistyki bez śladu. 409 z listą numerów i `niespakowane` (id), bez zmian."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        b = _transport(statusy=('spakowane', 'czeka_na_lakiernie'))
        routes.dodaj_przystanki(t, [a.id, b.id])
        routes.zatwierdz(t)
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.wykonaj(t, [a.id, b.id])
        assert e.value.status == 409
        assert e.value.dane == {'niespakowane': [b.id]}
        assert b.internal_order_number in e.value.komunikat
        assert a.internal_order_number not in e.value.komunikat
        db.session.rollback()
        assert t.status == 'zatwierdzona' and {x.order_id for x in t.stops} == {a.id, b.id}
        # Niespakowane odznaczone — wraca do puli, spakowane dostarczone.
        assert routes.wykonaj(t, [a.id]) == {'dostarczone': [a.id], 'niedostarczone': [b.id]}
        db.session.commit()
        assert a.logistics_closed_at is not None and b.logistics_closed_at is None


def test_odhaczenie_wiele_niespakowanych_w_jednym_komunikacie(app):
    with app.app_context():
        t = _trasa()
        a, b = _transport(), _transport()
        routes.dodaj_przystanki(t, [a.id, b.id])
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.wykonaj(t, [a.id, b.id])
        assert e.value.dane == {'niespakowane': [a.id, b.id]}
        assert e.value.komunikat.startswith(u'Zamówienia {}, {} nie są'.format(
            a.internal_order_number, b.internal_order_number))


def test_odhaczenie_pomija_anulowane_w_regule_spakowania(app):
    """I1: zamówienie bez aktywnych pozycji (wszystkie anulowane) nie blokuje odhaczenia."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        c = _transport(statusy=('czeka_na_wyciecie',))
        routes.dodaj_przystanki(t, [a.id, c.id])
        for p in c.products:
            p.current_status = 'anulowane'
        db.session.commit()
        assert routes.wykonaj(t, [a.id, c.id]) == {'dostarczone': [a.id, c.id], 'niedostarczone': []}


def test_odhaczenie_wymaga_listy_dostarczonych(app):
    """M6: brak listy (None) to 422, a nie „wszystko dostarczone”."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.wykonaj(t, None)
        assert e.value.status == 422 and 'delivered_order_ids' in e.value.komunikat
        assert t.status == 'robocza'


def test_odhaczenie_zamyka_wedlug_swiezej_trasy(app, monkeypatch):
    """Resztka O1: wykonaj/przywroc decydują o zamknięciu ze świeżej trasy spod blokady, nie
    z routes.przystanek_zamowienia (zwykły odczyt z migawki transakcji)."""
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        db.session.commit()

        def _nie_wolno(*args, **kwargs):
            raise AssertionError('zamknięcie liczone ze zwykłego odczytu przystanku')

        monkeypatch.setattr(routes, 'przystanek_zamowienia', _nie_wolno)
        routes.wykonaj(t, [a.id])
        db.session.commit()
        assert a.logistics_closed_at is not None
        routes.przywroc(t)
        db.session.commit()
        assert a.logistics_closed_at is None


# --- I3: niezmieniony wyłączony pojazd/kierowca nie blokuje edycji ani przywrócenia ---

def _wykonana_z(pojazd_id=None, kierowca_id=None):
    t = _trasa(vehicle_id=pojazd_id, driver_worker_id=kierowca_id)
    a = _transport(statusy=('spakowane',))
    routes.dodaj_przystanki(t, [a.id])
    routes.zatwierdz(t)
    routes.wykonaj(t, [a.id])
    db.session.commit()
    return t


def test_wylaczony_pojazd_i_kierowca_zostaja_przy_edycji(app):
    """I3 (spec 8.1): wyłączony pojazd zostaje widoczny na starych trasach — zmiana nazwy
    trasy z tym samym pojazdem i kierowcą nie wymaga ich wymiany."""
    with app.app_context():
        v, k = pojazd(), kierowca()
        t = _trasa(vehicle_id=v.id, driver_worker_id=k.id)
        v.is_active, k.is_active = False, False
        db.session.commit()
        routes.edytuj(t, {'name': 'Nowa nazwa', 'date_from': '2026-10-01',
                          'vehicle_id': v.id, 'driver_worker_id': k.id})
        db.session.commit()
        assert (t.name, t.vehicle_id, t.driver_worker_id) == ('Nowa nazwa', v.id, k.id)


def test_przywrocenie_z_wylaczonym_pojazdem_i_kierowca(app):
    with app.app_context():
        v, k = pojazd(), kierowca()
        t = _wykonana_z(v.id, k.id)
        v.is_active, k.is_active = False, False
        db.session.commit()
        routes.przywroc(t)
        db.session.commit()
        assert t.status == 'zatwierdzona'


@pytest.mark.parametrize('zasob', ['pojazd', 'kierowca'])
def test_nowe_przypisanie_wylaczonego_odrzucone(app, zasob):
    """I3: zakaz wyłączonego zostaje dla NOWEGO przypisania (zmiana zasobu, nowa trasa)."""
    with app.app_context():
        stary_v, stary_k = pojazd(), kierowca()
        t = _trasa(vehicle_id=stary_v.id, driver_worker_id=stary_k.id)
        nowy = pojazd(is_active=False) if zasob == 'pojazd' else kierowca(aktywny=False)
        pole = 'vehicle_id' if zasob == 'pojazd' else 'driver_worker_id'
        dane = {'name': 'A', 'date_from': '2026-10-01', 'vehicle_id': stary_v.id,
                'driver_worker_id': stary_k.id, pole: nowy.id}
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, dane)
        assert e.value.status == 422
        db.session.rollback()
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'B', 'date_from': '2026-10-05', pole: nowy.id})
        assert e.value.status == 422


def test_przywrocenie_nadal_sprawdza_zajetosc(app):
    """I3: pominięte jest tylko sprawdzenie aktywności — zajęty pojazd dalej daje 409."""
    with app.app_context():
        v = pojazd()
        t = _wykonana_z(v.id)
        druga = _trasa(name='Druga', vehicle_id=v.id)
        with pytest.raises(LogistykaBlad) as e:
            routes.przywroc(t)
        assert e.value.status == 409 and druga.name in e.value.komunikat


# --- M8: granice dat trasy ---

def test_granice_dat_trasy(app):
    """M8: od dziś − 1 rok do dziś + 2 lata (włącznie), „do” najwyżej 31 dni po „od”."""
    with app.app_context():
        assert routes.granice_dat() == (date(2025, 9, 26), date(2028, 9, 26))
        assert routes.utworz({'name': 'Najwcześniej', 'date_from': '2025-09-26'})
        assert routes.utworz({'name': 'Najpóźniej', 'date_from': '2028-09-26'})
        assert routes.utworz({'name': '31 dni', 'date_from': '2026-10-01', 'date_to': '2026-11-01'})
        for dane in ({'date_from': '2025-09-25'}, {'date_from': '2028-09-27'},
                     {'date_from': '0001-01-01'}, {'date_from': '2026-10-01', 'date_to': '9999-12-31'},
                     {'date_from': '2062-10-01'}):
            with pytest.raises(LogistykaBlad) as e:
                routes.utworz(dict(dane, name='Zła'))
            assert e.value.status == 422 and '26.09.2025' in e.value.komunikat, dane
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': '32 dni', 'date_from': '2026-10-01', 'date_to': '2026-11-02'})
        assert e.value.status == 422
        assert e.value.komunikat == u'Data „do” może być najwyżej 31 dni po dacie „od” (najpóźniej 01.11.2026).'


def test_granice_dat_przy_edycji(app):
    with app.app_context():
        t = _trasa()
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, {'name': 'A', 'date_from': '2029-01-01'})
        assert e.value.status == 422


def test_rok_przestepny_w_granicach_dat(app, monkeypatch):
    """29.02 minus rok → 28.02 (bez ValueError z date.replace)."""
    with app.app_context():
        monkeypatch.setattr(routes, 'dzis', lambda: date(2028, 2, 29))
        assert routes.granice_dat() == (date(2027, 2, 28), date(2030, 2, 28))


# --- M11: tylko RRRR-MM-DD, jednakowo na Pythonie 3.9 i 3.12 ---

@pytest.mark.parametrize('zla', [20261001, '20261001', '2026-W40-1', '2026-10-1', u'２０２６-10-01',
                                 '2026-10-01T00:00', ' 2026-10-01', '2026-02-30'])
def test_data_trasy_tylko_rrrr_mm_dd(app, zla):
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'A', 'date_from': zla})
        assert e.value.status == 422


# --- M1: dodanie do trasy widzi sposób dostawy zmieniony w międzyczasie ---

def test_dodanie_czyta_swiezy_sposob_dostawy(app):
    """M1: sposób zmieniony „za plecami” ORM-a (symulacja: druga transakcja zacommitowała
    kuriera, gdy ta czekała na blokadę) — dodaj_przystanki widzi bieżący stan
    (populate_existing), a nie kopię z identity mapy."""
    with app.app_context():
        t = _trasa()
        o = _transport()
        assert o.override_delivery_method == s.TRANSPORT      # obiekt wczytany do identity mapy
        db.session.execute(text("UPDATE prod_orders SET override_delivery_method = :k WHERE id = :i"),
                           {'k': s.KURIER, 'i': o.id})
        wynik = routes.dodaj_przystanki(t, [o.id])
        assert wynik['dodane'] == [] and 'transportu własnego' in wynik['bledy'][0]['komunikat']


# --- I5: zamówienia anulowane w całości ---

def test_dodanie_odrzuca_anulowane(app):
    with app.app_context():
        t = _trasa()
        o = _transport(statusy=('anulowane', 'anulowane'))
        wynik = routes.dodaj_przystanki(t, [o.id])
        assert wynik['dodane'] == []
        assert wynik['bledy'] == [{'order_id': o.id, 'komunikat':
                                   u'Zamówienie {} jest anulowane.'.format(o.internal_order_number)}]


def test_podsumowanie_i_numeracja_bez_anulowanych(app):
    """I5: przystanki = tylko aktywne, anulowane osobno; numer przystanku liczony wśród
    aktywnych (kolejność Routimo), anulowany bez numeru."""
    with app.app_context():
        t = _trasa()
        a, b, c = (_transport(statusy=('spakowane',)) for _ in range(3))
        routes.dodaj_przystanki(t, [a.id, b.id, c.id])
        for p in b.products:
            p.current_status = 'anulowane'
        db.session.commit()
        zamowienia = routes.zamowienia_trasy(t)
        sumy = routes.podsumowanie(t, zamowienia, {})
        assert (sumy['przystanki'], sumy['anulowane'], sumy['bez_lokalizacji']) == (2, 1, 2)
        assert sumy['m3'] == pytest.approx(2 * 0.048)
        assert [(o.id, nr, anul) for o, nr, anul in routes.numeracja_przystankow(zamowienia)] == [
            (a.id, 1, False), (b.id, None, True), (c.id, 2, False)]


# --- M3: brakujący wiersz blokady na MySQL zakłada się sam ---

def test_samonaprawa_wiersza_blokady(app, monkeypatch):
    """M3: baza po pierwszej wersji migracji (bez wiersza) — zablokuj_trasy zakłada wiersz
    (INSERT IGNORE w tej transakcji) i bierze na nim blokadę; kolejne wywołanie go nie dubluje.
    Na SQLite testów samonaprawę włączamy ręcznie (normalnie tylko MySQL)."""
    from modules.production.models import ProductionConfig
    with app.app_context():
        assert ProductionConfig.query.filter_by(config_key=routes.KLUCZ_BLOKADY).count() == 0
        monkeypatch.setattr(routes, '_samonaprawa_blokady', lambda: True)
        routes.zablokuj_trasy()
        routes.zablokuj_trasy()
        db.session.commit()
        wiersze = ProductionConfig.query.filter_by(config_key=routes.KLUCZ_BLOKADY).all()
        assert len(wiersze) == 1 and wiersze[0].config_type == 'string'


def test_bez_samonaprawy_poza_mysql(app):
    """Inne bazy niż MySQL (SQLite testów) — dalej fail-open z ostrzeżeniem, bez zakładania wiersza."""
    from modules.production.models import ProductionConfig
    with app.app_context():
        assert routes._samonaprawa_blokady() is False
        routes.zablokuj_trasy()
        assert ProductionConfig.query.filter_by(config_key=routes.KLUCZ_BLOKADY).count() == 0
