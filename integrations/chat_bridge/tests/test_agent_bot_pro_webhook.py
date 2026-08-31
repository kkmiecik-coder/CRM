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
        # Inbox "66" (nie "6") - "6" to domyslny CW_ALLEGRO_DISPUTE_INBOX (config.py),
        # ktory od U6 jest twardo wykluczony niezaleznie od tego mocka.
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"66"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "allegro")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="66"))

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


class TestPersonaProDlaInboxuOdpornaNaAwarieKatalogu:
    """N1 (code review, runda 2): persona_for(inbox_id) siega siecia po katalog
    inboksow i przy KAZDYM bledzie HTTP zwraca None (core/chatwoot.cw_inboxes
    daje [] na blad) — bez tej poprawki kanal spadalby na "pro" (DEFAULT_CAPS,
    linki WLACZONE) mimo ze inbox faktycznie jest OLX/Allegro. Identyfikacja
    idzie WIEC NAJPIERW przez identyfikatory z configu (CW_OLX_INBOX/
    CW_ALLEGRO_MSG_INBOX), ktore nie wymagaja sieci i nie moga "zawiesc"."""

    def test_config_olx_rozpoznany_mimo_katalogu_niedostepnego(self, monkeypatch):
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", "18")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "4")
        # Katalog "padl" - persona_for nie powinien byc w ogole potrzebny.
        monkeypatch.setattr(webhooks, "persona_for",
                            lambda inbox_id: (_ for _ in ()).throw(AssertionError(
                                "identyfikacja po configu nie powinna siegac po siec")))
        assert webhooks._persona_pro_dla_inboxu("18") == "olx"

    def test_config_allegro_rozpoznany_mimo_katalogu_niedostepnego(self, monkeypatch):
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", "18")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "6")
        monkeypatch.setattr(webhooks, "persona_for",
                            lambda inbox_id: (_ for _ in ()).throw(AssertionError(
                                "identyfikacja po configu nie powinna siegac po siec")))
        assert webhooks._persona_pro_dla_inboxu("6") == "allegro"

    def test_webhook_end_to_end_allegro_z_configu_nie_kolejkuje_linkow(self, klient, monkeypatch):
        # Dowod na poziomie calego webhooka (nie tylko funkcji pomocniczej): inbox
        # skonfigurowany jako CW_ALLEGRO_MSG_INBOX trafia do kolejki z persona
        # "allegro", NIE "pro", nawet gdy katalog inboksow jest niedostepny.
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"6"})
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", "18")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "6")
        # Jawnie inny inbox niz "6" - nie polegamy na tym, ze prawdziwy config.py
        # domyslnie ma CW_ALLEGRO_DISPUTE_INBOX="6" (kolizja zepsulaby ten test od U6).
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_DISPUTE_INBOX", "999")
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: None)   # katalog padl
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="6"))

        assert kolejkowane == ["allegro"]

    def test_inbox_spoza_configu_pada_na_persona_for_jak_dotychczas(self, monkeypatch):
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", "18")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "4")
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "allegro")
        assert webhooks._persona_pro_dla_inboxu("99") == "allegro"

    def test_inbox_spoza_configu_i_katalog_padl_daje_domyslne_pro(self, monkeypatch):
        # Udokumentowane rezydualne ryzyko: inbox NIGDY nie serwowany przez legacy
        # (brak identyfikatora w configu) I rownoczesna awaria katalogu nadal
        # spada na "pro" - to jest swiadomie zaakceptowany, wezszy przypadek
        # (patrz raport), nie scenariusz migracji, ktory ta poprawka zamyka.
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", "18")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "4")
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: None)
        assert webhooks._persona_pro_dla_inboxu("99") == "pro"

    def test_pusty_config_nie_wybucha(self, monkeypatch):
        monkeypatch.setattr(webhooks, "CW_OLX_INBOX", None)
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", None)
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        assert webhooks._persona_pro_dla_inboxu("18") == "pro"


class TestWykluczenieInboxuDyskusjiAllegro:
    """U6 (code review, runda 3): inbox 'Allegro - Dyskusje' (reklamacje/spory)
    MA byc wykluczony z Debusia Pro TWARDO, niezaleznie od BOT_PRO_INBOXES —
    Debus Pro to bot sprzedazowy bez pojecia o procesie reklamacyjnym, ktory
    odpowiada publicznie i bez nadzoru czlowieka. Wpisanie tego inboxu do
    BOT_PRO_INBOXES (bledem operatora przy migracji) nie ma go odblokowac."""

    def test_inbox_dyskusji_wykluczony_mimo_obecnosci_w_bot_pro_inboxes(self, klient, monkeypatch):
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_DISPUTE_INBOX", "6")
        # Blad operatora: inbox dyskusji NA LISCIE BOT_PRO_INBOXES.
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"6"})
        monkeypatch.setattr(webhooks, "persona_for",
                            lambda inbox_id: (_ for _ in ()).throw(AssertionError(
                                "wykluczenie ma zadzialac PRZED jakimkolwiek "
                                "sprawdzeniem persony/katalogu")))
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(a))

        odp = klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="6"))

        assert odp.status_code == 200
        assert kolejkowane == []

    def test_inny_inbox_allegro_niz_dyskusje_nie_jest_wykluczony(self, klient, monkeypatch):
        # Kontrola negatywna: wykluczenie dotyczy TYLKO skonfigurowanego inboxu
        # dyskusji, nie kazdego inboxu Allegro.
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_DISPUTE_INBOX", "6")
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_MSG_INBOX", "4")
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"4"})
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(k.get("persona")))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="4"))

        assert kolejkowane == ["allegro"]

    def test_pusty_cw_allegro_dispute_inbox_nie_wybucha(self, klient, monkeypatch):
        # Gdy identyfikator dyskusji nie jest skonfigurowany (pusty/None), bramka
        # ma po prostu nie wykluczac niczego (nie ma czego porownywac), nie rzucac.
        monkeypatch.setattr(webhooks, "BOT_PRO_AGENT_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(webhooks, "CW_ALLEGRO_DISPUTE_INBOX", None)
        monkeypatch.setattr(webhooks, "BOT_PRO_INBOXES", {"5"})
        monkeypatch.setattr(webhooks, "persona_for", lambda inbox_id: "livechat")
        kolejkowane = []
        monkeypatch.setattr(webhooks, "enqueue_quote_turn",
                            lambda *a, **k: kolejkowane.append(1))

        klient.post("/agent-bot-pro", json=_zdarzenie(inbox_id="5"))

        assert kolejkowane == [1]
