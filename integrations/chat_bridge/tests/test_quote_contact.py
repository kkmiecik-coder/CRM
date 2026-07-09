# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 10: kontakt bez pulapek. SB-01 (kontakt+korekta), LS-02 (globalny przechwyt po
# cenie), API-13 (normalizacja e-mail/telefon).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qcontact.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
crm = importlib.import_module("bots.crm_calc")

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def _patch(monkeypatch, replies, saved):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "Jan", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: '{"odpowiedz":"Jasne.","handoff":false,"pozycje":[],"wspolne":{}}')
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: saved.update(email=e, phone=p) or
                        {"ok": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1", "public_url": "https://crm/q/z"})


def _seed(conv_id, **flags):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(_KOMPLET)))
    cols = ["bot_turns"] + list(flags)
    c.execute("INSERT INTO quote_state(conv_id, %s) VALUES(%s)" % (",".join(cols), ",".join("?" * (len(cols) + 1))),
              tuple([conv_id, 1] + [flags[k] for k in flags]))
    c.commit(); c.close()


def test_sb01_kontakt_plus_korekta_nie_zapisuje_starej(monkeypatch):
    """SB-01: mail + korekta w jednej wiadomosci -> NIE zapisujemy starej wyceny; tura idzie dalej."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6001, priced=1, awaiting_contact=1)
    qb.run_quote_turn(6001, 12, "m1", "mój mail to jan@kowalski.pl, ale najpierw zmieńcie dąb na jesion")
    assert not saved, "przy kontakcie+korekcie NIE zapisujemy od razu (stara wycena)"
    assert not any("crm/q/z" in r for r in replies), "brak linku do starej wyceny"


def test_sb01_sam_kontakt_zapisuje(monkeypatch):
    """Sam kontakt (bez korekty) w awaiting_contact -> zapis od razu (regresja)."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6002, priced=1, awaiting_contact=1)
    qb.run_quote_turn(6002, 12, "m1", "jan@kowalski.pl")
    assert saved.get("email") == "jan@kowalski.pl"
    assert any("crm/q/z" in r for r in replies)


def test_ls02_globalny_przechwyt_po_cenie(monkeypatch):
    """LS-02: po cenie i po odmowie (awaiting_contact=0) spontaniczny mail -> i tak zapis wyceny."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6003, priced=1)   # brak awaiting_contact (klient wczesniej odmowil)
    qb.run_quote_turn(6003, 12, "m1", "a jednak zapiszcie, jan.kowalski@gmail.com")
    assert saved.get("email") == "jan.kowalski@gmail.com", "spontaniczny kontakt po cenie zapisuje wycene"
    assert any("crm/q/z" in r for r in replies)


def test_api13_normalizacja_email_i_tel(monkeypatch):
    """API-13: e-mail -> lower, telefon -> 9 cyfr krajowych (dedup po dokladnym stringu dziala)."""
    captured = {}
    monkeypatch.setattr(crm, "_post", lambda path, body: captured.update(body) or {"ok": True, "client": {"id": 1}})
    crm.find_or_create_client("Jan.Kowalski@GMAIL.com", "+48 501 234 567", "Jan")
    assert captured["email"] == "jan.kowalski@gmail.com"
    assert captured["phone"] == "501234567"


# --- LS-01: lead zawsze zapisany w CRM, niezaleznie od kontaktu ---

def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
            "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


def test_cena_zapisuje_lead_bez_kontaktu(monkeypatch):
    replies, notes = [], []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: notes.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1000.0, "total_netto": 813.0}})
    captured = {}
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: captured.update(
                            email=e, phone=p, client_number=client_number) or
                            {"ok": True, "matched": False, "created": True, "client": {"id": 99}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._wyslij_cene_i_kontakt(950, {"pozycje": [_poz()], "wspolne": {}}, {})
    assert captured["client_number"] == "chat-950"
    assert not captured["email"] and not captured["phone"]
    assert qb._stored_edit_uuid(950) == "UU"     # wycena JUZ zapisana, mimo braku kontaktu
    assert any("e-mail" in r.lower() or "telefon" in r.lower() for r in replies)
    assert any(n for n in notes)   # prywatna notatka z parametrami+cena poszla


def test_maks_dwa_dymki_po_cenie_bez_kontaktu(monkeypatch):
    """LS-12: prosba o kontakt + oferta wysylki sklejone w JEDNA wiadomosc — maks. 2 dymki
    publiczne po cenie (cena + sklejony dopisek), nie 3 osobne."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1.0, "total_netto": 1.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._wyslij_cene_i_kontakt(956, {"pozycje": [_poz()], "wspolne": {}}, {})
    assert len(replies) == 2   # cena + (prosba o kontakt sklejona z oferta wysylki)
    assert "kod pocztowy" in replies[1] and ("e-mail" in replies[1].lower() or "telefon" in replies[1].lower())
    assert qb._awaiting_contact(956) is True
    assert qb._awaiting_postcode(956) is True


def test_maks_dwa_dymki_po_cenie_z_kontaktem(monkeypatch):
    """Gdy kontakt jest juz znany w momencie liczenia ceny, link zapisu i oferta wysylki takze
    ida sklejone w JEDNEJ wiadomosci (maks. 2 dymki: cena + sklejony link+wysylka)."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1.0, "total_netto": 1.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._wyslij_cene_i_kontakt(957, {"pozycje": [_poz()], "wspolne": {}},
                              {"name": "Jan", "email": "jan@x.pl", "phone": ""})
    assert len(replies) == 2   # cena + (link zapisu sklejony z oferta wysylki)
    assert "Zapisałem" in replies[1] and "kod pocztowy" in replies[1]
    assert qb._awaiting_postcode(957) is True


def test_lead_note_nie_wywraca_tury_gdy_cw_note_pada(monkeypatch):
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1.0, "total_netto": 1.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._wyslij_cene_i_kontakt(951, {"pozycje": [_poz()], "wspolne": {}}, {})   # nie rzuca


def test_zapis_leada_bez_kontaktu_pada_nie_robi_handoffu(monkeypatch):
    """Bez podanego kontaktu nieudany zapis leada technicznego to CICHY blad (log + kontynuacja) —
    NIE handoff z komunikatem 'Dziękuję za kontakt!', bo klient zadnego kontaktu nie podal."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1000.0, "total_netto": 813.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": False, "client": {}})
    qb._wyslij_cene_i_kontakt(952, {"pozycje": [_poz()], "wspolne": {}}, {})
    assert not any("Dziękuję za kontakt" in r for r in replies), "klient nie podal kontaktu"
    assert any("e-mail" in r.lower() or "telefon" in r.lower() for r in replies), (
        "mimo nieudanego zapisu leada bot normalnie prosi o kontakt")


def test_zapis_leada_z_kontaktem_pada_robi_handoff(monkeypatch):
    """Regresja MS-05: gdy klient JUZ podal kontakt, a zapis pada, koniec ciszy — handoff."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": False, "client": {}})
    qb._zapisz_wycene(953, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    assert any("Dziękuję za kontakt" in r for r in replies)


def test_handoff_z_kontaktem_nie_kontynuuje_oferta_wysylki(monkeypatch):
    """Gdy zapis wyceny Z KONTAKTEM pada (_do_handoff), _wyslij_cene_i_kontakt NIE moze kontynuowac
    normalnymi follow-upami (oferta wysylki) — to zaprzeczaloby wlasnie wykonanemu handoffowi."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1000.0, "total_netto": 813.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": False, "client": {}})
    qb._wyslij_cene_i_kontakt(955, {"pozycje": [_poz()], "wspolne": {"kontakt": "jan@x.pl"}},
                              {"name": "Jan", "email": "jan@x.pl", "phone": ""})
    assert any("Dziękuję za kontakt" in r for r in replies)
    assert not any("kod pocztowy" in r for r in replies), "handoff juz sie stal, bot nie dopytuje dalej"
    assert qb._awaiting_postcode(955) is False


def test_pierwszy_zapis_z_kontaktem_po_wczesniejszym_leadzie_mowi_zapisalem(monkeypatch):
    """Klient dostal cene bez kontaktu (lead techniczny juz ma edit_uuid), potem podaje e-mail —
    z JEGO perspektywy to PIERWSZY zapis, wiec komunikat ma mowic 'Zapisałem', nie 'Zaktualizowałem'."""
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": False, "client": {"id": 42}})
    monkeypatch.setattr(qb.crm_calc, "update_quote",
                        lambda uid, p, o, **kw: {"ok": True, "quote_number": "W/1",
                                                 "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._set_edit_uuid(954, "UU")   # lead techniczny juz zapisany bez kontaktu wczesniej
    qb._zapisz_wycene(954, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    assert any("Zapisałem" in r for r in replies)
    assert not any("Zaktualizowałem" in r for r in replies)


def test_wzmianka_powracajacego_dopiero_po_udanym_zapisie(monkeypatch):
    """LS-09: wzmianka o powracajacym kliencie idzie DOPIERO po udanym zapisie wyceny, nie przed —
    gdy sam zapis pada, klient nie moze uslyszec 'widzimy wczesniejsze wyceny' bez linku do nich."""
    order = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: order.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": True,
                                                             "created": False, "client": {"id": 5}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": False, "errors": []})  # ZAPIS PADA
    qb._zapisz_wycene(995, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    assert not any("wcześniejsze wyceny" in t for t in order)  # zapis padl -> BEZ wzmianki


def test_wzmianka_powracajacego_idzie_po_udanym_zapisie(monkeypatch):
    order = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: order.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": True,
                                                             "created": False, "client": {"id": 5}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a"})
    qb._zapisz_wycene(996, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    wzmianka_idx = next(i for i, t in enumerate(order) if "wcześniejsze wyceny" in t)
    link_idx = next(i for i, t in enumerate(order) if "Zapisałem" in t)
    assert wzmianka_idx < link_idx, "wzmianka idzie PRZED linkiem, w tej samej udanej turze"
