# -*- coding: utf-8 -*-
"""
Drabina priorytetów: szczeble stałe, miejsce domyślne szczebla trasy, przesuwanie, samonaprawa (plan K1, Task 3;
spec 2026-10-04, sekcje 3.1, 4.4, 9.4). Zapisy drabiny idą pod blokadą tras (`routes.zablokuj_trasy`).

Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
import pytest

from extensions import db
from modules.production.logistics.models import Route
from modules.production.logistics.services import routes
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, PriorityRung
from modules.production.priorytety.services import drabina
from tests.blokady_pomocnicze import Zapytania, indeks_blokady_tras
from tests.logistyka_fixtures import app  # noqa: F401
from tests.priorytety_fixtures import drabina_domyslna

G5, G4, G3, G2, G1, G0 = [('stars', n) for n in (5, 4, 3, 2, 1, 0)]
PO_TERMINIE, BLISKO, ROZPOCZETE = [('tag', t) for t in stale.TAGI]
DOMYSLNA = list(stale.DRABINA_DOMYSLNA)


def _trasa(nazwa='Trasa', od='2026-10-01'):
    trasa = routes.utworz({'name': nazwa, 'date_from': od})
    db.session.commit()
    return trasa


def _klucze(szczeble=None):
    return [s.klucz for s in (drabina.szczeble() if szczeble is None else szczeble)]


def _wszystkie():
    return PriorityRung.query.order_by(PriorityRung.position).all()


def _szczebel(klucz):
    return next(s for s in _wszystkie() if s.klucz == klucz)


def _pozycje_ciagle():
    return [s.position for s in _wszystkie()] == list(range(1, PriorityRung.query.count() + 1))


def szczebel_do_zapisu(sql):
    return sql.startswith('SELECT') and 'FROM prod_priority_rungs' in sql and sql.endswith(' FOR UPDATE')


def test_seed_dziewieciu_szczebli_w_kolejnosci_3_1(app):
    drabina_domyslna()
    assert _klucze() == [G5, PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0]
    assert [s.position for s in drabina.szczeble()] == list(range(1, 10))


def test_utworz_zaklada_szczebel_pod_blokada_tras(app):
    drabina_domyslna()
    with Zapytania() as z:
        trasa = routes.utworz({'name': 'Śląsk', 'date_from': '2026-10-01'})
    wstawka = z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_priority_rungs'))
    assert indeks_blokady_tras(z) < wstawka
    # szczeble czytane do zapisu (FOR UPDATE) po blokadzie tras, a przed wstawieniem
    assert indeks_blokady_tras(z) < z.pierwsze(szczebel_do_zapisu) < wstawka
    db.session.commit()
    # tras nie było — szczebel tuż pod pięcioma gwiazdkami
    assert _klucze() == [G5, ('route', trasa.id), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0]
    assert _pozycje_ciagle()
    wpis = PriorityLog.query.one()
    assert (wpis.action, wpis.route_id, wpis.new_value, wpis.order_id) == ('szczebel', trasa.id, '2', None)


def test_druga_trasa_wchodzi_pod_najnizsza_trase(app):
    drabina_domyslna()
    t1, t2 = _trasa('Pierwsza'), _trasa('Druga', od='2026-10-02')
    assert _klucze()[:4] == [G5, ('route', t1.id), ('route', t2.id), PO_TERMINIE]
    # biuro przesuwa drugą trasę pod „bez gwiazdek” — trzecia wchodzi za nią, czyli pod NAJNIŻSZĄ trasę
    drabina.przesun(_szczebel(('route', t2.id)).id, 11)
    db.session.commit()
    t3 = _trasa('Trzecia', od='2026-10-03')
    assert _klucze() == [G5, ('route', t1.id), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0,
                         ('route', t2.id), ('route', t3.id)]
    assert _pozycje_ciagle()


def test_zapewnij_idempotentne(app):
    drabina_domyslna()
    trasa = _trasa()
    pierwszy = _szczebel(('route', trasa.id))
    assert drabina.zapewnij_szczebel_trasy(trasa).id == pierwszy.id
    db.session.commit()
    assert PriorityRung.query.filter_by(route_id=trasa.id).count() == 1
    assert PriorityRung.query.count() == 10
    assert PriorityLog.query.count() == 1


def test_przesun_tag_i_trase_renumeruje_1_n(app):
    drabina_domyslna()
    trasa = _trasa()
    # tag „Po terminie” na samą górę
    drabina.przesun(_szczebel(PO_TERMINIE).id, 1)
    db.session.commit()
    assert _klucze()[:3] == [PO_TERMINIE, G5, ('route', trasa.id)]
    # trasa pod ★★★ (pozycja 7 z 10)
    drabina.przesun(_szczebel(('route', trasa.id)).id, 7)
    db.session.commit()
    assert _klucze() == [PO_TERMINIE, G5, G4, BLISKO, ROZPOCZETE, G3, ('route', trasa.id), G2, G1, G0]
    # i w górę: „Rozpoczęte” nad „Blisko terminu”
    drabina.przesun(_szczebel(ROZPOCZETE).id, 4)
    db.session.commit()
    assert _klucze() == [PO_TERMINIE, G5, G4, ROZPOCZETE, BLISKO, G3, ('route', trasa.id), G2, G1, G0]
    # na koniec drabiny
    drabina.przesun(_szczebel(BLISKO).id, 10)
    db.session.commit()
    assert _klucze()[-2:] == [G0, BLISKO]
    assert _pozycje_ciagle()
    # szczeble gwiazdek nie zmieniły kolejności względem siebie
    assert [k for k in _klucze() if k[0] == 'stars'] == [G5, G4, G3, G2, G1, G0]


def test_przesun_na_te_sama_pozycje_nic_nie_zmienia(app):
    drabina_domyslna()
    szczebel = drabina.przesun(_szczebel(BLISKO).id, 4)
    assert szczebel.klucz == BLISKO
    assert _klucze() == DOMYSLNA
    assert PriorityLog.query.count() == 0


def test_przesun_gwiazdek_odmowa_szczebel_staly(app):
    drabina_domyslna()
    with pytest.raises(drabina.BladDrabiny) as e:
        drabina.przesun(_szczebel(G4).id, 1)
    assert (e.value.kod, e.value.status) == ('szczebel_staly', 400)
    assert e.value.komunikat
    assert _klucze() == DOMYSLNA


def test_przesun_nieznany_404(app):
    drabina_domyslna()
    with pytest.raises(drabina.BladDrabiny) as e:
        drabina.przesun(999999, 1)
    assert (e.value.kod, e.value.status) == ('brak_szczebla', 404)


def test_przesun_trasy_nieaktywnej_409(app):
    drabina_domyslna()
    trasa = _trasa()
    trasa.status = 'zaladowana'
    db.session.commit()
    with pytest.raises(drabina.BladDrabiny) as e:
        drabina.przesun(PriorityRung.query.filter_by(route_id=trasa.id).one().id, 1)
    assert (e.value.kod, e.value.status) == ('trasa_nieaktywna', 409)


@pytest.mark.parametrize('pozycja', [0, 10, -1, None, '2', 2.0, True])
def test_przesun_pozycja_poza_zakresem_400(app, pozycja):
    drabina_domyslna()
    with pytest.raises(drabina.BladDrabiny) as e:
        drabina.przesun(_szczebel(BLISKO).id, pozycja)
    assert (e.value.kod, e.value.status) == ('pozycja_poza_zakresem', 400)
    assert _klucze() == DOMYSLNA


def test_przesun_liczy_pozycje_wsrod_widocznych(app):
    """Szczebel trasy załadowanej jest ukryty: nie liczy się do pozycji docelowej i zostaje na swoim miejscu."""
    drabina_domyslna()
    ukryta, widoczna = _trasa('Ukryta'), _trasa('Widoczna', od='2026-10-02')
    ukryta.status = 'zaladowana'
    db.session.commit()
    assert _klucze()[:3] == [G5, ('route', widoczna.id), PO_TERMINIE]
    # 10 widocznych szczebli — pozycja 11 jest już poza zakresem, choć wierszy jest 11
    with pytest.raises(drabina.BladDrabiny):
        drabina.przesun(_szczebel(BLISKO).id, 11)
    drabina.przesun(_szczebel(BLISKO).id, 2)
    db.session.commit()
    assert _klucze()[:4] == [G5, BLISKO, ('route', widoczna.id), PO_TERMINIE]
    assert _pozycje_ciagle()
    # ukryty szczebel dalej stoi tuż pod pięcioma gwiazdkami
    assert [s.klucz for s in _wszystkie()][:3] == [G5, ('route', ukryta.id), BLISKO]


def test_przesun_bierze_blokade_tras_przed_szczeblami(app):
    drabina_domyslna()
    id_szczebla = _szczebel(BLISKO).id
    db.session.commit()
    with Zapytania() as z:
        drabina.przesun(id_szczebla, 2)
    assert indeks_blokady_tras(z) < z.pierwsze(szczebel_do_zapisu)
    assert z.pierwsze(szczebel_do_zapisu) < z.pierwsze(lambda sql: sql.startswith('UPDATE prod_priority_rungs'))
    # blokada tras jest pierwszym zapytaniem przesunięcia
    assert indeks_blokady_tras(z) == 0


def test_przesun_zapisuje_log_szczebel(app):
    drabina_domyslna()
    trasa = _trasa()
    PriorityLog.query.delete()
    db.session.commit()
    drabina.przesun(_szczebel(('route', trasa.id)).id, 5, user_id=7)
    drabina.przesun(_szczebel(PO_TERMINIE).id, 1, user_id=7)
    db.session.commit()
    wpisy = PriorityLog.query.order_by(PriorityLog.id).all()
    assert [(w.action, w.route_id, w.old_value, w.new_value, w.user_id) for w in wpisy] == [
        ('szczebel', trasa.id, '2', '5', 7), ('szczebel', None, '2', '1', 7)]
    assert wpisy[1].note == 'po_terminie'
    assert all(w.created_at is not None and w.order_id is None for w in wpisy)
    assert _szczebel(PO_TERMINIE).updated_by == 7


def test_szczebel_trasy_zaladowanej_ukryty_po_cofnieciu_wraca(app):
    drabina_domyslna()
    t1, t2 = _trasa('Pierwsza'), _trasa('Druga', od='2026-10-02')
    pozycja = _szczebel(('route', t1.id)).position
    t1.status = 'zaladowana'
    db.session.commit()
    assert ('route', t1.id) not in _klucze()
    assert ('route', t2.id) in _klucze()
    # wiersz zostaje — tylko widok go ukrywa
    assert PriorityRung.query.filter_by(route_id=t1.id).count() == 1
    for status in ('w_trasie', 'wykonana'):
        t1.status = status
        db.session.commit()
        assert ('route', t1.id) not in _klucze()
    # „Cofnij załadunek”: trasa znów zatwierdzona → szczebel w tym samym miejscu
    t1.status = 'zatwierdzona'
    db.session.commit()
    assert _klucze()[:3] == [G5, ('route', t1.id), ('route', t2.id)]
    assert _szczebel(('route', t1.id)).position == pozycja
    # odczyt bieżący (pod blokadą tras) widzi to samo
    routes.zablokuj_trasy()
    assert _klucze(drabina.szczeble(aktualny=True)) == _klucze()


def test_nowa_trasa_nie_liczy_ukrytej_jako_najnizszej(app):
    """Miejsce domyślne patrzy na trasy robocze/zatwierdzone: ukryty szczebel na dole drabiny nie ściąga tam nowej."""
    drabina_domyslna()
    stara = _trasa('Stara')
    drabina.przesun(_szczebel(('route', stara.id)).id, 10)
    stara.status = 'w_trasie'
    db.session.commit()
    nowa = _trasa('Nowa', od='2026-10-02')
    assert _klucze()[:2] == [G5, ('route', nowa.id)]


def test_usun_trase_usuwa_szczebel_i_renumeruje(app):
    drabina_domyslna()
    t1, t2 = _trasa('Pierwsza'), _trasa('Druga', od='2026-10-02')
    id_t1 = t1.id
    routes.usun(t1)
    db.session.commit()
    assert Route.query.get(id_t1) is None
    assert PriorityRung.query.filter_by(route_id=id_t1).count() == 0
    assert _klucze()[:3] == [G5, ('route', t2.id), PO_TERMINIE]
    assert _pozycje_ciagle()
    # trasa bez szczebla (okno wdrożenia) też daje się usunąć
    PriorityRung.query.filter_by(route_id=t2.id).delete()
    db.session.commit()
    assert drabina.usun_szczebel_trasy(t2.id) is False
    routes.usun(t2)
    db.session.commit()
    assert _klucze() == DOMYSLNA


def test_uzupelnij_dopisuje_brakujace_trasy_i_szczeble_stale(app):
    # Baza z okna wdrożenia: trasy już są, szczebli nie ma wcale.
    t1, t2 = _trasa('Pierwsza'), _trasa('Druga', od='2026-10-02')
    zaladowana = _trasa('Załadowana', od='2026-10-03')
    zaladowana.status = 'zaladowana'
    PriorityRung.query.delete()
    PriorityLog.query.delete()
    db.session.commit()

    with Zapytania() as z:
        assert drabina.uzupelnij(user_id=3) == 11
    assert indeks_blokady_tras(z) == 0
    assert indeks_blokady_tras(z) < z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_priority_rungs'))
    db.session.commit()
    # szczeble stałe jak seed, trasy w miejscu domyślnym w kolejności id; trasa załadowana bez szczebla
    assert _klucze() == [G5, ('route', t1.id), ('route', t2.id), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0]
    assert PriorityRung.query.count() == 11
    assert _pozycje_ciagle()
    assert drabina.uzupelnij() == 0
    db.session.commit()
    assert PriorityRung.query.count() == 11

    # brakuje jednego tagu i jednej trasy: tag dochodzi na końcu, trasa pod najniższą trasą
    PriorityRung.query.filter(PriorityRung.tag == 'rozpoczete').delete()
    PriorityRung.query.filter(PriorityRung.route_id == t2.id).delete()
    db.session.commit()
    assert drabina.uzupelnij() == 2
    db.session.commit()
    assert _klucze() == [G5, ('route', t1.id), ('route', t2.id), PO_TERMINIE, G4, BLISKO, G3, G2, G1, G0, ROZPOCZETE]
    assert _pozycje_ciagle()


def test_uzupelnij_zgodne_z_policz_dla_trasy_bez_szczebla(app):
    """`policz` liczy trasę bez szczebla tam, gdzie `uzupelnij` potem go wstawi — ranga nie skacze po samonaprawie."""
    from datetime import date
    from modules.production.priorytety.services import kolejka
    drabina_domyslna()
    t1, t2, t3 = _trasa('A'), _trasa('B', od='2026-10-02'), _trasa('C', od='2026-10-03')
    drabina.przesun(_szczebel(('route', t1.id)).id, 8)
    PriorityRung.query.filter(PriorityRung.route_id.in_([t2.id, t3.id])).delete(synchronize_session=False)
    db.session.commit()
    szczeble = [kolejka.Szczebel(s.id, s.kind, s.stars, s.tag, s.route_id, s.position) for s in _wszystkie()]
    trasy = {t.id: kolejka.Trasa(t.id, t.name, t.date_from, t.status) for t in (t1, t2, t3)}
    wynik = kolejka.policz(kolejka.Migawka(
        dzis=date(2026, 10, 5), prog_blisko_dni=3,
        zamowienia={1: kolejka.Zamowienie(1, '1001', 0, None, None), 2: kolejka.Zamowienie(2, '1002', 0, None, None)},
        pozycje=[kolejka.Pozycja(11, 1, 'czeka_na_sklejanie', None, 1, False, None, None, False, False),
                 kolejka.Pozycja(12, 2, 'czeka_na_sklejanie', None, 1, False, None, None, False, False)],
        trasa_zamowienia={1: t3.id, 2: t2.id}, trasy=trasy, szczeble=szczeble))
    assert drabina.uzupelnij() == 2
    db.session.commit()
    assert _klucze() == wynik.drabina


def test_pozycja_tagu_rozpoczete(app):
    assert drabina.pozycja_tagu('rozpoczete') is None        # baza bez szczebli
    drabina_domyslna()
    assert drabina.pozycja_tagu('rozpoczete') == 5
    assert drabina.pozycja_tagu('po_terminie') == 2
    trasa = _trasa()
    assert drabina.pozycja_tagu('rozpoczete') == 6           # szczebel trasy wszedł pod ★★★★★
    assert drabina.pozycja_szczebla(_szczebel(('route', trasa.id))) == 2
    assert drabina.pozycja_szczebla(_szczebel(G0)) == 10
    trasa.status = 'zaladowana'
    db.session.commit()
    # numeracja liczy tylko widoczne szczeble
    assert drabina.pozycja_tagu('rozpoczete') == 5
    assert drabina.pozycja_szczebla(PriorityRung.query.filter_by(route_id=trasa.id).one()) is None
    assert drabina.pozycja_tagu('nie_ma_takiego') is None


def test_miejsce_domyslne(app):
    drabina_domyslna()
    wszystkie = _wszystkie()
    assert drabina.miejsce_domyslne(wszystkie, set()) == 1               # tuż za ★★★★★
    t1 = _trasa()
    wszystkie = _wszystkie()
    assert drabina.miejsce_domyslne(wszystkie, {t1.id}) == 2             # za szczeblem trasy
    assert drabina.miejsce_domyslne(wszystkie, set()) == 1               # trasa nieaktywna się nie liczy
    assert drabina.miejsce_domyslne([], set()) == 0                      # pusta drabina


def test_serwis_nie_commituje(app):
    drabina_domyslna()
    trasa = _trasa()
    db.session.commit()
    drabina.przesun(_szczebel(BLISKO).id, 1, user_id=1)
    drabina.usun_szczebel_trasy(trasa.id)
    PriorityRung.query.filter(PriorityRung.tag == 'rozpoczete').delete()
    drabina.uzupelnij()
    db.session.rollback()
    assert _klucze() == [G5, ('route', trasa.id), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0]
    assert PriorityLog.query.count() == 1        # tylko wpis z utworzenia trasy
