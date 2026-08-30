# -*- coding: utf-8 -*-
"""
Egzekwowanie profilu kanału przy wysyłce.

to_channel_text sanityzuje tylko markdown i emoji. Flagi links i max_len musi
egzekwować wołający — w starym silniku było to rozproszone, tutaj jest w jednym
miejscu. Allegro ma links=False, bo regulamin zabrania kierowania kupującego
poza platformę.
"""
from bots_pro import wysylka


class TestWolnoLinkowac:
    def test_livechat_dopuszcza_linki(self):
        assert wysylka.wolno_linkowac("quote") is True

    def test_olx_dopuszcza_linki(self):
        assert wysylka.wolno_linkowac("quote_olx") is True

    def test_allegro_zabrania_linkow(self):
        assert wysylka.wolno_linkowac("quote_allegro") is False


class TestPrzygotuj:
    def test_livechat_zostawia_tekst_bez_zmian(self):
        assert wysylka.przygotuj("**Cena** 100 zł 🙂", "quote") == ["**Cena** 100 zł 🙂"]

    def test_olx_zdejmuje_markdown_i_emoji(self):
        wynik = wysylka.przygotuj("**Cena** 100 zł 🙂", "quote_olx")
        assert "**" not in wynik[0]
        assert "🙂" not in wynik[0]

    def test_dlugi_tekst_dzielony_na_kanale_z_limitem(self):
        wynik = wysylka.przygotuj("a" * 5000, "quote_olx")
        assert len(wynik) > 1
        assert all(len(czesc) <= 2000 for czesc in wynik)

    def test_link_wycinany_na_allegro(self):
        wynik = wysylka.przygotuj(
            "Wycena: https://crm.woodpower.pl/quotes/c/ABC", "quote_allegro")
        assert "https://" not in wynik[0]

    def test_link_zostaje_na_olx(self):
        wynik = wysylka.przygotuj(
            "Wycena: https://crm.woodpower.pl/quotes/c/ABC", "quote_olx")
        assert "https://crm.woodpower.pl/quotes/c/ABC" in wynik[0]
