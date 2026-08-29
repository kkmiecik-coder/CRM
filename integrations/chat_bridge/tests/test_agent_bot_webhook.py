# -*- coding: utf-8 -*-
# Test: endpoint /agent-bot — handoff zawsze, podpowiedz gdy inbox zmapowany, dedup, filtrowanie outgoing/private.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_agentbot.db")
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
wh = importlib.import_module("webhooks"); importlib.reload(wh)


def setup_function(_):
    """Inicjalizuj DB i wyczysc kolejki przed kazdym testem."""
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM suggest_queue")
    c.execute("DELETE FROM bot_seen")
    c.execute("DELETE FROM quote_queue")
    c.execute("DELETE FROM quote_seen")
    c.commit(); c.close()


def _count_queue():
    """Zlicz wiersze w suggest_queue."""
    c = db_mod.db()
    n = c.execute("SELECT COUNT(*) n FROM suggest_queue").fetchone()["n"]
    c.close()
    return n


def _count_quote_queue():
    """Zlicz wiersze w quote_queue."""
    c = db_mod.db()
    n = c.execute("SELECT COUNT(*) n FROM quote_queue").fetchone()["n"]
    c.close()
    return n


def _payload(mid="m1", content="Czas realizacji?", inbox_id=3, conv_id=77, mtype=0, private=False, event="message_created"):
    """Buduje payload webhooka Agent Bota (message.webhook_data)."""
    return {
        "event": event,
        "message_type": mtype,
        "id": mid,
        "content": content,
        "private": private,
        "conversation": {
            "id": conv_id,
            "inbox_id": inbox_id,
        },
    }


# ---------------------------------------------------------------------------
# Test 1: incoming + zmapowana persona + tresc + mid -> handoff + 1 wpis w kolejce
# (sciezka starego podpowiadacza — po przelaczeniu OLX/Allegro na quotebota, "mail" jest
# jedynym kanalem, ktory realnie przechodzi przez suggest_queue).
# ---------------------------------------------------------------------------

def test_incoming_z_persona_kolejkuje_i_handoff(monkeypatch):
    """Wiadomosc incoming z inboxu z persona: handoff wywolany, wpis w suggest_queue."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "mail")

    wh._process_agent_bot(_payload())

    assert len(handoffs) == 1, "cw_bot_handoff powinien byc wywolany raz"
    assert handoffs[0] == 77, "handoff dla conv_id=77"
    assert _count_queue() == 1, "powinien byc 1 wpis w suggest_queue"


# ---------------------------------------------------------------------------
# Test 2: incoming + inbox bez persony -> handoff TAK, kolejka NIE
# ---------------------------------------------------------------------------

def test_incoming_bez_persony_handoff_bez_kolejki(monkeypatch):
    """Inbox niezmapowany: handoff zawsze, ale brak podpowiedzi (na zadnym torze)."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: None)

    wh._process_agent_bot(_payload())

    assert len(handoffs) == 1, "handoff musi byc wywolany nawet dla nieznanego inboxu"
    assert _count_queue() == 0, "brak persony -> brak wpisu w suggest_queue"
    assert _count_quote_queue() == 0, "brak persony -> brak wpisu w quote_queue"


# ---------------------------------------------------------------------------
# Test 3: incoming + pusta tresc -> handoff TAK, kolejka NIE
# ---------------------------------------------------------------------------

def test_incoming_pusta_tresc_handoff_bez_kolejki(monkeypatch):
    """Pusta tresc: handoff wywolany, ale brak kolejkowania. Persona 'olx' — filtrowanie tresci
    jest wspolne dla obu torow, sprawdzane na kanale ktory realnie przechodzi przez quotebota."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(content="   "))

    assert len(handoffs) == 1, "handoff musi byc wywolany nawet przy pustej tresci"
    assert _count_queue() == 0, "pusta tresc -> brak wpisu w suggest_queue"
    assert _count_quote_queue() == 0, "pusta tresc -> brak wpisu w quote_queue"


# ---------------------------------------------------------------------------
# Test 4: private=True -> nic (bez handoffu, bez kolejki)
# ---------------------------------------------------------------------------

def test_private_ignorowany(monkeypatch):
    """Prywatna wiadomosc jest ignorowana w calosci. Persona 'olx' — filtrowanie sprawdzane
    na kanale ktory realnie przechodzi przez quotebota."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(private=True))

    assert len(handoffs) == 0, "private=True -> zadnego handoffu"
    assert _count_queue() == 0, "private=True -> brak wpisu w suggest_queue"
    assert _count_quote_queue() == 0, "private=True -> brak wpisu w quote_queue"


# ---------------------------------------------------------------------------
# Test 5: outgoing (message_type=1) -> nic
# ---------------------------------------------------------------------------

def test_outgoing_ignorowany(monkeypatch):
    """Wiadomosc wychodząca jest ignorowana w calosci. Persona 'olx' — filtrowanie sprawdzane
    na kanale ktory realnie przechodzi przez quotebota."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mtype=1))

    assert len(handoffs) == 0, "outgoing -> zadnego handoffu"
    assert _count_queue() == 0, "outgoing -> brak wpisu w suggest_queue"
    assert _count_quote_queue() == 0, "outgoing -> brak wpisu w quote_queue"


def test_outgoing_string_ignorowany(monkeypatch):
    """Wiadomosc wychodząca (message_type='outgoing') jest ignorowana. Persona 'olx'."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mtype="outgoing"))

    assert len(handoffs) == 0, "outgoing string -> zadnego handoffu"
    assert _count_queue() == 0
    assert _count_quote_queue() == 0


# ---------------------------------------------------------------------------
# Test 6: dedup — to samo mid dwa razy -> tylko 1 wpis w kolejce
# Persona 'olx' (bez mocka enqueue_quote_turn) — dedup dla OLX/Allegro NIE idzie juz przez
# bot_seen, tylko przez quote_seen wewnatrz enqueue_quote_turn (patrz bots/quote_intake.py),
# wiec sensowna weryfikacja dedupu dla tego kanalu wymaga realnego wywolania silnika quotebota:
# pierwsze wywolanie wstawia 1 wiersz do quote_queue, drugie (ten sam mid) jest odduplikowane
# na poziomie quote_seen i NIE wstawia kolejnego wiersza. quote_queue nie jest wiec puste (jak
# w pozostalych testach filtrujacych) — niezmiennik to "nadal dokladnie 1 wiersz mimo duplikatu".
# ---------------------------------------------------------------------------

def test_dedup_tego_samego_mid(monkeypatch):
    """Duplikat po message_id: drugi wpis zignorowany (teraz w quote_queue, przez quote_seen)."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mid="m_dedup"))
    wh._process_agent_bot(_payload(mid="m_dedup"))

    assert _count_quote_queue() == 1, "dedup po mid -> tylko 1 wiersz w quote_queue"
    assert _count_queue() == 0, "kanal olx nie pisze juz do suggest_queue"


# ---------------------------------------------------------------------------
# Test 7: nie-message_created event -> nic
# ---------------------------------------------------------------------------

def test_inny_event_ignorowany(monkeypatch):
    """Event inny niz message_created jest ignorowany. Persona 'olx' — filtrowanie sprawdzane
    na kanale ktory realnie przechodzi przez quotebota."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(event="conversation_updated"))

    assert len(handoffs) == 0
    assert _count_queue() == 0
    assert _count_quote_queue() == 0


# ---------------------------------------------------------------------------
# Test 9: persona "livechat" -> handoff TAK, kolejka podpowiedzi NIE (symetria z live-botem)
# ---------------------------------------------------------------------------

def test_persona_livechat_handoff_bez_kolejki_podpowiedzi(monkeypatch):
    """Inbox z persona 'livechat': handoff jak zawsze, ale bez notatki-podpowiedzi (ma ja bot live).
    Livechat NIE jest w _PERSONA_QUOTE_DLA_KANALU, wiec sprawdzamy oba tory."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")

    wh._process_agent_bot(_payload())

    assert len(handoffs) == 1, "handoff musi byc wywolany takze dla persony livechat"
    assert _count_queue() == 0, "persona livechat -> brak wpisu w suggest_queue"
    assert _count_quote_queue() == 0, "persona livechat -> brak wpisu w quote_queue"


# ---------------------------------------------------------------------------
# Test 8: inbox_id na poziomie top-level payloadu -> handoff + kolejka
# (sciezka starego podpowiadacza — persona 'mail', bo test sprawdza wpis w suggest_queue,
# a nie zachowanie specyficzne dla OLX/Allegro; sama ekstrakcja inbox_id jest wspolna dla obu
# torow i rownie dobrze weryfikuje sie ja na kanale ktory nadal pisze do suggest_queue).
# ---------------------------------------------------------------------------

def test_toplevel_inbox_id_fallback(monkeypatch):
    """Payload z inbox_id na poziomie top-level (bez conversation.inbox_id) jest przetwarzany."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "mail")

    # Payload z inbox_id na poziomie top-level, bez conversation.inbox_id
    payload = {
        "event": "message_created",
        "message_type": 0,
        "id": "mTL",
        "content": "pytanie",
        "inbox_id": 3,
        "conversation": {
            "id": 88,
        },
    }
    wh._process_agent_bot(payload)

    assert len(handoffs) == 1, "cw_bot_handoff powinien byc wywolany dla top-level inbox_id"
    assert handoffs[0] == 88, "handoff dla conv_id=88"
    assert _count_queue() == 1, "powinien byc 1 wpis w suggest_queue (pomimo braku conversation.inbox_id)"


# ---------------------------------------------------------------------------
# Testy 10-14: przelaczenie OLX/Allegro na silnik quotebota (tryb notatki).
# ---------------------------------------------------------------------------

def test_olx_trafia_do_quote_queue_z_persona_quote_olx(monkeypatch):
    """OLX obsluguje teraz pelny silnik quotebota, nie stary suggester."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")
    wh._process_agent_bot(_payload(mid="q1", inbox_id=3, conv_id=101))
    c = db_mod.db()
    row = c.execute("SELECT persona FROM quote_queue WHERE conv_id=101").fetchone()
    c.close()
    assert row["persona"] == "quote_olx"


def test_allegro_trafia_do_quote_queue_z_persona_quote_allegro(monkeypatch):
    """Allegro analogicznie jak OLX — persona 'quote_allegro' w quote_queue."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "allegro")
    wh._process_agent_bot(_payload(mid="q2", inbox_id=4, conv_id=102))
    c = db_mod.db()
    row = c.execute("SELECT persona FROM quote_queue WHERE conv_id=102").fetchone()
    c.close()
    assert row["persona"] == "quote_allegro"


def test_mail_zostaje_na_starym_suggesterze(monkeypatch):
    """Skrzynki mailowe sa poza zakresem — dalej stary podpowiadacz."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "mail")
    przed_quote, przed_sugg = _count_quote_queue(), _count_queue()
    wh._process_agent_bot(_payload(mid="q3", inbox_id=8, conv_id=103))
    assert _count_quote_queue() == przed_quote
    assert _count_queue() == przed_sugg + 1


def test_handoff_nadal_wykonywany(monkeypatch):
    """Bez handoffu rozmowy utknelyby w 'pending' i nie trafily do agentow."""
    handoffy = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffy.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")
    wh._process_agent_bot(_payload(mid="q4", inbox_id=3, conv_id=104))
    assert handoffy == [104]


def test_livechat_nadal_pomijany_przez_agent_bot(monkeypatch):
    """Webhook WoodPower AI nie obsluguje livechatu — tam pracuje Debus przez /agent-bot-quote."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    przed = _count_quote_queue()
    wh._process_agent_bot(_payload(mid="q5", inbox_id=5, conv_id=105))
    assert _count_quote_queue() == przed
