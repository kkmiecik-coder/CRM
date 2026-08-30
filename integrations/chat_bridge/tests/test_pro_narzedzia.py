# -*- coding: utf-8 -*-
"""
Narzędzia agenta wyceny — schematy, inwarianty przenośności i realne wywołania.

Schemat enumu 'selected_variant' jest tu najważniejszy: klasa B/B istnieje
WYŁĄCZNIE dla dębu, a dziś variant_code('Jesion','Lity','B/B') zwraca None
i pozycja wypada z wyceny bez wyraźnego błędu. Enum to zamyka.

narzedzia.py importuje `agents` na poziomie modułu (dekoruje funkcje
@function_tool) — bez zainstalowanego SDK cały ten plik ma zostać POMINIĘTY,
nie zerwany błędem importu przy kolekcjonowaniu testów. `pytest.importorskip`
na samej górze robi dokładnie to (wzorzec z test_pro_models.py).
"""
import asyncio
import json

import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from agents.tool_context import ToolContext

from bots import crm_calc
from bots_pro import narzedzia as n
from bots_pro import stan

stan.init_pro()


def _wolaj(tool, **kwargs):
    """Woła CIAŁO narzędzia SDK dokładnie tak, jak zrobiłby to Runner —
    przez on_invoke_tool, z prawdziwym parsowaniem JSON-a argumentów. Dowodzi
    więc faktycznego przekazania parametrów do warstwy stan/crm_calc, nie
    tylko poprawności zadeklarowanego schematu."""
    ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id="test",
                       tool_arguments="{}")
    return asyncio.run(tool.on_invoke_tool(ctx, json.dumps(kwargs)))


class TestEnumWariantow:
    def test_osiem_wariantow_bez_wiecej(self):
        assert len(n.WARIANTY) == 8

    def test_bb_istnieje_tylko_dla_debu(self):
        bb = [w for w in n.WARIANTY if w.endswith("-bb")]
        assert bb == ["dab-lity-bb", "dab-micro-bb"]

    def test_jesion_i_buk_maja_tylko_ab(self):
        for kod in n.WARIANTY:
            if kod.startswith(("jes-", "buk-")):
                assert kod.endswith("-ab")

    def test_kazdy_wariant_jest_rozpoznawalny_przez_crm_calc(self):
        # Enum narzedzia.py i mapa crm_calc.VARIANT_CODES musza sie zgadzac —
        # inaczej model wybralby wartosc, ktorej stan._rozloz_wariant nie rozpozna.
        assert set(n.WARIANTY) == set(crm_calc.VARIANT_CODES)


class TestLiteryKrawedzi:
    def test_komplet_liter(self):
        assert set(n.LITERY_KRAWEDZI) == {
            "A", "B", "C", "D", "E", "F", "G", "H",
            "N1", "N2", "N3", "N4", "KG", "KD",
        }

    def test_zgodnosc_z_crm_calc_edge_letters(self):
        assert set(n.LITERY_KRAWEDZI) == crm_calc.EDGE_LETTERS


class TestZestawNarzedzi:
    def test_agent_wyceny_ma_komplet_narzedzi(self):
        nazwy = {t.name for t in n.NARZEDZIA_WYCENY}
        assert nazwy == {
            "pobierz_opcje", "zapisz_pozycje", "policz_wycene", "policz_wysylke",
            "wyslij_podsumowanie", "potwierdz",
            "zapisz_wycene", "popraw_wycene", "znajdz_klienta",
            "przygotuj_zamowienie", "oddaj_czlowiekowi",
        }

    def test_jedenascie_narzedzi_dokladnie(self):
        # Konsolidacja kwoty_z_wyniku (rozstrzygniecie Task 2) NIE dodaje ani nie
        # usuwa zadnego narzedzia -- to prywatna wewnetrznie funkcja pomocnicza
        # wolana przez cialo policz_wycene, a nie osobny wpis w NARZEDZIA_WYCENY.
        assert len(n.NARZEDZIA_WYCENY) == 11

    def test_zadne_narzedzie_nie_jest_hostowane_przez_dostawce(self):
        # Inwariant 1b: file_search, web_search i spolka zamykaja droge do Anthropica.
        zakazane = {"file_search", "web_search", "code_interpreter", "computer"}
        nazwy = {t.name for t in n.NARZEDZIA_WYCENY}
        assert nazwy & zakazane == set()

    def test_kazde_narzedzie_ma_opis(self):
        # Bez opisu model zgaduje, kiedy wolac narzedzie — to wraca jako "nie rozumie".
        for t in n.NARZEDZIA_WYCENY:
            assert t.description and len(t.description) > 20


class TestSchematZapiszPozycje:
    """zapisz_pozycje musi wystawiać modelowi edges/otwory/wykończenie — bez
    tego w schemacie stan.zapisz_pozycje (które je już obsługuje) jest martwym
    kodem, bo model nie ma jak podać wartości, których nie widzi w narzędziu."""

    def _wlasciwosci(self):
        return n.zapisz_pozycje.params_json_schema["properties"]

    def test_ma_pole_edges(self):
        assert "edges" in self._wlasciwosci()

    def test_ma_pole_otwory(self):
        assert "otwory" in self._wlasciwosci()

    def test_ma_pole_wykonczenie(self):
        # Bez tego pola model nie ma jak ustawic "surowe"/"olejowane"/"lakierowane"
        # -- finishing_option_id samo nie wystarcza, crm_calc._finish_type czyta
        # WYLACZNIE tekst pola "wykonczenie" -- a bez niego KAZDA pozycja ladowalaby
        # w braki_mapowania niezaleznie od tego, co wybral klient.
        assert "wykonczenie" in self._wlasciwosci()

    def test_ksztalt_edges_ma_litera_typ_r_kat(self):
        # Ksztalt WEJSCIOWY (surowy), zgodny z tym, co przyjmuje
        # crm_calc.normalize_edges -- NIE ze znormalizowana postacia
        # (r_value/angle_value), ktora dopiero z niego powstaje.
        schemat = self._wlasciwosci()["edges"]
        warianty = schemat.get("anyOf", [schemat])
        [z_elementami] = [w for w in warianty if "items" in w]
        nazwa_definicji = z_elementami["items"]["$ref"].rsplit("/", 1)[-1]
        pola = set(n.zapisz_pozycje.params_json_schema["$defs"][nazwa_definicji]["properties"])
        assert pola == {"litera", "typ", "r", "kat"}

    def test_ksztalt_edges_dowod_zgodnosci_z_normalize_edges(self):
        # Dowod na prawdziwej funkcji, nie tylko na nazwach pol schematu.
        wynik = crm_calc.normalize_edges([{"litera": "A", "typ": "round", "r": 3}])
        assert wynik == [{"litera": "A", "typ": "round", "r_value": 3, "angle_value": None}]


class TestZapiszPozycjeWywolanie:
    """Realne wywołania narzędzia (nie tylko schemat) przez on_invoke_tool —
    dowód, że zapisz_pozycje z edges przechodzi przez PRAWDZIWE
    crm_calc.build_products bez trafienia w braki."""

    def test_pozycja_z_krawedziami_przechodzi_przez_prawdziwy_build_products(self):
        stan.ustaw_kontekst(96001)
        wynik = _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
                       szerokosc_cm=60, grubosc_cm=4, ilosc=1,
                       selected_variant="dab-lity-ab", wykonczenie="surowe",
                       edges=[{"litera": "A", "typ": "round", "r": 3, "kat": None}])
        assert wynik["ok"] is True

        products, braki = crm_calc.build_products(stan.pozycje(), {"finishing_options": []})
        assert braki == []
        assert len(products) == 1
        assert products[0]["edges"] == [
            {"letter": "A", "type": "round", "r_value": 3, "angle_value": None}]

    def test_wykonczenie_olejowane_z_finishing_id_przechodzi_bez_brakow(self):
        stan.ustaw_kontekst(96002)
        _wolaj(n.zapisz_pozycje, id="1", produkt="parapet", dlugosc_cm=100,
              szerokosc_cm=30, grubosc_cm=3, ilosc=2,
              selected_variant="jes-micro-ab", wykonczenie="olejowane",
              finishing_option_id=7)
        options = {"finishing_options": [{"id": 7, "price_netto": 10}]}
        products, braki = crm_calc.build_products(stan.pozycje(), options)
        assert braki == []
        assert products[0]["finishing_option_id"] == 7
        assert products[0]["finishing_type"] == "Olejowane"

    def test_otwory_zapisuja_sie_jako_lista_opisow(self):
        stan.ustaw_kontekst(96003)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat",
              otwory=["otwór na zlew 50x40 cm", "otwór na baterię"])
        (poz,) = stan.pozycje()
        assert poz["otwory"] == ["otwór na zlew 50x40 cm", "otwór na baterię"]

    def test_jawne_ostre_czysci_wczesniej_zapisane_krawedzie(self):
        # Rozstrzygniecie zadania: jawne "sharp" to sygnal WYCZYSZCZENIA, nie
        # kolejna wartosc do zapisania (crm_calc.normalize_edges sam odrzuca
        # "sharp" jako "brak obrobki" -- bez osobnej sciezki intencja klienta
        # "chce ostre" ginelaby, a stara obrobka zostawalaby na zawsze).
        stan.ustaw_kontekst(96004)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat",
              edges=[{"litera": "A", "typ": "round", "r": 5, "kat": None}])
        (poz,) = stan.pozycje()
        assert poz["edges"] != []

        _wolaj(n.zapisz_pozycje, id="1",
              edges=[{"litera": "A", "typ": "sharp", "r": None, "kat": None}])
        (poz,) = stan.pozycje()
        assert poz["edges"] == []

    def test_pominiecie_edges_nie_kasuje_wczesniej_zapisanych(self):
        stan.ustaw_kontekst(96005)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat",
              edges=[{"litera": "A", "typ": "round", "r": 5, "kat": None}])
        _wolaj(n.zapisz_pozycje, id="1", grubosc_cm=6)   # edges pominiete w tej turze
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "A", "typ": "round", "r_value": 5, "angle_value": None}]
        assert poz["grubosc"] == 6

    def test_nierozpoznany_wariant_nie_rozklada_gatunku_i_ladnuje_w_braki(self):
        # Model teoretycznie moze wywolac narzedzie z wartoscia spoza enuma
        # (np. blad warstwy posredniej) -- stan.py ma i tak nie zgadywac.
        stan.ustaw_kontekst(96006)
        _wolaj(n.zapisz_pozycje, id="1", selected_variant="nieistniejacy-wariant")
        (poz,) = stan.pozycje()
        assert "gatunek" not in poz
        products, braki = crm_calc.build_products(stan.pozycje(), {"finishing_options": []})
        assert products == []
        assert len(braki) == 1

    def test_usun_kasuje_pozycje(self):
        stan.ustaw_kontekst(96007)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        wynik = _wolaj(n.zapisz_pozycje, id="1", usun=True)
        assert wynik == {"ok": True, "usunieto": "1"}
        assert stan.pozycje() == []


class TestPoliczWyceneRejestrujeKwoty:
    """Inwariant I1 (rejestr kwot zasilaja WYLACZNIE policz_wycene i
    policz_wysylke) -- policz_wycene musi realnie dopisac kwoty przez
    wspolna funkcje podsumowanie.kwoty_z_wyniku, nie duplikowac jej logiki."""

    def test_policz_wycene_zapisuje_sumy_w_znanych_kwotach(self, monkeypatch):
        stan.ustaw_kontekst(96008)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        monkeypatch.setattr(n.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(n.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 685.40, "total_brutto": 843.04}})
        _wolaj(n.policz_wycene)
        assert {"685.40", "843.04"} <= stan.znane_kwoty()

    def test_policz_wysylke_zapisuje_koszt_dostawy(self, monkeypatch):
        stan.ustaw_kontekst(96009)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": True, "shipping_netto": 100.0, "shipping_brutto": 123.0})
        _wolaj(n.policz_wysylke, kod_pocztowy="00-000")
        assert {"100.00", "123.00"} <= stan.znane_kwoty()

    def test_policz_wysylke_zapisuje_zerowy_koszt_gdy_gratis(self, monkeypatch):
        # Wysylka za 0 zl (promocja) tez jest znana kwotoa -- prawdziwym zerem,
        # nie brakiem danych. Filtrowanie po samej prawdziwosci wartosci
        # ("if wynik.get(k)") zgubiloby 0.0, bo 0.0 jest falszywe w Pythonie.
        stan.ustaw_kontekst(96010)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": True, "shipping_netto": 0.0, "shipping_brutto": 0.0})
        _wolaj(n.policz_wysylke, kod_pocztowy="00-000")
        assert "0.00" in stan.znane_kwoty()
