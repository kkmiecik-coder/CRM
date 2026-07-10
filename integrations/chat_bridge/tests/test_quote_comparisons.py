# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 5: porownania bez slepych zaulkow — zamiast pustej odpowiedzi -> RuntimeError
# -> 3 retry -> handoff (MS-02) albo cichego konca tury (SB-04), bot daje deterministyczna odpowiedz.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qcmp.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _patch(monkeypatch, replies, chat_json):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "a ile w jesionie?"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (chat_json, {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def _reset(conv_id, dane, **flags):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    if dane is not None:
        c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(dane)))
    cols = ["bot_turns"] + list(flags.keys())
    vals = [1] + [flags[k] for k in flags]
    c.execute("INSERT INTO quote_state(conv_id, %s) VALUES(%s)" % (",".join(cols), ",".join("?" * (len(cols) + 1))),
              tuple([conv_id] + vals))
    c.commit(); c.close()


_POROWNANIE = '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}'


def test_porownanie_przed_pierwsza_cena_nie_handoff(monkeypatch):
    """MS-02: klient pyta o porownanie w trakcie zbierania (brak ceny) — LLM daje puste 'odpowiedz'
    + 'porownania'. Zamiast RuntimeError->handoff bot deterministycznie odpowiada."""
    replies = []
    _patch(monkeypatch, replies, _POROWNANIE)
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "gatunek": "dąb"}], "wspolne": {}}  # niekompletne, brak ceny
    _reset(1001, dane)
    qb.run_quote_turn(1001, 12, "m1", "a ile w jesionie?")
    assert replies, "bot musi cos odpowiedziec (nie cisza/handoff)"
    assert "__HANDOFF__" not in replies
    assert any("wycen" in t.lower() for t in replies), "deterministyczna info o porownaniu po wycenie"


_KOMPLET_CMP = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                             "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                             "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def test_potwierdzenie_z_bledna_porownania_liczy_cene(monkeypatch):
    """REGRESJA (prod 08.07): na 'tak' model bezpodstawnie wrzucił 'porownania' -> bot uciekał w
    komunikat o porównaniu zamiast policzyć cenę. Teraz potwierdzenie wygrywa, cena leci."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}')
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda poz, opts: {"ok": True, "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    _reset(1005, _KOMPLET_CMP, awaiting_confirm=1)   # komplet, przed ceną (NIE priced)
    qb.run_quote_turn(1005, 12, "m1", "tak, wszystko się zgadza")
    tekst = " ".join(replies)
    assert "1230" in tekst or "1 230" in tekst, "na 'tak' bot MUSI policzyć cenę"
    assert "dokończmy dane" not in tekst and "policzę zaraz po" not in tekst, "żadnej ucieczki w porównanie"


def test_po_zebraniu_danych_bledna_porownania_daje_podsumowanie(monkeypatch):
    """REGRESJA: po skompletowaniu danych model wrzuca 'porownania' -> bot ma wysłać PODSUMOWANIE,
    nie komunikat 'najpierw dokończmy dane' (dane są komplet)."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"Pokażę porównanie z innymi wariantami.","handoff":false,'
           '"pozycje":[{"id":"1","produkt":"blat","dlugosc":"200","szerokosc":"60","grubosc":"4",'
           '"gatunek":"dąb","technologia":"lita","klasa":"A/B","ilosc":"1","wykonczenie":"surowe"}],'
           '"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}')
    _reset(1006, {"pozycje": [], "wspolne": {}})   # pusto -> ta tura kompletuje dane
    qb.run_quote_turn(1006, 12, "m1", "blat dąb lity A/B surowy 200x60x4, 1 szt")
    assert any("Podsumowuję dane" in t for t in replies), "komplet -> podsumowanie, nie ucieczka w porównanie"
    assert not any("dokończmy dane" in t for t in replies)


def test_porownanie_po_cenie_ale_druga_pozycja_niekompletna(monkeypatch):
    """SB-04: cena wyslana (priced), ale inna pozycja niekompletna -> _czy_porownanie False.
    Bot NIE moze zamilknac — dopytuje o braki zamiast cichego return."""
    replies = []
    _patch(monkeypatch, replies, _POROWNANIE)
    dane = {"pozycje": [
        {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
         "gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "ilosc": "1", "wykonczenie": "surowe"},
        {"id": "2", "produkt": "parapet"}], "wspolne": {}}  # pozycja 2 niekompletna
    _reset(1002, dane, priced=1)
    qb.run_quote_turn(1002, 12, "m1", "a ile ten blat w jesionie?")
    assert replies, "bot nie moze zamilknac"
    assert "__HANDOFF__" not in replies


# --- Task 8: wycena wariantowa (wielu gatunkow naraz) ---

def test_gatunki_z_listy_normalizuje_dedupikuje_pomija_nieznane():
    assert qb._gatunki_z_listy(["dąb", "Jesion", "dab", "buk", "orzech", ""]) == ["Dąb", "Jesion", "Buk"]
    assert qb._gatunki_z_listy(None) == []
    assert qb._gatunki_z_listy([]) == []


_POZ_WARIANT = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90", "grubosc": "4",
                "gatunek": "Dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
                "wykonczenie": "surowe", "gatunki_do_porownania": ["Dąb", "Jesion"]}


def test_czy_wycena_wariantowa_wymaga_2plus_gatunkow_kompletu_i_braku_ceny():
    assert qb._czy_wycena_wariantowa(1101, _POZ_WARIANT) is True
    # Tylko 1 gatunek do porownania -> nie kwalifikuje sie.
    jeden = dict(_POZ_WARIANT, gatunki_do_porownania=["Dąb"])
    assert qb._czy_wycena_wariantowa(1101, jeden) is False
    # Niekompletna pozycja (brak grubosci) -> nie kwalifikuje sie.
    niekomplet = dict(_POZ_WARIANT); niekomplet.pop("grubosc")
    assert qb._czy_wycena_wariantowa(1101, niekomplet) is False
    # Cena juz padla w tej rozmowie -> to zwykle porownanie (_obsluz_porownania), nie tryb wariantowy.
    qb._set_priced(1102, True)
    assert qb._czy_wycena_wariantowa(1102, _POZ_WARIANT) is False


def _fake_calculate_2gatunki(n_pozycji=1):
    def fake_calculate(pozycje, options):
        return {"ok": True, "totals": {"total_brutto": 999.0, "total_netto": 812.0},
                "products": [{"variants": [
                    {"variant_code": "dab-lity-ab", "available": True, "total_netto": 800.0, "total_brutto": 984.0},
                    {"variant_code": "jes-lity-ab", "available": True, "total_netto": 900.0, "total_brutto": 1107.0},
                    {"variant_code": "buk-lity-ab", "available": True, "total_netto": 700.0, "total_brutto": 861.0},
                ]} for _ in range(n_pozycji)]}
    return fake_calculate


def test_wycena_wariantowa_pokazuje_tabele_bez_zapisu(monkeypatch):
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", _fake_calculate_2gatunki())
    find_or_create_called = {"n": 0}
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda *a, **k: find_or_create_called.update(n=find_or_create_called["n"] + 1))

    def fake_chat(messages, **kw):
        out = {"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "", "send_image": "",
               "pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90",
                           "grubosc": "4", "gatunek": "dąb", "technologia": "lity", "klasa": "A/B",
                           "ilosc": "1", "wykonczenie": "surowe",
                           "gatunki_do_porownania": ["dąb", "jesion"]}],
               "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)
    _reset(1150, {"pozycje": [], "wspolne": {}})

    qb.run_quote_turn(1150, 5, "m1", "poproszę wycenę blatu 200x90 dąb i jesion, lite, A/B, surowe, 1 szt.")

    assert len(replies) == 1, "tabela + pytanie o wybor MAJA byc jedna wiadomoscia (bundling, LS-12)"
    tekst = replies[0]
    assert "Dąb" in tekst and qb._fmt_pln(984.0) in tekst
    assert "Jesion" in tekst and qb._fmt_pln(1107.0) in tekst
    assert find_or_create_called["n"] == 0, "LS: bez zapisu w CRM"
    assert qb._priced(1150) is False
    # Stan "oczekuje wyboru" jest WYLICZANY z danych (nie osobna flaga) — pozycja nadal ma
    # nierozstrzygniete gatunki_do_porownania, dopoki LLM ich nie rozstrzygnie.
    assert qb._pozycje_z_oczekujacym_wyborem(qb._load_dane(1150))


def test_gatunki_w_tekscie_wykrywa_enumeracje_po_granicy_slowa():
    """Deterministyczny detektor gatunkow w tresci: lapie odmiane (dębie/jesionie), pomija
    falszywe podciagi po granicy slowa nie jest idealna, ale wymaga 2+ do trybu wariantowego."""
    assert qb._gatunki_w_tekscie("wycenę blatu w dębie i jesionie") == ["Dąb", "Jesion"]
    assert qb._gatunki_w_tekscie("dąb, jesion lub buk") == ["Dąb", "Jesion", "Buk"]
    assert qb._gatunki_w_tekscie("tylko dąb") == ["Dąb"]
    assert qb._gatunki_w_tekscie("bez gatunku") == []


def test_wycena_wariantowa_odpala_gdy_LLM_nie_ustawil_pola(monkeypatch):
    """Regresja E2E 2026-07-09 (V01/V04): przy „w dębie i jesionie” model nano czesto NIE
    ustawia gatunki_do_porownania — traktuje jak pojedynczy dąb i idzie w podsumowanie.
    Deterministyczny detektor gatunkow w tresci MA dokryc pole i uruchomic tabele wariantowa."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", _fake_calculate_2gatunki())
    find_or_create_called = {"n": 0}
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda *a, **k: find_or_create_called.update(n=find_or_create_called["n"] + 1))

    def fake_chat(messages, **kw):
        # LLM (jak nano w E2E) NIE ustawia gatunki_do_porownania — kompletny pojedynczy dąb.
        out = {"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "", "send_image": "",
               "pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90",
                           "grubosc": "4", "gatunek": "dąb", "technologia": "lity", "klasa": "A/B",
                           "ilosc": "1", "wykonczenie": "surowe", "gatunki_do_porownania": []}],
               "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)
    _reset(1155, {"pozycje": [], "wspolne": {}})

    qb.run_quote_turn(1155, 5, "m1", "poproszę wycenę blatu 200x90x4 w dębie i jesionie, lity, A/B, surowy, 1 szt")

    tekst = " ".join(replies)
    assert "Jesion" in tekst and qb._fmt_pln(1107.0) in tekst, "detektor MA uruchomic tabele wariantowa"
    assert "podsumowuję dane" not in tekst.lower(), "NIE podsumowanie pojedynczego gatunku"
    assert find_or_create_called["n"] == 0, "bez zapisu w CRM"
    assert qb._priced(1155) is False


def test_czy_wariantowa_liczy_kotwice_plus_gatunki_do_porownania():
    """Regresja E2E V05: LLM czesto wpisuje w gatunki_do_porownania tylko DRUGI gatunek,
    kotwice zostawiajac w 'gatunek' (blat: gatunek=dąb, gdp=['jesion']). Zbior do porownania
    = gatunek ∪ gdp — wtedy len>=2 i tryb wariantowy odpala."""
    poz = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90", "grubosc": "4",
           "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
           "wykonczenie": "surowe", "gatunki_do_porownania": ["jesion"]}
    assert qb._gatunki_pozycji(poz) == ["Dąb", "Jesion"]
    assert qb._czy_wycena_wariantowa(9401, poz) is True
    # pojedynczy gatunek bez gdp -> NIE wariantowa
    poz1 = dict(poz, gatunki_do_porownania=[])
    assert qb._gatunki_pozycji(poz1) == ["Dąb"]
    assert qb._czy_wycena_wariantowa(9402, poz1) is False


def test_wariantowa_ma_pierwszenstwo_przed_podsumowaniem_gdy_handoff_komplet(monkeypatch):
    """Regresja E2E V01: przy komplecie danych LLM czesto zglasza handoff=true (powod „komplet”)
    — straznik robil PODSUMOWANIE pojedynczego gatunku, przykrywajac tabele wariantowa. Tabela
    ma miec pierwszenstwo przed podsumowaniem kompletnosci (ale wciaz PO genuine-handoffie)."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", _fake_calculate_2gatunki())

    def fake_chat(messages, **kw):
        # komplet + handoff=true (jak nano dla gotowej pozycji) + gatunki_do_porownania ustawione
        out = {"odpowiedz": "", "handoff": True, "potwierdzono": False, "powod": "komplet danych do wyceny",
               "send_image": "", "pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200",
                   "szerokosc": "90", "grubosc": "4", "gatunek": "dąb", "technologia": "lity",
                   "klasa": "A/B", "ilosc": "1", "wykonczenie": "surowe",
                   "gatunki_do_porownania": ["dąb", "jesion"]}], "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)
    _reset(1158, {"pozycje": [], "wspolne": {}})
    qb.run_quote_turn(1158, 5, "m1", "wycena blatu 200x90x4 w dębie i jesionie, lity A/B surowy 1 szt")
    tekst = " ".join(replies)
    assert "Jesion" in tekst and qb._fmt_pln(1107.0) in tekst, "tabela wariantowa MA odpalic mimo handoff=komplet"
    assert "podsumowuję dane" not in tekst.lower(), "NIE podsumowanie pojedynczego gatunku"


def test_detektor_nie_odpala_gdy_pozycja_niekompletna(monkeypatch):
    """Detektor NIE moze uruchamiac trybu wariantowego dla niekompletnej pozycji (np. pytanie
    techniczne „różnica między dębem a jesionem” — brak wymiarow) — tam ma isc normalna sciezka."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    calc_called = {"n": 0}
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: calc_called.update(n=calc_called["n"] + 1) or {"ok": True, "products": []})
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (
        '{"odpowiedz":"Dąb jest twardszy, jesion bardziej sprężysty.","handoff":false,'
        '"potwierdzono":false,"powod":"","send_image":"","pozycje":[],"wspolne":{},"porownania":[]}',
        {"error_class": None}))
    _reset(1156, {"pozycje": [], "wspolne": {}})
    qb.run_quote_turn(1156, 5, "m1", "jaka jest różnica między dębem a jesionem?")
    assert calc_called["n"] == 0, "pytanie techniczne bez pozycji NIE uruchamia wyceny wariantowej"
    assert replies, "bot ma odpowiedziec merytorycznie"


def test_wycena_wariantowa_dwie_pozycje_naraz_obie_pokazane(monkeypatch):
    """Regresja code review Task 8: gdy DWIE pozycje kwalifikuja sie do wyceny wariantowej w
    jednej turze, OBIE maja dostac pokazana tabele (bundlowana jedna wiadomoscia) — wczesniejsza
    wersja pokazywala tylko pierwsza i cicho gubila druga (a pozniejszy wybor gatunku myliłby je)."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", _fake_calculate_2gatunki(n_pozycji=2))

    def fake_chat(messages, **kw):
        out = {"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "", "send_image": "",
               "pozycje": [
                   {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90", "grubosc": "4",
                    "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
                    "wykonczenie": "surowe", "gatunki_do_porownania": ["dąb", "jesion"]},
                   {"id": "2", "produkt": "parapet", "dlugosc": "100", "szerokosc": "30", "grubosc": "3",
                    "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
                    "wykonczenie": "surowe", "gatunki_do_porownania": ["dąb", "buk"]},
               ], "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)
    _reset(1151, {"pozycje": [], "wspolne": {}})

    qb.run_quote_turn(1151, 5, "m1",
                      "blat 200x90 dąb/jesion i parapet 100x30 dąb/buk, oba lite A/B surowe, 1 szt.")

    assert len(replies) == 1
    tekst = replies[0]
    assert "Jesion" in tekst, "pierwsza pozycja (blat) MUSI dostac swoja tabele"
    assert "Buk" in tekst, "druga pozycja (parapet) MUSI TEZ dostac swoja tabele, nie zgubiona"
    dane = qb._load_dane(1151)
    assert qb._gatunki_z_listy(dane["pozycje"][0]["gatunki_do_porownania"]) == ["Dąb", "Jesion"]
    assert qb._gatunki_z_listy(dane["pozycje"][1]["gatunki_do_porownania"]) == ["Dąb", "Buk"]


def test_wybor_gatunku_llm_czysci_gatunki_do_porownania(monkeypatch):
    """Wybor gatunku po tabeli: LLM (nie regex na surowym tekscie — kruchy na odmiane/falszywe
    trafienia, patrz code review) rozstrzyga ktora pozycje klient wybral i ustawia jej 'gatunek'
    + czysci 'gatunki_do_porownania'. _merge_dane MUSI to nadpisanie zastosowac (regresja: pusta
    lista od LLM wczesniej NIE kasowala przez ogolny _merge_pola)."""
    qb._zapisz_dane(1160, {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200",
                                        "szerokosc": "90", "grubosc": "4", "gatunek": "Dąb",
                                        "technologia": "lity", "klasa": "A/B", "ilosc": "1",
                                        "wykonczenie": "surowe", "gatunki_do_porownania": ["Dąb", "Jesion"]}],
                          "wspolne": {}})
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})

    def fake_chat(messages, **kw):
        # System prompt MUSI zawierac instrukcje wyboru wariantu, skoro pozycja ma oczekujacy wybor.
        assert any("gatunki_do_porownania" in m["content"] for m in messages if m["role"] == "system")
        out = {"odpowiedz": "Super, zapisuję jesion.", "handoff": False, "potwierdzono": False,
               "powod": "", "send_image": "",
               "pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90",
                           "grubosc": "4", "gatunek": "Jesion", "technologia": "lity", "klasa": "A/B",
                           "ilosc": "1", "wykonczenie": "surowe", "gatunki_do_porownania": []}],
               "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)

    qb.run_quote_turn(1160, 5, "m1", "poproszę w jesionie")

    dane = qb._load_dane(1160)
    assert dane["pozycje"][0]["gatunek"] == "Jesion"
    assert dane["pozycje"][0]["gatunki_do_porownania"] == []
    assert not qb._pozycje_z_oczekujacym_wyborem(dane)


def test_merge_dane_gatunki_do_porownania_nadpisuje_takze_pusta_liste():
    """Regresja code review Task 8: 'gatunki_do_porownania' to jednorazowa decyzja tury (jak
    'edges'), NIE zwykle akumulowane pole tekstowe — pusta lista od LLM (rozstrzygniecie) MUSI
    kasowac stara wartosc, inaczej pozycja utyka w trybie wariantowym na zawsze."""
    qb._zapisz_dane(1170, {"pozycje": [{"id": "1", "produkt": "blat", "gatunek": "Dąb",
                                        "gatunki_do_porownania": ["Dąb", "Jesion"]}], "wspolne": {}})
    out = {"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "", "send_image": "",
           "pozycje": [{"id": "1", "gatunek": "Jesion", "gatunki_do_porownania": []}],
           "wspolne": {}, "porownania": []}
    dane = qb._merge_dane(1170, out)
    assert dane["pozycje"][0]["gatunki_do_porownania"] == []
    assert dane["pozycje"][0]["gatunek"] == "Jesion"


def test_wycena_wariantowa_nie_przykrywa_schody_nietypowe(monkeypatch):
    """Regresja code review Task 8 (angle B): straznik schodow nieprostokatnych (kalkulator
    liczy tylko deski) MA pierwszenstwo przed tabela cen wariantowej — inaczej klient dostalby
    pewna wycene ksztaltu, ktorego kalkulator nie umie policzyc, zamiast trafic do konsultanta."""
    handed = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: handed.append(c) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    calc_called = {"n": 0}
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: calc_called.update(n=calc_called["n"] + 1) or _fake_calculate_2gatunki()(p, o))

    def fake_chat(messages, **kw):
        out = {"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "", "send_image": "",
               "pozycje": [{"id": "1", "produkt": "schody", "dlugosc": "30", "szerokosc": "90",
                           "grubosc": "4", "gatunek": "dąb", "technologia": "lity", "klasa": "A/B",
                           "ilosc": "15", "wykonczenie": "surowe",
                           "gatunki_do_porownania": ["dąb", "jesion"]}],
               "wspolne": {}, "porownania": []}
        return json.dumps(out), {"error_class": None}
    monkeypatch.setattr(qb, "chat", fake_chat)
    _reset(1180, {"pozycje": [], "wspolne": {}})

    qb.run_quote_turn(1180, 5, "m1", "schody kręcone, poproszę wycenę w dębie i jesionie")

    assert handed == [1180], "schody nietypowe MUSZA trafic do konsultanta, nie dostac tabeli cen"
    assert calc_called["n"] == 0, "przy schodach nietypowych nie liczymy nawet wyceny wariantowej"


def test_niejednoznaczna_odpowiedz_nie_przemyca_ceny_bez_wyboru_gatunku(monkeypatch):
    """Regresja code review Task 8 (weryfikacja redesignu): _WARIANT_WYBOR_INSTR to TYLKO miekka
    instrukcja dla LLM — gdy model nie rozstrzygnie wyboru na niejednoznacznej wiadomosci (i po
    prostu echuje pozycje bez zmian, zgodnie z instrukcja "zostaw bez zmian"), tabela jest juz
    zdedupowana (nie pokazemy jej drugi raz), wiec bez twardej bramki w kodzie tura przeszlaby
    do podsumowania/ceny z DOWOLNYM gatunkiem-kotwica, ktorego klient nigdy nie wybral. Test
    dowodzi, ze _wyslij_podsumowanie/_wyslij_cene_i_kontakt maja WLASNY (nie tylko promptowy)
    gate: dopoki gatunki_do_porownania nie jest rozstrzygniete, NIE MA podsumowania ani ceny."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", _fake_calculate_2gatunki())
    find_or_create_called = {"n": 0}
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda *a, **k: find_or_create_called.update(n=find_or_create_called["n"] + 1))

    _POZ_1 = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "90", "grubosc": "4",
             "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
             "wykonczenie": "surowe", "gatunki_do_porownania": ["dąb", "jesion"]}

    # Tura 1: tabela cen pokazana, gatunki_do_porownania wciaz NIErozstrzygniete (anchor='dąb').
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (
        json.dumps({"odpowiedz": "", "handoff": False, "potwierdzono": False, "powod": "",
                   "send_image": "", "pozycje": [_POZ_1], "wspolne": {}, "porownania": []}),
        {"error_class": None}))
    _reset(1190, {"pozycje": [], "wspolne": {}})
    qb.run_quote_turn(1190, 5, "m1", "poproszę wycenę blatu 200x90 dąb i jesion, lite, A/B, surowe, 1 szt.")
    assert len(replies) == 1
    replies.clear()

    # Tura 2: klient pyta o cos NIEZWIAZANEGO; LLM (zgodnie z wlasna instrukcja "zostaw bez
    # zmian") echuje pozycje BEZ rozstrzygniecia gatunku — gatunki_do_porownania nadal 2 wpisy.
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (
        json.dumps({"odpowiedz": "Realizacja trwa zwykle 10-14 dni roboczych.", "handoff": False,
                   "potwierdzono": False, "powod": "", "send_image": "",
                   "pozycje": [_POZ_1], "wspolne": {}, "porownania": []}),
        {"error_class": None}))
    qb.run_quote_turn(1190, 5, "m2", "a jak długo trwa realizacja?")

    assert qb._priced(1190) is False, "cena NIE MOZE paść bez rozstrzygnietego wyboru gatunku"
    assert find_or_create_called["n"] == 0, "zaden lead/CRM zapis bez rozstrzygnietego wyboru gatunku"
    assert qb._pozycje_z_oczekujacym_wyborem(qb._load_dane(1190)), "wybor nadal nierozstrzygniety"
    assert any("gatunk" in r.lower() for r in replies), "bot ma przypomniec o wyborze, nie milczec"
