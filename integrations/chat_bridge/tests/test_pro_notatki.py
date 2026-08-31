# -*- coding: utf-8 -*-
"""
U7: każde wyjście handoffowe zostawia ślad — notatkę dla konsultanta ORAZ
wiadomość do klienta.

Przed tą poprawką w CAŁYM `bots_pro/` nie było ani jednego `cw_note`, a trzy
z czterech wyjść handoffowych (`limit tur`, `podwójne naruszenie G1`,
`nieudane podsumowanie`) robiły `return` BEZ żadnej wysyłki: klient dostawał
ciszę, a człowiek nie wiedział, że ma przejąć rozmowę. Stary silnik ma
`bots.quotebot.handoff_with_apology` (przeprosiny + notatka z parametrami).

Ten plik NIE wymaga SDK — `bots_pro.notatki` i `bots_pro.stan` są od niego
niezależne (jak `bots_pro.wysylka`).
"""
from bots_pro import notatki, stan


class TestTrescNotatki:
    def test_zawiera_powod(self):
        tresc = notatki.tresc_dla_agenta("limit dlugosci rozmowy (ponad 12 tur)", pozycje=[])
        assert "limit dlugosci rozmowy (ponad 12 tur)" in tresc

    def test_zawiera_pozycje_wyceny(self):
        pozycje = [{"id": "1", "produkt": "blat", "gatunek": "Dąb", "technologia": "lity",
                    "klasa": "A/B", "dlugosc": 180, "szerokosc": 60, "grubosc": 4, "ilosc": 1,
                    "wykonczenie": "surowe"}]
        tresc = notatki.tresc_dla_agenta("powod", pozycje=pozycje)
        assert "180x60x4" in tresc
        assert "Dąb" in tresc

    def test_zawiera_dostawe_i_link_do_wyceny(self):
        tresc = notatki.tresc_dla_agenta(
            "powod", pozycje=[],
            dostawa={"kod_pocztowy": "31-000", "kurier": "DPD", "netto": 200.0, "brutto": 246.0},
            wycena={"edit_uuid": "UUID-1", "public_url": "https://crm/x/abc"})
        assert "DPD" in tresc
        assert "31-000" in tresc
        assert "246" in tresc
        assert "https://crm/x/abc" in tresc

    def test_bez_danych_nie_wywala_sie_i_mowi_ze_ich_brak(self):
        tresc = notatki.tresc_dla_agenta("powod")
        assert "powod" in tresc
        assert tresc.strip()


class TestWyslijNotatke:
    def test_uzywa_tokenu_bota_pro(self, monkeypatch):
        wywolania = []
        monkeypatch.setattr(notatki, "cw_note",
                            lambda conv_id, tekst, token=None: wywolania.append(
                                (conv_id, tekst, token)) or True)
        monkeypatch.setattr(notatki, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")

        assert notatki.wyslij_notatke(4242, "tresc") is True
        assert wywolania == [(4242, "tresc", "TOKEN-PRO")]

    def test_blad_notatki_nie_rzuca(self, monkeypatch):
        def _wybuch(*a, **k):
            raise RuntimeError("Chatwoot padl")

        monkeypatch.setattr(notatki, "cw_note", _wybuch)
        assert notatki.wyslij_notatke(1, "tresc") is False


class TestHandoffZostawiaNotatke:
    """Notatka siedzi w `stan.handoff`, więc obejmuje TAKŻE handoff wywołany
    przez sam model (narzędzie `oddaj_czlowiekowi`), nie tylko bezpieczniki tury."""

    def test_handoff_pisze_notatke_z_powodem_przed_toggle_statusu(self, monkeypatch):
        conv_id = 96401001
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        kolejnosc = []
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: kolejnosc.append(("notatka", cid, tekst)) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff",
                            lambda cid, token=None: kolejnosc.append(("toggle", cid)) or True)

        wynik = stan.handoff("klient prosi o czlowieka")

        assert wynik["ok"] is True
        assert [k[0] for k in kolejnosc] == ["notatka", "toggle"]
        assert "klient prosi o czlowieka" in kolejnosc[0][2]

    def test_nieudana_notatka_nie_blokuje_handoffu(self, monkeypatch):
        conv_id = 96401002
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: False)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        assert stan.handoff("powod")["ok"] is True
