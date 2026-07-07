# -*- coding: utf-8 -*-
# Test: prompt systemowy zawiera reguly wspolne i kanalowe, persony ladowane z JSON.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

p = importlib.import_module("bots.personas")


def test_load_personas_zwraca_common_i_channels():
    dane = p.load_personas()
    assert "common" in dane
    assert "channels" in dane
    assert "olx" in dane["channels"]
    assert "allegro" in dane["channels"]
    assert "mail" in dane["channels"]


def test_pierwsza_osoba_i_wspolne_reguly():
    s = p.build_system_prompt("olx", "", {})
    assert "PIERWSZEJ OSOBIE" in s
    assert "przygotujemy" in s
    assert "Pan/Pani" in s
    assert "cen" in s.lower()
    # Nie moze byc starej, trzecioosobowej frazy bota
    assert "nasz konsultant przygotuje" not in s.lower()


def test_allegro_zakaz_kontaktu_poza_platforma():
    s = p.build_system_prompt("allegro", "", {})
    assert "poza Allegro" in s
    assert "telefon" in s.lower()


def test_mail_i_olx_roznia_sie():
    assert p.build_system_prompt("mail", "", {}) != p.build_system_prompt("olx", "", {})


def test_wiedza_wstawiona_do_promptu():
    s = p.build_system_prompt("olx", "Realizacja 14 dni.", {"name": "Jan", "identifier": "x"})
    assert "Realizacja 14 dni." in s
    assert "Jan" in s


def test_brak_wiedzy_komunikat():
    s = p.build_system_prompt("olx", "", {})
    assert "brak" in s.lower()


def test_fallback_gdy_brak_pliku_json(monkeypatch):
    # Symulujemy zepsuty/brakujacy plik JSON - bot nie moze sie wywalic,
    # a reguly bezpieczenstwa (Allegro, 1. osoba) musza przetrwac.
    monkeypatch.setattr(p, "_PATH", os.path.join(os.path.dirname(p.__file__), "nieistniejacy_plik.json"))
    dane = p.load_personas()
    assert "common" in dane
    assert "channels" in dane
    assert "allegro" in dane["channels"]

    s = p.build_system_prompt("allegro", "", {})
    assert "PIERWSZEJ OSOBIE" in s
    assert "poza Allegro" in s


def test_livechat_ma_checkliste_pol_wymaganych():
    s = p.build_system_prompt("livechat", "", {})
    low = s.lower()
    assert "technologia" in low and "mikrowczep" in low
    assert "klasa" in low
    assert "ilość" in low                      # ilosc wymagana
    assert "podstopnic" in low                 # pola schodów
    assert "surowe" in low                     # reguła wykończenia
    assert "centymetr" in low                  # normalizacja jednostek
    assert "nie potwierdzaj docięcia" in low   # twardy zakaz pytania o docięcie


def test_livechat_regula_jednostek_dopytaj():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "centymetr" in s
    assert "dopytaj" in s or "dopyta" in s


def test_livechat_klasa_wymagana():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "klasa" in s and "wymagan" in s


def test_livechat_debus_i_uczciwosc_wobec_pytania_o_bota():
    s = p.build_system_prompt("livechat", "", {})
    assert "Dębuś" in s
    low = s.lower()
    assert "nie witaj się" in low or "nie przedstawiaj" in low
    assert "asystentem ai" in low, "na wprost pytanie o bota odpowiada uczciwie"


def test_livechat_otwory_krawedzie_nie_proponowane():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "nie proponuj otworów" in s or "nie proponuj otworow" in s
    assert "zapytaj też raz" not in s, "stara zasada zbiorczego pytania usunieta"


def test_livechat_tryb_informacyjny_i_sprawy_indywidualne():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "nie każda rozmowa to wycena" in s
    assert "reklamacj" in s
    assert "status" in s and "faktur" in s


def test_livechat_pozycje_i_potwierdzenie():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "osobne pozycje" in s, "wiele produktow = osobne pozycje"
    assert "nie nadpisuj" in s
    assert "podsumowanie" in s and "potwierdzi" in s
    assert "nie podsumowuj" in s, "podsumowanie wysyla system, nie LLM"


def test_livechat_kontakt_raz_nieblokujaco():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "kontakt zwrotny" in s
    assert "nie blokuje" in s or "niczego nie blokuje" in s


def test_checklista_dziedziczona_w_podpowiadaczu_olx():
    # common.zasady sa wspolne — podpowiadacz OLX tez dostaje checkliste (technologia/klasa).
    s = p.build_system_prompt("olx", "", {}).lower()
    assert "mikrowczep" in s
    assert "klasa" in s


def test_livechat_ma_regule_koperty_wymiarow():
    s = p.build_system_prompt("livechat", "", {})
    low = s.lower()
    assert "120 cm" in low                 # max szerokość
    assert "450" in low and "500" in low   # max długość lita / mikrowczep
    assert "ponadstandard" in low          # grubość > 4 cm nie odrzucana
    assert "860" in low                    # worked example (nie przyjmuj)


def test_regula_koperty_dziedziczona_w_olx():
    s = p.build_system_prompt("olx", "", {}).lower()
    assert "120 cm" in s
    assert "500" in s


def test_livechat_otwory_krawedzie_twardo():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "nigdy nie proponuj" in s or "nie proponuj" in s
    assert "otwor" in s and "krawęd" in s


def test_livechat_bez_samodzielnej_wyceny_i_bez_adnotacji():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "wrócę z wyceną" in s or "sam" in s   # zakaz udawania wyceny
    assert "bez wyceny" in s                       # zakaz adnotacji 'bez wyceny'


def test_livechat_tryb_info_bez_pozycji():
    s = p.build_system_prompt("livechat", "", {}).lower()
    assert "pozostaw" in s and "pozycje" in s


def test_regula_gatunkow_w_prompcie():
    # Twarda regula oferty (dab/jesion/buk, brak akacji) musi trafiac do promptu kazdego kanalu.
    from bots.personas import build_system_prompt
    for kanal in ("livechat", "mail", "olx", "allegro"):
        p = build_system_prompt(kanal, "", {})
        low = p.lower()
        assert "dąb" in low and "jesion" in low and "buk" in low
        assert "akacja" in low   # przyklad gatunku spoza oferty w regule
