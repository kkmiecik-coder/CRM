# -*- coding: utf-8 -*-
# Test: dedup obrazow (sent_images) + wysylka 1a/1b w silniku live-bota.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_liveimg.db")
os.environ["BOT_LIVE_CW_AGENT_TOKEN"] = "live-tok-img"
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
images = importlib.import_module("bots.images"); importlib.reload(images)
lc = importlib.import_module("bots.livechat"); importlib.reload(lc)

_IMG = None


def _plik(nazwa):
    with open(os.path.join(_IMG, nazwa), "wb") as f:
        f.write(b"\xff\xd8\xff")


def setup_function(_):
    # Swiezy katalog obrazow + env na kazdy test (images._dir() czyta env przy wywolaniu).
    global _IMG
    _IMG = tempfile.mkdtemp()
    os.environ["BOT_IMAGES_DIR"] = _IMG
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_state"); c.execute("DELETE FROM live_dane")
    c.commit(); c.close()


def test_sent_images_pusty_gdy_brak():
    assert lc._sent_images(1) == set()


def test_mark_i_odczyt_sent_images():
    lc._mark_image_sent(1, "gatunki_porownanie")
    lc._mark_image_sent(1, "sample:dab|lity|ab|olejowane")
    assert lc._sent_images(1) == {"gatunki_porownanie", "sample:dab|lity|ab|olejowane"}
