# -*- coding: utf-8 -*-
# Testy rundy poprawek quote-bota: copy ceny (Grupa 1), kontakt z czatu + trwalosc (Grupa 2),
# powitanie powracajacego klienta (Grupa 3), aktualizacja wyceny zamiast nowej (Grupa 4).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Detal"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qref.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "140", "szerokosc": "80", "grubosc": "3",
            "gatunek": "dąb", "technologia": "mikrowczep", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


# --- Grupa 1: wiadomosc z cena ---

def test_cena_msg_bez_preambuly_z_linia_parametrow():
    dane = {"pozycje": [_poz()], "wspolne": {}}
    msg = qb._cena_msg(dane, {"total_netto": 480.48, "total_brutto": 590.99})
    assert "Wstępna wycena" not in msg and "wstępny szacunek" not in msg
    assert msg.splitlines()[0].startswith("Blat")          # produkt podany -> "Blat", nie "Klejonka"
    assert "140×80×3 cm" in msg
    assert "Netto: 480,48 zł" in msg and "Brutto: 590,99 zł" in msg


def test_linia_pozycji_fallback_klejonka():
    assert qb._linia_pozycji({"gatunek": "dąb", "dlugosc": "200"}).startswith("Klejonka")


def test_pytanie_o_braki_lista_od_myslnika():
    poz = {"produkt": "blat"}
    brak = [(poz, "gatunek"), (poz, "technologia"), (poz, "klasa")]
    msg = qb._pytanie_o_braki(brak, False)
    assert msg.count("\n- ") >= 3          # kazdy brak w osobnej linii od "-"


# --- Grupa 2: kontakt z czatu + trwalosc ---

def test_effective_contact_bierze_email_z_czatu_i_zapamietuje():
    dane = {"pozycje": [_poz()], "wspolne": {"kontakt": "proszę pisać na jan@x.pl"}}
    email, phone, name = qb._effective_contact(700, dane, {"name": "Jan", "email": "", "phone": ""})
    assert email == "jan@x.pl"
    assert qb._stored_contact(700)[0] == "jan@x.pl"      # zapamietany na kolejne wyceny


def test_kontakt_zapamietany_drugi_raz_bez_pytania(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "totals": {"total_netto": 10.0, "total_brutto": 12.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n: {"ok": True, "client": {"id": 42}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda uid, p, o, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    dane = {"pozycje": [_poz()], "wspolne": {"kontakt": "jan@x.pl"}}
    qb._wyslij_cene_i_kontakt(701, dane, {"name": "", "email": "", "phone": ""})
    assert any("q/a" in r for r in replies)              # 1. raz: zapis + link (mail z czatu)
    replies.clear()
    dane2 = {"pozycje": [_poz(), _poz(id="2", produkt="parapet", dlugosc="260", szerokosc="43")],
             "wspolne": {}}                              # brak kontaktu w 2. turze
    qb._wyslij_cene_i_kontakt(701, dane2, {"name": "", "email": "", "phone": ""})
    assert not any("adres e-mail" in r for r in replies)  # NIE pyta ponownie o kontakt
    assert any("Zaktualizowałem" in r for r in replies)   # aktualizacja istniejacej, nie nowa


# --- Grupa 3: powracajacy klient ---

def test_powracajacy_klient_powitanie_raz(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n: {"ok": True, "matched": True, "client": {"id": 9}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a"})
    qb._zapisz_wycene(702, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", "", "Jan")
    assert any("wraca" in r for r in replies)


# --- Grupa 4: aktualizacja zamiast nowej wyceny ---

def test_update_gdy_zapamietany_edit_uuid(monkeypatch):
    called = {}
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n: {"ok": True, "client": {"id": 9}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda *a, **k: called.update(create=True) or {"ok": False})
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda uid, p, o, notes="": called.update(update=uid) or
                        {"ok": True, "quote_number": "W/1", "public_url": "https://crm/q/a"})
    qb._set_edit_uuid(703, "UU-123")
    qb._zapisz_wycene(703, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", "", "Jan")
    assert called.get("update") == "UU-123"
    assert "create" not in called


def test_wyciagnij_kontakt_odrzuca_krotki_ciag_cyfr():
    # 6-cyfrowy nr zamowienia -> NIE telefon; email nadal lapany.
    assert qb._wyciagnij_kontakt("zamówienie 123456")[1] == ""
    assert qb._wyciagnij_kontakt("tel 501 234 567")[1] != ""      # 9 cyfr -> ok
    assert qb._wyciagnij_kontakt("mail: a@b.pl")[0] == "a@b.pl"
