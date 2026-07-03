# -*- coding: utf-8 -*-
# Test: silnik live-bota — pozycje wyceny, merge per pozycja, straznik kompletnosci,
# podsumowanie do potwierdzenia (awaiting_confirm), wyzwalacze handoffu A/B/C/D,
# walidacja koperty wymiarow, cisza gdy status != pending, sciezka awaryjna.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_liveng.db")
os.environ["BOT_LIVE_CW_AGENT_TOKEN"] = "live-tok-eng"
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
# import przez test_live_worker moze nastapic wczesniej (kolejnosc alfabetyczna) i
# zamrozic bots.livechat na starym config (from-import); reload wiaze token z aktualnego config
lc = importlib.import_module("bots.livechat"); importlib.reload(lc)


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_state")
    c.execute("DELETE FROM live_dane")
    c.commit(); c.close()


def _mock_env(monkeypatch, status="pending", llm_json=None, llm_raw=None):
    """Wspolny zestaw mockow: API Chatwoota + LLM. Zwraca slownik zebranych wywolan."""
    calls = {"reply": [], "note": [], "handoff": [], "chat": []}
    monkeypatch.setattr(lc, "cw_conv_status", lambda cid: status)
    monkeypatch.setattr(lc, "cw_messages", lambda cid, lim: [{"role": "user", "text": "hej"}])
    monkeypatch.setattr(lc, "cw_contact", lambda cid: {"name": "Jan", "identifier": ""})
    monkeypatch.setattr(lc, "retrieve", lambda q: ["wiedza"])
    monkeypatch.setattr(lc, "cw_agent_reply", lambda cid, t: calls["reply"].append(t) or True)
    monkeypatch.setattr(lc, "cw_note", lambda cid, t: calls["note"].append(t))
    monkeypatch.setattr(lc, "cw_bot_handoff",
                        lambda cid, token=None: calls["handoff"].append(token) or True)
    raw = llm_raw if llm_raw is not None else json.dumps(llm_json or {})
    def fake_chat(messages, **kw):
        calls["chat"].append(messages)
        return raw
    monkeypatch.setattr(lc, "chat", fake_chat)
    return calls


def _poz(**pola):
    """Pozycja-blat z kompletem pol wymaganych; nadpisywalna przez kwargs."""
    d = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "80", "grubosc": "3.8",
         "gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "ilosc": "2",
         "wykonczenie": "lakier"}
    d.update(pola)
    return d


def _dane(*pozycje, **wspolne):
    return {"pozycje": list(pozycje), "wspolne": wspolne}


def _odp(odpowiedz="", handoff=False, powod="", pozycje=None, wspolne=None):
    return {"odpowiedz": odpowiedz, "handoff": handoff, "powod": powod,
            "pozycje": pozycje or [], "wspolne": wspolne or {}}


# ---------- tury podstawowe / statusy / awarie ----------

def test_normalna_tura_publiczna_odpowiedz_bez_handoffu(monkeypatch):
    """LLM: handoff=false -> publiczna odpowiedz, zero handoffu, licznik tur +1."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Jaki gatunek Pana interesuje?"))

    lc.run_livechat_turn(77, "12", "m1", "Szukam blatu")

    assert calls["reply"] == ["Jaki gatunek Pana interesuje?"]
    assert calls["handoff"] == []
    assert lc._bot_turns(77) == 1


def test_tryb_informacyjny_bez_pozycji_zwykla_odpowiedz(monkeypatch):
    """Pytanie poboczne (dostawa itp.): brak pozycji i handoffu -> zwykla odpowiedz, zero dopytek o wycene."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Dostawa kurierem, zwykle kilka dni roboczych."))

    lc.run_livechat_turn(77, "12", "m1", "Jak wyglada dostawa?")

    assert calls["reply"] == ["Dostawa kurierem, zwykle kilka dni roboczych."]
    assert calls["handoff"] == []
    assert lc._awaiting_confirm(77) is False


def test_reklamacja_bez_handoffu(monkeypatch):
    """Reklamacja -> instrukcja mailowa, BEZ handoffu, rozmowa zostaje (pending)."""
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Kupiłem blat i pękł, chcę zgłosić reklamację")
    assert calls["chat"] == []
    assert calls["handoff"] == [], "reklamacja nie robi juz handoffu"
    assert len(calls["reply"]) == 1
    assert "reklamacje@woodpower.pl" in calls["reply"][0]
    assert "pomóc" in calls["reply"][0].lower()


def test_reklamacja_jawna_slowo(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Chcę zgłosić reklamację blatu")
    assert calls["chat"] == [] and calls["handoff"] == []
    assert "reklamacje@woodpower.pl" in calls["reply"][0]


def test_reklamacja_uszkodzenie_z_posiadaniem(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Kupiłem blat 3 miesiące temu i pękł przy zlewie")
    assert calls["handoff"] == []


def test_pytanie_o_trwalosc_nie_jest_reklamacja(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp("Dąb jest bardzo trwały."))
    lc.run_livechat_turn(77, "12", "m1", "czy drewno jest odporne na uszkodzenia?")
    assert calls["handoff"] == [] and calls["reply"] == ["Dąb jest bardzo trwały."]


def test_czy_reklamacja_helper():
    assert lc._czy_reklamacja("chcę reklamować") is True
    assert lc._czy_reklamacja("mój blat pękł") is True
    assert lc._czy_reklamacja("jak uniknąć pęknięć w blacie?") is False
    assert lc._czy_reklamacja("czy to się nie uszkodzi?") is False


def test_deflect_msg_obiecuje_przelaczenie():
    low = lc.DEFLECT_MSG.lower()
    assert "konsultant" in low and ("przełącz" in low or "połącz" in low)


def test_czlowiek_pierwsza_prosba_miekkie_odbicie(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Chcę rozmawiać z konsultantem")
    assert calls["chat"] == []
    assert calls["handoff"] == [], "pierwsza prosba -> odbicie, nie handoff"
    assert calls["reply"] == [lc.DEFLECT_MSG]
    assert lc._human_deflected(77) is True


def test_czlowiek_druga_prosba_handoff(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Chcę konsultanta")
    lc.run_livechat_turn(77, "12", "m2", "no dawaj tego człowieka")
    assert len(calls["handoff"]) == 1


def test_od_konsultanta_nie_wyzwala_odbicia(monkeypatch):
    """Regresja conv 542: 'czekam na potwierdzenie od konsultanta' to wzmianka, nie prosba."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Jasne."))
    lc.run_livechat_turn(77, "12", "m1", "czekam na potwierdzenie od konsultanta")
    assert calls["reply"] == ["Jasne."], "wzmianka nie moze odbic ani przekazac"
    assert calls["handoff"] == []


def test_czy_prosi_o_czlowieka():
    assert lc._czy_prosi_o_czlowieka("chcę konsultanta") is True
    assert lc._czy_prosi_o_czlowieka("potwierdzenie od konsultanta") is False


def test_od_doradcy_nie_wyzwala_odbicia():
    assert lc._czy_prosi_o_czlowieka("materiał polecony od doradcy") is False


def test_awaiting_prosba_o_czlowieka_handoff_bez_deflect(monkeypatch):
    """W stanie potwierdzenia prosba o konsultanta -> od razu handoff (nie deflect)."""
    calls = _mock_env(monkeypatch)
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m1", "tak, proszę przekazać konsultantowi do wyceny")
    assert calls["chat"] == []
    assert len(calls["handoff"]) == 1
    assert calls["reply"] == [lc.CLOSING_MSG]


def test_pytanie_o_bota_nie_odbija_tylko_llm(monkeypatch):
    """'czy rozmawiam z botem czy z człowiekiem' -> NIE deflect, odpowiada LLM (uczciwie)."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Jestem asystentem AI wspierającym zespół WoodPower."))
    lc.run_livechat_turn(77, "12", "m1", "Chcę blat dębowy. Czy rozmawiam z botem, czy z człowiekiem?")
    assert len(calls["chat"]) == 1, "pytanie o tozsamosc idzie do LLM"
    assert calls["reply"] == ["Jestem asystentem AI wspierającym zespół WoodPower."]
    assert calls["handoff"] == []


def test_prosba_o_czlowieka_pierwsza_deflect_druga_handoff(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.run_livechat_turn(77, "12", "m1", "Chcę rozmawiać z konsultantem")
    assert calls["reply"] == [lc.DEFLECT_MSG] and calls["handoff"] == []
    lc.run_livechat_turn(77, "12", "m2", "no dawaj tego konsultanta")
    assert len(calls["handoff"]) == 1


def test_status_open_bot_milczy(monkeypatch):
    calls = _mock_env(monkeypatch, status="open")
    lc.run_livechat_turn(77, "12", "m1", "Halo?")
    assert calls["reply"] == [] and calls["handoff"] == [] and calls["chat"] == []


def test_status_none_rzuca_i_nic_nie_wysyla(monkeypatch):
    import pytest
    calls = _mock_env(monkeypatch, status=None)
    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "Halo?")
    assert calls["reply"] == [] and calls["handoff"] == [] and calls["chat"] == []


def test_licznik_tur_wymusza_handoff(monkeypatch):
    """Bezpiecznik D: po BOT_LIVE_MAX_TURNS turach -> wymuszony handoff bez LLM."""
    calls = _mock_env(monkeypatch)
    c = db_mod.db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns) VALUES(77, ?)",
              (config.BOT_LIVE_MAX_TURNS,))
    c.commit(); c.close()

    lc.run_livechat_turn(77, "12", "m1", "A jeszcze jedno pytanie")

    assert calls["chat"] == []
    assert calls["reply"] == [lc.CLOSING_MSG]
    assert len(calls["handoff"]) == 1
    assert "limit tur" in calls["note"][0].lower()


def test_brak_odpowiedzi_llm_rzuca(monkeypatch):
    import pytest
    calls = _mock_env(monkeypatch)
    monkeypatch.setattr(lc, "chat", lambda m, **kw: None)
    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"] == [], "przy bledzie LLM nie wysylamy nic klientowi (retry w workerze)"


def test_handoff_with_apology(monkeypatch):
    calls = _mock_env(monkeypatch)
    lc.handoff_with_apology(77)
    assert calls["reply"] == [lc.APOLOGY_MSG]
    assert len(calls["handoff"]) == 1
    assert len(calls["note"]) == 1


def test_nieudany_toggle_rzuca_i_nic_nie_wysyla(monkeypatch):
    """Reklamacja juz nie robi handoffu (patrz test_reklamacja_bez_handoffu), wiec toggle
    testujemy na innej sciezce przez _do_handoff: bezpiecznik D (limit tur bota)."""
    import pytest
    calls = _mock_env(monkeypatch)
    c = db_mod.db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns) VALUES(77, ?)",
              (config.BOT_LIVE_MAX_TURNS,))
    c.commit(); c.close()
    monkeypatch.setattr(lc, "cw_bot_handoff", lambda cid, token=None: False)
    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "A jeszcze jedno pytanie")
    assert calls["reply"] == [], "klient nie moze dostac 'przekazuje' gdy handoff padl"
    assert calls["note"] == []


def test_nieudana_wysylka_odpowiedzi_rzuca_i_nie_bumpuje_licznika(monkeypatch):
    import pytest
    calls = _mock_env(monkeypatch, llm_json=_odp("Jaki gatunek Pana interesuje?"))
    monkeypatch.setattr(lc, "cw_agent_reply", lambda cid, t: False)
    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "Szukam blatu")
    assert lc._bot_turns(77) == 0, "licznik tur nie moze wzrosnac przy nieudanej wysylce"


def test_handoff_resetuje_stan(monkeypatch):
    """Po handoffie znikaja live_state (licznik+awaiting) i live_dane."""
    calls = _mock_env(monkeypatch, llm_json=_odp(handoff=True, powod="klient prosi o człowieka"))
    c = db_mod.db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns, awaiting_confirm) VALUES(77, 3, 1)")
    c.commit(); c.close()
    lc._merge_dane(77, _odp(pozycje=[_poz()]))

    lc.run_livechat_turn(77, "12", "m1", "wolę z kimś porozmawiać")

    c = db_mod.db()
    row = c.execute("SELECT * FROM live_state WHERE conv_id=77").fetchone()
    c.close()
    assert row is None
    assert lc._load_dane(77) == {"pozycje": [], "wspolne": {}}


# ---------- parsowanie LLM ----------

def test_zly_json_traktowany_jako_tekst(monkeypatch):
    calls = _mock_env(monkeypatch, llm_raw="Dzień dobry, w czym mogę pomóc?")
    lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"] == ["Dzień dobry, w czym mogę pomóc?"]
    assert calls["handoff"] == []


def test_json_w_plocie_markdown_parsowany(monkeypatch):
    payload = json.dumps(_odp("OK"))
    calls = _mock_env(monkeypatch, llm_raw="```json\n" + payload + "\n```")
    lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"] == ["OK"]


def test_dwa_ploty_markdown_drugi_poprawny_json(monkeypatch):
    payload = json.dumps(_odp("Druga odpowiedz OK"))
    raw = "Przyklad:\n```\nto nie jest json\n```\n\nWlasciwa odpowiedz:\n```json\n" + payload + "\n```"
    calls = _mock_env(monkeypatch, llm_raw=raw)
    lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"] == ["Druga odpowiedz OK"]


def test_parse_llm_pozycje_i_wspolne():
    d = lc._parse_llm(json.dumps(_odp("ok", pozycje=[{"id": "1", "produkt": "blat"}],
                                      wspolne={"kontakt": "jan@x.pl"})))
    assert d["pozycje"] == [{"id": "1", "produkt": "blat"}]
    assert d["wspolne"] == {"kontakt": "jan@x.pl"}


def test_parse_llm_smieci_w_pozycjach_ignorowane():
    d = lc._parse_llm('{"odpowiedz": "ok", "handoff": false, "pozycje": "nie-lista", "wspolne": []}')
    assert d["pozycje"] == [] and d["wspolne"] == {}


def test_format_ma_pozycje_i_zasady_handoffu():
    for frag in ('"pozycje"', '"wspolne"', '"id"', '"usun"', '"ilosc"', '"schody"'):
        assert frag in lc._FORMAT
    assert "NIE ustawiaj handoff na samo pytanie o cenę" in lc._FORMAT
    assert "POTWIERDZIŁ" in lc._FORMAT
    assert "reklamacja" in lc._FORMAT


# ---------- warstwa danych: load/merge pozycji ----------

def test_load_dane_pusty_gdy_brak():
    assert lc._load_dane(999) == {"pozycje": [], "wspolne": {}}


def test_load_dane_stary_plaski_zapis_jako_pozycja_1():
    """Kompatybilnosc wstecz: rozmowy w toku sprzed deployu (plaski dict) czytane jako pozycja 1."""
    c = db_mod.db()
    c.execute("INSERT INTO live_dane(conv_id, dane_json) VALUES(77, ?)",
              (json.dumps({"produkt": "blat", "dlugosc": "200", "kontakt": "jan@x.pl"}),))
    c.commit(); c.close()
    d = lc._load_dane(77)
    assert d["pozycje"][0]["id"] == "1"
    assert d["pozycje"][0]["produkt"] == "blat"
    assert d["pozycje"][0]["dlugosc"] == "200"
    assert d["wspolne"] == {"kontakt": "jan@x.pl"}


def test_merge_dane_dwie_pozycje_naraz():
    """'2 blaty ... i 3 parapety ...' -> dwie osobne pozycje."""
    d = lc._merge_dane(77, _odp(pozycje=[
        {"id": "1", "produkt": "blat", "dlugosc": "150", "szerokosc": "40", "grubosc": "4", "ilosc": "2"},
        {"id": "2", "produkt": "parapet", "dlugosc": "150", "szerokosc": "30", "grubosc": "2", "ilosc": "3"}]))
    assert len(d["pozycje"]) == 2
    assert d["pozycje"][0]["produkt"] == "blat"
    assert d["pozycje"][1]["produkt"] == "parapet"


def test_merge_dane_korekta_pozycji_2_nie_rusza_pozycji_1():
    lc._merge_dane(77, _odp(pozycje=[
        {"id": "1", "produkt": "blat", "dlugosc": "150"},
        {"id": "2", "produkt": "parapet", "dlugosc": "150"}]))
    d = lc._merge_dane(77, _odp(pozycje=[{"id": "2", "dlugosc": "170"}]))
    assert d["pozycje"][0]["dlugosc"] == "150", "pozycja 1 nietknieta"
    assert d["pozycje"][1]["dlugosc"] == "170"


def test_merge_dane_pozycja_nieobecna_w_odpowiedzi_zostaje():
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat"}]))
    d = lc._merge_dane(77, _odp(pozycje=[]))
    assert len(d["pozycje"]) == 1, "krotka odpowiedz LLM nie moze zgubic pozycji"


def test_merge_dane_usun_true_usuwa_pozycje():
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat"},
                                     {"id": "2", "produkt": "parapet"}]))
    d = lc._merge_dane(77, _odp(pozycje=[{"id": "1", "usun": True}]))
    assert len(d["pozycje"]) == 1
    assert d["pozycje"][0]["produkt"] == "parapet"


def test_merge_dane_niepusta_nadpisuje_pusta_nie_kasuje():
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat", "otwory": "pod zlew"}]))
    d = lc._merge_dane(77, _odp(pozycje=[{"id": "1", "otwory": ""}]))
    assert d["pozycje"][0]["otwory"] == "pod zlew"


def test_merge_dane_bez_id_dopasowanie_po_produkcie():
    """LLM zgubil id: jedyna pozycja o tym samym produkcie -> merge, nie duplikat."""
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat", "dlugosc": "150"}]))
    d = lc._merge_dane(77, _odp(pozycje=[{"produkt": "blat", "gatunek": "dąb"}]))
    assert len(d["pozycje"]) == 1
    assert d["pozycje"][0]["gatunek"] == "dąb"
    assert d["pozycje"][0]["dlugosc"] == "150"


def test_merge_dane_nowe_id_nowa_pozycja():
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat"}]))
    d = lc._merge_dane(77, _odp(pozycje=[{"id": "2", "produkt": "schody"}]))
    assert len(d["pozycje"]) == 2


def test_merge_dane_wspolne_akumulowane():
    lc._merge_dane(77, _odp(wspolne={"kontakt": "jan@x.pl"}))
    d = lc._merge_dane(77, _odp(wspolne={"termin": "wrzesień"}))
    assert d["wspolne"] == {"kontakt": "jan@x.pl", "termin": "wrzesień"}


# ---------- straznik kompletnosci ----------

def test_brakujace_bez_pozycji_pyta_o_produkt():
    assert [k for _, k in lc._brakujace(_dane())] == ["produkt"]


def test_brakujace_komplet_pusta_lista():
    assert lc._brakujace(_dane(_poz())) == []


def test_brakujace_bez_technologii_i_klasy():
    poz = _poz(technologia="", klasa="")
    assert [k for _, k in lc._brakujace(_dane(poz))] == ["technologia", "klasa"]


def test_brakujace_ilosc_wymagana():
    poz = _poz(ilosc="")
    assert [k for _, k in lc._brakujace(_dane(poz))] == ["ilosc"]


def test_brakujace_otwory_krawedzie_niewymagane():
    """Otwory/krawedzie nie sa polami krytycznymi — komplet bez nich."""
    assert lc._brakujace(_dane(_poz(otwory="", krawedzie=""))) == []


def test_brakujace_schody_wymaga_pola_schody():
    poz = _poz(produkt="schody", dlugosc="", szerokosc="", grubosc="", schody="")
    assert [k for _, k in lc._brakujace(_dane(poz))] == ["schody"]


def test_brakujace_kazda_pozycja_musi_byc_kompletna():
    braki = lc._brakujace(_dane(_poz(), _poz(id="2", produkt="parapet", gatunek="")))
    assert [k for _, k in braki] == ["gatunek"]


def test_pytanie_o_braki_jedna_pozycja_bez_prefiksu():
    braki = lc._brakujace(_dane(_poz(technologia="")))
    assert lc._pytanie_o_braki(braki, False) == \
        "Żeby przygotować wycenę, potrzebuję jeszcze: technologię (lita czy mikrowczep)."


def test_pytanie_o_braki_wiele_pozycji_wskazuje_produkt():
    braki = lc._brakujace(_dane(_poz(), _poz(id="2", produkt="parapet", grubosc="", gatunek="")))
    pyt = lc._pytanie_o_braki(braki, True)
    assert "parapet" in pyt
    assert "grubość" in pyt and "gatunek" in pyt


def test_straznik_wstrzymuje_handoff_przy_brakach(monkeypatch):
    """B z niekompletnymi danymi -> bot NIE oddaje rozmowy, dopytuje, licznik tur +1."""
    calls = _mock_env(monkeypatch, llm_json=_odp(
        handoff=True, powod="komplet danych do wyceny",
        pozycje=[_poz(technologia="", klasa="")]))
    lc.run_livechat_turn(77, "12", "m1", "to wszystko")
    assert calls["handoff"] == [], "niekompletne dane nie moga oddac rozmowy"
    assert len(calls["reply"]) == 1
    assert "technologi" in calls["reply"][0].lower()
    assert lc._bot_turns(77) == 1


def test_straznik_przepuszcza_prosbe_o_czlowieka_mimo_brakow(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp(
        handoff=True, powod="klient prosi o człowieka", pozycje=[{"id": "1", "produkt": "blat"}]))
    lc.run_livechat_turn(77, "12", "m1", "wolę porozmawiać z kimś")
    assert len(calls["handoff"]) == 1
    assert calls["reply"] == [lc.CLOSING_MSG]


def test_straznik_przepuszcza_sprawe_indywidualna_mimo_brakow(monkeypatch):
    """Reklamacja / status zamowienia / faktura / zwrot -> handoff bez wzgledu na braki."""
    for powod in ("reklamacja produktu", "klient pyta o status zamówienia",
                  "prośba o fakturę", "zwrot towaru", "sprawa indywidualna"):
        setup_function(None)
        calls = _mock_env(monkeypatch, llm_json=_odp(handoff=True, powod=powod))
        lc.run_livechat_turn(77, "12", "m1", "mam sprawę")
        assert len(calls["handoff"]) == 1, "powod '%s' musi przejsc mimo brakow" % powod


def test_kontakt_zwrotny_nie_przepuszcza_strażnika():
    """Regresja regexu: 'zwrotny' (kontakt zwrotny) NIE moze pasowac do 'zwrot'."""
    assert lc._czy_powod_kompletu("klient podał kontakt zwrotny") is True


# ---------- podsumowanie i potwierdzenie ----------

def test_komplet_wysyla_podsumowanie_zamiast_handoffu(monkeypatch):
    """Bramka B: LLM chce handoff 'komplet', ale klient jeszcze nie potwierdzil ->
    kod wysyla podsumowanie i ustawia awaiting_confirm."""
    calls = _mock_env(monkeypatch, llm_json=_odp(handoff=True, powod="komplet danych",
                                                 pozycje=[_poz()]))
    lc.run_livechat_turn(77, "12", "m1", "to wszystko")
    assert calls["handoff"] == [], "handoff komplet bez potwierdzenia klienta zabroniony"
    assert len(calls["reply"]) == 1
    assert "Podsumowuję dane do wyceny" in calls["reply"][0]
    assert "Czy wszystko się zgadza?" in calls["reply"][0]
    assert lc._awaiting_confirm(77) is True
    assert lc._bot_turns(77) == 1


def test_komplet_bez_handoffu_tez_wysyla_podsumowanie(monkeypatch):
    """Takze gdy LLM nie ustawil handoff: komplet wymaganych -> podsumowanie + stan potwierdzenia.
    Proza LLM NIE poprzedza podsumowania (koniec podwojnego podsumowania)."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Dziękuję!", pozycje=[_poz()]))
    lc.run_livechat_turn(77, "12", "m1", "wykończenie lakier")
    assert len(calls["reply"]) == 1
    assert calls["reply"][0].startswith("Podsumowuję dane do wyceny"), "podsumowanie bez prozy LLM"
    assert lc._awaiting_confirm(77) is True


def test_podsumowanie_bez_prozy_llm(monkeypatch):
    """Na turze z podsumowaniem NIE doklejamy prozy LLM (koniec podwojnego podsumowania)."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Potwierdzam parametry: blat debowy...", pozycje=[_poz()]))
    lc.run_livechat_turn(77, "12", "m1", "wykończenie olej")
    assert len(calls["reply"]) == 1
    assert "Potwierdzam parametry" not in calls["reply"][0], "proza LLM nie moze poprzedzac podsumowania"
    assert calls["reply"][0].startswith("Podsumowuję dane do wyceny")


def test_potwierdzenie_deterministyczne_robi_handoff(monkeypatch):
    """Awaiting + 'tak, zgadza sie' bez zmian danych -> handoff w kodzie, bez handoff=true od LLM."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Świetnie!", pozycje=[_poz()]))  # LLM handoff=false
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "tak, wszystko się zgadza")
    assert len(calls["handoff"]) == 1
    assert calls["reply"] == [lc.CLOSING_MSG]


def test_negacja_ze_slowem_zgadza_nie_jest_potwierdzeniem():
    assert lc._jest_potwierdzenie("tak, zgadza się") is True
    assert lc._jest_potwierdzenie("nie, źle, zmień grubość") is False
    assert lc._jest_potwierdzenie("a ile to kosztuje?") is False


def test_potwierdzenie_z_negacja_false():
    assert lc._jest_potwierdzenie("nie, to się nie zgadza") is False


def test_jest_potwierdzenie_z_pytaniem_false():
    assert lc._jest_potwierdzenie("tak, zgadza się") is True
    assert lc._jest_potwierdzenie("tak, ale zaokrąglicie krawędzie?") is False
    assert lc._jest_potwierdzenie("nie, to się nie zgadza") is False


def test_pytanie_w_stanie_confirm_nadal_zwykla_odpowiedz(monkeypatch):
    """Awaiting + pytanie (nie-potwierdzenie) -> zwykla odpowiedz, stan zostaje."""
    calls = _mock_env(monkeypatch, llm_json=_odp("Olej podkreśla słoje."))
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "czym różni się olej od lakieru?")
    assert calls["handoff"] == []
    assert calls["reply"] == ["Olej podkreśla słoje."]
    assert lc._awaiting_confirm(77) is True


def test_potwierdzenie_w_stanie_confirm_robi_handoff(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp(
        handoff=True, powod="klient potwierdził dane do wyceny", pozycje=[_poz()]))
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "tak, zgadza się")
    assert len(calls["handoff"]) == 1
    assert calls["reply"] == [lc.CLOSING_MSG]
    assert len(calls["note"]) == 1
    assert "Blat" in calls["note"][0] or "blat" in calls["note"][0]


def test_korekta_w_stanie_confirm_wysyla_nowe_podsumowanie(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp(
        "Poprawiłem grubość.", pozycje=[{"id": "1", "grubosc": "4"}]))
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "grubość zmień na 4")
    assert calls["handoff"] == []
    assert len(calls["reply"]) == 1
    assert "Podsumowuję dane do wyceny" in calls["reply"][0]
    assert "4 cm" in calls["reply"][0]
    assert lc._awaiting_confirm(77) is True, "stan potwierdzenia zostaje po korekcie"


def test_pytanie_w_stanie_confirm_zwykla_odpowiedz_stan_zostaje(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp("Olejowanie podkreśla usłojenie."))
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "a czym różni się olej od lakieru?")
    assert calls["reply"] == ["Olejowanie podkreśla usłojenie."]
    assert calls["handoff"] == []
    assert lc._awaiting_confirm(77) is True


def test_pusta_odpowiedz_w_stanie_confirm_ponawia_podsumowanie(monkeypatch):
    """Awaiting + brak zmian + pusta odpowiedz LLM -> ponowione podsumowanie, BEZ RuntimeError
    (falszywy handoff techniczny). Persona dopuszcza puste 'odpowiedz' przy komplecie."""
    calls = _mock_env(monkeypatch, llm_json=_odp())
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "no i?")
    assert calls["handoff"] == []
    assert len(calls["reply"]) == 1
    assert "Podsumowuję dane do wyceny" in calls["reply"][0]
    assert lc._awaiting_confirm(77) is True


def test_nowa_pozycja_w_stanie_confirm_niekompletna_wraca_do_zbierania(monkeypatch):
    """Klient dorzuca produkt przy potwierdzaniu -> stan wraca do zbierania, bot dopytuje."""
    calls = _mock_env(monkeypatch, llm_json=_odp(
        "Jasne — jaki gatunek parapetu?", pozycje=[{"id": "2", "produkt": "parapet"}]))
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "dorzućmy jeszcze parapet")
    assert calls["handoff"] == []
    assert lc._awaiting_confirm(77) is False, "niekomplet -> powrot do zbierania"
    assert calls["reply"] == ["Jasne — jaki gatunek parapetu?"]


def test_prosba_o_czlowieka_w_stanie_confirm_handoff(monkeypatch):
    """W stanie confirm (komplet zebrany) prosba o konsultanta to OD RAZU handoff, bez
    posredniego odbicia — regresja conv 552/561 (potwierdzenie z prosba o czlowieka gubilo
    sprawe w deflect zamiast przekazac od razu)."""
    calls = _mock_env(monkeypatch)
    lc._merge_dane(77, _odp(pozycje=[_poz()]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "wolę dokończyć z konsultantem")
    assert len(calls["handoff"]) == 1
    assert calls["reply"] == [lc.CLOSING_MSG]


def test_podsumowanie_dwie_pozycje_numerowane():
    msg = lc._podsumowanie_msg(_dane(
        _poz(ilosc="2", dlugosc="150", szerokosc="40", grubosc="4"),
        _poz(id="2", produkt="parapet", ilosc="3", dlugosc="150", szerokosc="30", grubosc="2")))
    assert "1. Blat — 2 szt." in msg
    assert "2. Parapet — 3 szt." in msg
    assert "Długość: 150 cm" in msg
    assert "Czy wszystko się zgadza?" in msg


def test_podsumowanie_jedna_pozycja_bez_numeracji():
    msg = lc._podsumowanie_msg(_dane(_poz()))
    assert "1." not in msg.split("\n")[2], "jedna pozycja bez numeru"
    assert "Blat — 2 szt." in msg


def test_podsumowanie_pomija_puste_pola_i_pokazuje_wspolne():
    msg = lc._podsumowanie_msg(_dane(_poz(otwory="", krawedzie=""), kontakt="jan@x.pl"))
    assert "Otwory" not in msg
    assert "Krawędzie" not in msg
    assert "Kontakt: jan@x.pl" in msg


def test_podsumowanie_otwory_podane_przez_klienta_widoczne():
    msg = lc._podsumowanie_msg(_dane(_poz(otwory="pod zlew", krawedzie="fazowane")))
    assert "Otwory/wycięcia: pod zlew" in msg
    assert "Krawędzie: fazowane" in msg


def test_summary_note_pozycje_i_wspolne():
    note = lc._summary_note(_dane(
        _poz(), _poz(id="2", produkt="parapet", ilosc="3")), "klient potwierdził dane do wyceny")
    assert "klient potwierdził dane do wyceny" in note
    assert "Blat" in note and "Parapet" in note
    assert "Technologia: lita" in note


def test_summary_note_pusty_stan_nie_pada():
    note = lc._summary_note({"pozycje": [], "wspolne": {}}, "błąd techniczny")
    assert "błąd techniczny" in note


# ---------- stan w promptcie ----------

def test_prompt_zawiera_zebrane_dane_i_instrukcje_confirm(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp("ok"))
    lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat", "dlugosc": "150"}]))
    lc._set_awaiting(77, True)
    lc.run_livechat_turn(77, "12", "m2", "hm")
    system = calls["chat"][0][0]["content"]
    assert "DOTYCHCZAS ZEBRANE DANE WYCENY (utrzymuj" in system
    assert '"dlugosc": "150"' in system
    assert "STAN ROZMOWY" in system, "instrukcja potwierdzenia doklejona w stanie confirm"


def test_prompt_bez_danych_bez_bloku_stanu(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp("ok"))
    lc.run_livechat_turn(77, "12", "m1", "dzień dobry")
    system = calls["chat"][0][0]["content"]
    assert "DOTYCHCZAS ZEBRANE DANE WYCENY (utrzymuj" not in system
    assert "STAN ROZMOWY" not in system


# ---------- walidacja koperty wymiarow ----------

def test_liczby_parsuje_przecinek_i_znaki():
    assert lc._liczby("265 × 860 × 3,8 cm") == [265.0, 860.0, 3.8]
    assert lc._liczby("265x90") == [265.0, 90.0]
    assert lc._liczby("") == []


def test_walidacja_szerokosc_ponad_max_odrzucona():
    msg = lc._walidacja_wymiarow(_dane(_poz(szerokosc="860")))
    assert msg is not None and "120 cm" in msg


def test_walidacja_dlugosc_lita_ponad_max_odrzucona():
    msg = lc._walidacja_wymiarow(_dane(_poz(dlugosc="480")))
    assert msg is not None and "450 cm" in msg


def test_walidacja_dlugosc_mikrowczep_480_ok():
    assert lc._walidacja_wymiarow(_dane(_poz(dlugosc="480", technologia="mikrowczep"))) is None


def test_walidacja_dlugosc_nieznana_560_odrzucona():
    msg = lc._walidacja_wymiarow(_dane(_poz(dlugosc="560", technologia="")))
    assert msg is not None and "500 cm" in msg


def test_walidacja_grubosc_nie_egzekwowana():
    assert lc._walidacja_wymiarow(_dane(_poz(grubosc="6"))) is None


def test_walidacja_wskazuje_pozycje_przy_wielu():
    msg = lc._walidacja_wymiarow(_dane(_poz(), _poz(id="2", produkt="parapet", szerokosc="130")))
    assert msg is not None and "parapet" in msg


def test_walidacja_pusty_stan_ok():
    assert lc._walidacja_wymiarow(_dane()) is None


def test_wymiar_ponad_koperte_odrzucony_bez_handoffu(monkeypatch):
    """Integracja: 860 cm szerokosci -> odrzucenie w kodzie, BEZ handoffu, BEZ podsumowania."""
    calls = _mock_env(monkeypatch, llm_json=_odp(
        handoff=True, powod="komplet danych", pozycje=[_poz(szerokosc="860")]))
    lc.run_livechat_turn(77, "12", "m1", "265 x 860 x 3 cm dąb lity A/B 2 szt lakier")
    assert calls["handoff"] == []
    assert len(calls["reply"]) == 1
    assert "120 cm" in calls["reply"][0]
    assert "Podsumowuję" not in calls["reply"][0]
    assert lc._bot_turns(77) == 1


def test_korekta_szerokosci_zachowuje_dlugosc(monkeypatch):
    """Korekta jednego pola pozycji: dlugosc z tury 1 przezywa, komplet -> podsumowanie."""
    _mock_env(monkeypatch, llm_json=_odp(handoff=True, powod="komplet",
                                         pozycje=[_poz(szerokosc="860")]))
    lc.run_livechat_turn(77, "12", "m1", "265 x 860 x 3.8 dąb lity A/B 2 szt lakier")
    calls2 = _mock_env(monkeypatch, llm_json=_odp(pozycje=[{"id": "1", "szerokosc": "118"}]))
    lc.run_livechat_turn(77, "12", "m2", "niech będzie 118")
    assert len(calls2["reply"]) == 1
    assert "Podsumowuję dane do wyceny" in calls2["reply"][0]
    assert "200 cm" in calls2["reply"][0], "dlugosc z tury 1 zachowana"
    assert lc._awaiting_confirm(77) is True


# ---------- normalizacja mm->cm ----------

def test_normalizuj_jednostki_mm_na_cm():
    poz = {"dlugosc": "3200", "szerokosc": "650", "grubosc": "40"}
    lc._normalizuj_jednostki(poz)
    assert poz["dlugosc"] == "320" and poz["szerokosc"] == "65" and poz["grubosc"] == "4"


def test_normalizuj_jednostki_cm_niezmienione():
    poz = {"dlugosc": "200", "szerokosc": "60", "grubosc": "4"}
    lc._normalizuj_jednostki(poz)
    assert poz["dlugosc"] == "200" and poz["szerokosc"] == "60" and poz["grubosc"] == "4"


def test_normalizuj_grubosc_mm_nie_psuje_wymiarow_cm():
    """Cross-turn: dl/szer juz w cm, grubosc podana w mm -> tylko grubosc dzielona."""
    poz = {"dlugosc": "200", "szerokosc": "65", "grubosc": "40"}
    lc._normalizuj_jednostki(poz)
    assert poz["dlugosc"] == "200" and poz["szerokosc"] == "65" and poz["grubosc"] == "4"


def test_normalizuj_granica_15_bez_zmian():
    poz = {"grubosc": "15"}
    lc._normalizuj_jednostki(poz)
    assert poz["grubosc"] == "15"


def test_normalizuj_grubosc_nieliczbowa_bez_zmian():
    poz = {"grubosc": "gruba"}
    lc._normalizuj_jednostki(poz)
    assert poz["grubosc"] == "gruba"


def test_merge_normalizuje_mm(monkeypatch):
    _mock_env(monkeypatch)
    d = lc._merge_dane(77, _odp(pozycje=[{"id": "1", "produkt": "blat",
        "dlugosc": "3200", "szerokosc": "650", "grubosc": "40"}]))
    assert d["pozycje"][0]["szerokosc"] == "65"


# ---------- loop-breaker odrzucen wymiaru ----------

def test_loop_breaker_drugie_odrzucenie_dodaje_podpowiedz_cm(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp(pozycje=[_poz(szerokosc="860", grubosc="3")]))
    lc.run_livechat_turn(77, "12", "m1", "szerokosc 860")   # 1. odrzucenie
    lc.run_livechat_turn(77, "12", "m2", "nadal 860")        # 2. to samo
    assert "centymetrach" in calls["reply"][-1]


def test_loop_breaker_trzecie_odrzucenie_handoff(monkeypatch):
    calls = _mock_env(monkeypatch, llm_json=_odp(pozycje=[_poz(szerokosc="860", grubosc="3")]))
    lc.run_livechat_turn(77, "12", "m1", "860")
    lc.run_livechat_turn(77, "12", "m2", "860")
    lc.run_livechat_turn(77, "12", "m3", "860")   # 3. -> handoff
    assert len(calls["handoff"]) == 1
