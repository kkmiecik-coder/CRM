# -*- coding: utf-8 -*-
# Silnik konwersacyjnego bota WYCENIAJACEGO (kopia silnika live-chat, patrz bots/livechat.py):
# publiczne odpowiedzi do klienta (RAG + persona), wycena na POZYCJACH (wiele produktow bez
# wzajemnego nadpisywania), deterministyczne podsumowanie do potwierdzenia. Roznica wobec live-bota:
# po komplecie i potwierdzeniu NIE robi handoffu, tylko liczy cene przez API CRM i wysyla ja
# klientowi; gdy jest kontakt (e-mail/telefon) zapisuje wycene i dosyla publiczny link.
# Rzuca wyjatkiem przy niepowodzeniu LLM/wysylki; retry i sciezke awaryjna obsluguje quote_worker.
import os
import json
import re
from config import BOT_HISTORY_LIMIT, BOT_QUOTE_MAX_TURNS, BOT_QUOTE_CW_AGENT_TOKEN
from core.log import log
from core.db import db
from core.chatwoot import (cw_messages, cw_contact, cw_note, cw_agent_reply,
                           cw_conv_status, cw_bot_handoff, cw_contact_full)
from bots.knowledge import retrieve
from bots.personas import build_system_prompt
from bots.llm import chat
from bots import images
from bots.vision import attach_images
from bots import crm_calc

# Komunikaty stale (edytowalne). Bez obietnic czasowych — patrz spec §13.
CLOSING_MSG = "Dziękuję za informacje! Przekazuję rozmowę do konsultanta WoodPower — odpowiemy w tej rozmowie."
APOLOGY_MSG = ("Przepraszam, mam chwilowy problem techniczny z odpowiedzią. "
               "Przekazuję rozmowę do konsultanta WoodPower.")
# Wycena nie policzyla sie automatycznie (najczesciej lakier/olej bez koloru i polysku) —
# dopytujemy zamiast przekazywac do konsultanta.
_PROSBA_DOPRECYZ = ("Żeby dokończyć wycenę, potrzebuję jeszcze doprecyzowania wykończenia — przy "
                    "lakierze lub oleju proszę o kolor i poziom połysku (mat / półmat / połysk). "
                    "Które wybieramy?")

_MAX_PROBEK = 3   # limit probek wg konfiguracji doklejanych do jednego podsumowania
_PROBKA_PODPIS = "Poniżej próbka wybranego wykończenia 👇"

# Instrukcja formatu odpowiedzi LLM — doklejana do promptu systemowego persony.
# Kazdy produkt klienta = OSOBNA pozycja ze stalym id; pola wspolne calej wyceny poza pozycjami.
_FORMAT = (
    "FORMAT ODPOWIEDZI: odpowiedz WYŁĄCZNIE poprawnym JSON (bez tekstu przed/po):\n"
    '{"odpowiedz": "tekst do klienta", "handoff": false, "powod": "", "send_image": "", '
    '"pozycje": [{"id": "1", "produkt": "", "dlugosc": "", "szerokosc": "", "grubosc": "", '
    '"gatunek": "", "technologia": "", "klasa": "", "ilosc": "", "wykonczenie": "", '
    '"finishing_id": "", '
    '"otwory": "", "edges": [], "schody": ""}], '
    '"wspolne": {"termin": "", "kontakt": ""}, '
    '"porownania": [{"id": "1", "gatunek": "", "technologia": "", "klasa": ""}]}\n'
    "Każdy produkt klienta to OSOBNA pozycja listy 'pozycje' ze stałym id (\"1\", \"2\", ...). "
    "Utrzymuj id z bloku DOTYCHCZAS ZEBRANE DANE WYCENY i NIGDY nie nadpisuj jednej pozycji "
    "danymi innego produktu. Gdy klient rezygnuje z pozycji, zwróć ją z polem \"usun\": true. "
    "Uzupełniaj wszystko, co klient dotąd podał (całość rozmowy, nie tylko ostatnia wiadomość). "
    "Wymiary zapisuj w centymetrach. Pole 'schody' wypełniaj tylko dla produktu schody "
    "(liczba stopni, wymiar stopnia, podstopnice). "
    "Ustaw handoff=true gdy: klient prosi o człowieka/konsultanta, pytanie wykracza poza podaną "
    "wiedzę, sprawa indywidualna (reklamacja, status lub zmiana zamówienia, faktura, zwrot), "
    "albo klient POTWIERDZIŁ wysłane wcześniej podsumowanie danych do wyceny. "
    "NIE ustawiaj handoff na samo pytanie o cenę — wtedy zbieraj brakujące dane do wyceny. "
    "Pole 'send_image' ustaw na DOKŁADNY tag obrazu z listy DOSTĘPNE OBRAZY tylko wtedy, gdy "
    "obraz realnie pomoże klientowi (np. pyta o różnice gatunków). W innym razie zostaw pusty "
    "string. NIGDY nie wymyślaj tagów spoza listy i nie obiecuj zdjęć, których nie ma. "
    "Pola 'wspolne' (termin, kontakt) wypełniaj WYŁĄCZNIE danymi, które klient sam podał w "
    "rozmowie (np. telefon lub e-mail, który napisał). NIGDY nie wstawiaj tam nazwy ani "
    "identyfikatora kontaktu z systemu, ani własnej prośby o dane — jeśli klient nic nie podał, "
    "zostaw te pola puste. "
    "Pole 'finishing_id' ustaw na id wykończenia z listy DOSTĘPNE WYKOŃCZENIA odpowiadające "
    "wyborowi klienta (np. olejowanie bezbarwne). Dla wykończenia 'surowe' zostaw puste. "
    "SAM przygotowujesz wstępną wycenę — NIE mów, że przekażesz dane konsultantowi „do wyceny” "
    "(cenę policzysz automatycznie). "
    "Gdy do wyceny brakuje kilku parametrów, poproś o WSZYSTKIE naraz krótką listą — każdy punkt "
    "od myślnika „- ” w nowej linii — zamiast pytać po jednym. "
    "NIE proś klienta o e-mail ani telefon w trakcie zbierania parametrów produktu — o kontakt "
    "system zapyta sam już PO przygotowaniu wyceny.\n"
    "KRAWĘDZIE ('edges'): lista obróbek krawędzi tej pozycji, każdy element "
    '{"litera": "A", "typ": "round", "r": 3}. Typy: "sharp" (ostra, bez obróbki), "chamfer" '
    '(fazowanie — podaj kąt w polu "kat", np. 45), "round" (zaokrąglenie — podaj promień w mm w polu '
    '"r", np. gdy klient mówi „R3” użyj "r": 3; domyślnie 5). Klient może podać różne promienie dla '
    "różnych krawędzi (np. „C, A, D R3, E R5”) — każdą krawędź zapisz osobnym elementem z jej promieniem. "
    'Litery blatu/parapetu: A=góra przód (długość), '
    "B=góra tył (długość), C=góra lewa (szerokość), D=góra prawa (szerokość); dół: E/F/G/H; narożniki: "
    "N1–N4; kształt okrągły: KG (górny obwód)/KD (dolny obwód). Gdy klient chce „wszystkie/każdą "
    'krawędź” danego typu — użyj litery "WSZYSTKIE" (system rozwinie na A,B,C,D). Obsługujesz mieszane '
    "obróbki (różne krawędzie różnie). Gdy klient nie prosi o obróbkę krawędzi — zostaw edges puste []. "
    "Gdy klient chce krawędź OSTRĄ (bez obróbki) albo USUNĄĆ wcześniej ustawione zaokrąglenie/fazę — "
    'ustaw dla niej "typ": "sharp" (system ją wtedy usunie z obróbki). '
    "Nie wstrzymuj wyceny z powodu krawędzi — są opcjonalne.\n"
    "WYSYŁKA: po podaniu ceny system SAM proponuje oszacowanie wysyłki i prosi o kod pocztowy — "
    "Ty NIE licz kosztu wysyłki samodzielnie i nie podawaj żadnej ceny wysyłki. Gdy klient poda samo "
    "miasto bez kodu, poproś krótko o kod pocztowy w formacie 00-000. Ostateczny koszt i tak "
    "potwierdza konsultant przy finalizacji.\n"
    "OTWORY/WYCIĘCIA ('otwory'): NIE wyceniasz. Gdy klient je poda — zapisz opis w polu 'otwory' i "
    "wspomnij, że koszt wycięć doliczy konsultant. Nie wstrzymuj z tego powodu wyceny blatów i krawędzi.\n"
    "KLASA DREWNA ('klasa'): klasy to zawsze A/B albo B/B (NIGDY „A” ani „B” osobno). A/B = jedna "
    "strona produktu w klasie A, druga w klasie B; B/B = obie strony w klasie B. Dostępność: dąb — A/B "
    "lub B/B; jesion — tylko A/B; buk — tylko A/B. Pytając o klasę podawaj dostępne opcje (np. dla "
    "jesionu „klasa A/B”, dla dębu „A/B czy B/B”) — nie pytaj „A czy B”.\n"
    "PORÓWNANIE WARIANTU ('porownania'): używaj WYŁĄCZNIE gdy klient JUŻ OTRZYMAŁ wcześniej w tej "
    "rozmowie wycenę/cenę i teraz pyta o cenę TEGO SAMEGO produktu w innym gatunku, technologii lub "
    "klasie (np. „a ile w jesionie?”, „ciekawi mnie ta sama w buku litym”). Wtedy NIE zmieniaj pozycji "
    "ani zamówienia; dodaj wpis do 'porownania': "
    '[{"id": "<id pozycji>", "gatunek": "<jesion>", "technologia": "<jeśli inna>", "klasa": "<jeśli inna>"}] '
    "(podaj tylko pola, które klient zmienia; resztę zostaw pustą), a pole 'odpowiedz' zostaw puste. "
    "PIERWSZĄ wycenę produktu ZAWSZE prowadź normalnie przez 'pozycje' (zbierz dane → system wyśle "
    "podsumowanie → cena) — NIE używaj wtedy 'porownania'. 'porownania' NIE służy do wyceny nowego "
    "produktu ani pierwszej wyceny. DODANIE PRODUKTU: gdy klient prosi o KOLEJNY produkt (np. „dodaj "
    "jeszcze blat”, „drugi blat”, podaje nowe wymiary) — także gdy mówi „te same parametry” — utwórz "
    "NOWĄ pozycję w 'pozycje' z NOWYM id (skopiuj gatunek/technologię/klasę/wykończenie z poprzedniej "
    "pozycji, gdy klient mówi „te same”), a NIE wpis w 'porownania'. 'porownania' NIGDY nie dotyczy "
    "dodania produktu ani nowych wymiarów. Gdy klient chce FAKTYCZNIE zmienić zamówienie na inny wariant — "
    "zmień pozycję normalnie (nie używaj 'porownania'). "
    "Wypełniaj 'porownania' TYLKO dla porównania, o które klient prosi W TEJ wiadomości — NIGDY nie "
    "powtarzaj porównania z wcześniejszych tur. Gdy klient komentuje lub decyduje (np. „zostajemy "
    "przy dębie”, „ok”, „dziękuję”) — zostaw 'porownania' PUSTE i odpowiedz krótko i naturalnie w polu "
    "'odpowiedz' (np. potwierdź wybór i zapytaj, czy pomóc w czymś jeszcze)."
)

# Instrukcja stanu potwierdzenia — doklejana do promptu, gdy klient dostal podsumowanie od systemu.
_CONFIRM_INSTR = (
    "STAN ROZMOWY: klient właśnie otrzymał od systemu podsumowanie danych do wyceny i ma je "
    "potwierdzić. Jeśli potwierdza (np. 'tak', 'zgadza się', 'ok') — ustaw handoff=true z powodem "
    "'klient potwierdził dane do wyceny'. Jeśli coś koryguje lub dodaje — zaktualizuj pozycje "
    "(system wyśle nowe podsumowanie), handoff=false. Jeśli pyta o coś innego — odpowiedz "
    "normalnie, handoff=false."
)

# Twardy wyzwalacz: prosba o czlowieka. Bierne wzmianki ('od/przez konsultanta') NIE licza sie.
_HUMAN_RE = re.compile(r"\b(konsultant\w*|człowiek\w*|czlowiek\w*|doradc\w*|pracownik\w*|"
                       r"agent\w*|zadzwoń\w*|zadzwon\w*|oddzwon\w*)\b", re.IGNORECASE)
_HUMAN_PASYWNE_RE = re.compile(r"\b(od|przez|do)\s+(konsultant\w*|doradc\w*|pracownik\w*|agent\w*)",
                               re.IGNORECASE)

# Pytanie o tozsamosc rozmowcy — NIE traktujemy jako prosby o czlowieka; niech LLM odpowie uczciwie.
_PYTANIE_O_BOTA_RE = re.compile(
    r"(czy (jesteś|jestes) (botem|człowiekiem|czlowiekiem|robotem|prawdziw|maszyn)|"
    r"czy rozmawiam z (botem|człowiekiem|czlowiekiem|robotem|maszyn|prawdziw|ai|sztuczn)|"
    r"z kim (rozmawiam|mam przyjemność|mam przyjemnosc)|"
    r"(jesteś|jestes) (botem|robotem|sztuczn|prawdziw)|"
    r"czy to (jest )?(bot|robot|ai|sztuczna)|"
    r"bot\w* czy (człowiek|czlowiek)|człowiek\w* czy bot|czlowiek\w* czy bot)", re.IGNORECASE)

# Reklamacja — twardy wyzwalacz. Sam rzeczownik uszkodzenia (wadliwy/pekl) NIE wystarcza:
# musi byc intencja reklamacji ("reklamacj/reklamowa") ALBO uszkodzenie + kontekst posiadania
# (moj/kupilem/zamowilem/dostalem/mi), zeby pytania przedsprzedazowe o trwalosc nie wyzwalaly handoffu.
_REKLAMACJA_RE = re.compile(r"(reklamacj\w*|reklamowa\w*)", re.IGNORECASE)
_USZKODZENIE_RE = re.compile(r"(pęk\w*|pek\w*|uszkodz\w*|wadliw\w*|zepsu\w*|wypacz\w*|odklei\w*)",
                             re.IGNORECASE)
_POSIADANIE_RE = re.compile(r"\b(mój|moje|moja|moim|kupi\w*|zamówi\w*|zamowi\w*|dostał\w*|dostal\w*|"
                            r"otrzymał\w*|otrzymal\w*|zamówieni\w*|zamowieni\w*|mi)\b", re.IGNORECASE)


def _czy_reklamacja(text):
    """True gdy tresc to reklamacja: jawne 'reklamacj/reklamowa' albo uszkodzenie + posiadanie."""
    t = text or ""
    if _REKLAMACJA_RE.search(t):
        return True
    return bool(_USZKODZENIE_RE.search(t) and _POSIADANIE_RE.search(t))


COMPLAINT_MSG = ("Przykro nam z powodu problemu. Reklamacje przyjmujemy mailowo — prosimy o "
                 "wiadomość na reklamacje@woodpower.pl z numerem i szczegółami zamówienia oraz "
                 "zdjęciami reklamowanego produktu w treści maila. Nasz zespół reklamacji zajmie "
                 "się zgłoszeniem. Czy mogę jeszcze w czymś pomóc?")
DEFLECT_MSG = ("Jasne, mogę połączyć Pana/Panią z konsultantem. Zanim to zrobię — chętnie spróbuję "
               "pomóc od razu, często udaje się wszystko ustalić tu, na czacie. W czym mogę pomóc? "
               "A jeśli woli Pan/Pani rozmowę z konsultantem, od razu przełączę.")


def _czy_prosi_o_czlowieka(text):
    """True gdy tresc to prosba o czlowieka. Bierna wzmianka 'od/przez konsultanta' -> False."""
    t = text or ""
    if _HUMAN_PASYWNE_RE.search(t):
        return False
    return bool(_HUMAN_RE.search(t))


# Deterministyczne wykrycie potwierdzenia podsumowania (obok decyzji LLM).
_POTW_RE = re.compile(r"\b(tak|zgadza|zgadzam|potwierdzam|potwierdzone|ok|okej|okay|zgoda|"
                      r"pasuje|dokładnie|dokladnie|wysyłam|wysylam|super|świetnie|swietnie)\b",
                      re.IGNORECASE)
_NEG_RE = re.compile(r"\b(nie|źle|zle|błąd|blad|popraw\w*|zmień|zmien|inaczej|niepopr\w*)\b",
                     re.IGNORECASE)


def _jest_potwierdzenie(text):
    """True gdy tresc to czyste potwierdzenie (bez negacji/korekty/pytania). 'nie zgadza sie' -> False;
    'tak, ale zaokraglicie krawedzie?' -> False (pytanie -> LLM ma na nie odpowiedziec, nie handoff)."""
    t = text or ""
    if "?" in t:
        return False
    return bool(_POTW_RE.search(t)) and not _NEG_RE.search(t)


# --- Stan rozmowy: licznik tur + flaga oczekiwania na potwierdzenie podsumowania ---

def _bot_turns(conv_id):
    """Aktualny licznik tur bota dla rozmowy (0 gdy brak wpisu)."""
    c = db()
    row = c.execute("SELECT bot_turns FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return row["bot_turns"] if row else 0


def _bump_turns(conv_id):
    """Inkrementuje licznik tur bota (INSERT lub UPDATE)."""
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns) VALUES(?,1) "
              "ON CONFLICT(conv_id) DO UPDATE SET bot_turns=bot_turns+1", (conv_id,))
    c.commit(); c.close()


def _awaiting_confirm(conv_id):
    """Czy rozmowa czeka na potwierdzenie podsumowania wyceny przez klienta."""
    c = db()
    row = c.execute("SELECT awaiting_confirm FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["awaiting_confirm"]) if row else False


def _set_awaiting(conv_id, flag):
    """Ustawia/kasuje flage oczekiwania na potwierdzenie (INSERT lub UPDATE)."""
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_confirm) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET awaiting_confirm=excluded.awaiting_confirm",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


# --- Stan wyceny: cena policzona / oczekiwanie na kontakt / wycena zapisana (quote-bot) ---

def _priced(conv_id):
    c = db()
    row = c.execute("SELECT priced FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["priced"]) if row else False


def _set_priced(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET priced=excluded.priced", (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _awaiting_contact(conv_id):
    c = db()
    row = c.execute("SELECT awaiting_contact FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["awaiting_contact"]) if row else False


def _set_awaiting_contact(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_contact) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET awaiting_contact=excluded.awaiting_contact",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _awaiting_postcode(conv_id):
    c = db()
    row = c.execute("SELECT awaiting_postcode FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["awaiting_postcode"]) if row else False


def _set_awaiting_postcode(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_postcode) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET awaiting_postcode=excluded.awaiting_postcode",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _set_quote_saved(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, quote_saved) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET quote_saved=excluded.quote_saved",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _fmt_pln(v):
    """Kwota PLN z separatorem tysiecy i przecinkiem: 1230.0 -> '1 230,00 zł'."""
    try:
        s = "%0.2f" % float(v)
    except (TypeError, ValueError):
        return str(v)
    calosc, ulamek = s.split(".")
    calosc = re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", calosc)
    return "%s,%s zł" % (calosc, ulamek)


def _linia_pozycji(poz):
    """Jedna linia parametrow pozycji do echa przy cenie, np.
    'Klejonka dąb mikrowczep A/B 140×80×3 cm surowe'. Nazwa produktu = to co podal klient
    (blat/parapet/schody), a gdy nie podal konkretu — fallback 'Klejonka'."""
    nazwa = (str(poz.get("produkt") or "").strip() or "Klejonka").capitalize()
    czesci = [nazwa]
    for k in ("gatunek", "technologia", "klasa"):
        v = str(poz.get(k) or "").strip()
        if v:
            czesci.append(v)
    wym = [str(poz.get(k) or "").strip() for k in ("dlugosc", "szerokosc", "grubosc")]
    wym = [w for w in wym if w]
    if wym:
        czesci.append("×".join(wym) + " cm")
    wyk = str(poz.get("wykonczenie") or "").strip()
    if wyk:
        czesci.append(wyk)
    return " ".join(czesci)


def _cena_pozycji(poz, prod):
    """Skladowe ceny pozycji z /calculate jako dict: 'material' (wybrany wariant), 'wykonczenie',
    'krawedzie', 'razem' — kazde (netto, brutto). Odporne na braki pol (zwraca 0)."""
    code = crm_calc.variant_code(poz.get("gatunek"), poz.get("technologia"), poz.get("klasa"))
    var = next((v for v in (prod.get("variants") or [])
                if v.get("variant_code") == code and v.get("available")), None)

    def _n(d, k):
        try:
            return float((d or {}).get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
    mat = (_n(var, "total_netto"), _n(var, "total_brutto"))
    wyk = (_n(prod.get("finishing"), "netto"), _n(prod.get("finishing"), "brutto"))
    kra = (_n(prod.get("edges"), "netto"), _n(prod.get("edges"), "brutto"))
    razem = (mat[0] + wyk[0] + kra[0], mat[1] + wyk[1] + kra[1])
    return {"material": mat, "wykonczenie": wyk, "krawedzie": kra, "razem": razem}


def _cena_msg(dane, wynik):
    """Deterministyczna wiadomosc z cena: per pozycja opis pogrubiony + rozbicie na skladowe
    (Produkt surowy / Wykończenie / Krawędzie) i Razem, na koncu 'Cena za całość'. Skladowe
    zerowe (np. brak wykończenia/krawędzi) pomijamy. Ceny z odpowiedzi /calculate."""
    pozycje = dane.get("pozycje") or []
    products = wynik.get("products") or []
    totals = wynik.get("totals") or {}
    linie = []
    for i, poz in enumerate(pozycje):
        linie.append("**%s**" % _linia_pozycji(poz))   # nazwa+parametry pogrubione (markdown Chatwoota)
        if i < len(products):
            b = _cena_pozycji(poz, products[i])
            # Produkt surowy zawsze; wykończenie/krawędzie tylko gdy niezerowe.
            skladowe = [("Produkt surowy", b["material"])]
            if b["wykonczenie"][1] > 0:
                skladowe.append(("Wykończenie", b["wykonczenie"]))
            if b["krawedzie"][1] > 0:
                skladowe.append(("Krawędzie", b["krawedzie"]))
            for lab, (n, bru) in skladowe:
                linie.append("    %s: %s (%s netto)" % (lab, _fmt_pln(bru), _fmt_pln(n)))
            if len(skladowe) > 1:   # rozbicie ma sens tylko przy >1 skladowej
                rn, rb = b["razem"]
                linie.append("    Razem: %s (%s netto)" % (_fmt_pln(rb), _fmt_pln(rn)))
        linie.append("")
    linie.append("**Cena za całość:**")
    linie.append("%s (%s netto)" % (_fmt_pln(totals.get("total_brutto")), _fmt_pln(totals.get("total_netto"))))
    return "\n".join(linie)


def _rozbicie_linie(b):
    """Linie rozbicia ceny (Produkt surowy/Wykończenie/Krawędzie [+Razem]) ze slownika _cena_pozycji."""
    skladowe = [("Produkt surowy", b["material"])]
    if b["wykonczenie"][1] > 0:
        skladowe.append(("Wykończenie", b["wykonczenie"]))
    if b["krawedzie"][1] > 0:
        skladowe.append(("Krawędzie", b["krawedzie"]))
    linie = ["    %s: %s (%s netto)" % (lab, _fmt_pln(nb[1]), _fmt_pln(nb[0])) for lab, nb in skladowe]
    if len(skladowe) > 1:
        linie.append("    Razem: %s (%s netto)" % (_fmt_pln(b["razem"][1]), _fmt_pln(b["razem"][0])))
    return linie


def _porownanie_msg(alt_poz, prod, totals):
    """Wiadomosc informacyjna: cena pozycji w innym wariancie (z rozbiciem) + uwaga, ze wycena
    sie NIE zmienia (nadal aktualna cena calosci)."""
    linie = ["**%s** (informacyjnie)" % _linia_pozycji(alt_poz)]
    linie += _rozbicie_linie(_cena_pozycji(alt_poz, prod))
    linie.append("")
    linie.append("To tylko informacja — nie zmieniam Twojej wyceny (nadal %s / %s netto)."
                 % (_fmt_pln(totals.get("total_brutto")), _fmt_pln(totals.get("total_netto"))))
    return "\n".join(linie)


_ALT_NIEDOSTEPNY = ("Ten wariant nie jest dostępny — pracujemy w dębie (klasa A/B lub B/B), jesionie "
                    "(A/B) i buku (A/B), w technologii litej lub mikrowczep. Proszę wybrać z tych opcji.")


def _czy_porownanie(conv_id, out, dane, zmienione=False):
    """Porownanie wariantu obslugujemy TYLKO gdy: (1) model o nie poprosil, (2) jest komplet danych,
    (3) w rozmowie POKAZANO juz wycene (_priced) ORAZ (4) w tej turze NIE zmienily sie pozycje
    (zmienione=False). Bez (3) pierwsza wycena poszlaby blednie jako 'informacyjnie'. Bez (4) klient
    dodajacy/zmieniajacy produkt (np. 'dodaj jeszcze blat ... te same parametry') zostalby blednie
    potraktowany jako porownanie — dodanie/zmiana pozycji ma pierwszenstwo."""
    return (bool(out.get("porownania")) and _priced(conv_id)
            and not _brakujace(dane) and not zmienione)


def _obsluz_porownania(conv_id, dane, porownania):
    """Odpowiada na prośbę o cenę tego samego produktu w innym wariancie (gatunek/technologia/klasa)
    BEZ edycji wyceny. Warianty i tak są policzone w /calculate; wykończenie/krawędzie niezależne od
    gatunku. Zwraca True gdy coś wysłano (tura obsłużona). Nigdy nie edytuje danych/wyceny."""
    options = crm_calc.get_options()
    wynik = crm_calc.calculate(dane.get("pozycje") or [], options)
    if not wynik.get("ok") or not wynik.get("products"):
        return False   # nie policzymy (braki/blad) — niech LLM odpowie normalnie
    products, pozycje, totals = wynik["products"], dane.get("pozycje") or [], wynik.get("totals") or {}
    wyslane = _sent_images(conv_id)   # dedup (te same klucze co obrazy) — nie powtarzaj porownania
    wyslano = False
    for por in porownania:
        if not isinstance(por, dict):
            continue
        pid = str(por.get("id") or "").strip()
        idx = next((i for i, p in enumerate(pozycje) if str(p.get("id")) == pid), None)
        if idx is None or idx >= len(products):
            continue
        alt = dict(pozycje[idx])
        for k in ("gatunek", "technologia", "klasa"):
            if str(por.get(k) or "").strip():
                alt[k] = por[k]
        code = crm_calc.variant_code(alt.get("gatunek"), alt.get("technologia"), alt.get("klasa"))
        # Dedup: to samo porownanie (pozycja+wariant) juz pokazane -> pomijamy (LLM lubi echowac).
        dkey = "cmp:%s:%s" % (pid, code or "%s|%s|%s" % (alt.get("gatunek"), alt.get("technologia"), alt.get("klasa")))
        if dkey in wyslane:
            continue
        var = next((v for v in (products[idx].get("variants") or [])
                    if v.get("variant_code") == code and v.get("available")), None)
        if not var:
            cw_agent_reply(conv_id, _ALT_NIEDOSTEPNY, token=BOT_QUOTE_CW_AGENT_TOKEN)
        else:
            cw_agent_reply(conv_id, _porownanie_msg(alt, products[idx], totals),
                           token=BOT_QUOTE_CW_AGENT_TOKEN)
        _mark_image_sent(conv_id, dkey)
        wyslane.add(dkey)
        wyslano = True
    if wyslano:
        _bump_turns(conv_id)
        log("quotebot: porownanie wariantu (conv %s)" % conv_id)
    return wyslano   # False gdy nic nowego -> run_quote_turn schodzi do normalnej odpowiedzi


_PROSBA_KONTAKT = ("Jeśli poda Pan/Pani adres e-mail (lub telefon), zapiszę tę wycenę i wyślę "
                   "link — wróci Pan/Pani do niej w każdej chwili. Jeśli woli Pan/Pani nie "
                   "podawać, nie ma problemu — wycena wyżej pozostaje aktualna.")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Ograniczone do 9-15 cyfr (typowy numer PL z separatorami) + granice slowa, zeby dlugi
# ciag cyfr (np. numer zamowienia) nie zostal pomylony z telefonem.
_TEL_RE = re.compile(r"\b(?:\+?\d[\s-]?){9,15}\b")
_ODMOWA_RE = re.compile(r"\b(nie|nie chc\w*|bez|rezygnuj\w*|pomi\w*|p[oó]zniej)\b", re.IGNORECASE)

_KOD_RE = re.compile(r"\b(\d{2}-\d{3})\b")


def _wyciagnij_kod(text):
    """Kod pocztowy 00-000 z tekstu klienta albo None."""
    m = _KOD_RE.search(str(text or ""))
    return m.group(1) if m else None


_WYSYLKA_OFERTA = ("Mogę od razu oszacować koszt wysyłki 🚚 Proszę o kod pocztowy dostawy "
                   "(w formacie 00-000), a podam orientacyjną cenę.")


def _wysylka_msg(res):
    """Wiadomosc o wysylce z odpowiedzi /shipping-quote: najtanszy kurier +30%; gabaryt bez
    kuriera -> konsultant; blad -> konsultant."""
    if not res or not res.get("ok"):
        return ("Nie udało się teraz oszacować kosztu wysyłki — ostateczną cenę potwierdzi "
                "konsultant przy finalizacji zamówienia.")
    if not res.get("carriers"):
        return ("Ten gabaryt przekracza standardowe paczki kurierskie — koszt wysyłki wyceni "
                "indywidualnie konsultant przy finalizacji.")
    return "Najtańsza wysyłka to **%s** — **%s**." % (
        res.get("carrier_name") or "kurier", _fmt_pln(res.get("shipping_brutto")))


def _wyciagnij_kontakt(text):
    """(email, telefon) z tekstu klienta; '' gdy brak. Telefon akceptujemy tylko gdy po odsianiu
    separatorow ma 9-15 cyfr — chroni przed utrwaleniem ciagu cyfr (nr zamowienia/wymiary) jako tel."""
    t = text or ""
    email = _EMAIL_RE.search(t)
    tel = ""
    m = _TEL_RE.search(t)
    if m:
        cyfry = re.sub(r"\D", "", m.group(0))
        if 9 <= len(cyfry) <= 15:
            tel = m.group(0).strip()
    return (email.group(0) if email else ""), tel


# --- Trwaly kontakt klienta (zapamietany na cala rozmowe) + edit_uuid zapisanej wyceny ---

def _stored_contact(conv_id):
    """(email, telefon, nazwa) zapamietane w stanie rozmowy; '' gdy brak."""
    c = db()
    row = c.execute("SELECT contact_email, contact_phone, contact_name FROM quote_state WHERE conv_id=?",
                    (conv_id,)).fetchone()
    c.close()
    if not row:
        return "", "", ""
    return (row["contact_email"] or ""), (row["contact_phone"] or ""), (row["contact_name"] or "")


def _set_contact(conv_id, email, phone, name):
    """Zapisuje kontakt do stanu (niepusta wartosc nadpisuje, pusta NIE kasuje istniejacej)."""
    e0, p0, n0 = _stored_contact(conv_id)
    email = (email or "").strip() or e0
    phone = (phone or "").strip() or p0
    name = (name or "").strip() or n0
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, contact_email, contact_phone, contact_name) "
              "VALUES(?,0,?,?,?) ON CONFLICT(conv_id) DO UPDATE SET "
              "contact_email=excluded.contact_email, contact_phone=excluded.contact_phone, "
              "contact_name=excluded.contact_name", (conv_id, email, phone, name))
    c.commit(); c.close()


def _effective_contact(conv_id, dane, identity=None):
    """Ustala (email, telefon, nazwa) klienta z 3 zrodel wg priorytetu i ZAPAMIETUJE na rozmowe:
    1) kontakt juz zapamietany w stanie, 2) kontakt podany przez klienta W CZACIE
    (dane.wspolne.kontakt — LLM go tam zapisuje), 3) rekord kontaktu Chatwoota (identity).
    Dzieki temu maila podanego raz nie pytamy ponownie przy kolejnych wycenach."""
    email, phone, name = _stored_contact(conv_id)
    if not (email or phone):
        e2, p2 = _wyciagnij_kontakt(str((dane.get("wspolne") or {}).get("kontakt") or ""))
        email, phone = email or e2, phone or p2
    ident = identity or {}
    if not (email or phone):
        email, phone = email or (ident.get("email") or ""), phone or (ident.get("phone") or "")
    name = name or (ident.get("name") or "")
    if email or phone or name:
        _set_contact(conv_id, email, phone, name)
    return email, phone, name


def _stored_edit_uuid(conv_id):
    """edit_uuid zapisanej wczesniej wyceny (do aktualizacji zamiast tworzenia nowej); '' gdy brak."""
    c = db()
    row = c.execute("SELECT quote_edit_uuid FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return (row["quote_edit_uuid"] or "") if row else ""


def _set_edit_uuid(conv_id, edit_uuid):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, quote_edit_uuid) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET quote_edit_uuid=excluded.quote_edit_uuid",
              (conv_id, edit_uuid or ""))
    c.commit(); c.close()


def _returning_greeted(conv_id):
    c = db()
    row = c.execute("SELECT returning_greeted FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["returning_greeted"]) if row else False


def _set_returning_greeted(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, returning_greeted) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET returning_greeted=excluded.returning_greeted",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _human_deflected(conv_id):
    c = db()
    row = c.execute("SELECT human_deflected FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["human_deflected"]) if row else False


def _set_human_deflected(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, human_deflected) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET human_deflected=excluded.human_deflected",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _complaint_sent(conv_id):
    """Czy w tej rozmowie wyslano juz instrukcje reklamacyjna (COMPLAINT_MSG)."""
    c = db()
    row = c.execute("SELECT complaint_sent FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["complaint_sent"]) if row else False


def _set_complaint_sent(conv_id, flag):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, complaint_sent) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET complaint_sent=excluded.complaint_sent",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _reject_state(conv_id):
    """(sygnatura ostatniego odrzucenia, licznik powtorzen) — 0/'' gdy brak."""
    c = db()
    row = c.execute("SELECT reject_sig, reject_count FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    if not row:
        return "", 0
    return (row["reject_sig"] or ""), (row["reject_count"] or 0)


def _set_reject(conv_id, sig, count):
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, reject_sig, reject_count) VALUES(?,0,?,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET reject_sig=excluded.reject_sig, "
              "reject_count=excluded.reject_count", (conv_id, sig, count))
    c.commit(); c.close()


def _sent_images(conv_id):
    """Zbior kluczy obrazow juz wyslanych w tej rozmowie (dedup)."""
    c = db()
    row = c.execute("SELECT sent_images FROM quote_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    if not row or not row["sent_images"]:
        return set()
    try:
        v = json.loads(row["sent_images"])
        return set(v) if isinstance(v, list) else set()
    except Exception:
        return set()


def _mark_image_sent(conv_id, key):
    """Dopisuje klucz obrazu do sent_images (INSERT lub UPDATE)."""
    obecne = _sent_images(conv_id)
    obecne.add(key)
    c = db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, sent_images) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET sent_images=excluded.sent_images",
              (conv_id, json.dumps(sorted(obecne), ensure_ascii=False)))
    c.commit(); c.close()


# --- Warstwa danych wyceny: pozycje (wiele produktow) + pola wspolne ---

# Pola tekstowe pozycji. Krawedzie NIE sa tu — trzymamy je jako liste 'edges' (patrz _merge_dane).
_POZ_POLA = ("produkt", "dlugosc", "szerokosc", "grubosc", "gatunek", "technologia",
             "klasa", "ilosc", "wykonczenie", "finishing_id", "otwory", "schody")
_WSPOLNE_POLA = ("termin", "kontakt")


def _pusty_stan():
    return {"pozycje": [], "wspolne": {}}


def _load_dane(conv_id):
    """Wczytuje zaakumulowany stan wyceny {'pozycje': [...], 'wspolne': {...}}.
    Stary plaski zapis (rozmowy w toku sprzed pozycji) opakowuje jako pozycje '1'."""
    c = db()
    row = c.execute("SELECT dane_json FROM quote_dane WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    if not row or not row["dane_json"]:
        return _pusty_stan()
    try:
        d = json.loads(row["dane_json"])
    except Exception:
        return _pusty_stan()
    if not isinstance(d, dict):
        return _pusty_stan()
    if isinstance(d.get("pozycje"), list):
        return {"pozycje": [p for p in d["pozycje"] if isinstance(p, dict)],
                "wspolne": d.get("wspolne") if isinstance(d.get("wspolne"), dict) else {}}
    # Kompatybilnosc wstecz: plaski slownik = jedna pozycja + pola wspolne.
    wspolne = {k: d[k] for k in _WSPOLNE_POLA if str(d.get(k) or "").strip()}
    poz = {k: d[k] for k in _POZ_POLA if str(d.get(k) or "").strip()}
    stan = _pusty_stan()
    stan["wspolne"] = wspolne
    if poz:
        poz["id"] = "1"
        stan["pozycje"] = [poz]
    return stan


def _zapisz_dane(conv_id, stan):
    c = db()
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET dane_json=excluded.dane_json",
              (conv_id, json.dumps(stan, ensure_ascii=False)))
    c.commit(); c.close()


def _nowe_id(pozycje):
    """Najnizszy wolny numeryczny id dla nowej pozycji."""
    uzyte = {str(p.get("id")) for p in pozycje}
    n = 1
    while str(n) in uzyte:
        n += 1
    return str(n)


def _merge_pola(stare, nowe):
    """Scala pola tekstowe pozycji/wspolnych: niepusta nowa wartosc nadpisuje, pusta NIE kasuje.
    'edges' (lista) obslugujemy osobno w _merge_dane — tu pomijamy."""
    for k, v in (nowe or {}).items():
        if k in ("id", "usun", "edges"):
            continue
        if str(v or "").strip():
            stare[k] = v
    return stare


def _merge_dane(conv_id, out):
    """Scala pozycje i wspolne z tury LLM ze stanem. Dopasowanie po id (fallback: po nazwie
    produktu, gdy LLM zgubi id i pasuje dokladnie jedna pozycja). Pozycja nieobecna
    w odpowiedzi ZOSTAJE; usuwa ja wylacznie jawne usun=true. Zwraca scalony stan."""
    stan = _load_dane(conv_id)
    for p in (out.get("pozycje") or []):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        istn = None
        if pid:
            istn = next((x for x in stan["pozycje"] if str(x.get("id")) == pid), None)
        else:
            prod = str(p.get("produkt") or "").strip().lower()
            kandydaci = [x for x in stan["pozycje"]
                         if prod and str(x.get("produkt") or "").strip().lower() == prod]
            if len(kandydaci) == 1:
                istn = kandydaci[0]
        if p.get("usun"):
            if istn is not None:
                stan["pozycje"].remove(istn)
            continue
        if istn is None:
            if not any(str(p.get(k) or "").strip() for k in _POZ_POLA):
                continue  # pusta pozycja bez tresci - ignoruj
            target = {"id": pid or _nowe_id(stan["pozycje"])}
            stan["pozycje"].append(_merge_pola(target, p))
        else:
            target = istn
            _merge_pola(istn, p)
        # Krawedzie — poza _merge_pola. Znormalizowana niepusta lista (round/chamfer) zastepuje.
        # Jawne 'sharp'/ostre (raw_ma_sharp) = usun obrobke -> czysc. Puste bez sharp (LLM domyslnie
        # []) NIE kasuje istniejacych — klient nie musi powtarzac krawedzi co ture.
        raw_edges = p.get("edges")
        ed = crm_calc.normalize_edges(raw_edges)
        if ed:
            target["edges"] = ed
        elif crm_calc.raw_ma_sharp(raw_edges):
            target["edges"] = []   # klient wybral ostre / usunięcie obróbki
    _merge_pola(stan["wspolne"], out.get("wspolne") or {})
    _zapisz_dane(conv_id, stan)
    return stan


def _z_dict(d):
    """Buduje znormalizowany wynik tury z dict-a LLM."""
    return {"odpowiedz": (d.get("odpowiedz") or "").strip(),
            "handoff": bool(d.get("handoff")),
            "powod": (d.get("powod") or "").strip(),
            "send_image": (d.get("send_image") or "").strip(),
            "pozycje": d.get("pozycje") if isinstance(d.get("pozycje"), list) else [],
            "wspolne": d.get("wspolne") if isinstance(d.get("wspolne"), dict) else {},
            "porownania": d.get("porownania") if isinstance(d.get("porownania"), list) else []}


def _znajdz_json(txt):
    """Wyciaga pierwszy zbalansowany obiekt {...} z tekstu (przypadek proza+JSON) i parsuje.
    Zwraca dict albo None — chroni przed wyciekiem surowego JSON do klienta."""
    start = (txt or "").find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(txt)):
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        d = json.loads(txt[start:i + 1])
                        if isinstance(d, dict):
                            return d
                    except Exception:
                        pass
                    break
        start = txt.find("{", start + 1)
    return None


def _parse_llm(raw):
    """Parsuje odpowiedz LLM do dict. Toleruje ploty ```json (takze kilka blokow) oraz JSON
    osadzony w prozie. Dopiero gdy nie ma zadnego JSON -> caly tekst jako odpowiedz."""
    txt = (raw or "").strip()
    candidates = re.findall(r"```(?:json)?\s*(.+?)\s*```", txt, re.DOTALL) or [txt]
    for cand in candidates:
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return _z_dict(d)
        except Exception:
            continue
    emb = _znajdz_json(txt)   # proza + JSON -> uzyj osadzonego obiektu (bez wycieku JSON do klienta)
    if emb is not None:
        return _z_dict(emb)
    # Fallback: model zignorowal format — traktujemy calosc jako tekst do klienta.
    return {"odpowiedz": txt, "handoff": False, "powod": "", "send_image": "",
            "pozycje": [], "wspolne": {}, "porownania": []}


# --- Podsumowanie do potwierdzenia + notatka dla agenta ---

_POLA_POZYCJI = [("dlugosc", "Długość"), ("szerokosc", "Szerokość"), ("grubosc", "Grubość"),
                 ("gatunek", "Gatunek"), ("technologia", "Technologia"), ("klasa", "Klasa"),
                 ("wykonczenie", "Wykończenie"), ("otwory", "Otwory/wycięcia"),
                 ("schody", "Schody")]
_POLA_WSPOLNE = [("termin", "Termin"), ("kontakt", "Kontakt")]
_CM_POLA = ("dlugosc", "szerokosc", "grubosc")
_TYP_EDGE_PL = {"sharp": "ostre", "chamfer": "fazowane", "round": "zaokrąglone"}


def _opis_edges(edges):
    """Czytelny opis krawedzi do podsumowania, grupowany po (typ, promien/kat):
    'R3 (C, A, D); R5 (E)' dla zaokrąglen, 'Fazowanie 45° (E)' dla faz, 'Ostre (A)' dla sharp."""
    grupy = {}   # klucz -> [etykieta, [litery]]
    for e in edges or []:
        if not (isinstance(e, dict) and e.get("litera") and e.get("typ")):
            continue
        typ = e["typ"]
        r_value, angle = e.get("r_value"), e.get("angle_value")
        if typ == "round":
            etyk = "R%s" % r_value if r_value is not None else "Zaokrąglone"
        elif typ == "chamfer":
            etyk = "Fazowanie %s°" % angle if angle is not None else "Fazowanie"
        else:
            etyk = _TYP_EDGE_PL.get(typ, typ).capitalize()
        grupy.setdefault((typ, r_value, angle), [etyk, []])[1].append(e["litera"])
    return "; ".join("%s (%s)" % (etyk, ", ".join(lit)) for etyk, lit in grupy.values())


def _fmt_cm(v):
    """Dokleja jednostke do golej liczby (LLM zapisuje wymiary w cm); wartosc z tekstem zostaje."""
    v = str(v or "").strip()
    return v + " cm" if re.fullmatch(r"[\d.,]+", v) else v


def _naglowek_pozycji(poz):
    """Naglowek bloku pozycji: 'Blat — 2 szt.' (ilosc nie-liczbowa doklejana bez 'szt.')."""
    prod = (str(poz.get("produkt") or "").strip() or "Produkt").capitalize()
    il = str(poz.get("ilosc") or "").strip()
    if re.fullmatch(r"\d+", il):
        return "%s — %s szt." % (prod, il)
    if il:
        return "%s — %s" % (prod, il)
    return prod


def _wykonczenie_opis(poz, options):
    """Opis wykonczenia do podsumowania: pelna sciezka z katalogu (z kolorem/polyskiem) gdy jest
    finishing_id, np. 'Lakierowane > Barwne > BRUNAT 22-15'; inaczej surowy tekst 'wykonczenie'."""
    fid = str(poz.get("finishing_id") or "").strip()
    if fid and options:
        fp = crm_calc.finishing_full_path(fid, options)
        if fp:
            return fp.replace("/", " > ")
    return str(poz.get("wykonczenie") or "").strip()


def _czy_barwny_lakier(poz, options):
    """True gdy wykonczenie to lakier BARWNY (kolorowy) — dla niego nie mamy trafnej probki
    (plik pokazuje bezbarwne), wiec probki nie wysylamy. 'bezbarwne' -> False."""
    fid = str(poz.get("finishing_id") or "").strip()
    fp = crm_calc.finishing_full_path(fid, options).lower() if (fid and options) else ""
    tekst = (fp + " " + str(poz.get("wykonczenie") or "")).lower()
    return "barwn" in tekst and "bezbarwn" not in tekst


def _bloki_pozycji(dane, options=None):
    """Linie podsumowania: blok na pozycje (numerowany przy >1) + pola wspolne na koncu.
    Wykonczenie pokazujemy z katalogu (z kolorem) gdy podano options + finishing_id."""
    lines = []
    pozycje = dane.get("pozycje") or []
    wiele = len(pozycje) > 1
    for i, poz in enumerate(pozycje, 1):
        naglowek = _naglowek_pozycji(poz)
        lines.append("%d. %s" % (i, naglowek) if wiele else naglowek)
        for k, label in _POLA_POZYCJI:
            v = _wykonczenie_opis(poz, options) if k == "wykonczenie" else str(poz.get(k) or "").strip()
            if not v:
                continue
            lines.append("%s: %s" % (label, _fmt_cm(v) if k in _CM_POLA else v))
        opis_kraw = _opis_edges(poz.get("edges"))
        if opis_kraw:
            lines.append("Krawędzie: %s" % opis_kraw)
        lines.append("")
    for k, label in _POLA_WSPOLNE:
        v = str((dane.get("wspolne") or {}).get(k) or "").strip()
        if v:
            lines.append("%s: %s" % (label, v))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _podsumowanie_msg(dane, options=None):
    """Deterministyczne podsumowanie wyceny do potwierdzenia przez klienta (bez LLM)."""
    lines = ["Podsumowuję dane do wyceny:", ""]
    lines += _bloki_pozycji(dane, options)
    lines += ["", "Czy wszystko się zgadza? Jeśli tak, przygotuję wycenę."]
    return "\n".join(lines)


def _summary_note(dane, powod):
    """Prywatna notatka-podsumowanie dla agenta po handoffie (z kolorem wykonczenia z katalogu)."""
    lines = ["🤖 Asystent AI v1 (wycena) — przekazanie do konsultanta", "Powód: %s" % (powod or "-")]
    bloki = _bloki_pozycji(dane or _pusty_stan(), crm_calc.get_options())
    if bloki:
        lines.append("")
        lines += bloki
    return "\n".join(lines)


# --- Straznik kompletnosci danych do wyceny (per pozycja) ---
# Pola krytyczne wspolne dla kazdego produktu; wymiary (blat/parapet) albo 'schody' (schody)
# dokladane zaleznie od produktu pozycji. Otwory/krawedzie NIE sa wymagane (klient moze
# je podac sam — wtedy trafiaja do podsumowania), bot ich nie proponuje.
_KRYT_WSPOLNE = ("gatunek", "technologia", "klasa", "ilosc", "wykonczenie")

# Powody handoffu, ktore straznik PRZEPUSZCZA (A: czlowiek, C: poza wiedza, sprawy
# indywidualne) — to nie sa roszczenia o "komplet danych", brak pol nie moze ich blokowac.
# Uwaga: 'zwrot' z koncowka fleksyjna, zeby 'kontakt zwrotny' nie pasowal.
# 'zmiana/zmienic ... (adres/dostawa/zamowienie)' = modyfikacja ISTNIEJACEGO zamowienia (nie
# korekta wyceny) — dopuszcza dowolne slowa miedzy "zmiana" a przedmiotem (np. "zmiana adresu
# dostawy w zamowieniu"); regresja S17 (E2E 2026-07-06), gdzie waski 'zmian\w* zam' nie lapal.
# Celowo BEZ golego 'dane' (zeby "zmiana danych do wyceny" nie przeszla jako sprawa indywidualna).
_POWOD_PRZEPUSC = re.compile(
    r"(człowiek|czlowiek|konsultant|doradc|pracownik|poza (wiedz|zakres)|"
    r"nie wiem|nie potrafi|reklamacj|status zam|faktur|"
    r"zwrot(u|em|ów|ow|y)?\b|indywidualn|"
    r"zmi[ae]ń?\w*.{0,40}(adres|dostaw|zam(ó|o)wien))", re.IGNORECASE)

# Etykiety pol do backstopowego pytania o braki (gdy LLM ustawil handoff mimo brakow).
_ETYKIETY_PYTAN = {
    "produkt": "co dokładnie mamy wycenić (blat, parapet czy schody)",
    "dlugosc": "długość (w cm)",
    "szerokosc": "szerokość (w cm)",
    "grubosc": "grubość (w cm)",
    "gatunek": "gatunek drewna (dąb, jesion lub buk)",
    "technologia": "technologię (lita czy mikrowczep)",
    "klasa": "klasę drewna (A/B, a dla dębu również B/B)",
    "ilosc": "ilość (liczba sztuk)",
    "wykonczenie": "wykończenie (surowe, olejowane czy lakierowane)",
    "finishing_id": "dokładny rodzaj wykończenia — przy oleju lub lakierze proszę o kolor i poziom "
                    "połysku (mat / półmat / połysk)",
    "schody": "szczegóły schodów (liczba stopni, wymiar stopnia, podstopnice)",
}


def _brakujace_pozycji(poz):
    """Brakujace pola krytyczne jednej pozycji (kolejnosc = kolejnosc dopytywania)."""
    def pusto(k):
        return not str(poz.get(k) or "").strip()
    if pusto("produkt"):
        return ["produkt"]
    produkt = str(poz.get("produkt")).strip().lower()
    brak = []
    if "schod" in produkt or "stopni" in produkt or "stopie" in produkt:
        if pusto("schody"):
            brak.append("schody")
    else:
        for k in ("dlugosc", "szerokosc", "grubosc"):
            if pusto(k):
                brak.append(k)
    for k in _KRYT_WSPOLNE:
        if pusto(k):
            brak.append(k)
    # Dla oleju/lakieru wymagamy konkretnego wariantu (finishing_id z kolorem/polyskiem) — bez tego
    # wycena nie policzy sie i bot spadlby do dopytania po podsumowaniu. Surowe = brak finishing_id OK.
    wyk = str(poz.get("wykonczenie") or "").lower()
    if wyk and "surow" not in wyk and pusto("finishing_id"):
        brak.append("finishing_id")
    return brak


def _brakujace(dane):
    """Lista (pozycja, pole) brakow krytycznych calej wyceny; pusta = komplet KAZDEJ pozycji.
    Bez zadnej pozycji -> najpierw ustal produkt."""
    pozycje = dane.get("pozycje") or []
    if not pozycje:
        return [({}, "produkt")]
    out = []
    for poz in pozycje:
        for k in _brakujace_pozycji(poz):
            out.append((poz, k))
    return out


def _czy_powod_kompletu(powod):
    """True gdy handoff to roszczenie o 'komplet danych' (B) — pilnuje go straznik.
    False dla A/C i spraw indywidualnych — te przepuszczamy zawsze."""
    return not _POWOD_PRZEPUSC.search(powod or "")


def _pytanie_o_braki(brak, wiele_pozycji):
    """Backstop: pyta o WSZYSTKIE braki PIERWSZEJ niekompletnej pozycji naraz — listą, każdy
    punkt od myślnika. Przy wielu pozycjach wskazuje, o który produkt pytamy."""
    poz = brak[0][0]
    pola = [k for p, k in brak if p is poz]
    etyk = [_ETYKIETY_PYTAN.get(k, k) for k in pola]
    prefiks = ""
    nazwa = str(poz.get("produkt") or "").strip()
    if wiele_pozycji and nazwa:
        prefiks = " (%s)" % nazwa
    if len(etyk) == 1:
        return "Żeby przygotować wycenę, potrzebuję jeszcze%s: %s." % (prefiks, etyk[0])
    naglowek = "Żeby przygotować wycenę%s, potrzebuję jeszcze:" % prefiks
    return naglowek + "\n" + "\n".join("- %s" % e for e in etyk)


# --- Koperta maksimow (cm) — egzekwowana w kodzie niezaleznie od LLM/persony ---
# Grubosc celowo poza kodem (obsluguje persona: >4 ponadstandardowa, <1.5 niestandardowa).
_MAX_SZEROKOSC = 120
_MAX_DLUGOSC_LITA = 450
_MAX_DLUGOSC_MIKRO = 500


def _liczby(txt):
    """Wyciaga liczby (float) z tekstu; przecinek dziesietny -> kropka."""
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", txt or "")]


def _technologia_typ(poz):
    """'lita' | 'mikrowczep' | None na podstawie pola technologia pozycji."""
    t = str(poz.get("technologia") or "").lower()
    if "lit" in t:
        return "lita"
    if "mikro" in t or "wczep" in t:
        return "mikrowczep"
    return None


def _fmt(x):
    """Liczba bez zbednego .0 (860.0 -> '860', 3.8 -> '3.8')."""
    return str(int(x)) if x == int(x) else str(x)


def _walidacja_pozycji(poz):
    """Twarda walidacja koperty jednej pozycji. Komunikat odrzucenia albo None."""
    szer = _liczby(poz.get("szerokosc"))
    dlug = _liczby(poz.get("dlugosc"))
    szerokosc = szer[0] if szer else None
    dlugosc = dlug[0] if dlug else None
    if szerokosc is not None and szerokosc > _MAX_SZEROKOSC:
        return ("Maksymalna szerokość naszych blatów to %d cm, a podana to %s cm. "
                "Proszę o korektę szerokości." % (_MAX_SZEROKOSC, _fmt(szerokosc)))
    if dlugosc is not None:
        tech = _technologia_typ(poz)
        if tech == "lita":
            if dlugosc > _MAX_DLUGOSC_LITA:
                return ("Dla technologii litej maksymalna długość to %d cm (dla mikrowczepu 500 cm), "
                        "a podana to %s cm. Proszę o korektę długości lub zmianę technologii na mikrowczep."
                        % (_MAX_DLUGOSC_LITA, _fmt(dlugosc)))
        else:  # mikrowczep albo technologia nieznana -> limit absolutny 500
            if dlugosc > _MAX_DLUGOSC_MIKRO:
                return ("Maksymalna długość to %d cm (mikrowczep), a podana to %s cm. "
                        "Proszę o korektę długości." % (_MAX_DLUGOSC_MIKRO, _fmt(dlugosc)))
    return None


def _walidacja_wymiarow(dane):
    """Walidacja koperty per pozycja; pierwszy blad wygrywa. Przy wielu pozycjach
    komunikat wskazuje produkt, ktorego dotyczy odrzucenie."""
    pozycje = dane.get("pozycje") or []
    wiele = len(pozycje) > 1
    for poz in pozycje:
        msg = _walidacja_pozycji(poz)
        if msg:
            nazwa = str(poz.get("produkt") or "").strip()
            if wiele and nazwa:
                return "%s Dotyczy pozycji: %s." % (msg, nazwa)
            return msg
    return None


# --- Handoff + podsumowanie ---

def _do_handoff(conv_id, powod, dane, closing=CLOSING_MSG):
    """Przekazanie rozmowy agentom: NAJPIERW toggle statusu (open), potem notatka i domkniecie.
    Kolejnosc celowa: gdy toggle padnie, rzucamy PRZED wyslaniem czegokolwiek do klienta —
    retry w workerze przebiega czysto, bez zdublowanych wiadomosci."""
    if not cw_bot_handoff(conv_id, token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: handoff nieudany (conv %s)" % conv_id)
    # Reset stanu (licznik tur + awaiting_confirm + dane): gdy agent odda rozmowe botowi
    # (open->pending), bot startuje od zera.
    c = db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()
    cw_note(conv_id, _summary_note(dane, powod), token=BOT_QUOTE_CW_AGENT_TOKEN)
    cw_agent_reply(conv_id, closing, token=BOT_QUOTE_CW_AGENT_TOKEN)
    log("quotebot: handoff conv %s (%s)" % (conv_id, powod))


def _wyslij_cene_i_kontakt(conv_id, dane, identity):
    """Liczy cene przez API, wysyla ja klientowi. Gdy jest email/telefon (z tozsamosci) —
    zapisuje wycene i dosyla link; inaczej ustawia awaiting_contact i miekko prosi o kontakt.
    Rzuca RuntimeError gdy wysylka do Chatwoota padnie (retry w worker)."""
    options = crm_calc.get_options()
    wynik = crm_calc.calculate(dane.get("pozycje") or [], options)
    if not wynik.get("ok") or not wynik.get("totals"):
        # Nie da sie policzyc automatycznie (najczesciej: brak konkretnego wariantu wykonczenia dla
        # lakieru/oleju — kolor/polysk). NIE przekazujemy do konsultanta — prosimy o doprecyzowanie
        # i wracamy do zbierania (bez awaiting_confirm), zeby dokonczyc wycene.
        cw_agent_reply(conv_id, _PROSBA_DOPRECYZ, token=BOT_QUOTE_CW_AGENT_TOKEN)
        _set_awaiting(conv_id, False)
        _bump_turns(conv_id)
        log("quotebot: wycena nieudana (braki mapowania) -> prosba o doprecyzowanie (conv %s)" % conv_id)
        return
    if not cw_agent_reply(conv_id, _cena_msg(dane, wynik), token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: wysylka ceny nieudana (conv %s)" % conv_id)
    _set_priced(conv_id, True)
    _set_awaiting(conv_id, False)
    _bump_turns(conv_id)

    # Kontakt z dowolnego zrodla (stan / czat / rekord Chatwoota) — jak mamy, zapisujemy od razu.
    email, phone, name = _effective_contact(conv_id, dane, identity)
    if email or phone:
        _zapisz_wycene(conv_id, dane, options, email, phone, name)
    else:
        if not cw_agent_reply(conv_id, _PROSBA_KONTAKT, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka prosby o kontakt nieudana (conv %s)" % conv_id)
        _set_awaiting_contact(conv_id, True)
    log("quotebot: cena wyslana (conv %s)" % conv_id)


def _zapisz_wycene(conv_id, dane, options, email, phone, name):
    """find-or-create klienta + zapis LUB aktualizacja wyceny + wyslanie linku.
    Gdy w stanie jest edit_uuid wczesniejszej wyceny -> AKTUALIZUJE ja (bez tworzenia sieroty).
    Powracajacy klient (dopasowany po email/tel) -> krotka wzmianka raz. Niepowodzenie zapisu
    nie wywraca tury — cena juz poszla; logujemy i zostawiamy bez linku."""
    kl = crm_calc.find_or_create_client(email, phone, name)
    client = (kl or {}).get("client") or {}
    if not kl.get("ok") or not client.get("id"):
        log("quotebot: find_or_create nieudane (conv %s): %s" % (conv_id, kl))
        return
    # Grupa 3: klient juz w bazie (dopasowany, nie utworzony) -> raz na rozmowe mila wzmianka.
    if kl.get("matched") and not _returning_greeted(conv_id):
        cw_agent_reply(conv_id, "Widzę wcześniejsze wyceny w naszym systemie. Miło nam, że znów Państwo do nas zaglądają 😊", token=BOT_QUOTE_CW_AGENT_TOKEN)
        _set_returning_greeted(conv_id, True)

    edit_uuid = _stored_edit_uuid(conv_id)
    if edit_uuid:
        q = crm_calc.update_quote(edit_uuid, dane.get("pozycje") or [], options)
    else:
        q = crm_calc.create_quote(dane.get("pozycje") or [], options, client["id"])
    if q.get("ok") and q.get("public_url"):
        if q.get("edit_uuid"):
            _set_edit_uuid(conv_id, q["edit_uuid"])   # zapamietaj do kolejnych aktualizacji
        czasownik = "Zaktualizowałem" if edit_uuid else "Zapisałem"
        link = "%s wycenę %s. Link: %s" % (czasownik, q.get("quote_number") or "", q["public_url"])
        cw_agent_reply(conv_id, link, token=BOT_QUOTE_CW_AGENT_TOKEN)
        _set_quote_saved(conv_id, True)
        _set_awaiting_contact(conv_id, False)
        log("quotebot: wycena %s (conv %s, %s)"
            % ("zaktualizowana" if edit_uuid else "zapisana", conv_id, q.get("quote_number")))
        if not edit_uuid:
            # Pierwszy zapis wyceny -> RAZ zaproponuj oszacowanie wysylki (kolejne aktualizacje nie).
            if cw_agent_reply(conv_id, _WYSYLKA_OFERTA, token=BOT_QUOTE_CW_AGENT_TOKEN):
                _set_awaiting_postcode(conv_id, True)
    else:
        log("quotebot: zapis/aktualizacja wyceny nieudana (conv %s): %s" % (conv_id, q))


def _obsluz_wysylke(conv_id, kod):
    """Liczy wysylke przez API dla zebranych pozycji + kodu pocztowego, wysyla najtansza opcje i
    (gdy jest zapisana wycena) dopisuje kuriera+koszt do wyceny. Nie rzuca — blad = komunikat o
    konsultancie (obraz/zapis wysylki nie moze wywrocic tury)."""
    dane = _load_dane(conv_id)
    options = crm_calc.get_options()
    res = crm_calc.shipping_quote(dane.get("pozycje") or [], kod, options)
    cw_agent_reply(conv_id, _wysylka_msg(res), token=BOT_QUOTE_CW_AGENT_TOKEN)
    edit_uuid = _stored_edit_uuid(conv_id)
    if res.get("ok") and res.get("carriers") and edit_uuid:
        q = crm_calc.update_quote(edit_uuid, dane.get("pozycje") or [], options,
                                  courier_name=res.get("carrier_name"),
                                  shipping_netto=res.get("shipping_netto"),
                                  shipping_brutto=res.get("shipping_brutto"))
        if q.get("ok"):
            log("quotebot: wysylka dopisana do wyceny (conv %s, %s)" % (conv_id, res.get("carrier_name")))
        else:
            log("quotebot: nieudane dopisanie wysylki do wyceny (conv %s): %s" % (conv_id, q))
    _bump_turns(conv_id)


def _wyslij_probki(conv_id, dane, options=None):
    """Deterministycznie dokleja probki wybranej konfiguracji (lookup po nazwie pliku).
    Nigdy nie rzuca — obraz nie moze wywrocic tury po wyslanym podsumowaniu. Dedup + cap.
    Barwny lakier POMIJAMY — plik probki pokazuje bezbarwne (inny wyglad); klient widzi wzornik."""
    wyslane = _sent_images(conv_id)
    ile = 0
    for poz in (dane.get("pozycje") or []):
        if ile >= _MAX_PROBEK:
            break
        if _czy_barwny_lakier(poz, options):
            continue
        key = images.sample_key(poz)
        if not key or key in wyslane:
            continue
        sciezka = images.resolve_sample(poz)
        if not sciezka:
            continue
        if cw_agent_reply(conv_id, _PROBKA_PODPIS, image_path=sciezka,
                          image_name=os.path.basename(sciezka), image_mime="image/jpeg",
                          token=BOT_QUOTE_CW_AGENT_TOKEN):
            _mark_image_sent(conv_id, key)
            wyslane.add(key)
            ile += 1
        else:
            log("quotebot: wysylka probki nieudana (conv %s, %s)" % (conv_id, key))


# Klient pisze o obrobce krawedzi -> pokazujemy obraz z oznaczeniem krawedzi.
_KRAWEDZIE_RE = re.compile(r"(kraw[eę]d|zaokr[aą]gl|fazow|zfazuj|sfazuj|\bR\d)", re.IGNORECASE)
# Klient wybiera barwe/odcien lakieru -> pokazujemy wzornik kolorow.
_KOLOR_RE = re.compile(r"(barwn|odcie[nń]|wzornik|palet[aę]|jaki[ei]? kolor|kt[oó]ry kolor)", re.IGNORECASE)


def _wyslij_obraz_kontekstowy(conv_id, key):
    """Wysyla obraz kontekstowy (wymiary/krawedzie) RAZ na rozmowe (dedup jak probki).
    Nigdy nie rzuca — obraz pomocniczy nie moze wywrocic tury."""
    dedup = "ctx:" + key
    if dedup in _sent_images(conv_id):
        return
    sciezka = images.resolve_context(key)
    if not sciezka:
        return
    meta = images.CONTEXT_IMAGES.get(key) or {}
    if cw_agent_reply(conv_id, meta.get("podpis") or "", image_path=sciezka,
                      image_name=meta.get("nazwa"), image_mime=meta.get("mime") or "image/jpeg",
                      token=BOT_QUOTE_CW_AGENT_TOKEN):
        _mark_image_sent(conv_id, dedup)


def _obrazy_kontekstowe(conv_id, content, dane):
    """Deterministyczne obrazy pomocnicze (raz na rozmowe): krawedzie — gdy klient pisze o
    obrobce krawedzi; kolory — gdy klient wybiera barwe/odcien lakieru (wzornik); wymiary — gdy
    pierwsza pozycja (nie-schody) nie ma kompletu wymiarow, czyli bot bedzie o nie pytal."""
    if _KRAWEDZIE_RE.search(content or ""):
        _wyslij_obraz_kontekstowy(conv_id, "krawedzie")
    if _KOLOR_RE.search(content or ""):
        _wyslij_obraz_kontekstowy(conv_id, "kolory")
    pozycje = dane.get("pozycje") or []
    if pozycje:
        poz = pozycje[0]
        if "schod" not in str(poz.get("produkt") or "").lower() and any(
                not str(poz.get(k) or "").strip() for k in ("dlugosc", "szerokosc", "grubosc")):
            _wyslij_obraz_kontekstowy(conv_id, "wymiary")


def _wyslij_podsumowanie(conv_id, dane):
    """Wysyla WYLACZNIE deterministyczne podsumowanie (bez prozy LLM — koniec podwojnego
    'Potwierdzam parametry.../Podsumowuje dane...'). Ustawia stan oczekiwania na potwierdzenie,
    po czym dokleja probki wybranej konfiguracji (jesli sa).
    Kolejnosc CELOWO wysylka -> stan: gdy POST padnie, retry ponawia ture bez awaiting i
    podsumowanie dociera; stan-przed-wysylka po nieudanym POST omijalby podsumowanie."""
    options = crm_calc.get_options()   # do pokazania koloru w podsumowaniu + pominiecia probki barwnego lakieru
    if not cw_agent_reply(conv_id, _podsumowanie_msg(dane, options), token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: wysylka podsumowania nieudana (conv %s)" % conv_id)
    _set_awaiting(conv_id, True)
    _bump_turns(conv_id)
    _wyslij_probki(conv_id, dane, options)
    log("quotebot: podsumowanie do potwierdzenia (conv %s)" % conv_id)


def run_quote_turn(conv_id, inbox_id, message_id, content, attachments=None):
    """Pelna tura bota. Rzuca RuntimeError przy braku odpowiedzi LLM (retry w workerze)."""
    # Cisza po handoffie: bot prowadzi TYLKO rozmowy w statusie pending.
    status = cw_conv_status(conv_id)
    if status is None:
        # Nie zgadujemy: bez statusu nie wolno pisac do klienta — retry w workerze.
        raise RuntimeError("quotebot: nie mozna odczytac statusu rozmowy (conv %s)" % conv_id)
    if status != "pending":
        log("quotebot: conv %s status=%s - bot milczy" % (conv_id, status))
        return

    # Bezpiecznik D: limit tur bota.
    if _bot_turns(conv_id) >= BOT_QUOTE_MAX_TURNS:
        _do_handoff(conv_id, "limit tur bota (bezpiecznik)", _load_dane(conv_id))
        return

    # Po wysłanej cenie czekamy na kontakt (miękko). Klient podał e-mail/telefon -> zapis.
    if _awaiting_contact(conv_id):
        email, phone = _wyciagnij_kontakt(content)
        if email or phone:
            _set_awaiting_contact(conv_id, False)
            nazwa = (cw_contact_full(conv_id) or {}).get("name") or ""
            _set_contact(conv_id, email, phone, nazwa)   # zapamietaj na kolejne wyceny
            _zapisz_wycene(conv_id, _load_dane(conv_id), crm_calc.get_options(), email, phone, nazwa)
            return
        if _ODMOWA_RE.search(content or ""):
            # Klient nie chce podawać kontaktu — respektujemy, koniec bez zapisu.
            _set_awaiting_contact(conv_id, False)
            cw_agent_reply(conv_id, "Jasne, nie ma problemu. Gdyby chciał Pan/Pani zapisać wycenę "
                           "lub coś doprecyzować — jestem do dyspozycji.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        # Ani kontakt, ani odmowa -> normalna tura (klient pyta o coś innego) — leci dalej.

    # Po zapisaniu wyceny proponujemy wysylke — czekamy na kod pocztowy dostawy.
    if _awaiting_postcode(conv_id):
        kod = _wyciagnij_kod(content)
        if kod:
            _set_awaiting_postcode(conv_id, False)
            _obsluz_wysylke(conv_id, kod)
            return
        if _ODMOWA_RE.search(content or ""):
            # Klient nie chce podawac kodu — respektujemy, koszt ustali konsultant.
            _set_awaiting_postcode(conv_id, False)
            cw_agent_reply(conv_id, "Jasne. Koszt wysyłki potwierdzi konsultant przy finalizacji "
                           "zamówienia.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        # Ani kod, ani odmowa (np. samo miasto lub inne pytanie) -> normalna tura;
        # flaga zostaje, LLM (wg reguly promptu) dopyta o kod, kolejny kod znow przechwycimy.

    # Reklamacja — twardy wyzwalacz RAZ: instrukcja mailowa, BEZ handoffu (bot zostaje w rozmowie).
    # Kolejne wiadomosci reklamacyjne (klient echuje adres/temat) ida do LLM, zeby odpowiedziec
    # na follow-up zamiast powtarzac canned (fix petli reklamacji z E2E tura 3).
    if _czy_reklamacja(content) and not _complaint_sent(conv_id):
        if not cw_agent_reply(conv_id, COMPLAINT_MSG, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka instrukcji reklamacji nieudana (conv %s)" % conv_id)
        _set_complaint_sent(conv_id, True)
        _bump_turns(conv_id)
        log("quotebot: reklamacja - instrukcja mailowa, bez handoffu (conv %s)" % conv_id)
        return

    # Prosba o czlowieka. Guard: pytanie o tozsamosc -> pomijamy (niech LLM odpowie uczciwie).
    # W stanie potwierdzenia (komplet zebrany) prosba o konsultanta = przekaz od razu, bez deflect.
    if _czy_prosi_o_czlowieka(content) and not _PYTANIE_O_BOTA_RE.search(content or ""):
        if _awaiting_confirm(conv_id) or _human_deflected(conv_id):
            _do_handoff(conv_id, "klient prosi o konsultanta", _load_dane(conv_id))
            return
        if not cw_agent_reply(conv_id, DEFLECT_MSG, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka odbicia nieudana (conv %s)" % conv_id)
        _set_human_deflected(conv_id, True)
        _bump_turns(conv_id)
        log("quotebot: miekkie odbicie prosby o czlowieka (conv %s)" % conv_id)
        return

    history = cw_messages(conv_id, BOT_HISTORY_LIMIT)
    identity = cw_contact(conv_id)
    query = (content or "").strip() or (history[-1]["text"] if history else "")
    knowledge = "\n\n".join(retrieve(query))
    dane_przed = _load_dane(conv_id)
    awaiting = _awaiting_confirm(conv_id)

    system = build_system_prompt("livechat", knowledge, identity) + "\n\n" + _FORMAT
    wl = images.whitelist_prompt()
    if wl:
        system += ("\n\nDOSTĘPNE OBRAZY (możesz dołączyć maks. jeden przez pole send_image, "
                   "tylko gdy realnie pomaga):\n" + wl)
    opts = crm_calc.get_options()
    fin = opts.get("finishing_options") or []
    if fin:
        lista = "\n".join("- id=%s — %s" % (o.get("id"), o.get("full_path")) for o in fin)
        system += "\n\nDOSTĘPNE WYKOŃCZENIA (wybierz finishing_id pasujący do klienta):\n" + lista
    if dane_przed["pozycje"] or dane_przed["wspolne"]:
        # Akumulowany stan w promptcie: LLM widzi wszystkie pozycje i ich id nawet wtedy,
        # gdy poczatek rozmowy wypadl poza limit historii.
        system += ("\n\nDOTYCHCZAS ZEBRANE DANE WYCENY (utrzymuj te id pozycji, aktualizuj "
                   "tylko to, co klient zmienia):\n" + json.dumps(dane_przed, ensure_ascii=False))
    if awaiting:
        system += "\n\n" + _CONFIRM_INSTR

    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["text"]} for m in history]
    if not history and (content or "").strip():
        messages.append({"role": "user", "content": content})

    # Faza 2: obrazy klienta z tej tury -> multimodalna wiadomosc do modelu (vision).
    if attachments:
        try:
            urls = json.loads(attachments) if isinstance(attachments, str) else (attachments or [])
        except Exception:
            urls = []
        if urls:
            attach_images(messages, urls)

    raw = chat(messages)
    if not raw:
        raise RuntimeError("quotebot: brak odpowiedzi modelu")
    out = _parse_llm(raw)
    dane = _merge_dane(conv_id, out)   # akumulacja per pozycja: raz zebrane pole zostaje
    # Obrazy pomocnicze (wymiary/krawedzie) — raz na rozmowe, wg tresci klienta i kompletu wymiarow.
    _obrazy_kontekstowe(conv_id, content, dane)

    # 'zmienione' liczymy TYLKO po POZYCJACH (spec wyceny). Zmiana pol wspolnych
    # (kontakt/termin) — np. gdy LLM sam dopisze kontakt z tozsamosci klienta — NIE ponawia
    # podsumowania i nie tlumi odpowiedzi na pytanie w stanie awaiting (regresja S54 E2E 2026-07-06).
    zmienione = dane.get("pozycje") != dane_przed.get("pozycje")

    # Porownanie wariantu (inny gatunek/technologia/klasa) — TYLKO informacja, bez edycji wyceny.
    # Gdy klient w tej turze dodal/zmienil pozycje (zmienione) — to NIE porownanie: dodanie produktu
    # ma pierwszenstwo (fix kolizji 'dodaj jeszcze blat ... te same parametry' -> bledne porownanie).
    if _czy_porownanie(conv_id, out, dane, zmienione):
        if _obsluz_porownania(conv_id, dane, out["porownania"]):
            return

    # Straznik wymiarow (deterministyczny) + loop-breaker: 2. to samo odrzucenie -> podpowiedz cm,
    # 3. -> handoff (koniec nieskonczonej petli, np. mm mylone z cm).
    odrzucenie = _walidacja_wymiarow(dane)
    if odrzucenie:
        sig_prev, cnt_prev = _reject_state(conv_id)
        cnt = cnt_prev + 1 if odrzucenie == sig_prev else 1
        if cnt >= 3:
            _do_handoff(conv_id, "wymiar poza zakresem — do ustalenia z konsultantem", dane)
            return
        _set_reject(conv_id, odrzucenie, cnt)
        msg = odrzucenie
        if cnt >= 2:
            msg += ("\n\nJeśli podał Pan/Pani wymiar w milimetrach, proszę o wartość w "
                    "centymetrach (np. 65 zamiast 650).")
        if not cw_agent_reply(conv_id, msg, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka odrzucenia wymiaru nieudana (conv %s)" % conv_id)
        _bump_turns(conv_id)
        log("quotebot: odrzucony wymiar (conv %s, powt %s)" % (conv_id, cnt))
        return
    if _reject_state(conv_id)[1]:
        _set_reject(conv_id, "", 0)   # walidacja OK -> reset licznika odrzucen

    brak = _brakujace(dane)

    # Wyzwalacze B/C (decyzja LLM) + straznik kompletnosci + bramka potwierdzenia.
    if out["handoff"]:
        powod = out["powod"] or "decyzja bota"
        if _czy_powod_kompletu(powod):
            if brak:
                # Braki -> nie oddajemy rozmowy, dopytujemy (backstop).
                reply = _pytanie_o_braki(brak, len(dane["pozycje"]) > 1)
                if not cw_agent_reply(conv_id, reply, token=BOT_QUOTE_CW_AGENT_TOKEN):
                    raise RuntimeError("quotebot: wysylka pytania o braki nieudana (conv %s)" % conv_id)
                _bump_turns(conv_id)
                log("quotebot: straznik wstrzymal handoff, braki: %s (conv %s)"
                    % (",".join(k for _, k in brak), conv_id))
                return
            if not awaiting:
                # Bramka: podsumowanie dopiero PO nim wycena, gdy klient potwierdzi.
                _wyslij_podsumowanie(conv_id, dane)
                return
            # Komplet + awaiting + LLM zgłosił potwierdzenie -> licz cenę zamiast handoffu.
            _wyslij_cene_i_kontakt(conv_id, dane, cw_contact_full(conv_id))
            return
        _do_handoff(conv_id, powod, dane)
        return

    # Bez handoffu: komplet wymaganych -> podsumowanie (pierwsze lub po korekcie danych).
    if not brak and _priced(conv_id) and not zmienione:
        # Cena juz wyslana, dane bez zmian -> NIE ponawiamy podsumowania/potwierdzenia (petla
        # podsumowanie->potwierdzenie->cena). Niejednoznaczna wiadomosc leci do zwyklej
        # odpowiedzi LLM nizej, bez ponownego uzbrajania awaiting_confirm.
        pass
    elif not brak:
        if not awaiting or zmienione:
            _wyslij_podsumowanie(conv_id, dane)
            return
        # Awaiting bez zmian: czyste potwierdzenie -> licz cenę deterministycznie (nie czekamy na LLM).
        if _jest_potwierdzenie(content):
            _wyslij_cene_i_kontakt(conv_id, dane, cw_contact_full(conv_id))
            return
        if not out["odpowiedz"]:
            # Pusta odpowiedz przy komplecie -> ponow podsumowanie zamiast rzucac (falszywy handoff).
            _wyslij_podsumowanie(conv_id, dane)
            return
        # awaiting bez zmian, nie-potwierdzenie -> klient pyta o cos innego, zwykla odpowiedz nizej.
    elif awaiting:
        _set_awaiting(conv_id, False)

    reply = out["odpowiedz"]
    if not reply:
        if _priced(conv_id):
            # Po wycenie klient napisal cos konwersacyjnego (np. „zostajemy przy dębie”), a model
            # nie dal tresci (czasem echuje samo 'porownania' zdjete przez dedup) — nie rzucamy ani
            # nie petlimy; cicho konczymy ture.
            _bump_turns(conv_id)
            return
        raise RuntimeError("quotebot: pusta odpowiedz modelu")
    # 1a: obraz semantyczny wybrany przez model (whitelist), raz na rozmowe.
    tag = out.get("send_image") or ""
    sciezka = images.resolve(tag) if tag else None
    if sciezka and tag not in _sent_images(conv_id):
        meta = images.IMAGES[tag]
        ok = cw_agent_reply(conv_id, reply, image_path=sciezka,
                            image_name=meta["nazwa"], image_mime=meta["mime"],
                            token=BOT_QUOTE_CW_AGENT_TOKEN)
        if ok:
            _mark_image_sent(conv_id, tag)
    else:
        ok = cw_agent_reply(conv_id, reply, token=BOT_QUOTE_CW_AGENT_TOKEN)
    if not ok:
        raise RuntimeError("quotebot: wysylka odpowiedzi nieudana (conv %s)" % conv_id)
    _bump_turns(conv_id)
    log("quotebot: odpowiedz wyslana (conv %s, tura %s)" % (conv_id, _bot_turns(conv_id)))


def handoff_with_apology(conv_id):
    """Sciezka awaryjna (po wyczerpaniu retry): przeprosiny + przekazanie do agenta.
    Notatka dla konsultanta dziedziczy juz zebrane dane (nie zaczynamy od pustego stanu)."""
    _do_handoff(conv_id, "błąd techniczny bota (wyczerpane próby)", _load_dane(conv_id),
                closing=APOLOGY_MSG)
