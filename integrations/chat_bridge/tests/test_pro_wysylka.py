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


class TestPrzygotujLinkiRozszerzone:
    """Runda poprawek 1, W4: pierwsza wersja filtra na Allegro łapała wyłącznie
    `https?://` — gołą domenę (bez protokołu) przepuszczała bez zmian."""

    def test_gola_domena_bez_protokolu_wycinana_na_allegro(self):
        wynik = wysylka.przygotuj(
            "Szczegóły znajdziesz na crm.woodpower.pl/quotes/c/ABC", "quote_allegro")
        assert "crm.woodpower.pl" not in wynik[0]

    def test_www_bez_protokolu_wycinana_na_allegro(self):
        wynik = wysylka.przygotuj("Zapraszamy na www.woodpower.pl", "quote_allegro")
        assert "woodpower.pl" not in wynik[0]

    def test_gola_domena_zostaje_na_olx(self):
        # Kontrola negatywna: OLX ma links=True, wiec gola domena tam NIE jest wycinana.
        wynik = wysylka.przygotuj(
            "Szczegóły znajdziesz na crm.woodpower.pl/quotes/c/ABC", "quote_olx")
        assert "crm.woodpower.pl" in wynik[0]

    def test_email_nie_traci_domeny_przy_wycinaniu_linkow(self):
        # Wzorzec goej domeny nie ma prawa "odgryzc" domeny z adresu e-mail — inaczej
        # "kontakt@woodpower.pl" zostaloby okaleczone do samego "kontakt@".
        wynik = wysylka.przygotuj("Napisz na kontakt@woodpower.pl", "quote_allegro")
        assert "kontakt@woodpower.pl" in wynik[0]

    def test_wlasna_domena_allegro_zostaje_bo_to_nie_jest_wyjscie_poza_platforme(self):
        wynik = wysylka.przygotuj(
            "Sprawdź naszą ofertę na allegro.pl/oferta/123", "quote_allegro")
        assert "allegro.pl/oferta/123" in wynik[0]

    def test_kikut_link_dwukropek_jest_sprzatany(self):
        wynik = wysylka.przygotuj(
            "Link: https://crm.woodpower.pl/quotes/c/ABC", "quote_allegro")
        assert wynik == [] or "link" not in wynik[0].lower()

    def test_osierocony_dwukropek_bez_slowa_link_jest_sprzatany(self):
        wynik = wysylka.przygotuj(
            "Szczegóły wyceny: https://crm.woodpower.pl/quotes/c/ABC", "quote_allegro")
        assert wynik == [] or not wynik[0].rstrip().endswith(":")
