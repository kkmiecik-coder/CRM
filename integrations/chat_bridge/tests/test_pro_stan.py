# -*- coding: utf-8 -*-
"""
Stan rozmowy Dębusia Pro — zapis/odczyt pozycji, kwoty znane guardrailowi,
persona tury oraz pomocnicze funkcje handoffu i linku do checkoutu.

Brief zadania 3 nie zawiera testów dla stan.py (tylko dla guardraila i bramki
potwierdzenia) — te są dopisane zgodnie z rozstrzygnięciem właściciela zadania:
pokryj zachowanie, nie każdą linijkę.
"""
import pytest

import config as config_mod
import core.chatwoot as chatwoot_mod
from bots_pro import stan

stan.init_pro()


class TestPozycje:
    def test_brak_wiersza_daje_pusta_liste(self):
        stan.ustaw_kontekst(93001)
        assert stan.pozycje() == []

    def test_zapisz_pozycje_wstawia_nowa_pozycje(self):
        stan.ustaw_kontekst(93002)
        wynik = stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                                    grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                                    finishing_option_id=3, wykonczenie="lakierowane")
        assert wynik["ok"] is True
        # K2: selected_variant jest DODATKOWO rozlozony na gatunek/technologia/klasa —
        # bez tego crm_calc.build_products nie rozpozna pozycji (patrz test nizej).
        assert stan.pozycje() == [{"id": "1", "produkt": "blat", "dlugosc": 180,
                                   "szerokosc": 60, "grubosc": 4, "ilosc": 1,
                                   "selected_variant": "dab-lity-ab", "finishing_id": 3,
                                   "wykonczenie": "lakierowane",
                                   "gatunek": "Dąb", "technologia": "Lity", "klasa": "A/B"}]

    def test_zapisz_pozycje_z_nieznanym_wariantem_nie_rozklada_gatunku(self):
        # Enum spoza VARIANT_CODES (literowka modelu, brak w katalogu) — nie zgadujemy,
        # zostawiamy pozycje bez gatunek/technologia/klasa (build_products i tak ja
        # odrzuci jako "brak mapowania", co jest bezpieczniejsze niz zmyslanie).
        stan.ustaw_kontekst(93018)
        stan.zapisz_pozycje("1", produkt="blat", selected_variant="nieistniejacy-wariant")
        (poz,) = stan.pozycje()
        assert "gatunek" not in poz
        assert poz["selected_variant"] == "nieistniejacy-wariant"

    def test_pozycja_przechodzi_przez_prawdziwy_build_products_bez_brakow(self):
        # K2, dowod naprawy: to jest DOKLADNIE to, co robi podsumowanie.wyslij() —
        # bierze stan.pozycje() i podaje je crm_calc.build_products. Przed poprawka
        # kazda pozycja ladowala w braki_mapowania ("nie rozpoznano wariantu drewna"),
        # wiec KAZDA wycena konczyla sie WYCENA_NIEUDANA niezaleznie od wyboru klienta.
        from bots import crm_calc
        stan.ustaw_kontekst(93019)
        stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                            grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                            wykonczenie="surowe")
        products, braki = crm_calc.build_products(stan.pozycje(), {"finishing_options": []})
        assert braki == []
        assert len(products) == 1
        assert products[0]["selected_variant"] == "dab-lity-ab"
        assert products[0]["finishing_type"] == "Surowe"

    def test_pozycja_z_wykonczeniem_i_finishing_id_przechodzi_przez_build_products(self):
        from bots import crm_calc
        stan.ustaw_kontekst(93020)
        stan.zapisz_pozycje("1", produkt="parapet", dlugosc_cm=100, szerokosc_cm=30,
                            grubosc_cm=3, ilosc=2, selected_variant="jes-micro-ab",
                            wykonczenie="olejowane", finishing_option_id=7)
        options = {"finishing_options": [{"id": 7, "price_netto": 10}]}
        products, braki = crm_calc.build_products(stan.pozycje(), options)
        assert braki == []
        assert products[0]["finishing_option_id"] == 7
        assert products[0]["finishing_type"] == "Olejowane"

    def test_zapisz_pozycje_pod_tym_samym_id_aktualizuje_bez_kasowania_pustych(self):
        stan.ustaw_kontekst(93003)
        stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                            grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab")
        # Klient zmienia TYLKO grubosc — reszta pol przychodzi pusta/zerowa i MUSI przezyc.
        stan.zapisz_pozycje("1", grubosc_cm=6)
        (poz,) = stan.pozycje()
        assert poz["grubosc"] == 6
        assert poz["produkt"] == "blat"
        assert poz["dlugosc"] == 180
        assert poz["selected_variant"] == "dab-lity-ab"

    def test_zapisz_pozycje_z_roznymi_id_dodaje_druga_pozycje(self):
        stan.ustaw_kontekst(93004)
        stan.zapisz_pozycje("1", produkt="blat")
        stan.zapisz_pozycje("2", produkt="parapet")
        assert {p["id"] for p in stan.pozycje()} == {"1", "2"}

    def test_zapisz_pozycje_usun_kasuje_pozycje(self):
        stan.ustaw_kontekst(93005)
        stan.zapisz_pozycje("1", produkt="blat")
        stan.zapisz_pozycje("2", produkt="parapet")
        wynik = stan.zapisz_pozycje("1", usun=True)
        assert wynik == {"ok": True, "usunieto": "1"}
        assert [p["id"] for p in stan.pozycje()] == ["2"]


class TestKrawedzie:
    """Task 2: zapisz_pozycje dostaje edges — ksztalt WEJSCIOWY (litera/typ/r/kat),
    zgodny z tym, co konsumuje crm_calc.normalize_edges. Zapisywana jest juz
    postac ZNORMALIZOWANA (litera/typ/r_value/angle_value), bo w tej postaci
    czyta ja crm_calc.build_products i podsumowanie._opis_edges."""

    def test_niepusta_lista_zapisuje_sie_w_postaci_znormalizowanej(self):
        stan.ustaw_kontekst(93024)
        stan.zapisz_pozycje("1", produkt="blat",
                            edges=[{"litera": "A", "typ": "round", "r": 3}])
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "A", "typ": "round", "r_value": 3, "angle_value": None}]

    def test_domyslny_promien_i_kat_gdy_nie_podano(self):
        stan.ustaw_kontekst(93025)
        stan.zapisz_pozycje("1", produkt="blat", edges=[
            {"litera": "A", "typ": "round"}, {"litera": "B", "typ": "chamfer"}])
        (poz,) = stan.pozycje()
        assert {"litera": "A", "typ": "round", "r_value": 5, "angle_value": None} in poz["edges"]
        assert {"litera": "B", "typ": "chamfer", "r_value": None, "angle_value": 45} in poz["edges"]

    def test_pominiecie_edges_nie_kasuje_wczesniej_zapisanych(self):
        # edges=None (domyslne, model nic nie powiedzial o krawedziach w tej
        # turze) NIE ma kasowac — klient nie musi powtarzac krawedzi co ture.
        stan.ustaw_kontekst(93026)
        stan.zapisz_pozycje("1", produkt="blat",
                            edges=[{"litera": "A", "typ": "round", "r": 5}])
        stan.zapisz_pozycje("1", grubosc_cm=6)
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "A", "typ": "round", "r_value": 5, "angle_value": None}]
        assert poz["grubosc"] == 6

    def test_nowa_niepusta_lista_zastepuje_cala_poprzednia_obrobke(self):
        # Replace, nie merge per-litera — jak w starym silniku (bots/quotebot.py).
        # Model musi podac KOMPLET krawedzi, ktore maja obowiazywac.
        stan.ustaw_kontekst(93027)
        stan.zapisz_pozycje("1", produkt="blat", edges=[
            {"litera": "A", "typ": "round", "r": 5}, {"litera": "B", "typ": "round", "r": 5}])
        stan.zapisz_pozycje("1", edges=[{"litera": "C", "typ": "chamfer", "kat": 30}])
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "C", "typ": "chamfer", "r_value": None, "angle_value": 30}]

    def test_jawne_ostra_czysci_cala_wczesniej_zapisana_obrobke(self):
        # Rozstrzygniecie zadania: "sharp" nie jest kolejna wartoscia do zapisania
        # (crm_calc.normalize_edges sam go pomija jako "brak obrobki") — to sygnal
        # WYCZYSZCZENIA. Bez osobnej sciezki intencja klienta "chce ostre" ginelaby
        # w normalize_edges(), a stara obrobka zostawalaby w pozycji na zawsze.
        stan.ustaw_kontekst(93028)
        stan.zapisz_pozycje("1", produkt="blat",
                            edges=[{"litera": "A", "typ": "round", "r": 5}])
        wynik = stan.zapisz_pozycje("1", edges=[{"litera": "A", "typ": "sharp"}])
        assert wynik["ok"] is True
        (poz,) = stan.pozycje()
        assert poz["edges"] == []

    def test_pusta_lista_bez_sharp_nie_kasuje(self):
        # normalize_edges([]) == [] i raw_ma_sharp([]) == False -- odrozniamy to
        # od jawnego sharp powyzej. Pusta lista BEZ zadnego sharp w srodku (np.
        # gdy warstwa posrednia domyslnie wysyla []) ma sie zachowac jak edges=None.
        stan.ustaw_kontekst(93029)
        stan.zapisz_pozycje("1", produkt="blat",
                            edges=[{"litera": "A", "typ": "round", "r": 5}])
        stan.zapisz_pozycje("1", edges=[])
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "A", "typ": "round", "r_value": 5, "angle_value": None}]

    def test_pozycja_z_krawedziami_przechodzi_przez_prawdziwy_build_products(self):
        # Dowod naprawy: zapisz_pozycje(edges=...) -> stan.pozycje() -> prawdziwy
        # crm_calc.build_products, bez trafienia w braki_mapowania.
        from bots import crm_calc
        stan.ustaw_kontekst(93030)
        stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                            grubosc_cm=4, ilosc=1, selected_variant="dab-lity-ab",
                            wykonczenie="surowe",
                            edges=[{"litera": "A", "typ": "round", "r": 3},
                                   {"litera": "C", "typ": "chamfer", "kat": 30}])
        products, braki = crm_calc.build_products(stan.pozycje(), {"finishing_options": []})
        assert braki == []
        assert products[0]["edges_mode"] == "advanced"
        assert products[0]["edges"] == [
            {"letter": "A", "type": "round", "r_value": 3, "angle_value": None},
            {"letter": "C", "type": "chamfer", "r_value": None, "angle_value": 30},
        ]

    def test_sharp_obok_realnej_obrobki_nie_czysci_calosci(self):
        # Runda poprawek 1, drobne: lista MIESZANA — normalize_edges() zwraca
        # NIEPUSTA liste (samo B, sharp A jest przez nia pomijane), wiec idzie
        # sciezka REPLACE ("znormalizowane" niepuste), NIE sciezka CLEAR — A
        # (sharp) po prostu nie trafia do zapisanego wyniku, B zostaje.
        # To zachowanie wynika WYLACZNIE z kolejnosci if/elif w
        # _zastosuj_krawedzie (odwrocona kolejnosc zmienilaby semantyke na
        # "kazdy sharp w liscie czysci wszystko"), wiec zasluguje na wlasny test.
        stan.ustaw_kontekst(93034)
        stan.zapisz_pozycje("1", produkt="blat", edges=[
            {"litera": "A", "typ": "sharp"}, {"litera": "B", "typ": "round", "r": 5}])
        (poz,) = stan.pozycje()
        assert poz["edges"] == [
            {"litera": "B", "typ": "round", "r_value": 5, "angle_value": None}]


class TestSurowyCzysciFinishingId:
    """W1 (runda poprawek 1): wykonczenie="surowe" musi skasowac finishing_id
    zapisany przy poprzednim (innym) wykonczeniu — inaczej klient potwierdza
    KOLOR/POLYSK przy cenie surowego blatu, ktora go juz nie liczy."""

    def test_przejscie_na_surowe_kasuje_wczesniej_zapisany_finishing_id(self):
        stan.ustaw_kontekst(93035)
        stan.zapisz_pozycje("1", produkt="blat", wykonczenie="olejowane",
                            finishing_option_id=3)
        (poz,) = stan.pozycje()
        assert poz["finishing_id"] == 3

        stan.zapisz_pozycje("1", wykonczenie="surowe")
        (poz,) = stan.pozycje()
        assert "finishing_id" not in poz
        assert poz["wykonczenie"] == "surowe"

    def test_surowe_bez_wczesniejszego_finishing_id_nie_rzuca(self):
        stan.ustaw_kontekst(93036)
        wynik = stan.zapisz_pozycje("1", produkt="blat", wykonczenie="surowe")
        assert wynik["ok"] is True
        assert "finishing_id" not in wynik["pozycja"]

    def test_inne_wykonczenie_niz_surowe_nie_rusza_finishing_id(self):
        # Kontrola negatywna: zmiana grubosci (bez dotykania wykonczenia) MA
        # zachowac finishing_id -- czyszczenie jest zwiazane WYLACZNIE z
        # jawnym "surowe", nie z kazda aktualizacja pozycji.
        stan.ustaw_kontekst(93037)
        stan.zapisz_pozycje("1", produkt="blat", wykonczenie="olejowane",
                            finishing_option_id=3)
        stan.zapisz_pozycje("1", grubosc_cm=6)
        (poz,) = stan.pozycje()
        assert poz["finishing_id"] == 3

    def test_rozne_pisownie_surowego_tez_czysza_finishing_id(self):
        # N1 (runda poprawek 2): straznik uzywa teraz crm_calc._finish_type
        # (podciag "surow", bez wzgledu na wielkosc liter/diakrytyki), nie
        # scislego porownania `== "surowe"` -- ta sama regula, ktorej uzywa
        # wycena (crm_calc.build_products), wiec "czyszcze finishing_id" i
        # "wycena ignoruje finishing_id" sa zawsze zgodne ze soba. Dzis enum
        # narzedzia (Wykonczenie) wysyla wylacznie dokladne "surowe"
        # (nieosiagalne przez narzedzie), ale obrona ma dzialac niezaleznie.
        for i, wykonczenie in enumerate(("Surowe", "SUROWE", "surowy dąb"), start=1):
            conv_id = 93039 + i
            stan.ustaw_kontekst(conv_id)
            stan.zapisz_pozycje("1", produkt="blat", wykonczenie="olejowane",
                                finishing_option_id=3)
            stan.zapisz_pozycje("1", wykonczenie=wykonczenie)
            (poz,) = stan.pozycje()
            assert "finishing_id" not in poz, wykonczenie


class TestOtwory:
    """Task 2: zapisz_pozycje dostaje otwory — lista opisow (jak stary silnik,
    bots/quotebot.py: "OTWORY/WYCIECIA: NIE wyceniasz"), NIE wycenianych
    automatycznie przez crm_calc. Sluza jako notatka dla konsultanta i wchodza
    do podpisu potwierdzenia (potwierdzenia._POLA_ISTOTNE)."""

    def test_lista_opisow_zapisuje_sie_bez_zmian(self):
        stan.ustaw_kontekst(93031)
        stan.zapisz_pozycje("1", produkt="blat",
                            otwory=["otwór na zlew 50x40 cm", "otwór na baterię"])
        (poz,) = stan.pozycje()
        assert poz["otwory"] == ["otwór na zlew 50x40 cm", "otwór na baterię"]

    def test_pominiecie_otwory_nie_kasuje_wczesniej_zapisanych(self):
        stan.ustaw_kontekst(93032)
        stan.zapisz_pozycje("1", produkt="blat", otwory=["otwór na zlew"])
        stan.zapisz_pozycje("1", grubosc_cm=6)
        (poz,) = stan.pozycje()
        assert poz["otwory"] == ["otwór na zlew"]

    def test_jawna_pusta_lista_kasuje_otwory(self):
        # W odroznieniu od edges, otwory nie maja odrebnego sygnalu "sharp" —
        # jawna pusta lista to jedyny i wystarczajacy sposob wyczyszczenia.
        stan.ustaw_kontekst(93033)
        stan.zapisz_pozycje("1", produkt="blat", otwory=["otwór na zlew"])
        stan.zapisz_pozycje("1", otwory=[])
        (poz,) = stan.pozycje()
        assert poz["otwory"] == []


class TestKwoty:
    """Rejestr kwot (Task 8, B1): PRZENIESIONY z contextvara per-tura do `pro_stan`
    (trwaly per ROZMOWA). Bylo: `ustaw_kontekst` zerowal `_kwoty` na starcie KAZDEJ
    tury (`_kwoty.set(set())`), wiec cena zarejestrowana w turze N (np. przez
    `policz_wycene`/`podsumowanie.wyslij`) znikala na starcie tury N+1 — a
    `zapisz_wycene` w kolejnej turze NIE zasila rejestru wcale (nie musi, bo
    tylko cytuje juz ustalona cene). Skutek w praktyce: bot w turze N+1 cytujacy
    PRAWDZIWA cene z tury N ("wycena na 1936,71 zl zapisana") byl przez guardrail
    G1 oskarzany o halucynacje — dokladnie w momencie udanego zamkniecia sprzedazy."""

    def test_zapamietaj_kwoty_normalizuje_do_dwoch_miejsc(self):
        stan.ustaw_kontekst(93006)
        stan.zapamietaj_kwoty([843.04, "123", 100])
        assert stan.znane_kwoty() == {"843.04", "123.00", "100.00"}

    def test_kwoty_przetrwaja_granice_tury_tej_samej_rozmowy(self):
        # B1: DOKLADNA odwrotnosc starego zachowania (patrz docstring klasy) —
        # to jest fix, nie regresja. `ustaw_kontekst` woluje sie na poczatku
        # KAZDEJ tury (patrz tura.uruchom), a rejestr tej SAMEJ rozmowy ma
        # przetrwac to wywolanie.
        stan.ustaw_kontekst(93043)
        stan.zapamietaj_kwoty([10])
        assert stan.znane_kwoty() == {"10.00"}
        stan.ustaw_kontekst(93043)   # nowa tura, TA SAMA rozmowa
        assert stan.znane_kwoty() == {"10.00"}

    def test_kwoty_nie_przeciekaja_miedzy_roznymi_rozmowami(self):
        # Odwrotna strona tego samego inwariantu (I1) — przechowywanie w `pro_stan`
        # (kluczowanym po conv_id) NIE MOZE pozwolic kwocie z jednej rozmowy
        # "pomoc" guardrailowi w INNEJ.
        stan.ustaw_kontekst(93044)
        stan.zapamietaj_kwoty([555])
        assert stan.znane_kwoty() == {"555.00"}
        stan.ustaw_kontekst(93045)   # INNA rozmowa
        assert stan.znane_kwoty() == set()

    def test_zapamietaj_kwoty_dopisuje_a_nie_nadpisuje(self):
        stan.ustaw_kontekst(93046)
        stan.zapamietaj_kwoty([10])
        stan.zapamietaj_kwoty([20])
        assert stan.znane_kwoty() == {"10.00", "20.00"}


class TestPodsumowanieWyslane:
    """Bramka W3 (runda poprawek 1): `podsumowanie.wyslij()` oznacza w stanie tury,
    że sam już wysłał deterministyczną treść — `tura.py` to sprawdza, żeby nie
    wysłać drugiego, sparafrazowanego przez model podsumowania w tej samej turze."""

    def test_domyslnie_falsz(self):
        stan.ustaw_kontekst(93040)
        assert stan.podsumowanie_wyslane() is False

    def test_oznaczenie_ustawia_prawde(self):
        stan.ustaw_kontekst(93041)
        stan.oznacz_podsumowanie_wyslane()
        assert stan.podsumowanie_wyslane() is True

    def test_ustaw_kontekst_czysci_flage_z_poprzedniej_tury(self):
        stan.ustaw_kontekst(93042)
        stan.oznacz_podsumowanie_wyslane()
        assert stan.podsumowanie_wyslane() is True
        stan.ustaw_kontekst(93042)
        assert stan.podsumowanie_wyslane() is False


class TestPersonaIConvId:
    def test_domyslna_persona_to_pro(self):
        stan.ustaw_kontekst(93008)
        assert stan.persona() == "pro"

    def test_persona_jawnie_ustawiona(self):
        stan.ustaw_kontekst(93009, persona_tury="quote_olx")
        assert stan.persona() == "quote_olx"

    def test_conv_id_zwraca_ustawiona_wartosc(self):
        stan.ustaw_kontekst(93010)
        assert stan.conv_id() == 93010


class TestZapiszStan:
    """zapisz_stan — jedyne miejsce piszące do pro_stan (konsolidacja z potwierdzenia.py
    i podsumowanie.py, które wcześniej dublowały własny UPSERT do tej samej tabeli)."""

    def test_wstawia_nowy_wiersz(self):
        from core.db import db
        stan.ustaw_kontekst(93021)
        stan.zapisz_stan(oczekiwany_podpis="abc123")
        c = db()
        wiersz = c.execute("SELECT oczekiwany_podpis FROM pro_stan WHERE conv_id=?",
                           (93021,)).fetchone()
        c.close()
        assert wiersz["oczekiwany_podpis"] == "abc123"

    def test_aktualizuje_bez_kasowania_innych_kolumn(self):
        from core.db import db
        stan.ustaw_kontekst(93022)
        stan.zapisz_stan(quote_edit_uuid="uuid-1", priced=1)
        stan.zapisz_stan(oczekiwany_podpis="xyz789")   # inna tura, inna kolumna
        c = db()
        wiersz = c.execute(
            "SELECT quote_edit_uuid, priced, oczekiwany_podpis FROM pro_stan WHERE conv_id=?",
            (93022,)).fetchone()
        c.close()
        assert wiersz["quote_edit_uuid"] == "uuid-1"
        assert wiersz["priced"] == 1
        assert wiersz["oczekiwany_podpis"] == "xyz789"

    def test_wolane_bez_kolumn_nie_rzuca(self):
        stan.ustaw_kontekst(93023)
        stan.zapisz_stan()   # no-op, nie powinno rzucic ani dotknac bazy


class TestLinkDoCheckoutu:
    def test_zwraca_podany_uuid_bez_zapisanej_wyceny(self):
        stan.ustaw_kontekst(93011)
        wynik = stan.link_do_checkoutu("uuid-podany")
        assert wynik == {"ok": True, "edit_uuid": "uuid-podany"}

    def test_bez_uuid_i_bez_zapisanej_wyceny_jest_bledem(self):
        stan.ustaw_kontekst(93012)
        wynik = stan.link_do_checkoutu(None)
        assert wynik["ok"] is False

    def test_bez_argumentu_pobiera_zapisany_uuid_z_bazy(self):
        from core.db import db
        stan.ustaw_kontekst(93013)
        c = db()
        c.execute("INSERT INTO pro_stan(conv_id, quote_edit_uuid) VALUES(?,?)",
                  (93013, "uuid-z-bazy"))
        c.commit(); c.close()
        assert stan.link_do_checkoutu(None) == {"ok": True, "edit_uuid": "uuid-z-bazy"}


class TestHandoff:
    def test_uzywa_tokenu_bota_pro_i_zwraca_powod(self, monkeypatch):
        stan.ustaw_kontekst(93014)
        monkeypatch.setattr(config_mod, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")
        wywolania = []
        monkeypatch.setattr(chatwoot_mod, "cw_bot_handoff",
                            lambda conv_id, token=None: wywolania.append((conv_id, token)) or True)
        wynik = stan.handoff("reklamacja")
        assert wynik == {"ok": True, "powod": "reklamacja"}
        assert wywolania == [(93014, "TOKEN-PRO")]

    def test_niepowodzenie_cw_zwraca_ok_false(self, monkeypatch):
        stan.ustaw_kontekst(93015)
        monkeypatch.setattr(chatwoot_mod, "cw_bot_handoff", lambda conv_id, token=None: False)
        assert stan.handoff("cokolwiek")["ok"] is False


class TestOstatniaWiadomoscKlienta:
    def test_zwraca_tresc_najnowszej_wiadomosci_uzytkownika(self, monkeypatch):
        stan.ustaw_kontekst(93016)
        monkeypatch.setattr(chatwoot_mod, "cw_messages", lambda conv_id, limit: [
            {"role": "user", "text": "dzien dobry"},
            {"role": "assistant", "text": "w czym moge pomoc?"},
            {"role": "user", "text": "tak, zgadza sie"},
        ])
        assert stan.ostatnia_wiadomosc_klienta() == "tak, zgadza sie"

    def test_brak_wiadomosci_uzytkownika_daje_pusty_tekst(self, monkeypatch):
        stan.ustaw_kontekst(93017)
        monkeypatch.setattr(chatwoot_mod, "cw_messages", lambda conv_id, limit: [
            {"role": "assistant", "text": "witaj"},
        ])
        assert stan.ostatnia_wiadomosc_klienta() == ""


class _FakeResp:
    def __init__(self, payload, ok=True, status_code=200):
        self._p = payload
        self.ok = ok
        self.status_code = status_code
    def json(self):
        return {"payload": self._p}


class TestWolnoProwadzicRozmowe:
    """Bramka ciszy po handoffie (rozstrzygniecie zadania 7, brief o niej nie mowi;
    przepisana w rundzie poprawek 1 po code review — K1/W3).

    K1: tura Debusia Pro jest ZAWSZE wyzwalana swieza wiadomoscia klienta, wiec
    "kto mowil OSTATNI" jest w praktyce prawie zawsze klientem — pierwsza wersja
    tej bramki (sprawdzajaca ostatniego mowce) byla wiec martwa. Sprawdzamy
    teraz, czy w PUBLICZNEJ historii W OGOLE pojawila sie wiadomosc czlowieka-
    -agenta, niezaleznie od pozycji. Sekwencje ponizej odpowiadaja przykladom
    z code review: A=[klient,agent], B=[klient,agent,klient] (realny #1316),
    C=[klient,agent,activity], D=[klient]."""

    def test_status_inny_niz_pending_blokuje(self, monkeypatch):
        stan.ustaw_kontekst(94001)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "open")
        wolane_cw = []
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: wolane_cw.append(1) or _FakeResp([]))
        assert stan.wolno_prowadzic_rozmowe(94001) is False
        # Status juz przesadzil sprawe - nie ma potrzeby dopytywac o historie wiadomosci.
        assert wolane_cw == []

    def test_sekwencja_a_klient_agent_blokuje(self, monkeypatch):
        # A) [klient, agent] - agent odpisal jako ostatni.
        stan.ustaw_kontekst(94002)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "dzien dobry", "private": False, "sender": {"type": "contact"}},
            {"content": "nie robimy naturalnych krawedzi", "private": False,
             "sender": {"type": "user"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94002) is False

    def test_sekwencja_b_klient_agent_klient_realny_1316_blokuje(self, monkeypatch):
        # B) [klient, agent, klient] - DOKLADNIE audyt #1316: agent odpisal, klient
        # napisal PO NIM. Ostatnia wiadomosc jest znow od klienta, ale agent juz
        # przejal rozmowe - bot MA milczec, nie tylko gdy agent mowil ostatni.
        stan.ustaw_kontekst(94008)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "dzien dobry", "private": False, "sender": {"type": "contact"}},
            {"content": "nie robimy naturalnych krawedzi", "private": False,
             "sender": {"type": "user"}},
            {"content": "a jednak chcialbym taki blat", "private": False,
             "sender": {"type": "contact"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94008) is False

    def test_sekwencja_c_wiadomosc_activity_bez_sender_nie_maskuje_agenta(self, monkeypatch):
        # C) [klient, agent, activity] - wiadomosc systemowa (np. "przypisano do X")
        # bez pola sender nie moze przesloniec faktu, ze agent juz sie odezwal.
        stan.ustaw_kontekst(94009)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "dzien dobry", "private": False, "sender": {"type": "contact"}},
            {"content": "nie robimy naturalnych krawedzi", "private": False,
             "sender": {"type": "user"}},
            {"content": "Przypisano do zespolu", "private": False},   # activity, brak sender
        ]))
        assert stan.wolno_prowadzic_rozmowe(94009) is False

    def test_sekwencja_d_tylko_klient_swieza_rozmowa_pozwala(self, monkeypatch):
        # D) [klient] - swieza rozmowa, zaden agent sie jeszcze nie odezwal.
        stan.ustaw_kontekst(94003)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "cena?", "private": False, "sender": {"type": "contact"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94003) is True

    def test_sama_odpowiedz_bota_nie_blokuje(self, monkeypatch):
        # Bot sam odpowiadal wczesniej (normalny przebieg rozmowy bot<->klient) - to
        # NIE jest sygnal przejecia rozmowy przez czlowieka (sender.type != "user").
        stan.ustaw_kontekst(94004)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "cena?", "private": False, "sender": {"type": "contact"}},
            {"content": "Juz licze...", "private": False, "sender": {"type": "agent_bot"}},
            {"content": "dzieki, poprosze", "private": False, "sender": {"type": "contact"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94004) is True

    def test_prywatna_notatka_agenta_nie_blokuje(self, monkeypatch):
        # Wewnetrzna notatka miedzy agentami nie jest publiczna odpowiedzia klientowi -
        # bramka pomija wiadomosci prywatne przy szukaniu wypowiedzi czlowieka.
        stan.ustaw_kontekst(94005)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "cena?", "private": False, "sender": {"type": "contact"}},
            {"content": "notatka wewnetrzna", "private": True, "sender": {"type": "user"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94005) is True

    def test_pusta_historia_pozwala(self, monkeypatch):
        # Zupelnie nowa rozmowa (webhook przyszedl, ale endpoint GET messages jeszcze
        # nic nie zwraca) - nie ma podstaw do blokady.
        stan.ustaw_kontekst(94006)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([]))
        assert stan.wolno_prowadzic_rozmowe(94006) is True

    def test_blad_odczytu_historii_rzuca_blad_odczytu_stanu(self, monkeypatch):
        # W3: blad sieci/Chatwoot ma RZUCAC (retryable), NIE cicho zwracac False -
        # inaczej quote_worker oznaczylby wiersz jako 'sent' i zgubil wiadomosc klienta.
        stan.ustaw_kontekst(94007)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        def _boom(*a, **k):
            raise ConnectionError("timeout")
        monkeypatch.setattr(chatwoot_mod, "cw", _boom)
        with pytest.raises(stan.BladOdczytuStanu):
            stan.wolno_prowadzic_rozmowe(94007)

    def test_blad_odczytu_statusu_rzuca_blad_odczytu_stanu(self, monkeypatch):
        # cw_conv_status zwraca None przy bledzie (patrz core/chatwoot.py) - to TEZ
        # ma rzucac, nie byc cicho potraktowane jako "status != pending -> False".
        stan.ustaw_kontekst(94010)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: None)
        wolane_cw = []
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: wolane_cw.append(1) or _FakeResp([]))
        with pytest.raises(stan.BladOdczytuStanu):
            stan.wolno_prowadzic_rozmowe(94010)
        assert wolane_cw == []

    def test_blad_odczytu_stanu_ma_atrybut_retryable_true(self):
        assert stan.BladOdczytuStanu.retryable is True

    def test_odpowiedz_http_blad_rzuca_blad_odczytu_stanu(self, monkeypatch):
        # Drobne (code review runda 2): cw() nie robi raise_for_status - odpowiedz
        # bledu, ktora sparsuje sie jako JSON bez "payload", dawalaby cicho []
        # (pusta historia -> bramka pozwala) bez tego jawnego sprawdzenia r.ok.
        stan.ustaw_kontekst(94011)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw",
                            lambda *a, **k: _FakeResp({"blad": "wewnetrzny"}, ok=False, status_code=500))
        with pytest.raises(stan.BladOdczytuStanu):
            stan.wolno_prowadzic_rozmowe(94011)


class TestWolnoProwadzicRozmoweStickyBit:
    """N2 (code review, runda 2): semantyka "czy czlowiek KIEDYKOLWIEK sie
    odezwal" zaklada, ze pobrana strona /messages to CALA historia - ale
    endpoint jest stronicowany i bez parametru strony zwraca tylko najswiezsza
    strone. Gdy po odpowiedzi agenta narosnie dosc kolejnych wiadomosci klienta,
    odpowiedz agenta wypadnie z pobranej strony i bramka (bez sticky bita)
    wrocilaby na True. Sticky bit w pro_stan jest NIEZALEZNY od rozmiaru strony:
    raz ustawiony, blokuje trwale bez ponownego skanowania historii."""

    def test_sticky_bit_ustawiany_gdy_znaleziono_wiadomosc_agenta(self):
        stan.ustaw_kontekst(94101)
        assert stan._czlowiek_juz_sie_odezwal(94101) is False
        stan._oznacz_czlowiek_odezwal_sie(94101)
        assert stan._czlowiek_juz_sie_odezwal(94101) is True

    def test_wolno_prowadzic_rozmowe_ustawia_sticky_bit_po_znalezieniu_agenta(self, monkeypatch):
        stan.ustaw_kontekst(94102)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "dzien dobry", "private": False, "sender": {"type": "contact"}},
            {"content": "juz nie pracujemy nad tym", "private": False, "sender": {"type": "user"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94102) is False
        assert stan._czlowiek_juz_sie_odezwal(94102) is True

    def test_druga_tura_nie_siega_juz_po_historie_dzieki_sticky_bitowi(self, monkeypatch):
        # Kluczowy dowod na N2: gdy sticky bit jest juz ustawiony, bramka NIE
        # woła /messages wcale - odpowiedz jest wiec odporna na to, co ta
        # (potencjalnie juz nieaktualna/przepełniona) strona by zwrocila.
        stan.ustaw_kontekst(94103)
        stan._oznacz_czlowiek_odezwal_sie(94103)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        wolania_historii = []
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: wolania_historii.append(1) or _FakeResp([]))

        assert stan.wolno_prowadzic_rozmowe(94103) is False
        assert wolania_historii == []

    def test_agent_wypadl_ze_strony_ale_sticky_bit_nadal_blokuje(self, monkeypatch):
        # Symulacja dokladnie tego scenariusza z code review: agent odpisal DAWNO,
        # od tamtej pory narosla nowa strona samych wiadomosci klienta (agent nie
        # jest juz widoczny w pobranej stronie /messages) - bez sticky bita bramka
        # zwrocilaby True (blednie). Ze sticky bitem ustawionym w PIERWSZEJ turze
        # (gdy agent byl jeszcze widoczny), druga tura poprawnie blokuje.
        stan.ustaw_kontekst(94104)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")

        # Tura 1: agent widoczny w historii -> bramka wykrywa i ustawia sticky bit.
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "dzien dobry", "private": False, "sender": {"type": "contact"}},
            {"content": "nie robimy naturalnych krawedzi", "private": False, "sender": {"type": "user"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94104) is False

        # Tura 2: "nowa strona" /messages, gdzie agent JUZ NIE MIESCI SIE (same
        # pozniejsze wiadomosci klienta) - bez sticky bita to dawaloby True.
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: _FakeResp([
            {"content": "hej, jest tam ktos?", "private": False, "sender": {"type": "contact"}},
            {"content": "no to ja czekam", "private": False, "sender": {"type": "contact"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94104) is False

    def test_brak_sticky_bita_robi_normalny_skan_historii(self, monkeypatch):
        # Kontrola negatywna: swieza rozmowa (bez sticky bita) nadal dziala jak
        # przed N2 - bramka i tak siega po historie i poprawnie pozwala.
        stan.ustaw_kontekst(94105)
        monkeypatch.setattr(chatwoot_mod, "cw_conv_status", lambda conv_id: "pending")
        wolania_historii = []
        monkeypatch.setattr(chatwoot_mod, "cw", lambda *a, **k: wolania_historii.append(1) or _FakeResp([
            {"content": "cena?", "private": False, "sender": {"type": "contact"}},
        ]))
        assert stan.wolno_prowadzic_rozmowe(94105) is True
        assert wolania_historii == [1]
