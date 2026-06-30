# -*- coding: utf-8 -*-
# Test: chunkowanie, sync_index (dedup po hashu) i retrieve (top-K po cosine).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge.db")
import importlib

db_mod = importlib.import_module("core.db")
kn = importlib.import_module("bots.knowledge")


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db(); c.execute("DELETE FROM kb_chunks"); c.commit(); c.close()


def test_chunk_text_dzieli_dlugi_tekst():
    txt = "akapit\n\n" * 500
    parts = kn.chunk_text(txt, max_chars=100)
    assert len(parts) > 1
    assert all(len(p) <= 100 for p in parts)


def test_cosine_identycznych_wektorow_to_1():
    assert abs(kn.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(kn.cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_sync_index_embeduje_tylko_nowe(monkeypatch):
    arts = [{"id": 1, "title": "Czasy", "content": "Realizacja 14 dni."}]
    monkeypatch.setattr(kn, "cw_articles", lambda slug: arts)
    calls = {"n": 0}
    def fake_embed(texts, **kw):
        calls["n"] += 1
        return [[float(len(t)), 1.0] for t in texts]
    monkeypatch.setattr(kn, "embed", fake_embed)
    n1 = kn.sync_index()
    n2 = kn.sync_index()  # drugi raz: nic nowego do embedowania
    assert n1 >= 1
    assert calls["n"] == 1  # embed wolany tylko za pierwszym razem


def test_retrieve_zwraca_najtrafniejsze(monkeypatch):
    monkeypatch.setattr(kn, "cw_articles",
                        lambda slug: [{"id": 1, "title": "A", "content": "wysyłka kurierem"},
                                      {"id": 2, "title": "B", "content": "gatunki drewna dąb"}])
    # Embedding deterministyczny: wektor zalezny od obecnosci slowa "drewno"/"wysylka".
    def fake_embed(texts, **kw):
        return [[1.0, 0.0] if "wysył" in t else [0.0, 1.0] for t in texts]
    monkeypatch.setattr(kn, "embed", fake_embed)
    kn.sync_index()
    top = kn.retrieve("kiedy wysyłka?", k=1)
    assert len(top) == 1
    assert "wysył" in top[0]


def test_retrieve_pusty_indeks_zwraca_pusto():
    assert kn.retrieve("cokolwiek") == []
