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
# Komunikat dedykowany dla handoffu z limitu tur (LS-11) — nie zaklada, ze klient wlasnie cos podal.
LIMIT_MSG = ("Sporo już ustaliliśmy — przekazuję rozmowę do konsultanta WoodPower, który poprowadzi "
             "ją dalej (ma komplet naszych ustaleń).")
APOLOGY_MSG = ("Przepraszam, mam chwilowy problem techniczny z odpowiedzią. "
               "Przekazuję rozmowę do konsultanta WoodPower.")
# Wycena nie policzyla sie automatycznie (najczesciej lakier/olej bez koloru i polysku) —
# dopytujemy zamiast przekazywac do konsultanta.
_PROSBA_DOPRECYZ = ("Żeby dokończyć wycenę, potrzebuję jeszcze doprecyzowania wykończenia — przy "
                    "lakierze lub oleju proszę o kolor i poziom połysku (mat / półmat / połysk). "
                    "Które wybieramy?")

def _pytanie_z_missing(missing):
    """Buduje pytanie z pol 'missing_fields' /calculate (hinty sa juz po polsku). Pomija braki
    poziomu wyceny (client_type = konfiguracja bota, nie pytanie do klienta). None gdy brak pytania."""
    hinty = [str(m.get("hint") or "").strip() for m in (missing or [])
             if m.get("field") not in (None, "client_type", "products")]
    hinty = [h for h in hinty if h]
    if not hinty:
        return None
    uniq = list(dict.fromkeys(hinty))   # zachowaj kolejnosc, usun duplikaty
    if len(uniq) == 1:
        return "Żeby policzyć wycenę, potrzebuję jeszcze: %s." % uniq[0]
    return "Żeby policzyć wycenę, potrzebuję jeszcze:\n" + "\n".join("- %s" % h for h in uniq)


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
    "Gdy klient rezygnuje z pojedynczego szczegółu (np. otworów, terminu), wpisz w to pole "
    "wartość \"brak\" — system je wtedy wyczyści (puste pole niczego nie kasuje). "
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
    "Przy KAŻDEJ zmianie wykończenia (np. z lakieru na olej) ustaw NOWY finishing_id pasujący do "
    "nowego wyboru — nie zostawiaj starego. "
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
    "potwierdzić. Jeśli potwierdza (np. 'tak', 'zgadza się', 'ok', 'działajmy') — ustaw pole "
    "\"potwierdzono\": true i NIE ustawiaj handoff (cenę policzy i wyśle system, rozmowa NIE idzie "
    "do konsultanta). Jeśli coś koryguje lub dodaje — zaktualizuj pozycje (system wyśle nowe "
    "podsumowanie), potwierdzono=false i handoff=false. Jeśli pyta o coś innego — odpowiedz "
    "normalnie, potwierdzono=false i handoff=false."
)

# Prosba o czlowieka wymaga INTENCJI (czasownik prosby przy rzeczowniku-osobie), zeby wzmianka
# 'nasz pracownik odbierze' / 'jestem pracownikiem' nie wyzwalala handoffu (RX-04, MS-09).
_OSOBA = r"(?:konsultant\w*|człowiek\w*|czlowiek\w*|doradc\w*|pracownik\w*|agent\w*)"
_HUMAN_INTENCJA_RE = re.compile(
    r"(?:(?:popro\w*|prosz\w*|prosi\w*|chc[ęe]|chcia[łl]\w*|wol[ęe]|wola[łl]\w*|po[łl][aą]cz\w*|"
    r"prze[łl][aą]cz\w*|przeka[żz]\w*|daj\w*|dawa\w*|rozmawia\w*|porozmawia\w*|potrzebuj\w*)"
    r"[\s\S]{0,40}" + _OSOBA + r"|\bz\s+" + _OSOBA + r")", re.IGNORECASE)
# Prosba o oddzwonienie/telefon zwrotny = osobna intencja kontaktu z czlowiekiem (tryb rozkazujacy
# lub 'prosze o telefon' — 'maz zadzwoni' to NIE prosba).
_CALLBACK_RE = re.compile(
    r"(oddzwo[nń]cie|zadzwo[nń]cie|prosz[ęe][\s\S]{0,25}(telefon|oddzwo|zadzwo)|"
    r"telefon\s+zwrotn|numer\s+zwrotn)", re.IGNORECASE)

# Pytanie o tozsamosc rozmowcy — NIE traktujemy jako prosby o czlowieka; niech LLM odpowie uczciwie.
_PYTANIE_O_BOTA_RE = re.compile(
    r"(czy (jesteś|jestes) (botem|człowiekiem|czlowiekiem|robotem|prawdziw|maszyn)|"
    r"(jesteś|jestes) (botem|robotem|sztuczn|prawdziw|człowiek\w*|czlowiek\w*)|"
    r"czy rozmawiam z (botem|człowiekiem|czlowiekiem|robotem|maszyn|prawdziw|ai|sztuczn)|"
    r"z kim (rozmawiam|mam przyjemność|mam przyjemnosc)|"
    r"czy to (jest )?(bot|robot|ai|sztuczna)|"
    r"(bot|robot)\w* czy (z )?(człowiek|czlowiek)|(człowiek|czlowiek)\w* czy (z )?(bot|robot))",
    re.IGNORECASE)

# Reklamacja — twardy wyzwalacz. Sam rzeczownik uszkodzenia NIE wystarcza: musi byc intencja
# reklamacji ("reklamacj/reklamowa") ALBO uszkodzenie-DOKONANE (pekl/pekniety/uszkodzony — nie
# hipotetyczne 'pęknie') + kontekst posiadania (moj/zamowilem/dostalem), a przy tym BRAK intencji
# zakupu — zeby pytania przedsprzedazowe o trwalosc i motywacja zakupowa nie wyzwalaly handoffu.
_REKLAMACJA_RE = re.compile(r"(reklamacj\w*|reklamowa\w*)", re.IGNORECASE)
_USZKODZENIE_RE = re.compile(
    r"(pęk[łl]\w*|pek[łl]\w*|pękni[ę]\w*|pekniet\w*|popęka\w*|popek\w*|uszkodzon\w*|uszkodzi[łl]\w*|"
    r"wadliw\w*|zepsu[łt]\w*|wypaczy[łl]\w*|wypaczo\w*|odklei[łl]\w*|odpad[łl]\w*)", re.IGNORECASE)
_POSIADANIE_RE = re.compile(r"\b(mój|moje|moja|moim|kupił\w*|kupil\w*|kupion\w*|zamówi\w*|zamowi\w*|"
                            r"dostał\w*|dostal\w*|otrzymał\w*|otrzymal\w*|zamówieni\w*|zamowieni\w*)\b",
                            re.IGNORECASE)
_ZAKUP_RE = re.compile(r"(chc[ęe]\s+(kupi|za?m[oó]wi)|kupi[ćc]|zam[oó]wi[ćc]|szuka\w*|"
                       r"zainteresowan\w*|\bpoleca\w*)", re.IGNORECASE)


def _czy_reklamacja(text):
    """True gdy tresc to reklamacja: jawne 'reklamacj/reklamowa' ALBO uszkodzenie-dokonane +
    posiadanie, ale NIE gdy widac intencje zakupu (klient pyta o nowy produkt)."""
    t = text or ""
    if _REKLAMACJA_RE.search(t):
        return True
    if _USZKODZENIE_RE.search(t) and _POSIADANIE_RE.search(t):
        return not bool(_ZAKUP_RE.search(t))
    return False


COMPLAINT_MSG = ("Przykro nam z powodu problemu. Reklamacje przyjmujemy mailowo — prosimy o "
                 "wiadomość na reklamacje@woodpower.pl z numerem i szczegółami zamówienia oraz "
                 "zdjęciami reklamowanego produktu w treści maila. Nasz zespół reklamacji zajmie "
                 "się zgłoszeniem. Czy mogę jeszcze w czymś pomóc?")
DEFLECT_MSG = ("Jasne, mogę połączyć Pana/Panią z konsultantem. Zanim to zrobię — chętnie spróbuję "
               "pomóc od razu, często udaje się wszystko ustalić tu, na czacie. W czym mogę pomóc? "
               "A jeśli woli Pan/Pani rozmowę z konsultantem, od razu przełączę.")


def _czy_prosi_o_czlowieka(text):
    """True gdy tresc to prosba o czlowieka: intencja (prosba/rozmowa) przy rzeczowniku-osobie
    albo prosba o oddzwonienie. Sama wzmianka ('nasz pracownik', 'od konsultanta') -> False."""
    t = text or ""
    if _CALLBACK_RE.search(t):
        return True
    return bool(_HUMAN_INTENCJA_RE.search(t))


# Deterministyczne wykrycie potwierdzenia podsumowania (obok decyzji LLM). Lista rozszerzona o
# najczestsze polskie potwierdzenia (RX-12); _NEG lapie tez odmiany 'zmienic/zamiast/jednak' (RX-02).
_POTW_RE = re.compile(r"\b(tak|zgadza|zgadzam|potwierdzam|potwierdzone|ok|okej|okay|okey|zgoda|"
                      r"pasuje|dokładnie|dokladnie|wysyłam|wysylam|super|świetnie|swietnie|"
                      r"dobrze|dobra|jasne|git|spoko|zatwierdzam|działam\w*|dzialam\w*|bierzemy|"
                      r"zamawiam|w porządku|w porzadku|może być|moze byc|niech będzie|niech bedzie)\b",
                      re.IGNORECASE)
_NEG_RE = re.compile(r"\b(nie|źle|zle|błąd|blad|popraw\w*|zmie[ńn]\w*|zamiast|jednak|inaczej|niepopr\w*)\b",
                     re.IGNORECASE)


def _jest_potwierdzenie(text):
    """True tylko dla KROTKICH, jednoznacznych potwierdzen (bez negacji/korekty/pytania). Dluzsze
    wypowiedzi oddajemy LLM-owi ('ok, a co z transportem' -> nie potwierdzenie); 'nie zgadza sie'
    -> False; 'tak, ale zaokraglicie krawedzie?' -> False (pytanie -> LLM ma odpowiedziec)."""
    t = (text or "").strip()
    if "?" in t:
        return False
    if len(t.split()) > 4:
        return False
    return bool(_POTW_RE.search(t)) and not _NEG_RE.search(t)


# Powod handoffu wskazujacy potwierdzenie podsumowania (LLM czesto parafrazuje _CONFIRM_INSTR i
# dorzuca 'konsultanta') — w stanie awaiting traktujemy taki handoff jako potwierdzenie, nie oddanie.
_POTWIERDZ_POWOD_RE = re.compile(r"potwierdz", re.IGNORECASE)


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
# Komunikat przy nieudanym zapisie wyceny (MS-05) — koniec ciszy po podanym mailu.
_SAVE_FAIL_MSG = ("Dziękuję za kontakt! Mam chwilowy problem techniczny z zapisem wyceny — "
                  "przekazuję rozmowę do konsultanta WoodPower, który dośle link w tej rozmowie.")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Wlasne domeny firmowe — adres w nich (np. reklamacje@woodpower.pl, ktory bot sam wysyla)
# NIE jest kontaktem klienta (RX-07).
_WLASNE_DOMENY = ("woodpower.pl",)
# Kandydat na telefon: ciag cyfr z separatorami; realnosc numeru waliduje _waliduj_tel (RX-06,
# MS-10, SB-02 — odsiewa wymiary, NIP-y i numery zamowien).
_TEL_CAND_RE = re.compile(r"\+?\d[\d \-]{7,}\d")
_TEL_KONTEKST_ODRZUC = re.compile(r"(nip|zam[oó]wieni|faktur|\bnr\b|konto|iban|oferta|oferty|"
                                  r"mm|cm|×|\bx\b)", re.IGNORECASE)

# Jednoznaczna odmowa podania kontaktu/kodu — fraza intencji, nie gole 'nie'/'bez' (RX-05, LS-03,
# SB-03, MS-01). Odroczenie ('podam pozniej') NIE jest odmowa (flaga zostaje) — patrz _POZNIEJ_RE.
_ODMOWA_RE = re.compile(r"(nie\s*,?\s*dzięk\w*|nie\s*,?\s*dziek\w*|nie\s+chc\w*|nie\s+podam|"
                        r"nie\s+teraz|nie\s+trzeba|nie\s+musz\w*|rezygnuj\w*|pomi[nń]\w*|"
                        r"wol[ęe]\s+nie|obejdzie\s+si[eę]|bez\s+zapis\w*|bez\s+kontakt\w*)",
                        re.IGNORECASE)
_POZNIEJ_RE = re.compile(r"\b(p[oó][zź]niej|potem|za\s+chwil\w*|jutro|wr[oó]c[ęe]|"
                         r"odezw\w*|dam\s+zna[ćc])\b", re.IGNORECASE)

# Kod pocztowy: NN-NNN / 'NN NNN' / 'NNNNN'; z odsiewem zakresow wymiarow (40-120 cm) — RX-11,
# SB-07, MS-06.
_KOD_RE = re.compile(r"(?<!\d)(\d{2})[ -]?(\d{3})(?!\d)")
_KOD_KONTEKST_ODRZUC = re.compile(r"(cm|mm|\bmiędzy\b|\bmiedzy\b|\bod\b|\bdo\b|szerok|"
                                  r"długoś|dlugos|grubo|zakres|\bx\b|×)", re.IGNORECASE)


def _czy_odmowa(text):
    """True gdy tresc to jednoznaczna odmowa podania kontaktu/kodu. Pytanie (?) -> nie odmowa
    (oddajemy LLM). Gole 'nie'/'bez'/'pomiary' NIE gasi juz lejka."""
    t = text or ""
    if "?" in t:
        return False
    return bool(_ODMOWA_RE.search(t))


def _wyciagnij_kod(text):
    """Kod pocztowy z tekstu klienta (NN-NNN znormalizowany) albo None. Odrzuca zakresy wymiarow
    (kontekst cm/mm/miedzy/od/do/x) oraz pytania bez slow o wysylce."""
    t = str(text or "")
    if "?" in t and not re.search(r"(wysył|wysyl|dostaw|kod|paczk|kurier)", t, re.IGNORECASE):
        return None
    for m in _KOD_RE.finditer(t):
        okno = t[max(0, m.start() - 12):min(len(t), m.end() + 6)]
        if _KOD_KONTEKST_ODRZUC.search(okno):
            continue
        return "%s-%s" % (m.group(1), m.group(2))
    return None


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


def _waliduj_tel(cand):
    """Czy kandydat to realny numer PL: 9 cyfr krajowych (opcjonalny prefiks +48/0048), pierwsza
    cyfra 4-8 (odsiewa nr zamowienia '250...' i NIP 10-cyfrowy)."""
    cyfry = re.sub(r"\D", "", cand)
    if cyfry.startswith("0048") and len(cyfry) == 13:
        cyfry = cyfry[4:]
    elif cyfry.startswith("48") and len(cyfry) == 11:
        cyfry = cyfry[2:]
    if len(cyfry) != 9:
        return False
    return cyfry[0] in "45678"


def _wyciagnij_kontakt(text):
    """(email, telefon) z tekstu klienta; '' gdy brak. E-mail w domenie firmowej (woodpower.pl)
    odrzucany (RX-07). Telefon tylko realny numer PL, nie wymiary/NIP/nr zamowienia (RX-06/MS-10/SB-02)."""
    t = text or ""
    email = ""
    for m in _EMAIL_RE.finditer(t):
        adres = m.group(0)
        low = adres.lower()
        if any(low.endswith("@" + d) or ("@" + d) in low or low.endswith("." + d)
               for d in _WLASNE_DOMENY):
            continue
        email = adres
        break
    tel = ""
    for m in _TEL_CAND_RE.finditer(t):
        cand = m.group(0)
        if not _waliduj_tel(cand):
            continue
        okno = t[max(0, m.start() - 16):min(len(t), m.end() + 4)]
        if _TEL_KONTEKST_ODRZUC.search(okno):
            continue
        tel = cand.strip()
        break
    return email, tel


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


# Wartosci-sentinele kasujace pole (MD-04): klient rezygnuje z otworow/terminu/szczegolow.
_KASUJ_POLE = {"brak", "-", "—", "nie dotyczy", "rezygnuję", "rezygnuje"}


def _merge_pola(stare, nowe):
    """Scala pola tekstowe pozycji/wspolnych: niepusta nowa wartosc nadpisuje, pusta NIE kasuje.
    Wartosc-sentinel ('brak'/'-') KASUJE pole (rezygnacja klienta — MD-04). 'edges' (lista)
    obslugujemy osobno w _merge_dane — tu pomijamy."""
    for k, v in (nowe or {}).items():
        if k in ("id", "usun", "edges"):
            continue
        vs = str(v or "").strip()
        if not vs:
            continue
        if vs.lower() in _KASUJ_POLE:
            stare.pop(k, None)   # jawne kasowanie pola
            continue
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
            if istn is None:
                pid = ""   # id spoza stanu (LLM je wymyslil) -> traktuj jak brak id, nie tworz duplikatu (MD-05b)
        if istn is None and not pid:
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
            "potwierdzono": bool(d.get("potwierdzono")),
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
    # Zaostrzenie (PL-03): tekst wygladajacy na JSON (ucięty limitem tokenow / uszkodzony) NIE moze
    # trafic do klienta jako 'odpowiedz'. Rzucamy -> worker ponawia ture (retry zwykle naprawia).
    if txt.startswith("{") or '"odpowiedz"' in txt or '"pozycje"' in txt:
        raise RuntimeError("quotebot: odpowiedz LLM wyglada na uszkodzony/ucięty JSON")
    # Fallback: czysta proza (bez markerow JSON) — traktujemy calosc jako tekst do klienta.
    return {"odpowiedz": txt, "handoff": False, "potwierdzono": False, "powod": "",
            "send_image": "", "pozycje": [], "wspolne": {}, "porownania": []}


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


# --- Walidacja domenowa po merge (MD-01, MD-02/API-02, MD-03, MD-07; schody = API-01) ---

def _ma_schody(dane):
    """True gdy ktoras pozycja to schody (produkt zawiera 'schod') — /calculate ich nie liczy."""
    return any("schod" in str(p.get("produkt") or "").lower() for p in (dane.get("pozycje") or []))


def _wyczysc_niespojny_finishing(dane, options):
    """MD-01: gdy finishing_id wskazuje inny typ wykonczenia niz pole 'wykonczenie' (np. olej vs
    lakier z katalogu), kasuje finishing_id — straznik naturalnie dopyta o wlasciwy wariant.
    Zwraca True gdy cos wyczyszczono."""
    zmiana = False
    for poz in (dane.get("pozycje") or []):
        fid = str(poz.get("finishing_id") or "").strip()
        wyk = str(poz.get("wykonczenie") or "").strip()
        if not (fid and wyk and options):
            continue
        typ_wyk = crm_calc._finish_type(wyk)                    # Surowe/Olejowane/Lakierowane
        typ_fid = crm_calc._finish_type(crm_calc.finishing_full_path(fid, options))
        if typ_wyk and typ_fid and typ_wyk != typ_fid:
            poz.pop("finishing_id", None)
            zmiana = True
    return zmiana


def _walidacja_domenowa(dane, options):
    """Walidacja domenowa pozycji PO merge (poza koperta maksimow). Zwraca konkretne pytanie/
    odrzucenie (PL) albo None. Kolejnosc: pojedyncza liczba + minimum wymiaru, ilosc calkowita,
    dostepnosc wariantu drewna. Schody pomijamy (osobny handoff API-01)."""
    pozycje = dane.get("pozycje") or []
    wiele = len(pozycje) > 1
    for poz in pozycje:
        nazwa = str(poz.get("produkt") or "").strip()
        if "schod" in nazwa.lower():
            continue
        pref = (" (%s)" % nazwa) if (wiele and nazwa) else ""
        # Wymiary: pojedyncza liczba w cm + minimum (MD-07).
        for k, label in (("dlugosc", "długość"), ("szerokosc", "szerokość"), ("grubosc", "grubość")):
            v = str(poz.get(k) or "").strip()
            if not v:
                continue
            num = crm_calc._num(v)
            if num is None:
                return ("Proszę o pojedynczą liczbę w centymetrach — %s%s (np. 200, nie zakres)."
                        % (label, pref))
            if k in ("dlugosc", "szerokosc") and num < 10:
                return ("Podana %s%s to %s cm — to bardzo mało jak na blat. Jeśli chodziło o "
                        "milimetry, proszę o wartość w centymetrach (np. 60 zamiast 600)."
                        % (label, pref, _fmt(num)))
        # Ilosc: dodatnia liczba calkowita (koniec cichego quantity=1 — API-02/MD-02).
        il = str(poz.get("ilosc") or "").strip()
        if il and not (re.fullmatch(r"\d+", il) and int(il) > 0):
            return "Ile dokładnie sztuk%s? Proszę o liczbę (np. 2)." % pref
        # Wariant drewna: komplet 3 pol, ale brak kodu -> niedostepny (MD-03).
        g, t, kl = poz.get("gatunek"), poz.get("technologia"), poz.get("klasa")
        if str(g or "").strip() and str(t or "").strip() and str(kl or "").strip():
            if not crm_calc.variant_code(g, t, kl):
                return _ALT_NIEDOSTEPNY
    return None


# --- Handoff + podsumowanie ---

def _do_handoff(conv_id, powod, dane, closing=CLOSING_MSG):
    """Przekazanie rozmowy agentom. Kolejnosc (API-05): notatka + komunikat zamkniecia PRZED
    toggle statusu, toggle jako OSTATNI krok — gdy notatka/closing padnie, status wciaz 'pending'
    i worker ponawia ture czysto (bez cichej rozmowy w 'open'). Reset stanu jest MIEKKI (MS-03/
    SB-10): zerujemy tylko flagi konwersacyjne, a quote_dane/quote_edit_uuid/contact_*/sent_images
    ZOSTAJA — powrot rozmowy do bota nie zaczyna od zera i nie tworzy wyceny-sieroty."""
    cw_note(conv_id, _summary_note(dane, powod), token=BOT_QUOTE_CW_AGENT_TOKEN)   # rzuca przy awarii -> retry
    if not cw_agent_reply(conv_id, closing, token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: wysylka zamkniecia handoffu nieudana (conv %s)" % conv_id)
    if not cw_bot_handoff(conv_id, token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: handoff nieudany (conv %s)" % conv_id)
    # Miekki reset: zeruj bot_turns/awaiting_*/human_deflected/reject_* (inaczej powrot do pending
    # od razu znow trafilby w limit tur), ZACHOWAJ quote_dane, edit_uuid, kontakt, sent_images.
    c = db()
    c.execute("UPDATE quote_state SET bot_turns=0, awaiting_confirm=0, awaiting_contact=0, "
              "awaiting_postcode=0, human_deflected=0, reject_sig='', reject_count=0 WHERE conv_id=?",
              (conv_id,))
    c.commit(); c.close()
    log("quotebot: handoff conv %s (%s)" % (conv_id, powod))


def _wyslij_cene_i_kontakt(conv_id, dane, identity):
    """Liczy cene przez API, wysyla ja klientowi. Gdy jest email/telefon (z tozsamosci) —
    zapisuje wycene i dosyla link; inaczej ustawia awaiting_contact i miekko prosi o kontakt.
    Rzuca RuntimeError gdy wysylka do Chatwoota padnie (retry w worker)."""
    options = crm_calc.get_options()
    wynik = crm_calc.calculate(dane.get("pozycje") or [], options)
    if not wynik.get("ok") or not wynik.get("totals"):
        # Rozgałęzienie po przyczynie (API-03), zamiast zlewac wszystko w komunikat o lakierze:
        errors = wynik.get("errors") or []
        kody = {str(e.get("code") or "") for e in errors}
        if any(k == "TRANSPORT" or k.startswith("HTTP_") for k in kody):
            # Awaria CRM -> RuntimeError: worker ponawia z backoffem, po wyczerpaniu uczciwe
            # przeprosiny + handoff (handoff_with_apology). Bez tego surowy blat slyszy o lakierze.
            raise RuntimeError("quotebot: /calculate awaria transportu (conv %s)" % conv_id)
        pytanie = _pytanie_z_missing(wynik.get("missing_fields") or [])
        if pytanie:
            # bot_api zwrocil konkretne braki pol z polskimi hintami -> pytamy o nie wprost.
            cw_agent_reply(conv_id, pytanie, token=BOT_QUOTE_CW_AGENT_TOKEN)
        else:
            # Dopiero braki_mapowania (najczesciej lakier/olej bez koloru i polysku) -> doprecyzowanie.
            cw_agent_reply(conv_id, _PROSBA_DOPRECYZ, token=BOT_QUOTE_CW_AGENT_TOKEN)
        _set_awaiting(conv_id, False)
        _bump_turns(conv_id)
        log("quotebot: wycena nieudana -> dopytanie (conv %s)" % conv_id)
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
        # MS-05: koniec ciszy po podanym mailu — informujemy klienta i przekazujemy do konsultanta
        # (lead z kontaktem nie moze zginac bez sladu).
        log("quotebot: find_or_create nieudane (conv %s): %s" % (conv_id, kl))
        _do_handoff(conv_id, "błąd zapisu wyceny — link do dosłania przez konsultanta", dane,
                    closing=_SAVE_FAIL_MSG)
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
        # MS-05: zapis/aktualizacja padla -> nie milcz; informuj klienta + przekaz konsultantowi.
        log("quotebot: zapis/aktualizacja wyceny nieudana (conv %s): %s" % (conv_id, q))
        _do_handoff(conv_id, "błąd zapisu wyceny — link do dosłania przez konsultanta", dane,
                    closing=_SAVE_FAIL_MSG)


def _obsluz_wysylke(conv_id, kod):
    """Liczy wysylke przez API dla zebranych pozycji + kodu pocztowego, wysyla najtansza opcje i
    (gdy jest zapisana wycena) dopisuje kuriera+koszt do wyceny. MS-12: sprawdza wynik wysylki i
    przy niepowodzeniu RZUCA PRZED zgaszeniem flagi awaiting_postcode (retry ponowi z tym kodem)."""
    dane = _load_dane(conv_id)
    options = crm_calc.get_options()
    res = crm_calc.shipping_quote(dane.get("pozycje") or [], kod, options)
    if not cw_agent_reply(conv_id, _wysylka_msg(res), token=BOT_QUOTE_CW_AGENT_TOKEN):
        raise RuntimeError("quotebot: wysylka kosztu wysylki nieudana (conv %s)" % conv_id)
    _set_awaiting_postcode(conv_id, False)   # dopiero po udanej wysylce (retry nie zgubi kodu)
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

    # --- Twarde wyzwalacze intencji PRZED bramkami kontaktu/kodu (RX-05/LS-03/MS-01: gole 'nie'/
    # 'bez' w awaiting_* nie moze polykac reklamacji ani prosby o czlowieka) ---
    rekl = _czy_reklamacja(content)
    prosi = _czy_prosi_o_czlowieka(content) and not _PYTANIE_O_BOTA_RE.search(content or "")

    # Reklamacja + jednoczesna prosba o czlowieka -> od razu handoff (SB-05: nie kaz prosic 3 razy).
    if rekl and prosi:
        _do_handoff(conv_id, "reklamacja + prośba o konsultanta", _load_dane(conv_id))
        return

    # Reklamacja — twardy wyzwalacz RAZ: instrukcja mailowa, BEZ handoffu (bot zostaje w rozmowie).
    # Kolejne wiadomosci reklamacyjne (klient echuje adres/temat) ida do LLM (fix petli z E2E tura 3).
    if rekl and not _complaint_sent(conv_id):
        if not cw_agent_reply(conv_id, COMPLAINT_MSG, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka instrukcji reklamacji nieudana (conv %s)" % conv_id)
        _set_complaint_sent(conv_id, True)
        _bump_turns(conv_id)
        log("quotebot: reklamacja - instrukcja mailowa, bez handoffu (conv %s)" % conv_id)
        return

    # Prosba o czlowieka. W stanie potwierdzenia LUB po wczesniejszym odbiciu LUB po reklamacji
    # (SB-05) -> przekaz od razu, bez deflect. Inaczej miekkie odbicie (raz).
    if prosi:
        if _awaiting_confirm(conv_id) or _human_deflected(conv_id) or _complaint_sent(conv_id):
            _do_handoff(conv_id, "klient prosi o konsultanta", _load_dane(conv_id))
            return
        if not cw_agent_reply(conv_id, DEFLECT_MSG, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka odbicia nieudana (conv %s)" % conv_id)
        _set_human_deflected(conv_id, True)
        _bump_turns(conv_id)
        log("quotebot: miekkie odbicie prosby o czlowieka (conv %s)" % conv_id)
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
        if _czy_odmowa(content):
            # Klient nie chce podawać kontaktu — respektujemy, koniec bez zapisu.
            _set_awaiting_contact(conv_id, False)
            cw_agent_reply(conv_id, "Jasne, nie ma problemu. Gdyby chciał Pan/Pani zapisać wycenę "
                           "lub coś doprecyzować — jestem do dyspozycji.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        if _POZNIEJ_RE.search(content or ""):
            # Odroczenie ('podam pozniej') — flaga ZOSTAJE, tylko potwierdzamy (nie gasimy lejka).
            cw_agent_reply(conv_id, "Jasne, będę czekać — proszę podać e-mail lub telefon, gdy "
                           "będzie wygodnie.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        # Ani kontakt, ani odmowa/odroczenie -> normalna tura (klient pyta o coś innego) — leci dalej.

    # Po zapisaniu wyceny proponujemy wysylke — czekamy na kod pocztowy dostawy.
    if _awaiting_postcode(conv_id):
        kod = _wyciagnij_kod(content)
        if kod:
            # Flage gasi _obsluz_wysylke DOPIERO po udanej wysylce (MS-12) — przy padzie POST
            # flaga zostaje i retry ponawia z tym samym kodem.
            _obsluz_wysylke(conv_id, kod)
            return
        if _czy_odmowa(content):
            # Klient nie chce podawac kodu — respektujemy, koszt ustali konsultant.
            _set_awaiting_postcode(conv_id, False)
            cw_agent_reply(conv_id, "Jasne. Koszt wysyłki potwierdzi konsultant przy finalizacji "
                           "zamówienia.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        if _POZNIEJ_RE.search(content or ""):
            cw_agent_reply(conv_id, "Jasne, proszę podać kod pocztowy, gdy będzie wygodnie — "
                           "oszacuję wtedy koszt wysyłki.", token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        # Ani kod, ani odmowa (np. samo miasto lub inne pytanie) -> normalna tura;
        # flaga zostaje, LLM (wg reguly promptu) dopyta o kod, kolejny kod znow przechwycimy.

    # Bezpiecznik D: limit tur bota — PO bramkach kontaktu/kodu (MS-11: e-mail/kod z ostatniej
    # tury zostaje skonsumowany, nie przepada w handoffie z limitu). Dedykowany komunikat (LS-11).
    if _bot_turns(conv_id) >= BOT_QUOTE_MAX_TURNS:
        _do_handoff(conv_id, "limit tur bota (bezpiecznik)", _load_dane(conv_id), closing=LIMIT_MSG)
        return

    history = cw_messages(conv_id, BOT_HISTORY_LIMIT)
    identity = cw_contact(conv_id)
    query = (content or "").strip() or (history[-1]["text"] if history else "")
    knowledge = "\n\n".join(retrieve(query))
    dane_przed = _load_dane(conv_id)
    awaiting = _awaiting_confirm(conv_id)

    system = build_system_prompt("quote", knowledge, identity) + "\n\n" + _FORMAT
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
    # Stan 'priced' w promptcie (PL-10/MD-06): LLM ma wiedziec, czy cena juz padla — bez tego
    # uzywa 'porownania' przed pierwsza wycena (slepy zaulek).
    if _priced(conv_id):
        system += ("\n\nSTAN: wysłano już wycenę w tej rozmowie — 'porownania' możesz teraz użyć dla "
                   "TEGO SAMEGO produktu w innym wariancie.")
    else:
        system += ("\n\nSTAN: nie wysłano jeszcze żadnej ceny — NIE używaj 'porownania'; pierwszą "
                   "wycenę prowadź normalnie przez 'pozycje'.")

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

    raw = chat(messages, response_format={"type": "json_object"})
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
    # Bez zmiany pozycji porownanie NIGDY nie konczy sie cisza/RuntimeError (MS-02, SB-04): albo je
    # pokazujemy, albo deterministycznie tlumaczymy, kiedy je pokazemy.
    if out.get("porownania") and not zmienione:
        if _czy_porownanie(conv_id, out, dane, zmienione):
            if _obsluz_porownania(conv_id, dane, out["porownania"]):
                return
            # Wszystkie porownania juz pokazane (dedup) -> krotka info zamiast ciszy.
            cw_agent_reply(conv_id, "To porównanie pokazałem już wyżej — Twoja wycena pozostaje "
                           "aktualna. Chętnie policzę inny wariant albo pomogę w czymś jeszcze.",
                           token=BOT_QUOTE_CW_AGENT_TOKEN)
            _bump_turns(conv_id)
            return
        # Nie mozemy policzyc porownania teraz -> nie milcz, wytlumacz kiedy.
        if not _priced(conv_id):
            msg = ("Porównanie z innym wariantem policzę zaraz po przygotowaniu pierwszej wyceny — "
                   "najpierw dokończmy dane tego produktu.")
        else:
            braki_cmp = _brakujace(dane)
            msg = (_pytanie_o_braki(braki_cmp, len(dane["pozycje"]) > 1) if braki_cmp
                   else "Już liczę to porównanie — chwilę proszę.")
        if not cw_agent_reply(conv_id, msg, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka info o porownaniu nieudana (conv %s)" % conv_id)
        _bump_turns(conv_id)
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

    # Spojnosc wykonczenie<->finishing_id (MD-01): niespojne id kasujemy PRZED strażnikiem braku,
    # zeby dopytal o wlasciwy wariant zamiast liczyc cene starego wykonczenia.
    if _wyczysc_niespojny_finishing(dane, opts):
        _zapisz_dane(conv_id, dane)
    # Walidacja domenowa (ilosc/wariant/minima wymiarow) -> konkretne pytanie zamiast cichego
    # quantity=1 albo mylnego _PROSBA_DOPRECYZ (API-02/MD-02, MD-03, MD-07).
    problem = _walidacja_domenowa(dane, opts)
    if problem:
        if not cw_agent_reply(conv_id, problem, token=BOT_QUOTE_CW_AGENT_TOKEN):
            raise RuntimeError("quotebot: wysylka walidacji domenowej nieudana (conv %s)" % conv_id)
        _bump_turns(conv_id)
        log("quotebot: walidacja domenowa - dopytanie (conv %s)" % conv_id)
        return

    brak = _brakujace(dane)

    # Schody nie sa wyceniane automatycznie przez /calculate (API-01) -> po komplecie danych
    # deterministyczny handoff z notatka zamiast petli mylnego _PROSBA_DOPRECYZ.
    if _ma_schody(dane) and not brak:
        _do_handoff(conv_id, "schody — wycena indywidualna konsultanta", dane)
        return

    # Bramka potwierdzenia (PL-02, RX-09): w stanie awaiting potwierdzenie ma PIERWSZENSTWO przed
    # handoffem. Sygnal potwierdzenia = pole 'potwierdzono' od LLM, deterministyczne _POTW_RE dla
    # krotkich wypowiedzi, ALBO handoff z powodem zawierajacym 'potwierdz' (LLM parafrazujacy
    # 'konsultanta' — _POWOD_PRZEPUSC blednie by go przepuscil do czlowieka). Wtedy licz cene.
    if awaiting and not brak and not zmienione and (
            out.get("potwierdzono") or _jest_potwierdzenie(content)
            or (out["handoff"] and _POTWIERDZ_POWOD_RE.search(out.get("powod") or ""))):
        _wyslij_cene_i_kontakt(conv_id, dane, cw_contact_full(conv_id))
        return

    # Wyzwalacze B/C (decyzja LLM) + straznik kompletnosci + bramka potwierdzenia.
    if out["handoff"]:
        powod = out["powod"] or "decyzja bota"
        if not _czy_powod_kompletu(powod):
            _do_handoff(conv_id, powod, dane)
            return
        if brak:
            # Braki -> nie oddajemy rozmowy, dopytujemy (backstop).
            reply = _pytanie_o_braki(brak, len(dane["pozycje"]) > 1)
            if not cw_agent_reply(conv_id, reply, token=BOT_QUOTE_CW_AGENT_TOKEN):
                raise RuntimeError("quotebot: wysylka pytania o braki nieudana (conv %s)" % conv_id)
            _bump_turns(conv_id)
            log("quotebot: straznik wstrzymal handoff, braki: %s (conv %s)"
                % (",".join(k for _, k in brak), conv_id))
            return
        if _priced(conv_id):
            # MS-04: cena JUZ wyslana -> nie ponawiaj podsumowania ani ceny (retry po awarii
            # prosby o kontakt nie moze zdublowac podsumowania/ceny). Niejednoznaczny handoff-
            # komplet po cenie obsluzy zwykla odpowiedz LLM nizej.
            pass
        elif not awaiting:
            # Bramka: podsumowanie dopiero PO nim wycena, gdy klient potwierdzi.
            _wyslij_podsumowanie(conv_id, dane)
            return
        else:
            # Komplet + awaiting + LLM zgłosił potwierdzenie -> licz cenę zamiast handoffu.
            _wyslij_cene_i_kontakt(conv_id, dane, cw_contact_full(conv_id))
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
