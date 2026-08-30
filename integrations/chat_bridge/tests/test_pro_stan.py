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
                                    finishing_option_id=3)
        assert wynik["ok"] is True
        assert stan.pozycje() == [{"id": "1", "produkt": "blat", "dlugosc": 180,
                                   "szerokosc": 60, "grubosc": 4, "ilosc": 1,
                                   "selected_variant": "dab-lity-ab", "finishing_id": 3}]

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
