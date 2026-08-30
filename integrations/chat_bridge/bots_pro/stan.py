# -*- coding: utf-8 -*-
"""
Stan rozmowy Dębusia Pro.

Historia rozmowy idzie przez SQLiteSession Agents SDK — tutaj trzymamy
wyłącznie to, co jest DECYZJĄ BIZNESOWĄ, a nie odtwarzalnym przebiegiem:
identyfikator zapisanej wyceny, dane kontaktowe, fakt podania ceny.

Znane kwoty (do guardraila G1) zbieramy per tura w contextvar — guardrail
sprawdza odpowiedź zanim opuści proces.
"""
import contextvars
import json

from core.db import db

_conv_id = contextvars.ContextVar("conv_id", default=None)
_kwoty = contextvars.ContextVar("kwoty", default=None)
_persona = contextvars.ContextVar("persona", default=None)

_SCHEMAT = """
CREATE TABLE IF NOT EXISTS pro_dane(
  conv_id INTEGER PRIMARY KEY, dane_json TEXT);
CREATE TABLE IF NOT EXISTS pro_stan(
  conv_id INTEGER PRIMARY KEY,
  quote_edit_uuid TEXT, quote_saved INTEGER DEFAULT 0, priced INTEGER DEFAULT 0,
  contact_email TEXT, contact_phone TEXT, contact_name TEXT,
  oczekiwany_podpis TEXT, potwierdzony_podpis TEXT,
  potwierdzenie_cytat TEXT, potwierdzenie_ts REAL);
"""


def init_pro():
    """Tabele stanu Dębusia Pro. Świadomie BEZ kolumn bot_turns, awaiting_*,
    reject_*, sent_images, returning_greeted, human_deflected — przebieg rozmowy
    odtwarza sesja Agents SDK, a te kolumny były księgowaniem tego przebiegu."""
    polaczenie = db()
    try:
        polaczenie.executescript(_SCHEMAT)
        polaczenie.commit()
    finally:
        polaczenie.close()


def ustaw_kontekst(conv_id, persona_tury="pro"):
    """Wołane na początku tury przez worker."""
    _conv_id.set(conv_id)
    _kwoty.set(set())
    _persona.set(persona_tury)


def conv_id():
    return _conv_id.get()


def persona():
    """Persona bieżącej tury (np. 'pro', 'quote_olx', 'quote_allegro') — decyduje
    m.in. o profilu wysyłki w podsumowaniu (bez markdownu na OLX, bez linków na Allegro)."""
    return _persona.get()


def zapamietaj_kwoty(wartosci):
    """Rejestruje kwoty zwrócone przez kalkulator — guardrail porówna z nimi
    treść odpowiedzi. Wartości mogą przyjść jako float (typowo) albo string
    z polskim przecinkiem dziesiętnym — stąd zamiana przed float()."""
    biezace = _kwoty.get()
    if biezace is None:
        biezace = set()
        _kwoty.set(biezace)
    for w in wartosci:
        biezace.add("%.2f" % float(str(w).replace(",", ".")))


def znane_kwoty():
    return set(_kwoty.get() or set())


def _wczytaj():
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT dane_json FROM pro_dane WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return json.loads(wiersz["dane_json"]) if wiersz else {"pozycje": []}


def _zapisz(dane):
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_dane(conv_id, dane_json) VALUES(?,?) "
            "ON CONFLICT(conv_id) DO UPDATE SET dane_json=excluded.dane_json",
            (conv_id(), json.dumps(dane, ensure_ascii=False)))
        polaczenie.commit()
    finally:
        polaczenie.close()


def pozycje():
    """Pozycje wyceny zapisane w tej rozmowie."""
    return _wczytaj().get("pozycje", [])


def _rozloz_wariant(kod):
    """selected_variant (enum bezpieczny dla modelu, np. 'dab-lity-ab') -> (gatunek,
    technologia, klasa) w języku, którego oczekuje bots.crm_calc.build_products.

    NIE rezygnujemy z enuma jako parametru narzędzia — to on chroni model przed
    kombinacją spoza oferty (np. 'jes-lity-bb', której nie ma w VARIANT_CODES).
    Warstwa stanu tłumaczy bezpieczny enum na język kalkulatora, więc obie
    własności (bezpieczeństwo enuma + zgodność z build_products) są zachowane
    naraz, zamiast wybierać jedną kosztem drugiej."""
    from bots.crm_calc import VARIANT_CODES
    cfg = VARIANT_CODES.get(kod)
    if not cfg:
        return None
    return cfg["species"], cfg["technology"], cfg["wood_class"]


def _zastosuj_krawedzie(biezaca, edges):
    """Krawędzie są POZA generyczną pętlą pól — jak w starym silniku (patrz
    bots/quotebot.py, komentarz przy _merge_dane: "Krawedzie — poza
    _merge_pola. Znormalizowana niepusta lista (round/chamfer) zastepuje.").

    Znormalizowana niepusta lista ZASTĘPUJE w całości wcześniejszą obróbkę tej
    pozycji — model podaje komplet krawędzi, które mają obowiązywać, nie tylko
    zmienianą literę. Jawne "sharp" (ostra) w którymś wpisie to sygnał
    USUNIĘCIA całej wcześniej zapisanej obróbki: crm_calc.normalize_edges
    milcząco POMIJA wpisy "sharp" (dla niej to "brak obróbki", nie osobna
    wartość do zapisania), więc bez tej odrębnej ścieżki intencja klienta
    "chcę ostre, bez fazowania" ginęłaby, a stara obróbka zostawałaby
    w pozycji na zawsze. `edges=None` (model nic nie powiedział o krawędziach
    w tej turze) NIE kasuje — nie trzeba ich powtarzać co turę."""
    from bots.crm_calc import normalize_edges, raw_ma_sharp
    if edges is None:
        return
    znormalizowane = normalize_edges(edges)
    if znormalizowane:
        biezaca["edges"] = znormalizowane
    elif raw_ma_sharp(edges):
        biezaca["edges"] = []


def zapisz_pozycje(id, produkt="", dlugosc_cm=0, szerokosc_cm=0, grubosc_cm=0,
                   ilosc=0, selected_variant="", finishing_option_id=None,
                   wykonczenie="", edges=None, otwory=None, usun=False):
    """Wstawia albo aktualizuje JEDNĄ pozycję pod stałym identyfikatorem.
    Puste pola nie kasują wcześniej ustalonych wartości — model woła to
    narzędzie raz na zmianę, a nie przepisuje całej listy.

    `selected_variant` jest dodatkowo rozkładany na gatunek/technologia/klasa
    (patrz `_rozloz_wariant`) — bez tego crm_calc.build_products nie rozpozna
    pozycji (czyta te trzy pola osobno, nie kod wariantu) i KAŻDA wycena
    kończyłaby się `WYCENA_NIEUDANA`, niezależnie od tego, co wybrał klient.

    `edges` i `otwory` mają WŁASNĄ semantykę zapisu, inną niż reszta pól —
    patrz `_zastosuj_krawedzie` (edges) i sekcję niżej (otwory). `wykonczenie
    == "surowe"` dodatkowo czyści `finishing_id` — patrz komentarz przy tym
    warunku (W1, runda poprawek 1)."""
    dane = _wczytaj()
    pozycje = dane.setdefault("pozycje", [])
    biezaca = next((p for p in pozycje if p.get("id") == id), None)

    if usun:
        dane["pozycje"] = [p for p in pozycje if p.get("id") != id]
        _zapisz(dane)
        return {"ok": True, "usunieto": id}

    if biezaca is None:
        biezaca = {"id": id}
        pozycje.append(biezaca)

    for pole, wartosc in (
        ("produkt", produkt), ("dlugosc", dlugosc_cm), ("szerokosc", szerokosc_cm),
        ("grubosc", grubosc_cm), ("ilosc", ilosc),
        ("selected_variant", selected_variant), ("finishing_id", finishing_option_id),
        ("wykonczenie", wykonczenie),
    ):
        if wartosc not in ("", 0, None):
            biezaca[pole] = wartosc

    if selected_variant:
        rozlozony = _rozloz_wariant(selected_variant)
        if rozlozony:
            biezaca["gatunek"], biezaca["technologia"], biezaca["klasa"] = rozlozony

    if wykonczenie == "surowe":
        # "surowe" = brak wykończenia -> finishing_id staje się bez znaczenia
        # dla WYCENY (crm_calc.build_products/_finish_type ignoruje go, gdy
        # ftype == "Surowe") — ale bez jawnego wyczyszczenia zostawałby w
        # pozycji jako duch: podsumowanie (i podpis potwierdzenia) pokazywałyby
        # KOLOR/POŁYSK sprzed zmiany na "surowe", mimo że wycena go już nie
        # liczy (W1, runda poprawek 1 — ta sama klasa błędu co W5 z poprzedniej
        # rundy, tylko odwrócona: tam klient widział MNIEJ niż podpisywał, tu
        # widziałby CO INNEGO). `finishing_option_id` samo w sobie NIE ma
        # sposobu na wyczyszczenie (0 -> None -> pole pomijane w pętli wyżej,
        # patrz bots_pro/narzedzia.py:zapisz_pozycje) — czyszczenie musi więc
        # być automatyczne, wywołane samą zmianą wykończenia na "surowe".
        biezaca.pop("finishing_id", None)

    _zastosuj_krawedzie(biezaca, edges)

    # Otwory/wycięcia: opisowa lista, NIE wyceniana automatycznie (koszt
    # dolicza konsultant — jak w starym silniku, bots/quotebot.py: "OTWORY/
    # WYCIĘCIA: NIE wyceniasz"). Podana lista (także pusta — jawne
    # "klient zrezygnował") ZASTĘPUJE poprzednią; `otwory=None` (pole
    # pominięte w tej turze) niczego nie zmienia.
    if otwory is not None:
        biezaca["otwory"] = list(otwory)

    _zapisz(dane)
    return {"ok": True, "pozycja": biezaca}


def zapisz_stan(**kolumny):
    """Upsert dowolnych kolumn `pro_stan` dla bieżącej rozmowy — jedyne miejsce,
    które pisze do tej tabeli. `potwierdzenia.py` i `podsumowanie.py` wołają to
    zamiast dublować własny UPSERT do cudzej tabeli (tabela rozjeżdża się przy
    pierwszej zmianie schematu, tak jak groziło to podwójnemu odczytowi pozycji
    przed poprawką w tym module)."""
    if not kolumny:
        return
    nazwy = list(kolumny)
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, %s) VALUES(?,%s) "
            "ON CONFLICT(conv_id) DO UPDATE SET %s" % (
                ",".join(nazwy), ",".join("?" * len(nazwy)),
                ",".join("%s=excluded.%s" % (n, n) for n in nazwy)),
            tuple([conv_id()] + [kolumny[n] for n in nazwy]))
        polaczenie.commit()
    finally:
        polaczenie.close()


def handoff(powod):
    """Oddaje rozmowę konsultantowi. Token bota Pro przekazujemy JAWNIE —
    domyślny cw_bot_handoff sięga po token bota-podpowiadacza."""
    from config import BOT_PRO_CW_AGENT_TOKEN
    from core.chatwoot import cw_bot_handoff
    udane = cw_bot_handoff(conv_id(), token=BOT_PRO_CW_AGENT_TOKEN)
    return {"ok": bool(udane), "powod": powod}


def link_do_checkoutu(edit_uuid):
    """Publiczny link, pod którym klient domknie zamówienie i zapłaci."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT quote_edit_uuid FROM pro_stan WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    uuid_wyceny = edit_uuid or (wiersz["quote_edit_uuid"] if wiersz else None)
    if not uuid_wyceny:
        return {"ok": False, "error": "Brak zapisanej wyceny — najpierw ją zapisz."}
    return {"ok": True, "edit_uuid": uuid_wyceny}


def ostatnia_wiadomosc_klienta():
    """Treść ostatniej wiadomości przychodzącej — materiał do weryfikacji cytatu."""
    from config import BOT_HISTORY_LIMIT
    from core.chatwoot import cw_messages
    for wiadomosc in reversed(cw_messages(conv_id(), BOT_HISTORY_LIMIT) or []):
        if wiadomosc.get("role") == "user":
            return wiadomosc.get("text") or ""
    return ""
