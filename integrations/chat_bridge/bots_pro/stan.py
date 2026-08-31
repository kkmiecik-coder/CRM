# -*- coding: utf-8 -*-
"""
Stan rozmowy Dębusia Pro.

Historia rozmowy idzie przez SQLiteSession Agents SDK — tutaj trzymamy
wyłącznie to, co jest DECYZJĄ BIZNESOWĄ, a nie odtwarzalnym przebiegiem:
identyfikator zapisanej wyceny, dane kontaktowe, fakt podania ceny.

Znane kwoty (do guardraila G1) zbieramy w `pro_stan`, TRWALE PER ROZMOWA — nie
per tura (Task 8, B1). Pierwsza wersja trzymała je w contextvar zerowanym na
starcie KAŻDEJ tury (`ustaw_kontekst` -> `_kwoty.set(set())`) — to działało w
JEDNEJ turze (np. `policz_wycene` rejestruje, `wyslij_podsumowanie` cytuje w tej
samej turze), ale pękało na granicy DWÓCH tur: klient potwierdza w turze N+1,
model woła `potwierdz` -> `znajdz_klienta` -> `zapisz_wycene` i naturalnie pisze
"wycena na 1936,71 zł zapisana" — `zapisz_wycene` NIE zasila rejestru (nie musi,
tylko cytuje już ustaloną cenę), a rejestr TEJ tury jest pusty, bo zerowany na
starcie. Guardrail uznawał więc PRAWDZIWĄ cenę za halucynację, w momencie
udanego zamknięcia sprzedaży. Przechowanie w `pro_stan` (kluczowane po conv_id,
jak reszta tego modułu) usuwa problem u źródła: rejestr żyje tak długo jak
rozmowa, nie jak pojedyncza tura, i — dzięki kluczowaniu po conv_id — NIE
przecieka między różnymi rozmowami (patrz TestKwoty w test_pro_stan.py).
Usuwa to też ryzyko z poprzedniej wersji (B3): `zapamietaj_kwoty` mutowała
WSPÓLNY set z contextvara i TYLKO DZIĘKI TEJ MUTACJI kwoty w ogóle propagowały
z kontekstu narzędzia do tury — gałąź `if biezace is None: _kwoty.set(nowy_set)`
w SKOPIOWANYM kontekście (np. inny wątek/task asyncio) zgubiłaby je PO CICHU,
z fałszywym alarmem guardraila jako jedynym objawem. Zapis do bazy nie ma tej
klasy błędu — nie ma kontekstu do skopiowania.

Analogicznie, fakt wysłania deterministycznego podsumowania (`podsumowanie.wyslij`)
zbieramy per tura w OSOBNYM contextvarze — `tura.py` sprawdza go PO Runner.run_sync,
żeby nie wysłać klientowi DRUGIEGO, tym razem sparafrazowanego przez model,
podsumowania w tej samej turze (patrz komentarz w podsumowanie.py przy `wyslij()`:
model dostaje wskazówkę zostawić `final_output` puste, ale to dyscyplina promptu,
nie bramka — bramka jest tutaj)."""
import contextvars
import json

from core.db import db

_conv_id = contextvars.ContextVar("conv_id", default=None)
_persona = contextvars.ContextVar("persona", default=None)
_podsumowanie_wyslane = contextvars.ContextVar("podsumowanie_wyslane", default=False)

_SCHEMAT = """
CREATE TABLE IF NOT EXISTS pro_dane(
  conv_id INTEGER PRIMARY KEY, dane_json TEXT);
CREATE TABLE IF NOT EXISTS pro_stan(
  conv_id INTEGER PRIMARY KEY,
  quote_edit_uuid TEXT, quote_saved INTEGER DEFAULT 0, priced INTEGER DEFAULT 0,
  contact_email TEXT, contact_phone TEXT, contact_name TEXT,
  oczekiwany_podpis TEXT, potwierdzony_podpis TEXT,
  potwierdzenie_cytat TEXT, potwierdzenie_ts REAL,
  czlowiek_odezwal_sie INTEGER DEFAULT 0,
  znane_kwoty_json TEXT,
  tury_rozmowy INTEGER DEFAULT 0, tury_bez_postepu INTEGER DEFAULT 0);
"""


def init_pro():
    """Tabele stanu Dębusia Pro. Świadomie BEZ kolumn bot_turns, awaiting_*,
    reject_*, sent_images, returning_greeted, human_deflected — przebieg rozmowy
    odtwarza sesja Agents SDK, a te kolumny były księgowaniem tego przebiegu.

    `czlowiek_odezwal_sie` (N2, code review runda 2), `znane_kwoty_json` (Task 8,
    B1) i `tury_rozmowy`/`tury_bez_postepu` (Task 8, B2) dołożone ALTER-em osobno —
    `CREATE TABLE IF NOT EXISTS` w `_SCHEMAT` nie doda kolumny do tabeli, która
    już istnieje z wdrożeń sprzed tej zmiany (ten sam wzorzec co w core/db.py)."""
    polaczenie = db()
    try:
        polaczenie.executescript(_SCHEMAT)
        for stmt in (
            "ALTER TABLE pro_stan ADD COLUMN czlowiek_odezwal_sie INTEGER DEFAULT 0",
            "ALTER TABLE pro_stan ADD COLUMN znane_kwoty_json TEXT",
            "ALTER TABLE pro_stan ADD COLUMN tury_rozmowy INTEGER DEFAULT 0",
            "ALTER TABLE pro_stan ADD COLUMN tury_bez_postepu INTEGER DEFAULT 0",
        ):
            try:
                polaczenie.execute(stmt)
            except Exception:
                pass
        polaczenie.commit()
    finally:
        polaczenie.close()


def ustaw_kontekst(conv_id, persona_tury="pro"):
    """Wołane na początku tury przez worker.

    Świadomie NIE zeruje rejestru kwot (Task 8, B1) — ten żyje w `pro_stan`,
    trwale per ROZMOWA (conv_id), nie per tura. Zerowanie go tutaj byłoby
    dokładnie tym błędem, który B1 naprawia: cena ustalona w tej rozmowie w
    poprzedniej turze ma zostać znana guardrailowi także w kolejnych turach tej
    samej rozmowy — patrz docstring modułu i TestKwoty w test_pro_stan.py."""
    _conv_id.set(conv_id)
    _persona.set(persona_tury)
    _podsumowanie_wyslane.set(False)


def conv_id():
    return _conv_id.get()


def persona():
    """Persona bieżącej tury (np. 'pro', 'quote_olx', 'quote_allegro') — decyduje
    m.in. o profilu wysyłki w podsumowaniu (bez markdownu na OLX, bez linków na Allegro)."""
    return _persona.get()


def oznacz_podsumowanie_wyslane():
    """Wołane WYŁĄCZNIE przez `podsumowanie.wyslij()`, zaraz po tym, jak sam wyśle
    deterministyczne podsumowanie do klienta. `tura.py` czyta to niżej
    (`podsumowanie_wyslane`), żeby nie wysłać jeszcze jednej wiadomości w tej
    samej turze — nawet jeśli model coś dopisał, a guardrail G1 (integralność
    ceny) by to przepuścił (bo dopiska nie musi mieć ceny, żeby był problemem —
    problemem jest DRUGIE podsumowanie własnymi słowami modelu tuż po pierwszym,
    deterministycznym)."""
    _podsumowanie_wyslane.set(True)


def podsumowanie_wyslane():
    """Czy w BIEŻĄCEJ turze już wysłano deterministyczne podsumowanie."""
    return bool(_podsumowanie_wyslane.get())


def zapamietaj_kwoty(wartosci):
    """Rejestruje kwoty zwrócone przez kalkulator — guardrail porówna z nimi
    treść odpowiedzi. Wartości mogą przyjść jako float (typowo) albo string
    z polskim przecinkiem dziesiętnym — stąd zamiana przed float().

    Trwały zapis w `pro_stan` (Task 8, B1), nie contextvar — patrz docstring
    modułu. Read-modify-write na tym samym połączeniu: w obrębie jednej tury to
    wystarcza (worker przetwarza rozmowy kolejno per conv_id, patrz
    quote_worker.py — API-06), a to jedyne miejsce, które w ogóle PISZE do
    `znane_kwoty_json`, więc nie ma z czym się ścigać."""
    biezace = znane_kwoty()
    for w in wartosci:
        biezace.add("%.2f" % float(str(w).replace(",", ".")))
    zapisz_stan(znane_kwoty_json=json.dumps(sorted(biezace)))


def znane_kwoty():
    """Kwoty znane guardrailowi G1 dla BIEŻĄCEJ rozmowy (conv_id z kontekstu) —
    zbiór trwa przez całą rozmowę, nie tylko bieżącą turę (patrz docstring modułu)."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT znane_kwoty_json FROM pro_stan WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    if not wiersz or not wiersz["znane_kwoty_json"]:
        return set()
    return set(json.loads(wiersz["znane_kwoty_json"]))


def zarejestruj_ture():
    """Inkrementuje licznik TUR CAŁEJ ROZMOWY (Task 8, B2) — NIE mylić z
    BOT_PRO_MAX_RUNNER_STEPS (limit iteracji narzędzie->model WEWNĄTRZ jednej
    tury, config.py). Wołane RAZ, na samym początku `tura.uruchom`, dla KAŻDEJ
    tury, w której bot faktycznie działa (a więc już PO bramce ciszy
    `wolno_prowadzic_rozmowe` — tura, w której bot milczy, nie zużywa budżetu).
    Zwraca nową wartość licznika PO inkrementacji."""
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, tury_rozmowy) VALUES(?, 1) "
            "ON CONFLICT(conv_id) DO UPDATE SET tury_rozmowy = tury_rozmowy + 1",
            (conv_id(),))
        polaczenie.commit()
        wiersz = polaczenie.execute(
            "SELECT tury_rozmowy FROM pro_stan WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["tury_rozmowy"]


def migawka_postepu():
    """Odcisk stanu BIZNESOWEGO bieżącej rozmowy — do wykrywania braku postępu
    między turami (Task 8, B2). Obejmuje zapisane pozycje (`pro_dane`) ORAZ
    kolumny `pro_stan`, które zmieniają się WYŁĄCZNIE w wyniku realnej decyzji
    (znana kwota z kalkulatora, wysłane podsumowanie, potwierdzenie klienta,
    zapisana wycena) — celowo BEZ `tury_rozmowy`/`tury_bez_postepu` (te zmieniają
    się co turę z definicji, więc wliczenie ich do odcisku zawsze pokazywałoby
    "postęp" i bezpiecznik nigdy by się nie uruchomił).

    Porównanie odcisku SPRZED i PO turze (w `tura.uruchom`) wykrywa postęp
    niezależnie od tego, KTÓRE konkretne narzędzie go spowodowało — odporne na
    nowe narzędzia zmieniające stan dodane w przyszłości bez aktualizacji tej
    funkcji, w odróżnieniu od ręcznie utrzymywanej listy nazw narzędzi."""
    polaczenie = db()
    try:
        wiersz_stanu = polaczenie.execute(
            "SELECT quote_edit_uuid, quote_saved, oczekiwany_podpis, potwierdzony_podpis, "
            "potwierdzenie_cytat, znane_kwoty_json FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
        wiersz_pozycji = polaczenie.execute(
            "SELECT dane_json FROM pro_dane WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return json.dumps({
        "stan": dict(wiersz_stanu) if wiersz_stanu else None,
        "pozycje": wiersz_pozycji["dane_json"] if wiersz_pozycji else None,
    }, sort_keys=True, ensure_ascii=False)


def zarejestruj_brak_postepu():
    """Inkrementuje licznik KOLEJNYCH tur BEZ ŻADNEJ zmiany stanu biznesowego
    (patrz `migawka_postepu`). Zwraca nową wartość licznika PO inkrementacji."""
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, tury_bez_postepu) VALUES(?, 1) "
            "ON CONFLICT(conv_id) DO UPDATE SET tury_bez_postepu = tury_bez_postepu + 1",
            (conv_id(),))
        polaczenie.commit()
        wiersz = polaczenie.execute(
            "SELECT tury_bez_postepu FROM pro_stan WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["tury_bez_postepu"]


def zresetuj_brak_postepu():
    """Wołane, gdy tura ZROBIŁA realny postęp — zeruje licznik z
    `zarejestruj_brak_postepu`, żeby kolejna seria bezczynności liczyła się od nowa."""
    zapisz_stan(tury_bez_postepu=0)


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

    from bots.crm_calc import _finish_type
    if _finish_type(wykonczenie) == "Surowe":
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
        #
        # Porównanie przez crm_calc._finish_type (podciąg "surow", bez
        # względu na wielkość liter/diakrytyki), NIE `== "surowe"` (runda
        # poprawek 2, N1): to DOKŁADNIE ta sama reguła, którą stosuje wycena
        # (crm_calc.build_products), więc "czyszczę finishing_id" i "wycena
        # ignoruje finishing_id" są zawsze zgodne ze sobą — dwa niezależne
        # porównania tego samego tekstu łatwo rozjeżdżają się przy literówce/
        # innej pisowni. Dziś enum narzędzia (Wykonczenie) wysyła wyłącznie
        # dokładne "surowe", więc luka jest nieosiągalna PRZEZ NARZĘDZIE —
        # ale to samo dotyczyło W2 dla selected_variant, więc obrona ma
        # działać niezależnie od enumu, nie zamiast niego.
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


class BladOdczytuStanu(Exception):
    """Statusu rozmowy albo jej historii nie dało się odczytać (sieć/Chatwoot) —
    PRZEJŚCIOWY błąd. `.retryable = True` jawnie (nie polegamy na hierarchii
    wyjątków `requests`/`ConnectionError`, która i tak NIE pokrywa np.
    `requests.exceptions.ConnectionError` — ten nie dziedziczy po wbudowanym
    `ConnectionError`), żeby `quote_worker._klasyfikuj_retryable` (Task 7, W3
    code review) zakwalifikowało to jako retry niezależnie od zawężenia dla
    persony bota (K2 code review) — patrz `wolno_prowadzic_rozmowe` niżej."""
    retryable = True


def _czlowiek_juz_sie_odezwal(conv_id):
    """Odczyt sticky-bita (N2, code review runda 2) — NIE przez kontekst `conv_id()`
    (contextvar), bo ta funkcja jest wołana PRZED `stan.ustaw_kontekst` (patrz
    `tura.uruchom`). Konto conv_id idzie więc jawnym parametrem, jak w reszcie
    tego modułu przy podobnych wywołaniach spoza tury (np. `handoff`)."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT czlowiek_odezwal_sie FROM pro_stan WHERE conv_id=?", (conv_id,)).fetchone()
    finally:
        polaczenie.close()
    return bool(wiersz and wiersz["czlowiek_odezwal_sie"])


def _oznacz_czlowiek_odezwal_sie(conv_id):
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, czlowiek_odezwal_sie) VALUES(?, 1) "
            "ON CONFLICT(conv_id) DO UPDATE SET czlowiek_odezwal_sie=1", (conv_id,))
        polaczenie.commit()
    finally:
        polaczenie.close()


def wolno_prowadzic_rozmowe(conv_id):
    """Bramka ciszy po handoffie (Task 7, brief o niej nie wspomina — rozstrzygnięcie
    właściciela zadania; przepisana w rundzie poprawek 1 i 2 po code review —
    K1/W3, potem N2).

    Sam status "pending" NIE wystarcza jako bramka: w Chatwoocie "Oczekująca"
    (pending) to jednocześnie stan startowy (bot jeszcze się nie odezwał) I zwykły
    "snooze" agenta — agent może ręcznie zaparkować rozmowę w pending PO WŁASNEJ
    publicznej odpowiedzi (np. czekając na klienta). Dokładnie to wydarzyło się
    w audycie (rozmowa #1316): agentka odpisała klientowi ("nie robimy naturalnych
    krawędzi"), a godzinę później bot podjął rozmowę od nowa i jej zaprzeczył.
    Stary silnik (bots/quotebot.py:_wolno_prowadzic_rozmowe) ma dokładnie tę lukę
    — sprawdza WYŁĄCZNIE status.

    K1 (code review, runda 1): PIERWSZA wersja tej funkcji sprawdzała, kto napisał
    OSTATNIĄ publiczną wiadomość — ale tura Dębusia Pro jest ZAWSZE wyzwalana
    świeżą wiadomością `incoming` klienta (webhooks.py + okno ciszy w
    quote_intake), więc w momencie sprawdzania bramki ostatnią wiadomością jest
    PRAWIE ZAWSZE wiadomość klienta, niezależnie od tego, czy wcześniej odpisał
    już agent. Warunek "kto mówił ostatni" był więc martwy — sekwencja
    [klient, agent, klient] (dokładnie #1316: agent odpisał, klient napisał
    później) dawała True (bot mówi), mimo że agent już się włączył.

    Poprawka: bramka sprawdza, czy w PUBLICZNEJ historii rozmowy W OGÓLE
    pojawiła się wiadomość człowieka-agenta (sender.type == "user" w Chatwoocie —
    w odróżnieniu od klienta "contact" i samego bota "agent_bot"), niezależnie od
    pozycji w historii i niezależnie od ewentualnych wiadomości `activity`
    (systemowych, bez sender) między nią a wiadomością wyzwalającą. Gdy human
    KIEDYKOLWIEK odpisał publicznie w tej rozmowie, bot milczy TRWALE (dopóki
    ktoś ręcznie nie przypnie rozmowy z powrotem do bota w Chatwoocie) — to
    świadomie zachowawcze: koszt fałszywego alarmu (bot niepotrzebnie milczy,
    mimo że agent tylko przelotnie coś napisał) jest dużo niższy niż koszt
    #1316 (bot zaprzecza agentowi). Notatki prywatne (private=True) są POMIJANE
    — wewnętrzna notatka między agentami nie jest publiczną odpowiedzią klientowi.

    Zapytanie o historię idzie PRZEZ `core.chatwoot.cw` (surowe wywołanie API),
    NIE przez `cw_messages` — `cw_messages` celowo gubi nadawcę (mapuje tylko
    role user/assistant) i pomija wiadomości z pustą treścią (np. sam załącznik
    obrazu bez tekstu), co ukryłoby realną odpowiedź agenta przed tą bramką.

    W3 (code review, runda 1): błąd odczytu statusu/historii RZUCA
    `BladOdczytuStanu` (retryable=True), NIE zwraca cicho False. Pierwsza wersja
    zwracała False przy błędzie — z punktu widzenia `tura.uruchom` to WYGLĄDA
    identycznie jak legalna blokada (human już rozmawia), więc `quote_worker`
    oznaczał wiersz kolejki jako 'sent' i CICHO GUBIŁ wiadomość klienta przy
    zwykłym, przejściowym błędzie sieci. Rzucanie (jak w starym silniku, ten sam
    powód) oddaje decyzję workerowi: retry z backoffem, a nie zgadywanie tutaj.
    `cw()` sam NIE rzuca na odpowiedź błędu (nie robi `raise_for_status`) — gdy
    ciało błędu sparsuje się jako JSON bez klucza "payload", `.get("payload", [])`
    cicho dałoby `[]` (pusta historia -> bramka pozwala), więc status HTTP jest
    sprawdzany JAWNIE (`r.ok`) przed odczytem `payload`.

    N2 (code review, runda 2): semantyka "czy CZŁOWIEK KIEDYKOLWIEK się odezwał"
    (K1) niejawnie zakłada, że pobrana strona `payload` to CAŁA historia — ale
    endpoint `/messages` jest stronicowany i bez parametru strony zwraca tylko
    najświeższą stronę. Gdy po odpowiedzi agenta narośnie dość kolejnych
    wiadomości KLIENTA (np. kilka dni niecierpliwych ponagleń), odpowiedź agenta
    wypadnie z pobranej strony i bramka wróci na True — bot znów zaprzeczy
    agentowi, dokładnie ten sam błąd co #1316, tylko odroczony w czasie zamiast
    natychmiastowy. Rozwiązanie NIEZALEŻNE od rozmiaru strony: sticky bit
    `czlowiek_odezwal_sie` w `pro_stan`, ustawiany RAZ (`_oznacz_czlowiek_odezwal_sie`)
    gdy wiadomość agenta zostanie znaleziona, i sprawdzany PRZED sięgnięciem po
    historię (`_czlowiek_juz_sie_odezwal`) — raz ustawiony, blokuje TRWALE bez
    ponownego skanowania /messages. To jednocześnie ogranicza liczbę wywołań API
    Chatwoota na turę (odmowa scalenia statusu+historii z rundy 1 pozostaje
    słuszna — patrz raport — ale po ustawieniu sticky bita druga rozmowa idzie
    już wyłącznie po statusie, bez /messages w ogóle)."""
    from core.chatwoot import cw_conv_status, cw

    status = cw_conv_status(conv_id)
    if status is None:
        raise BladOdczytuStanu(
            "stan: nie mozna odczytac statusu rozmowy (conv %s)" % conv_id)
    if status != "pending":
        return False
    if _czlowiek_juz_sie_odezwal(conv_id):
        return False
    try:
        odpowiedz = cw("GET", "/conversations/%s/messages" % conv_id)
        if not odpowiedz.ok:
            raise BladOdczytuStanu(
                "stan: HTTP %s przy odczycie historii rozmowy (conv %s)"
                % (odpowiedz.status_code, conv_id))
        wiadomosci = odpowiedz.json().get("payload", [])
    except BladOdczytuStanu:
        raise
    except Exception as e:
        raise BladOdczytuStanu(
            "stan: nie mozna odczytac historii rozmowy (conv %s): %r" % (conv_id, e)) from e
    for wiadomosc in wiadomosci or []:
        if wiadomosc.get("private"):
            continue
        if (wiadomosc.get("sender") or {}).get("type") == "user":
            _oznacz_czlowiek_odezwal_sie(conv_id)
            return False
    return True


def ostatnia_wiadomosc_klienta():
    """Treść ostatniej wiadomości przychodzącej — materiał do weryfikacji cytatu."""
    from config import BOT_HISTORY_LIMIT
    from core.chatwoot import cw_messages
    for wiadomosc in reversed(cw_messages(conv_id(), BOT_HISTORY_LIMIT) or []):
        if wiadomosc.get("role") == "user":
            return wiadomosc.get("text") or ""
    return ""
