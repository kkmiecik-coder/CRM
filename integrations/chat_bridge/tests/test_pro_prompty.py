# -*- coding: utf-8 -*-
"""
Reguły promptu, które powstały z naprawy KONKRETNEGO błędu zaobserwowanego na
żywym czacie (runda napraw 1, sześć rozmów). Prompt jest tu jedynym miejscem,
w którym te reguły żyją — nie ma pod nimi kodu, który by je egzekwował — więc
test pilnuje jedynej rzeczy, jakiej może: że reguła NIE ZNIKNĘŁA. Przypadkowe
usunięcie zdania z długiego stringa jest niewidoczne w code review, a każde
z tych zdań kosztowało jedną rozmowę z klientem.

Testujemy KOTWICE (nagłówek sekcji + fragment nośny), nie brzmienie słowo
w słowo — przeredagowanie stylu ma przechodzić, wycięcie reguły ma oblewać.

`bots_pro.prompty` nie importuje `agents` (to gołe stringi), więc ten plik —
w odróżnieniu od test_pro_agenci.py — NIE ma `importorskip` i chodzi także
w obrazie bez SDK.
"""
from bots_pro import prompty


class TestN1PytanieZobowiazuje:
    """Trzy rozmowy z żywego czatu, jedna figura: bot w JEDNEJ turze zadawał
    pytanie i wołał oddaj_czlowiekowi. „Czy jesteś botem?" -> oferta konsultanta
    i natychmiastowe przekazanie. Obietnica porównania wariantów -> dopytanie
    i przekazanie. Przekroczony limit wariantu -> propozycja wyboru i
    przekazanie. Za każdym razem klient zostawał z pytaniem bez adresata:
    rozmowa była już u człowieka, więc odpowiedź klienta trafiała w próżnię."""

    def test_rola_kaze_poczekac_na_odpowiedz_po_pytaniu_o_bota(self):
        assert "czy to bot" in prompty.ROLA
        assert "poczekaj na odpowiedź klienta" in prompty.ROLA

    def test_rola_nie_wozi_juz_dopisku_o_imieniu_klienta(self):
        # Ta zmiana jest opłaceniem tej wyżej: ROLA doklejana jest do WSZYSTKICH
        # agentów, w tym do routera, którego budżet (ROLA+ROUTER) ma limit 400
        # tokenów i stał na 393. Dopisek o imieniu klienta jest kosmetyką stylu
        # — reguła o czekaniu na odpowiedź chroni przed zostawieniem klienta
        # bez adresata. Wycięcie zwolniło zapas: 393 -> 388 tokenów.
        assert "imieniem klienta" not in prompty.ROLA

    def test_wycena_ma_regule_pytanie_zobowiazuje(self):
        assert "PYTANIE ZOBOWIĄZUJE" in prompty.WYCENA
        assert "nie wołaj w tej samej turze oddaj_czlowiekowi" in prompty.WYCENA


class TestN2PodsumowaniePoDoliczeniuDostawy:
    """Rozmowa z żywego czatu: po policz_wysylke bot poprosił o ponowne
    potwierdzenie, NIE pokazując nowego podsumowania — musiałem sam poprosić
    o zestawienie. Klient miałby potwierdzić kwotę, której nigdy nie zobaczył,
    czyli dokładnie to, przed czym chroni wymóg potwierdzenia (I2), wpuszczone
    bocznymi drzwiami."""

    def test_wycena_kaze_wyslac_podsumowanie_ponownie_po_dostawie(self):
        assert "Po policz_wysylke zawsze wołaj wyslij_podsumowanie ponownie" in prompty.WYCENA
        assert "nie potwierdzać starą" in prompty.WYCENA


class TestN4KsztaltInnyNizProstokat:
    """Rozmowa z żywego czatu: klient poprosił o blat okrągły ⌀120. Bot nazwał
    go okrągłym i policzył kwadrat 120x120. Koło o średnicy 120 to 1,13 m2,
    kwadrat 120x120 to 1,44 m2 — 27% materiału różnicy, czyli kwota bez
    pokrycia, podana klientowi jako cena wiążąca do potwierdzenia. Kalkulator
    CRM nie zna innych kształtów niż prostokąt; jedynym poprawnym wyjściem
    jest człowiek."""

    def test_wycena_ma_sekcje_ksztalt(self):
        assert "KSZTAŁT." in prompty.WYCENA
        assert "Wyceniamy wyłącznie prostokąty i kwadraty" in prompty.WYCENA

    def test_wycena_wymienia_ksztalty_ktorych_nie_liczymy(self):
        for ksztalt in ("okrągły", "owalny", "litery L", "łukiem", "nieregularny"):
            assert ksztalt in prompty.WYCENA, ksztalt

    def test_wycena_zabrania_liczenia_ksztaltu_jak_prostokata(self):
        assert "Nigdy nie licz takiego kształtu jak prostokąta" in prompty.WYCENA

    def test_wycena_kaze_oddac_taki_ksztalt_czlowiekowi(self):
        assert "kształt inny niż prostokąt" in prompty.WYCENA
