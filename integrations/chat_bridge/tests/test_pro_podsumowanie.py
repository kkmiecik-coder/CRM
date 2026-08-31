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
