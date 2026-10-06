# -*- coding: utf-8 -*-
"""
Czysta część algorytmu priorytetów: `kolejka.policz` (ranga zamówień i pozycji) i `kolejka.kandydaci_stanowiska`
(kolejność kafli stanowiska). Plan K1, Task 2; spec 2026-10-04, sekcje 3.1–3.3, 4.2, 4.5, 5.6.

Bez Flaska i bez bazy — same struktury (namedtuple). Daty z października 2026: „dziś” to poniedziałek 5.10.
"""
from datetime import date, datetime

from modules.production.priorytety import stale
from modules.production.priorytety.services import kolejka

DZIS = date(2026, 10, 5)            # poniedziałek
G5, G4, G3, G2, G1, G0 = [('stars', n) for n in (5, 4, 3, 2, 1, 0)]
PO_TERMINIE, BLISKO, ROZPOCZETE = [('tag', t) for t in stale.TAGI]
DOMYSLNA = list(stale.DRABINA_DOMYSLNA)


def drabina(*klucze):
    """Szczeble w podanej kolejności, `position` 1..n."""
    return [kolejka.Szczebel(id=i, kind=k[0], stars=k[1] if k[0] == 'stars' else None,
                             tag=k[1] if k[0] == 'tag' else None, route_id=k[1] if k[0] == 'route' else None,
                             position=i)
            for i, k in enumerate(klucze, start=1)]


def trasa(id, status='robocza', name=None, date_from=date(2026, 10, 12)):
    return kolejka.Trasa(id=id, name=name or 'Trasa %d' % id, date_from=date_from, status=status)


def zam(id, gwiazdki=0, numer=None, rank=None, rung=None):
    return kolejka.Zamowienie(id=id, numer=numer or str(1000 + id), gwiazdki=gwiazdki, rank=rank, rung=rung)


def poz(id, order_id, status='czeka_na_sklejanie', termin=None, sequence=1, dorobka=False, created_at=None,
        rank=None, is_priority=False, manual_override=False):
    return kolejka.Pozycja(id=id, order_id=order_id, status=status, deadline_date=termin, sequence=sequence,
                           dorobka=dorobka, created_at=created_at, rank=rank, is_priority=is_priority,
                           manual_override=manual_override)


def migawka(zamowienia, pozycje, szczeble=None, trasy=(), trasa_zamowienia=None, dzis=DZIS, prog=3):
    return kolejka.Migawka(
        dzis=dzis, prog_blisko_dni=prog,
        zamowienia={z.id: z for z in zamowienia},
        pozycje=list(pozycje),
        trasa_zamowienia=dict(trasa_zamowienia or {}),
        trasy={t.id: t for t in trasy},
        szczeble=drabina(*DOMYSLNA) if szczeble is None else szczeble)


def kolejnosc(wynik):
    """Id zamówień w kolejności rangi."""
    return [oid for oid, _ in sorted(wynik.zamowienia.items(), key=lambda para: para[1].rank)]


# ── pomocnicze czyste ─────────────────────────────────────────────────────────────────────────────────────────

def test_dodaj_dni_robocze_pomija_weekend():
    piatek = date(2026, 10, 9)
    assert kolejka.dodaj_dni_robocze(piatek, 1) == date(2026, 10, 12)
    assert kolejka.dodaj_dni_robocze(piatek, 3) == date(2026, 10, 14)
    assert kolejka.dodaj_dni_robocze(piatek, 0) == piatek
    assert kolejka.dodaj_dni_robocze(DZIS, 16) == date(2026, 10, 27)


def test_termin_zamowienia_to_najblizszy_termin_pozycji_aktywnych():
    pozycje = [poz(1, 1, termin=date(2026, 10, 20)), poz(2, 1, termin=date(2026, 10, 15)),
               # spakowana, wstrzymana i anulowana nie wyciągają terminu
               poz(3, 1, status='spakowane', termin=date(2026, 10, 1)),
               poz(4, 1, status='wstrzymane', termin=date(2026, 10, 2)),
               poz(5, 1, status='anulowane', termin=date(2026, 10, 3)),
               poz(6, 1, termin=None)]
    assert kolejka.termin_zamowienia(pozycje) == date(2026, 10, 15)
    assert kolejka.termin_zamowienia([poz(1, 1, termin=None)]) is None
    assert kolejka.termin_zamowienia([]) is None

    class Orm(object):                      # ProductionProduct ma status w `current_status`
        def __init__(self, status, termin):
            self.current_status, self.deadline_date = status, termin
    assert kolejka.termin_zamowienia([Orm('czeka_na_pakowanie', date(2026, 10, 9)),
                                      Orm('dostarczone', date(2026, 10, 1))]) == date(2026, 10, 9)


def test_rozpoczete_wymaga_pozycji_na_stanowisku_zamowieniowym_i_wczesniejszej():
    assert kolejka.rozpoczete(('czeka_na_formatowanie', 'czeka_na_sklejanie')) is True
    assert kolejka.rozpoczete(('czeka_na_krawedzie', 'czeka_na_wyciecie')) is True
    assert kolejka.rozpoczete(('spakowane', 'czeka_na_lakiernie')) is True
    assert kolejka.rozpoczete(('czeka_na_pakowanie', 'czeka_na_krawedzie')) is True
    # wszystko przed Formatowaniem albo wszystko na jednym etapie — nic na nic nie czeka
    assert kolejka.rozpoczete(('czeka_na_sklejanie', 'czeka_na_wyciecie')) is False
    assert kolejka.rozpoczete(('czeka_na_formatowanie', 'czeka_na_formatowanie')) is False
    assert kolejka.rozpoczete(('czeka_na_pakowanie', 'spakowane')) is False
    assert kolejka.rozpoczete(('czeka_na_sklejanie',)) is False
    assert kolejka.rozpoczete(()) is False
    # anulowane i wstrzymane nie liczą się ani jako „dalej”, ani jako „wcześniej”
    assert kolejka.rozpoczete(('czeka_na_formatowanie', 'anulowane', 'wstrzymane')) is False


def test_tagi_zamowienia():
    statusy = ('czeka_na_sklejanie',)
    assert kolejka.tagi_zamowienia(statusy, date(2026, 10, 2), DZIS, 3) == {'po_terminie'}
    assert kolejka.tagi_zamowienia(statusy, DZIS, DZIS, 3) == {'blisko_terminu'}
    assert kolejka.tagi_zamowienia(statusy, date(2026, 10, 8), DZIS, 3) == {'blisko_terminu'}
    assert kolejka.tagi_zamowienia(statusy, date(2026, 10, 9), DZIS, 3) == set()
    assert kolejka.tagi_zamowienia(statusy, None, DZIS, 3) == set()
    assert kolejka.tagi_zamowienia(('czeka_na_formatowanie', 'czeka_na_sklejanie'), date(2026, 10, 2), DZIS, 3) == {
        'po_terminie', 'rozpoczete'}


def test_kompletne_na_stanowisku():
    assert kolejka.kompletne_na_stanowisku(('czeka_na_formatowanie', 'czeka_na_krawedzie', 'spakowane'),
                                           'formatting') is True
    assert kolejka.kompletne_na_stanowisku(('czeka_na_formatowanie', 'czeka_na_sklejanie'), 'formatting') is False
    assert kolejka.kompletne_na_stanowisku(('czeka_na_pakowanie', 'czeka_na_lakiernie'), 'packaging') is False
    assert kolejka.kompletne_na_stanowisku(('czeka_na_pakowanie', 'czeka_na_logistyke', 'zweryfikowane'),
                                           'packaging') is True
    assert kolejka.kompletne_na_stanowisku(('czeka_na_formatowanie', 'wstrzymane', 'anulowane'),
                                           'formatting') is True


def test_kompletne_na_stanowisku_pomija_omijajace():
    """K3-poprawka-1 (spec 5.6 p. 2): pozycja, której ścieżka omija stanowisko (bez docięcia nie idzie na
    Formatowanie), nie liczy się do jego kompletności, nawet gdy stoi jeszcze wcześniej. `omija` — flagi równoległe
    do `statusy`."""
    statusy = ('czeka_na_formatowanie', 'czeka_na_sklejanie')
    assert kolejka.kompletne_na_stanowisku(statusy, 'formatting') is False
    assert kolejka.kompletne_na_stanowisku(statusy, 'formatting', omija=(False, True)) is True
    # inna, zwykła pozycja wcześniej dalej blokuje
    assert kolejka.kompletne_na_stanowisku(statusy + ('czeka_na_wyciecie',), 'formatting',
                                           omija=(False, True, False)) is False
    assert kolejka.kompletne_na_stanowisku(statusy, 'formatting', omija=(True, False)) is False


def test_liczone_na_stanowisku():
    pary = ((1, 'czeka_na_formatowanie'), (2, 'czeka_na_sklejanie'), (3, 'anulowane'), (4, 'wstrzymane'),
            (5, 'czeka_na_pakowanie'), (6, 'czeka_na_formatowanie'))
    assert kolejka.liczone_na_stanowisku(pary, 'formatting') == [
        (1, 'czeka_na_formatowanie'), (2, 'czeka_na_sklejanie'), (5, 'czeka_na_pakowanie'),
        (6, 'czeka_na_formatowanie')]
    # omijające znikają z liczenia — poza pozycją, która mimo to STOI na stanowisku (ręczna zmiana statusu)
    assert kolejka.liczone_na_stanowisku(pary, 'formatting', omijajace={2, 5, 6}) == [
        (1, 'czeka_na_formatowanie'), (6, 'czeka_na_formatowanie')]


def test_klucz_zamowienia_numer_porzadkuje_liczbowo():
    k = kolejka.klucz_zamowienia
    assert k(1, 2, date(2026, 10, 17), '1001') < k(1, 0, date(2026, 10, 10), '1000')      # gwiazdki przed terminem
    assert k(1, 0, date(2026, 10, 17), '1001') < k(1, 0, date(2026, 10, 21), '1000')      # termin przed numerem
    assert k(1, 0, date(2026, 10, 17), '1001') < k(1, 0, None, '1000')                    # brak terminu na końcu
    assert k(1, 0, None, '9999') < k(1, 0, None, '10000')                                 # numer liczbowo
    assert k(1, 0, None, '26/00001') < k(1, 0, None, '26/00002')
    assert k(3, 5, date(2026, 10, 1), '1') > k(2, 0, None, '2')                           # szczebel najpierw


# ── policz: ranga zamówień ────────────────────────────────────────────────────────────────────────────────────

def test_policz_tabela_3_3():
    """Tabela ze specu 3.3 jeden do jednego: trasa decyduje mimo ★★★★★, tag wyciąga ponad gwiazdki."""
    SLASK, MAZOWSZE, POMORZE = 11, 12, 13
    # Drabina biura z 3.3 (11 szczebli). Tag „Rozpoczęte” (dodany do specu później) stoi tu na końcu, żeby
    # numeracja szczebli przykładu została bez zmian.
    szczeble = drabina(('route', SLASK), G5, PO_TERMINIE, G4, ('route', MAZOWSZE), BLISKO, G3,
                       ('route', POMORZE), G2, G1, G0, ROZPOCZETE)
    A, B, C, D, E, F, G, H = range(1, 9)
    zamowienia = [zam(A, 2), zam(B, 0), zam(C, 5), zam(D, 4), zam(E, 3), zam(F, 5), zam(G, 0), zam(H, 1)]
    terminy = {A: date(2026, 10, 17), B: date(2026, 10, 21), C: date(2026, 10, 20), D: date(2026, 10, 24),
               E: date(2026, 10, 6), F: date(2026, 10, 27), G: date(2026, 10, 27), H: date(2026, 10, 2)}
    pozycje = [poz(100 + oid, oid, termin=t) for oid, t in terminy.items()]
    wynik = kolejka.policz(migawka(
        zamowienia, pozycje, szczeble=szczeble,
        trasy=[trasa(SLASK), trasa(MAZOWSZE, status='zatwierdzona'), trasa(POMORZE)],
        trasa_zamowienia={A: SLASK, B: SLASK, D: MAZOWSZE, F: POMORZE}))

    assert kolejnosc(wynik) == [A, B, C, H, D, E, F, G]
    assert [wynik.zamowienia[o].rank for o in (A, B, C, H, D, E, F, G)] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert {o: wynik.zamowienia[o].rung for o in terminy} == {A: 1, B: 1, C: 2, H: 3, D: 5, E: 6, F: 8, G: 11}
    assert {o: wynik.zamowienia[o].szczebel for o in terminy} == {
        A: 'trasa', B: 'trasa', C: 'gwiazdki', H: 'po_terminie', D: 'trasa', E: 'blisko_terminu', F: 'trasa',
        G: 'gwiazdki'}
    # F ma pięć gwiazdek, a idzie siódme — trasa decyduje.
    assert wynik.zamowienia[F].rank == 7
    # H (jedna gwiazdka, po terminie) ponad D (cztery gwiazdki).
    assert wynik.zamowienia[H].rank < wynik.zamowienia[D].rank
    assert wynik.zamowienia[A].termin == date(2026, 10, 17)
    assert 'po_terminie' in wynik.zamowienia[H].tagi and 'blisko_terminu' in wynik.zamowienia[E].tagi
    assert wynik.ostrzezenia == []
    assert wynik.drabina == [('route', SLASK), G5, PO_TERMINIE, G4, ('route', MAZOWSZE), BLISKO, G3,
                             ('route', POMORZE), G2, G1, G0, ROZPOCZETE]


def test_w_trasie_gwiazdki_potem_termin():
    szczeble = drabina(G5, ('route', 7), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0)
    zamowienia = [zam(1, 0), zam(2, 3), zam(3, 3), zam(4, 0)]
    pozycje = [poz(11, 1, termin=date(2026, 10, 12)), poz(12, 2, termin=date(2026, 10, 30)),
               poz(13, 3, termin=date(2026, 10, 20)), poz(14, 4, termin=date(2026, 10, 2))]
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=szczeble, trasy=[trasa(7)],
                                   trasa_zamowienia={1: 7, 2: 7, 3: 7, 4: 7}))
    # ★★★ przed bez gwiazdek; w ★★★ wcześniejszy termin; bez gwiazdek: po terminie (4) przed 12.10 (1) —
    # ale tag nie wyciąga zamówienia 4 ponad trasę ani ponad gwiazdki w trasie.
    assert kolejnosc(wynik) == [3, 2, 4, 1]
    assert {r.rung for r in wynik.zamowienia.values()} == {2}
    assert {r.szczebel for r in wynik.zamowienia.values()} == {'trasa'}


def test_termin_rozjemca_w_szczeblu_gwiazdek():
    zamowienia = [zam(1, 2, numer='1001'), zam(2, 2, numer='1002'), zam(3, 2, numer='1003'),
                  zam(4, 2, numer='1000')]
    pozycje = [poz(11, 1, termin=date(2026, 10, 30)), poz(12, 2, termin=date(2026, 10, 20)),
               poz(13, 3, termin=date(2026, 10, 20)), poz(14, 4, termin=date(2026, 10, 30))]
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    # termin, a przy równym terminie numer zamówienia
    assert kolejnosc(wynik) == [2, 3, 4, 1]
    assert {r.rung for r in wynik.zamowienia.values()} == {7}       # ★★ w domyślnej drabinie


def test_blisko_terminu_dni_robocze_prog_3():
    piatek = date(2026, 10, 9)
    zamowienia = [zam(1), zam(2), zam(3), zam(4)]
    pozycje = [poz(11, 1, termin=date(2026, 10, 14)),       # środa = piątek + 3 dni robocze → tag
               poz(12, 2, termin=date(2026, 10, 15)),       # czwartek — za progiem
               poz(13, 3, termin=piatek),                   # dziś → tag
               poz(14, 4, termin=date(2026, 10, 8))]        # wczoraj → po terminie, nie „blisko”
    wynik = kolejka.policz(migawka(zamowienia, pozycje, dzis=piatek, prog=3))
    assert wynik.zamowienia[1].szczebel == 'blisko_terminu'
    assert wynik.zamowienia[2].szczebel == 'gwiazdki'
    assert wynik.zamowienia[3].szczebel == 'blisko_terminu'
    assert wynik.zamowienia[4].szczebel == 'po_terminie'
    assert wynik.zamowienia[4].tagi == ('po_terminie',)
    assert kolejnosc(wynik) == [4, 3, 1, 2]
    # próg z ustawień: przy 5 dniach czwartek też łapie tag
    wynik = kolejka.policz(migawka(zamowienia, pozycje, dzis=piatek, prog=5))
    assert wynik.zamowienia[2].szczebel == 'blisko_terminu'


def test_zamowienie_bez_terminu_na_koncu_szczebla():
    zamowienia = [zam(1, numer='1001'), zam(2, numer='1002'), zam(3, numer='1003')]
    pozycje = [poz(11, 1, termin=None), poz(12, 2, termin=date(2026, 11, 30)), poz(13, 3, termin=None)]
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    assert kolejnosc(wynik) == [2, 1, 3]
    assert wynik.zamowienia[1].termin is None
    assert wynik.zamowienia[1].tagi == ()               # bez terminu tagi terminowe nie działają


def test_rangi_pozycji_rank_razy_100_plus_sekwencja_dorobki_zero():
    zamowienia = [zam(1, 5), zam(2, 0)]
    pozycje = [poz(11, 1, sequence=1), poz(12, 1, sequence=2), poz(13, 1, sequence=3, dorobka=True),
               poz(21, 2, sequence=1), poz(22, 2, sequence=7),
               # ponad 99 pozycji w zamówieniu nie może wejść w numerację następnego zamówienia
               poz(23, 2, sequence=150)]
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    assert wynik.zamowienia[1].rank == 1 and wynik.zamowienia[2].rank == 2
    assert {pid: r for pid, (r, _flaga) in wynik.pozycje.items()} == {
        11: 101, 12: 102, 13: 0, 21: 201, 22: 207, 23: 299}


def test_is_priority_pochodna():
    zamowienia = [zam(1, 1), zam(2, 0), zam(3, 0), zam(4, 0)]
    pozycje = [poz(11, 1, termin=date(2026, 11, 30)),                      # gwiazdka
               poz(12, 2, termin=date(2026, 10, 1)),                       # po terminie
               poz(13, 3, termin=date(2026, 11, 30), dorobka=True),        # doróbka
               poz(14, 3, termin=date(2026, 11, 30), sequence=2),          # reszta zamówienia z doróbką — nie
               poz(15, 4, termin=date(2026, 10, 6))]                       # blisko terminu — nie
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    assert {pid: flaga for pid, (_r, flaga) in wynik.pozycje.items()} == {
        11: True, 12: True, 13: True, 14: False, 15: False}


def test_pozycje_nieaktywne_poza_wynikiem():
    zamowienia = [zam(1), zam(2), zam(3)]
    pozycje = [poz(11, 1), poz(12, 1, status='spakowane', sequence=2), poz(13, 1, status='anulowane', sequence=3),
               poz(14, 1, status='wstrzymane', sequence=4), poz(15, 1, status='w_realizacji', sequence=5),
               poz(16, 1, status='czeka_na_logistyke', sequence=6),
               # zamówienia bez pozycji w produkcji nie są aktywne
               poz(21, 2, status='spakowane'), poz(31, 3, status='wstrzymane')]
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    assert set(wynik.zamowienia) == {1}
    assert set(wynik.pozycje) == {11}


def test_trasa_bez_szczebla_w_miejscu_domyslnym_z_ostrzezeniem():
    zamowienia = [zam(1), zam(2, 5), zam(3)]
    pozycje = [poz(11, 1), poz(12, 2), poz(13, 3)]
    # bez innych tras: wirtualny szczebel tuż pod ★★★★★
    wynik = kolejka.policz(migawka(zamowienia, pozycje, trasy=[trasa(7)], trasa_zamowienia={1: 7}))
    assert wynik.drabina == [G5, ('route', 7)] + DOMYSLNA[1:]
    assert wynik.zamowienia[1].rung == 2 and wynik.zamowienia[1].szczebel == 'trasa'
    assert kolejnosc(wynik) == [2, 1, 3]
    assert len(wynik.ostrzezenia) == 1 and '7' in wynik.ostrzezenia[0]

    # z trasą na drabinie (przesuniętą pod ★★★): nowa wchodzi pod najniższą trasę, kolejne za nią po id
    szczeble = drabina(G5, PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, ('route', 7), G2, G1, G0)
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=szczeble,
                                   trasy=[trasa(7), trasa(9), trasa(8)], trasa_zamowienia={1: 7, 3: 9}))
    assert wynik.drabina == [G5, PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, ('route', 7), ('route', 9), G2, G1, G0]
    assert wynik.zamowienia[3].rung == 8
    # trasa 8 nie ma zamówień w produkcji — policz jej nie dokłada (dopisze ją drabina.uzupelnij)
    assert len(wynik.ostrzezenia) == 1


def test_brak_szczebli_stalych_uzupelniany_domyslnie():
    zamowienia = [zam(1, 5), zam(2, 0), zam(3, 3)]
    pozycje = [poz(11, 1), poz(12, 2, termin=date(2026, 10, 1)), poz(13, 3)]
    # pusta tabela szczebli (baza testowa bez seedu): drabina domyślna
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=[]))
    assert wynik.drabina == DOMYSLNA
    assert kolejnosc(wynik) == [1, 2, 3]
    assert wynik.zamowienia[2].rung == 2
    assert len(wynik.ostrzezenia) == 9
    # brakuje pojedynczych szczebli: dopisane na końcu w kolejności domyślnej
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=drabina(G5, G4, G3, G2, G1, G0)))
    assert wynik.drabina == [G5, G4, G3, G2, G1, G0, PO_TERMINIE, BLISKO, ROZPOCZETE]
    assert wynik.zamowienia[2].szczebel == 'gwiazdki'       # ★0 (6) stoi wyżej niż dopisany tag (7)
    assert len(wynik.ostrzezenia) == 3


def test_trasa_zaladowana_nie_liczy_sie_jako_trasa():
    szczeble = drabina(G5, ('route', 7), PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0)
    zamowienia = [zam(1, 3), zam(2, 0)]
    pozycje = [poz(11, 1), poz(12, 2)]
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=szczeble, trasy=[trasa(7, status='zaladowana')],
                                   trasa_zamowienia={1: 7}))
    # szczebel trasy załadowanej jest ukryty: drabina liczona bez niego, zamówienie na szczeblu gwiazdek
    assert wynik.drabina == DOMYSLNA
    assert wynik.zamowienia[1].szczebel == 'gwiazdki' and wynik.zamowienia[1].rung == 6
    assert wynik.ostrzezenia == []
    # szczebel, którego trasy migawka w ogóle nie zna (wykonana, usunięta) — tak samo ukryty
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=szczeble))
    assert wynik.drabina == DOMYSLNA


def test_rozpoczete_po_statusach_nie_po_nazwie_stanowiska():
    # Pozycja bez docięcia idzie ze Sklejania prosto do pakowania (omija Formatowanie), druga jeszcze na Sklejaniu.
    zamowienia = [zam(1), zam(2), zam(3, 3)]
    pozycje = [poz(11, 1, status='czeka_na_pakowanie'), poz(12, 1, status='czeka_na_sklejanie', sequence=2),
               poz(21, 2, status='czeka_na_sklejanie'),
               poz(31, 3, status='czeka_na_sklejanie')]
    wynik = kolejka.policz(migawka(zamowienia, pozycje))
    assert wynik.zamowienia[1].szczebel == 'rozpoczete' and wynik.zamowienia[1].rung == 5
    assert wynik.zamowienia[2].szczebel == 'gwiazdki' and wynik.zamowienia[2].rung == 9
    # Rozpoczęte (5) stoi nad ★★★ (6)
    assert kolejnosc(wynik) == [1, 3, 2]
    # spakowana pozycja też znaczy „rozpoczęte”, choć sama nie jest już w produkcji
    pozycje[0] = poz(11, 1, status='spakowane')
    assert kolejka.policz(migawka(zamowienia, pozycje)).zamowienia[1].szczebel == 'rozpoczete'


def test_rozpoczete_na_trasie_nie_zmienia_szczebla():
    szczeble = drabina(G5, PO_TERMINIE, G4, BLISKO, ROZPOCZETE, G3, G2, G1, G0, ('route', 7))
    zamowienia = [zam(1)]
    pozycje = [poz(11, 1, status='czeka_na_formatowanie'), poz(12, 1, status='czeka_na_sklejanie', sequence=2)]
    wynik = kolejka.policz(migawka(zamowienia, pozycje, szczeble=szczeble, trasy=[trasa(7)],
                                   trasa_zamowienia={1: 7}))
    assert wynik.zamowienia[1].szczebel == 'trasa' and wynik.zamowienia[1].rung == 10
    assert 'rozpoczete' in wynik.zamowienia[1].tagi


def test_gwiazdki_spoza_zakresu_nie_wywracaja_przeliczenia():
    zamowienia = [zam(1, 9), zam(2, None), zam(3, -2)]
    wynik = kolejka.policz(migawka(zamowienia, [poz(11, 1), poz(12, 2), poz(13, 3)]))
    assert wynik.zamowienia[1].rung == 1 and wynik.zamowienia[2].rung == 9 and wynik.zamowienia[3].rung == 9


# ── kandydaci_stanowiska: kafle-pozycje ───────────────────────────────────────────────────────────────────────

def ps(id, order_id, wymiary, numer=None, termin=None, gwiazdki=0, rung=9, rank=None, na_trasie=False,
       status='czeka_na_sklejanie', gatunek='dąb', klasa='A/B', dorobka=False, created_at=None, sequence=None):
    dlugosc, szerokosc, grubosc = wymiary
    return kolejka.PozycjaStanowiska(
        id=id, order_id=order_id, status=status, dorobka=dorobka, created_at=created_at,
        sequence=sequence if sequence is not None else id % 100, gatunek=gatunek, klasa=klasa, grubosc=grubosc,
        dlugosc=dlugosc, szerokosc=szerokosc, numer=numer or str(1000 + order_id), gwiazdki=gwiazdki, termin=termin,
        rung=rung, rank=rank, na_trasie=na_trasie)


def statusy(pozycje, **inne):
    """{order_id: ((product_id, status), …)} z pozycji stanowiska + dodatkowe pozycje zamówień spoza stanowiska:
    `inne` = {'o<order_id>': [(product_id, status), …]}."""
    wynik = {}
    for p in pozycje:
        wynik.setdefault(p.order_id, []).append((p.id, p.status))
    for klucz, pary in inne.items():
        wynik.setdefault(int(klucz[1:]), []).extend(pary)
    return {oid: tuple(pary) for oid, pary in wynik.items()}


def test_kandydaci_przyklad_konrada_dab_4cm_przed_3cm():
    """Przykład Konrada: A (17.10) i B (21.10) na trasie Śląsk, równe gwiazdki; dąb A/B 4 cm i 3 cm."""
    A, B = 1, 2
    wspolne = dict(rung=1, na_trasie=True)
    pozycje = [
        ps(101, A, (180, 70, 3), termin=date(2026, 10, 17), **wspolne),
        ps(102, A, (190, 50, 4), termin=date(2026, 10, 17), **wspolne),
        ps(103, A, (220, 60, 4), termin=date(2026, 10, 17), **wspolne),
        ps(201, B, (240, 80, 4), termin=date(2026, 10, 21), **wspolne),
        ps(202, B, (200, 60, 3), termin=date(2026, 10, 21), **wspolne),
        ps(203, B, (150, 60, 4), termin=date(2026, 10, 21), **wspolne),
    ]
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje), szczebel_rozpoczete=6)
    # grupa 4 cm pierwsza: A po długości malejąco, potem B; potem grupa 3 cm tak samo
    assert wynik.kafle == [103, 102, 201, 203, 101, 202]
    assert wynik.niekompletne == []


def test_kandydaci_gwiazdki_przed_grupa_w_szczeblu_trasy():
    """Spec 3.2 p. 1: wyższe gwiazdki w tej samej trasie idą w całości pierwsze, przed grupowaniem po materiale."""
    A, B = 1, 2
    pozycje = [
        ps(101, A, (180, 70, 3), termin=date(2026, 10, 17), gwiazdki=2, rung=1, na_trasie=True),
        ps(102, A, (190, 50, 4), termin=date(2026, 10, 17), gwiazdki=2, rung=1, na_trasie=True),
        ps(201, B, (240, 80, 4), termin=date(2026, 10, 10), gwiazdki=0, rung=1, na_trasie=True),
        ps(202, B, (200, 60, 3), termin=date(2026, 10, 10), gwiazdki=0, rung=1, na_trasie=True),
    ]
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje))
    assert wynik.kafle == [102, 101, 201, 202]


def test_kandydaci_grupy_po_najblizszym_terminie_w_grupie():
    """Wariant A2: grupa, w której leży najpilniejsze zamówienie, idzie pierwsza — także przed grubszą."""
    P, Q, R = 1, 2, 3
    pozycje = [
        ps(201, Q, (200, 60, 4), termin=date(2026, 10, 20)),
        ps(301, R, (200, 60, 3), termin=date(2026, 10, 22)),
        ps(101, P, (100, 60, 3), termin=date(2026, 10, 12)),
    ]
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje))
    assert wynik.kafle == [101, 301, 201]
    # przy równym najbliższym terminie grup: gatunek, klasa, potem grubość malejąco
    pozycje = [
        ps(101, P, (100, 60, 3), termin=date(2026, 10, 12)),
        ps(201, Q, (100, 60, 4), termin=date(2026, 10, 12)),
        ps(301, R, (100, 60, 4), termin=date(2026, 10, 12), gatunek='buk'),
    ]
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje)).kafle == [301, 201, 101]


def test_kandydaci_w_grupie_termin_przed_dlugoscia():
    pozycje = [
        ps(101, 1, (250, 60, 4), termin=date(2026, 10, 21)),
        ps(201, 2, (120, 60, 4), termin=date(2026, 10, 17)),
        ps(202, 2, (140, 90, 4), termin=date(2026, 10, 17)),
        ps(203, 2, (140, 60, 4), termin=date(2026, 10, 17)),
    ]
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje))
    # termin, potem długość malejąco, potem szerokość malejąco
    assert wynik.kafle == [202, 203, 201, 101]


def test_kandydaci_przyklad_xy_rozpoczete_wskakuje_na_szczebel_tagu():
    """Spec 5.6: X (4 pozycje) i Y (3 po 4 cm), bez gwiazdek. Po zakończeniu 190×50×4 z X reszta X idzie pierwsza —
    także przed zamówieniem Z z trzema gwiazdkami, bo tag „Rozpoczęte” (szczebel 5) stoi nad ★★★ (szczebel 6)."""
    X, Y, Z = 1, 2, 3
    termin = date(2026, 10, 30)
    x1 = ps(101, X, (190, 50, 4), termin=termin, sequence=1)
    x2 = ps(102, X, (180, 70, 4), termin=termin, sequence=2)
    x3 = ps(103, X, (180, 60, 3), termin=termin, sequence=3)
    x4 = ps(104, X, (170, 78, 3), termin=termin, sequence=4)
    y = [ps(201, Y, (200, 60, 4), termin=termin, sequence=1), ps(202, Y, (185, 60, 4), termin=termin, sequence=2),
         ps(203, Y, (160, 60, 4), termin=termin, sequence=3)]
    z = ps(301, Z, (210, 60, 2), termin=termin, gwiazdki=3, rung=6, sequence=1)

    przed = [x1, x2, x3, x4] + y + [z]
    wynik = kolejka.kandydaci_stanowiska('gluing', przed, statusy(przed), szczebel_rozpoczete=5)
    # ★★★ najpierw; potem Sklejanie grupuje: 4 cm z X i Y razem (po długości), potem 3 cm
    assert wynik.kafle == [301, 201, 101, 202, 102, 203, 103, 104]

    # 190×50×4 z X poszła na Formatowanie → X „Rozpoczęte” na żywo (kolumna rung dalej 9): szczebel 5
    po = [x2, x3, x4] + y + [z]
    wynik = kolejka.kandydaci_stanowiska('gluing', po, statusy(po, o1=[(101, 'czeka_na_formatowanie')]),
                                         szczebel_rozpoczete=5)
    assert wynik.kafle == [102, 103, 104, 301, 201, 202, 203]


def test_kandydaci_rozpoczete_przed_grupowaniem_w_tym_samym_szczeblu():
    """Zamówienie z trasy nie zmienia szczebla, ale w obrębie trasy jego pozostałe pozycje idą na początek."""
    pozycje = [
        ps(101, 1, (200, 60, 4), termin=date(2026, 10, 17), rung=1, na_trasie=True),
        ps(201, 2, (150, 60, 3), termin=date(2026, 10, 21), rung=1, na_trasie=True),
    ]
    stan = statusy(pozycje, o2=[(202, 'czeka_na_pakowanie')])
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, stan, szczebel_rozpoczete=5)
    assert wynik.kafle == [201, 101]
    # tag stoi niżej (5) niż trasa (1): rozpoczęte z trasy nie spada na szczebel tagu
    inne = pozycje + [ps(301, 3, (300, 60, 4), termin=date(2026, 10, 10), rung=3)]
    stan = statusy(inne, o2=[(202, 'czeka_na_pakowanie')])
    assert kolejka.kandydaci_stanowiska('gluing', inne, stan, szczebel_rozpoczete=5).kafle == [201, 101, 301]


def test_kandydaci_bez_szczebla_rozpoczete_nie_podnosi():
    pozycje = [
        ps(101, 1, (200, 60, 4), termin=date(2026, 10, 17), rung=6),
        ps(201, 2, (150, 60, 3), termin=date(2026, 10, 21), rung=9),
    ]
    stan = statusy(pozycje, o2=[(202, 'czeka_na_formatowanie')])
    # bez pozycji tagu na drabinie rozpoczęte zostaje na swoim szczeblu…
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, stan).kafle == [101, 201]
    # …a z nią wskakuje ponad ★★★ (szczebel 6)
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, stan, szczebel_rozpoczete=5).kafle == [201, 101]
    # tag niżej niż własny szczebel zamówienia niczego nie obniża
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, stan, szczebel_rozpoczete=10).kafle == [101, 201]


def test_kandydaci_zamowienie_nieutrwalone_idzie_na_koniec_ale_tag_je_podnosi():
    pozycje = [
        ps(101, 1, (200, 60, 4), termin=date(2026, 10, 1), rung=None),
        ps(201, 2, (150, 60, 3), termin=date(2026, 10, 21), rung=9),
    ]
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje), szczebel_rozpoczete=5).kafle == [
        201, 101]
    stan = statusy(pozycje, o1=[(102, 'czeka_na_formatowanie')])
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, stan, szczebel_rozpoczete=5).kafle == [101, 201]


def test_kandydaci_dorobki_pierwsze_po_created_at():
    pozycje = [
        ps(101, 1, (200, 60, 4), termin=date(2026, 10, 6), gwiazdki=5, rung=1),
        ps(901, 8, (100, 60, 2), termin=date(2026, 11, 30), dorobka=True, created_at=datetime(2026, 10, 5, 9, 0)),
        ps(902, 9, (100, 60, 2), termin=date(2026, 11, 30), dorobka=True, created_at=datetime(2026, 10, 4, 14, 0)),
    ]
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje))
    assert wynik.kafle == [902, 901, 101]


def test_kandydaci_brak_materialu_i_wymiarow_nie_wywraca():
    pozycje = [
        kolejka.PozycjaStanowiska(id=1, order_id=1, status='czeka_na_sklejanie', dorobka=False, created_at=None,
                                  sequence=None, gatunek=None, klasa=None, grubosc=None, dlugosc=None,
                                  szerokosc=None, numer='1001', gwiazdki=None, termin=None, rung=9, rank=None,
                                  na_trasie=False),
        ps(2, 2, (200, 60, 4), termin=date(2026, 10, 21)),
    ]
    assert kolejka.kandydaci_stanowiska('gluing', pozycje, statusy(pozycje)).kafle == [2, 1]


# ── kandydaci_stanowiska: kafle-zamówienia (Formatowanie, Pakowanie) ──────────────────────────────────────────

def pf(id, order_id, **kw):
    kw.setdefault('status', 'czeka_na_formatowanie')
    return ps(id, order_id, (200, 60, 4), **kw)


def test_kandydaci_zamowienie_kompletne_na_stol_niekompletne_osobno():
    K, N, M = 1, 2, 3
    pozycje = [
        pf(101, K, termin=date(2026, 10, 21), rank=3), pf(102, K, termin=date(2026, 10, 21), rank=3),
        pf(201, N, termin=date(2026, 10, 17), rank=1), pf(202, N, termin=date(2026, 10, 17), rank=1),
        pf(301, M, termin=date(2026, 10, 19), rank=2),
    ]
    stan = statusy(pozycje, o2=[(204, 'czeka_na_sklejanie'), (203, 'czeka_na_wyciecie'), (205, 'anulowane')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan, szczebel_rozpoczete=5)
    # kafle = zamówienia kompletne w kolejności rangi (tu: termin); N czeka na dwie pozycje
    assert wynik.kafle == [M, K]
    assert wynik.niekompletne == [(N, 2, 4, [(203, 'czeka_na_wyciecie'), (204, 'czeka_na_sklejanie')])]


def test_kandydaci_ostatnia_pozycja_czyni_zamowienie_kompletnym():
    N = 2
    pozycje = [pf(201, N), pf(202, N)]
    stan = statusy(pozycje, o2=[(203, 'czeka_na_sklejanie')])
    assert kolejka.kandydaci_stanowiska('formatting', pozycje, stan).kafle == []
    pozycje.append(pf(203, N))
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, statusy(pozycje))
    assert wynik.kafle == [N]
    assert wynik.niekompletne == []


def test_kandydaci_pozycje_dalej_licza_sie_jako_zrobione():
    pozycje = [pf(101, 1)]
    stan = statusy(pozycje, o1=[(102, 'czeka_na_krawedzie'), (103, 'czeka_na_pakowanie'), (104, 'spakowane'),
                                (105, 'dostarczone')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan)
    assert wynik.kafle == [1] and wynik.niekompletne == []
    # Pakowanie: pozycja na Lakierni to jeszcze „wcześniej”
    pak = [pf(201, 2, status='czeka_na_pakowanie')]
    stan = statusy(pak, o2=[(202, 'czeka_na_lakiernie'), (203, 'zweryfikowane')])
    wynik = kolejka.kandydaci_stanowiska('packaging', pak, stan)
    assert wynik.kafle == []
    assert wynik.niekompletne == [(2, 1, 3, [(202, 'czeka_na_lakiernie')])]


def test_kandydaci_pozycja_omijajaca_nie_blokuje_kompletnosci():
    """Przykład z pytania 8 raportu K3: A czeka na Formatowaniu, B (bez docięcia) stoi na Sklejaniu i na
    Formatowanie nigdy nie trafi — zamówienie jest na Formatowaniu kompletne."""
    pozycje = [pf(101, 1)]
    stan = statusy(pozycje, o1=[(102, 'czeka_na_sklejanie')])
    bez = kolejka.kandydaci_stanowiska('formatting', pozycje, stan)
    assert bez.kafle == [] and bez.niekompletne == [(1, 1, 2, [(102, 'czeka_na_sklejanie')])]

    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan, omijajace={102})
    assert wynik.kafle == [1] and wynik.niekompletne == []


def test_kandydaci_niekompletne_bez_omijajacych_w_liczniku_i_brakuje():
    pozycje = [pf(101, 1)]
    stan = statusy(pozycje, o1=[(102, 'czeka_na_sklejanie'), (103, 'czeka_na_wyciecie'),
                                (104, 'czeka_na_pakowanie')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan, omijajace={102, 104})
    # 102 i 104 omijają Formatowanie: nie ma ich w `pozycji` ani w `brakuje`; 103 dalej trzyma zamówienie
    assert wynik.kafle == []
    assert wynik.niekompletne == [(1, 1, 2, [(103, 'czeka_na_wyciecie')])]


def test_kandydaci_wstrzymana_nie_blokuje_kompletnosci():
    pozycje = [pf(101, 1)]
    stan = statusy(pozycje, o1=[(102, 'wstrzymane'), (103, 'anulowane')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan)
    assert wynik.kafle == [1]
    # i nie liczy się do „pozycji” zamówienia niekompletnego
    stan = statusy(pozycje, o1=[(102, 'wstrzymane'), (103, 'anulowane'), (104, 'czeka_na_sklejanie')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan)
    assert wynik.niekompletne == [(1, 1, 2, [(104, 'czeka_na_sklejanie')])]


def test_kandydaci_zamowienia_w_kolejnosci_klucza_rangi_z_tagiem_na_zywo():
    pozycje = [
        pf(101, 1, termin=date(2026, 10, 30), gwiazdki=0, rung=9, status='czeka_na_pakowanie'),
        pf(201, 2, termin=date(2026, 10, 12), gwiazdki=0, rung=9, status='czeka_na_pakowanie'),
        pf(301, 3, termin=date(2026, 10, 30), gwiazdki=3, rung=6, status='czeka_na_pakowanie'),
        pf(401, 4, termin=date(2026, 10, 30), gwiazdki=1, rung=1, na_trasie=True, status='czeka_na_pakowanie'),
        pf(501, 5, termin=date(2026, 10, 20), gwiazdki=4, rung=1, na_trasie=True, status='czeka_na_pakowanie'),
    ]
    wynik = kolejka.kandydaci_stanowiska('packaging', pozycje, statusy(pozycje), szczebel_rozpoczete=5)
    # trasa (szczebel 1): gwiazdki malejąco; potem ★★★ (6); potem bez gwiazdek po terminie
    assert wynik.kafle == [5, 4, 3, 2, 1]
    # zamówienie 1 częściowo spakowane → „Rozpoczęte” na żywo (szczebel 5) → ponad ★★★
    stan = statusy(pozycje, o1=[(102, 'spakowane')])
    stan[1] = stan[1] + ((103, 'czeka_na_pakowanie'),)
    wynik = kolejka.kandydaci_stanowiska('packaging', pozycje, stan, szczebel_rozpoczete=5)
    assert wynik.kafle == [5, 4, 3, 2, 1]       # spakowane + pakowanie: nic nie jest „wcześniej” → nie rozpoczęte
    wynik = kolejka.kandydaci_stanowiska('formatting', [
        pf(101, 1, termin=date(2026, 10, 30), rung=9), pf(301, 3, termin=date(2026, 10, 30), gwiazdki=3, rung=6),
    ], {1: ((101, 'czeka_na_formatowanie'), (102, 'czeka_na_krawedzie')), 3: ((301, 'czeka_na_formatowanie'),)},
        szczebel_rozpoczete=5)
    assert wynik.kafle == [3, 1]                # etapy 2 i 3: nic przed Formatowaniem → nie rozpoczęte


def test_kandydaci_zamowienie_z_dorobka_na_stanowisku_idzie_pierwsze():
    pozycje = [
        pf(101, 1, termin=date(2026, 10, 6), gwiazdki=5, rung=1),
        pf(201, 2, termin=date(2026, 11, 30), dorobka=True, created_at=datetime(2026, 10, 5, 9, 0)),
    ]
    stan = statusy(pozycje, o2=[(202, 'czeka_na_pakowanie')])
    wynik = kolejka.kandydaci_stanowiska('formatting', pozycje, stan)
    assert wynik.kafle == [2, 1]


def test_kandydaci_jednostka_jawna_wygrywa_z_domyslna_stanowiska():
    """Jednostka kafla jest ustawieniem stanowiska (`priorytety_jednostka_<S>`); bez parametru decyduje lista
    stanowisk zamówieniowych."""
    pozycje = [ps(101, 1, (200, 60, 4)), ps(102, 1, (180, 60, 4)), ps(201, 2, (220, 60, 4))]
    stan = statusy(pozycje, o2=[(202, 'czeka_na_wyciecie')])
    wynik = kolejka.kandydaci_stanowiska('gluing', pozycje, stan, jednostka='zamowienie')
    assert wynik.kafle == [1]
    assert wynik.niekompletne == [(2, 1, 2, [(202, 'czeka_na_wyciecie')])]
    formatowanie = [pf(101, 1), pf(102, 1)]
    wynik = kolejka.kandydaci_stanowiska('formatting', formatowanie, statusy(formatowanie), jednostka='pozycja')
    assert sorted(wynik.kafle) == [101, 102] and wynik.niekompletne == []
