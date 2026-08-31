# -*- coding: utf-8 -*-
"""
Obrazy wysyłane KLIENTOWI (P2, runda napraw 4).

Stary silnik potrafi pokazać próbkę gatunków, wzornik kolorów, schemat wymiarów
i schemat krawędzi (`bots/livechat.py` -> `images.resolve`, `bots/quotebot.py`
-> `_obrazy_kontekstowe`). Dębuś Pro nie miał tej ścieżki wcale — regres wobec
silnika, który tę funkcję ma na produkcji. Transport był gotowy
(`core.chatwoot.cw_agent_reply` przyjmuje `image_path`/`image_name`/`image_mime`),
brakowało wyłącznie wyjścia po stronie Pro.

Testy pilnują trzech rzeczy, każdej z innego powodu:
  - BIAŁA LISTA jest zamknięta i wskazuje pliki, które NAPRAWDĘ istnieją —
    nieznany identyfikator nie wysyła NICZEGO (nie „wysyła coś innego");
  - PROFIL KANAŁU jest sprawdzany w Pythonie (flagi `images` i `image_formats`
    z `bots/channel_caps.py`), a nie proszony od modelu — dokładnie tak, jak
    zapowiadał to docstring `bots_pro/wysylka.py`;
  - PODPIS składa KOD, nie model. Gdyby podpis pisał model, omijałby guardrail
    cenowy G1: `tura.py` ogląda `final_output`, a treść wysłana z wnętrza
    narzędzia nigdy przez niego nie przechodzi.

Moduł NIE importuje `agents` (buduje zwykłe słowniki i woła Chatwoota), więc ten
plik chodzi także w obrazie bez SDK — testy samego narzędzia SDK są w
test_pro_narzedzia.py.
"""
import os
import tempfile

import pytest

from bots import images
from bots_pro import guardraile, obrazy_do_klienta, stan

stan.init_pro()

# `bots.images._dir()` czyta BOT_IMAGES_DIR ze ZMIENNEJ SRODOWISKOWEJ przy KAZDYM
# wywolaniu, a dwa inne pliki testow (test_images.py, test_livechat_images.py)
# ustawiaja ja GLOBALNIE na wlasny katalog tymczasowy i po sobie nie sprzataja.
# W pelnym suicie te testy przechodzilyby wiec zaleznie od kolejnosci — dlatego
# katalog liczymy z polozenia repozytorium i przypinamy na kazdy test.
_KATALOG_ASSETOW = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "bot_images")


@pytest.fixture(autouse=True)
def _prawdziwy_katalog_obrazow(monkeypatch):
    monkeypatch.setenv("BOT_IMAGES_DIR", _KATALOG_ASSETOW)


def _rejestrator(monkeypatch, wynik=True):
    """Atrapa `cw_agent_reply` zapisująca KAŻDE wywołanie.

    Rejestrator, nie atrapa rzucająca wyjątkiem: wyciek ma się objawić WPISEM,
    a nie wyjątkiem z przypadkowego miejsca (ta sama nauka co z rundy 3, P2 —
    `core/chatwoot.py` łapie wyjątki wewnątrz i po cichu zwraca pustkę)."""
    wyslane = []

    def atrapa(conv_id, tekst, image_path=None, image_name=None,
               image_mime="image/jpeg", token=None):
        wyslane.append({"conv_id": conv_id, "tekst": tekst, "image_path": image_path,
                        "image_name": image_name, "image_mime": image_mime,
                        "token": token})
        return wynik

    monkeypatch.setattr(obrazy_do_klienta, "cw_agent_reply", atrapa)
    return wyslane


def _caps(**nadpisania):
    """Profil kanału do wstrzyknięcia. Żaden PRAWDZIWY kanał nie ma dziś
    images=False ani węższej listy formatów niż jpg/jpeg/png, więc bramki nie da
    się sprawdzić na produkcyjnym profilu — a sprawdzić trzeba, bo profil może
    się zmienić bez zmiany tego modułu."""
    baza = {"markdown": True, "images": True, "image_formats": None,
            "emoji": True, "max_len": None, "links": True}
    baza.update(nadpisania)
    return baza


class TestBialaLista:
    def test_lista_pokrywa_cztery_obrazy_starego_silnika(self):
        # Probka wariantow, schemat wymiarow, schemat krawedzi, wzornik kolorow.
        assert set(obrazy_do_klienta.OBRAZY_DLA_KLIENTA) == {
            "gatunki_porownanie", "wymiary", "krawedzie", "kolory"}

    def test_kazdy_identyfikator_wskazuje_wpis_w_bots_images(self):
        # Sonda spojnosci z modulem, ktorego NIE WOLNO nam zmieniac: gdyby ktos
        # przemianowal klucz w bots/images.py, obraz przestalby sie wysylac
        # CICHO (nieznany identyfikator = brak wysylki, nie wyjatek).
        znane = set(images.IMAGES) | set(images.CONTEXT_IMAGES)
        assert set(obrazy_do_klienta.OBRAZY_DLA_KLIENTA) <= znane

    def test_kazdy_identyfikator_ma_plik_na_dysku(self):
        for ident in obrazy_do_klienta.OBRAZY_DLA_KLIENTA:
            meta = obrazy_do_klienta._meta(ident)
            assert meta is not None, ident
            assert os.path.isfile(meta[0]), ident

    def test_kazdy_obraz_ma_podpis_po_polsku_z_diakrytykami(self):
        for ident in obrazy_do_klienta.OBRAZY_DLA_KLIENTA:
            podpis = obrazy_do_klienta._meta(ident)[3]
            assert podpis and len(podpis) > 20, ident
            assert any(z in podpis for z in "ąćęłńóśźż"), ident

    def test_zaden_podpis_nie_wnosi_ZADNEJ_kwoty(self):
        # Podpis idzie do klienta z wnetrza narzedzia, wiec NIE przechodzi przez
        # guardrail G1 w tura.py. Rejestr `stan.znane_kwoty` zna wylacznie liczby
        # z kalkulatora — podpis nie ma prawa wniesc wlasnej. (Same cyfry sa
        # dozwolone: podpis krawedzi wymienia N1-N4.)
        for ident in obrazy_do_klienta.OBRAZY_DLA_KLIENTA:
            podpis = obrazy_do_klienta._meta(ident)[3]
            assert guardraile.sprawdz_ceny(podpis, set()) == [], ident

    def test_zaden_podpis_nie_niesie_zakazanego_zobowiazania(self):
        # Ta sama luka co wyzej, drugi guardrail: G3 (`znajdz_zakazane_
        # zobowiazania`) tez oglada WYLACZNIE `final_output` modelu, wiec
        # „wytrzyma"/„gwarantujemy" w podpisie wyszloby do klienta bez kontroli.
        # Podpisy sa stale i pochodza z bots/images.py — tego modulu nie wolno
        # nam zmieniac, wiec sprawdzamy, ze to, co z niego bierzemy, jest czyste.
        for ident in obrazy_do_klienta.OBRAZY_DLA_KLIENTA:
            podpis = obrazy_do_klienta._meta(ident)[3]
            assert guardraile.znajdz_zakazane_zobowiazania(podpis) == [], ident


class TestWysylka:
    def test_znany_obraz_leci_z_podpisem_i_wlasciwym_plikiem(self, monkeypatch):
        stan.ustaw_kontekst(96501, persona_tury="pro")
        wyslane = _rejestrator(monkeypatch)
        wynik = obrazy_do_klienta.wyslij("kolory")
        assert wynik["ok"] is True
        assert len(wyslane) == 1
        assert wyslane[0]["conv_id"] == 96501
        assert wyslane[0]["image_path"].endswith("wzornik_kolorow.png")
        assert wyslane[0]["image_name"] == "wzornik-kolorow.png"
        assert wyslane[0]["image_mime"] == "image/png"
        assert "wzornik" in wyslane[0]["tekst"].lower()

    def test_obraz_idzie_tozsamoscia_debusia_pro(self, monkeypatch):
        # Token MUSI byc podany jawnie: `cw_agent_reply` bez `token` siega po
        # tokenie LIVE-bota (`core/chatwoot.py`), wiec obrazek Debusia Pro
        # wyszedlby podpisany cudza tozsamoscia — dokladnie ta izolacja, na
        # ktorej stoi caly slot kandydata (patrz test_pro_zapora_core_chatwoot.py).
        #
        # Podmieniamy STALA MODULU, jak `test_pro_notatki.py`, a nie czytamy
        # config w tescie: `test_quote_worker_pro_failover.py` ustawia ten token
        # w env i PRZELADOWUJE `config`, wiec wartosc zwiazana przy imporcie
        # `obrazy_do_klienta` i ta w swiezo odczytanym `config` moga sie roznic
        # zaleznie od kolejnosci testow.
        stan.ustaw_kontekst(96513, persona_tury="pro")
        monkeypatch.setattr(obrazy_do_klienta, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")
        wyslane = _rejestrator(monkeypatch)
        obrazy_do_klienta.wyslij("wymiary")
        assert wyslane[0]["token"] == "TOKEN-PRO"

    def test_nieznany_identyfikator_nie_wysyla_NICZEGO(self, monkeypatch):
        stan.ustaw_kontekst(96502, persona_tury="pro")
        wyslane = _rejestrator(monkeypatch)
        wynik = obrazy_do_klienta.wyslij("cennik_hurtowy")
        assert wynik["ok"] is False
        assert wynik["error"] == "NIEZNANY_OBRAZ"
        assert wyslane == []

    def test_pusty_identyfikator_nie_wysyla_NICZEGO(self, monkeypatch):
        stan.ustaw_kontekst(96503, persona_tury="pro")
        wyslane = _rejestrator(monkeypatch)
        assert obrazy_do_klienta.wyslij("")["error"] == "NIEZNANY_OBRAZ"
        assert obrazy_do_klienta.wyslij(None)["error"] == "NIEZNANY_OBRAZ"
        assert wyslane == []

    def test_brak_pliku_na_dysku_nie_wysyla_samego_podpisu(self, monkeypatch):
        # Wysylka podpisu BEZ obrazu bylaby gorsza niz brak wysylki: klient
        # dostalby „prosze wskazac odcien 👇" i nie zobaczylby wzornika.
        stan.ustaw_kontekst(96504, persona_tury="pro")
        monkeypatch.setenv("BOT_IMAGES_DIR", tempfile.mkdtemp())
        wyslane = _rejestrator(monkeypatch)
        wynik = obrazy_do_klienta.wyslij("kolory")
        assert wynik["ok"] is False
        assert wynik["error"] == "BRAK_PLIKU"
        assert wyslane == []

    def test_kanal_ktory_nie_przyjmuje_obrazow_nie_dostaje_wysylki(self, monkeypatch):
        stan.ustaw_kontekst(96505, persona_tury="pro")
        monkeypatch.setattr(obrazy_do_klienta, "caps_for",
                            lambda persona: _caps(images=False))
        wyslane = _rejestrator(monkeypatch)
        wynik = obrazy_do_klienta.wyslij("wymiary")
        assert wynik["ok"] is False
        assert wynik["error"] == "KANAL_BEZ_OBRAZOW"
        assert wyslane == []

    def test_format_spoza_profilu_kanalu_nie_leci(self, monkeypatch):
        # OLX i Allegro deklaruja jpg/jpeg/png, wiec wzornik (.png) tam przejdzie —
        # ale gdyby ktorys kanal zawezil liste, PNG ma zostac w domu.
        stan.ustaw_kontekst(96506, persona_tury="pro")
        monkeypatch.setattr(obrazy_do_klienta, "caps_for",
                            lambda persona: _caps(image_formats=("jpg", "jpeg")))
        wyslane = _rejestrator(monkeypatch)
        wynik = obrazy_do_klienta.wyslij("kolory")
        assert wynik["ok"] is False
        assert wynik["error"] == "FORMAT_NIEDOZWOLONY"
        assert wyslane == []

    def test_jpg_przechodzi_przy_tym_samym_zawezonym_profilu(self, monkeypatch):
        # Kontrola negatywna do testu wyzej: bramka ma odsiewac FORMAT, a nie
        # blokowac wszystko, gdy `image_formats` jest ustawione.
        stan.ustaw_kontekst(96507, persona_tury="pro")
        monkeypatch.setattr(obrazy_do_klienta, "caps_for",
                            lambda persona: _caps(image_formats=("jpg", "jpeg")))
        wyslane = _rejestrator(monkeypatch)
        assert obrazy_do_klienta.wyslij("wymiary")["ok"] is True
        assert len(wyslane) == 1

    def test_podpis_przechodzi_przez_profil_tekstowy_kanalu(self, monkeypatch):
        # Podpisy z bots/images.py niosa emoji 👇, a OLX/Allegro emoji nie
        # renderuja (OLX_CAPS: emoji=False). Podpis MUSI wiec isc przez
        # `wysylka.przygotuj`, a nie prosto do Chatwoota.
        stan.ustaw_kontekst(96508, persona_tury="quote_olx")
        wyslane = _rejestrator(monkeypatch)
        assert obrazy_do_klienta.wyslij("krawedzie")["ok"] is True
        assert "👇" not in wyslane[0]["tekst"]
        assert "krawędzie" in wyslane[0]["tekst"]

    def test_livechat_zachowuje_emoji_z_podpisu(self, monkeypatch):
        # Kontrola negatywna: profil 'pro' nie sanityzuje niczego.
        stan.ustaw_kontekst(96509, persona_tury="pro")
        wyslane = _rejestrator(monkeypatch)
        obrazy_do_klienta.wyslij("krawedzie")
        assert "👇" in wyslane[0]["tekst"]

    def test_nieudana_wysylka_konczy_sie_bledem_a_nie_cichym_sukcesem(self, monkeypatch):
        # `cw_agent_reply` NIGDY nie rzuca — przy 429/5xx/timeoucie zwraca False.
        # Samo „nie wywalilo sie" nie jest dowodem, ze klient obraz dostal (ta
        # sama nauka co U1 w podsumowanie.wyslij).
        stan.ustaw_kontekst(96510, persona_tury="pro")
        _rejestrator(monkeypatch, wynik=False)
        wynik = obrazy_do_klienta.wyslij("wymiary")
        assert wynik["ok"] is False
        assert wynik["error"] == "WYSYLKA_NIEUDANA"

    def test_wysylka_obrazu_nie_dopisuje_niczego_do_rejestru_kwot(self, monkeypatch):
        # Inwariant I1: rejestr G1 rosnie WYLACZNIE o liczby z kalkulatora.
        stan.ustaw_kontekst(96511, persona_tury="pro")
        przed = stan.znane_kwoty()
        _rejestrator(monkeypatch)
        obrazy_do_klienta.wyslij("gatunki_porownanie")
        assert stan.znane_kwoty() == przed

    def test_wysylka_nie_udaje_handoffu_ani_podsumowania(self, monkeypatch):
        # Obraz to zwykla wiadomosc — nie moze zapalac flag, ktore `tura.py`
        # czyta jako „klient dostal juz deterministyczna tresc" albo „rozmowa
        # poszla do czlowieka". Inaczej model straciłby swoja ture za obrazek.
        stan.ustaw_kontekst(96512, persona_tury="pro")
        _rejestrator(monkeypatch)
        obrazy_do_klienta.wyslij("wymiary")
        assert stan.podsumowanie_wyslane() is False
        assert stan.handoff_w_turze() is False
