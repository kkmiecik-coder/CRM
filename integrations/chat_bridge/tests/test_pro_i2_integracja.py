# -*- coding: utf-8 -*-
"""
I2 od początku do końca, przez PRAWDZIWĄ bazę — nie atrapy.

Runda poprawek 1, W2: `TestBramka` w `test_pro_potwierdzenia.py` stubuje OBIE strony
porównania (`_stan_potwierdzenia` i `_biezace_pozycje`), więc dowodzi tylko jednego
`!=` na dwóch stałych — nie dotyka ani `pro_stan`, ani `stan.pozycje()`, ani
`potwierdz()`. To poniżej jest test, który faktycznie broni przypadku #2016: prawdziwy
przepływ `stan.zapisz_pozycje` -> `podsumowanie.wyslij` -> `potwierdzenia.potwierdz`
-> `potwierdzenia.sprawdz_bramke`, z zamockowanym tylko tym, co mostek naprawdę nie
może wywołać w testach (kalkulator CRM przez HTTP i wysyłka do Chatwoota).
"""
import sys
import types

from bots_pro import podsumowanie, potwierdzenia, stan

stan.init_pro()


def _atrapa_wysylki(monkeypatch):
    """Podmienia bots_pro.wysylka w sys.modules — moduł powstaje dopiero w Task 6."""
    modul = types.ModuleType("bots_pro.wysylka")
    modul.przygotuj = lambda tekst, persona: [tekst]
    monkeypatch.setitem(sys.modules, "bots_pro.wysylka", modul)


def _przygotuj(monkeypatch, conv_id, grubosc, ostatnia_wiadomosc):
    stan.ustaw_kontekst(conv_id)
    _atrapa_wysylki(monkeypatch)
    monkeypatch.setattr(podsumowanie, "cw_agent_reply", lambda *a, **k: True)
    monkeypatch.setattr(podsumowanie.crm_calc, "get_options", lambda: {})
    monkeypatch.setattr(podsumowanie.crm_calc, "calculate", lambda p, o: {
        "ok": True,
        "totals": {"total_netto": 3806.0, "total_brutto": 7261.92 if grubosc == 10 else 4681.87},
        "products": [],
    })
    monkeypatch.setattr(stan, "ostatnia_wiadomosc_klienta", lambda: ostatnia_wiadomosc)
    stan.zapisz_pozycje("1", produkt="blat", dlugosc_cm=180, szerokosc_cm=60,
                        grubosc_cm=grubosc, ilosc=1, selected_variant="dab-lity-ab",
                        wykonczenie="surowe")


def test_zmiana_grubosci_po_potwierdzeniu_blokuje_bramke(monkeypatch):
    """Pierwsza polowa #2016: klient zmienia grubosc PO tym, jak juz potwierdzil
    (podpisal) poprzednie podsumowanie. sprawdz_bramke — brama przed zapisem/linkiem
    do checkoutu — MUSI odmowic, dopoki nie przyjdzie nowe podsumowanie+potwierdzenie."""
    conv_id = 95001
    _przygotuj(monkeypatch, conv_id, grubosc=10, ostatnia_wiadomosc="Tak")

    wynik_podsumowania = podsumowanie.wyslij()
    assert wynik_podsumowania["ok"] is True

    wynik_potwierdzenia = potwierdzenia.potwierdz("Tak")
    assert wynik_potwierdzenia["ok"] is True

    assert potwierdzenia.sprawdz_bramke()["ok"] is True

    # Klient (albo model po cichu) zmienia grubosc na 6 PO potwierdzeniu.
    stan.zapisz_pozycje("1", grubosc_cm=6)

    wynik_bramki = potwierdzenia.sprawdz_bramke()
    assert wynik_bramki["ok"] is False
    assert wynik_bramki["error"] == "POTWIERDZENIE_NIEAKTUALNE"


def test_zmiana_grubosci_miedzy_podsumowaniem_a_potwierdzeniem_blokuje_potwierdz(monkeypatch):
    """Druga polowa #2016 (W1): zmiana danych MIEDZY wyslaniem podsumowania a
    potwierdzeniem klienta. potwierdz() nie moze podpisac czegos, czego klient
    nigdy nie widzial, nawet jesli klient dosłownie napisal 'Tak'."""
    conv_id = 95002
    _przygotuj(monkeypatch, conv_id, grubosc=10, ostatnia_wiadomosc="Tak")

    wynik_podsumowania = podsumowanie.wyslij()
    assert wynik_podsumowania["ok"] is True

    # Dane zmieniaja sie PO wyslaniu podsumowania, PRZED odpowiedzia klienta.
    stan.zapisz_pozycje("1", grubosc_cm=6)

    wynik_potwierdzenia = potwierdzenia.potwierdz("Tak")
    assert wynik_potwierdzenia["ok"] is False
    assert wynik_potwierdzenia["error"] == "DANE_ZMIENIONE_OD_PODSUMOWANIA"

    # I konsekwentnie: bramka tez nie przepuszcza, bo nic nie zostalo potwierdzone.
    assert potwierdzenia.sprawdz_bramke()["ok"] is False


def test_bez_zmian_potwierdzenie_przechodzi_przez_cala_sciezke(monkeypatch):
    """Kontrola negatywna: ta sama sciezka BEZ zmiany danych po drodze musi
    zakonczyc sie sukcesem — inaczej poprawka I2 blokowalaby tez prawidlowy przeplyw."""
    conv_id = 95003
    _przygotuj(monkeypatch, conv_id, grubosc=4, ostatnia_wiadomosc="Tak, zgadzam się")

    assert podsumowanie.wyslij()["ok"] is True
    assert potwierdzenia.potwierdz("tak, zgadzam się")["ok"] is True
    assert potwierdzenia.sprawdz_bramke()["ok"] is True


def test_zmiana_dostawy_po_potwierdzeniu_blokuje_bramke(monkeypatch):
    """U4: dostawa jest CZĘŚCIĄ ceny (wymóg właściciela: produkt + ew. dostawa),
    więc zmiana kuriera/kodu pocztowego PO potwierdzeniu musi unieważnić zgodę
    dokładnie tak samo, jak zmiana grubości blatu."""
    conv_id = 95004
    _przygotuj(monkeypatch, conv_id, grubosc=4, ostatnia_wiadomosc="Tak")
    stan.zapisz_dostawe("00-001", kurier="DPD", netto=200.0, brutto=246.0)

    assert podsumowanie.wyslij()["ok"] is True
    assert potwierdzenia.potwierdz("Tak")["ok"] is True
    assert potwierdzenia.sprawdz_bramke()["ok"] is True

    # Klient podaje inny adres -> inny kurier i inny koszt dostawy.
    stan.zapisz_dostawe("80-001", kurier="InPost", netto=300.0, brutto=369.0)

    wynik = potwierdzenia.sprawdz_bramke()
    assert wynik["ok"] is False
    assert wynik["error"] == "POTWIERDZENIE_NIEAKTUALNE"
