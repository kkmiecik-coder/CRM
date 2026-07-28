# -*- coding: utf-8 -*-
# Testy odrzucania zalacznikow niewspieranych przez OLX. Kontekst: 2026-07-28 08:51 agent
# wyslal oferte PDF, OLX odrzucil CALY POST ("Nie mozna dolaczyc pliku w tym formacie.
# Dopuszczalne formaty: jpeg, jpg, png") — zginela tez tresc wiadomosci, a w Chatwoocie
# dymek wygladal na dostarczony. Czwarty taki przypadek (q#20, 405, 542, 626).
# Oczekiwane zachowanie: wykryc format PRZED wyjsciem do OLX, nie ponawiac 5 razy,
# oznaczyc wiadomosc w Chatwoocie jako niedostarczona i powiedziec agentowi dlaczego.
import json
import pytest
from unittest import mock

import channels.olx as olx
import worker as w
from core.errors import PermanentSendError
from core.db import db, init_db

BLOB = "https://chat.woodpower.pl/rails/active_storage/blobs/redirect/eyJfcmFpbHMi--26a274eb/%s"


@pytest.fixture(autouse=True)
def czysta_kolejka():
    init_db()
    c = db(); c.execute("DELETE FROM queue"); c.commit(); c.close()
    yield


# ---------- rozpoznanie formatu ----------

def test_pdf_nie_wychodzi_do_olx(monkeypatch):
    wywolania = []
    monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
    monkeypatch.setattr(olx.requests, "post", lambda *a, **k: wywolania.append(a))

    with pytest.raises(PermanentSendError) as e:
        olx.olx_send("123", "Wycena w zalaczeniu", [BLOB % "Oferta_487_07_26_W.pdf"])

    assert "Oferta_487_07_26_W.pdf" in str(e.value), "powod ma wskazywac konkretny plik"
    assert "JPG" in str(e.value).upper() and "PNG" in str(e.value).upper()
    assert wywolania == [], "nie wolno marnowac 5 prob na blad, ktory sie nie naprawi"


def test_obrazy_przechodza_bez_zmian(monkeypatch):
    for nazwa in ("paleta.jpg", "wzornik.JPEG", "blat.png", "render.PNG"):
        wyslane = []

        def fake_post(url, headers=None, json=None, timeout=None):
            wyslane.append(json)
            r = mock.Mock(); r.status_code = 200 if url.endswith("/messages") else 204
            return r

        monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
        monkeypatch.setattr(olx.requests, "post", fake_post)
        r = olx.olx_send("123", "tresc", [BLOB % nazwa])
        assert r.status_code == 200, "obraz %s musi przejsc" % nazwa


def test_jeden_zly_plik_blokuje_cala_wiadomosc(monkeypatch):
    # OLX i tak odrzuci caly POST — lepiej powiedziec to od razu i konkretnie.
    monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
    monkeypatch.setattr(olx.requests, "post", lambda *a, **k: pytest.fail("nie powinno wyjsc"))

    with pytest.raises(PermanentSendError) as e:
        olx.olx_send("123", "tresc", [BLOB % "zdjecie.jpg", BLOB % "faktura.pdf"])

    assert "faktura.pdf" in str(e.value)
    assert "zdjecie.jpg" not in str(e.value), "wskazujemy tylko winowajce"


def test_wiadomosc_bez_zalacznikow_niezmieniona(monkeypatch):
    wyslane = []

    def fake_post(url, headers=None, json=None, timeout=None):
        wyslane.append((url, json))
        r = mock.Mock(); r.status_code = 200
        return r

    monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
    monkeypatch.setattr(olx.requests, "post", fake_post)
    assert olx.olx_send("123", "sama tresc").status_code == 200


# ---------- reakcja workera ----------

def _wstaw_do_kolejki(att, cw_msg_id="9001"):
    c = db()
    c.execute("INSERT INTO queue(thread_id, conv_id, content, attachments, channel, next_at, cw_msg_id) "
              "VALUES(?,?,?,?,?,0,?)", ("123", 555, "Wycena w zalaczeniu", json.dumps(att), "olx", cw_msg_id))
    c.commit()
    row = c.execute("SELECT * FROM queue ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    return row


def test_trwaly_blad_konczy_sie_od_razu_bez_ponawiania(monkeypatch):
    notatki, oznaczone = [], []
    monkeypatch.setattr(w, "cw_note", lambda conv, tekst, *a, **k: notatki.append((conv, tekst)))
    monkeypatch.setattr(w, "cw_mark_failed", lambda conv, mid, err=None: oznaczone.append((conv, mid, err)))

    class KanalPDF:
        @staticmethod
        def send(tid, content, att):
            raise PermanentSendError("OLX nie przyjmuje pliku faktura.pdf. Dopuszczalne: JPG/JPEG/PNG.")
    monkeypatch.setitem(w.REGISTRY, "olx", KanalPDF)

    row = _wstaw_do_kolejki([BLOB % "faktura.pdf"])
    w.process_row(row)

    c = db(); po = c.execute("SELECT status, attempts FROM queue WHERE id=?", (row["id"],)).fetchone(); c.close()
    assert po["status"] == "failed"
    assert po["attempts"] == 1, "trwaly blad nie moze isc przez 5 prob i 30 s backoffu"
    assert notatki and "faktura.pdf" in notatki[0][1]
    assert "JPG" in notatki[0][1].upper() and "PNG" in notatki[0][1].upper()
    assert len(oznaczone) == 1, "wiadomosc w Chatwoocie ma byc oznaczona jako niedostarczona"
    conv, mid, powod = oznaczone[0]
    assert (conv, mid) == (555, "9001")
    assert "faktura.pdf" in (powod or ""), "czerwony dymek ma niesc powod, nie samo 'blad'"


def test_zwykly_blad_dalej_jest_ponawiany(monkeypatch):
    # Regresja: przejsciowe 400/500 musza zachowac dotychczasowy retry+backoff.
    monkeypatch.setattr(w, "cw_note", lambda *a, **k: None)
    monkeypatch.setattr(w, "cw_mark_failed", lambda *a, **k: None)

    class KanalPada:
        @staticmethod
        def send(tid, content, att):
            r = mock.Mock(); r.status_code = 500; r.text = "server error"
            return r
    monkeypatch.setitem(w.REGISTRY, "olx", KanalPada)

    row = _wstaw_do_kolejki([])
    w.process_row(row)

    c = db(); po = c.execute("SELECT status, attempts FROM queue WHERE id=?", (row["id"],)).fetchone(); c.close()
    assert po["status"] == "pending", "przejsciowy blad ma czekac na kolejna probe"
    assert po["attempts"] == 1


def test_sukces_oznacza_wyslane(monkeypatch):
    monkeypatch.setattr(w, "cw_note", lambda *a, **k: None)
    monkeypatch.setattr(w, "cw_mark_failed", lambda *a, **k: None)

    class KanalOk:
        @staticmethod
        def send(tid, content, att):
            r = mock.Mock(); r.status_code = 200
            return r
    monkeypatch.setitem(w.REGISTRY, "olx", KanalOk)

    row = _wstaw_do_kolejki([])
    w.process_row(row)

    c = db(); po = c.execute("SELECT status FROM queue WHERE id=?", (row["id"],)).fetchone(); c.close()
    assert po["status"] == "sent"
