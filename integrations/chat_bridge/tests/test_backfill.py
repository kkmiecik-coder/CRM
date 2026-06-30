# -*- coding: utf-8 -*-
# Testy klasyfikacji wiadomosci w jednorazowym backfillu historii (migracja z Responso).
# Klient -> "incoming"; nasza strona (sprzedawca) -> "note" (notatka prywatna, bez ryzyka wysylki);
# mediator Allegro (ADMIN) -> "incoming" z prefiksem.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

bf = importlib.import_module("backfill")


def kinds(recs):
    return [r["kind"] for r in recs]


def test_olx_klient_incoming_my_note_oraz_kolejnosc_po_id():
    msgs = [
        {"id": "3", "type": "sent", "text": "nasza odpowiedz"},
        {"id": "1", "type": "received", "text": "pytanie klienta"},
        {"id": "2", "type": "received", "text": "drugie pytanie"},
    ]
    recs = bf.build_olx_records(msgs)
    assert [r["text"] for r in recs] == ["pytanie klienta", "drugie pytanie", "nasza odpowiedz"]
    assert kinds(recs) == ["incoming", "incoming", "note"]


def test_olx_zachowuje_przeplatana_kolejnosc_rozmowy():
    # Rozmowa: klient -> my -> klient -> my -> klient (wg id). Backfill MUSI zachowac
    # ten przeplot, a nie zgrupowac "najpierw wszyscy klienci, potem nasze".
    msgs = [
        {"id": "10", "type": "received", "text": "k1"},
        {"id": "11", "type": "sent", "text": "n1"},
        {"id": "12", "type": "received", "text": "k2"},
        {"id": "13", "type": "sent", "text": "n2"},
        {"id": "14", "type": "received", "text": "k3"},
    ]
    recs = bf.build_olx_records(msgs)
    assert [r["text"] for r in recs] == ["k1", "n1", "k2", "n2", "k3"]
    assert kinds(recs) == ["incoming", "note", "incoming", "note", "incoming"]


def test_dispute_zachowuje_przeplatana_kolejnosc():
    chat = [
        {"createdAt": "2026-05-01T09:00:00Z", "author": {"role": "BUYER"}, "text": "k1"},
        {"createdAt": "2026-05-01T09:10:00Z", "author": {"role": "SELLER"}, "text": "n1"},
        {"createdAt": "2026-05-01T09:20:00Z", "author": {"role": "BUYER"}, "text": "k2"},
        {"createdAt": "2026-05-01T09:30:00Z", "author": {"role": "ADMIN"}, "text": "m1"},
        {"createdAt": "2026-05-01T09:40:00Z", "author": {"role": "SELLER"}, "text": "n2"},
    ]
    recs = bf.build_dispute_records(chat)
    assert [r["text"] for r in recs] == ["k1", "n1", "k2", "[Mediator Allegro] m1", "n2"]
    assert kinds(recs) == ["incoming", "note", "incoming", "incoming", "note"]


def test_allegro_msg_klasyfikacja_i_sklejenie_tematu():
    msgs = [
        {"createdAt": "2026-05-01T10:00:00Z", "author": {"isInterlocutor": True},
         "subject": "Zamowienie", "text": "Dzien dobry"},
        {"createdAt": "2026-05-01T11:00:00Z", "author": {"isInterlocutor": False},
         "text": "Dziekujemy za wiadomosc"},
    ]
    recs = bf.build_allegro_msg_records(msgs)
    assert kinds(recs) == ["incoming", "note"]
    assert recs[0]["text"] == "Zamowienie\n\nDzien dobry"   # temat doklejony
    assert recs[1]["text"] == "Dziekujemy za wiadomosc"


def test_dispute_role_seller_note_admin_incoming_z_prefiksem():
    chat = [
        {"createdAt": "2026-05-01T09:00:00Z", "author": {"role": "BUYER"}, "text": "Reklamacja"},
        {"createdAt": "2026-05-01T09:30:00Z", "author": {"role": "SELLER"}, "text": "Nasza odpowiedz"},
        {"createdAt": "2026-05-01T10:00:00Z", "author": {"role": "ADMIN"}, "text": "Stanowisko mediatora"},
    ]
    recs = bf.build_dispute_records(chat)
    assert kinds(recs) == ["incoming", "note", "incoming"]
    assert recs[2]["text"] == "[Mediator Allegro] Stanowisko mediatora"
