# -*- coding: utf-8 -*-
# Testy czystej logiki dopasowania kontaktow OLX z Chatwoota do klientow CRM
# (modules/quotes/chatwoot_match.py).
#
# Modul jest czysty (tylko `re`), ale import przez sciezke pakietu
# (modules.quotes.chatwoot_match) ciagnie modules/quotes/__init__.py -> routers -> caly Flask.
# Dlatego ladujemy go bezposrednio z pliku, niezaleznie od reszty aplikacji.
import importlib.util
import os

_MOD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "modules", "quotes", "chatwoot_match.py",
)
_spec = importlib.util.spec_from_file_location("quotes_chatwoot_match", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

olx_buyer_prefix = _mod.olx_buyer_prefix
name_matches_olx_prefix = _mod.name_matches_olx_prefix


class TestOlxBuyerPrefix:
    def test_pelny_identyfikator_z_watkiem_daje_prefiks_kupujacego(self):
        # olx-{id_kupujacego}-{id_watku} -> ucinamy id watku
        assert olx_buyer_prefix("olx-5028153-25066393520") == "olx-5028153"

    def test_sam_prefiks_kupujacego_bez_watku(self):
        assert olx_buyer_prefix("olx-5028153") == "olx-5028153"

    def test_wielkie_litery_normalizowane_do_malych(self):
        assert olx_buyer_prefix("OLX-5028153-1") == "olx-5028153"

    def test_biale_znaki_wokol_sa_tolerowane(self):
        assert olx_buyer_prefix("  olx-5028153-1  ") == "olx-5028153"

    def test_identyfikator_allegro_nie_jest_olx(self):
        assert olx_buyer_prefix("allegro-jan_kowalski-123") is None

    def test_email_nie_jest_olx(self):
        assert olx_buyer_prefix("konrad@example.com") is None

    def test_pusty_i_none_daja_none(self):
        assert olx_buyer_prefix("") is None
        assert olx_buyer_prefix(None) is None

    def test_olx_bez_cyfr_daje_none(self):
        assert olx_buyer_prefix("olx-") is None
        assert olx_buyer_prefix("olx-abc") is None


class TestNameMatchesOlxPrefix:
    def test_nazwa_rowna_pelnemu_identyfikatorowi(self):
        assert name_matches_olx_prefix("olx-5028153-25066393520", "olx-5028153") is True

    def test_nazwa_rowna_samemu_prefiksowi(self):
        assert name_matches_olx_prefix("olx-5028153", "olx-5028153") is True

    def test_prefiks_jako_podlancuch_w_dluzszej_nazwie(self):
        assert name_matches_olx_prefix("Konrad olx-5028153-25066393520", "olx-5028153") is True

    def test_dluzszy_numer_kupujacego_nie_jest_dopasowany(self):
        # olx-5028153 NIE moze zlapac olx-50281539 (inny kupujacy)
        assert name_matches_olx_prefix("olx-50281539-123", "olx-5028153") is False

    def test_krotszy_prefiks_nie_lapie_dluzszej_nazwy(self):
        assert name_matches_olx_prefix("olx-5028153", "olx-50281539") is False

    def test_zwykla_nazwa_bez_identyfikatora(self):
        assert name_matches_olx_prefix("Konrad", "olx-5028153") is False

    def test_wielkosc_liter_nie_ma_znaczenia(self):
        assert name_matches_olx_prefix("OLX-5028153-1", "olx-5028153") is True

    def test_puste_argumenty(self):
        assert name_matches_olx_prefix(None, "olx-5028153") is False
        assert name_matches_olx_prefix("olx-5028153", "") is False
        assert name_matches_olx_prefix("", "olx-5028153") is False
