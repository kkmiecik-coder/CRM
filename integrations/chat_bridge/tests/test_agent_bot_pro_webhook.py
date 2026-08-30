# -*- coding: utf-8 -*-
"""
Webhook Dębusia Pro.

Bramka inboxów to kill-switch migracji: przełączamy inbox po inboxie
zmienną BOT_PRO_INBOXES, bez zmiany kodu i bez ruszania starych botów.

UWAGA (rozstrzygnięcie zadania 7): `_process_pro` świadomie NIE robi
bezwarunkowego `cw_bot_handoff` (w odróżnieniu od `_process_agent_bot`,
który woła go przed jakimkolwiek sprawdzeniem treści/persony) — testy
niżej to potwierdzają (`cw_bot_handoff` nigdy nie jest importowany/wołany
z tego modułu w kontekście trasy /agent-bot-pro).
"""
import json

import pytest

import webhooks


@pytest.fixture()
def klient():
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(webhooks.bp)
    return app.test_client()


def _zdarzenie(inbox_id="5", tresc="dzień dobry", mtype="incoming", private=False, mid=999):
    return {
        "event": "message_created",
        "message_type": mtype,
        "private": private,
        "id": mid,
        "content": tresc,
        "inbox_id": inbox_id,
        "conversation": {"id": 123},
    }


class TestWebhookPro:
    def test_brak_tokenu_odrzucony(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
        odp = klient.post("/agent-bot-pro", json=_zdarzenie())
        assert odp.status_code == 401

    def test_zly_token_odrzucony(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
        odp = klient.post("/agent-bot-pro?token=zly", json=_zdarzenie())
        assert odp.status_code == 401

    def test_dobry_token_akceptowany(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret")
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        monkeypatch.setattr(webhooks, "enqueue_quote_turn", lambda *a, **k: None)
        odp = klient.post("/agent-bot-pro?token=sekret", json=_zdarzenie(inbox_id="5"))
        assert odp.status_code == 200

    def test_inbox_spoza_listy_ignorowany(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"18"})
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(a))

        odp = klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="5"))

        assert odp.status_code == 200
        assert kolejkowane == []

    def test_inbox_z_listy_kolejkowany(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        odp = klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="5"))

        assert odp.status_code == 200
        assert kolejkowane == ["pro"]

    def test_inbox_olx_dostaje_persone_olx(self, monkeypatch, klient):
        # W1 (code review): persona MA wynikac z inboxu, nie byc "pro" na sztywno —
        # inaczej bots.channel_caps.caps_for("pro") spada na DEFAULT_CAPS (linki
        # wlaczone) zamiast na OLX_CAPS/ALLEGRO_CAPS.
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "olx")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="5"))

        assert kolejkowane == ["olx"]

    def test_inbox_allegro_dostaje_persone_allegro(self, monkeypatch, klient):
        # Krytyczne: allegro MUSI dostac wlasna persone (links=False), inaczej
        # wyciek linkow do kupujacego na Allegro (regulamin marketplace'u).
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"6"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "allegro")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="6"))

        assert kolejkowane == ["allegro"]

    def test_inbox_mail_lub_nieznany_dostaje_domyslna_persone_pro(self, monkeypatch, klient):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"7"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "mail")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="7"))

        assert kolejkowane == ["pro"]

    def test_wiadomosc_wychodzaca_ignorowana(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(a))

        zdarzenie = _zdarzenie(mtype="outgoing")
        klient.post("/agent-bot-pro", json=zdarzenie)

        assert kolejkowane == []

    def test_wiadomosc_prywatna_ignorowana(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(a))

        klient.post("/agent-bot-pro", json=_zdarzenie(private=True))

        assert kolejkowane == []

    def test_pusta_tresc_bez_zalacznikow_ignorowana(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(a))

        klient.post("/agent-bot-pro", json=_zdarzenie(tresc=""))

        assert kolejkowane == []

    def test_zalacznik_obrazu_przekazany_do_kolejki(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("attachments")))

        zdarzenie = _zdarzenie(tresc="")
        zdarzenie["attachments"] = [
            {"data_url": "https://x/obraz.jpg", "file_type": "image"},
            {"data_url": "https://x/plik.pdf", "file_type": "file"},
        ]
        klient.post("/agent-bot-pro", json=zdarzenie)

        assert kolejkowane == [["https://x/obraz.jpg"]]

    def test_brak_bezwarunkowego_handoff(self, klient, monkeypatch):
        """Rozstrzygniecie zadania 7: w odroznieniu od `_process_agent_bot`, trasa
        /agent-bot-pro NIE ma wolac cw_bot_handoff przed jakimkolwiek sprawdzeniem
        tresci/persony — inaczej rozmowa budzilaby sie z 'pending' zanim ktokolwiek
        cokolwiek powiedzial."""
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        wolania_handoff = []
        monkeypatch.setattr(webhooks, "cw_bot_handoff",
                            lambda conv_id: wolania_handoff.append(conv_id))
        monkeypatch.setattr(webhooks, "enqueue_quote_turn", lambda *a, **k: None)

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="5"))

        assert wolania_handoff == []
