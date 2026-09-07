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
from core.events import log_event
from core.log import log


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
    # U-N7: zadeklarowany kształt inny niż prostokąt. W podsumowaniu DLA KLIENTA
    # ta gałąź jest nieosiągalna — `wyslij` odmawia wcześniej
    # (`blokada_ksztaltu`), więc reguła „NIE nazywaj kształtu w podsumowaniu"
    # zostaje nietknięta. Pisane jest to dla DRUGIEGO odbiorcy tej funkcji:
    # prywatnej notatki dla konsultanta (`notatki.tresc_dla_agenta`), która
    # składa się z tych samych linii. Bez tego notatka po handoffie na kształcie
    # opisywała sześciokąt 87x75 jako zwykły blat 87x75 — czyli konsultant
    # dostawał specyfikację MYLĄCĄ, a nie tylko niepełną (dokładnie ta sytuacja
    # z rozmowy 4727: konsultantka musiała sama dopytać o 6 długości krawędzi).
    ksztalt = str(poz.get("ksztalt") or "").strip()
    if ksztalt and not _KSZTALT_PROSTOKATNY.fullmatch(ksztalt):
        linia += ", kształt: %s" % ksztalt
    wykonczenie = _wykonczenie_opis(poz, options)
    if wykonczenie:
        linia += ", wykończenie: %s" % wykonczenie
    opis_krawedzi = _opis_edges(poz.get("edges"))
    if opis_krawedzi:
        linia += ", krawędzie: %s" % opis_krawedzi
    otwory = poz.get("otwory") or []
    if otwory:
        linia += ", otwory: %s" % "; ".join(str(o) for o in otwory)
        # N3 (naprawa po testach na żywym czacie): wycięcia SĄ w podsumowaniu,
        # ich koszt NIE jest w cenie — pole `otwory` nigdy nie dociera do
        # kalkulatora (jest jawnie OPISOWE, patrz `_POLA_OPISOWE` i
        # `odcisk_cenotworczy` w potwierdzenia.py) — a podsumowanie o tym
        # milczało. Bot mówił prawdę dopiero zapytany wprost, więc klient
        # potwierdzał cenę, która nie obejmowała tego, co widział tuż obok niej.
        # Adnotację składa KOD, nie model — dokładnie jak resztę tej linii; to
        # jedyny sposób, żeby stała przy KAŻDYM podsumowaniu z wycięciami, a nie
        # wtedy, gdy model akurat sobie o niej przypomni.
        #
        # To naprawa KOMUNIKATU, nie ceny: faktyczne wliczenie wycięć do wyceny
        # jest osobnym, większym zadaniem (wymaga mapowania opisu na pozycję
        # cennika, dziś FinishingOption CUTOUT w CRM).
        linia += " (koszt wycięć nie jest wliczony w tę cenę — wycenia je konsultant)"
    return linia


# --- Bramka kształtu w nazwie produktu (U-N5, runda napraw 6) ----------------
#
# `_linia` drukuje `poz["produkt"]` DOSŁOWNIE, a to pole wypełnia model
# swobodnym tekstem. Recenzja pokazała sondą, że nazwa omija każdą kontrolę:
#
#     • Blat okrągły dębowy Dąb lita A/B, 120x120x4 cm, 1 szt., ...
#
# Reguła KSZTAŁT w `prompty.WYCENA` zabrania i liczenia takiego blatu, i
# nazywania kształtu w podsumowaniu — ale była WYŁĄCZNIE promptowa, a prompt
# jest prośbą, nie bramką (ta sama różnica, dla której powstały G1 i G3).
# Kwota stojąca obok takiej nazwy jest policzona jak prostokąt o tych samych
# wymiarach: ⌀120 to 1,13 m2, kwadrat 120x120 to 1,44 m2 — 27% materiału bez
# pokrycia, podane klientowi jako cena do potwierdzenia.
#
# CO TO JEST, A CZYM NIE JEST: to nie jest walidator nazw i nie ma nim być.
# To jedna ZAMKNIĘTA lista słów kształtu i jedna bramka na wejściu `wyslij`.
# Sprawdzamy WYŁĄCZNIE pole `produkt` — „okrągły otwór pod baterię" w polu
# `otwory` jest normalną, poprawną pozycją prostokątnego blatu i ma dochodzić
# do klienta bez przeszkód.
#
# DLACZEGO ODMOWA, A NIE WYCIĘCIE SŁOWA Z NAZWY: usunięcie „okrągły" dałoby
# podsumowanie wyglądające POPRAWNIE przy cenie, która nadal jest zła —
# ukrycie dowodu, nie naprawa. Odmowa zostawia model tam, gdzie reguła
# KSZTAŁT każe mu być: przy `oddaj_czlowiekowi`.
#
# ZNANY KOSZT: model może obejść bramkę, po prostu zmieniając nazwę. To nie
# jest luka, tylko granica tego, co da się sprawdzić po nazwie — wtedy jednak
# obchodzi ją ŚWIADOMIE i po komunikacie wskazującym regułę, zamiast wysyłać
# złą cenę bez żadnego śladu. Trafienia zostają w logu, tak jak trafienia G3,
# więc na skrzynce testowej da się je policzyć.
_SLOWA_KSZTALTU = (
    r"okr[ąa]g[łl]\w*",          # okrągły, okrągła, okragly
    r"p[óo][łl]okr[ąa]g[łl]\w*",  # półokrągły — osobno, bo granica słowa
    r"owaln\w*",
    r"elipt\w*|elips\w*",
    r"nieregularn\w*",
    r"[łl]uk\w*",                # łuk, łukiem, łukowy
    # „kształt" i „kształcie" — wymiana t:c w odmianie, stąd klasa [tc]
    r"kszta[łl][tc]\w*",
    # --- U-N7 (zadanie 3): formy, których lista do dziś nie znała ------------
    # Dwie z dwunastu zmierzonych rozmów produkcyjnych to kształty
    # nieprostokątne (4727 — blat sześciokątny 87x75 o boku 43 cm, 4819 —
    # sześciokąt foremny), czyli 17% próbki, a ANI JEDNO z poniższych słów nie
    # było tu obecne. Sześciokąt z 4727 nie został wyceniony jak prostokąt
    # WYŁĄCZNIE dlatego, że model nie zapisał żadnego pola i bezpiecznik braku
    # postępu zabrał rozmowę wcześniej — osłona przypadkowa, która po naprawach
    # bramki postępu znika.
    #
    # Każdy wzorzec w DWÓCH pisowniach (z ogonkami i bez), dokładnie z tego
    # samego powodu co [ąa]/[łl] w wzorcach wyżej: kanały marketplace potrafią
    # rozebrać polskie znaki (sanitize.py), a nazwę pozycji pisze model.
    r"sze[śs][ćc]iok[ąa]t\w*",     # sześciokąt, sześciokątny, szesciokatnego
    r"pi[ęe][ćc]iok[ąa]t\w*",      # pięciokąt, pieciokatny
    r"o[śs]miok[ąa]t\w*",          # ośmiokąt, osmiokatny
    r"wielok[ąa]t\w*",
    r"tr[óo]jk[ąa]t\w*",
    r"trapez\w*",
    r"romb\w*",
    # „w kształcie litery L" — osobny wzorzec, choć „L-kształtny" łapie już
    # `kszta[łl][tc]\w*`: model przepisuje nazwę klienta i słowo „kształt"
    # bardzo często z niej wypada („Blat litery L 240x60").
    r"liter\w*\s+L",
    # „Blat w serek" (narożnik kuchenny) — realne zamówienie stolarskie i tak
    # samo niepoliczalne jak reszta tej listy.
    r"ser(?:ek|k\w*)",
)
_KSZTALT_W_NAZWIE = re.compile(
    r"(?<!\w)(?:%s)(?!\w)" % "|".join(_SLOWA_KSZTALTU), re.IGNORECASE)

# Wspólny ogon obu wskazówek niżej — jedna definicja tego, CO model ma z takim
# kształtem zrobić. Dwie kopie rozjechałyby się przy pierwszej poprawce reguły
# KSZTAŁT, a to jest jedyne zdanie, które kieruje rozmowę tam, gdzie ma trafić.
#
# Brzmi tak samo dla `policz_wycene` i dla `wyslij` — i to jest prawdą w obu
# miejscach: w żadnym z nich nic się nie policzyło ani nie wysłało.
_OGON_WSKAZOWKI_KSZTALT = (
    "Kalkulator liczy WYŁĄCZNIE prostokąty i kwadraty, więc ceny NIE policzyłem "
    "i podsumowania NIE wysłałem — kwota obok takiej pozycji byłaby ceną "
    "prostokąta o tych samych wymiarach. Postąp zgodnie z regułą KSZTAŁT: zbierz "
    "brakujące dane i wołaj oddaj_czlowiekowi z powodem 'kształt inny niż "
    "prostokąt: <opis klienta>'.")

_WSKAZOWKA_KSZTALT = (
    "Nazwa pozycji %r mówi o kształcie innym niż prostokąt. "
    + _OGON_WSKAZOWKI_KSZTALT +
    " Jeśli blat JEST prostokątny, popraw nazwę pozycji (zapisz_pozycje) tak, "
    "żeby nie nazywała kształtu, i spróbuj ponownie.")

_WSKAZOWKA_KSZTALT_POLE = (
    "Pozycja ma zapisany kształt %r, inny niż prostokąt. "
    + _OGON_WSKAZOWKI_KSZTALT +
    " Jeśli to pomyłka i blat JEST prostokątny, ustaw w zapisz_pozycje "
    "ksztalt='prostokąt' i spróbuj ponownie.")


# Definicja „co jest prostokątem" (U-N7) mieszka w `potwierdzenia.py`, razem
# z listą pól cenotwórczych i z uzasadnieniem konwencji fail-closed — służy
# DWÓM mechanizmom: tej bramce i czyszczeniu rejestru kwot G1
# (`stan._zmien_pozycje` przy zejściu pozycji z prostokąta). Jedno wyrażenie,
# bo dwie kopie rozjechałyby się przy pierwszej poprawce.
_KSZTALT_PROSTOKATNY = potwierdzenia.KSZTALT_PROSTOKATNY


def _nazwa_z_ksztaltem(pozycje):
    """Nazwa pierwszej pozycji, która przemyca kształt — albo None."""
    for poz in pozycje or []:
        nazwa = str(poz.get("produkt") or "")
        if _KSZTALT_W_NAZWIE.search(nazwa):
            return nazwa
    return None


def _zadeklarowany_inny_ksztalt(pozycje):
    """Wartość pola `ksztalt` pierwszej pozycji, która NIE jest prostokątem —
    albo None. Puste/brakujące pole to prostokąt (patrz `_KSZTALT_PROSTOKATNY`)."""
    for poz in pozycje or []:
        deklaracja = str(poz.get("ksztalt") or "").strip()
        if deklaracja and not _KSZTALT_PROSTOKATNY.fullmatch(deklaracja):
            return deklaracja
    return None


def blokada_ksztaltu(pozycje):
    """Słownik odmowy dla modelu, gdy KTÓRAKOLWIEK pozycja nie jest prostokątem
    — albo None, gdy wolno liczyć.

    JEDNA bramka dla DWÓCH wejść, którymi kształt dociera do ceny: `policz_wycene`
    (kwota do zacytowania w czacie) i `podsumowanie.wyslij` (kwota pod podpisem
    I2). Wcześniej sprawdzenie stało wyłącznie w `wyslij`, więc bot mógł
    legalnie WYPOWIEDZIEĆ cenę sześciokąta policzoną jak prostokąt — do
    podsumowania po prostu nigdy nie dochodziło.

    DWIE LINIE OBRONY, świadomie w tej kolejności:
      1. pole `ksztalt` — DEKLARACJA modelu, jednoznaczna i niezależna od tego,
         jak nazwał pozycję;
      2. regex po nazwie produktu — łapie sytuację, w której model pola nie
         ustawił, a nazwę wpisał szczerze („Blat sześciokątny 87x75").
    Deklaracja idzie pierwsza, bo niesie opis kształtu podany przez klienta,
    czyli dokładnie to, co ma trafić do powodu handoffu.

    ZAKRES, KTÓRY JEST DECYZJĄ WŁAŚCICIELA, NIE MOJĄ — NIE LUZOWAĆ MIMOCHODEM:
    bramka jest TWARDA, blokuje wszystko poza prostokątem i kwadratem. A CRM
    liczy koło i owal z dopłatą (`/api/bot/options` wystawia botowi listę
    kształtów z `round`/`circle`), więc firma robi to rutynowo, tylko nie
    rękami bota. Poluzowanie tej bramki do koła/owalu to OSOBNA decyzja
    właściciela i OSOBNE zadanie — wymaga przekazania kształtu do
    `crm_calc.build_products` (dziś wpisuje `shape: "rectangular"` na sztywno),
    inaczej „przepuszczone" koło zostanie policzone jak kwadrat, czyli powstanie
    dokładnie ta awaria, którą ta bramka zamyka."""
    deklaracja = _zadeklarowany_inny_ksztalt(pozycje)
    if deklaracja:
        # Ślad w logu jak przy trafieniach G3 — żeby dało się je policzyć na
        # skrzynce testowej, zamiast zgadywać, czy bramka w ogóle strzela.
        log("bramka ksztaltu: zadeklarowany ksztalt %r -> odmowa (conv %s)"
            % (deklaracja, stan.conv_id()))
        return {"ok": False, "error": "KSZTALT_NIEPROSTOKATNY",
                "wskazowka": _WSKAZOWKA_KSZTALT_POLE % deklaracja}

    nazwa = _nazwa_z_ksztaltem(pozycje)
    if nazwa:
        log("bramka ksztaltu: ksztalt w nazwie pozycji %r -> odmowa (conv %s)"
            % (nazwa, stan.conv_id()))
        return {"ok": False, "error": "KSZTALT_W_NAZWIE",
                "wskazowka": _WSKAZOWKA_KSZTALT % nazwa}
    return None


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


# P1 (runda napraw 3) — rozstrzygnięcie właściciela: „czasem klient nie wie co
# wybrać, więc nie możemy go zmuszać do wyboru, wtedy proponujemy szerszy zakres,
# czyli wszystkie warianty".
#
# Podsumowanie pokazuje cenę JEDNEGO wariantu — tego przyjętego do rachunku —
# i to jest w porządku, bo strona wyceny pokazuje wszystkie osiem z cenami
# (`_products_with_all_variants` w modules/calculator/routers/bot_api.py zapisuje
# komplet kodów wariantów, ceny dokłada `_inject_backend_prices` w
# quote_service.py, a client_quote.js renderuje je razem z powodem
# niedostępności). Brakowało jedynie tego, żeby klient o tym WIEDZIAŁ, zanim
# zacznie się zastanawiać, dlaczego widzi jedną kwotę zamiast porównania.
#
# Zdanie składa KOD, nie model — dokładnie tak jak adnotację o wycięciach
# (`_linia`): tylko wtedy stoi przy KAŻDYM podsumowaniu, a nie wtedy, gdy model
# akurat sobie o nim przypomni.
#
# ZERO KWOT, świadomie: porównanie jest NA STRONIE wyceny, nie w czacie, więc
# rejestr G1 nie rośnie ani o jedną pozycję i tolerancja guardraila zostaje
# nietknięta. To jest właśnie ta różnica, która przesądziła o kształcie tej
# naprawy — zestawianie kwot w oknie czatu wymagałoby zarejestrowania cen
# wszystkich wariantów i poszerzyłoby ślepą plamkę G1 kilkukrotnie.
ZDANIE_O_WARIANTACH = (
    "\n\nW wycenie, którą przygotowujemy, są ceny wszystkich wariantów drewna "
    "— dębu, jesionu i buku — do porównania; niedostępne dla tych wymiarów są "
    "tam oznaczone.")


def wyslij():
    """Liczy cenę, składa podsumowanie, zapisuje oczekiwany podpis i wysyła.

    bots_pro.wysylka (Task 6) importujemy dopiero tuż przed użyciem — moduł jeszcze
    nie istnieje w tym zadaniu, a ścieżki wczesnego wyjścia (brak pozycji, nieudana
    wycena) mają działać już teraz, bez zależności od niego.
    """
    pozycje = stan.pozycje()
    if not pozycje:
        return {"ok": False, "error": "BRAK_POZYCJI"}

    # U-N5/U-N7: kształt inny niż prostokąt — zadeklarowany polem `ksztalt`
    # albo przemycony w nazwie produktu. Sprawdzamy PRZED wołaniem kalkulatora
    # — i tak nie ma czego z niego wysłać, a cena prostokąta dla blatu
    # sześciokątnego nie ma po co powstawać. Patrz `blokada_ksztaltu`.
    blokada = blokada_ksztaltu(pozycje)
    if blokada:
        return blokada

    options = crm_calc.get_options()
    wynik = crm_calc.calculate(pozycje, options)
    if not wynik.get("ok"):
        return {"ok": False, "error": "WYCENA_NIEUDANA",
                "szczegoly": _bez_wrazliwych_cen(wynik)}

    kwoty = kwoty_z_wyniku(pozycje, wynik)
    totals = wynik.get("totals") or {}
    dostawa = stan.dostawa()

    tekst = "Podsumowanie do potwierdzenia:\n" + "\n".join(
        _linia(poz, options) for poz in pozycje)
    razem_produkty = totals.get("total_brutto")
    dostawa_brutto = dostawa.get("brutto")

    # U4: dostawa jest CZĘŚCIĄ ceny (wymóg właściciela: produkt + ew. dostawa),
    # więc klient ma ją WIDZIEĆ w tym, co potwierdza — wcześniej podsumowanie
    # pokazywało wyłącznie cenę produktu, choć bot mówił mu "produkt + wysyłka".
    # Suma jest liczona z DWÓCH liczb kalkulatora CRM (nie zgadywana) i trafia do
    # rejestru G1, żeby bot mógł ją potem legalnie zacytować.
    #
    # R3 (recenzja końcowa, runda 2) — ŚWIADOMY WYJĄTEK od zasady „cena zawsze
    # z CRM". To JEDYNA arytmetyka cenowa po stronie mostka. Sprawdzone: żaden
    # endpoint bota NIE zwraca sumy obejmującej wysyłkę, więc nie ma czego użyć
    # zamiast dodawania:
    #   - POST /api/bot/calculate -> `totals` liczone WYŁĄCZNIE z pozycji
    #     (kalkulator nie zna kodu pocztowego, więc nie ma jak doliczyć kuriera),
    #   - POST /api/bot/shipping-quote -> sam koszt wysyłki, bez produktu,
    #   - POST i PUT /api/bot/quotes -> {ok, quote_number, quote_id, edit_uuid,
    #     public_url} — ZERO kwot,
    #   - GET /api/bot/quotes(/by-token) -> `totals` z komentarzem wprost
    #     „Wysyłki NIE doliczamy — liczy ją sklep" (bot_api.py, serializer sklepu).
    # RYZYKO, które ten wyjątek niesie: gdyby CRM zaczął kiedyś stosować rabat na
    # poziomie SUMY (np. darmowa wysyłka powyżej progu), ta linia pokazywałaby
    # klientowi cenę WYŻSZĄ niż faktyczna, i to w treści, którą klient podpisuje.
    # Sygnał ostrzegawczy: pojawienie się w odpowiedzi któregokolwiek z tych
    # endpointów pola z sumą razem z wysyłką — wtedy użyć JEGO, nie tego dodawania.
    # Ostrzeżenie powtórzone w DEPLOY-quotebot.md.
    kwoty_dostawy = []
    razem_z_dostawa = None
    if dostawa.get("kurier") and isinstance(dostawa_brutto, (int, float)):
        razem_z_dostawa = round(float(razem_produkty or 0) + float(dostawa_brutto), 2)
        # N2: suma „produkt + dostawa" to kwota DOSTAWY — traci ważność razem z
        # kosztem kuriera, więc rejestrujemy ją z tym źródłem, żeby nowe
        # oszacowanie wysyłki (stan.zapisz_dostawe) mogło ją unieważnić.
        kwoty_dostawy.append(razem_z_dostawa)
        tekst += "\n\nRazem produkty: %s brutto" % _fmt_pln(razem_produkty)
        tekst += "\nDostawa (%s): %s brutto" % (dostawa["kurier"], _fmt_pln(dostawa_brutto))
        tekst += "\nRazem z dostawą: %s brutto" % _fmt_pln(razem_z_dostawa)
    else:
        # Wysyłka jeszcze nieoszacowana albo gabaryt bez kuriera — NIE dopisujemy
        # ani zmyślonego "0 zł", ani nieaktualnego kosztu sprzed zmiany pozycji
        # (stan.zapisz_dostawe/_zmien_pozycje dbają o to, żeby stary koszt tu nie dotrwał).
        #
        # N3 (rerecenzja gałęzi): ale MILCZEĆ o dostawie też nie wolno. Odkąd
        # podsumowanie CZASEM pokazuje trzy linie z kurierem, brak takiej linii
        # czyta się jak „dostawa gratis" — a klient potwierdza tę kwotę jako
        # cenę całości. Mówimy więc wprost, że kosztu wysyłki tu NIE MA, i
        # rozróżniamy dwie sytuacje, bo znaczą dla klienta co innego: „jeszcze
        # nie pytaliśmy o kod" i „kod jest, ale kuriera dla tego gabarytu nie
        # znaleźliśmy" (dokładnie ta, dla której napisano docstring
        # narzędzia policz_wysylke: carriers=0 to NIE jest darmowa wysyłka).
        kod = dostawa.get("kod_pocztowy")
        if kod:
            tekst += ("\n\nDostawa (kod %s): nie udało się wycenić kuriera dla tego "
                      "gabarytu — koszt ustali konsultant." % kod)
        else:
            tekst += ("\n\nDostawa: jeszcze nie wyceniona — koszt poznamy po podaniu "
                      "kodu pocztowego.")
        tekst += "\nRazem za produkty (bez dostawy): %s brutto" % _fmt_pln(razem_produkty)

    # P1: zdanie o wszystkich wariantach — WYŁĄCZNIE tam, gdzie klient dostanie
    # link do wyceny. Na Allegro linku nie wolno wysłać (regulamin, `wysylka.
    # wolno_linkowac`), a wycena trafia do konsultanta — obietnica „zobaczy Pan
    # wszystkie warianty" byłaby tam obietnicą bez pokrycia, czyli dokładnie tym
    # błędem, który ta runda naprawia.
    from bots_pro import wysylka
    if wysylka.wolno_linkowac(stan.persona()):
        tekst += ZDANIE_O_WARIANTACH
    tekst += "\n\nCzy wszystko się zgadza?"

    stan.zapamietaj_kwoty(kwoty)
    stan.zapamietaj_kwoty(kwoty_dostawy, zrodlo="dostawa")

    oczekiwany = potwierdzenia.podpis(pozycje, dostawa)

    # WYSYŁAMY TU, nie zwracamy tekstu modelowi. Gdyby treść wróciła do modelu,
    # ten mógłby ją sparafrazować i klient potwierdzałby parafrazę zamiast danych.
    #
    # U1 (recenzja końcowa): wynik `cw_agent_reply` JEST sprawdzany, a
    # `oczekiwany_podpis` zapisywany DOPIERO PO udanej wysyłce. `cw_agent_reply`
    # nigdy nie rzuca — przy 429/5xx/timeoucie zwraca False (core/chatwoot.py) —
    # więc wcześniejsza wersja (zapis podpisu PRZED wysyłką, wynik ignorowany)
    # meldowała `{"ok": True, "wyslano": True}` dla podsumowania, którego klient
    # NIGDY nie zobaczył. To było pełne obejście I2: podpis w bazie sprawiał, że
    # `potwierdz` i `sprawdz_bramke` przechodziły w kolejnej turze na DOWOLNYM
    # fragmencie odpowiedzi klienta, a wycena i link szły do CRM bez potwierdzenia
    # czegokolwiek. Kolejność (wyślij -> sprawdź -> zapisz podpis) jest istotą tej
    # poprawki, nie kosmetyką.
    #
    # `wysylka` jest już zaimportowana wyżej (zdanie o wariantach, P1) — drugi,
    # identyczny import w tej samej funkcji byłby martwy.
    for czesc in wysylka.przygotuj(tekst, stan.persona()):
        if not cw_agent_reply(stan.conv_id(), czesc, token=BOT_PRO_CW_AGENT_TOKEN):
            # Przerywamy PO PIERWSZEJ nieudanej części: dosłanie ogona po dziurze
            # dałoby klientowi podsumowanie z brakującym środkiem, a i tak nie
            # byłoby czego podpisywać. Podpis NIE trafia do bazy, tura NIE jest
            # oznaczana jako obsłużona — model dostaje jednoznaczny błąd.
            stan.oznacz_podsumowanie_nieudane()
            return {"ok": False, "error": "PODSUMOWANIE_NIEWYSLANE",
                    "wskazowka": "Podsumowanie NIE dotarło do klienta (błąd wysyłki). "
                                 "Klient go nie widział, więc nie może go potwierdzić. "
                                 "Napisz krótko, że za chwilę wrócisz z podsumowaniem, "
                                 "albo spróbuj wysłać je ponownie w kolejnej turze."}

    # Z4: RAZEM z podpisem, jednym zapisem i w tym samym momencie — czyli
    # dopiero PO udanej wysyłce (U1 wyżej). Osobny, wcześniejszy zapis byłby
    # powtórzeniem dokładnie tego obejścia, przed którym broni U1: w bazie
    # leżałby ślad po podsumowaniu, którego klient nigdy nie zobaczył.
    # To, co widzi klient, to ostatnia linia z sumą: „Razem z dostawą", gdy
    # kurier jest policzony, w przeciwnym razie „Razem za produkty".
    # Wartość jest POCHODNA liczb, które zwrócił kalkulator — nie nowym
    # źródłem ceny (nie idzie do `zapamietaj_kwoty`, więc guardrail G1 jej nie
    # zna i bot nadal nie może jej wypowiedzieć z tego tytułu). Wychodzi
    # WYŁĄCZNIE do prywatnej notatki dla konsultanta.
    kwota_pokazana = razem_z_dostawa if kwoty_dostawy else razem_produkty
    stan.zapisz_stan(
        oczekiwany_podpis=oczekiwany,
        pokazana_kwota=(float(kwota_pokazana)
                        if isinstance(kwota_pokazana, (int, float)) else None))

    # Bramka (nie dyscyplina promptu — runda poprawek 1, W3): oznacz w stanie tury,
    # że podsumowanie już poszło. `tura.py` to sprawdza i NIE wyśle niczego więcej w
    # tej samej turze, nawet gdyby model mimo wskazówki niżej coś dopisał (np.
    # sparafrazował podsumowanie własnymi słowami — dokładnie to, przed czym ma
    # chronić wysyłka WYŁĄCZNIE stąd, nie z final_output modelu).
    stan.oznacz_podsumowanie_wyslane()

    # T1 (telemetria lejka): ta sama nazwa i to samo pole `positions` co w
    # starym silniku (bots/quotebot.py, LS-08) — dane z obu silników mają
    # wpadać do `quote_events` w JEDNEJ jednostce.
    #
    # PO pętli wysyłki, nie przed: nieudana część robi wcześniej `return`, więc
    # zdarzenie z definicji opisuje podsumowanie, które klient FAKTYCZNIE
    # zobaczył — tak samo jak `oczekiwany_podpis` zapisywany dwie linie wyżej
    # (U1). Podsumowanie, które nie dotarło, ma zostać w telemetrii NIEobecne;
    # jego ślad to `podsumowanie_nieudane` -> handoff w `tura.py`.
    log_event(stan.conv_id(), "summary_sent", {"positions": len(pozycje)})

    return {"ok": True, "wyslano": True, "podpis": oczekiwany,
            "wskazowka": "Podsumowanie wysłane. Twoja odpowiedź w tej turze może być pusta. "
                         "Poczekaj na reakcję klienta."}
