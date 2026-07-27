# -*- coding: utf-8 -*-
# Testy rotacji refresh tokenu OLX. Kontekst awarii 2026-07-26/27: OLX zwraca przy KAZDYM
# odswiezeniu nowy refresh token (dokumentacja: "You may need to update access token and
# refresh token in your database"), a stary ma twarde 30 dni zycia (2592000 s). Most
# wyrzucal zwracana wartosc i jechal na tokenie z 26.06 az do jego wygasniecia 26.07 10:08
# — kanal OLX (wysylka I odbior) lezal ~26 h. Zapis rotacji resetuje te 30 dni codziennie.
import pytest
import requests
from unittest import mock

import channels.olx as olx
from core.db import init_db, db, meta_get, meta_set


@pytest.fixture(autouse=True)
def czysty_stan():
    init_db()
    c = db()
    c.execute("DELETE FROM meta WHERE k IN ('olx_refresh_token', 'olx_auth_error')")
    c.commit(); c.close()
    olx._token["access"] = None
    olx._token["exp"] = 0
    yield


def _odpowiedz(payload, status=200):
    r = mock.Mock()
    r.status_code = status
    r.text = str(payload)
    r.json.return_value = payload

    def raise_for_status():
        if status >= 400:
            raise requests.exceptions.HTTPError("%s Client Error" % status, response=r)
    r.raise_for_status = raise_for_status
    return r


def _podstaw_post(monkeypatch, odpowiedzi):
    """Podstawia requests.post; zwraca liste payloadow wyslanych do endpointu tokenu."""
    wyslane = []
    kolejka = list(odpowiedzi)

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        wyslane.append(data)
        return kolejka.pop(0) if len(kolejka) > 1 else kolejka[0]

    monkeypatch.setattr(olx.requests, "post", fake_post)
    return wyslane


def test_zrotowany_refresh_token_zostaje_zapisany(monkeypatch):
    meta_set("olx_refresh_token", "STARY")
    wyslane = _podstaw_post(monkeypatch, [
        _odpowiedz({"access_token": "AT1", "expires_in": 86400, "refresh_token": "NOWY"}),
    ])

    assert olx.get_access_token(force=True) == "AT1"
    assert wyslane[0]["refresh_token"] == "STARY", "do OLX idzie token aktualny"
    assert meta_get("olx_refresh_token") == "NOWY", "zwrocony refresh token MUSI byc zapisany"


def test_kolejne_odswiezenie_uzywa_zrotowanego_tokenu(monkeypatch):
    meta_set("olx_refresh_token", "STARY")
    wyslane = _podstaw_post(monkeypatch, [
        _odpowiedz({"access_token": "AT1", "expires_in": 86400, "refresh_token": "NOWY"}),
        _odpowiedz({"access_token": "AT2", "expires_in": 86400, "refresh_token": "NOWSZY"}),
    ])

    olx.get_access_token(force=True)
    olx.get_access_token(force=True)

    assert wyslane[1]["refresh_token"] == "NOWY", "drugie odswiezenie jedzie na zrotowanym tokenie"
    assert meta_get("olx_refresh_token") == "NOWSZY"


def test_bootstrap_refresh_tokenu_z_env_gdy_baza_pusta(monkeypatch):
    # Pierwszy start po wdrozeniu: w meta nic nie ma, zrodlem jest bridge.env.
    monkeypatch.setattr(olx, "OLX_REFRESH_TOKEN", "Z_ENV")
    wyslane = _podstaw_post(monkeypatch, [
        _odpowiedz({"access_token": "AT1", "expires_in": 86400, "refresh_token": "NOWY"}),
    ])

    olx.get_access_token(force=True)

    assert wyslane[0]["refresh_token"] == "Z_ENV"
    assert meta_get("olx_refresh_token") == "NOWY"


def test_brak_rotacji_nie_kasuje_zapisanego_tokenu(monkeypatch):
    # Gdyby OLX kiedys nie zwrocil refresh_token — zostajemy przy dotychczasowym.
    meta_set("olx_refresh_token", "STARY")
    _podstaw_post(monkeypatch, [_odpowiedz({"access_token": "AT1", "expires_in": 86400})])

    olx.get_access_token(force=True)

    assert meta_get("olx_refresh_token") == "STARY"


def test_wygasly_refresh_token_zostawia_slad_i_nie_kasuje_tokenu(monkeypatch):
    # Dokladnie sytuacja z 26.07: invalid_grant / "Refresh token has expired".
    meta_set("olx_refresh_token", "STARY")
    _podstaw_post(monkeypatch, [_odpowiedz(
        {"error": "invalid_grant", "error_description": "Refresh token has expired"}, status=400)])

    with pytest.raises(requests.exceptions.HTTPError):
        olx.get_access_token(force=True)

    assert meta_get("olx_auth_error"), "pad autoryzacji musi zostawic slad do alertu"
    assert meta_get("olx_refresh_token") == "STARY", "nie kasujemy tokenu przy bledzie sieci/OLX"


def test_udane_odswiezenie_czysci_slad_bledu(monkeypatch):
    meta_set("olx_refresh_token", "STARY")
    meta_set("olx_auth_error", "1785000000")
    _podstaw_post(monkeypatch, [
        _odpowiedz({"access_token": "AT1", "expires_in": 86400, "refresh_token": "NOWY"})])

    olx.get_access_token(force=True)

    assert not meta_get("olx_auth_error"), "po odzyskaniu autoryzacji slad znika"
