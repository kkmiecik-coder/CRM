# -*- coding: utf-8 -*-
# Skrypt zakłada (idempotentnie) Agent Bota w Chatwoocie przez API.
# Uruchamiać z katalogu integrations/chat_bridge:
#   python3 -m setup.create_agent_bot
import os
import sys

import requests


# ---------------------------------------------------------------------------
# Odczyt konfiguracji ze zmiennych środowiskowych (te same co config.py mostka)
# ---------------------------------------------------------------------------

def _cfg():
    """Zwraca tuple (base, acc, token, outgoing_url) ze zmiennych środowiskowych."""
    base  = os.environ.get("CHATWOOT_BASE", "http://rails:3000").rstrip("/")
    acc   = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ.get("CHATWOOT_API_TOKEN", "")
    # Token bezpieczeństwa webhooka bota (dodawany do query string URL)
    bot_token = os.environ.get("BOT_AGENT_WEBHOOK_TOKEN", "")
    # Bazowy URL webhooka — można nadpisać przez env; domyślny = produkcja
    webhook_base = os.environ.get(
        "BOT_AGENT_WEBHOOK_URL",
        "https://chatbridge.woodpower.pl/agent-bot",
    )
    # Outgoing URL: jeśli token ustawiony — dołącz jako ?token=
    if bot_token:
        outgoing_url = "%s?token=%s" % (webhook_base, bot_token)
    else:
        outgoing_url = webhook_base
    return base, acc, token, outgoing_url


def _cfg_quote():
    """Konfiguracja dla bota wyceniającego (webhook /agent-bot-quote)."""
    base  = os.environ.get("CHATWOOT_BASE", "http://rails:3000").rstrip("/")
    acc   = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ.get("CHATWOOT_API_TOKEN", "")
    # Token bezpieczeństwa webhooka bota wyceniającego (dodawany do query string URL)
    bot_token = os.environ.get("BOT_QUOTE_AGENT_WEBHOOK_TOKEN", "")
    # Bazowy URL webhooka — można nadpisać przez env; domyślny = produkcja
    webhook_base = os.environ.get(
        "BOT_QUOTE_AGENT_WEBHOOK_URL",
        "https://chatbridge.woodpower.pl/agent-bot-quote",
    )
    # Outgoing URL: jeśli token ustawiony — dołącz jako ?token=
    if bot_token:
        outgoing_url = "%s?token=%s" % (webhook_base, bot_token)
    else:
        outgoing_url = webhook_base
    return base, acc, token, outgoing_url


def _cfg_pro():
    """Konfiguracja dla Dębusia Pro (webhook /agent-bot-pro, silnik Agents SDK)."""
    base  = os.environ.get("CHATWOOT_BASE", "http://rails:3000").rstrip("/")
    acc   = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ.get("CHATWOOT_API_TOKEN", "")
    # Token bezpieczeństwa webhooka Debusia Pro (dodawany do query string URL)
    bot_token = os.environ.get("BOT_PRO_AGENT_WEBHOOK_TOKEN", "")
    # Bazowy URL webhooka — można nadpisać przez env; domyślny = produkcja
    webhook_base = os.environ.get(
        "BOT_PRO_AGENT_WEBHOOK_URL",
        "https://chatbridge.woodpower.pl/agent-bot-pro",
    )
    # Outgoing URL: jeśli token ustawiony — dołącz jako ?token=
    if bot_token:
        outgoing_url = "%s?token=%s" % (webhook_base, bot_token)
    else:
        outgoing_url = webhook_base
    return base, acc, token, outgoing_url


def _headers(token):
    """Buduje nagłówki HTTP z tokenem admina Chatwoota."""
    return {
        "api_access_token": token,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Publiczne funkcje (importowalne, bez efektów ubocznych przy imporcie)
# ---------------------------------------------------------------------------

def list_agent_bots():
    """
    Pobiera listę Agent Botów z konta Chatwoota.
    GET /api/v1/accounts/{acc}/agent_bots
    Zwraca listę dict z polami id, name (etc.) lub [] przy błędzie.
    """
    base, acc, token, _ = _cfg()
    url = "%s/api/v1/accounts/%s/agent_bots" % (base, acc)
    try:
        r = requests.get(url, headers=_headers(token), timeout=25)
        if r.status_code != 200:
            print("BLAD list_agent_bots HTTP %s: %s" % (r.status_code, r.text[:200]), file=sys.stderr)
            return []
        data = r.json()
        # Odpowiedź to gołą lista lub {"payload": [...]}
        if isinstance(data, dict):
            return data.get("payload", [])
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print("BLAD list_agent_bots wyjątek: %s" % repr(e), file=sys.stderr)
        return []


_OPIS_DOMYSLNY = "Asystent AI - podpowiedzi (prywatne notatki)"


def _patch_outgoing_url(bot_id, outgoing_url):
    """PATCH /agent_bots/{id} — aktualizuje outgoing_url istniejącego bota.
    Zwraca zaktualizowany dict bota, albo None przy błędzie (wołający ma wtedy
    fallback na stary obiekt bota z list_agent_bots — patrz ensure_agent_bot)."""
    base, acc, token, _ = _cfg()
    url = "%s/api/v1/accounts/%s/agent_bots/%s" % (base, acc, bot_id)
    try:
        r = requests.patch(url, headers=_headers(token), json={"outgoing_url": outgoing_url}, timeout=25)
    except Exception as e:
        print("BLAD patch_outgoing_url wyjątek: %s" % repr(e), file=sys.stderr)
        return None
    if r.status_code not in (200, 201):
        print("BLAD patch_outgoing_url HTTP %s: %s" % (r.status_code, r.text[:200]), file=sys.stderr)
        return None
    data = r.json()
    if isinstance(data, dict) and "payload" in data:
        return data["payload"]
    return data if isinstance(data, dict) else None


def ensure_agent_bot(name="WoodPower AI", outgoing_url=None, description=None):
    """
    Idempotentnie tworzy Agent Bota o podanej nazwie.
    Jeśli bot o tej nazwie już istnieje — zwraca go BEZ tworzenia duplikatu, ale
    PATCHUJE outgoing_url, gdy różni się od tego, co dziś wynika z configu (np.
    token webhooka zmieniony w bridge.env) — inaczej idempotencja po cichu
    zamieniałaby się w "nigdy już nie aktualizuj", a webhook zostawałby trwale
    nieaktualny mimo poprawnego configu (Task 7, Step 6).
    Zwraca dict bota z polami id, access_token (i innymi).
    Rzuca RuntimeError przy błędzie tworzenia.

    outgoing_url: opcjonalny własny URL webhooka (np. z _cfg_quote()/_cfg_pro()).
    Gdy nie podany — używany jest domyślny URL z _cfg() (dotychczasowe zachowanie).

    description: opcjonalny opis bota w Chatwoocie. Gdy nie podany — domyślny
    (dotychczasowy) tekst "Asystent AI - podpowiedzi (prywatne notatki)", który
    pasuje do WoodPower AI / Asystenta AI v1 (tryb podpowiedzi/notatek), ale NIE
    do Debusia Pro (ten NIE działa w trybie notatek — odpowiada wprost klientowi).
    """
    base, acc, token, default_url = _cfg()
    outgoing_url = outgoing_url or default_url
    opis = description or _OPIS_DOMYSLNY

    # Sprawdź czy bot już istnieje — idempotencja
    existing = list_agent_bots()
    for bot in existing:
        if bot.get("name") == name:
            if bot.get("outgoing_url") != outgoing_url and bot.get("id"):
                zaktualizowany = _patch_outgoing_url(bot.get("id"), outgoing_url)
                if zaktualizowany:
                    return zaktualizowany
            return bot

    # Bot nie istnieje — utwórz
    url = "%s/api/v1/accounts/%s/agent_bots" % (base, acc)
    payload = {
        "name": name,
        "description": opis,
        "outgoing_url": outgoing_url,
    }
    try:
        r = requests.post(url, headers=_headers(token), json=payload, timeout=25)
    except Exception as e:
        raise RuntimeError("BLAD create_agent_bot wyjątek: %s" % repr(e)) from e

    if r.status_code not in (200, 201):
        raise RuntimeError(
            "BLAD create_agent_bot HTTP %s: %s" % (r.status_code, r.text[:300])
        )

    data = r.json()
    # Odpowiedź może być w payload lub gołym dict
    if isinstance(data, dict) and "payload" in data:
        return data["payload"]
    return data


# ---------------------------------------------------------------------------
# Punkt wejścia CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Wariant "quote": tworzy osobnego bota "Asystent AI v1" pod webhook /agent-bot-quote
    if len(sys.argv) > 1 and sys.argv[1] == "quote":
        _, _, _, q_url = _cfg_quote()
        print("Tworzenie / weryfikacja Agent Bota 'Asystent AI v1'...")
        print("outgoing_url:", q_url)
        print()

        try:
            bot = ensure_agent_bot("Asystent AI v1", outgoing_url=q_url)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

        access_token = bot.get("access_token") or bot.get("agent_bot_access_token", "")
        print("Asystent AI v1 access_token:", access_token)
        print("outgoing_url:", q_url)
        print()
        print("Wklej do bridge.env: BOT_QUOTE_CW_AGENT_TOKEN=%s" % access_token)
        raise SystemExit(0)

    # Wariant "pro": tworzy osobna encje "Dębuś Pro" pod webhook /agent-bot-pro (Agents SDK) —
    # OBOK istniejacych botow, zeby migracje dalo sie przelaczac inbox po inboxie (BOT_PRO_INBOXES)
    # z natychmiastowym odwrotem, bez ruszania starych botow.
    if len(sys.argv) > 1 and sys.argv[1] == "pro":
        _, _, _, p_url = _cfg_pro()
        print("Tworzenie / weryfikacja Agent Bota 'Dębuś Pro'...")
        print("outgoing_url:", p_url)
        print()

        try:
            bot = ensure_agent_bot(
                "Dębuś Pro", outgoing_url=p_url,
                description="Dębuś Pro - agent sprzedażowy (odpowiada bezpośrednio klientowi)")
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

        access_token = bot.get("access_token") or bot.get("agent_bot_access_token", "")
        print("Dębuś Pro access_token:", access_token)
        print("outgoing_url:", p_url)
        print()
        print("Wklej do bridge.env: BOT_PRO_CW_AGENT_TOKEN=%s" % access_token)
        raise SystemExit(0)

    _, _, _, outgoing_url = _cfg()

    print("Tworzenie / weryfikacja Agent Bota 'WoodPower AI'...")
    print("outgoing_url:", outgoing_url)
    print()

    try:
        bot = ensure_agent_bot("WoodPower AI")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    bot_id = bot.get("id")
    access_token = bot.get("access_token") or bot.get("agent_bot_access_token", "")

    print("OK. Agent Bot:")
    print("  id          :", bot_id)
    print("  access_token:", access_token)
    print("  outgoing_url:", bot.get("outgoing_url", outgoing_url))
    print()
    print("Wklej do bridge.env:")
    print("  BOT_CW_AGENT_TOKEN=%s" % access_token)
    print()
    print("Następnie: docker compose restart (lub bridge-deploy.sh) + przypnij bota")
    print("do skrzynki w Chatwoocie: Inbox → Konfiguracja bota → WoodPower AI → Aktualizuj.")
