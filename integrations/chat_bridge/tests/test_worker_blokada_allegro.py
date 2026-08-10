# -*- coding: utf-8 -*-
# Testy bramki wysylki w workerze: podpis Chatwoota nie moze wyjsc na OLX/Allegro,
# a tresc z danymi kontaktowymi nie moze wyjsc na Allegro (ostrzezenie z 10.08.2026).
from unittest import mock

import worker
from core.db import db, init_db

PODPIS = (
    "**Anna Paszkowska**\n"
    "Specjalista ds. Obsługi Klienta\n"
    "anna.paszkowska@woodpower.pl: mailto:anna.paszkowska@woodpower.pl\n"
    "woodpower.pl: https://woodpower.pl"
)
STOPKA = "Pozdrawiam,\nAnna Paszkowska\nDział Obsługi Klienta\nWood Power Sp. z o.o."


class _KanalAtrapa(object):
    def __init__(self):
        self.wyslane = []

    def send(self, tid, content, att_urls):
        self.wyslane.append(content)
        r = mock.Mock()
        r.status_code = 200
        r.text = ""
        return r


def _zakolejkuj(channel, content, conv_id=77):
    init_db()
    c = db()
    cur = c.execute("INSERT INTO queue(thread_id, conv_id, content, channel, footer, cw_msg_id, next_at) "
                    "VALUES(?,?,?,?,?,?,0)", ("t1", conv_id, content, channel, STOPKA, "555"))
    qid = cur.lastrowid
    c.commit()
    row = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    c.close()
    return qid, row


def _status(qid):
    c = db()
    row = c.execute("SELECT status, last_error FROM queue WHERE id=?", (qid,)).fetchone()
    c.close()
    return row["status"], row["last_error"]


def _podepnij_atrape(monkeypatch, channel):
    kanal = _KanalAtrapa()
    monkeypatch.setattr(worker, "REGISTRY", {channel: kanal, "olx": kanal})
    wywolania = {"note": [], "failed": [], "reopen": []}
    monkeypatch.setattr(worker, "cw_note", lambda cid, txt, *a, **k: wywolania["note"].append(txt))
    monkeypatch.setattr(worker, "cw_mark_failed", lambda cid, mid, err=None: wywolania["failed"].append(err))
    monkeypatch.setattr(worker, "cw_reopen", lambda cid: wywolania["reopen"].append(cid))
    return kanal, wywolania


def test_allegro_z_linkiem_nie_wychodzi(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "allegro_msg")
    qid, row = _zakolejkuj("allegro_msg", "cennik mamy na woodpower.pl")

    worker.process_row(row)

    assert kanal.wyslane == [], "wiadomosc z linkiem nie moze trafic na Allegro"
    status, blad = _status(qid)
    assert status == "blocked"
    assert "woodpower.pl" in blad


def test_zablokowana_wiadomosc_daje_znac_agentowi(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "allegro_msg")
    qid, row = _zakolejkuj("allegro_msg", "proszę pisać na biuro@woodpower.pl", conv_id=88)

    worker.process_row(row)

    assert len(wyw["note"]) == 1 and "biuro@woodpower.pl" in wyw["note"][0]
    assert len(wyw["failed"]) == 1
    assert wyw["reopen"] == [88], "rozmowa ma wrocic do open, zeby agent zobaczyl problem"


def test_allegro_bez_danych_kontaktowych_wychodzi_ze_stopka(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "allegro_msg")
    qid, row = _zakolejkuj("allegro_msg", "ok to docinamy wg ww wymiarów")

    worker.process_row(row)

    assert kanal.wyslane == ["ok to docinamy wg ww wymiarów\n\n" + STOPKA]
    assert _status(qid)[0] == "sent"
    assert wyw["reopen"] == []


def test_podpis_chatwoota_nie_wychodzi_na_allegro(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "allegro_msg")
    qid, row = _zakolejkuj("allegro_msg", "fv w panelu klienta\n\n--\n\n" + PODPIS)

    worker.process_row(row)

    assert kanal.wyslane == ["fv w panelu klienta\n\n" + STOPKA]
    assert _status(qid)[0] == "sent", "sam podpis wycinamy, to nie powod do blokady"


def test_olx_z_podpisem_wychodzi_bez_podpisu(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "olx")
    qid, row = _zakolejkuj("olx", "jaka grubość ?\n\n--\n\n" + PODPIS)

    worker.process_row(row)

    assert kanal.wyslane == ["jaka grubość ?\n\n" + STOPKA]
    assert _status(qid)[0] == "sent"


def test_olx_z_linkiem_nie_jest_blokowany(monkeypatch):
    kanal, wyw = _podepnij_atrape(monkeypatch, "olx")
    qid, row = _zakolejkuj("olx", "zapraszamy na woodpower.pl")

    worker.process_row(row)

    assert len(kanal.wyslane) == 1
    assert _status(qid)[0] == "sent"
