# -*- coding: utf-8 -*-
"""
Deterministyczne podsumowanie do potwierdzenia.

Treść składa KOD, nie model — to jedyna rzecz ze starego silnika przeniesiona wprost
(_wyslij_podsumowanie miał docstring „wysyła WYŁĄCZNIE deterministyczne podsumowanie,
bez prozy LLM" i była to słuszna decyzja).
"""
import re

from bots import crm_calc
from bots_pro import potwierdzenia, stan
from config import BOT_PRO_CW_AGENT_TOKEN
from core.chatwoot import cw_agent_reply


def _fmt_pln(v):
    """Kwota PLN po polsku: separator tysięcy spacja, przecinek dziesiętny —
    1230.0 -> '1 230,00 zł'. Mała lokalna kopia bots.quotebot._fmt_pln (nie
    importujemy z bots/ — ten moduł ma ciężkie zależności startowe, a samo
    formatowanie liczby to trzy linijki)."""
    try:
        s = "%0.2f" % float(v or 0)
    except (TypeError, ValueError):
        return str(v)
    calosc, ulamek = s.split(".")
    calosc = re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", calosc)
    return "%s,%s zł" % (calosc, ulamek)


def _opis_materialu(poz):
    """'Dąb lity A/B' zamiast surowego kodu enuma 'dab-lity-ab' — gatunek/technologia/
    klasa są już w pozycji, bo stan.zapisz_pozycje rozkłada je z selected_variant
    przy zapisie (K2)."""
    gatunek = str(poz.get("gatunek") or "").strip()
    technologia = str(poz.get("technologia") or "").strip().lower()
    klasa = str(poz.get("klasa") or "").strip()
    return " ".join(c for c in (gatunek, technologia, klasa) if c)


def _wykonczenie_opis(poz, options):
    """Opis wykończenia do podsumowania: pełna ścieżka z katalogu (z kolorem/
    połyskiem) gdy jest finishing_id, inaczej surowy tekst z pola 'wykonczenie'.

    Bez tego klient potwierdzałby ogólnik ('lakierowane'), nie wiedząc, KTÓRY
    konkretny kolor/połysk (finishing_id) faktycznie trafi do zamówienia — a to
    pole i tak wchodzi do podpisu potwierdzenia (potwierdzenia.podpis), więc
    klient podpisywałby decyzję, której nigdy nie zobaczył (Task 2, domknięcie
    resztki z Task 3 — ten sam problem, który W5 rozwiązało dla materiału)."""
    fid = poz.get("finishing_id")
    if fid and options:
        pelna_sciezka = crm_calc.finishing_full_path(fid, options)
        if pelna_sciezka:
            return pelna_sciezka.replace("/", " > ")
    return str(poz.get("wykonczenie") or "").strip()


_TYP_EDGE_PL = {"sharp": "ostre", "chamfer": "fazowane", "round": "zaokrąglone"}


def _opis_edges(edges):
    """Czytelny opis krawędzi do podsumowania, pogrupowany po (typ, promień/kąt):
    'R5 (A, B); Fazowanie 45° (C)' — zamiast surowej liczby sztuk, która nie mówi
    klientowi, CO konkretnie podpisuje. Układ wzorowany na bots.quotebot._opis_edges
    (ten sam pomysł, bez importowania całego ciężkiego modułu quotebota)."""
    grupy = {}
    for e in edges or []:
        if not (isinstance(e, dict) and e.get("litera") and e.get("typ")):
            continue
        typ = e["typ"]
        r_value, angle = e.get("r_value"), e.get("angle_value")
        if typ == "round":
            etykieta = "R%s" % r_value if r_value is not None else "Zaokrąglone"
        elif typ == "chamfer":
            etykieta = "Fazowanie %s°" % angle if angle is not None else "Fazowanie"
        else:
            etykieta = _TYP_EDGE_PL.get(typ, typ).capitalize()
        grupy.setdefault((typ, r_value, angle), [etykieta, []])[1].append(e["litera"])
    return "; ".join("%s (%s)" % (etyk, ", ".join(litery)) for etyk, litery in grupy.values())


def _linia(poz, options=None):
    """Jedna linia pozycji do podsumowania — wymiary, materiał, KONKRETNE
    wykończenie (kolor/połysk z katalogu, nie tylko ogólnik), typy krawędzi
    (nie tylko ich liczba) i treść otworów/wycięć. Klient ma potwierdzać
    WSZYSTKO, co obejmuje podpis (potwierdzenia.podpis) — inaczej I2
    chroniłoby dane, których nigdy nie zobaczył (W5; ten sam problem miały
    do niedawna finishing_id i typy krawędzi — pokazywana była tylko surowa
    liczba sztuk, klient nie widział, JAKĄ obróbkę faktycznie potwierdza)."""
    nazwa = str(poz.get("produkt") or "produkt").strip()
    material = _opis_materialu(poz)
    opis = "%s %s" % (nazwa, material) if material else nazwa
    wymiary = "%sx%sx%s cm" % (poz.get("dlugosc"), poz.get("szerokosc"), poz.get("grubosc"))
    linia = "• %s, %s, %s szt." % (opis, wymiary, poz.get("ilosc"))
    wykonczenie = _wykonczenie_opis(poz, options)
    if wykonczenie:
        linia += ", wykończenie: %s" % wykonczenie
    opis_krawedzi = _opis_edges(poz.get("edges"))
    if opis_krawedzi:
        linia += ", krawędzie: %s" % opis_krawedzi
    otwory = poz.get("otwory") or []
    if otwory:
        linia += ", otwory: %s" % "; ".join(str(o) for o in otwory)
    return linia


def kwoty_z_wyniku(pozycje, wynik):
    """Wszystkie kwoty z odpowiedzi kalkulatora — nie tylko sumy całości (totals),
    ale i rozbicie per pozycja (materiał wybranego wariantu, wykończenie, krawędzie
    — wynik["products"]). Bot może w kolejnej turze wypowiedzieć dowolną z tych
    liczb (np. "blat 843,04 zł, parapet 320,00 zł"), a guardrail G1 musi je znać —
    inaczej zgłosi prawdziwą cenę jako halucynację (W4).

    Funkcja dzielona między `wyslij()` (to podsumowanie) i
    `bots_pro.narzedzia.policz_wycene` (Task 2) — jeden rejestr kwot, jedna
    definicja tego, co się do niego liczy. Bez publicznej nazwy (bez
    wiodącego podkreślnika) druga strona nie miałaby jak jej zaimportować."""
    kwoty = []
    totals = wynik.get("totals") or {}
    kwoty.extend(v for v in totals.values() if isinstance(v, (int, float)))

    for poz, prod in zip(pozycje, wynik.get("products") or []):
        for skladowa in ("finishing", "edges"):
            blok = prod.get(skladowa) or {}
            for pole in ("netto", "brutto"):
                wartosc = blok.get(pole)
                if isinstance(wartosc, (int, float)):
                    kwoty.append(wartosc)

        kod = poz.get("selected_variant")
        wariant = next((v for v in (prod.get("variants") or [])
                        if v.get("variant_code") == kod and v.get("available")), None)
        if wariant:
            for pole in ("unit_netto", "unit_brutto", "total_netto", "total_brutto"):
                wartosc = wariant.get(pole)
                if isinstance(wartosc, (int, float)):
                    kwoty.append(wartosc)
    return kwoty


def wyslij():
    """Liczy cenę, składa podsumowanie, zapisuje oczekiwany podpis i wysyła.

    bots_pro.wysylka (Task 6) importujemy dopiero tuż przed użyciem — moduł jeszcze
    nie istnieje w tym zadaniu, a ścieżki wczesnego wyjścia (brak pozycji, nieudana
    wycena) mają działać już teraz, bez zależności od niego.
    """
    pozycje = stan.pozycje()
    if not pozycje:
        return {"ok": False, "error": "BRAK_POZYCJI"}

    options = crm_calc.get_options()
    wynik = crm_calc.calculate(pozycje, options)
    if not wynik.get("ok"):
        return {"ok": False, "error": "WYCENA_NIEUDANA", "szczegoly": wynik}

    stan.zapamietaj_kwoty(kwoty_z_wyniku(pozycje, wynik))

    totals = wynik.get("totals") or {}
    tekst = "Podsumowanie do potwierdzenia:\n" + "\n".join(
        _linia(poz, options) for poz in pozycje)
    tekst += "\n\nRazem: %s brutto" % _fmt_pln(totals.get("total_brutto"))
    tekst += "\n\nCzy wszystko się zgadza?"

    oczekiwany = potwierdzenia.podpis(pozycje)
    stan.zapisz_stan(oczekiwany_podpis=oczekiwany)

    # WYSYŁAMY TU, nie zwracamy tekstu modelowi. Gdyby treść wróciła do modelu,
    # ten mógłby ją sparafrazować i klient potwierdzałby parafrazę zamiast danych.
    from bots_pro import wysylka
    for czesc in wysylka.przygotuj(tekst, stan.persona()):
        cw_agent_reply(stan.conv_id(), czesc, token=BOT_PRO_CW_AGENT_TOKEN)

    return {"ok": True, "wyslano": True, "podpis": oczekiwany,
            "wskazowka": "Podsumowanie wysłane. Twoja odpowiedź w tej turze może być pusta. "
                         "Poczekaj na reakcję klienta."}
