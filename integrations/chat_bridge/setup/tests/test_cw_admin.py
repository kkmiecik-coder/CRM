# -*- coding: utf-8 -*-
import importlib
from unittest import mock
cwa = importlib.import_module("setup.cw_admin")


def test_to_create_pomija_istniejace_po_nazwie():
    desired = [{"title": "wycena"}, {"title": "pilne"}, {"title": "techniczne"}]
    existing = {"pilne"}
    out = cwa.to_create(existing, desired, "title")
    assert [d["title"] for d in out] == ["wycena", "techniczne"]


def test_to_create_pusta_lista_gdy_wszystko_istnieje():
    desired = [{"name": "Pilne"}]
    out = cwa.to_create({"Pilne"}, desired, "name")
    assert out == []


def test_verify_admin_rzuca_gdy_brak_uprawnien():
    client = cwa.CwAdmin("http://x", "1", "tok")
    resp = mock.Mock(status_code=403, text="forbidden")
    with mock.patch("requests.request", return_value=resp):
        try:
            client.verify_admin()
            assert False, "powinno rzucic PermissionError"
        except PermissionError:
            pass


def test_get_buduje_poprawny_url_i_naglowek():
    client = cwa.CwAdmin("http://x", "7", "tok")
    resp = mock.Mock(status_code=200)
    with mock.patch("requests.request", return_value=resp) as m:
        client.get("/labels")
        args, kwargs = m.call_args
        assert args[0] == "GET"
        assert args[1] == "http://x/api/v1/accounts/7/labels"
        assert kwargs["headers"]["api_access_token"] == "tok"
