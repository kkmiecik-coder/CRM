# -*- coding: utf-8 -*-
# Test: rejestr obrazow wysylanych + lookup probek wg konfiguracji (konwencja nazwy pliku).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib
import config; importlib.reload(config)
images = importlib.import_module("bots.images"); importlib.reload(images)

_IMG = None


def setup_function(_):
    # Swiezy katalog + env na KAZDY test -> izolacja od innych plikow testowych
    # (images._dir() czyta env przy wywolaniu, wiec to wystarcza, bez reimportu).
    global _IMG
    _IMG = tempfile.mkdtemp()
    os.environ["BOT_IMAGES_DIR"] = _IMG


def _plik(nazwa):
    with open(os.path.join(_IMG, nazwa), "wb") as f:
        f.write(b"\xff\xd8\xff")  # udawany JPEG


def test_whitelist_prompt_zawiera_gatunki():
    p = images.whitelist_prompt()
    assert "gatunki_porownanie" in p and "usłojeniu" in p


def test_resolve_znany_tag_gdy_plik_istnieje():
    _plik("gatunki_porownanie.jpg")
    assert images.resolve("gatunki_porownanie") == os.path.join(_IMG, "gatunki_porownanie.jpg")


def test_resolve_nieznany_tag_none():
    assert images.resolve("nie_ma_takiego") is None


def test_resolve_brak_pliku_none():
    # swiezy katalog bez pliku -> None (znany tag, ale brak zdjecia)
    assert images.resolve("gatunki_porownanie") is None


def test_resolve_sample_dopasowuje_konfiguracje():
    _plik("dab_lity_ab_lakierowane.jpg")
    poz = {"gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "wykonczenie": "lakier"}
    assert images.resolve_sample(poz) == os.path.join(_IMG, "dab_lity_ab_lakierowane.jpg")


def test_resolve_sample_brak_pliku_none():
    # buk lity lakierowane: oferowane, brak zdjecia -> None (bez wyjatku)
    poz = {"gatunek": "buk", "technologia": "lity", "klasa": "AB", "wykonczenie": "lakierowane"}
    assert images.resolve_sample(poz) is None


def test_resolve_sample_niepelna_konfiguracja_none():
    assert images.resolve_sample({"gatunek": "dąb", "technologia": "lita"}) is None


def test_sample_key_stabilny():
    poz = {"gatunek": "Dąb", "technologia": "lita", "klasa": "A/B", "wykonczenie": "olejowane"}
    assert images.sample_key(poz) == "sample:dab|lity|ab|olejowane"


def test_sample_key_niepelna_none():
    assert images.sample_key({"gatunek": "dąb"}) is None


def test_resolve_sample_nie_dict_none():
    assert images.resolve_sample("nie dict") is None
    assert images.resolve_sample(42) is None


def test_sample_key_nie_dict_none():
    assert images.sample_key(["lista"]) is None
    assert images.sample_key(None) is None
