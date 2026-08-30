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
    resztki z Task 3 — ten sam problem, który W5 rozwiązało dla materiału).

    "surowe" NIGDY nie pokazuje ścieżki katalogowej, nawet jeśli finishing_id
    zostałby w pozycji z poprzedniego (innego) wykończenia — stan.zapisz_pozycje
    czyści finishing_id automatycznie przy przejściu na "surowe" (W1, runda
    poprawek 1), ale ta funkcja ma zostać poprawna NAWET gdyby to się kiedyś
    nie zdarzyło: inaczej klient potwierdzałby KOLOR/POŁYSK przy cenie
    surowego blatu, której ten kolor/połysk już nie dotyczy (build_products
    ignoruje finishing_id, gdy ftype == "Surowe").

    Sprawdzamy przez crm_calc._finish_type (podciąg "surow", bez względu na
    wielkość liter/diakrytyki) — DOKŁADNIE ta sama reguła, którą stosuje
    wycena (crm_calc.build_products), a nie własne, luźniejsze porównanie
    (runda poprawek 2, N1): `== "surowe"` łapało tylko jedną dokładną
    pisownię, więc "Surowe"/"surowy dąb" i podobne przechodziły przez tę
    strażnicę i nadal pokazywały ducha katalogowej ścieżki. Dziś enum
    narzędzia (Wykonczenie) wysyła wyłącznie dokładne "surowe", więc luka
    jest nieosiągalna PRZEZ NARZĘDZIE — ale ta funkcja ma być poprawna
    niezależnie od tego, czy coś kiedyś obejdzie enum."""
    tekst = str(poz.get("wykonczenie") or "").strip()
    if crm_calc._finish_type(tekst) == "Surowe":
        return tekst
    fid = poz.get("finishing_id")
    if fid and options:
        pelna_sciezka = crm_calc.finishing_full_path(fid, options)
        if pelna_sciezka:
            return pelna_sciezka.replace("/", " > ")
    return tekst


def _opis_edges(edges):
    """Czytelny opis krawędzi do podsumowania, pogrupowany po (typ, promień/kąt):
    'R5 (A, B); Fazowanie 45° (C)' — zamiast surowej liczby sztuk, która nie mówi
    klientowi, CO konkretnie podpisuje. Układ wzorowany na bots.quotebot._opis_edges
    (ten sam pomysł, bez importowania całego ciężkiego modułu quotebota).

    Obsługuje WYŁĄCZNIE "round"/"chamfer" — "sharp" nigdy tu nie trafia, bo
    crm_calc.normalize_edges pomija go już przy zapisie (stan._zastosuj_krawedzie
    zapisuje wyłącznie wynik normalize_edges), więc gałąź na inne/nieznane typy
    pomija wpis, zamiast zgadywać etykietę dla wartości, która w praktyce nie
    występuje (runda poprawek 1, drobne: martwa gałąź z etykietą dla "sharp"
    usunięta razem z nieużywanym słownikiem _TYP_EDGE_PL)."""
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
            continue
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


def wynik_dla_modelu(pozycje, wynik):
    """Payload crm_calc.calculate() PRZYCIĘTY do tego, co bot smie zacytować.

    Sekcja 'variants' per produkt z definicji niesie WSZYSTKIE 8 wariantów
    drewna z katalogu (patrz calculate_material_variants w pricing_service —
    kalkulator CRM zawsze liczy pełną tabelę porównawczą, nie tylko wybrany
    wariant), a rejestr I1 (kwoty_z_wyniku, wyżej) zna TYLKO cenę wariantu
    faktycznie WYBRANEGO w danej pozycji. Bez przycięcia bot cytujący cenę
    INNEGO (niewybranego, ale wciąż PRAWDZIWEGO) wariantu z wyniku WŁASNEGO
    wywołania narzędzia zostałby przez guardrail G1 oskarżony o halucynację
    (W3, runda poprawek 1).

    Kierunek naprawy: zwężamy to, co widzi model — NIE poszerzamy rejestru.
    Poszerzenie rejestru o wszystkie warianty otworzyłoby furtkę do cytowania
    cen wariantów, o których w rozmowie nigdy nie było mowy (dziś żadne z 11
    narzędzi nie oferuje klientowi porównania wariantów — takie narzędzie,
    gdyby powstało, dostałoby WŁASNY, świadomy zakres rejestru).

    Runda poprawek 2 (W3, sonda na PRAWDZIWYM kształcie calculate_quote):
    obcięcie do jednego wariantu NIE WYSTARCZAŁO — nawet ten jeden wariant,
    'finishing' i 'edges' niosą WŁASNE ceny jednostkowe, których rejestr też
    nie zna: variants[].price_per_m3 (cena za m3, z której liczy się
    unit_netto — zarejestrowany jest tylko wynik mnożenia, nie ten czynnik),
    finishing.price_per_m2 (analogicznie dla wykończenia) i edges.details
    (lista per-krawędź z WŁASNYMI price_netto/price_brutto per litera —
    zarejestrowana jest tylko SUMA w edges.netto/brutto, nie rozbicie).
    Bot cytujący którąkolwiek z tych liczb (np. "zaokrąglenie krawędzi A
    kosztuje 27,00 zł") cytowałby PRAWDZIWĄ cenę z wyniku WŁASNEGO narzędzia,
    a mimo to zostałby oskarżony o halucynację. Ta sama zasada: zwężamy widok
    modelu (usuwamy te trzy pola), NIE poszerzamy rejestru o rozbicie, które
    nic dziś nie potrzebuje zacytować osobno od sumy."""
    if "products" not in wynik:
        return wynik   # brak sekcji products (np. braki_mapowania) -> nic do przycięcia
    okrojony = dict(wynik)
    przyciete_produkty = []
    for poz, prod in zip(pozycje, wynik.get("products") or []):
        prod = dict(prod)
        kod = poz.get("selected_variant")
        prod["variants"] = [
            {k: v for k, v in wariant.items() if k != "price_per_m3"}
            for wariant in (prod.get("variants") or [])
            if wariant.get("variant_code") == kod and wariant.get("available")
        ]
        finishing = prod.get("finishing")
        if isinstance(finishing, dict):
            prod["finishing"] = {k: v for k, v in finishing.items() if k != "price_per_m2"}
        edges = prod.get("edges")
        if isinstance(edges, dict):
            prod["edges"] = {k: v for k, v in edges.items() if k != "details"}
        przyciete_produkty.append(prod)
    okrojony["products"] = przyciete_produkty
    return okrojony


def _bez_wrazliwych_cen(wynik):
    """Szczegóły nieudanej wyceny do zwrócenia modelowi — WYŁĄCZNIE powód
    niepowodzenia, nigdy surowy payload kalkulatora.

    Runda poprawek 2, W3b: ta sama klasa wycieku co W3 (wynik_dla_modelu),
    tylko na ścieżce błędu. crm_calc.calculate() może zwrócić ok=False z
    NADAL pełną tabelą cen w products[] (np. per-produktowy błąd
    VARIANT_UNAVAILABLE — pricing_service.calculate_quote dokłada wtedy
    'variants'/'finishing'/'edges' z tymi samymi cenami, co ścieżka sukcesu),
    a `kwoty_z_wyniku` na tej ścieżce W OGÓLE nie jest wołane (rejestr
    zostaje pusty) — więc KAŻDA liczba z takiego payloadu byłaby dla
    guardraila G1 halucynacją. Model do zakomunikowania niepowodzenia klientowi
    potrzebuje tylko powodu, nie cen."""
    bezpieczne = {}
    for pole in ("errors", "missing_fields", "braki_mapowania"):
        if wynik.get(pole):
            bezpieczne[pole] = wynik[pole]
    return bezpieczne


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
        return {"ok": False, "error": "WYCENA_NIEUDANA",
                "szczegoly": _bez_wrazliwych_cen(wynik)}

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

    # Bramka (nie dyscyplina promptu — runda poprawek 1, W3): oznacz w stanie tury,
    # że podsumowanie już poszło. `tura.py` to sprawdza i NIE wyśle niczego więcej w
    # tej samej turze, nawet gdyby model mimo wskazówki niżej coś dopisał (np.
    # sparafrazował podsumowanie własnymi słowami — dokładnie to, przed czym ma
    # chronić wysyłka WYŁĄCZNIE stąd, nie z final_output modelu).
    stan.oznacz_podsumowanie_wyslane()

    return {"ok": True, "wyslano": True, "podpis": oczekiwany,
            "wskazowka": "Podsumowanie wysłane. Twoja odpowiedź w tej turze może być pusta. "
                         "Poczekaj na reakcję klienta."}
