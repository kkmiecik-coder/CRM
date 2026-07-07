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

def test_cena_msg_per_pozycja_i_calosc():
    dane = {"pozycje": [_poz()], "wspolne": {}}
    wynik = {"products": [{"index": 1,
                           "variants": [{"variant_code": "dab-micro-ab", "available": True,
                                         "total_netto": 480.48, "total_brutto": 590.99}],
                           "finishing": {"netto": 0, "brutto": 0},
                           "edges": {"netto": 0, "brutto": 0}}],
             "totals": {"total_netto": 480.48, "total_brutto": 590.99}}
    msg = qb._cena_msg(dane, wynik)
    assert "Wstępna wycena" not in msg
    assert msg.splitlines()[0].startswith("**Blat")   # nazwa pogrubiona (markdown)
    assert "140×80×3 cm" in msg
    assert "590,99 zł (480,48 zł netto)" in msg     # cena per pozycja
    assert "**Cena za całość:**" in msg              # nagłówek pogrubiony


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
    assert any("zaglądają" in r or "wcześniejsze wyceny" in r for r in replies)


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


# --- Runda 3: krawedzie (tryb advanced) ---

def test_normalize_edges_rozwija_wszystkie():
    out = qb.crm_calc.normalize_edges([{"litera": "WSZYSTKIE", "typ": "round"}])
    assert [e["litera"] for e in out] == ["A", "B", "C", "D"]
    assert all(e["typ"] == "round" for e in out)


def test_normalize_edges_waliduje_i_odrzuca():
    out = qb.crm_calc.normalize_edges([
        {"litera": "A", "typ": "zaokrąglenie"},   # alias PL -> round, promien domyslny 5
        {"litera": "X", "typ": "round"},           # zla litera -> odrzucona
        {"litera": "B", "typ": "cokolwiek"},       # zly typ -> odrzucony
    ])
    assert out == [{"litera": "A", "typ": "round", "r_value": 5, "angle_value": None}]


def test_normalize_edges_promienie_i_kat():
    out = qb.crm_calc.normalize_edges([
        {"litera": "C", "typ": "round", "r": 3}, {"litera": "E", "typ": "round", "r": "R5"},
        {"litera": "F", "typ": "chamfer", "kat": 45}])
    assert {"litera": "C", "typ": "round", "r_value": 3, "angle_value": None} in out
    assert {"litera": "E", "typ": "round", "r_value": 5, "angle_value": None} in out
    assert {"litera": "F", "typ": "chamfer", "r_value": None, "angle_value": 45} in out


def test_build_products_dodaje_edges_advanced():
    poz = _poz(edges=[{"litera": "A", "typ": "round", "r": 3},
                      {"litera": "B", "typ": "chamfer", "kat": 45}])
    products, braki = qb.crm_calc.build_products([poz], {"finishing_options": []})
    assert braki == []
    p = products[0]
    assert p["edges_mode"] == "advanced"
    assert {"letter": "A", "type": "round", "r_value": 3, "angle_value": None} in p["edges"]
    assert {"letter": "B", "type": "chamfer", "r_value": None, "angle_value": 45} in p["edges"]


def test_podsumowanie_grupuje_krawedzie_po_promieniu():
    edges = qb.crm_calc.normalize_edges([
        {"litera": "C", "typ": "round", "r": 3}, {"litera": "A", "typ": "round", "r": 3},
        {"litera": "D", "typ": "round", "r": 3}, {"litera": "E", "typ": "round", "r": 5}])
    dane = {"pozycje": [_poz(edges=edges)], "wspolne": {}}
    msg = qb._podsumowanie_msg(dane)
    assert "Krawędzie: R3 (C, A, D); R5 (E)" in msg


def test_merge_zapamietuje_edges():
    qb._zapisz_dane(720, {"pozycje": [_poz(id="1")], "wspolne": {}})
    out = {"pozycje": [{"id": "1", "edges": [{"litera": "WSZYSTKIE", "typ": "round"}]}], "wspolne": {}}
    dane = qb._merge_dane(720, out)
    ed = dane["pozycje"][0].get("edges")
    assert [e["litera"] for e in ed] == ["A", "B", "C", "D"]


def test_cena_pozycji_rozbicie_na_skladowe():
    poz = _poz()
    prod = {"variants": [{"variant_code": "dab-micro-ab", "available": True,
                          "total_netto": 100.0, "total_brutto": 123.0}],
            "finishing": {"netto": 10.0, "brutto": 12.3}, "edges": {"netto": 5.0, "brutto": 6.15}}
    b = qb._cena_pozycji(poz, prod)
    assert b["material"] == (100.0, 123.0)
    assert b["wykonczenie"] == (10.0, 12.3)
    assert b["krawedzie"] == (5.0, 6.15)
    assert round(b["razem"][0], 2) == 115.0 and round(b["razem"][1], 2) == 141.45


def test_cena_msg_pokazuje_skladowe_gdy_niezerowe():
    dane = {"pozycje": [_poz()], "wspolne": {}}
    wynik = {"products": [{"index": 1,
                           "variants": [{"variant_code": "dab-micro-ab", "available": True,
                                         "total_netto": 100.0, "total_brutto": 123.0}],
                           "finishing": {"netto": 10.0, "brutto": 12.3},
                           "edges": {"netto": 5.0, "brutto": 6.15}}],
             "totals": {"total_netto": 115.0, "total_brutto": 141.45}}
    msg = qb._cena_msg(dane, wynik)
    assert "Produkt surowy: 123,00 zł" in msg
    assert "Wykończenie: 12,30 zł" in msg
    assert "Krawędzie: 6,15 zł" in msg
    assert "Razem: 141,45 zł" in msg


def test_cena_msg_surowe_bez_krawedzi_tylko_produkt():
    # Surowe bez krawedzi -> jedna skladowa (Produkt surowy), bez linii Wykonczenie/Krawedzie/Razem.
    dane = {"pozycje": [_poz()], "wspolne": {}}
    wynik = {"products": [{"index": 1,
                           "variants": [{"variant_code": "dab-micro-ab", "available": True,
                                         "total_netto": 480.48, "total_brutto": 590.99}],
                           "finishing": {"netto": 0, "brutto": 0}, "edges": {"netto": 0, "brutto": 0}}],
             "totals": {"total_netto": 480.48, "total_brutto": 590.99}}
    msg = qb._cena_msg(dane, wynik)
    assert "Produkt surowy: 590,99 zł" in msg
    assert "Wykończenie" not in msg and "Krawędzie" not in msg and "Razem" not in msg


def test_obrazy_kontekstowe_trigger(monkeypatch):
    sent = []
    # resolve_context zamockowany — BOT_IMAGES_DIR jest globalny w procesie (inne testy go zmieniaja),
    # tu sprawdzamy LOGIKE triggera, nie rozwiazanie pliku.
    monkeypatch.setattr(qb.images, "resolve_context", lambda key: "/fake/%s.jpg" % key)
    monkeypatch.setattr(qb, "cw_agent_reply",
                        lambda c, t, **kw: sent.append(kw.get("image_name") or t) or True)
    qb._obrazy_kontekstowe(730, "czy możemy zaokrąglić krawędzie?",
                           {"pozycje": [_poz(dlugosc="", szerokosc="", grubosc="")], "wspolne": {}})
    assert any("krawedzi" in str(s) for s in sent)   # obraz oznaczenia krawedzi
    assert any("wymiar" in str(s) for s in sent)     # obraz oznaczenia wymiarow


# --- Runda 5: sharp = brak obrobki (nie 'sharp Rnull') + czyszczenie przy zmianie na ostre ---

def test_normalize_edges_odrzuca_sharp():
    out = qb.crm_calc.normalize_edges([{"litera": "A", "typ": "sharp"},
                                       {"litera": "B", "typ": "round", "r": 3}])
    assert out == [{"litera": "B", "typ": "round", "r_value": 3, "angle_value": None}]  # sharp wypada


def test_merge_ostre_czysci_krawedzie():
    # Pozycja ma zaokraglenia -> klient zmienia na ostre (LLM: sharp) -> krawedzie wyczyszczone.
    qb._zapisz_dane(740, {"pozycje": [_poz(id="1", edges=[
        {"litera": "A", "typ": "round", "r_value": 3, "angle_value": None}])], "wspolne": {}})
    out = {"pozycje": [{"id": "1", "edges": [{"litera": "A", "typ": "sharp"},
                                             {"litera": "B", "typ": "sharp"}]}], "wspolne": {}}
    dane = qb._merge_dane(740, out)
    assert dane["pozycje"][0].get("edges") == []          # obrobka usunieta


def test_merge_puste_edges_bez_sharp_nie_kasuje():
    # LLM domyslnie []-> NIE kasuje wczesniejszych krawedzi (klient nie wspomnial o nich).
    qb._zapisz_dane(741, {"pozycje": [_poz(id="1", edges=[
        {"litera": "A", "typ": "round", "r_value": 3, "angle_value": None}])], "wspolne": {}})
    out = {"pozycje": [{"id": "1", "edges": []}], "wspolne": {}}
    dane = qb._merge_dane(741, out)
    assert [e["litera"] for e in dane["pozycje"][0]["edges"]] == ["A"]   # zachowane


# --- Runda 7: porownanie wariantu (bez edycji wyceny) ---

def test_obsluz_porownania_pokazuje_wariant_bez_edycji(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", lambda p, o: {
        "ok": True,
        "products": [{"variants": [
            {"variant_code": "dab-micro-ab", "available": True, "total_netto": 800.0, "total_brutto": 984.0},
            {"variant_code": "jes-micro-ab", "available": True, "total_netto": 700.0, "total_brutto": 861.0}],
            "finishing": {"netto": 0, "brutto": 0}, "edges": {"netto": 0, "brutto": 0}}],
        "totals": {"total_netto": 800.0, "total_brutto": 984.0}})
    ok = qb._obsluz_porownania(900, {"pozycje": [_poz()], "wspolne": {}}, [{"id": "1", "gatunek": "jesion"}])
    assert ok is True
    txt = " ".join(replies)
    assert "861,00 zł" in txt                      # cena wariantu jesion
    assert "jesion" in txt.lower()                 # opis pozycji w jesionie
    assert "nie zmieniam Twojej wyceny" in txt
    assert "984,00 zł" in txt                       # aktualna cena calosci (dab) w uwadze


def test_obsluz_porownania_wariant_niedostepny(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", lambda p, o: {
        "ok": True, "products": [{"variants": [
            {"variant_code": "dab-micro-ab", "available": True, "total_netto": 800.0, "total_brutto": 984.0}],
            "finishing": {"netto": 0, "brutto": 0}, "edges": {"netto": 0, "brutto": 0}}],
        "totals": {"total_brutto": 984.0, "total_netto": 800.0}})
    # jesion B/B nie istnieje -> variant_code None -> niedostepny
    ok = qb._obsluz_porownania(901, {"pozycje": [_poz()], "wspolne": {}},
                               [{"id": "1", "gatunek": "jesion", "klasa": "B/B"}])
    assert ok is True
    assert any("nie jest dostępny" in r for r in replies)
