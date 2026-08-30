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
from typing import List, Literal, Optional, TypedDict

from agents import function_tool

from bots import crm_calc

# Osiem kombinacji z VARIANT_CODES. B/B istnieje WYŁĄCZNIE dla dębu.
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

# Literal zbudowany z WARIANTY/LITERY_KRAWEDZI zamiast osobno wypisanych stałych
# (runda poprawek 1, W2): to one są teraz jedynym źródłem prawdy dla enumu w
# JSON Schema narzędzia — inaczej wcześniejsze WARIANTY/LITERY_KRAWEDZI martwo
# leżały obok zwykłego `str` w podpisie zapisz_pozycje, więc `jes-lity-bb` dało
# się wyrazić i kończyło ciche `braki` -> `WYCENA_NIEUDANA`, zamiast być
# niewyrażalne na poziomie schematu, jak zakładał komentarz sprzed poprawki.
# "" domyka enum o wartość sentinel "pole pominięte w tej turze" (patrz
# stan.zapisz_pozycje — pusty string nie kasuje wcześniej ustalonej wartości).
SelectedVariant = Literal[("",) + WARIANTY]
Litera = Literal[LITERY_KRAWEDZI]
TypKrawedzi = Literal["round", "chamfer", "sharp"]
Wykonczenie = Literal["", "surowe", "olejowane", "lakierowane"]


class Krawedz(TypedDict):
    """Jedna obróbka krawędzi — kształt WEJŚCIOWY (surowy), zgodny z tym, co
    konsumuje crm_calc.normalize_edges: litera/typ/r/kat. To NIE jest
    znormalizowana postać (r_value/angle_value) — tę liczy dopiero
    bots_pro.stan przy zapisie."""
    litera: Litera
    typ: TypKrawedzi
    r: Optional[int]
    kat: Optional[int]


@function_tool
def pobierz_opcje() -> dict:
    """Zwraca listę wykończeń z identyfikatorami (finishing_options: id +
    full_path) oraz globalne limity wymiarowe (global_limits). Wołaj raz na
    początku rozmowy o wycenę, żeby poznać finishing_option_id pasujące do
    wyboru klienta przy olejowaniu/lakierowaniu.

    Warianty drewna i typy/litery krawędzi NIE są tu zwracane — to enumy w
    schemacie zapisz_pozycje (SelectedVariant, Litera, TypKrawedzi), model ma
    je już w podpisie narzędzia i SDK odrzuci wartość spoza listy, zanim
    ciało narzędzia się uruchomi. Katalog kolorów/połysków (finishing_options)
    enumem NIE jest — jest danymi, więc został tutaj."""
    dane = crm_calc.get_options()
    return {
        "finishing_options": [
            {"id": o["id"], "full_path": o["full_path"]}
            for o in (dane.get("finishing_options") or [])
        ],
        "global_limits": dane.get("global_limits"),
    }


@function_tool
def zapisz_pozycje(
    id: str,
    produkt: str = "",
    dlugosc_cm: float = 0,
    szerokosc_cm: float = 0,
    grubosc_cm: float = 0,
    ilosc: int = 0,
    selected_variant: SelectedVariant = "",
    wykonczenie: Wykonczenie = "",
    finishing_option_id: int = 0,
    edges: Optional[List[Krawedz]] = None,
    otwory: Optional[List[str]] = None,
    usun: bool = False,
) -> dict:
    """Zapisuje lub aktualizuje JEDNĄ pozycję wyceny pod stałym identyfikatorem.
    Każdy produkt klienta to osobna pozycja. Wołaj osobno dla każdej zmiany —
    nigdy nie przepisuj całej listy. usun=True usuwa pozycję.

    selected_variant: klasa B/B istnieje wyłącznie dla dębu (dab-lity-bb,
    dab-micro-bb) — dla jesionu i buku dostępne jest tylko *-ab.

    wykonczenie: "surowe", "olejowane" albo "lakierowane" — bez tego pola
    wyceny nie da się policzyć. Dla "olejowane"/"lakierowane" podaj też
    finishing_option_id (konkretny kolor/połysk z pobierz_opcje) W TYM SAMYM
    wywołaniu — przy KAŻDEJ zmianie wykończenia ustaw NOWY finishing_option_id
    pasujący do nowego wyboru, nie zostawiaj starego. Ustawienie "surowe" SAMO
    czyści wcześniej zapisany finishing_option_id (surowe drewno nie ma
    koloru/połysku) — nie musisz nic dodatkowo kasować.

    edges: obróbka krawędzi tej pozycji, lista {litera, typ, r, kat}. KAŻDY
    wpis MUSI mieć WSZYSTKIE CZTERY pola — pominięcie któregokolwiek (nawet
    nieużywanego w tym wpisie) odrzuca całe wywołanie z błędem. Pole, które
    nie dotyczy danego typu, ustaw na null (nie pomijaj klucza): dla "round"
    ustaw kat=null, dla "chamfer" ustaw r=null, dla "sharp" ustaw oba na null.
    Litery: A-D góra, E-H dół, N1-N4 narożniki, KG/KD obwód (kształt
    okrągły). Typy: "round" (zaokrąglenie — promień w mm w polu r; null daje
    domyślne 5 mm) i "chamfer" (fazowanie — kąt w stopniach w polu kat; null
    daje domyślne 45°). Lista ZASTĘPUJE w całości wcześniejszą obróbkę tej
    pozycji, NIGDY nie łączy się z nią po literze — podaj w JEDNYM wywołaniu
    KOMPLET krawędzi, które mają obowiązywać (także te ustalone wcześniej,
    które klient chce zachować), nie tylko tę, którą właśnie zmienia. Gdy
    klient nie wspomina krawędzi wcale, pomiń CAŁE pole edges (domyślne
    None) — nic się nie zmieni.

    "sharp" (ostra) ma DWA różne skutki zależnie od tego, co jeszcze jest w
    liście w tym samym wywołaniu: wymieszany z innymi realnymi wpisami
    (round/chamfer) po prostu znika z zapisanego wyniku, a reszta się
    zapisuje — więc "A ostra, B zostaw R5" wymaga podania OBU wpisów w jednej
    liście: [{litera: A, typ: sharp, r: null, kat: null}, {litera: B,
    typ: round, r: 5, kat: null}]. Lista zawierająca WYŁĄCZNIE wpis(y)
    "sharp" (nic poza tym) KASUJE CAŁĄ dotychczasową obróbkę tej pozycji —
    to jedyny sposób na całkowite wyczyszczenie krawędzi.

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
    i rozbicie per pozycja — WYŁĄCZNIE dla wariantu wybranego w każdej pozycji
    (selected_variant), nie dla wszystkich wariantów drewna z katalogu. To
    JEDYNE źródło cen produktu — nigdy nie licz samodzielnie i nigdy nie
    podawaj kwoty, której nie ma w wyniku tego narzędzia. Wołaj za każdym
    razem, gdy klient ustalił/zmienił dane pozycji i chcesz poznać albo
    zaktualizować cenę — także kilka razy w jednej rozmowie."""
    from bots_pro import podsumowanie, stan
    pozycje = stan.pozycje()
    wynik = crm_calc.calculate(pozycje, crm_calc.get_options())
    stan.zapamietaj_kwoty(podsumowanie.kwoty_z_wyniku(pozycje, wynik))   # inwariant I1
    return podsumowanie.wynik_dla_modelu(pozycje, wynik)


@function_tool
def policz_wysylke(kod_pocztowy: str) -> dict:
    """Szacuje koszt kuriera dla zapisanych pozycji. Kod pocztowy w formacie
    00-000. To JEDYNE źródło cen dostawy. Wołaj dopiero gdy klient już zna
    cenę produktu (po policz_wycene) i poda kod pocztowy odbiorcy.

    Gdy nie znaleziono kuriera dla gabarytu (carriers=0), wynik NIE ma pól
    carrier_name/shipping_netto/shipping_brutto wcale (nie ma ich w JSON-ie,
    nie są ustawione na null) — to znaczy, że wysyłki NIE dało się oszacować,
    NIE że jest gratis. Nie mów wtedy klientowi, że wysyłka jest darmowa —
    zaproponuj kontakt z konsultantem."""
    from bots_pro import stan
    wynik = crm_calc.shipping_quote(stan.pozycje(), kod_pocztowy)
    stan.zapamietaj_kwoty(
        wynik[pole] for pole in ("shipping_netto", "shipping_brutto")
        if isinstance(wynik.get(pole), (int, float)))
    if not wynik.get("ok"):
        return wynik
    # crm_calc.shipping_quote niesie też raw_netto/raw_brutto — cenę kuriera
    # SPRZED narzutu na pakowanie (PACKING_MULTIPLIER) — to PRAWDZIWE liczby,
    # których rejestr powyżej NIE zna (rejestrujemy tylko shipping_netto/
    # brutto, bo to one trafiają do wyceny). Bez przycięcia bot cytujący
    # raw_* zostałby przez G1 oskarżony o halucynację mimo że liczba pochodzi
    # z wyniku WŁASNEGO wywołania tego narzędzia (W3, runda poprawek 1).
    #
    # Klucze o wartości None POMIJAMY (nie wpisujemy jawnego null) — runda
    # poprawek 2, N2: jawne "shipping_netto": null wygląda inaczej niż brak
    # klucza sprzed tej poprawki i model mógłby odczytać null jako "0 zł/
    # gratis" zamiast "nie udało się oszacować". Brak klucza jest jednoznaczny
    # razem z carriers=0 (patrz docstring wyżej).
    surowy = {
        "ok": True,
        "carriers": wynik.get("carriers"),
        "carrier_name": wynik.get("carrier_name"),
        "shipping_netto": wynik.get("shipping_netto"),
        "shipping_brutto": wynik.get("shipping_brutto"),
    }
    return {k: v for k, v in surowy.items() if v is not None}


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
    Wołaj WYŁĄCZNIE gdy klient jednoznacznie potwierdza treść PRAWDZIWIE wysłanego
    podsumowania (wyslij_podsumowanie) — nie wołaj go, jeśli klient o coś pyta,
    coś poprawia, albo potwierdza coś innego niż samą wycenę."""
    from bots_pro import potwierdzenia
    return potwierdzenia.potwierdz(cytat_klienta)


@function_tool
def zapisz_wycene(client_id: int, notatka: str = "") -> dict:
    """Zapisuje wycenę w CRM i zwraca jej numer oraz publiczny link dla klienta.
    Wymaga wcześniejszego potwierdzenia klienta — bez niego odmówi. Wołaj RAZ,
    zaraz po tym, jak klient potwierdzi podsumowanie (potwierdz) i masz jego
    client_id (ze znajdz_klienta). Kolejne zmiany tej samej wyceny rób przez
    popraw_wycene, nie przez ponowne wołanie tego narzędzia — inaczej w CRM
    powstanie druga, zbędna wycena dla tej samej rozmowy."""
    from bots_pro import potwierdzenia, stan
    bramka = potwierdzenia.sprawdz_bramke()
    if not bramka["ok"]:
        return bramka
    return crm_calc.create_quote(stan.pozycje(), crm_calc.get_options(),
                                 client_id, notes=notatka)


@function_tool
def popraw_wycene(edit_uuid: str, notatka: str = "") -> dict:
    """Nadpisuje wcześniej zapisaną wycenę (zapisz_wycene) aktualnym stanem
    pozycji. Wołaj, gdy dane zmieniają się PO tym, jak wycena już istnieje w
    CRM (np. klient dokłada pozycję albo poprawia wymiar już zapisanego
    zamówienia) — edit_uuid pochodzi z wyniku zapisz_wycene (albo
    poprzedniego popraw_wycene). NIE twórz przez to nowej wyceny wywołaniem
    zapisz_wycene — to zdublowałoby wycenę w CRM zamiast ją zaktualizować.
    Wymaga aktualnego potwierdzenia klienta — bez niego odmówi: to zmiana
    danych, które klient zobaczy pod już wysłanym linkiem, więc wymaga tego
    samego potwierdzenia co pierwszy zapis (wyślij nowe podsumowanie przez
    wyslij_podsumowanie i poczekaj na potwierdz, zanim wywołasz to narzędzie)."""
    from bots_pro import potwierdzenia, stan
    bramka = potwierdzenia.sprawdz_bramke()
    if not bramka["ok"]:
        return bramka
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
