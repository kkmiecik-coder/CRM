# -*- coding: utf-8 -*-
"""Silnik E2E quote-bota: wstrzykuje tury klienta przez Chatwoot Application API na skrzynke
testowa (inbox 18), deterministycznie wyzwala webhook kandydata (/agent-bot-quote), czeka na
odpowiedz bota (polling) i ocenia scenariusz wg pola `oczekuj`.

Konfiguracja przez ENV (najprosciej uruchamiac w kontenerze z --env-file bridge-candidate.env,
zeby sekrety NIE trafialy do argv/logow):
  CHATWOOT_BASE            baza API (w sieci dockera: http://rails:3000)
  CHATWOOT_ACCOUNT_ID      konto (2)
  CHATWOOT_API_TOKEN       token agenta/admina z dostepem do inboxu 18 (odczyt+wstrzykiwanie)
  BOT_QUOTE_AGENT_WEBHOOK_TOKEN  token webhooka quote-bota (do wyzwalania /agent-bot-quote)
  E2E_INBOX_ID             domyslnie 18
  E2E_WEBHOOK_URL          domyslnie http://quotebot-candidate:5006/agent-bot-quote
  E2E_POLL_TIMEOUT         maks. sekund oczekiwania na odpowiedz bota na ture (domyslnie 60)
  E2E_FIRE_WEBHOOK         "1" (domyslnie) = wyzwalaj webhook recznie; "0" = polegaj na auto-fire Chatwoota
  E2E_MSG_PREFIX           prefiks nazwy kontaktu testowego (domyslnie "E2E")
"""
import os
import re
import time
import json
import html
import base64
import requests

CW_BASE = os.environ.get("CHATWOOT_BASE", "http://rails:3000").rstrip("/")
CW_ACC = os.environ.get("CHATWOOT_ACCOUNT_ID", "2")
CW_TOKEN = os.environ["CHATWOOT_API_TOKEN"]
INBOX_ID = int(os.environ.get("E2E_INBOX_ID", "18"))
# Publiczny identyfikator widgetu (website_token) inboxu WebWidget. Gdy pusty — pobieramy z API.
INBOX_IDENTIFIER = os.environ.get("E2E_INBOX_IDENTIFIER", "")
WEBHOOK_URL = os.environ.get("E2E_WEBHOOK_URL", "http://quotebot-candidate:5006/agent-bot-quote")
WEBHOOK_TOKEN = os.environ.get("BOT_QUOTE_AGENT_WEBHOOK_TOKEN", "")
POLL_TIMEOUT = float(os.environ.get("E2E_POLL_TIMEOUT", "60"))
POLL_INTERVAL = 1.5
SETTLE_QUIET = 5.0   # gdy przez tyle sekund nie przybyla nowa wiadomosc bota -> tura ustabilizowana
FIRE_WEBHOOK = os.environ.get("E2E_FIRE_WEBHOOK", "1") == "1"
MSG_PREFIX = os.environ.get("E2E_MSG_PREFIX", "E2E")


class HarnessError(RuntimeError):
    pass


def _api(method, path, **kw):
    """Application API (token agenta) — do ODCZYTU wiadomosci/statusu i toggle_status."""
    url = "%s/api/v1/accounts/%s%s" % (CW_BASE, CW_ACC, path)
    h = {"api_access_token": CW_TOKEN, "Content-Type": "application/json"}
    r = requests.request(method, url, headers=h, timeout=30, **kw)
    if r.status_code >= 400:
        raise HarnessError("API %s %s -> %s: %s" % (method, path, r.status_code, r.text[:300]))
    return r.json() if r.text.strip() else {}


def _identifier():
    """website_token inboxu WebWidget (publiczny identyfikator widgetu). Pobierany raz z API,
    o ile nie podano E2E_INBOX_IDENTIFIER."""
    global INBOX_IDENTIFIER
    if not INBOX_IDENTIFIER:
        d = _api("GET", "/inboxes/%s" % INBOX_ID)
        INBOX_IDENTIFIER = d.get("website_token") or d.get("inbox_identifier") or ""
        if not INBOX_IDENTIFIER:
            raise HarnessError("brak website_token dla inboxu %s (nie-WebWidget?)" % INBOX_ID)
    return INBOX_IDENTIFIER


def _jwt_source(token):
    """Wyciaga source_id z payloadu JWT authToken widgetu (bez weryfikacji podpisu — tylko odczyt)."""
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p.encode())).get("source_id")
    except Exception:
        return None


def nowa_sesja_widgetu(nazwa=None):
    """Bootstrap widgetu jak realna przegladarka: GET /widget?website_token -> swiezy kontakt
    (window.authToken = JWT) + cookie sesji. Rozmowa powstaje przy pierwszej wiadomosci
    (wyslij_ture ustawia conv_id z odpowiedzi). Zwraca dict sesji {sess, auth, wt, source_id, conv_id}."""
    wt = _identifier()
    sess = requests.Session()
    r = sess.get("%s/widget?website_token=%s" % (CW_BASE, wt), timeout=20)
    if r.status_code >= 400:
        raise HarnessError("GET /widget -> %s" % r.status_code)
    m = re.search(r"window\.authToken\s*=\s*'([^']+)'", r.text)
    if not m:
        raise HarnessError("nie znaleziono window.authToken w HTML widgetu")
    auth = m.group(1)
    hdr = {"X-Auth-Token": auth, "Content-Type": "application/json"}
    if nazwa:
        try:
            sess.patch("%s/api/v1/widget/contact?website_token=%s" % (CW_BASE, wt),
                       headers=hdr, json={"name": nazwa}, timeout=20)
        except Exception:
            pass
    return {"sess": sess, "auth": auth, "wt": wt, "source_id": _jwt_source(auth), "conv_id": None}


def _txt(s):
    """HTML -> czysty tekst (bot czasem zwraca <br>/encje); do asercji i podgladu."""
    s = s or ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


# ---------- tworzenie rozmowy ----------

def status_rozmowy(conv_id):
    d = _api("GET", "/conversations/%s" % conv_id)
    return d.get("status") or (d.get("meta") or {}).get("status") or (d.get("payload") or {}).get("status")


def _wiadomosci(conv_id):
    d = _api("GET", "/conversations/%s/messages" % conv_id)
    return d.get("payload") or d.get("data") or []


def wyslij_ture(sesja, tekst):
    """Wysyla wiadomosc KLIENTA przez API widgetu (X-Auth-Token) — incoming, widoczna w UI,
    natywnie wyzwala webhook bota. Zwraca message_id."""
    hdr = {"X-Auth-Token": sesja["auth"], "Content-Type": "application/json"}
    url = "%s/api/v1/widget/messages?website_token=%s" % (CW_BASE, sesja["wt"])
    r = sesja["sess"].post(url, headers=hdr, json={"message": {"content": tekst}}, timeout=20)
    if r.status_code >= 400:
        raise HarnessError("POST /api/v1/widget/messages -> %s: %s" % (r.status_code, r.text[:200]))
    d = r.json() or {}
    mid = d.get("id") or (d.get("payload") or {}).get("id")
    if not mid:
        raise HarnessError("brak id wiadomosci widgetu: %s" % json.dumps(d)[:300])
    if not sesja.get("conv_id"):
        sesja["conv_id"] = d.get("conversation_id")   # rozmowa powstaje przy 1. wiadomosci
    return mid


def wyzwol_webhook(conv_id, mid, tekst):
    """Deterministycznie wyzwala ture bota (obok ewentualnego auto-fire Chatwoota; dedup po mid
    w quote_seen chroni przed podwojnym przetworzeniem)."""
    url = WEBHOOK_URL
    if WEBHOOK_TOKEN:
        url += ("&" if "?" in url else "?") + "token=" + WEBHOOK_TOKEN
    body = {"event": "message_created", "message_type": "incoming",
            "id": mid, "content": tekst,
            "conversation": {"id": conv_id, "inbox_id": INBOX_ID},
            "inbox_id": INBOX_ID, "attachments": []}
    try:
        requests.post(url, json=body, timeout=15)
    except Exception as e:
        # nie przerywamy — auto-fire Chatwoota moze i tak zadzialac
        print("   [uwaga] webhook nieudany: %r" % e)


def czekaj_na_odpowiedz(conv_id, znane_ids):
    """Czeka na nowe PUBLICZNE odpowiedzi bota (i notatki) po turze. Zwraca
    (nowe_publiczne:list[str], nowe_notatki:list[str], status:str, wszystkie_ids:set)."""
    t0 = time.monotonic()
    ostatnia_zmiana = t0
    pub, notatki = [], []
    widziane = set(znane_ids)
    while time.monotonic() - t0 < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            msgs = _wiadomosci(conv_id)
        except Exception as e:
            print("   [uwaga] odczyt wiadomosci nieudany: %r" % e)
            continue
        cos_nowego = False
        for m in msgs:
            mid = m.get("id")
            if mid in widziane:
                continue
            widziane.add(mid)
            mtype = m.get("message_type")
            priv = bool(m.get("private"))
            ctype = m.get("content_type")
            snd = (m.get("sender") or {}).get("type")
            tresc = _txt(m.get("content"))
            # Realna wiadomosc bota = outgoing(1) + sender agent_bot. Pomijamy: incoming klienta (0),
            # template/automat widgetu (3: powitanie „Dębuś", email-collect — sender None) i activity (2).
            if mtype not in (1, "outgoing"):
                continue
            if snd != "agent_bot":
                continue
            if not tresc.strip():
                continue
            if priv:
                notatki.append(tresc)             # prywatna notatka (handoff)
            elif ctype in (None, "", "text"):
                pub.append(tresc)                 # publiczna odpowiedz do klienta
            cos_nowego = True
        if cos_nowego:
            ostatnia_zmiana = time.monotonic()
        # ustabilizowanie: mamy jakas publiczna odpowiedz i cisza przez SETTLE_QUIET
        if pub and (time.monotonic() - ostatnia_zmiana) >= SETTLE_QUIET:
            break
    st = None
    try:
        st = status_rozmowy(conv_id)
    except Exception:
        pass
    return pub, notatki, st, widziane


# ---------- ocena ----------

def ocen(sc, pub_all, notatki_all, status_koniec):
    """Zwraca (werdykt, powody). werdykt: PASS | FAIL | REVIEW.
    Deterministyczne asercje z `oczekuj`; scenariusz z `human` -> co najwyzej REVIEW."""
    o = sc.get("oczekuj") or {}
    powody = []
    polaczone = "\n".join(pub_all).lower()
    ostatnia = (pub_all[-1] if pub_all else "").lower()

    min_odp = o.get("min_odp", 1)
    if len(pub_all) < min_odp:
        powody.append("za malo odpowiedzi bota: %d < %d (cisza?)" % (len(pub_all), min_odp))

    for sub in o.get("zawiera", []):
        if sub.lower() not in polaczone:
            powody.append("brak wymaganego fragmentu: %r" % sub)

    for sub in o.get("zawiera_ost", []):
        if sub.lower() not in ostatnia:
            powody.append("ostatnia odpowiedz nie zawiera: %r" % sub)

    for sub in o.get("nie_zawiera", []):
        if sub.lower() in polaczone:
            powody.append("wystapil zakazany fragment: %r" % sub)

    if "status" in o and status_koniec and status_koniec != o["status"]:
        powody.append("status %r != oczekiwany %r" % (status_koniec, o["status"]))

    if o.get("notatka") and not notatki_all:
        powody.append("brak prywatnej notatki (oczekiwano handoffu z notatka)")

    if powody:
        return "FAIL", powody
    if sc.get("human"):
        return "REVIEW", ["do oceny czlowieka: " + sc["human"]]
    return "PASS", []


# ---------- orkiestracja scenariusza ----------

def uruchom_scenariusz(sc, idx=None, total=None):
    """Uruchamia jeden scenariusz od zera (swiezy kontakt/rozmowa). Zwraca dict wyniku."""
    naglowek = "[%s/%s] " % (idx, total) if idx else ""
    print("%s%s %s — %s" % (naglowek, sc["id"], sc.get("kat", ""), sc.get("tytul", "")))
    nazwa = "%s %s %s" % (MSG_PREFIX, sc["id"], int(time.time()))
    sesja = nowa_sesja_widgetu(nazwa)
    conv_id = None
    transkrypt = []
    pub_all, notatki_all = [], []
    widziane = set()
    status_koniec = None
    for i, tura in enumerate(sc["tury"], 1):
        mid = wyslij_ture(sesja, tura)
        if conv_id is None:
            conv_id = sesja["conv_id"]   # rozmowa powstala przy 1. wiadomosci
        if FIRE_WEBHOOK:
            wyzwol_webhook(conv_id, mid, tura)
        pub, notatki, status_koniec, widziane = czekaj_na_odpowiedz(conv_id, widziane)
        pub_all += pub
        notatki_all += notatki
        transkrypt.append({"tura": i, "klient": tura, "bot": pub, "notatki": notatki, "status": status_koniec})
        for b in pub:
            print("      bot> " + b.replace("\n", "\n           "))
        for n in notatki:
            print("      [notatka]> " + n.replace("\n", " ")[:200])
        if not pub:
            print("      [!] brak odpowiedzi bota na ture %d" % i)
    werdykt, powody = ocen(sc, pub_all, notatki_all, status_koniec)
    print("   => %s%s" % (werdykt, ("  (" + "; ".join(powody) + ")") if powody else ""))
    print()
    return {"id": sc["id"], "kat": sc.get("kat"), "tytul": sc.get("tytul"),
            "conv_id": conv_id, "source_id": sesja.get("source_id"),
            "tworzy_lead": bool(sc.get("tworzy_lead")),
            "werdykt": werdykt, "powody": powody,
            "status_koniec": status_koniec, "transkrypt": transkrypt}
