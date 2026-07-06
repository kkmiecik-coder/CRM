# -*- coding: utf-8 -*-
# Silnik konwersacyjnego bota live-chat: publiczne odpowiedzi do klienta (RAG + persona livechat),
# wycena na POZYCJACH (wiele produktow bez wzajemnego nadpisywania), deterministyczne podsumowanie
# do potwierdzenia przez klienta przed handoffem, wyzwalacze A/B/C/D, cisza po przekazaniu.
# Rzuca wyjatkiem przy niepowodzeniu LLM; retry i sciezke awaryjna obsluguje live_worker.
import os
import json
import re
from config import BOT_HISTORY_LIMIT, BOT_LIVE_MAX_TURNS, BOT_LIVE_CW_AGENT_TOKEN
from core.log import log
from core.db import db
from core.chatwoot import (cw_messages, cw_contact, cw_note, cw_agent_reply,
                           cw_conv_status, cw_bot_handoff)
from bots.knowledge import retrieve
from bots.personas import build_system_prompt
from bots.llm import chat
from bots import images

# Komunikaty stale (edytowalne). Bez obietnic czasowych — patrz spec §13.
CLOSING_MSG = "Dziękuję za informacje! Przekazuję rozmowę do konsultanta WoodPower — odpowiemy w tej rozmowie."
APOLOGY_MSG = ("Przepraszam, mam chwilowy problem techniczny z odpowiedzią. "
               "Przekazuję rozmowę do konsultanta WoodPower.")

_MAX_PROBEK = 3   # limit probek wg konfiguracji doklejanych do jednego podsumowania
_PROBKA_PODPIS = "Poniżej próbka wybranego wykończenia 👇"

# Instrukcja formatu odpowiedzi LLM — doklejana do promptu systemowego persony.
# Kazdy produkt klienta = OSOBNA pozycja ze stalym id; pola wspolne calej wyceny poza pozycjami.
_FORMAT = (
    "FORMAT ODPOWIEDZI: odpowiedz WYŁĄCZNIE poprawnym JSON (bez tekstu przed/po):\n"
    '{"odpowiedz": "tekst do klienta", "handoff": false, "powod": "", "send_image": "", '
    '"pozycje": [{"id": "1", "produkt": "", "dlugosc": "", "szerokosc": "", "grubosc": "", '
    '"gatunek": "", "technologia": "", "klasa": "", "ilosc": "", "wykonczenie": "", '
    '"otwory": "", "krawedzie": "", "schody": ""}], '
    '"wspolne": {"termin": "", "kontakt": ""}}\n'
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
    "string. NIGDY nie wymyślaj tagów spoza listy i nie obiecuj zdjęć, których nie ma."
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
    row = c.execute("SELECT bot_turns FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return row["bot_turns"] if row else 0


def _bump_turns(conv_id):
    """Inkrementuje licznik tur bota (INSERT lub UPDATE)."""
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns) VALUES(?,1) "
              "ON CONFLICT(conv_id) DO UPDATE SET bot_turns=bot_turns+1", (conv_id,))
    c.commit(); c.close()


def _awaiting_confirm(conv_id):
    """Czy rozmowa czeka na potwierdzenie podsumowania wyceny przez klienta."""
    c = db()
    row = c.execute("SELECT awaiting_confirm FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["awaiting_confirm"]) if row else False


def _set_awaiting(conv_id, flag):
    """Ustawia/kasuje flage oczekiwania na potwierdzenie (INSERT lub UPDATE)."""
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns, awaiting_confirm) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET awaiting_confirm=excluded.awaiting_confirm",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _human_deflected(conv_id):
    c = db()
    row = c.execute("SELECT human_deflected FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["human_deflected"]) if row else False


def _set_human_deflected(conv_id, flag):
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns, human_deflected) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET human_deflected=excluded.human_deflected",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _complaint_sent(conv_id):
    """Czy w tej rozmowie wyslano juz instrukcje reklamacyjna (COMPLAINT_MSG)."""
    c = db()
    row = c.execute("SELECT complaint_sent FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    return bool(row["complaint_sent"]) if row else False


def _set_complaint_sent(conv_id, flag):
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns, complaint_sent) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET complaint_sent=excluded.complaint_sent",
              (conv_id, 1 if flag else 0))
    c.commit(); c.close()


def _reject_state(conv_id):
    """(sygnatura ostatniego odrzucenia, licznik powtorzen) — 0/'' gdy brak."""
    c = db()
    row = c.execute("SELECT reject_sig, reject_count FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    if not row:
        return "", 0
    return (row["reject_sig"] or ""), (row["reject_count"] or 0)


def _set_reject(conv_id, sig, count):
    c = db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns, reject_sig, reject_count) VALUES(?,0,?,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET reject_sig=excluded.reject_sig, "
              "reject_count=excluded.reject_count", (conv_id, sig, count))
    c.commit(); c.close()


def _sent_images(conv_id):
    """Zbior kluczy obrazow juz wyslanych w tej rozmowie (dedup)."""
    c = db()
    row = c.execute("SELECT sent_images FROM live_state WHERE conv_id=?", (conv_id,)).fetchone()
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
    c.execute("INSERT INTO live_state(conv_id, bot_turns, sent_images) VALUES(?,0,?) "
              "ON CONFLICT(conv_id) DO UPDATE SET sent_images=excluded.sent_images",
              (conv_id, json.dumps(sorted(obecne), ensure_ascii=False)))
    c.commit(); c.close()


# --- Warstwa danych wyceny: pozycje (wiele produktow) + pola wspolne ---

_POZ_POLA = ("produkt", "dlugosc", "szerokosc", "grubosc", "gatunek", "technologia",
             "klasa", "ilosc", "wykonczenie", "otwory", "krawedzie", "schody")
_WSPOLNE_POLA = ("termin", "kontakt")


def _pusty_stan():
    return {"pozycje": [], "wspolne": {}}


def _load_dane(conv_id):
    """Wczytuje zaakumulowany stan wyceny {'pozycje': [...], 'wspolne': {...}}.
    Stary plaski zapis (rozmowy w toku sprzed pozycji) opakowuje jako pozycje '1'."""
    c = db()
    row = c.execute("SELECT dane_json FROM live_dane WHERE conv_id=?", (conv_id,)).fetchone()
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
    c.execute("INSERT INTO live_dane(conv_id, dane_json) VALUES(?,?) "
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
    """Scala pola pozycji/wspolnych: niepusta nowa wartosc nadpisuje, pusta NIE kasuje."""
    for k, v in (nowe or {}).items():
        if k in ("id", "usun"):
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
            nowa = {"id": pid or _nowe_id(stan["pozycje"])}
            stan["pozycje"].append(_merge_pola(nowa, p))
        else:
            _merge_pola(istn, p)
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
            "wspolne": d.get("wspolne") if isinstance(d.get("wspolne"), dict) else {}}


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
            "pozycje": [], "wspolne": {}}


# --- Podsumowanie do potwierdzenia + notatka dla agenta ---

_POLA_POZYCJI = [("dlugosc", "Długość"), ("szerokosc", "Szerokość"), ("grubosc", "Grubość"),
                 ("gatunek", "Gatunek"), ("technologia", "Technologia"), ("klasa", "Klasa"),
                 ("wykonczenie", "Wykończenie"), ("otwory", "Otwory/wycięcia"),
                 ("krawedzie", "Krawędzie"), ("schody", "Schody")]
_POLA_WSPOLNE = [("termin", "Termin"), ("kontakt", "Kontakt")]
_CM_POLA = ("dlugosc", "szerokosc", "grubosc")


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


def _bloki_pozycji(dane):
    """Linie podsumowania: blok na pozycje (numerowany przy >1) + pola wspolne na koncu."""
    lines = []
    pozycje = dane.get("pozycje") or []
    wiele = len(pozycje) > 1
    for i, poz in enumerate(pozycje, 1):
        naglowek = _naglowek_pozycji(poz)
        lines.append("%d. %s" % (i, naglowek) if wiele else naglowek)
        for k, label in _POLA_POZYCJI:
            v = str(poz.get(k) or "").strip()
            if not v:
                continue
            lines.append("%s: %s" % (label, _fmt_cm(v) if k in _CM_POLA else v))
        lines.append("")
    for k, label in _POLA_WSPOLNE:
        v = str((dane.get("wspolne") or {}).get(k) or "").strip()
        if v:
            lines.append("%s: %s" % (label, v))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _podsumowanie_msg(dane):
    """Deterministyczne podsumowanie wyceny do potwierdzenia przez klienta (bez LLM)."""
    lines = ["Podsumowuję dane do wyceny:", ""]
    lines += _bloki_pozycji(dane)
    lines += ["", "Czy wszystko się zgadza? Jeśli tak, przekażę specyfikację konsultantowi do wyceny."]
    return "\n".join(lines)


def _summary_note(dane, powod):
    """Prywatna notatka-podsumowanie dla agenta po handoffie."""
    lines = ["🤖 Bot live-chat — przekazanie do konsultanta", "Powód: %s" % (powod or "-")]
    bloki = _bloki_pozycji(dane or _pusty_stan())
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
_POWOD_PRZEPUSC = re.compile(
    r"(człowiek|czlowiek|konsultant|doradc|pracownik|poza (wiedz|zakres)|"
    r"nie wiem|nie potrafi|reklamacj|status zam|zmian\w* zam|faktur|"
    r"zwrot(u|em|ów|ow|y)?\b|indywidualn)", re.IGNORECASE)

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
    """Backstop: krotkie pytanie o max 2 pierwsze braki PIERWSZEJ niekompletnej pozycji.
    Przy wielu pozycjach wskazuje, o ktory produkt pytamy."""
    poz = brak[0][0]
    pola = [k for p, k in brak if p is poz][:2]
    etyk = [_ETYKIETY_PYTAN.get(k, k) for k in pola]
    prefiks = ""
    nazwa = str(poz.get("produkt") or "").strip()
    if wiele_pozycji and nazwa:
        prefiks = " (%s)" % nazwa
    if len(etyk) == 1:
        return "Żeby przygotować wycenę, potrzebuję jeszcze%s: %s." % (prefiks, etyk[0])
    return "Żeby przygotować wycenę, potrzebuję jeszcze%s: %s oraz %s." % (prefiks, etyk[0], etyk[1])


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
    if not cw_bot_handoff(conv_id, token=BOT_LIVE_CW_AGENT_TOKEN):
        raise RuntimeError("livechat: handoff nieudany (conv %s)" % conv_id)
    # Reset stanu (licznik tur + awaiting_confirm + dane): gdy agent odda rozmowe botowi
    # (open->pending), bot startuje od zera.
    c = db()
    c.execute("DELETE FROM live_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM live_dane WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()
    cw_note(conv_id, _summary_note(dane, powod))
    cw_agent_reply(conv_id, closing)
    log("livechat: handoff conv %s (%s)" % (conv_id, powod))


def _wyslij_probki(conv_id, dane):
    """Deterministycznie dokleja probki wybranej konfiguracji (lookup po nazwie pliku).
    Nigdy nie rzuca — obraz nie moze wywrocic tury po wyslanym podsumowaniu. Dedup + cap."""
    wyslane = _sent_images(conv_id)
    ile = 0
    for poz in (dane.get("pozycje") or []):
        if ile >= _MAX_PROBEK:
            break
        key = images.sample_key(poz)
        if not key or key in wyslane:
            continue
        sciezka = images.resolve_sample(poz)
        if not sciezka:
            continue
        if cw_agent_reply(conv_id, _PROBKA_PODPIS, image_path=sciezka,
                          image_name=os.path.basename(sciezka), image_mime="image/jpeg"):
            _mark_image_sent(conv_id, key)
            wyslane.add(key)
            ile += 1


def _wyslij_podsumowanie(conv_id, dane):
    """Wysyla WYLACZNIE deterministyczne podsumowanie (bez prozy LLM — koniec podwojnego
    'Potwierdzam parametry.../Podsumowuje dane...'). Ustawia stan oczekiwania na potwierdzenie,
    po czym dokleja probki wybranej konfiguracji (jesli sa).
    Kolejnosc CELOWO wysylka -> stan: gdy POST padnie, retry ponawia ture bez awaiting i
    podsumowanie dociera; stan-przed-wysylka po nieudanym POST omijalby podsumowanie."""
    if not cw_agent_reply(conv_id, _podsumowanie_msg(dane)):
        raise RuntimeError("livechat: wysylka podsumowania nieudana (conv %s)" % conv_id)
    _set_awaiting(conv_id, True)
    _bump_turns(conv_id)
    _wyslij_probki(conv_id, dane)
    log("livechat: podsumowanie do potwierdzenia (conv %s)" % conv_id)


def run_livechat_turn(conv_id, inbox_id, message_id, content):
    """Pelna tura bota. Rzuca RuntimeError przy braku odpowiedzi LLM (retry w workerze)."""
    # Cisza po handoffie: bot prowadzi TYLKO rozmowy w statusie pending.
    status = cw_conv_status(conv_id)
    if status is None:
        # Nie zgadujemy: bez statusu nie wolno pisac do klienta — retry w workerze.
        raise RuntimeError("livechat: nie mozna odczytac statusu rozmowy (conv %s)" % conv_id)
    if status != "pending":
        log("livechat: conv %s status=%s - bot milczy" % (conv_id, status))
        return

    # Bezpiecznik D: limit tur bota.
    if _bot_turns(conv_id) >= BOT_LIVE_MAX_TURNS:
        _do_handoff(conv_id, "limit tur bota (bezpiecznik)", _load_dane(conv_id))
        return

    # Reklamacja — twardy wyzwalacz RAZ: instrukcja mailowa, BEZ handoffu (bot zostaje w rozmowie).
    # Kolejne wiadomosci reklamacyjne (klient echuje adres/temat) ida do LLM, zeby odpowiedziec
    # na follow-up zamiast powtarzac canned (fix petli reklamacji z E2E tura 3).
    if _czy_reklamacja(content) and not _complaint_sent(conv_id):
        if not cw_agent_reply(conv_id, COMPLAINT_MSG):
            raise RuntimeError("livechat: wysylka instrukcji reklamacji nieudana (conv %s)" % conv_id)
        _set_complaint_sent(conv_id, True)
        _bump_turns(conv_id)
        log("livechat: reklamacja - instrukcja mailowa, bez handoffu (conv %s)" % conv_id)
        return

    # Prosba o czlowieka. Guard: pytanie o tozsamosc -> pomijamy (niech LLM odpowie uczciwie).
    # W stanie potwierdzenia (komplet zebrany) prosba o konsultanta = przekaz od razu, bez deflect.
    if _czy_prosi_o_czlowieka(content) and not _PYTANIE_O_BOTA_RE.search(content or ""):
        if _awaiting_confirm(conv_id) or _human_deflected(conv_id):
            _do_handoff(conv_id, "klient prosi o konsultanta", _load_dane(conv_id))
            return
        if not cw_agent_reply(conv_id, DEFLECT_MSG):
            raise RuntimeError("livechat: wysylka odbicia nieudana (conv %s)" % conv_id)
        _set_human_deflected(conv_id, True)
        _bump_turns(conv_id)
        log("livechat: miekkie odbicie prosby o czlowieka (conv %s)" % conv_id)
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

    raw = chat(messages)
    if not raw:
        raise RuntimeError("livechat: brak odpowiedzi modelu")
    out = _parse_llm(raw)
    dane = _merge_dane(conv_id, out)   # akumulacja per pozycja: raz zebrane pole zostaje
    zmienione = dane != dane_przed   # porownanie wartosci (dict ==), nie tozsamosci — oba swieze obiekty z _load_dane

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
        if not cw_agent_reply(conv_id, msg):
            raise RuntimeError("livechat: wysylka odrzucenia wymiaru nieudana (conv %s)" % conv_id)
        _bump_turns(conv_id)
        log("livechat: odrzucony wymiar (conv %s, powt %s)" % (conv_id, cnt))
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
                if not cw_agent_reply(conv_id, reply):
                    raise RuntimeError("livechat: wysylka pytania o braki nieudana (conv %s)" % conv_id)
                _bump_turns(conv_id)
                log("livechat: straznik wstrzymal handoff, braki: %s (conv %s)"
                    % (",".join(k for _, k in brak), conv_id))
                return
            if not awaiting:
                # Bramka: handoff "komplet danych" dopiero PO potwierdzeniu podsumowania.
                _wyslij_podsumowanie(conv_id, dane)
                return
        _do_handoff(conv_id, powod, dane)
        return

    # Bez handoffu: komplet wymaganych -> podsumowanie (pierwsze lub po korekcie danych).
    if not brak:
        if not awaiting or zmienione:
            _wyslij_podsumowanie(conv_id, dane)
            return
        # Awaiting bez zmian: czyste potwierdzenie -> handoff deterministyczny (nie czekamy na LLM).
        if _jest_potwierdzenie(content):
            _do_handoff(conv_id, "klient potwierdził dane do wyceny", dane)
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
        raise RuntimeError("livechat: pusta odpowiedz modelu")
    # 1a: obraz semantyczny wybrany przez model (whitelist), raz na rozmowe.
    tag = out.get("send_image") or ""
    sciezka = images.resolve(tag) if tag else None
    if sciezka and tag not in _sent_images(conv_id):
        meta = images.IMAGES[tag]
        ok = cw_agent_reply(conv_id, reply, image_path=sciezka,
                            image_name=meta["nazwa"], image_mime=meta["mime"])
        if ok:
            _mark_image_sent(conv_id, tag)
    else:
        ok = cw_agent_reply(conv_id, reply)
    if not ok:
        raise RuntimeError("livechat: wysylka odpowiedzi nieudana (conv %s)" % conv_id)
    _bump_turns(conv_id)
    log("livechat: odpowiedz wyslana (conv %s, tura %s)" % (conv_id, _bot_turns(conv_id)))


def handoff_with_apology(conv_id):
    """Sciezka awaryjna (po wyczerpaniu retry): przeprosiny + przekazanie do agenta."""
    _do_handoff(conv_id, "błąd techniczny bota (wyczerpane próby)", _pusty_stan(),
                closing=APOLOGY_MSG)
