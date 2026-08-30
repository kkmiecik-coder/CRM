# -*- coding: utf-8 -*-
"""
Narzędzia agentów. Opakowują istniejące API CRM (/api/bot/*) w function tools
Agents SDK.

Zasada nadrzędna: cena NIGDY nie powstaje w modelu. policz_wycene zwraca liczby
z pricing_service, a agent może je wyłącznie zacytować — pilnuje tego guardrail
integralności ceny (G1, bots_pro/guardraile.py).

Inwariant przenośności: żadnych narzędzi hostowanych przez dostawcę i żadnych
funkcji wyłącznych dla Responses API. Wszystko to zwykłe function tools —
patrz test_pro_narzedzia.py::TestZestawNarzedzi.

Zasada warstw: ten moduł jest CIENKĄ WARSTWĄ nad bots_pro.stan / .potwierdzenia
/ .podsumowanie i bots.crm_calc. Logika (co wolno, co się liczy, co blokuje
zapis) mieszka TAM — tutaj tylko marszaling parametrów SDK <-> te moduły.
"""
from typing import List, Optional, TypedDict

from agents import function_tool

from bots import crm_calc

# Osiem kombinacji z VARIANT_CODES. B/B istnieje WYŁĄCZNIE dla dębu — enum
# zamyka to na poziomie schematu, zamiast pozwalać modelowi zgadywać (dawniej
# variant_code('Jesion','Lity','B/B') cicho zwracał None i pozycja wypadała
# z wyceny bez wyraźnego błędu).
WARIANTY = (
    "dab-lity-ab", "dab-lity-bb", "dab-micro-ab", "dab-micro-bb",
    "jes-lity-ab", "jes-micro-ab", "buk-lity-ab", "buk-micro-ab",
)

LITERY_KRAWEDZI = (
    "A", "B", "C", "D",          # góra
    "E", "F", "G", "H",          # dół
    "N1", "N2", "N3", "N4",      # narożniki
    "KG", "KD",                  # obwód (kształt okrągły)
)


class Krawedz(TypedDict):
    """Jedna obróbka krawędzi — kształt WEJŚCIOWY (surowy), zgodny z tym, co
    konsumuje crm_calc.normalize_edges: litera/typ/r/kat. To NIE jest
    znormalizowana postać (r_value/angle_value) — tę liczy dopiero
    bots_pro.stan przy zapisie."""
    litera: str
    typ: str
    r: Optional[int]
    kat: Optional[int]


@function_tool
def pobierz_opcje() -> dict:
    """Zwraca katalog: warianty drewna, wykończenia z identyfikatorami, typy
    krawędzi, limity wymiarowe. Wołaj raz na początku rozmowy o wycenę."""
    return crm_calc.get_options()


@function_tool
def zapisz_pozycje(
    id: str,
    produkt: str = "",
    dlugosc_cm: float = 0,
    szerokosc_cm: float = 0,
    grubosc_cm: float = 0,
    ilosc: int = 0,
    selected_variant: str = "",
    wykonczenie: str = "",
    finishing_option_id: int = 0,
    edges: Optional[List[Krawedz]] = None,
    otwory: Optional[List[str]] = None,
    usun: bool = False,
) -> dict:
    """Zapisuje lub aktualizuje JEDNĄ pozycję wyceny pod stałym identyfikatorem.
    Każdy produkt klienta to osobna pozycja. Wołaj osobno dla każdej zmiany —
    nigdy nie przepisuj całej listy. usun=True usuwa pozycję.

    selected_variant musi być jednym z: dab-lity-ab, dab-lity-bb, dab-micro-ab,
    dab-micro-bb, jes-lity-ab, jes-micro-ab, buk-lity-ab, buk-micro-ab.
    Klasa B/B istnieje wyłącznie dla dębu.

    wykonczenie: "surowe", "olejowane" albo "lakierowane" — bez tego pola
    wyceny nie da się policzyć. Dla "olejowane"/"lakierowane" podaj też
    finishing_option_id (konkretny kolor/połysk z pobierz_opcje).

    edges: obróbka krawędzi tej pozycji, lista {litera, typ, r, kat}. Litery:
    A-D góra, E-H dół, N1-N4 narożniki, KG/KD obwód (kształt okrągły). Typy:
    "round" (zaokrąglenie, promień w mm w polu r, domyślnie 5) i "chamfer"
    (fazowanie, kąt w stopniach w polu kat, domyślnie 45). Podana niepusta
    lista ZASTĘPUJE w całości wcześniejszą obróbkę tej pozycji — podaj komplet
    krawędzi, które mają obowiązywać, nie tylko tę, którą klient zmienia. Gdy
    klient nie wspomina krawędzi, pomiń to pole (domyślne None) — nic się nie
    zmieni. Żeby przywrócić krawędź OSTRĄ (bez obróbki) albo skasować całą
    wcześniej zapisaną obróbkę tej pozycji, podaj jeden wpis z typ="sharp"
    (litera dowolna) — to jedyny sposób na wyczyszczenie, bo pusta lista przy
    typ innym niż "sharp" jest traktowana jak "klient nic nie powiedział".

    otwory: opcjonalna lista opisów wycięć/otworów (po jednym opisie na
    otwór, np. "otwór na zlew 50x40 cm"). NIE są automatycznie wyceniane —
    koszt doliczy konsultant. Podana lista (także pusta) zastępuje poprzednią;
    pomiń pole, żeby jej nie zmieniać."""
    from bots_pro import stan
    return stan.zapisz_pozycje(
        id=id, produkt=produkt, dlugosc_cm=dlugosc_cm, szerokosc_cm=szerokosc_cm,
        grubosc_cm=grubosc_cm, ilosc=ilosc, selected_variant=selected_variant,
        wykonczenie=wykonczenie, finishing_option_id=finishing_option_id or None,
        edges=edges, otwory=otwory, usun=usun,
    )


@function_tool
def policz_wycene() -> dict:
    """Liczy cenę wszystkich zapisanych pozycji w kalkulatorze CRM. Zwraca sumy
    i rozbicie per pozycja. To JEDYNE źródło cen produktu — nigdy nie licz samodzielnie
    i nigdy nie podawaj kwoty, której nie ma w wyniku tego narzędzia."""
    from bots_pro import podsumowanie, stan
    pozycje = stan.pozycje()
    wynik = crm_calc.calculate(pozycje, crm_calc.get_options())
    stan.zapamietaj_kwoty(podsumowanie.kwoty_z_wyniku(pozycje, wynik))   # inwariant I1
    return wynik


@function_tool
def policz_wysylke(kod_pocztowy: str) -> dict:
    """Szacuje koszt kuriera dla zapisanych pozycji. Kod pocztowy w formacie 00-000.
    To JEDYNE źródło cen dostawy."""
    from bots_pro import stan
    wynik = crm_calc.shipping_quote(stan.pozycje(), kod_pocztowy)
    stan.zapamietaj_kwoty(
        wynik[pole] for pole in ("shipping_netto", "shipping_brutto")
        if isinstance(wynik.get(pole), (int, float)))
    return wynik


@function_tool
def znajdz_klienta(email: str = "", telefon: str = "", imie: str = "") -> dict:
    """Znajduje lub zakłada klienta w CRM. Wołaj dopiero PO przygotowaniu wyceny."""
    from bots_pro import stan
    return crm_calc.find_or_create_client(
        email or None, telefon or None, imie or None,
        client_number="chat-%s" % stan.conv_id(),
    )


@function_tool
def wyslij_podsumowanie() -> dict:
    """Wysyła klientowi podsumowanie danych do wyceny WRAZ Z CENĄ i prosi o potwierdzenie.
    Treść składa system — Twoje pole odpowiedzi może zostać puste.
    Wołaj, gdy masz komplet danych. Bez potwierdzenia klienta NIE MOŻESZ zapisać wyceny
    ani podać linku do zamówienia."""
    from bots_pro import podsumowanie
    return podsumowanie.wyslij()


@function_tool
def potwierdz(cytat_klienta: str) -> dict:
    """Rejestruje zgodę klienta na wysłane podsumowanie.

    cytat_klienta — DOSŁOWNY fragment ostatniej wiadomości klienta, w którym się zgadza
    (np. 'tak, zgadza się'). Narzędzie odrzuci cytat, którego w niej nie ma.
    Nie wołaj tego narzędzia, jeśli klient o coś pyta albo coś poprawia."""
    from bots_pro import potwierdzenia
    return potwierdzenia.potwierdz(cytat_klienta)


@function_tool
def zapisz_wycene(client_id: int, notatka: str = "") -> dict:
    """Zapisuje wycenę w CRM i zwraca jej numer oraz publiczny link dla klienta.
    Wymaga wcześniejszego potwierdzenia klienta — bez niego odmówi."""
    from bots_pro import potwierdzenia, stan
    bramka = potwierdzenia.sprawdz_bramke()
    if not bramka["ok"]:
        return bramka
    return crm_calc.create_quote(stan.pozycje(), crm_calc.get_options(),
                                 client_id, notes=notatka)


@function_tool
def popraw_wycene(edit_uuid: str, notatka: str = "") -> dict:
    """Nadpisuje wcześniej zapisaną wycenę aktualnym stanem pozycji."""
    from bots_pro import stan
    return crm_calc.update_quote(edit_uuid, stan.pozycje(),
                                 crm_calc.get_options(), notes=notatka)


@function_tool
def przygotuj_zamowienie(edit_uuid: str) -> dict:
    """Zwraca link do strony, na której klient domknie zamówienie.
    Wołaj dopiero po zapisaniu wyceny i po tym, jak klient wyrazi chęć zamówienia.
    Wymaga aktualnego potwierdzenia klienta — bez niego odmówi."""
    from bots_pro import potwierdzenia, stan
    bramka = potwierdzenia.sprawdz_bramke()
    if not bramka["ok"]:
        return bramka
    return stan.link_do_checkoutu(edit_uuid)


@function_tool
def oddaj_czlowiekowi(powod: str) -> dict:
    """Przekazuje rozmowę konsultantowi. Wołaj gdy: klient prosi o człowieka,
    sprawa jest indywidualna (reklamacja, status zamówienia, faktura, zwrot),
    pytanie wykracza poza bazę wiedzy, albo schody są nietypowe
    (kręcone, zabiegowe, trapezowe, z łukiem, policzki, wymiary ze zdjęcia)."""
    from bots_pro import stan
    return stan.handoff(powod)


NARZEDZIA_WYCENY = [
    pobierz_opcje, zapisz_pozycje, policz_wycene, policz_wysylke,
    wyslij_podsumowanie, potwierdz,
    znajdz_klienta, zapisz_wycene, popraw_wycene,
    przygotuj_zamowienie, oddaj_czlowiekowi,
]
