# -*- coding: utf-8 -*-
# Testy wysylki GlobKurier w quotebocie: helpery stanu/kodu/komunikatu, oferta po zapisie,
# obsluga oszacowania + dopisanie do wyceny.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Detal"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qwys.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
            "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


# --- helpery stanu / kodu / komunikatu ---

def test_awaiting_postcode_set_get():
    qb._set_awaiting_postcode(900, True)
    assert qb._awaiting_postcode(900) is True
    qb._set_awaiting_postcode(900, False)
    assert qb._awaiting_postcode(900) is False


def test_wyciagnij_kod():
    assert qb._wyciagnij_kod("mój kod to 36-068 proszę") == "36-068"
    assert qb._wyciagnij_kod("Kraków, ul. Długa") is None
    assert qb._wyciagnij_kod("") is None


def test_wysylka_msg_najtansza_z_cena():
    msg = qb._wysylka_msg({"ok": True, "carriers": 3, "carrier_name": "InPost",
                           "shipping_brutto": 104.0})
    assert "InPost" in msg and "104,00 zł" in msg


def test_wysylka_msg_gabaryt_bez_kuriera():
    assert "konsultant" in qb._wysylka_msg({"ok": True, "carriers": 0})


def test_wysylka_msg_blad_api():
    assert "konsultant" in qb._wysylka_msg({"ok": False, "errors": []})
