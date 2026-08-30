# -*- coding: utf-8 -*-
"""
Stan rozmowy Dębusia Pro — zapis/odczyt pozycji, kwoty znane guardrailowi,
persona tury oraz pomocnicze funkcje handoffu i linku do checkoutu.

Brief zadania 3 nie zawiera testów dla stan.py (tylko dla guardraila i bramki
potwierdzenia) — te są dopisane zgodnie z rozstrzygnięciem właściciela zadania:
pokryj zachowanie, nie każdą linijkę.
"""
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


class TestKwoty:
    def test_zapamietaj_kwoty_normalizuje_do_dwoch_miejsc(self):
        stan.ustaw_kontekst(93006)
        stan.zapamietaj_kwoty([843.04, "123", 100])
        assert stan.znane_kwoty() == {"843.04", "123.00", "100.00"}

    def test_ustaw_kontekst_czysci_kwoty_z_poprzedniej_tury(self):
        stan.ustaw_kontekst(93007)
        stan.zapamietaj_kwoty([10])
        assert stan.znane_kwoty() == {"10.00"}
        stan.ustaw_kontekst(93007)
        assert stan.znane_kwoty() == set()


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
