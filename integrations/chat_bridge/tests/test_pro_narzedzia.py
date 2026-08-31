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
import sys
import types

import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from agents.tool_context import ToolContext

from bots import crm_calc
from bots_pro import narzedzia as n
from bots_pro import notatki, podsumowanie, potwierdzenia, stan
from bots_pro import wysylka as prawdziwa_wysylka

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


class TestPobierzOpcjePrzycina:
    """Task 5, rozstrzygniecie 1: selected_variant/wykonczenie/litery i typy
    krawedzi (jako WYBIERALNE WARTOSCI) sa enumami w schemacie (Literal[...])
    — model NIE potrzebuje juz z /api/bot/options listy DOZWOLONYCH KODOW
    wariantu/typow krawedzi, bo SDK i tak odrzuci wartosc spoza enumu zanim
    cialo narzedzia sie uruchomi. Zostawiamy finishing_options (id + full_path,
    bo finishing_option_id NIE jest enumem — katalog kolorow/polyskow jest
    zmienny) i limity wymiarowe — global_limits ORAZ per-wariant
    (variant_limits), bo to LICZBY Z CENNIKA (moga sie zmienic bez zmiany
    kodu), nie zbior dozwolonych kodow. Runda poprawek 1 (recenzja): przycięcie
    najpierw zgubiło variant_limits calkiem, zamazujac np. ze mikrowczep ma
    inna (wieksza) maksymalna dlugosc niz technologia lita — global_limits
    sam w sobie tego rozroznienia nie niesie."""

    _VARIANTS_MOCK = [
        {"variant_code": "dab-lity-ab", "species": "Dąb", "technology": "Lity",
         "wood_class": "A/B", "length_min": 40, "length_max": 450,
         "width_min": 10, "width_max": 120, "thickness_min": 1.5, "thickness_max": 4},
        {"variant_code": "dab-micro-ab", "species": "Dąb", "technology": "Mikrowczep",
         "wood_class": "A/B", "length_min": 40, "length_max": 500,
         "width_min": 10, "width_max": 120, "thickness_min": 1.5, "thickness_max": 4},
    ]

    def test_zwraca_finishing_options_i_limity_global_oraz_per_wariant(self, monkeypatch):
        monkeypatch.setattr(n.crm_calc, "get_options", lambda: {
            "ok": True,
            "variants": self._VARIANTS_MOCK,
            "global_limits": {"length_min": 40, "length_max": 500,
                               "width_min": 10, "width_max": 120,
                               "thickness_min": 1.5, "thickness_max": 4},
            "finishing_options": [
                {"id": 7, "full_path": "Olejowane / Dąb naturalny",
                 "price_netto": 12.5, "level": 2},
            ],
            "edge_types": [{"type": "round", "price_netto": 3}],
            "client_types": ["detaliczny"],
            "cutout_price_netto": 81.3,
            "shapes": ["rectangular", "round", "circle"],
            "vat": 1.23,
        })
        wynik = _wolaj(n.pobierz_opcje)
        assert wynik == {
            "finishing_options": [{"id": 7, "full_path": "Olejowane / Dąb naturalny"}],
            "global_limits": {"length_min": 40, "length_max": 500,
                               "width_min": 10, "width_max": 120,
                               "thickness_min": 1.5, "thickness_max": 4},
            "variant_limits": [
                {"variant_code": "dab-lity-ab", "length_min": 40, "length_max": 450,
                 "width_min": 10, "width_max": 120, "thickness_min": 1.5, "thickness_max": 4},
                {"variant_code": "dab-micro-ab", "length_min": 40, "length_max": 500,
                 "width_min": 10, "width_max": 120, "thickness_min": 1.5, "thickness_max": 4},
            ],
        }

    def test_limit_dlugosci_roznicuje_technologie(self, monkeypatch):
        # Dowod na rzeczywisty powod przywrocenia variant_limits: lita i
        # mikrowczep MAJA rozna maksymalna dlugosc, global_limits by to zlaczyl.
        monkeypatch.setattr(n.crm_calc, "get_options", lambda: {
            "variants": self._VARIANTS_MOCK, "global_limits": {}, "finishing_options": [],
        })
        wynik = _wolaj(n.pobierz_opcje)
        limity = {w["variant_code"]: w["length_max"] for w in wynik["variant_limits"]}
        assert limity["dab-lity-ab"] == 450
        assert limity["dab-micro-ab"] == 500

    def test_brak_polaczenia_z_crm_nie_wywala_narzedzia(self, monkeypatch):
        # crm_calc.get_options() zwraca {} przy awarii API (patrz jej docstring)
        # — pobierz_opcje ma wtedy zwrocic puste struktury, nie rzucic wyjatkiem.
        monkeypatch.setattr(n.crm_calc, "get_options", lambda: {})
        wynik = _wolaj(n.pobierz_opcje)
        assert wynik == {"finishing_options": [], "global_limits": None, "variant_limits": []}


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

    def test_selected_variant_ma_enum_z_pustym_stringiem_i_osmioma_wariantami(self):
        # W2 (runda poprawek 1): przed poprawka WARIANTY/LITERY_KRAWEDZI byly
        # martwe -- podpis narzedzia mial zwykly `str`, wiec komentarz "enum
        # zamyka to na poziomie schematu" byl niezgodny ze stanem kodu.
        schemat = self._wlasciwosci()["selected_variant"]
        assert set(schemat["enum"]) == {""} | set(n.WARIANTY)

    def test_wykonczenie_ma_enum_z_trzema_wartosciami_i_pustym_stringiem(self):
        schemat = self._wlasciwosci()["wykonczenie"]
        assert set(schemat["enum"]) == {"", "surowe", "olejowane", "lakierowane"}

    def test_litera_krawedzi_w_edges_ma_enum_zgodny_z_litery_krawedzi(self):
        nazwa_definicji = self._nazwa_definicji_krawedzi()
        pola = n.zapisz_pozycje.params_json_schema["$defs"][nazwa_definicji]["properties"]
        assert set(pola["litera"]["enum"]) == set(n.LITERY_KRAWEDZI)

    def test_typ_krawedzi_w_edges_ma_enum_round_chamfer_sharp(self):
        nazwa_definicji = self._nazwa_definicji_krawedzi()
        pola = n.zapisz_pozycje.params_json_schema["$defs"][nazwa_definicji]["properties"]
        assert set(pola["typ"]["enum"]) == {"round", "chamfer", "sharp"}

    def _nazwa_definicji_krawedzi(self):
        schemat = self._wlasciwosci()["edges"]
        warianty = schemat.get("anyOf", [schemat])
        [z_elementami] = [w for w in warianty if "items" in w]
        return z_elementami["items"]["$ref"].rsplit("/", 1)[-1]


class TestWartoscSpozaEnumuOdrzucanaPrzezSchemat:
    """W2 (runda poprawek 1): dowód na PRAWDZIWEJ ścieżce wywołania SDK (nie
    tylko na deklaracji schematu), że enum naprawdę zamyka model przed
    wysłaniem wartości spoza oferty — `on_invoke_tool` odrzuca taki JSON
    PRZED wykonaniem ciała narzędzia, więc `stan.zapisz_pozycje` w ogóle nie
    zostaje wywołane i żadna pozycja nie powstaje. Zachowanie zweryfikowane
    empirycznie w kontenerze: SDK w tej sytuacji zwraca string z komunikatem
    błędu (nie rzuca wyjątku i nie zwraca dict {"ok": ...})."""

    def test_selected_variant_spoza_enuma(self):
        stan.ustaw_kontekst(96011)
        wynik = _wolaj(n.zapisz_pozycje, id="1", selected_variant="jes-lity-bb")
        assert isinstance(wynik, str)
        assert "zapisz_pozycje" in wynik
        assert stan.pozycje() == []

    def test_wykonczenie_spoza_enuma(self):
        stan.ustaw_kontekst(96012)
        wynik = _wolaj(n.zapisz_pozycje, id="1", wykonczenie="matowe")
        assert isinstance(wynik, str)
        assert stan.pozycje() == []

    def test_litera_krawedzi_spoza_enuma(self):
        stan.ustaw_kontekst(96013)
        wynik = _wolaj(n.zapisz_pozycje, id="1",
                       edges=[{"litera": "Z", "typ": "round", "r": 5, "kat": None}])
        assert isinstance(wynik, str)
        assert stan.pozycje() == []

    def test_litera_wszystkie_makro_nie_jest_juz_w_enumie(self):
        # Świadoma zmiana zachowania (W2): stary silnik (bots/quotebot.py) i
        # crm_calc.normalize_edges rozumieją "WSZYSTKIE" jako skrót na A,B,C,D
        # — ale to narzędzie SDK teraz zamyka enum liter na 14 prawdziwych
        # wartościach z LITERY_KRAWEDZI, więc "WSZYSTKIE" NIE przechodzi przez
        # schemat. Model musi wypisać cztery osobne wpisy — bezpieczeństwo
        # zamkniętego enumu jest tu ważniejsze niż wygoda jednej skrótowej
        # wartości specjalnej.
        stan.ustaw_kontekst(96014)
        wynik = _wolaj(n.zapisz_pozycje, id="1",
                       edges=[{"litera": "WSZYSTKIE", "typ": "round", "r": 5, "kat": None}])
        assert isinstance(wynik, str)


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

    # Test "wartość spoza enuma nie rozkłada gatunku" PRZENIESIONY do
    # TestWartoscSpozaEnumuOdrzucanaPrzezSchemat (runda poprawek 1, W2):
    # od czasu, gdy selected_variant dostał Literal, taka wartość w ogóle
    # nie dociera do stan.zapisz_pozycje przez tę ścieżkę wywołania SDK —
    # `on_invoke_tool` odrzuca ją wcześniej. Defensywne zachowanie
    # stan.zapisz_pozycje na wypadek wywołania Z POMINIĘCIEM narzędzia SDK
    # nadal jest pokryte w tests/test_pro_stan.py
    # (test_zapisz_pozycje_z_nieznanym_wariantem_nie_rozklada_gatunku).

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

    def test_policz_wysylke_zapamietuje_dostawe_w_stanie(self, monkeypatch):
        # U4: bez trwalego zapisu dostawa nie ma jak wejsc ani do podpisu, ani do
        # podsumowania, ani do korekty wyceny w CRM.
        stan.ustaw_kontekst(96011)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": True, "carriers": 2, "carrier_name": "DPD",
            "shipping_netto": 203.25, "shipping_brutto": 250.0})
        _wolaj(n.policz_wysylke, kod_pocztowy="00-001")
        assert stan.dostawa() == {"kod_pocztowy": "00-001", "kurier": "DPD",
                                  "netto": 203.25, "brutto": 250.0}

    def test_policz_wysylke_bez_kuriera_czysci_wczesniejszy_koszt(self, monkeypatch):
        # Nowy kod pocztowy bez kuriera dla gabarytu NIE moze zostawic w stanie
        # kosztu sprzed zmiany — klient potwierdzilby nieaktualna cene dostawy.
        stan.ustaw_kontekst(96012)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.0)
        monkeypatch.setattr(n.crm_calc, "shipping_quote",
                            lambda p, kod: {"ok": True, "carriers": 0})
        _wolaj(n.policz_wysylke, kod_pocztowy="80-001")
        assert stan.dostawa() == {"kod_pocztowy": "80-001"}


class TestPoliczWyceneIWysylkePrzycinajaWynik:
    """W3 (runda poprawek 1 i 2): policz_wycene/policz_wysylke muszą zwracać
    modelowi WYŁĄCZNIE to, co rejestr I1 zna — inaczej bot cytujący prawdziwą
    cenę z WŁASNEGO wyniku WŁASNEGO narzędzia (niewybrany wariant,
    price_per_m3/price_per_m2/edges.details, albo raw_netto/brutto sprzed
    narzutu na pakowanie) zostałby przez guardrail G1 oskarżony o
    halucynację. Atrapa calculate() ma REALNY kształt (price_per_m3 w
    wariancie, price_per_m2 w finishing, details w edges) — runda poprawek 2:
    atrapa bez tych pól była ślepa na dokładnie ten wyciek."""

    def test_policz_wycene_nie_pokazuje_niewybranych_wariantow_ani_cen_jednostkowych(self, monkeypatch):
        stan.ustaw_kontekst(96019)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        monkeypatch.setattr(n.crm_calc, "get_options", lambda: {})
        monkeypatch.setattr(n.crm_calc, "calculate", lambda p, o: {
            "ok": True, "totals": {"total_netto": 934.2, "total_brutto": 1149.07},
            "products": [{
                "variants": [
                    {"variant_code": "dab-lity-ab", "available": True,
                     "price_per_m3": 8200.0, "unit_netto": 700.0, "unit_brutto": 861.0,
                     "total_netto": 700.0, "total_brutto": 861.0},
                    {"variant_code": "jes-lity-ab", "available": True,
                     "price_per_m3": 5800.0, "unit_netto": 500.0, "unit_brutto": 615.0,
                     "total_netto": 500.0, "total_brutto": 615.0},
                ],
                "finishing": {"netto": 200.0, "brutto": 246.0, "price_per_m2": 120.0},
                "edges": {"netto": 34.2, "brutto": 42.07, "details": [
                    {"letter": "A", "type": "round",
                     "price_netto": 27.0, "price_brutto": 33.21},
                    {"letter": "C", "type": "chamfer",
                     "price_netto": 7.2, "price_brutto": 8.86},
                ]},
            }],
        })
        wynik = _wolaj(n.policz_wycene)
        [prod] = wynik["products"]
        kody = [v["variant_code"] for v in prod["variants"]]
        assert kody == ["dab-lity-ab"]
        assert "jes-lity-ab" not in kody
        assert "price_per_m3" not in prod["variants"][0]
        assert "price_per_m2" not in prod["finishing"]
        assert "details" not in prod["edges"]
        # I1 nadal zna tylko to, co model widzi po przycięciu.
        assert "615.00" not in stan.znane_kwoty()
        assert "8200.00" not in stan.znane_kwoty()
        assert "120.00" not in stan.znane_kwoty()
        assert "27.00" not in stan.znane_kwoty()
        assert "861.00" in stan.znane_kwoty()
        assert "200.00" in stan.znane_kwoty()
        assert "34.20" in stan.znane_kwoty()

    def test_policz_wysylke_nie_pokazuje_ceny_kuriera_sprzed_narzutu(self, monkeypatch):
        # crm_calc.shipping_quote() niesie tez raw_netto/raw_brutto (cena
        # PRZED PACKING_MULTIPLIER) — to prawdziwe liczby, ktorych rejestr
        # (tylko shipping_netto/brutto) nie zna.
        stan.ustaw_kontekst(96020)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": True, "carriers": 2, "carrier_name": "DPD",
            "shipping_netto": 130.0, "shipping_brutto": 159.9,
            "raw_netto": 100.0, "raw_brutto": 123.0,
        })
        wynik = _wolaj(n.policz_wysylke, kod_pocztowy="00-000")
        assert "raw_netto" not in wynik
        assert "raw_brutto" not in wynik
        assert wynik["shipping_netto"] == 130.0
        assert wynik["shipping_brutto"] == 159.9
        assert wynik["carrier_name"] == "DPD"

    def test_policz_wysylke_bez_ok_zwraca_wynik_bez_zmian(self, monkeypatch):
        stan.ustaw_kontekst(96021)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": False, "errors": [{"code": "BAD_POSTCODE"}]})
        wynik = _wolaj(n.policz_wysylke, kod_pocztowy="zly-kod")
        assert wynik == {"ok": False, "errors": [{"code": "BAD_POSTCODE"}]}

    def test_policz_wysylke_bez_kuriera_pomija_klucze_none_zamiast_null(self, monkeypatch):
        # N2 (runda poprawek 2): dawne {'ok': True, 'carriers': 0} (brak
        # kuriera dla gabarytu) nie ma dostac jawnych "shipping_netto": null
        # itp. -- model moglby odczytac null jako "0 zl/gratis".
        stan.ustaw_kontekst(96028)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        monkeypatch.setattr(n.crm_calc, "shipping_quote", lambda p, kod: {
            "ok": True, "carriers": 0})
        wynik = _wolaj(n.policz_wysylke, kod_pocztowy="00-000")
        assert wynik == {"ok": True, "carriers": 0}
        assert "carrier_name" not in wynik
        assert "shipping_netto" not in wynik
        assert "shipping_brutto" not in wynik


def _zaladuj_atrape_wysylki(monkeypatch):
    """Podmienia bots_pro.wysylka w sys.modules (moduł powstaje dopiero w
    Task 6) — jak w tests/test_pro_podsumowanie.py i test_pro_i2_integracja.py.

    `wolno_linkowac` jest PRAWDZIWE, nie zaatrapowane (U11): to od niego zależy,
    czy `przygotuj_zamowienie` zwróci link, czy skończy notatką dla agenta —
    atrapa tej funkcji sprawdzałaby wyłącznie własną atrapę, a nie profil kanału
    z `bots.channel_caps`. `przygotuj` zostaje atrapą, bo tu chodzi o wywołanie
    ciała narzędzia, nie o formatowanie wysyłki."""
    modul = types.ModuleType("bots_pro.wysylka")
    modul.przygotuj = lambda tekst, persona: [tekst]
    modul.wolno_linkowac = prawdziwa_wysylka.wolno_linkowac
    monkeypatch.setitem(sys.modules, "bots_pro.wysylka", modul)


def _potwierdz_biezace_pozycje(monkeypatch, cytat="Tak, zgadzam się"):
    """Przechodzi PRAWDZIWĄ ścieżkę I2 — podsumowanie.wyslij() ->
    potwierdzenia.potwierdz() — dokładnie tak, jak zrobiłby to model w
    prawdziwej rozmowie, żeby bramka (potwierdzenia.sprawdz_bramke) miała co
    przepuścić. Wzorowane na tests/test_pro_i2_integracja.py."""
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
        "ok": True, "totals": {"total_netto": 100.0, "total_brutto": 123.0}})
    _zaladuj_atrape_wysylki(monkeypatch)
    monkeypatch.setattr(podsumowanie, "cw_agent_reply", lambda *a, **k: True)
    monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: cytat)
    assert podsumowanie.wyslij()["ok"] is True
    assert potwierdzenia.potwierdz(cytat)["ok"] is True


class TestBramkaI2WNarzedziach:
    """W4 (runda poprawek 1): dowód na PRAWDZIWY efekt uboczny, nie tylko na
    to, że narzędzie zwraca błąd — bez aktualnego potwierdzenia
    crm_calc.create_quote/update_quote i stan.link_do_checkoutu NIE MAJĄ
    zostać wywołane. Ta sama bramka (potwierdzenia.sprawdz_bramke) chroni
    zapisz_wycene, popraw_wycene (W5) i przygotuj_zamowienie."""

    def test_zapisz_wycene_bez_potwierdzenia_nie_wola_create_quote(self, monkeypatch):
        stan.ustaw_kontekst(96022)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        wywolania = []
        monkeypatch.setattr(n.crm_calc, "create_quote",
                            lambda *a, **k: wywolania.append(1) or {"ok": True})
        wynik = _wolaj(n.zapisz_wycene, client_id=1)
        assert wynik["ok"] is False
        assert wywolania == []

    def test_zapisz_wycene_z_aktualnym_potwierdzeniem_wola_create_quote(self, monkeypatch):
        stan.ustaw_kontekst(96023)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        wywolania = []
        monkeypatch.setattr(n.crm_calc, "create_quote",
                            lambda *a, **k: wywolania.append(a) or {"ok": True, "quote_number": "X"})
        wynik = _wolaj(n.zapisz_wycene, client_id=1)
        assert wynik["ok"] is True
        assert len(wywolania) == 1

    def test_popraw_wycene_bez_potwierdzenia_nie_wola_update_quote(self, monkeypatch):
        # W5 (runda poprawek 1): popraw_wycene byla JEDYNA sciezka zapisu bez
        # bramki I2 -- klient pod juz wyslanym linkiem widzialby dane, ktorych
        # nigdy nie potwierdzil.
        stan.ustaw_kontekst(96024)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat")
        wywolania = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: wywolania.append(1) or {"ok": True})
        wynik = _wolaj(n.popraw_wycene, edit_uuid="uuid-x")
        assert wynik["ok"] is False
        assert wywolania == []

    def test_popraw_wycene_z_aktualnym_potwierdzeniem_wola_update_quote(self, monkeypatch):
        stan.ustaw_kontekst(96025)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        wywolania = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: wywolania.append(a) or {"ok": True, "quote_number": "X"})
        wynik = _wolaj(n.popraw_wycene, edit_uuid="uuid-x")
        assert wynik["ok"] is True
        assert len(wywolania) == 1

    def test_popraw_wycene_przekazuje_kuriera_i_koszt_dostawy(self, monkeypatch):
        # U4 (recenzja koncowa): crm_calc.update_quote PRZYJMUJE courier_name/
        # shipping_*, stary silnik ich uzywa (bots/quotebot.py:1989), a Pro NIGDY —
        # wiec w CRM ladowala wycena BEZ dostawy, mimo ze klient potwierdzil cene
        # z dostawa.
        stan.ustaw_kontekst(96028)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.0)
        _potwierdz_biezace_pozycje(monkeypatch)
        przekazane = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: przekazane.append(k) or {"ok": True})
        _wolaj(n.popraw_wycene, edit_uuid="uuid-x")
        assert przekazane[0]["courier_name"] == "DPD"
        assert przekazane[0]["shipping_netto"] == 203.25
        assert przekazane[0]["shipping_brutto"] == 250.0

    def test_popraw_wycene_bez_znanej_dostawy_nie_wysyla_kuriera(self, monkeypatch):
        # Kontrola negatywna: brak oszacowania wysylki NIE moze trafic do CRM jako
        # "kurier None / 0 zl" — update_quote dopisuje wysylke tylko gdy courier_name.
        stan.ustaw_kontekst(96029)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        przekazane = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: przekazane.append(k) or {"ok": True})
        _wolaj(n.popraw_wycene, edit_uuid="uuid-x")
        assert przekazane[0].get("courier_name") is None

    def test_zapisz_wycene_zapamietuje_edit_uuid_i_link(self, monkeypatch):
        # Sonda P4 z recenzji: po create_quote zwracajacym edit_uuid stan zostawal
        # PUSTY, a link_do_checkoutu('') odpowiadalo "Brak zapisanej wyceny".
        stan.ustaw_kontekst(96030)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        _wolaj(n.zapisz_wycene, client_id=1)
        assert stan.zapisana_wycena() == {"edit_uuid": "UUID-XYZ",
                                          "public_url": "https://crm.example/q/abc"}

    def test_przygotuj_zamowienie_zwraca_public_url_bez_podanego_uuid(self, monkeypatch):
        # Specyfikacja, wiersz 442: model dostaje `public_url`. Fallback na
        # zapisany identyfikator dziala, gdy uuid wypadl juz z okna sesji SDK.
        stan.ustaw_kontekst(96031)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        _wolaj(n.zapisz_wycene, client_id=1)

        wynik = _wolaj(n.przygotuj_zamowienie)
        assert wynik["ok"] is True
        assert wynik["public_url"] == "https://crm.example/q/abc"

    def test_popraw_wycene_bez_podanego_uuid_uzywa_zapisanego(self, monkeypatch):
        stan.ustaw_kontekst(96032)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        stan.zapamietaj_wycene({"ok": True, "edit_uuid": "UUID-ZAPISANY",
                                "public_url": "https://crm.example/q/abc"})
        przekazane = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda uuid, *a, **k: przekazane.append(uuid) or {"ok": True})
        _wolaj(n.popraw_wycene)
        assert przekazane == ["UUID-ZAPISANY"]

    def test_zapisz_wycene_dopisuje_dostawe_przez_update_quote(self, monkeypatch):
        # POST /api/bot/quotes NIE przyjmuje kuriera (patrz bot_api.py) — jedyna
        # droga to PUT tuz po zapisie, dokladnie jak w starym silniku
        # (bots/quotebot.py:1983-1991). Bez tego klient potwierdza cene Z dostawa,
        # a pod linkiem widzi wycene BEZ niej.
        stan.ustaw_kontekst(96033)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.0)
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        przekazane = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda uuid, *a, **k: przekazane.append((uuid, k)) or {"ok": True})
        _wolaj(n.zapisz_wycene, client_id=1)
        assert przekazane[0][0] == "UUID-XYZ"
        assert przekazane[0][1]["courier_name"] == "DPD"

    def test_zapisz_wycene_bez_dostawy_nie_wola_update_quote(self, monkeypatch):
        stan.ustaw_kontekst(96034)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        wywolania = []
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: wywolania.append(1) or {"ok": True})
        _wolaj(n.zapisz_wycene, client_id=1)
        assert wywolania == []

    def test_przygotuj_zamowienie_bez_potwierdzenia_nie_zwraca_linku(self, monkeypatch):
        stan.ustaw_kontekst(96026)
        wywolania = []
        monkeypatch.setattr(stan, "link_do_checkoutu",
                            lambda uuid: wywolania.append(uuid) or {"ok": True, "edit_uuid": uuid})
        wynik = _wolaj(n.przygotuj_zamowienie, edit_uuid="uuid-x")
        assert wynik["ok"] is False
        assert wywolania == []

    def test_przygotuj_zamowienie_z_aktualnym_potwierdzeniem_zwraca_link(self, monkeypatch):
        stan.ustaw_kontekst(96027)
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
              szerokosc_cm=60, grubosc_cm=4, ilosc=1,
              selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        wywolania = []
        monkeypatch.setattr(stan, "link_do_checkoutu",
                            lambda uuid: wywolania.append(uuid) or {"ok": True, "edit_uuid": uuid})
        wynik = _wolaj(n.przygotuj_zamowienie, edit_uuid="uuid-x")
        assert wynik == {"ok": True, "edit_uuid": "uuid-x"}
        assert wywolania == ["uuid-x"]


class TestNieudaneDopisanieDostawy:
    """R1 (recenzja końcowa, runda 2): `zapisz_wycene` dopisuje dostawę OSOBNYM
    wywołaniem (`PUT /api/bot/quotes/<uuid>`), bo endpoint tworzący wycenę nie
    przyjmuje kuriera. Poprzednia runda zrobiła to best-effort — nieudane
    dopisanie tylko się logowało. To otwierało dokładnie tę dziurę, którą U4
    zamykało: klient potwierdza cenę Z DOSTAWĄ, a dostaje link do wyceny BEZ
    niej. Link nie może wtedy wyjść; rozmowa idzie do człowieka."""

    def _wycena_z_dostawa(self, monkeypatch, conv_id, wynik_update):
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
               szerokosc_cm=60, grubosc_cm=4, ilosc=1,
               selected_variant="dab-lity-ab", wykonczenie="surowe")
        stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.0)
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        monkeypatch.setattr(n.crm_calc, "update_quote", lambda *a, **k: wynik_update)

    def test_nieudane_dopisanie_nie_zwraca_linku(self, monkeypatch):
        self._wycena_z_dostawa(monkeypatch, 96051, {"ok": False, "errors": [{"code": "X"}]})
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        wynik = _wolaj(n.zapisz_wycene, client_id=1)

        assert wynik["ok"] is False
        assert "public_url" not in wynik
        assert "crm.example" not in json.dumps(wynik, ensure_ascii=False)

    def test_nieudane_dopisanie_oddaje_rozmowe_czlowiekowi_z_notatka(self, monkeypatch):
        self._wycena_z_dostawa(monkeypatch, 96052, {"ok": False, "errors": []})
        notatki_wyslane = []
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: notatki_wyslane.append(tekst) or True)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        _wolaj(n.zapisz_wycene, client_id=1)

        assert len(powody) == 1
        assert "dostaw" in powody[0].lower()

    def test_po_nieudanym_dopisaniu_link_do_checkoutu_odmawia(self, monkeypatch):
        self._wycena_z_dostawa(monkeypatch, 96053, {"ok": False, "errors": []})
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})
        _wolaj(n.zapisz_wycene, client_id=1)

        # Model NIE MOZE obejsc blokady, wolajac po prostu przygotuj_zamowienie.
        wynik = _wolaj(n.przygotuj_zamowienie)
        assert wynik["ok"] is False
        assert wynik["error"] == "WYCENA_BEZ_DOSTAWY"

    def test_udane_dopisanie_zwraca_link_normalnie(self, monkeypatch):
        # Kontrola pozytywna: sciezka szczesliwa bez zmian.
        self._wycena_z_dostawa(monkeypatch, 96054, {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("udany zapis nie oddaje rozmowy"))

        wynik = _wolaj(n.zapisz_wycene, client_id=1)

        assert wynik["ok"] is True
        assert _wolaj(n.przygotuj_zamowienie)["public_url"] == "https://crm.example/q/abc"

    def test_bez_dostawy_zachowanie_bez_zmian(self, monkeypatch):
        # Klient odbiera osobiscie — nie ma czego dopisywac, wiec nie ma czego
        # blokowac. `update_quote` w ogole nie jest wolane.
        stan.ustaw_kontekst(96055, persona_tury="pro")
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
               szerokosc_cm=60, grubosc_cm=4, ilosc=1,
               selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(n.crm_calc, "create_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        monkeypatch.setattr(n.crm_calc, "update_quote",
                            lambda *a, **k: pytest.fail("brak dostawy = brak PUT"))
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("brak dostawy nie oddaje rozmowy"))

        assert _wolaj(n.zapisz_wycene, client_id=1)["ok"] is True
        assert _wolaj(n.przygotuj_zamowienie)["public_url"] == "https://crm.example/q/abc"

    def test_udana_korekta_odblokowuje_link(self, monkeypatch):
        # Konsultant (albo bot w kolejnej turze) poprawia wycene — udany PUT z
        # kurierem znaczy, ze wycena JEST juz kompletna, wiec blokada znika.
        self._wycena_z_dostawa(monkeypatch, 96056, {"ok": False, "errors": []})
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})
        _wolaj(n.zapisz_wycene, client_id=1)
        assert _wolaj(n.przygotuj_zamowienie)["ok"] is False

        monkeypatch.setattr(n.crm_calc, "update_quote", lambda *a, **k: {
            "ok": True, "quote_number": "W/1", "edit_uuid": "UUID-XYZ",
            "public_url": "https://crm.example/q/abc"})
        assert _wolaj(n.popraw_wycene)["ok"] is True
        assert _wolaj(n.przygotuj_zamowienie)["public_url"] == "https://crm.example/q/abc"


def _wycena_gotowa_do_zamowienia(monkeypatch, conv_id, persona="allegro"):
    """Rozmowa doprowadzona do stanu „wycena zapisana i potwierdzona" — punkt,
    w którym `przygotuj_zamowienie` ma sens."""
    stan.ustaw_kontekst(conv_id, persona_tury=persona)
    _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
           szerokosc_cm=60, grubosc_cm=4, ilosc=1,
           selected_variant="dab-lity-ab", wykonczenie="surowe")
    stan.zapisz_dostawe("00-001", kurier="DPD", netto=203.25, brutto=250.0)
    _potwierdz_biezace_pozycje(monkeypatch)
    stan.zapamietaj_wycene({"ok": True, "edit_uuid": "UUID-ALG",
                            "public_url": "https://crm.example/q/abc"})


class TestAllegroKonczyNotatka:
    """U11 (recenzja końcowa) + specyfikacja D8, wiersz 394: „livechat,
    Messenger i OLX dostają link do checkoutu. **Allegro kończy notatką dla
    agenta**". Profil kanału Allegro ma `links=False` (regulamin marketplace'u
    zakazuje kierowania kupującego poza platformę), więc `wysylka._wytnij_linki`
    i tak skasowałby `public_url` z odpowiedzi modelu — szczęśliwa ścieżka na
    Allegro była strukturalnie niedomykalna."""

    def test_na_allegro_model_nie_dostaje_linku(self, monkeypatch):
        _wycena_gotowa_do_zamowienia(monkeypatch, 96041)
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        wynik = _wolaj(n.przygotuj_zamowienie)

        assert wynik["ok"] is True
        assert wynik["tryb"] == "notatka"
        assert "public_url" not in wynik
        assert "crm.example" not in json.dumps(wynik, ensure_ascii=False)

    def test_notatka_niesie_komplet_danych_wraz_z_linkiem(self, monkeypatch):
        _wycena_gotowa_do_zamowienia(monkeypatch, 96042)
        notatki_wyslane = []
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: notatki_wyslane.append((cid, tekst)) or True)
        monkeypatch.setattr(stan, "handoff", lambda powod: {"ok": True})

        _wolaj(n.przygotuj_zamowienie)

        assert len(notatki_wyslane) == 1
        conv, tekst = notatki_wyslane[0]
        assert conv == 96042
        # Notatka jest PRYWATNA, wiec link moze i MUSI sie w niej znalezc.
        assert "https://crm.example/q/abc" in tekst
        assert "UUID-ALG" in tekst
        assert "180.0x60.0x4.0 cm" in tekst   # opis pozycji, nie sam identyfikator
        assert "DPD" in tekst

    def test_na_allegro_rozmowa_idzie_do_czlowieka(self, monkeypatch):
        _wycena_gotowa_do_zamowienia(monkeypatch, 96043)
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: True)
        powody = []
        monkeypatch.setattr(stan, "handoff", lambda powod: powody.append(powod) or {"ok": True})

        _wolaj(n.przygotuj_zamowienie)

        assert len(powody) == 1
        assert "allegro" in powody[0].lower()

    def test_na_olx_link_nadal_idzie_do_klienta(self, monkeypatch):
        # Kontrola negatywna: OLX ma links=True, wiec sciezka linku zostaje bez zmian.
        _wycena_gotowa_do_zamowienia(monkeypatch, 96044, persona="olx")
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: pytest.fail("OLX nie konczy notatka"))
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("OLX nie oddaje rozmowy tutaj"))

        wynik = _wolaj(n.przygotuj_zamowienie)

        assert wynik["public_url"] == "https://crm.example/q/abc"

    def test_bramka_potwierdzenia_dziala_przed_notatka(self, monkeypatch):
        # I2 jest PIERWSZA: bez potwierdzenia nie ma ani linku, ani notatki.
        stan.ustaw_kontekst(96045, persona_tury="allegro")
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: pytest.fail("notatka bez potwierdzenia"))
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("handoff bez potwierdzenia"))

        assert _wolaj(n.przygotuj_zamowienie)["ok"] is False

    def test_brak_zapisanej_wyceny_na_allegro_nie_wysyla_notatki(self, monkeypatch):
        # Nie ma czego przekazywac czlowiekowi, dopoki wycena nie istnieje w CRM —
        # model ma dostac ten sam blad co na kazdym innym kanale.
        stan.ustaw_kontekst(96046, persona_tury="allegro")
        _wolaj(n.zapisz_pozycje, id="1", produkt="blat", dlugosc_cm=180,
               szerokosc_cm=60, grubosc_cm=4, ilosc=1,
               selected_variant="dab-lity-ab", wykonczenie="surowe")
        _potwierdz_biezace_pozycje(monkeypatch)
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: pytest.fail("notatka bez wyceny"))
        monkeypatch.setattr(stan, "handoff",
                            lambda powod: pytest.fail("handoff bez wyceny"))

        assert _wolaj(n.przygotuj_zamowienie)["ok"] is False
