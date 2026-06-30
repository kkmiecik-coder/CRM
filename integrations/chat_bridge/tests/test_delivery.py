# -*- coding: utf-8 -*-
# Testy dostawy wiadomosci do Chatwoota: wodowskaz (last_seen) przesuwa sie wylacznie
# za REALNIE dostarczone wiadomosci. Reprodukcja buga z 2026-06-30 (awaria tokena CW):
# niedostarczone wiadomosci nie moga zostac oznaczone jako "widziane".
import os
# Atrapa wymaganych env (jak w _smoke.py) — config.py czyta je przy imporcie.
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

util = importlib.import_module("core.util")


class FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_cw_ok_rozpoznaje_sukces_i_porazke():
    assert util.cw_ok(FakeResp(200)) is True
    assert util.cw_ok(FakeResp(201)) is True
    assert util.cw_ok(FakeResp(401)) is False
    assert util.cw_ok(FakeResp(500)) is False
    assert util.cw_ok(None) is False  # brak odpowiedzi = porazka


def test_deliver_wszystkie_dostarczone():
    msgs = [{"id": 1}, {"id": 2}, {"id": 3}]
    sent = []

    def send(m):
        sent.append(m["id"])
        return FakeResp(200)

    delivered, ok = util.deliver_in_order(msgs, lambda m: m["id"], send)
    assert ok is True
    assert delivered == 3
    assert sent == [1, 2, 3]


def test_deliver_zatrzymuje_sie_na_pierwszej_porazce():
    # Wiadomosc 1 dostarczona, 2 pada (401) -> wodowskaz tylko do 1, 3 nieproszona.
    msgs = [{"id": 1}, {"id": 2}, {"id": 3}]
    sent = []

    def send(m):
        sent.append(m["id"])
        return FakeResp(200 if m["id"] == 1 else 401)

    delivered, ok = util.deliver_in_order(msgs, lambda m: m["id"], send)
    assert ok is False
    assert delivered == 1            # nie przesuwamy za niedostarczona wiadomosc
    assert sent == [1, 2]            # przerwano po porazce 2, nie probowano 3


def test_deliver_pierwsza_pada_nic_nie_dostarczono():
    msgs = [{"id": 5}, {"id": 6}]

    def send(m):
        return FakeResp(401)

    delivered, ok = util.deliver_in_order(msgs, lambda m: m["id"], send)
    assert ok is False
    assert delivered is None         # zadna nie dostarczona -> wodowskaz bez ruchu


def test_deliver_pomija_klucz_none_zachowujac_ostatni_poprawny():
    # Wiadomosc bez uzytecznego klucza (msg_key -> None) nie moze cofnac wodowskazu:
    # delivered_key zostaje na ostatnim NIEPUSTYM kluczu dostarczonej wiadomosci.
    msgs = [{"k": "a"}, {"k": None}, {"k": "c"}]
    delivered, ok = util.deliver_in_order(msgs, lambda m: m["k"], lambda m: FakeResp(200))
    assert ok is True
    assert delivered == "c"
    # gdy ostatnia ma klucz None, trzymamy poprzedni poprawny
    msgs2 = [{"k": "a"}, {"k": None}]
    delivered2, ok2 = util.deliver_in_order(msgs2, lambda m: m["k"], lambda m: FakeResp(200))
    assert ok2 is True
    assert delivered2 == "a"


def test_deliver_wyjatek_traktowany_jak_niedostawa():
    # Wyjatek z send_fn (np. timeout) zatrzymuje dostawe i zwraca postep do ostatniej
    # dostarczonej wiadomosci — bez propagacji wyjatku, bez gubienia juz wyslanych.
    msgs = [{"id": 1}, {"id": 2}, {"id": 3}]
    sent = []

    def send(m):
        sent.append(m["id"])
        if m["id"] == 2:
            raise RuntimeError("network down")
        return FakeResp(200)

    delivered, ok = util.deliver_in_order(msgs, lambda m: m["id"], send)
    assert ok is False
    assert delivered == 1            # postep zachowany do ostatniej dostarczonej
    assert sent == [1, 2]            # przerwano na wyjatku, nie probowano 3


def test_deliver_pusta_lista_jest_ok():
    delivered, ok = util.deliver_in_order([], lambda m: m["id"], lambda m: FakeResp(200))
    assert ok is True
    assert delivered is None
