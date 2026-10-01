# -*- coding: utf-8 -*-
"""
Pisarze priorytetów bez blokady zamówienia: pozycje zapisują JEDNYM flushem, rosnąco po kluczu głównym
(logistyka etap 4, krok 4.4a, fala końcowa: I1 i priority_service).

ZAKOŃCZ i doróbka trzymają wiersz zamówienia i blokują wszystkie jego pozycje rosnąco po id
(services/blokady_zamowien.py). Pisarz, który zapisuje pozycje w innej kolejności, trzyma pozycję o wyższym id
i czeka na niższą, a ZAKOŃCZ odwrotnie — MySQL 1213. SQLite nie ma blokad, więc pilnujemy kolejności samych
UPDATE-ów `prod_products` (tests/blokady_pomocnicze.py): UPDATE zakłada blokadę X na wierszu.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
from sqlalchemy.orm import joinedload

from extensions import db
from modules.production.models import ProductionProduct
from modules.production.services import priority_service
from tests.blokady_pomocnicze import Zapytania, id_zapisow_pozycji
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _zamowienie_z_pozycjami(app, ile=2, status='czeka_na_krawedzie'):
    """Jedno zamówienie z `ile` pozycjami; id pozycji rosnąco."""
    pierwsza, _ = produkt(app, status=status)
    with app.app_context():
        wzor = db.session.get(ProductionProduct, pierwsza)
        ids = [pierwsza]
        for sekwencja in range(2, ile + 1):
            pozycja = ProductionProduct(
                order_id=wzor.order_id, configuration_id=wzor.configuration_id,
                short_product_id='%s_%d' % (wzor.short_product_id.split('_')[0], sekwencja),
                product_sequence_in_order=sekwencja, original_product_name='Blat dębowy',
                current_status=wzor.current_status, quantity=1, volume_m3=0.1,
                parsed_thickness_cm=4.0)
            db.session.add(pozycja)
            db.session.flush()
            ids.append(pozycja.id)
        db.session.commit()
    return ids


def _przeciagnij(client, wpisy):
    return client.post(BASE + '/update-priority', json={'products': wpisy})


# --- Przeciąganie priorytetów (POST /production/api/update-priority) -----------------------------------------

def test_przeciaganie_zapisuje_pozycje_rosnaco_po_id_niezaleznie_od_kolejnosci_zadania(app, client):
    """Żądanie [wyższe id, niższe id] (front wysyła pozycje w kolejności nowych rang, nie id): UPDATE niższego id
    idzie przed wyższym. Dawniej każde `query.get` autoflushowało poprzedni UPDATE, więc blokady szły w kolejności
    żądania — przeciąganie trzymało p_hi i czekało na p_lo, a ZAKOŃCZ tego zamówienia odwrotnie (1213)."""
    nizsze, srodkowe, wyzsze = _zamowienie_z_pozycjami(app, ile=3)
    with Zapytania() as z:
        r = _przeciagnij(client, [{'id': wyzsze, 'priority_rank': 1}, {'id': nizsze, 'priority_rank': 2},
                                  {'id': srodkowe, 'priority_rank': 3}])
    assert r.status_code == 200, r.get_data()[:300]
    assert id_zapisow_pozycji(z.lista) == [nizsze, srodkowe, wyzsze]


def test_przeciaganie_czyta_pozycje_jednym_zapytaniem_przed_pierwszym_zapisem(app, client):
    """Wszystkie pozycje z żądania jednym odczytem, potem same zapisy — bez odczytów przeplecionych z UPDATE-ami."""
    nizsze, wyzsze = _zamowienie_z_pozycjami(app)
    with Zapytania() as z:
        _przeciagnij(client, [{'id': wyzsze, 'priority_rank': 1}, {'id': nizsze, 'priority_rank': 2}])
    odczyty = [sql for sql, _p in z.lista if sql.startswith('SELECT') and 'FROM prod_products' in sql]
    assert len(odczyty) == 1, odczyty
    pierwszy_update = next(i for i, (sql, _p) in enumerate(z.lista) if sql.startswith('UPDATE prod_products'))
    assert not [sql for sql, _p in z.lista[pierwszy_update:] if sql.startswith('SELECT')]


def test_przeciaganie_odpowiedz_w_kolejnosci_zadania_i_zapisane_rangi(app, client):
    nizsze, wyzsze = _zamowienie_z_pozycjami(app)
    r = _przeciagnij(client, [{'id': wyzsze, 'priority_rank': 7}, {'id': nizsze, 'priority_rank': 8}])
    assert r.status_code == 200
    assert r.get_json() == {
        'success': True,
        'message': 'Zaktualizowano priorytety 2 produktów',
        'updated_count': 2,
        'updated_products': [{'id': wyzsze, 'new_priority_rank': 7}, {'id': nizsze, 'new_priority_rank': 8}],
    }
    with app.app_context():
        for pid, ranga in ((wyzsze, 7), (nizsze, 8)):
            pozycja = db.session.get(ProductionProduct, pid)
            assert (pozycja.priority_rank, pozycja.priority_manual_override) == (ranga, True)


def test_przeciaganie_pomija_brakujace_id_i_niepelne_wpisy(app, client):
    """Brakujące id i wpisy bez `id` albo bez `priority_rank` pomijamy po cichu, jak dotąd."""
    nizsze, wyzsze = _zamowienie_z_pozycjami(app)
    r = _przeciagnij(client, [{'id': 987654, 'priority_rank': 1}, {'priority_rank': 2}, {'id': nizsze},
                              {'id': wyzsze, 'priority_rank': 4}, {'id': nizsze, 'priority_rank': None}])
    assert r.status_code == 200
    assert r.get_json()['updated_products'] == [{'id': wyzsze, 'new_priority_rank': 4}]
    with app.app_context():
        assert db.session.get(ProductionProduct, nizsze).priority_rank is None
        assert db.session.get(ProductionProduct, wyzsze).priority_rank == 4


def test_przeciaganie_przyjmuje_id_jako_tekst(app, client):
    """`query.get('12')` znajdowało pozycję 12 — odczyt jednym zapytaniem też ją znajduje, a odpowiedź oddaje id
    tak, jak przyszło w żądaniu. Ułamek nie wskazywał żadnej pozycji i dalej nie wskazuje."""
    nizsze, wyzsze = _zamowienie_z_pozycjami(app)
    r = _przeciagnij(client, [{'id': str(wyzsze), 'priority_rank': 5}, {'id': '%d.5' % nizsze, 'priority_rank': 6}])
    assert r.get_json()['updated_products'] == [{'id': str(wyzsze), 'new_priority_rank': 5}]
    with app.app_context():
        assert db.session.get(ProductionProduct, wyzsze).priority_rank == 5
        assert db.session.get(ProductionProduct, nizsze).priority_rank is None


def test_zmiana_priorytetu_jednej_pozycji_bez_zmian(app, client):
    """Gałąź pojedyncza (`product_id`) zostaje jak była: 404 dla brakującej, zapis i odpowiedź dla istniejącej."""
    (pid,) = _zamowienie_z_pozycjami(app, ile=1)
    assert client.post(BASE + '/update-priority', json={'product_id': 987654, 'priority_rank': 3}).status_code == 404
    r = client.post(BASE + '/update-priority', json={'product_id': pid, 'priority_rank': 3})
    assert r.status_code == 200
    assert r.get_json()['updated_products'] == [{'id': pid, 'new_priority_rank': 3}]
    with app.app_context():
        pozycja = db.session.get(ProductionProduct, pid)
        assert (pozycja.priority_rank, pozycja.priority_manual_override) == (3, True)


# --- Przeliczenie priorytetów (priority_service.recalculate_all_priorities) ------------------------------------

def _aktywne_bez_isnull(kalkulator, monkeypatch):
    """`get_active_products_for_prioritization` sortuje przez MySQL-owe ISNULL(), które w SQLite jest operatorem
    (błąd składni) — podmieniamy samo zapytanie na równoważne bez sortowania po dacie opłacenia. Reszta
    przeliczenia (KROKI 2–8, własna sesja) zostaje prawdziwa."""
    def aktywne():
        return (kalkulator._sesja_robocza().query(ProductionProduct)
                .options(joinedload(ProductionProduct.order), joinedload(ProductionProduct.configuration))
                .filter(ProductionProduct.current_status.in_(kalkulator.active_statuses))
                .order_by(ProductionProduct.id).all())
    monkeypatch.setattr(kalkulator, 'get_active_products_for_prioritization', aktywne)


def test_przeliczenie_priorytetow_zapisuje_pozycje_jednym_flushem_rosnaco(app, monkeypatch):
    """KROK 2 (thickness_group) i KROK 7 (rangi) zmieniają te same pozycje. Zapytanie o zarezerwowane rangi między
    nimi autoflushowało grupy grubości osobno, więc pozycja o wyższym id (zmieniona grupa) była blokowana przed
    niższą (sama ranga): kolejność [wyższe, niższe, wyższe]. Teraz jeden flush przy commicie, rosnąco po id."""
    nizsze, wyzsze = _zamowienie_z_pozycjami(app, status='czeka_na_wyciecie')
    with app.app_context():
        kalkulator = priority_service.NewPriorityCalculator()
        _aktywne_bez_isnull(kalkulator, monkeypatch)
        db.session.get(ProductionProduct, nizsze).thickness_group = '3.6-4.5'   # zgodna z grubością 4 cm
        db.session.get(ProductionProduct, wyzsze).thickness_group = None        # do przeliczenia w KROKU 2
        db.session.commit()
        with Zapytania() as z:
            wynik = kalkulator.recalculate_all_priorities()
        assert wynik['success'] is True, wynik
        assert id_zapisow_pozycji(z.lista) == [nizsze, wyzsze]
        db.session.expire_all()
        wyzsza = db.session.get(ProductionProduct, wyzsze)
        assert wyzsza.thickness_group == '3.6-4.5'
        assert sorted(db.session.get(ProductionProduct, pid).priority_rank for pid in (nizsze, wyzsze)) == [1, 2]
