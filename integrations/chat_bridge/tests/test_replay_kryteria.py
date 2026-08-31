# -*- coding: utf-8 -*-
"""
Kryteria oceny odtworzonych rozmow (Task 9: harness ewaluacyjny) i parser
transkryptow audytu produkcji.

Kryteria musza byc automatyczne — 117 rozmow nie da sie oceniac recznie przy
kazdej zmianie modelu (dostawcy). Ten plik NIE wymaga zainstalowanego SDK
`agents` — kryteria (e2e/kryteria.py) sa CZYSTYMI funkcjami, a parser
(`replay.wczytaj_rozmowy`) tylko czyta tekst; import samego modulu
`e2e.replay` jest bezpieczny bez SDK (import bots_pro.tura, a wiec i agents,
jest LENIWY, dopiero wewnatrz `odtworz()` — patrz jego docstring).

Testy WYWOLUJACE `replay.odtworz()` (a wiec wymagajace prawdziwego Runnera
Agents SDK) sa w osobnym pliku, test_replay_odtworz.py, ktory zaczyna od
pytest.importorskip("agents") — ten sam wzorzec co tests/test_pro_tura.py.
Ten podzial maksymalizuje liczbe testow dzialajacych TAKZE bez SDK (pakiet
"bez SDK" z raportu zadania)."""
import os

import pytest

from e2e import kryteria, replay

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "e2e", "dane", "przyklad_shard.txt")


class TestPowtorzonaFormulka:
    def test_ta_sama_odpowiedz_dwa_razy_jest_zgloszona(self):
        odpowiedzi = ["To porownanie pokazalem juz wyzej.",
                      "To porownanie pokazalem juz wyzej."]
        assert kryteria.powtorzone_formulki(odpowiedzi) == 1

    def test_rozne_odpowiedzi_nie_sa_powtorka(self):
        assert kryteria.powtorzone_formulki(["Dzien dobry", "Jaki gatunek?"]) == 0

    def test_trzy_takie_same_to_dwie_powtorki(self):
        assert kryteria.powtorzone_formulki(["x", "x", "x"]) == 2

    def test_rozne_biale_znaki_i_wielkosc_liter_to_wciaz_ta_sama_formulka(self):
        # Audyt: bot potrafil powtorzyc TEN SAM komunikat z drobnymi
        # roznicami formatowania (podwojne spacje, inna wielkosc liter) —
        # to wciaz jedna, powtorzona formulka z punktu widzenia klienta.
        odpowiedzi = ["Dzien dobry,  jak moge   pomoc?", "dzien dobry, jak moge pomoc?"]
        assert kryteria.powtorzone_formulki(odpowiedzi) == 1

    def test_puste_odpowiedzi_sa_pomijane(self):
        assert kryteria.powtorzone_formulki(["", "   ", ""]) == 0

    def test_brak_odpowiedzi_nie_wybucha(self):
        assert kryteria.powtorzone_formulki([]) == 0
        assert kryteria.powtorzone_formulki(None) == 0


class TestPowtorzoneFormulkiPrzyblizone:
    """Runda poprawek 1 (drobne): porownanie DOKLADNE nie lapie powtorki
    roznizacej sie jedna liczba (audyt: ta sama formulka z inna cena/wymiarem
    powtarzana w kolko) — `powtorzone_formulki` zanizalby wynik wzgledem
    audytu. To NOWA, DODATKOWA metryka — nie zastepuje dokladnej."""

    def test_ta_sama_formulka_z_inna_liczba_jest_zgloszona(self):
        odpowiedzi = ["Cena wynosi 999,00 zl.", "Cena wynosi 1050,00 zl."]
        assert kryteria.powtorzone_formulki(odpowiedzi) == 0  # dokladne NIE lapie
        assert kryteria.powtorzone_formulki_przyblizone(odpowiedzi) == 1  # przyblizone lapie

    def test_naprawde_rozne_odpowiedzi_nie_sa_powtorka(self):
        odpowiedzi = ["Jaki gatunek Pan/Pani wybiera?", "Ile sztuk potrzeba?"]
        assert kryteria.powtorzone_formulki_przyblizone(odpowiedzi) == 0

    def test_dokladna_powtorka_jest_tez_zgloszona_jako_przyblizona(self):
        # kontrola spojnosci: dokladna powtorka (bez liczb) to TEZ przyblizona
        odpowiedzi = ["Dzien dobry", "Dzien dobry"]
        assert kryteria.powtorzone_formulki(odpowiedzi) == 1
        assert kryteria.powtorzone_formulki_przyblizone(odpowiedzi) == 1

    def test_puste_i_brak_nie_wybuchaja(self):
        assert kryteria.powtorzone_formulki_przyblizone(["", "  "]) == 0
        assert kryteria.powtorzone_formulki_przyblizone([]) == 0
        assert kryteria.powtorzone_formulki_przyblizone(None) == 0


class TestZawieraLink:
    def test_link_https_jest_wykrywany(self):
        assert kryteria.zawiera_link(
            ["Oto link: https://crm.woodpower.pl/quotes/c/abc"]) is True

    def test_link_http_bez_s_tez_jest_wykrywany(self):
        assert kryteria.zawiera_link(["http://przyklad.pl/x"]) is True

    def test_brak_linku_w_zadnej_odpowiedzi(self):
        assert kryteria.zawiera_link(["Dziekuje za wiadomosc", "Prosze o wymiary"]) is False

    def test_link_w_ktorejkolwiek_odpowiedzi_wystarczy(self):
        assert kryteria.zawiera_link(["pierwsza bez linku", "http://przyklad.pl/x"]) is True

    def test_pusta_lista_nie_ma_linku(self):
        assert kryteria.zawiera_link([]) is False
        assert kryteria.zawiera_link(None) is False


class TestZakonczenie:
    def test_handoff_jest_poprawnym_zakonczeniem(self):
        assert kryteria.zakonczona_poprawnie(["...konsultant sie odezwie"],
                                             handoff=True, link=False) is True

    def test_link_do_wyceny_jest_poprawnym_zakonczeniem(self):
        assert kryteria.zakonczona_poprawnie(["oto link"],
                                             handoff=False, link=True) is True

    def test_brak_handoffu_i_linku_to_slepa_uliczka(self):
        assert kryteria.zakonczona_poprawnie(["..."],
                                             handoff=False, link=False) is False


class TestTrafnoscRoutingu:
    """Sygnatura bierze DWIE LISTY (nie gotowe pary) — runda poprawek 1:
    poprzednia wersja budowala pary przez zwykly `zip(oczekiwana, faktyczna)`
    w `kryteria.ocen`, ktory MILCZACO obcina do krotszej listy. Sygnatura z
    dwiema listami usuwa mozliwosc powtorzenia tego bledu u KAZDEGO
    wywolujacego, nie tylko w jednym miejscu wywolania."""

    def test_wszystkie_trafienia_daja_1(self):
        assert kryteria.trafnosc_routingu(
            ["Wycena", "Wiedza"], ["Wycena", "Wiedza"]) == 1.0

    def test_polowa_trafien_daje_0_5(self):
        assert kryteria.trafnosc_routingu(
            ["Wycena", "Wiedza"], ["Wycena", "Posprzedaz"]) == 0.5

    def test_zero_trafien_daje_0(self):
        assert kryteria.trafnosc_routingu(["Wycena"], ["Wiedza"]) == 0.0

    def test_pusta_lista_oczekiwanych_to_brak_pomiaru_nie_zero(self):
        # None != 0.0 — brak etykiet (jak w realnych transkryptach audytu)
        # nie ma zostac odczytany jako "0% trafnosci".
        assert kryteria.trafnosc_routingu([], []) is None
        assert kryteria.trafnosc_routingu(None, None) is None

    def test_krotsza_faktyczna_trasa_nie_jest_cicho_obcinana(self):
        # Regresja rundy poprawek 1: router mial zrobic DWA przeskoki
        # (Wycena->Wiedza), zrobil jeden (utknal na Wycena) - to POLOWA
        # trafien (1 z 2), NIE 100% jak dawaloby zwykle zip() obcinajace
        # oczekiwana liste do dlugosci faktycznej.
        assert kryteria.trafnosc_routingu(["Wycena", "Wiedza"], ["Wycena"]) == 0.5

    def test_dluzsza_faktyczna_trasa_nie_zawyza_wyniku(self):
        # Odwrotny przypadek: faktyczna trasa DLUZSZA niz oczekiwana (router
        # zrobil dodatkowy, niepotrzebny przeskok) - nadmiarowy wpis nie ma
        # jak "trafic" (dzielimy przez dlugosc oczekiwanej), ale tez nie ma
        # wywalic wyjatkiem.
        assert kryteria.trafnosc_routingu(["Wycena"], ["Wycena", "Wiedza"]) == 1.0

    def test_pusta_faktyczna_trasa_przy_niepustej_oczekiwanej_to_zero(self):
        # Rozne od "brak pomiaru" (oba None) - tu ETYKIETA jest, ale bot
        # nie zrobil ZADNEGO przeskoku (np. Runner sie wywalil) - to
        # naprawde 0%, nie brak danych.
        assert kryteria.trafnosc_routingu(["Wycena"], []) == 0.0


class TestHandoffyNa100:
    def test_polowa_rozmow_z_handoffem(self):
        assert kryteria.handoffy_na_100(10, 5) == 50.0

    def test_zero_rozmow_nie_dzieli_przez_zero(self):
        assert kryteria.handoffy_na_100(0, 0) == 0.0

    def test_skala_audytu_117_rozmow(self):
        assert round(kryteria.handoffy_na_100(117, 30), 2) == round(100.0 * 30 / 117, 2)


class TestKosztRozmowy:
    def test_domyslny_cennik_wazy_wyjscie_mocniej_niz_wejscie(self):
        # Runda poprawek 1: waga 1:1 z pierwszej wersji byla zwyklym
        # licznikiem tokenow pod inna nazwa — kazdy liczacy sie dostawca
        # liczy token WYJSCIOWY kilkukrotnie drozej niz wejsciowy.
        uzycia = [{"input_tokens": 100, "output_tokens": 50}]
        assert kryteria.koszt_rozmowy(uzycia) == 100 * 1.0 + 50 * 4.0

    def test_wiele_wywolan_w_jednej_rozmowie_sie_sumuje(self):
        # jedna tura moze wywolac Runner.run_sync dwa razy (korekta G1)
        uzycia = [{"input_tokens": 100, "output_tokens": 50},
                  {"input_tokens": 40, "output_tokens": 10}]
        assert kryteria.koszt_rozmowy(uzycia) == (100 + 40) * 1.0 + (50 + 10) * 4.0

    def test_wlasny_cennik_nadpisuje_domyslny(self):
        uzycia = [{"input_tokens": 1000, "output_tokens": 1000}]
        cennik = {"input": 0.000003, "output": 0.000015}
        assert kryteria.koszt_rozmowy(uzycia, cennik=cennik) == pytest.approx(0.018)

    def test_obiekt_z_atrybutami_dziala_tak_samo_jak_dict(self):
        # replay.py w praktyce podaje TU prawdziwe obiekty agents.usage.Usage
        # (atrybuty, nie dict) — funkcja ma dzialac dla obu ksztaltow.
        class UzycieAtrapa:
            input_tokens = 20
            output_tokens = 5

        assert kryteria.koszt_rozmowy([UzycieAtrapa()]) == 20 * 1.0 + 5 * 4.0

    def test_brak_pola_na_obiekcie_liczy_sie_jako_zero(self):
        class UzycieBezPol:
            pass

        assert kryteria.koszt_rozmowy([UzycieBezPol()]) == 0.0

    def test_brak_uzyc_to_koszt_zero(self):
        assert kryteria.koszt_rozmowy([]) == 0.0
        assert kryteria.koszt_rozmowy(None) == 0.0


class TestP95CzasuTury:
    def test_pusta_lista_to_brak_pomiaru(self):
        assert kryteria.p95_czas([]) is None
        assert kryteria.p95_czas(None) is None

    def test_jedna_wartosc_to_ona_sama(self):
        assert kryteria.p95_czas([3.5]) == 3.5

    def test_dwadziescia_wartosci_p95_to_dziewietnasta_najmniejsza(self):
        # nearest-rank: 20 wartosci 1..20 sekund -> indeks = ceil(0.95*20)-1
        # = 18 (0-indeksowany) -> 19-ta co do wielkosci wartosc = 19.0.
        czasy = [float(i) for i in range(1, 21)]
        assert kryteria.p95_czas(czasy) == 19.0

    def test_kolejnosc_wejscia_nie_ma_znaczenia(self):
        nieposortowane = kryteria.p95_czas([5.0, 1.0, 3.0, 2.0, 4.0])
        posortowane = kryteria.p95_czas([1.0, 2.0, 3.0, 4.0, 5.0])
        assert nieposortowane == posortowane


class TestOcenZbiorczo:
    def test_zawiera_wszystkie_pola_brief(self):
        rozmowa = {"id": 42}
        wynik = kryteria.ocen(rozmowa, ["odp1", "odp1"], handoff=False, link=False)
        assert wynik["id"] == 42
        assert wynik["tur"] == 2
        assert wynik["powtorki"] == 1
        assert wynik["ma_wyjscie"] is False
        assert wynik["kwoty_niezgodne"] == 0

    def test_link_wykrywany_automatycznie_gdy_nie_podano_jawnie(self):
        rozmowa = {"id": 1}
        wynik = kryteria.ocen(rozmowa, ["oto link https://crm.woodpower.pl/x"])
        assert wynik["ma_wyjscie"] is True

    def test_koszt_i_p95_licza_sie_z_podanych_danych(self):
        rozmowa = {"id": 1}
        wynik = kryteria.ocen(
            rozmowa, ["odp"], uzycia=[{"input_tokens": 10, "output_tokens": 5}],
            czasy_tur=[1.0, 2.0])
        assert wynik["koszt"] == 10 * 1.0 + 5 * 4.0
        assert wynik["p95_czasu_tury"] == 2.0

    def test_trafnosc_routingu_liczy_sie_tylko_gdy_podano_oczekiwana_trase(self):
        rozmowa = {"id": 1}
        bez_etykiety = kryteria.ocen(rozmowa, ["odp"], trasa=["Wycena"])
        assert "trafnosc_routingu" not in bez_etykiety

        z_etykieta = kryteria.ocen(
            rozmowa, ["odp"], trasa=["Wycena"], oczekiwana_trasa=["Wycena"])
        assert z_etykieta["trafnosc_routingu"] == 1.0


class TestParserTranskryptu:
    """Format audytu produkcji: naglowek `ROZMOWA #<id>`, linie
    `[czas] KLIENT:` / `BOT:` / `AGENT:` / `NOTATKA-PRYW:` / `SYSTEM:`."""

    def test_wczytuje_wszystkie_rozmowy_z_syntetycznego_shardu(self):
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        assert [r["id"] for r in rozmowy] == [1001, 1002, 1003]

    def test_naglowek_z_dodatkowym_tekstem_nie_gubi_id(self):
        # "ROZMOWA #1001 (przyklad syntetyczny, inbox 18, 2026-01-05)" —
        # reszta naglowka (data/inbox) jest ignorowana, id musi zostac
        # poprawnie odczytane.
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        assert rozmowy[0]["id"] == 1001

    def test_rozpoznaje_wiadomosci_klienta_po_kolei(self):
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == [
            "dzien dobry, chcialbym wycene blatu debowego",
            "200x60x4, lity, klasa A/B, 1 sztuka, surowy",
            "tak",
        ]

    def test_rozpoznaje_wszystkie_typy_nadawcy(self):
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        nadawcy = {k for k, _ in rozmowy[1]["wiadomosci"]}
        assert nadawcy == {"KLIENT", "BOT", "AGENT", "NOTATKA-PRYW"}

    def test_system_jest_rozpoznawany(self):
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        assert any(k == "SYSTEM" for k, _ in rozmowy[2]["wiadomosci"])

    def test_dwie_kolejne_wiadomosci_nie_sa_bledne_sklejane(self):
        # kontrola negatywna dla logiki doklejania kontynuacji: KAZDA linia
        # pasujaca do wzorca `[czas] KTO:` to NOWA wiadomosc.
        rozmowy = replay.wczytaj_rozmowy(FIXTURE)
        assert len(rozmowy[0]["wiadomosci"]) == 5   # 3 KLIENT + 2 BOT

    def test_wieloliniowa_wiadomosc_klienta_jest_sklejana(self, tmp_path):
        plik = tmp_path / "shard_wieloliniowy.txt"
        plik.write_text(
            "ROZMOWA #5\n"
            "[08:00] KLIENT: adres dostawy to:\n"
            "ul. Kwiatowa 5\n"
            "00-000 Miasto\n"
            "[08:01] BOT: Dziekuje, zapisalem adres.\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == ["adres dostawy to:\nul. Kwiatowa 5\n00-000 Miasto"]

    def test_pusta_linia_nie_wchodzi_do_tresci_ale_nie_zrywa_kontynuacji(self, tmp_path):
        plik = tmp_path / "shard_pusta_linia.txt"
        plik.write_text(
            "ROZMOWA #6\n"
            "[08:00] KLIENT: pierwsza czesc\n"
            "\n"
            "druga czesc (po pustej linii)\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == ["pierwsza czesc\ndruga czesc (po pustej linii)"]

    def test_blok_metadanych_nie_dokleja_sie_do_wiadomosci_klienta(self, tmp_path):
        # Runda poprawek 1, W2 — reprodukcja zgloszonej sondy: blok "ZDARZENIA"
        # z wcietymi podpunktami, wystepujacy BEZPOSREDNIO po linii KLIENT (bez
        # pustej linii oddzielajacej), NIE MA prawa trafic do tresci klienta —
        # bot dostalby wtedy metadane harnessu jako czesc wiadomosci klienta.
        plik = tmp_path / "shard_zdarzenia.txt"
        plik.write_text(
            "ROZMOWA #8\n"
            "[10:05] KLIENT: 200x60x4\n"
            "ZDARZENIA\n"
            "  10:06 handoff -> konsultant\n"
            "  10:07 status: open\n"
            "[10:08] BOT: Dziekuje.\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == ["200x60x4"]
        bot = [t for k, t in rozmowy[0]["wiadomosci"] if k == "BOT"]
        assert bot == ["Dziekuje."]

    def test_blok_metadanych_na_koncu_pliku_nie_wybucha(self, tmp_path):
        plik = tmp_path / "shard_zdarzenia_koniec.txt"
        plik.write_text(
            "ROZMOWA #9\n"
            "[10:05] KLIENT: pytanie\n"
            "ZDARZENIA\n"
            "  10:06 status: pending\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == ["pytanie"]

    def test_wcieta_linia_bez_naglowka_bloku_tez_nie_dokleja_sie(self, tmp_path):
        # Drugi, niezalezny sygnal (samo wciecie, bez linii-naglowka) — obrona
        # w glab, gdyby jakis blok metadanych nie mial wlasnego naglowka.
        plik = tmp_path / "shard_wciecie.txt"
        plik.write_text(
            "ROZMOWA #10\n"
            "[10:05] KLIENT: pytanie\n"
            "  cos co wyglada na podpunkt\n"
            "[10:06] BOT: odpowiedz\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        klient = [t for k, t in rozmowy[0]["wiadomosci"] if k == "KLIENT"]
        assert klient == ["pytanie"]

    def test_tekst_przed_pierwszym_naglowkiem_jest_ignorowany(self, tmp_path):
        plik = tmp_path / "shard_smieci.txt"
        plik.write_text(
            "### export z 2026-01-01 ###\n"
            "ROZMOWA #7\n"
            "[08:00] KLIENT: pierwsza wiadomosc\n",
            encoding="utf-8")

        rozmowy = replay.wczytaj_rozmowy(str(plik))

        assert len(rozmowy) == 1
        assert rozmowy[0]["id"] == 7

    def test_dwa_pliki_z_rozlacznymi_id_nie_koliduja(self, tmp_path):
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        p1.write_text("ROZMOWA #1\n[08:00] KLIENT: a\n", encoding="utf-8")
        p2.write_text("ROZMOWA #2\n[08:00] KLIENT: b\n", encoding="utf-8")

        assert [r["id"] for r in replay.wczytaj_rozmowy(str(p1))] == [1]
        assert [r["id"] for r in replay.wczytaj_rozmowy(str(p2))] == [2]

    def test_pusty_plik_daje_pusta_liste(self, tmp_path):
        plik = tmp_path / "pusty.txt"
        plik.write_text("", encoding="utf-8")

        assert replay.wczytaj_rozmowy(str(plik)) == []
