# -*- coding: utf-8 -*-
import importlib
from unittest import mock
prov = importlib.import_module("setup.provision_chatwoot")


def _fake_client(existing_labels=None, existing_folders=None, existing_rules=None):
    client = mock.Mock()
    def _get(path):
        r = mock.Mock(status_code=200)
        if path == "/labels":
            r.json.return_value = {"payload": existing_labels or []}
        elif path == "/custom_filters":
            r.json.return_value = {"payload": existing_folders or []}
        elif path == "/automation_rules":
            r.json.return_value = {"payload": existing_rules or []}
        else:
            r.json.return_value = {}
        return r
    client.get.side_effect = _get
    client.post.return_value = mock.Mock(status_code=200, json=lambda: {"id": 1})
    return client


def test_build_plan_pomija_istniejace_etykiety():
    client = _fake_client(existing_labels=[{"title": "wycena"}, {"title": "pilne"}])
    plan = prov.build_plan(client)
    titles = [l["title"] for l in plan["labels"]]
    assert "wycena" not in titles and "pilne" not in titles
    assert "reklamacja" in titles


def test_build_plan_pusty_gdy_wszystko_jest():
    from setup import desired_state as ds
    client = _fake_client(
        existing_labels=[{"title": l["title"]} for l in ds.LABELS],
        existing_folders=[{"name": f["name"]} for f in ds.FOLDERS],
    )
    plan = prov.build_plan(client)
    assert plan["labels"] == []
    assert plan["folders"] == []


def test_apply_plan_wola_post_dla_kazdego_elementu():
    client = _fake_client()
    plan = {"labels": [{"title": "x", "color": "#111"}], "folders": [], "rules": []}
    log = prov.apply_plan(client, plan)
    assert client.post.called
    assert any("etykieta" in l.lower() for l in log)


def test_run_dry_run_nie_wola_post():
    client = _fake_client()
    with mock.patch.object(prov, "_make_client", return_value=client):
        rc = prov.run(["--dry-run"])
    assert rc == 0
    assert not client.post.called
