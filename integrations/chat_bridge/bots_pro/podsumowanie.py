# -*- coding: utf-8 -*-
"""
Deterministyczne podsumowanie do potwierdzenia.

Treść składa KOD, nie model — to jedyna rzecz ze starego silnika przeniesiona wprost
(_wyslij_podsumowanie miał docstring „wysyła WYŁĄCZNIE deterministyczne podsumowanie,
bez prozy LLM" i była to słuszna decyzja).
"""
from bots import crm_calc
from bots_pro import potwierdzenia, stan
from config import BOT_PRO_CW_AGENT_TOKEN
from core.chatwoot import cw_agent_reply
from core.db import db


def _linia(poz):
    return "• %s %sx%sx%s cm, %s szt., %s" % (
        poz.get("produkt", "produkt"), poz.get("dlugosc"), poz.get("szerokosc"),
        poz.get("grubosc"), poz.get("ilosc"), poz.get("selected_variant"))


def wyslij():
    """Liczy cenę, składa podsumowanie, zapisuje oczekiwany podpis i wysyła.

    bots_pro.wysylka (Task 6) importujemy dopiero tuż przed użyciem — moduł jeszcze
    nie istnieje w tym zadaniu, a ścieżki wczesnego wyjścia (brak pozycji, nieudana
    wycena) mają działać już teraz, bez zależności od niego.
    """
    pozycje = stan.pozycje()
    if not pozycje:
        return {"ok": False, "error": "BRAK_POZYCJI"}

    wynik = crm_calc.calculate(pozycje, crm_calc.get_options())
    if not wynik.get("ok"):
        return {"ok": False, "error": "WYCENA_NIEUDANA", "szczegoly": wynik}

    totals = wynik.get("totals") or {}
    stan.zapamietaj_kwoty([v for v in totals.values() if isinstance(v, (int, float))])

    tekst = "Podsumowanie do potwierdzenia:\n" + "\n".join(_linia(p) for p in pozycje)
    tekst += "\n\nRazem: %.2f zł brutto" % (totals.get("total_brutto") or 0)
    tekst += "\n\nCzy wszystko się zgadza?"

    oczekiwany = potwierdzenia.podpis(pozycje)
    polaczenie = db()
    polaczenie.execute(
        "INSERT INTO pro_stan(conv_id, oczekiwany_podpis) VALUES(?,?) "
        "ON CONFLICT(conv_id) DO UPDATE SET oczekiwany_podpis=excluded.oczekiwany_podpis",
        (stan.conv_id(), oczekiwany))
    polaczenie.commit()
    polaczenie.close()

    # WYSYŁAMY TU, nie zwracamy tekstu modelowi. Gdyby treść wróciła do modelu,
    # ten mógłby ją sparafrazować i klient potwierdzałby parafrazę zamiast danych.
    from bots_pro import wysylka
    for czesc in wysylka.przygotuj(tekst, stan.persona()):
        cw_agent_reply(stan.conv_id(), czesc, token=BOT_PRO_CW_AGENT_TOKEN)

    return {"ok": True, "wyslano": True, "podpis": oczekiwany,
            "wskazowka": "Podsumowanie wysłane. Twoja odpowiedź w tej turze może być pusta. "
                         "Poczekaj na reakcję klienta."}
