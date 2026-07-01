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


def ensure_agent_bot(name="WoodPower AI"):
    """
    Idempotentnie tworzy Agent Bota o podanej nazwie.
    Jeśli bot o tej nazwie już istnieje — zwraca go bez tworzenia duplikatu.
    Zwraca dict bota z polami id, access_token (i innymi).
    Rzuca RuntimeError przy błędzie tworzenia.
    """
    base, acc, token, outgoing_url = _cfg()

    # Sprawdź czy bot już istnieje — idempotencja
    existing = list_agent_bots()
    for bot in existing:
        if bot.get("name") == name:
            # Bot istnieje — zwróć bez POST
            return bot

    # Bot nie istnieje — utwórz
    url = "%s/api/v1/accounts/%s/agent_bots" % (base, acc)
    payload = {
        "name": name,
        "description": "Asystent AI - podpowiedzi (prywatne notatki)",
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
