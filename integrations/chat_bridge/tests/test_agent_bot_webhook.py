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
    c.commit(); c.close()


def _count_queue():
    """Zlicz wiersze w suggest_queue."""
    c = db_mod.db()
    n = c.execute("SELECT COUNT(*) n FROM suggest_queue").fetchone()["n"]
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
# ---------------------------------------------------------------------------

def test_incoming_z_persona_kolejkuje_i_handoff(monkeypatch):
    """Wiadomosc incoming z inboxu z persona: handoff wywolany, wpis w suggest_queue."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload())

    assert len(handoffs) == 1, "cw_bot_handoff powinien byc wywolany raz"
    assert handoffs[0] == 77, "handoff dla conv_id=77"
    assert _count_queue() == 1, "powinien byc 1 wpis w suggest_queue"


# ---------------------------------------------------------------------------
# Test 2: incoming + inbox bez persony -> handoff TAK, kolejka NIE
# ---------------------------------------------------------------------------

def test_incoming_bez_persony_handoff_bez_kolejki(monkeypatch):
    """Inbox niezmapowany: handoff zawsze, ale brak podpowiedzi."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: None)

    wh._process_agent_bot(_payload())

    assert len(handoffs) == 1, "handoff musi byc wywolany nawet dla nieznanego inboxu"
    assert _count_queue() == 0, "brak persony -> brak wpisu w kolejce"


# ---------------------------------------------------------------------------
# Test 3: incoming + pusta tresc -> handoff TAK, kolejka NIE
# ---------------------------------------------------------------------------

def test_incoming_pusta_tresc_handoff_bez_kolejki(monkeypatch):
    """Pusta tresc: handoff wywolany, ale brak kolejkowania."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(content="   "))

    assert len(handoffs) == 1, "handoff musi byc wywolany nawet przy pustej tresci"
    assert _count_queue() == 0, "pusta tresc -> brak wpisu w kolejce"


# ---------------------------------------------------------------------------
# Test 4: private=True -> nic (bez handoffu, bez kolejki)
# ---------------------------------------------------------------------------

def test_private_ignorowany(monkeypatch):
    """Prywatna wiadomosc jest ignorowana w calosci."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(private=True))

    assert len(handoffs) == 0, "private=True -> zadnego handoffu"
    assert _count_queue() == 0, "private=True -> brak wpisu w kolejce"


# ---------------------------------------------------------------------------
# Test 5: outgoing (message_type=1) -> nic
# ---------------------------------------------------------------------------

def test_outgoing_ignorowany(monkeypatch):
    """Wiadomosc wychodząca jest ignorowana w calosci."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mtype=1))

    assert len(handoffs) == 0, "outgoing -> zadnego handoffu"
    assert _count_queue() == 0, "outgoing -> brak wpisu w kolejce"


def test_outgoing_string_ignorowany(monkeypatch):
    """Wiadomosc wychodząca (message_type='outgoing') jest ignorowana."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mtype="outgoing"))

    assert len(handoffs) == 0, "outgoing string -> zadnego handoffu"
    assert _count_queue() == 0


# ---------------------------------------------------------------------------
# Test 6: dedup — to samo mid dwa razy -> tylko 1 wpis w kolejce
# ---------------------------------------------------------------------------

def test_dedup_tego_samego_mid(monkeypatch):
    """Duplikat po message_id: drugi wpis zignorowany."""
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(mid="m_dedup"))
    wh._process_agent_bot(_payload(mid="m_dedup"))

    assert _count_queue() == 1, "dedup po mid -> tylko 1 wiersz w suggest_queue"


# ---------------------------------------------------------------------------
# Test 7: nie-message_created event -> nic
# ---------------------------------------------------------------------------

def test_inny_event_ignorowany(monkeypatch):
    """Event inny niz message_created jest ignorowany."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

    wh._process_agent_bot(_payload(event="conversation_updated"))

    assert len(handoffs) == 0
    assert _count_queue() == 0


# ---------------------------------------------------------------------------
# Test 8: inbox_id na poziomie top-level payloadu -> handoff + kolejka
# ---------------------------------------------------------------------------

def test_toplevel_inbox_id_fallback(monkeypatch):
    """Payload z inbox_id na poziomie top-level (bez conversation.inbox_id) jest przetwarzany."""
    handoffs = []
    monkeypatch.setattr(wh, "cw_bot_handoff", lambda conv_id: handoffs.append(conv_id) or True)
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")

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
