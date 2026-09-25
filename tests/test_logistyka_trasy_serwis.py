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
        routes.wykonaj(t)
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
        routes.wykonaj(t)
    db.session.commit()
    return t, o


@pytest.mark.parametrize('status, operacja', [
    ('robocza', lambda t: routes.edytuj(t, {'name': 'Nowa', 'date_from': '2026-10-01'})),
    ('robocza', lambda t: routes.zatwierdz(t)),
    ('zatwierdzona', lambda t: routes.cofnij_do_roboczej(t)),
    ('zatwierdzona', lambda t: routes.wykonaj(t)),
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
])
def test_zle_typy_w_danych_trasy(app, zle):
    with app.app_context():
        dane = dict({'date_from': '2026-10-01'}, **zle)
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz(dane)
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

        o1, o2 = _transport(), _transport()
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
        routes.wykonaj(t)
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
