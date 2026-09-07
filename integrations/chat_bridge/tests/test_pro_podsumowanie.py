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

import pytest

from bots_pro import podsumowanie, potwierdzenia, stan
from core.db import db

stan.init_pro()


def _zaladuj_atrape_wysylki(monkeypatch):
    """Podmienia bots_pro.wysylka w sys.modules — `from bots_pro import wysylka`
    wewnątrz wyslij() znajdzie tę atrapę zamiast szukać nieistniejącego pliku.

    `przygotuj` jest atrapą (tekst ma zostać W CAŁOŚCI, bez cięcia na części
    i bez profilu kanału), ale `wolno_linkowac` delegujemy do PRAWDZIWEGO
    modułu — od rundy napraw 3 podsumowanie pyta o profil kanału (zdanie
    o wszystkich wariantach ma sens tylko tam, gdzie klient dostanie link do
    wyceny), więc atrapa z własną, uproszczoną odpowiedzią mierzyłaby siebie,
    nie `bots.channel_caps`."""
    from bots_pro import wysylka as prawdziwa_wysylka
    modul = types.ModuleType("bots_pro.wysylka")
    modul.przygotuj = lambda tekst, persona: [tekst]
    modul.wolno_linkowac = prawdziwa_wysylka.wolno_linkowac
    monkeypatch.setitem(sys.modules, "bots_pro.wysylka", modul)


def _pozycja():
    # gatunek/technologia/klasa/wykonczenie/edges/otwory — tak jak realnie wyglada
    # pozycja po przejsciu przez stan.zapisz_pozycje (K2: rozlozenie selected_variant;
    # Task 2: edges w postaci ZNORMALIZOWANEJ — litera/typ/r_value/angle_value, bo
    # tak stan.zapisz_pozycje zapisuje je po crm_calc.normalize_edges).
    return {"id": "1", "produkt": "blat", "dlugosc": 180, "szerokosc": 60,
            "grubosc": 4, "ilosc": 1, "selected_variant": "dab-lity-ab",
            "gatunek": "Dąb", "technologia": "Lity", "klasa": "A/B",
            "wykonczenie": "olejowane", "finishing_id": 3,
            "edges": [{"litera": "A", "typ": "round", "r_value": 5, "angle_value": None}],
            "otwory": ["otwór na zlew 50x40 cm"]}


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


def test_wycena_nieudana_nie_oddaje_cen_z_pelnego_payloadu_kalkulatora(monkeypatch):
    """W3b (runda poprawek 2): crm_calc.calculate() moze zwrocic ok=False z
    NADAL pelna tabela cen w products[] (np. per-produktowy blad
    VARIANT_UNAVAILABLE) — kwoty_z_wyniku na tej sciezce W OGOLE nie jest
    wolane (rejestr pusty), wiec KAZDA liczba z takiego payloadu bylaby dla
    G1 halucynacja. szczegoly ma niesc WYLACZNIE powod niepowodzenia."""
    stan.ustaw_kontekst(94013)
    monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
        "ok": False,
        "errors": [{"field": "selected_variant", "code": "VARIANT_UNAVAILABLE",
                    "message": "Wariant niedostępny dla tych wymiarów."}],
        "products": [{
            "index": 1, "errors": [{"code": "VARIANT_UNAVAILABLE"}],
            "variants": [
                {"variant_code": "dab-lity-ab", "available": True,
                 "price_per_m3": 8200.0, "unit_netto": 700.0, "unit_brutto": 861.0},
            ],
            "finishing": {"netto": 200.0, "brutto": 246.0, "price_per_m2": 120.0},
            "edges": {"netto": 34.2, "brutto": 42.07, "details": [
                {"letter": "A", "type": "round", "price_netto": 27.0, "price_brutto": 33.21},
            ]},
        }],
        "totals": None,
    })
    wynik = podsumowanie.wyslij()
    assert wynik["ok"] is False
    assert wynik["error"] == "WYCENA_NIEUDANA"
    # Powod niepowodzenia zostaje...
    assert wynik["szczegoly"]["errors"][0]["code"] == "VARIANT_UNAVAILABLE"
    # ...ale ZADNA cena z pelnego payloadu kalkulatora nie wyciekla.
    assert "products" not in wynik["szczegoly"]
    assert "totals" not in wynik["szczegoly"]
    tekst_szczegolow = str(wynik["szczegoly"])
    assert "8200" not in tekst_szczegolow
    assert "price_per_m3" not in tekst_szczegolow
    assert "27.0" not in tekst_szczegolow


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

    def test_podsumowanie_pokazuje_typy_krawedzi_nie_tylko_liczbe_sztuk(self, monkeypatch):
        # Domkniecie resztki z Task 3: przed poprawka klient widzial "krawedzie: 1 szt."
        # -- liczbe, nie TYP obrobki (zaokraglenie/fazowanie/ktora litera) -- mimo ze
        # cala ta informacja wchodzi do podpisu potwierdzenia (potwierdzenia.podpis
        # czyta pole "edges" w calosci, wiec klient podpisywal wiecej, niz widzial).
        _, wyslane = self._przygotuj(monkeypatch, 94009)
        podsumowanie.wyslij()
        tekst = wyslane[0][1]
        assert "krawędzie: R5 (A)" in tekst
        assert "krawędzie: 1 szt." not in tekst

    def test_podsumowanie_pokazuje_tresc_otworow_nie_liczbe_sztuk(self, monkeypatch):
        _, wyslane = self._przygotuj(monkeypatch, 94010)
        podsumowanie.wyslij()
        tekst = wyslane[0][1]
        assert "otwory: otwór na zlew 50x40 cm" in tekst
        assert "otwory: 1 szt." not in tekst

    def test_przy_otworach_podsumowanie_mowi_ze_ich_koszt_nie_jest_wliczony(self, monkeypatch):
        # N3 (naprawa po testach na zywym czacie): wyciecia SA w podsumowaniu,
        # ich koszt NIE jest w cenie (pole `otwory` nigdy nie dochodzi do
        # kalkulatora — patrz _POLA_OPISOWE w potwierdzenia.py), a podsumowanie
        # o tym milczalo. Bot mowil prawde dopiero zapytany wprost. Klient
        # potwierdzal wiec cene, ktora nie obejmowala tego, co widzial obok niej.
        #
        # UWAGA: to naprawa KOMUNIKATU, nie ceny. Faktyczne wliczenie wyciec do
        # wyceny jest osobnym, wiekszym zadaniem.
        _, wyslane = self._przygotuj(monkeypatch, 94012)
        podsumowanie.wyslij()
        tekst = wyslane[0][1]
        assert "koszt wycięć nie jest wliczony w tę cenę" in tekst

    def test_adnotacja_o_wycieciach_miesci_sie_w_zawezonej_regule_CENY(self):
        """P2: adnotację składa KOD, więc reguła promptu jej nie dotyczy — ale
        model widzi wysłane podsumowanie w historii i mógł tę frazę uogólnić na
        całą wycenę. Sekcja CENY dopuszcza ją dziś wprost i oba brzmienia mają
        zostać zgodne: gdyby ktoś przeredagował adnotację, ten test pokaże, że
        zgoda w prompcie przestała do niej pasować."""
        import re

        from bots_pro import prompty
        linia = podsumowanie._linia({"produkt": "blat", "dlugosc": 180,
                                     "szerokosc": 60, "grubosc": 4, "ilosc": 1,
                                     "otwory": ["otwór na zlew 50x40 cm"]})
        assert "wycenia je konsultant" in linia
        # Prompt jest w źródle zawijany do ~90 kolumn, więc szukana fraza potrafi
        # mieć w środku znak nowej linii — porównujemy po normalizacji białych
        # znaków, tak samo jak test_pro_prompty.py.
        assert "wycięcia i otwory wycenia konsultant" in re.sub(r"\s+", " ", prompty.WYCENA)

    def test_bez_otworow_podsumowanie_nie_wspomina_o_wycieciach(self, monkeypatch):
        # Kontrola negatywna: adnotacja wisi przy otworach, nie przy kazdej
        # pozycji — wzmianka o wycieciach w pozycji, ktora ich nie ma, byloby
        # zaproszeniem do rozmowy, ktorej prompt zabrania zaczynac (CZEGO NIE
        # WOLNO: nie wspominaj o wycieciach z wlasnej inicjatywy).
        stan.ustaw_kontekst(94013)
        poz = _pozycja()
        poz.pop("otwory")
        monkeypatch.setattr(stan, "pozycje", lambda: [poz])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda conv, tekst, token=None: wyslane.append(tekst) or True)
        podsumowanie.wyslij()
        assert "wycięć" not in wyslane[0]

    def test_podsumowanie_pokazuje_konkretny_kolor_polysk_z_katalogu_finishing_id(self, monkeypatch):
        # Domkniecie resztki z Task 3: finishing_id (KONKRETNY wariant/polysk) nie byl
        # pokazywany wcale -- klient widzial tylko ogolnik "olejowane", a to
        # finishing_id (nie sam tekst 'wykonczenie') trafia do zamowienia i do
        # podpisu potwierdzenia.
        stan.ustaw_kontekst(94011)
        poz = [_pozycja()]
        monkeypatch.setattr(stan, "pozycje", lambda: poz)
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {
            "finishing_options": [
                {"id": 3, "full_path": "Olejowane/Bezbarwne/Olej twardowoskowy"},
            ]})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append((cid, tekst, token)) or True)

        podsumowanie.wyslij()
        tekst = wyslane[0][1]
        assert "wykończenie: Olejowane > Bezbarwne > Olej twardowoskowy" in tekst
        assert "wykończenie: olejowane" not in tekst

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


def test_surowe_nigdy_nie_pokazuje_sciezki_katalogowej_nawet_z_duchem_finishing_id(monkeypatch):
    """W1 (runda poprawek 1): stan.zapisz_pozycje juz czysci finishing_id przy
    przejsciu na "surowe" (fix w stan.py), ale _wykonczenie_opis ma zostac
    poprawna NIEZALEZNIE od tego -- ten test symuluje pozycje, w ktorej
    finishing_id zostal jako "duch" (np. dane sprzed poprawki, recznie
    naprawiona baza) i sprawdza, ze mimo katalogowego wpisu dla tego id
    podsumowanie NIE pokazuje koloru/polysku przy cenie surowego blatu."""
    conv_id = 94012
    stan.ustaw_kontekst(conv_id)
    poz_z_duchem = dict(_pozycja())
    poz_z_duchem["wykonczenie"] = "surowe"
    poz_z_duchem["finishing_id"] = 3   # "duch" -- nie powinien juz nic znaczyc
    poz = [poz_z_duchem]
    monkeypatch.setattr(stan, "pozycje", lambda: poz)
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {
        "finishing_options": [
            {"id": 3, "full_path": "Olejowane/Bezbarwne/Olej twardowoskowy"},
        ]})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
        "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
    _zaladuj_atrape_wysylki(monkeypatch)
    wyslane = []
    monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                        lambda cid, tekst, token=None: wyslane.append((cid, tekst, token)) or True)

    podsumowanie.wyslij()
    tekst = wyslane[0][1]
    assert "wykończenie: surowe" in tekst
    assert "Olejowane" not in tekst
    assert "Bezbarwne" not in tekst


class TestWykonczenieOpisLapiePodciagSurowNiezaleznieOdPisowni:
    """N1 (runda poprawek 2): straznik "surowe" porownywal DOKLADNIE, a
    regula cenowa crm_calc._finish_type lapie PODCIAG "surow" (bez wzgledu
    na wielkosc liter/diakrytyki) -- "Surowe" (duza litera) czy "surowy dab"
    tez licza sie jako Surowe dla WYCENY (crm_calc.build_products), ale
    strazniczka je przepuszczala do sciezki katalogowej. Dzis enum narzedzia
    (Wykonczenie) wysyla wylacznie dokladne "surowe" (nieosiagalne przez
    narzedzie), ale funkcja ma byc poprawna niezaleznie od enumu."""

    _OPCJE = {"finishing_options": [
        {"id": 3, "full_path": "Olejowane/Bezbarwne/Olej twardowoskowy"}]}

    def test_rozne_pisownie_surowego_nie_pokazuja_sciezki_katalogowej(self):
        for wykonczenie in ("surowe", "Surowe", "SUROWE", "surowy dąb", "surowa deska"):
            opis = podsumowanie._wykonczenie_opis(
                {"wykonczenie": wykonczenie, "finishing_id": 3}, self._OPCJE)
            assert opis == wykonczenie, wykonczenie
            assert "Olejowane" not in opis

    def test_olejowane_nadal_pokazuje_sciezke_katalogowa(self):
        # Kontrola negatywna: naprawa nie ma zaszkodzic prawdziwym wykonczeniom.
        opis = podsumowanie._wykonczenie_opis(
            {"wykonczenie": "olejowane", "finishing_id": 3}, self._OPCJE)
        assert opis == "Olejowane > Bezbarwne > Olej twardowoskowy"


class TestWynikDlaModelu:
    """W3 (runda poprawek 1 i 2): payload calculate() zwracany modelowi ma byc
    przyciety do wariantu WYBRANEGO -- rejestr I1 (kwoty_z_wyniku) zna tylko
    jego cene, wiec pelna lista wariantow w wyniku narzedzia byla furtka,
    przez ktora bot cytujacy PRAWDZIWA cene niewybranego wariantu zostawalby
    oskarzony o halucynacje przez wlasny wynik wlasnego narzedzia.

    Atrapa `_wynik_calculate` MA REALNY KSZTALT prawdziwego calculate_quote
    (pricing_service.py: calculate_material_variants/calculate_finishing/
    calculate_edges_pricing) -- W REALNYM KSZTALCIE, nie w uproszczonej
    wersji. Runda poprawek 2: pierwsza wersja tego pliku miala atrapy BEZ
    variants[].price_per_m3, finishing.price_per_m2 i edges.details, wiec
    caly ten wyciek byl niewidoczny dla pakietu testow mimo ze W3 "przeszlo"
    -- ta klasa bledu (test dowodzi tego, co atrapa POZWALA udowodnic, nie
    tego, co robi prawdziwy kod) nie ma sie powtorzyc."""

    def _wynik_calculate(self):
        return {
            "ok": True,
            "totals": {"total_netto": 1000.0, "total_brutto": 1230.0},
            "products": [{
                "index": 1,
                "variants": [
                    {"variant_code": "dab-lity-ab", "available": True,
                     "volume_m3": 0.0432, "price_per_m3": 8200.0, "multiplier": 2.0,
                     "unit_netto": 700.0, "unit_brutto": 861.0,
                     "total_netto": 700.0, "total_brutto": 861.0},
                    {"variant_code": "jes-lity-ab", "available": True,
                     "volume_m3": 0.0432, "price_per_m3": 5800.0, "multiplier": 2.0,
                     "unit_netto": 500.0, "unit_brutto": 615.0,
                     "total_netto": 500.0, "total_brutto": 615.0},
                    {"variant_code": "buk-lity-ab", "available": False},
                ],
                "finishing": {"netto": 200.0, "brutto": 246.0,
                              "price_per_m2": 120.0, "surface_m2": 1.67},
                "edges": {"netto": 34.2, "brutto": 42.07, "details": [
                    {"letter": "A", "type": "round", "length_cm": 180.0,
                     "price_netto": 27.0, "price_brutto": 33.21, "is_corner": False},
                    {"letter": "C", "type": "chamfer", "length_cm": 60.0,
                     "price_netto": 7.2, "price_brutto": 8.86, "is_corner": False},
                ]},
            }],
        }

    def test_zostawia_tylko_wariant_wybrany_w_pozycji(self):
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, self._wynik_calculate())
        [prod] = okrojony["products"]
        assert [v["variant_code"] for v in prod["variants"]] == ["dab-lity-ab"]

    def test_niedostepny_wybrany_wariant_daje_pusta_liste_nie_bledy(self):
        # buk-lity-ab jest w wyniku, ale available=False -- nie ma prawdziwej
        # ceny do pokazania, wiec przyciety wynik ma pusta liste dla tej pozycji.
        pozycje = [{"id": "1", "selected_variant": "buk-lity-ab"}]
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, self._wynik_calculate())
        assert okrojony["products"][0]["variants"] == []

    def test_totals_i_reszta_wyniku_zostaja_bez_zmian(self):
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        wynik = self._wynik_calculate()
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, wynik)
        assert okrojony["totals"] == wynik["totals"]
        assert okrojony["ok"] is True

    def test_nie_mutuje_oryginalnego_wyniku(self):
        # policz_wycene w narzedzia.py najpierw rejestruje kwoty z PELNEGO
        # wynik["products"], DOPIERO POTEM przycina -- gdyby ta funkcja
        # mutowala wejscie in-place, kolejnosc miałaby znaczenie w sposob
        # trudny do zauwazenia. Kopiowanie zamiast mutacji to eliminuje.
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        wynik = self._wynik_calculate()
        liczba_wariantow_przed = len(wynik["products"][0]["variants"])
        podsumowanie.wynik_dla_modelu(pozycje, wynik)
        assert len(wynik["products"][0]["variants"]) == liczba_wariantow_przed

    def test_brak_sekcji_products_przechodzi_bez_zmian(self):
        # np. braki_mapowania -- crm_calc.calculate() zwraca {"ok": False, ...}
        # BEZ klucza "products" wcale (patrz bots/crm_calc.py:calculate).
        wynik = {"ok": False, "braki_mapowania": [{"powod": "x"}]}
        assert podsumowanie.wynik_dla_modelu([], wynik) == wynik

    def test_usuwa_price_per_m3_z_wariantu(self):
        # W3, runda poprawek 2: cena za m3 jest CZYNNIKIEM, z ktorego liczy
        # sie unit_netto (zarejestrowany jest tylko WYNIK mnozenia).
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, self._wynik_calculate())
        [wariant] = okrojony["products"][0]["variants"]
        assert "price_per_m3" not in wariant
        assert wariant["unit_netto"] == 700.0   # reszta pol wariantu zostaje

    def test_usuwa_price_per_m2_z_finishing(self):
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, self._wynik_calculate())
        finishing = okrojony["products"][0]["finishing"]
        assert "price_per_m2" not in finishing
        assert finishing["netto"] == 200.0   # suma (zarejestrowana) zostaje

    def test_usuwa_details_z_edges(self):
        # details niesie WLASNE price_netto/price_brutto PER KRAWEDZ -- suma
        # (edges.netto/brutto) jest zarejestrowana, rozbicie per litera nie.
        pozycje = [{"id": "1", "selected_variant": "dab-lity-ab"}]
        okrojony = podsumowanie.wynik_dla_modelu(pozycje, self._wynik_calculate())
        edges = okrojony["products"][0]["edges"]
        assert "details" not in edges
        assert edges["netto"] == 34.2   # suma (zarejestrowana) zostaje

class TestOpisEdges:
    """Runda poprawek 1, drobne: galaz dla nierozpoznanego typu (dawniej z
    etykieta z martwego _TYP_EDGE_PL) POMIJA wpis, zamiast zgadywac etykiete
    -- "sharp" nigdy tu nie trafia (normalize_edges go odrzuca przy zapisie
    w stan.py), ale funkcja ma zostac bezpieczna, gdyby jednak trafil."""

    def test_pomija_wpis_z_nierozpoznanym_typem(self):
        assert podsumowanie._opis_edges(
            [{"litera": "A", "typ": "sharp", "r_value": None, "angle_value": None}]) == ""

    def test_grupuje_round_i_chamfer_normalnie(self):
        opis = podsumowanie._opis_edges([
            {"litera": "A", "typ": "round", "r_value": 5, "angle_value": None},
            {"litera": "B", "typ": "round", "r_value": 5, "angle_value": None},
            {"litera": "C", "typ": "chamfer", "r_value": None, "angle_value": 45},
        ])
        assert opis == "R5 (A, B); Fazowanie 45° (C)"


class TestPodsumowaniePokazujeDostawe:
    """U4 (recenzja końcowa): klient potwierdzał podsumowanie zawierające WYŁĄCZNIE
    cenę produktu, mimo że bot mówił mu wcześniej "produkt + wysyłka". Dostawa ma
    być w treści, którą klient podpisuje — inaczej I2 chroni połowę ceny."""

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
                            lambda cid, tekst, token=None: wyslane.append(tekst) or True)
        return wyslane

    def test_znana_dostawa_jest_widoczna_w_podsumowaniu(self, monkeypatch):
        wyslane = self._przygotuj(monkeypatch, 94030)
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.00)
        podsumowanie.wyslij()
        tekst = wyslane[0]
        assert "DPD" in tekst
        assert "250,00" in tekst
        assert "1 093,04" in tekst   # produkt 843,04 + dostawa 250,00

    def test_suma_z_dostawa_trafia_do_rejestru_kwot_g1(self, monkeypatch):
        # Bot moze te sume zacytowac w kolejnej turze — guardrail musi ja znac,
        # inaczej zglosi PRAWDZIWA cene jako halucynacje.
        self._przygotuj(monkeypatch, 94031)
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.00)
        podsumowanie.wyslij()
        assert "1093.04" in stan.znane_kwoty()

    def test_suma_jest_dokladnie_soma_dwoch_liczb_z_crm(self, monkeypatch):
        """R3: dodawanie po stronie mostka to ŚWIADOMY WYJĄTEK od „cena zawsze
        z CRM" (żaden endpoint bota nie zwraca sumy z wysyłką — dowód w
        komentarzu przy `wyslij()`). Skoro tak, to ma być DODAWANIE I NIC WIĘCEJ:
        żadnego zaokrąglania w górę, narzutu ani rabatu wymyślonego tutaj."""
        wyslane = self._przygotuj(monkeypatch, 94033)
        stan.zapisz_dostawe("00-002", kurier="DPD", netto=100.00, brutto=123.00)
        podsumowanie.wyslij()
        assert "966,04" in wyslane[0]                  # 843,04 + 123,00, co do grosza
        assert "%.2f" % (843.04 + 123.00) == "966.04"

    def test_suma_z_dostawa_znika_z_rejestru_po_nowym_oszacowaniu(self, monkeypatch):
        """N2 (rerecenzja): suma „produkt + dostawa" jest kwotą DOSTAWY —
        po nowym oszacowaniu kuriera przestaje obowiązywać i musi zniknąć z
        rejestru G1 razem z samym kosztem wysyłki. Cena produktu zostaje."""
        self._przygotuj(monkeypatch, 94034)
        stan.zapisz_dostawe("10-900", kurier="DPD", netto=203.25, brutto=250.00)
        podsumowanie.wyslij()
        assert "1093.04" in stan.znane_kwoty()

        stan.zapisz_dostawe("80-000", kurier="DPD", netto=146.34, brutto=180.00)

        assert "1093.04" not in stan.znane_kwoty()
        assert "843.04" in stan.znane_kwoty()

    def test_bez_wycenionej_dostawy_podsumowanie_mowi_o_tym_wprost(self, monkeypatch):
        """N3 (rerecenzja gałęzi): po U4 podsumowanie CZASEM pokazuje dostawę,
        więc jej BRAK czyta się jak „dostawa gratis" — klient potwierdzał
        „Razem: 843,04 zł" jako cenę całości. Musi być powiedziane wprost, że
        koszt dostawy nie jest znany i NIE jest w tej kwocie zawarty.

        Nadal nie dopisujemy ani kuriera, ani zmyślonego „0 zł"."""
        wyslane = self._przygotuj(monkeypatch, 94032)
        podsumowanie.wyslij()
        tekst = wyslane[0]
        assert "Razem za produkty (bez dostawy): 843,04 zł brutto" in tekst
        assert "Dostawa: jeszcze nie wyceniona" in tekst
        assert "0,00 zł" not in tekst

    def test_kod_pocztowy_bez_kuriera_mowi_ze_wysylki_nie_wyceniono(self, monkeypatch):
        """N3, wariant z sondy: klient PODAŁ kod pocztowy, `policz_wysylke`
        zwróciło carriers=0 (gabaryt bez kuriera). Milczenie o dostawie w tym
        miejscu jest najgroźniejsze — klient wie, że o wysyłce była mowa."""
        wyslane = self._przygotuj(monkeypatch, 94035)
        stan.zapisz_dostawe("10-900")
        podsumowanie.wyslij()
        tekst = wyslane[0]
        assert "Razem za produkty (bez dostawy): 843,04 zł brutto" in tekst
        assert "10-900" in tekst
        assert "nie udało się wycenić" in tekst
        assert "0,00 zł" not in tekst


class TestWyslijNieudanaWysylka:
    """U1 (recenzja końcowa gałęzi): `cw_agent_reply` NIGDY nie rzuca — przy
    429/5xx/timeoucie po prostu zwraca False (core/chatwoot.py). Podsumowanie,
    którego Chatwoot NIE przyjął, nie może liczyć się jako doręczone: zapisany
    `oczekiwany_podpis` + `podsumowanie_wyslane` otwierają bramkę I2 na treść,
    której klient NIGDY nie zobaczył (wycena zapisana i link wysłany bez
    potwierdzenia czegokolwiek — sonda P2 z recenzji)."""

    def _przygotuj(self, monkeypatch, conv_id, wyniki_wysylki, czesci=1):
        stan.ustaw_kontekst(conv_id)
        poz = [_pozycja()]
        monkeypatch.setattr(stan, "pozycje", lambda: poz)
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        # `from bots_pro import wysylka` wewnątrz wyslij() sięga po ATRYBUT paczki
        # (moduł jest już zaimportowany), więc podmiana w sys.modules nic by nie
        # dała — łatamy prawdziwy moduł, żeby sterować liczbą części wysyłki.
        from bots_pro import wysylka as prawdziwa_wysylka
        monkeypatch.setattr(prawdziwa_wysylka, "przygotuj",
                            lambda tekst, persona: [tekst] * czesci)
        proby, wyniki = [], list(wyniki_wysylki)

        def _reply(cid, tekst, token=None):
            proby.append(tekst)
            return wyniki.pop(0)

        monkeypatch.setattr(podsumowanie, "cw_agent_reply", _reply)
        return proby

    def _oczekiwany_podpis_w_bazie(self, conv_id):
        c = db()
        wiersz = c.execute("SELECT oczekiwany_podpis FROM pro_stan WHERE conv_id=?",
                           (conv_id,)).fetchone()
        c.close()
        return wiersz["oczekiwany_podpis"] if wiersz else None

    def test_nieudana_wysylka_zwraca_blad_nie_ok(self, monkeypatch):
        self._przygotuj(monkeypatch, 94020, [False])
        wynik = podsumowanie.wyslij()
        assert wynik["ok"] is False
        assert wynik["error"] == "PODSUMOWANIE_NIEWYSLANE"
        assert "wyslano" not in wynik

    def test_nieudana_wysylka_nie_zapisuje_oczekiwanego_podpisu(self, monkeypatch):
        self._przygotuj(monkeypatch, 94021, [False])
        podsumowanie.wyslij()
        assert self._oczekiwany_podpis_w_bazie(94021) is None

    def test_nieudana_wysylka_nie_oznacza_tury_jako_obsluzonej(self, monkeypatch):
        # `podsumowanie_wyslane()` blokuje w tura.py wysyłkę czegokolwiek innego w
        # tej turze — po NIEUDANEJ wysyłce ta blokada zostawiłaby klienta w ciszy.
        self._przygotuj(monkeypatch, 94022, [False])
        podsumowanie.wyslij()
        assert stan.podsumowanie_wyslane() is False
        assert stan.podsumowanie_nieudane() is True

    def test_nieudana_wysylka_nie_otwiera_bramki_i2(self, monkeypatch):
        # Pełne obejście I2 z sondy P2: podpis w bazie -> potwierdz('tak') przechodzi
        # -> sprawdz_bramke() przechodzi -> wycena zapisana bez wiedzy klienta.
        self._przygotuj(monkeypatch, 94023, [False])
        monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: "tak")
        podsumowanie.wyslij()
        assert potwierdzenia.potwierdz("tak")["ok"] is False
        assert potwierdzenia.sprawdz_bramke()["ok"] is False

    def test_polowicznie_wyslane_podsumowanie_nie_liczy_sie_jako_doreczone(self, monkeypatch):
        # Wieloczęściowa wysyłka (OLX/Allegro, max_len): część 1 przeszła, część 2 nie.
        # Klient widzi urwane podsumowanie — podpis NIE może zostać zapisany, a
        # kolejnych części nie dosyłamy (ogon po dziurze byłby jeszcze gorszy).
        proby = self._przygotuj(monkeypatch, 94024, [True, False, True], czesci=3)
        wynik = podsumowanie.wyslij()
        assert wynik["error"] == "PODSUMOWANIE_NIEWYSLANE"
        assert self._oczekiwany_podpis_w_bazie(94024) is None
        assert len(proby) == 2   # trzecia część już nie poleciała

    def test_udana_wysylka_nie_ustawia_flagi_niepowodzenia(self, monkeypatch):
        # Kontrola negatywna dla ścieżki szczęśliwej.
        self._przygotuj(monkeypatch, 94025, [True])
        wynik = podsumowanie.wyslij()
        assert wynik["ok"] is True and wynik["wyslano"] is True
        assert stan.podsumowanie_wyslane() is True
        assert stan.podsumowanie_nieudane() is False
        assert self._oczekiwany_podpis_w_bazie(94025) == wynik["podpis"]


class TestP1WszystkieWariantyWWycenie:
    """Runda napraw 3, P1. Rozstrzygnięcie właściciela: „czasem klient nie wie
    co wybrać, więc nie możemy go zmuszać do wyboru, wtedy proponujemy szerszy
    zakres, czyli wszystkie warianty".

    Podsumowanie pokazuje cenę JEDNEGO wariantu — tego przyjętego do rachunku
    — a strona wyceny pokazuje wszystkie osiem z cenami (`_products_with_all_variants`
    w modules/calculator/routers/bot_api.py zapisuje komplet kodów, ceny dokłada
    `_inject_backend_prices` w quote_service.py, a client_quote.js renderuje je
    razem z powodem niedostępności). Klient ma się o tym dowiedzieć zdaniem,
    które składa KOD — dokładnie z tego powodu, dla którego kod składa adnotację
    o wycięciach: żeby stało przy KAŻDYM podsumowaniu, a nie wtedy, gdy model
    akurat sobie o nim przypomni.

    Zdanie NIE niesie żadnej kwoty — porównanie jest na stronie wyceny, nie
    w czacie, więc rejestr G1 nie rośnie ani o jedną pozycję."""

    def _wyslij(self, monkeypatch, conv_id, persona="pro"):
        stan.ustaw_kontekst(conv_id, persona_tury=persona)
        monkeypatch.setattr(stan, "pozycje", lambda: [_pozycja()])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append(tekst) or True)
        podsumowanie.wyslij()
        return wyslane[0]

    def test_podsumowanie_mowi_o_cenach_wszystkich_wariantow(self, monkeypatch):
        tekst = self._wyslij(monkeypatch, 94051)
        assert podsumowanie.ZDANIE_O_WARIANTACH.strip() in tekst

    def test_zdanie_wymienia_gatunki_z_oferty(self, monkeypatch):
        tekst = self._wyslij(monkeypatch, 94052)
        for gatunek in ("dębu", "jesionu", "buku"):
            assert gatunek in tekst, gatunek

    def test_zdanie_nie_wnosi_do_rozmowy_zadnej_kwoty(self):
        # Cała istota rozstrzygnięcia P1: klient widzi porównanie NA STRONIE
        # wyceny, nie w czacie — więc rejestr G1 (i jego tolerancja
        # zaokrąglenia do pełnych złotych) nie rośnie ani o jedną kwotę.
        from bots_pro import guardraile
        assert guardraile.znajdz_kwoty(podsumowanie.ZDANIE_O_WARIANTACH) == set()
        assert guardraile.znajdz_gole_kwoty(podsumowanie.ZDANIE_O_WARIANTACH) == set()

    def test_zdanie_nie_zmienia_rejestru_kwot(self, monkeypatch):
        self._wyslij(monkeypatch, 94053)
        assert stan.znane_kwoty() == {"685.40", "843.04"}

    def test_na_kanale_bez_linkow_zdania_nie_ma(self, monkeypatch):
        # Allegro: linku do wyceny klient NIE dostanie (regulamin), więc
        # obietnica „zobaczy Pan wszystkie warianty" byłaby obietnicą bez
        # pokrycia — czyli dokładnie tym błędem, który ta runda naprawia.
        tekst = self._wyslij(monkeypatch, 94054, persona="allegro")
        assert podsumowanie.ZDANIE_O_WARIANTACH.strip() not in tekst

    def test_na_olx_zdanie_jest_bo_link_wolno_wyslac(self, monkeypatch):
        tekst = self._wyslij(monkeypatch, 94055, persona="olx")
        assert podsumowanie.ZDANIE_O_WARIANTACH.strip() in tekst

    def test_zdanie_stoi_przed_pytaniem_o_zgode(self, monkeypatch):
        # Kolejność jest treścią: klient ma przeczytać o wariantach ZANIM
        # odpowie „czy wszystko się zgadza".
        tekst = self._wyslij(monkeypatch, 94056)
        assert tekst.index(podsumowanie.ZDANIE_O_WARIANTACH.strip()) < \
            tekst.index("Czy wszystko się zgadza?")

    def test_zdanie_i_regula_promptu_nie_rozjezdzaja_sie(self):
        # SONDA spojnosci (P1): to samo zdanie o wszystkich wariantach mowi
        # KOD (tutaj, przy kazdym podsumowaniu) i PROMPT. Przeredagowanie
        # jednego bez drugiego dawaloby klientowi dwie rozne obietnice
        # w jednej rozmowie.
        #
        # RUNDA NAPRAW 6 (P4, sprzecznosc S4): strona PROMPTU to juz nie
        # niebramkowana sekcja PORÓWNANIE, tylko blok NIEZDECYDOWANY KLIENT —
        # bramkowany DOKLADNIE tym samym predykatem (`wysylka.wolno_linkowac`)
        # co to zdanie. Sonda jest przez to MOCNIEJSZA niz byla: sprawdza, ze
        # obie strony obietnicy znikaja i pojawiaja sie razem, a nie tylko ze
        # brzmia tak samo.
        import re as _re

        from bots_pro import prompty
        regula = _re.sub(r"\s+", " ", prompty.blok_wyboru_w_wycenie(True))
        zdanie = _re.sub(r"\s+", " ", podsumowanie.ZDANIE_O_WARIANTACH)
        assert "ceny wszystkich wariantów drewna" in regula
        assert "ceny wszystkich wariantów drewna" in zdanie
        # Kontrola negatywna: na kanale bez linku nie ma ANI zdania w kodzie
        # (testy wyzej), ANI reguly w prompcie.
        assert prompty.blok_wyboru_w_wycenie(False) == ""

    def test_zdanie_nie_wchodzi_do_podpisu_potwierdzenia(self, monkeypatch):
        # `potwierdzenia.podpis` liczy odcisk z pozycji i dostawy, nie z tekstu
        # — dopisek nie ma prawa unieważnić potwierdzenia, bo nie zmienia
        # niczego, co klient potwierdza.
        stan.ustaw_kontekst(94057)
        przed = potwierdzenia.podpis([_pozycja()], {})
        self._wyslij(monkeypatch, 94057)
        assert potwierdzenia.podpis([_pozycja()], {}) == przed


class TestR6NazwaProduktuNiePrzemycaKsztaltu:
    """Runda napraw 6, P5 — recenzja §5/U-N5 (pochodna U2).

    Sonda recenzenta:

        _linia({"produkt": "Blat okrągły dębowy", "dlugosc": 120,
                "szerokosc": 120, ...})
        -> „• Blat okrągły dębowy Dąb lita A/B, 120x120x4 cm, ..."

    Nazwa produktu szła do klienta DOSŁOWNIE z pola tekstowego wypełnianego
    przez model, a `podsumowanie.py` nie znało słowa „kształt" ani razu.
    Reguła KSZTAŁT („NIE wyceniaj i NIE nazywaj kształtu w podsumowaniu") była
    więc niesprawdzalna kodem — a kwota, która stoi obok takiej nazwy, jest
    policzona jak prostokąt o tych samych wymiarach (⌀120 to 1,13 m2, kwadrat
    120x120 to 1,44 m2 — 27% materiału bez pokrycia).

    To NIE jest walidator nazw i nie ma nim być. To jedna zamknięta lista słów
    kształtu i jedna bramka: podsumowanie z takim słowem w nazwie NIE wychodzi
    do klienta, model dostaje jednoznaczny błąd odsyłający do reguły KSZTAŁT,
    a trafienie zostaje w logu — czyli sytuacja przestaje przechodzić po cichu.
    Kierunek jest ten sam co przy `wyslij_obraz` i `policz_wycene`: bramka
    odmawia, zamiast wysyłać klientowi coś, czego nie umiemy policzyć."""

    def _pozycja_o_nazwie(self, nazwa):
        return dict(_pozycja(), produkt=nazwa)

    def _sprobuj_wyslac(self, monkeypatch, conv_id, nazwa):
        stan.ustaw_kontekst(conv_id)
        monkeypatch.setattr(stan, "pozycje", lambda: [self._pozycja_o_nazwie(nazwa)])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append(tekst) or True)
        return podsumowanie.wyslij(), wyslane

    def test_ksztalt_w_nazwie_nie_dociera_do_klienta(self, monkeypatch):
        wynik, wyslane = self._sprobuj_wyslac(monkeypatch, 94061, "Blat okrągły dębowy")
        assert wynik["ok"] is False
        assert wynik["error"] == "KSZTALT_W_NAZWIE"
        assert wyslane == []

    def test_blad_odsyla_model_do_reguly_ksztalt(self, monkeypatch):
        wynik, _ = self._sprobuj_wyslac(monkeypatch, 94062, "Blat okrągły dębowy")
        assert "KSZTAŁT" in wynik["wskazowka"]
        assert "oddaj_czlowiekowi" in wynik["wskazowka"]

    def test_podpis_potwierdzenia_NIE_zostaje_zapisany(self, monkeypatch):
        # Kluczowe dla I2: gdyby bramka odmawiała PO zapisaniu podpisu, klient
        # mógłby w kolejnej turze „potwierdzić" podsumowanie, którego nigdy nie
        # zobaczył — dokładnie to obejście, które zamknęła recenzja U1.
        self._sprobuj_wyslac(monkeypatch, 94063, "Blat okrągły dębowy")
        assert not stan.podsumowanie_wyslane()

    def test_lapie_kazdy_ksztalt_z_reguly_KSZTALT(self, monkeypatch):
        nazwy = ("Blat okrągły", "Blat owalny", "Blat w kształcie litery L",
                 "Blat z łukiem", "Blat nieregularny", "Blat półokrągły",
                 "Blat eliptyczny", "Blat L-kształtny")
        for numer, nazwa in enumerate(nazwy):
            wynik, wyslane = self._sprobuj_wyslac(monkeypatch, 94070 + numer, nazwa)
            assert wynik.get("error") == "KSZTALT_W_NAZWIE", nazwa
            assert wyslane == [], nazwa

    def test_dziala_bez_diakrytykow(self, monkeypatch):
        # Kanały marketplace potrafią rozebrać polskie znaki (sanitize.py),
        # a nazwę pisze model — nie zakładamy, że zawsze z ogonkami.
        wynik, _ = self._sprobuj_wyslac(monkeypatch, 94080, "Blat okragly debowy")
        assert wynik.get("error") == "KSZTALT_W_NAZWIE"

    def test_zwykla_nazwa_przechodzi(self, monkeypatch):
        # Kontrola negatywna — bramka ma być wąska. Prostokątne blaty to
        # cały normalny ruch i żaden z nich nie może się o nią potknąć.
        for numer, nazwa in enumerate(("Blat", "blat kuchenny dębowy",
                                       "Parapet jesionowy", "Stopnie schodowe",
                                       "Blat roboczy 180x60")):
            wynik, wyslane = self._sprobuj_wyslac(monkeypatch, 94090 + numer, nazwa)
            assert wynik["ok"] is True, nazwa
            assert wyslane, nazwa

    def test_slowo_ksztaltu_w_INNYM_polu_nie_blokuje_podsumowania(self, monkeypatch):
        # Bramka patrzy WYŁĄCZNIE na nazwę produktu. Okrągły otwór pod baterię
        # w prostokątnym blacie jest normalną, poprawną pozycją — i jego opis
        # ma dalej dochodzić do klienta razem z adnotacją o kosztach wycięć.
        stan.ustaw_kontekst(94095)
        pozycja = dict(_pozycja(), produkt="Blat kuchenny",
                       otwory=["okrągły otwór pod baterię fi 35"])
        monkeypatch.setattr(stan, "pozycje", lambda: [pozycja])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append(tekst) or True)
        wynik = podsumowanie.wyslij()
        assert wynik["ok"] is True
        assert "okrągły otwór pod baterię" in wyslane[0]

    def test_bramka_zostawia_slad_w_logu(self, monkeypatch):
        # „Nie przechodzi po cichu": trafienie ma dać się policzyć na skrzynce
        # testowej tak samo jak trafienia guardraila G3.
        linie = []
        monkeypatch.setattr(podsumowanie, "log", lambda tekst: linie.append(tekst))
        self._sprobuj_wyslac(monkeypatch, 94096, "Blat okrągły dębowy")
        assert any("ksztalt w nazwie" in linia for linia in linie), linie


class TestUN7BramkaKsztaltuPoDeklaracjiIPoNazwie:
    """Zadanie 3 (U-N7) — bramka kształtu przestaje stać na jednym regeksie.

    DLACZEGO TO NIE WYSTARCZAŁO. Jedyną kontrolą kształtu było
    `_KSZTALT_W_NAZWIE` czytające pole `produkt`, a lista słów nie znała ANI
    JEDNEGO wielokąta. Rozmowa produkcyjna 4727 (blat sześciokątny 87x75
    o boku 43 cm) nie została wyceniona jak prostokąt WYŁĄCZNIE dlatego, że
    model nie zapisał żadnego pola i bezpiecznik braku postępu zabrał rozmowę
    wcześniej — czyli osłoną było niedziałanie bota. Dwie z dwunastu zmierzonych
    rozmów produkcyjnych (4727, 4819) to takie kształty: 17% próbki.

    Druga rzecz: nazwę pisze model, a reguła KSZTAŁT każe mu kształtu w
    podsumowaniu NIE nazywać — bramka po nazwie sprawdza więc pole, którego
    poprawnie zachowujący się model NIE wypełni. Stąd `ksztalt`: jawna
    deklaracja, niezależna od tego, jak nazwał pozycję."""

    def _wyslij_z(self, monkeypatch, conv_id, **pola):
        stan.ustaw_kontekst(conv_id)
        pozycja = dict(_pozycja(), **pola)
        monkeypatch.setattr(stan, "pozycje", lambda: [pozycja])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        wyslane = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, token=None: wyslane.append(tekst) or True)
        return podsumowanie.wyslij(), wyslane

    @pytest.mark.parametrize("nazwa", [
        "Blat sześciokątny 87x75", "Blat szesciokatny 87x75", "Blat sześciokąt",
        "Blat pięciokątny", "Blat pieciokatny",
        "Blat ośmiokątny", "Blat osmiokatny",
        "Blat wielokątny", "Blat wielokatny",
        "Blat trójkątny", "Blat trojkatny",
        "Blat trapezowy", "Blat w kształcie trapezu",
        "Blat rombowy", "Blat romb",
        "Blat w kształcie litery L", "Blat litery L", "Blat litera L",
        "Blat w serek", "Blat serek",
    ])
    def test_nowe_slowa_ksztaltu_blokuja_podsumowanie(self, monkeypatch, nazwa):
        # Odmiana ORAZ pisownia bez ogonków — kanały marketplace potrafią
        # rozebrać polskie znaki (sanitize.py), a nazwę pozycji pisze model.
        wynik, wyslane = self._wyslij_z(monkeypatch, 94200, produkt=nazwa)
        assert wynik.get("error") == "KSZTALT_W_NAZWIE", nazwa
        assert wyslane == [], nazwa

    @pytest.mark.parametrize("nazwa", [
        "Blat", "Blat kuchenny dębowy", "Parapet jesionowy", "Stopnie schodowe",
        "Blat roboczy 180x60", "Blat pod zlew", "Blat barowy",
    ])
    def test_zwykle_nazwy_nadal_przechodza(self, monkeypatch, nazwa):
        # Kontrola negatywna po rozszerzeniu listy: bramka ma zostać WĄSKA.
        # Prostokątne blaty to cały normalny ruch i żaden nie może się o nią
        # potknąć — inaczej „naprawa" oddaje konsultantowi zdrowe rozmowy.
        wynik, wyslane = self._wyslij_z(monkeypatch, 94210, produkt=nazwa)
        assert wynik["ok"] is True, nazwa
        assert wyslane, nazwa

    def test_zadeklarowany_ksztalt_blokuje_mimo_niewinnej_nazwy(self, monkeypatch):
        # Sedno naprawy: model zachowuje się ZGODNIE z regułą KSZTAŁT (nie
        # nazywa kształtu w podsumowaniu), więc regex nie ma czego złapać.
        wynik, wyslane = self._wyslij_z(monkeypatch, 94220, produkt="Blat kuchenny",
                                        ksztalt="sześciokąt")
        assert wynik["ok"] is False
        assert wynik["error"] == "KSZTALT_NIEPROSTOKATNY"
        assert wyslane == []

    def test_deklaracja_ksztaltu_nie_zapisuje_podpisu_potwierdzenia(self, monkeypatch):
        # Kluczowe dla I2, dokładnie jak przy bramce po nazwie: podpis zapisany
        # mimo odmowy pozwoliłby klientowi „potwierdzić" podsumowanie, którego
        # nigdy nie zobaczył.
        self._wyslij_z(monkeypatch, 94221, produkt="Blat kuchenny", ksztalt="trapez")
        assert not stan.podsumowanie_wyslane()

    def test_wskazowka_odsyla_do_reguly_KSZTALT_i_niesie_opis_klienta(self, monkeypatch):
        wynik, _ = self._wyslij_z(monkeypatch, 94222, produkt="Blat kuchenny",
                                  ksztalt="sześciokąt foremny")
        assert "KSZTAŁT" in wynik["wskazowka"]
        assert "oddaj_czlowiekowi" in wynik["wskazowka"]
        assert "sześciokąt foremny" in wynik["wskazowka"]

    @pytest.mark.parametrize("deklaracja", [
        "prostokąt", "prostokat", "Prostokątny", "kwadrat", "kwadratowy", "",
    ])
    def test_prostokat_zadeklarowany_wprost_przechodzi(self, monkeypatch, deklaracja):
        # Regresja: model, który to pole wypełnia ZAWSZE, nie może zablokować
        # sobie każdej wyceny.
        wynik, wyslane = self._wyslij_z(monkeypatch, 94230, produkt="Blat kuchenny",
                                        ksztalt=deklaracja)
        assert wynik["ok"] is True, deklaracja
        assert wyslane, deklaracja

    def test_wartosc_nieczytelna_blokuje_bo_bramka_jest_fail_closed(self, monkeypatch):
        # Konwencja odwrotna („czego nie rozumiem, to prostokąt") znaczyłaby, że
        # literówka modelu przywraca cichą wycenę sześciokąta jak prostokąta.
        wynik, _ = self._wyslij_z(monkeypatch, 94231, produkt="Blat kuchenny",
                                  ksztalt="prostokąt z zaokrąglonym rogiem")
        assert wynik["error"] == "KSZTALT_NIEPROSTOKATNY"

    def test_deklaracja_ma_pierwszenstwo_przed_nazwa(self, monkeypatch):
        # Obie linie obrony trafiają naraz. Wygrywa deklaracja, bo niesie opis
        # kształtu podany przez klienta — czyli to, co ma wejść do powodu
        # handoffu („kształt inny niż prostokąt: <opis klienta>").
        wynik, _ = self._wyslij_z(monkeypatch, 94232, produkt="Blat okrągły",
                                  ksztalt="sześciokąt")
        assert wynik["error"] == "KSZTALT_NIEPROSTOKATNY"

    def test_ksztalt_w_INNYM_polu_nadal_nie_blokuje(self, monkeypatch):
        # Bramka po deklaracji nie rozszerza zakresu bramki po nazwie:
        # „okrągły otwór pod baterię" w prostokątnym blacie to poprawna pozycja.
        wynik, wyslane = self._wyslij_z(
            monkeypatch, 94233, produkt="Blat kuchenny",
            otwory=["okrągły otwór pod baterię fi 35"])
        assert wynik["ok"] is True
        assert "okrągły otwór pod baterię" in wyslane[0]

    def test_bramka_po_deklaracji_zostawia_slad_w_logu(self, monkeypatch):
        # „Nie przechodzi po cichu" — trafienia mają dać się policzyć na
        # skrzynce testowej, tak samo jak trafienia bramki po nazwie.
        linie = []
        monkeypatch.setattr(podsumowanie, "log", lambda tekst: linie.append(tekst))
        self._wyslij_z(monkeypatch, 94234, produkt="Blat kuchenny", ksztalt="romb")
        assert any("bramka ksztaltu" in linia for linia in linie), linie

    def test_ksztalt_nie_przechodzi_do_kalkulatora(self, monkeypatch):
        # Bramka stoi PRZED `calculate` — cena prostokąta dla sześciokąta nie
        # ma po co powstawać, bo model mógłby ją zacytować (rejestr G1 uznałby
        # ją za prawdziwą, bo PRZYSZŁA z kalkulatora).
        stan.ustaw_kontekst(94235)
        pozycja = dict(_pozycja(), produkt="Blat kuchenny", ksztalt="sześciokąt")
        monkeypatch.setattr(stan, "pozycje", lambda: [pozycja])
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        wywolano = []
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate",
                            lambda p, o: wywolano.append(1) or {"ok": True, "totals": {}})
        podsumowanie.wyslij()
        assert not wywolano

    def test_notatka_dla_konsultanta_NIESIE_ksztalt(self):
        # Drugi odbiorca `_linia` to prywatna notatka dla konsultanta
        # (`notatki.tresc_dla_agenta`). Po handoffie na kształcie notatka
        # opisywała sześciokąt 87x75 jako zwykły blat 87x75 — specyfikacja
        # MYLĄCA, nie tylko niepełna (rozmowa 4727: konsultantka i tak musiała
        # dopytać o 6 długości krawędzi).
        linia = podsumowanie._linia(dict(_pozycja(), produkt="blat kuchenny",
                                         ksztalt="sześciokąt o boku 43 cm"))
        assert "kształt: sześciokąt o boku 43 cm" in linia

    def test_prostokat_nie_dokleja_slowa_ksztalt_do_linii(self):
        # Klient NIGDY nie zobaczy tej gałęzi (bramka odmawia wcześniej), ale
        # „kształt: prostokąt" przy każdej normalnej pozycji byłoby szumem
        # w podsumowaniu, które klient PODPISUJE.
        for deklaracja in ("", "prostokąt", "kwadratowy"):
            linia = podsumowanie._linia(dict(_pozycja(), ksztalt=deklaracja))
            assert "kształt" not in linia, deklaracja



class TestZ4PokazanaKwota:
    """Z4: kwota, ktora klient FAKTYCZNIE zobaczyl, zapisywana do `pro_stan`
    RAZEM z `oczekiwany_podpis` — do prywatnej notatki dla konsultanta.

    Do tej poprawki notatka handoffowa nie drukowala ceny w ogole i nie dalo sie
    jej odtworzyc: rejestr `pro_kwoty` zawiera WSZYSTKIE kwoty zwrocone przez
    kalkulator (ceny jednostkowe, sumy czastkowe), bez sladu, ktora z nich poszla
    do klienta jako cena calosci."""

    def _przygotuj(self, monkeypatch, conv_id):
        stan.ustaw_kontekst(conv_id)
        poz = [_pozycja()]
        monkeypatch.setattr(stan, "pozycje", lambda: poz)
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        monkeypatch.setattr(podsumowanie, "cw_agent_reply", lambda *a, **k: True)

    def test_bez_dostawy_zapisuje_sume_produktow(self, monkeypatch):
        self._przygotuj(monkeypatch, 94060)
        podsumowanie.wyslij()
        assert stan.pokazana_kwota() == 843.04

    def test_z_dostawa_zapisuje_sume_z_dostawa(self, monkeypatch):
        # Klient widzi w podsumowaniu linie „Razem z dostawa" — to JA ma zobaczyc
        # konsultant w notatce, nie sama cene produktu.
        self._przygotuj(monkeypatch, 94061)
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.00)
        podsumowanie.wyslij()
        assert stan.pokazana_kwota() == 1093.04

    def test_nieudana_wysylka_nie_zapisuje_kwoty(self, monkeypatch):
        # Ta sama zasada co U1 dla `oczekiwany_podpis`: kwota z podsumowania,
        # ktore utknelo na bledzie Chatwoota, NIE jest kwota pokazana klientowi.
        self._przygotuj(monkeypatch, 94062)
        monkeypatch.setattr(podsumowanie, "cw_agent_reply", lambda *a, **k: False)
        podsumowanie.wyslij()
        assert stan.pokazana_kwota() is None

    def test_linia_kwoty_nie_wychodzi_do_klienta(self, monkeypatch):
        """I1, wlasciwa powierzchnia tej zmiany: linia „Ostatnia kwota pokazana
        klientowi" jest tekstem dla KONSULTANTA i ma isc wylacznie prywatnym
        `cw_note`.

        Testu „kwota nie wchodzi do rejestru G1" tu NIE MA, i to swiadomie —
        bylby falszywym zapewnieniem. Kwota pokazana klientowi to albo
        `totals.total_brutto`, albo suma z dostawa, a obie rejestruje
        `kwoty_z_wyniku`/`kwoty_dostawy` PRZED zapisem `pokazana_kwota`. G1 te
        liczbe zna i ma znac: klient widzi ja w podsumowaniu, wiec bot musi moc
        ja powtorzyc. Ryzykiem, ktore ta zmiana faktycznie tworzy, jest wyciek
        TRESCI NOTATKI do klienta — i to jest tu mierzone: zbieramy WSZYSTKO,
        co poszlo kanalem do klienta, i sprawdzamy, ze notatkowej linii tam nie
        ma, mimo ze notatka powstala i poszla `cw_note`."""
        from bots_pro import notatki

        self._przygotuj(monkeypatch, 94063)
        do_klienta = []
        do_notatek = []
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, **k: do_klienta.append(tekst) or True)
        monkeypatch.setattr(notatki, "cw_note",
                            lambda cid, tekst, token=None: do_notatek.append(tekst) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        podsumowanie.wyslij()
        stan.handoff("klient prosi o czlowieka")

        # Obie kontrole zywotnosci: bez nich petla nizej przechodzilaby na
        # pustej liscie, czyli test bylby zielony takze wtedy, gdy nic sie nie
        # wyslalo (dokladnie ta wada, ktora mial poprzednik tego testu).
        assert do_klienta, "do klienta nie poszlo nic — petla nizej nie mierzylaby niczego"
        assert do_notatek, "notatka w ogole nie powstala — test nie mierzylby niczego"
        assert any("Ostatnia kwota pokazana klientowi" in t for t in do_notatek)
        for tekst in do_klienta:
            assert "Ostatnia kwota pokazana klientowi" not in tekst
            assert "przekazuje rozmowę konsultantowi" not in tekst


class TestWyslijCzytaStanPodZamkiem:
    """P1/P2/P3 (kontrola koncowa): `wyslij()` bralo migawke `stan.pozycje()`
    POZA `zamek_stanu` i po powrocie z kalkulatora juz do bazy nie zagladalo.

    `wyslij_podsumowanie` jest zwyklym `@function_tool`, wiec SDK odpala je
    ROWNOLEGLE z `zapisz_pozycje` tego samego kroku modelu — a prompt („ZAPISUJ
    NA BIEZACO" + klauzula kompletnosci) ustawia wyzwalacz podsumowania
    dokladnie na krok, w ktorym leca ostatnie zapisy. Skutek biznesowy jest
    IDENTYCZNY z awaria conv 4912, ktora zamkniete zapisy juz naprawily: klient
    widzi jedna pozycje i jedna cene zamiast kompletu, i te cene potwierdza
    (I2). Zmienia sie tylko przyczyna — z utraty zapisu na nieaktualny odczyt.

    ZMIERZONE, wierna reprodukcja SDK (jeden krok modelu = `asyncio.gather` po
    13 wywolaniach `zapisz_pozycje` i jednym `wyslij_podsumowanie`, kazde przez
    `on_invoke_tool`; 20 przebiegow):
      - PRZED naprawa: w `pro_dane` komplet 13/13 w 20/20, a u KLIENTA
        1..13 pozycji — komplet tylko w 8/20, najczesciej 1 pozycja;
      - PO naprawie: u klienta 13/13 w 20/20.

    Testy nizej NIE licza na scheduler. Odtwarzaja ten sam przeplot
    deterministycznie: watek glowny TRZYMA `zamek_stanu` i pod nim wykonuje
    zapisy (RLock jest reentrantny), a watek podsumowania startuje wczesniej.
    Kod sprzed naprawy czyta wtedy baze BEZ zamka, czyli sprzed zapisow;
    kod po naprawie czeka na zamek i widzi komplet. Asercja dotyczy liczby
    pozycji WIDZIANYCH PRZEZ KLIENTA (linie „•" w tresci, ktora poszla
    `cw_agent_reply`), a nie liczby pozycji w bazie — w tym rzecz, ze baza
    byla poprawna przez caly czas."""

    NAZWY_4912 = ["blat-1", "parapet-2", "polka-3", "stopien-4", "listwa-5",
                  "horizontal-divider", "panel-7", "front-8", "bok-9",
                  "plecy-10", "wieniec-11", "cokol-12", "blenda-13"]

    @staticmethod
    def _watek_wyslij(conv_id, wynik):
        """Watek robiacy z `wyslij()` to, co robi SDK z cialem `@function_tool`:
        osobny watek, ktory jawnie ustawia `_conv_id` (gole watki kontekstu nie
        dziedzicza, `asyncio.to_thread` go kopiuje — efekt jest ten sam)."""
        import threading

        def _cialo():
            stan._conv_id.set(conv_id)
            stan._persona.set("pro")
            wynik.update(podsumowanie.wyslij() or {})

        return threading.Thread(target=_cialo)

    def _przygotuj_atrapy(self, monkeypatch, wyslane):
        monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _zaladuj_atrape_wysylki(monkeypatch)
        monkeypatch.setattr(podsumowanie, "cw_agent_reply",
                            lambda cid, tekst, **k: wyslane.append(tekst) or True)

    def test_klient_dostaje_komplet_pozycji_zapisanych_w_tym_samym_kroku(self, monkeypatch):
        import time

        conv_id = 94200
        wyslane, wynik = [], {}
        stan.ustaw_kontekst(conv_id)
        self._przygotuj_atrapy(monkeypatch, wyslane)

        watek = self._watek_wyslij(conv_id, wynik)
        with stan.zamek_stanu:
            watek.start()
            # Tyle, zeby watek podsumowania na pewno doszedl do odczytu stanu.
            # Kod sprzed naprawy odczytuje TU (zamka nie bierze) i widzi baze
            # sprzed zapisow; kod po naprawie stoi na zamku.
            time.sleep(0.05)
            for nazwa in self.NAZWY_4912:
                stan.zapisz_pozycje(nazwa, produkt="blat", dlugosc_cm=101,
                                    szerokosc_cm=42.5, grubosc_cm=4, ilosc=2,
                                    selected_variant="buk-lity-ab",
                                    wykonczenie="surowe")
        watek.join(timeout=10)
        stan.ustaw_kontekst(conv_id)

        assert len(stan.pozycje()) == 13, "baza ma miec komplet — to nie jest test zapisu"
        assert wynik.get("ok") is True, wynik
        assert sum(tekst.count("•") for tekst in wyslane) == 13

    def test_deklaracja_ksztaltu_w_trakcie_liczenia_wstrzymuje_wysylke(self, monkeypatch):
        """P2: bramka ksztaltu badala migawke SPRZED `calculate`, a samo
        `calculate` to HTTP z timeoutem 30 s poza zamkiem. Deklaracja
        „a ma byc szesciokatny", ktora trafila do bazy w tym oknie, byla dla
        bramki niewidzialna i klient dostawal pelne podsumowanie z cena
        PROSTOKATA dla szesciokata (conv 4727) — pod podpisem I2."""
        conv_id = 94201
        wyslane = []
        stan.ustaw_kontekst(conv_id)
        stan.zapisz_pozycje("1", produkt="blat kuchenny", dlugosc_cm=87,
                            szerokosc_cm=75, grubosc_cm=1.9, ilosc=1,
                            selected_variant="dab-lity-ab", wykonczenie="surowe")
        self._przygotuj_atrapy(monkeypatch, wyslane)

        def _kalkulator_z_wyscigiem(pozycje, opcje):
            # Rownolegly `zapisz_pozycje` z tego samego kroku modelu.
            stan.zapisz_pozycje("1", ksztalt="sześciokąt o boku 43 cm")
            return {"ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}}

        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", _kalkulator_z_wyscigiem)
        wynik = podsumowanie.wyslij()

        assert wynik["ok"] is False
        assert wynik["error"] == "KSZTALT_NIEPROSTOKATNY"
        assert wyslane == [], "klient NIE ma zobaczyc ceny prostokata dla szesciokata"
        # I1: kwota prostokata nie ma prawa zostac „znana" guardrailowi G1 —
        # inaczej bot moglby ja zacytowac w dowolnej kolejnej turze.
        assert stan.znane_kwoty() == set()

    def test_zmiana_wymiaru_w_trakcie_liczenia_nie_rejestruje_kwot(self, monkeypatch):
        """P3: `wyslij()` wolalo `zapamietaj_kwoty` bez kontroli, ktora ma
        `policz_wycene` — a to ta sama kwota z tego samego kalkulatora. Cena
        policzona dla konfiguracji, z ktorej klient wlasnie zrezygnowal, nie ma
        prawa wejsc do rejestru G1 jako znana (wzorzec z rozmow 4910 i 4799).

        Samo podsumowanie idzie do klienta swiadomie: jest wewnetrznie SPOJNE
        (pokazuje te pozycje, dla ktorych policzono cene), a I2 zostaje
        fail-closed, bo podpis liczy sie z tej samej migawki."""
        conv_id = 94202
        wyslane = []
        stan.ustaw_kontekst(conv_id)
        stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                            grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                            wykonczenie="surowe")
        self._przygotuj_atrapy(monkeypatch, wyslane)

        def _kalkulator_z_wyscigiem(pozycje, opcje):
            stan.zapisz_pozycje("1", dlugosc_cm=240)
            return {"ok": True, "totals": {"total_netto": 1574.56, "total_brutto": 1936.71}}

        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", _kalkulator_z_wyscigiem)
        wynik = podsumowanie.wyslij()

        assert wynik["ok"] is True
        assert stan.znane_kwoty() == set()

    def test_zmiana_NIECENOTWORCZA_w_trakcie_liczenia_nie_blokuje_rejestracji(self, monkeypatch):
        """Kontrola negatywna — bez niej powyzsza bramka moglaby byc dowolnie
        ciasna. Dopisanie otworu nie zmienia ceny (`otwory` to pole OPISOWE,
        `build_products` go nie czyta), wiec kwoty MAJA wejsc do rejestru:
        inaczej typowa tura „dopisuje wyciecie na zlew, cena bez zmian"
        konczylaby sie falszywym alarmem G1 na PRAWDZIWEJ kwocie."""
        conv_id = 94203
        wyslane = []
        stan.ustaw_kontekst(conv_id)
        stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                            grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                            wykonczenie="surowe")
        self._przygotuj_atrapy(monkeypatch, wyslane)

        def _kalkulator_z_otworem(pozycje, opcje):
            stan.zapisz_pozycje("1", otwory=["otwór na zlew 50x40 cm"])
            return {"ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}}

        monkeypatch.setattr(podsumowanie.crm_calc, "calculate", _kalkulator_z_otworem)
        wynik = podsumowanie.wyslij()

        assert wynik["ok"] is True
        assert {"685.40", "843.04"} <= stan.znane_kwoty()
