# -*- coding: utf-8 -*-
"""
Podsumowanie deterministyczne: liczy cenę, zapisuje `oczekiwany_podpis` i wysyła
przez atrapy `wysylka`/`cw_agent_reply` (moduł `bots_pro.wysylka` powstaje dopiero
w Task 6 — tu podmieniamy go w `sys.modules`, żeby przetestować resztę już teraz).

Brief zadania 3 nie zawiera testów dla podsumowania — dopisane zgodnie
z rozstrzygnięciem właściciela zadania.
"""
import sys
import types

from bots_pro import podsumowanie, potwierdzenia, stan
from core.db import db

stan.init_pro()


def _zaladuj_atrape_wysylki(monkeypatch):
    """Podmienia bots_pro.wysylka w sys.modules — `from bots_pro import wysylka`
    wewnątrz wyslij() znajdzie tę atrapę zamiast szukać nieistniejącego pliku."""
    modul = types.ModuleType("bots_pro.wysylka")
    modul.przygotuj = lambda tekst, persona: [tekst]
    monkeypatch.setitem(sys.modules, "bots_pro.wysylka", modul)


def _pozycja():
    # gatunek/technologia/klasa/wykonczenie/edges — tak jak realnie wyglada pozycja
    # po przejsciu przez stan.zapisz_pozycje (K2: rozlozenie selected_variant).
    return {"id": "1", "produkt": "blat", "dlugosc": 180, "szerokosc": 60,
            "grubosc": 4, "ilosc": 1, "selected_variant": "dab-lity-ab",
            "gatunek": "Dąb", "technologia": "Lity", "klasa": "A/B",
            "wykonczenie": "olejowane", "finishing_id": 3,
            "edges": [{"litera": "A", "typ": "round"}]}


def test_brak_pozycji_zwraca_blad_bez_liczenia_ceny(monkeypatch):
    stan.ustaw_kontekst(94001)
    monkeypatch.setattr(stan, "pozycje", lambda: [])
    wywolano = []
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate",
                        lambda p, o: wywolano.append(1) or {"ok": True, "totals": {}})
    wynik = podsumowanie.wyslij()
    assert wynik == {"ok": False, "error": "BRAK_POZYCJI"}
    assert not wywolano


def test_wycena_nieudana_zwraca_blad_ze_szczegolami(monkeypatch):
    stan.ustaw_kontekst(94002)
    monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate",
                        lambda p, o: {"ok": False, "errors": [{"code": "X"}]})
    wynik = podsumowanie.wyslij()
    assert wynik["ok"] is False
    assert wynik["error"] == "WYCENA_NIEUDANA"
    assert wynik["szczegoly"]["errors"] == [{"code": "X"}]


class TestWyslijSzczesliwaSciezka:
    def _przygotuj(self, monkeypatch, conv_id):
        stan.ustaw_kontekst(conv_id)
        poz = [_pozycja()]
        monkeypatch.setattr(stan, "pozycje", lambda: poz)
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append((cid, tekst, token)) or True)
        return poz, wyslane

    def test_zwraca_podpis_zgodny_z_potwierdzeniami_podpis(self, monkeypatch):
        poz, _ = self._przygotuj(monkeypatch, 94003)
        wynik = podsumowanie.wyslij()
        assert wynik["ok"] is True
        assert wynik["podpis"] == potwierdzenia.podpis(poz)

    def test_wysyla_dokladnie_jedna_wiadomosc_do_wlasciwej_rozmowy(self, monkeypatch):
        poz, wyslane = self._przygotuj(monkeypatch, 94004)
        podsumowanie.wyslij()
        assert len(wyslane) == 1
        conv, tekst, token = wyslane[0]
        assert conv == 94004
        assert "843,04" in tekst   # polska notacja (przecinek dziesietny), nie "843.04"
        assert "Czy wszystko się zgadza?" in tekst

    def test_podsumowanie_pokazuje_material_wykonczenie_i_krawedzie_nie_surowy_kod(self, monkeypatch):
        # W5: klient ma widziec WSZYSTKO, co obejmuje podpis (potwierdzenia.podpis) —
        # gdyby wykonczenie/krawedzie byly niewidoczne, potwierdzalby mniej, niz
        # faktycznie sie zapisze. Kod enuma ('dab-lity-ab') to nie jest opis dla klienta.
        _, wyslane = self._przygotuj(monkeypatch, 94008)
        podsumowanie.wyslij()
        tekst = wyslane[0][1]
        assert "Dąb lity A/B" in tekst
        assert "dab-lity-ab" not in tekst
        assert "wykończenie: olejowane" in tekst
        assert "krawędzie: 1 szt." in tekst

    def test_zapisuje_oczekiwany_podpis_w_pro_stan(self, monkeypatch):
        _, _ = self._przygotuj(monkeypatch, 94005)
        wynik = podsumowanie.wyslij()
        c = db()
        wiersz = c.execute("SELECT oczekiwany_podpis FROM pro_stan WHERE conv_id=?",
                           (94005,)).fetchone()
        c.close()
        assert wiersz["oczekiwany_podpis"] == wynik["podpis"]

    def test_rejestruje_kwote_calkowita_w_znanych_kwotach_guardraila(self, monkeypatch):
        self._przygotuj(monkeypatch, 94006)
        podsumowanie.wyslij()
        assert "843.04" in stan.znane_kwoty()


def test_rejestruje_rozbicie_per_pozycja_nie_tylko_sumy_calosci(monkeypatch):
    """W4: ceny per pozycja (material/wykonczenie/krawedzie) sa w wynik["products"],
    nie w totals. Bot mowiacy "material 861,00 zl" (bez wykonczenia/krawedzi w tej
    kwocie) dostalby falszywe naruszenie, gdyby rejestr znal tylko totale."""
    conv_id = 94007
    stan.ustaw_kontekst(conv_id)
    poz = [_pozycja()]
    monkeypatch.setattr(stan, "pozycje", lambda: poz)
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
        "ok": True,
        "totals": {"total_netto": 1000.00, "total_brutto": 1230.00},
        "products": [{
            "variants": [{"variant_code": "dab-lity-ab", "available": True,
                          "unit_netto": 700.00, "unit_brutto": 861.00,
                          "total_netto": 700.00, "total_brutto": 861.00},
                         {"variant_code": "jes-lity-ab", "available": False}],
            "finishing": {"netto": 200.00, "brutto": 246.00},
            "edges": {"netto": 100.00, "brutto": 123.00},
        }],
    })
    _zaladuj_atrape_wysylki(monkeypatch)
    monkeypatch.setattr(podsumowanie, "cw_agent_reply", lambda *a, **k: True)

    podsumowanie.wyslij()

    znane = stan.znane_kwoty()
    assert {"1000.00", "1230.00"} <= znane   # sumy calosci (jak wczesniej)
    assert {"700.00", "861.00"} <= znane     # material wybranego wariantu (unit/total)
    assert {"200.00", "246.00"} <= znane     # wykonczenie
    assert {"100.00", "123.00"} <= znane     # krawedzie
