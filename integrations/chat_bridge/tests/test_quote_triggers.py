# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 3: zawezenie regexow-pulapek + kolejnosc bramek. Znaleziska:
# RX-01..RX-08, RX-11, RX-12, MS-01, MS-06, MS-09, MS-10, MS-11, SB-02, SB-03, SB-05, SB-06,
# SB-07, LS-03. Wspolne regexy sprawdzamy w OBU botach (quotebot + livechat).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qtrig.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
lc = importlib.import_module("bots.livechat"); importlib.reload(lc)


# ---------------- Reklamacja: pytania przedsprzedazowe NIE sa reklamacja (RX-01, SB-06) ----------------

import pytest

@pytest.mark.parametrize("bot", [qb, lc])
def test_reklamacja_pytania_przedsprzedazowe_false(bot):
    assert bot._czy_reklamacja("czy taki blat mi nie pęknie po roku?") is False
    assert bot._czy_reklamacja("zależy mi, żeby się nie wypaczył") is False
    assert bot._czy_reklamacja("chcę kupić blat odporny na pęknięcia") is False
    assert bot._czy_reklamacja("czy jak kupię surowy to mi się nie wypaczy?") is False
    assert bot._czy_reklamacja(
        "poprzedni blat z marketu mi pękł, dlatego szukam czegoś solidnego, co polecacie?") is False


@pytest.mark.parametrize("bot", [qb, lc])
def test_reklamacja_prawdziwa_true(bot):
    assert bot._czy_reklamacja("chcę reklamować") is True
    assert bot._czy_reklamacja("mam reklamację, uszkodzony blat") is True
    assert bot._czy_reklamacja("mój blat pękł po miesiącu") is True
    assert bot._czy_reklamacja("zamówiłem u was blat i przyszedł uszkodzony") is True
    # zachowanie z istniejacych testow livechata
    assert bot._czy_reklamacja("jak uniknąć pęknięć w blacie?") is False
    assert bot._czy_reklamacja("czy to się nie uszkodzi?") is False


# ---------------- Prosba o czlowieka: wymagana INTENCJA (RX-04, MS-09) ----------------

@pytest.mark.parametrize("bot", [qb, lc])
def test_human_wymaga_intencji(bot):
    # istniejace True
    assert bot._czy_prosi_o_czlowieka("chcę konsultanta") is True
    assert bot._czy_prosi_o_czlowieka("Chcę rozmawiać z konsultantem") is True
    assert bot._czy_prosi_o_czlowieka("no dawaj tego człowieka") is True
    assert bot._czy_prosi_o_czlowieka("tak, proszę przekazać konsultantowi do wyceny") is True
    # aktywne prosby wczesniej gubione (false-negative RX-04)
    assert bot._czy_prosi_o_czlowieka("przekaż mnie do konsultanta") is True
    # callback jako intencja
    assert bot._czy_prosi_o_czlowieka("oddzwońcie do mnie proszę") is True
    # false-positive: bierna/rzeczowa wzmianka bez intencji
    assert bot._czy_prosi_o_czlowieka("potwierdzenie od konsultanta") is False
    assert bot._czy_prosi_o_czlowieka("materiał polecony od doradcy") is False
    assert bot._czy_prosi_o_czlowieka("jestem pracownikiem biura projektowego, potrzebuję wyceny 6 blatów") is False
    assert bot._czy_prosi_o_czlowieka("nasz pracownik odbierze blat osobiście") is False
    assert bot._czy_prosi_o_czlowieka("mój mąż zadzwoni do was jutro") is False


# ---------------- Pytanie o bota: luki (RX-08) ----------------

@pytest.mark.parametrize("bot", [qb, lc])
def test_pytanie_o_bota_luki(bot):
    assert bot._PYTANIE_O_BOTA_RE.search("jesteś człowiekiem?")
    assert bot._PYTANIE_O_BOTA_RE.search("rozmawiam z botem czy z człowiekiem?")
    assert bot._PYTANIE_O_BOTA_RE.search("gadam z człowiekiem czy z botem?")


# ---------------- Potwierdzenie: zakotwiczone + krotkie (RX-03, RX-12) ----------------

@pytest.mark.parametrize("bot", [qb, lc])
def test_potwierdzenie_zawezone(bot):
    # dluga wypowiedz z jednym slowem-kluczem NIE jest potwierdzeniem
    assert bot._jest_potwierdzenie("ok, a co z transportem") is False
    assert bot._jest_potwierdzenie("tak myślę, że jeszcze się zastanowię") is False
    assert bot._jest_potwierdzenie("super, a ile potrwa realizacja") is False
    # krotkie jednoznaczne potwierdzenia (w tym nowe frazy RX-12)
    assert bot._jest_potwierdzenie("tak, zgadza się") is True
    assert bot._jest_potwierdzenie("dobrze") is True
    assert bot._jest_potwierdzenie("jasne") is True
    assert bot._jest_potwierdzenie("w porządku") is True
    # pytanie / negacja / korekta nadal False
    assert bot._jest_potwierdzenie("tak, ale zaokrąglicie krawędzie?") is False
    assert bot._jest_potwierdzenie("nie, źle, zmień grubość") is False


# ---------------- _NEG_RE: odmiany 'zmienic' (RX-02) ----------------

@pytest.mark.parametrize("bot", [qb, lc])
def test_neg_lapie_odmiany_zmienic(bot):
    assert bot._jest_potwierdzenie("tak, ale zmieńcie olej na lakier") is False
    assert bot._jest_potwierdzenie("dobra, zmienić na dąb") is False
    assert bot._jest_potwierdzenie("ok, ale jednak buk") is False


# ---------------- Odmowa kontaktu/kodu: intencja, nie gole slowo (RX-05, LS-03, SB-03, MS-01) ----------------

def test_odmowa_zawezona():
    # FP gasla lejek — teraz NIE odmowa
    assert qb._czy_odmowa("Nie jestem pewien, a czy możecie zrobić grubość 5 cm?") is False
    assert qb._czy_odmowa("a nie da się taniej z tą wysyłką?") is False
    assert qb._czy_odmowa("a czy blat może być bez sęków?") is False
    assert qb._czy_odmowa("nie wiem, czy dobrze podałem wymiary") is False
    assert qb._czy_odmowa("zrobię jeszcze pomiary i wrócę") is False
    # jednoznaczna odmowa — TAK
    assert qb._czy_odmowa("nie, dziękuję") is True
    assert qb._czy_odmowa("nie chcę podawać maila") is True
    assert qb._czy_odmowa("wolę nie podawać") is True
    assert qb._czy_odmowa("pomińmy to") is True


# ---------------- Kod pocztowy: '02 495'/'02495' ok, zakresy odrzucone (RX-11, SB-07, MS-06) ----------------

def test_kod_elastyczny_i_bez_zakresow():
    assert qb._wyciagnij_kod("mój kod to 36-068 proszę") == "36-068"
    assert qb._wyciagnij_kod("02 495") == "02-495"
    assert qb._wyciagnij_kod("kod 02495") == "02-495"
    # zakresy wymiarow NIE sa kodem
    assert qb._wyciagnij_kod("a jakie robicie grubości w zakresie 40-120 cm?") is None
    assert qb._wyciagnij_kod("czy szerokość parapetu może być między 40-120 cm?") is None
    assert qb._wyciagnij_kod("Kraków, ul. Długa") is None


# ---------------- Telefon: realny numer PL, nie wymiary/NIP/zamowienie (RX-06, MS-10, SB-02) ----------------

def test_tel_tylko_realny_numer():
    assert qb._wyciagnij_kontakt("tel 501 234 567")[1] != ""      # realny numer
    assert qb._wyciagnij_kontakt("+48 501 234 567")[1] != ""      # z prefiksem
    assert qb._wyciagnij_kontakt("zamówienie 123456")[1] == ""    # za krotki
    assert qb._wyciagnij_kontakt("a właściwie wymiary to 2000 450 38 mm")[1] == ""  # wymiary
    assert qb._wyciagnij_kontakt("poproszę fakturę na NIP 521-345-67-89")[1] == ""  # NIP
    assert qb._wyciagnij_kontakt("podepnij do zamówienia 250601234")[1] == ""       # nr zamowienia


# ---------------- E-mail: nie firmowa domena woodpower.pl (RX-07) ----------------

def test_email_odrzuca_wlasna_domene():
    assert qb._wyciagnij_kontakt("mail: a@b.pl")[0] == "a@b.pl"
    assert qb._wyciagnij_kontakt("a piszę na reklamacje@woodpower.pl?")[0] == ""
    assert qb._wyciagnij_kontakt("kontakt@woodpower.pl")[0] == ""


# ---------------- Kolejnosc bramek: reklamacja+czlowiek -> handoff od razu (SB-05) ----------------

def _patch(monkeypatch, replies, chat_json='{"odpowiedz":"ok","handoff":false,"pozycje":[],"wspolne":{}}'):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: chat_json)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def _reset(conv_id):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.commit(); c.close()


def test_reklamacja_plus_czlowiek_handoff_od_razu(monkeypatch):
    replies = []
    _patch(monkeypatch, replies)
    _reset(801)
    qb.run_quote_turn(801, 12, "m1", "mam reklamację, uszkodzony blat, proszę o kontakt z konsultantem")
    assert "__HANDOFF__" in replies, "reklamacja + prosba o czlowieka -> handoff od razu"
    assert not any("reklamacje@woodpower.pl" in t for t in replies), "bez canned reklamacji"


def test_odmowa_w_awaiting_contact_nie_polyka_pytania(monkeypatch):
    """MS-01/LS-03: pytanie z gołym 'nie' w awaiting_contact NIE jest odmowa — idzie do LLM."""
    replies = []
    _patch(monkeypatch, replies, chat_json='{"odpowiedz":"Tak, grubość 5 cm jest możliwa.","handoff":false,"pozycje":[],"wspolne":{}}')
    _reset(802)
    c = db_mod.db()
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced, awaiting_contact) VALUES(?,1,1,1)", (802,))
    c.commit(); c.close()
    qb.run_quote_turn(802, 12, "m1", "Nie jestem pewien, a czy możecie zrobić grubość 5 cm?")
    assert any("5 cm" in t for t in replies), "pytanie klienta powinno trafic do LLM, nie canned odmowa"
    c = db_mod.db()
    row = c.execute("SELECT awaiting_contact FROM quote_state WHERE conv_id=802").fetchone()
    c.close()
    assert row["awaiting_contact"] == 1, "flaga kontaktu NIE moze zgasnac przez gole 'nie'"


def test_limit_tur_po_bramkach_awaiting(monkeypatch):
    """MS-11: e-mail podany w ostatniej turze (limit) jest skonsumowany zamiast przepasc w handoffie."""
    replies = []
    _patch(monkeypatch, replies)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": [{"id": 7, "full_path": "Olej"}]})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "client": {"id": 5}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda poz, o, cid, notes="": {"ok": True, "quote_number": "W/9", "public_url": "https://crm/q/z"})
    _reset(803)
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
                         "gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "ilosc": "1",
                         "wykonczenie": "olejowane", "finishing_id": 7}], "wspolne": {}}
    c = db_mod.db()
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (803, json.dumps(dane)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced, awaiting_contact) VALUES(?,?,1,1)",
              (803, qb.BOT_QUOTE_MAX_TURNS))   # licznik na limicie
    c.commit(); c.close()
    qb.run_quote_turn(803, 12, "m1", "jan@kowalski.pl")
    assert any("crm/q/z" in t for t in replies), "e-mail w turze limitu ma zapisac wycene, nie handoff"
    assert "__HANDOFF__" not in replies
