# -*- coding: utf-8 -*-
# Testy trybu wyjscia tury: "reply" (wiadomosc do klienta) vs "note" (prywatna notatka).
# NAJWAZNIEJSZY test w tym pliku: w trybie "note" ZADNA sciezka nie moze dotknac surowej
# wysylki do klienta (_cw_agent_reply_raw) — to jedyna bariera chroniaca kanaly sprzedazy.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_reply_mode.db"))
import importlib

qb = importlib.import_module("bots.quotebot")
from bots.channel_caps import caps_for, _EMOJI_RE
from config import BOT_QUOTE_NOTE_PERSONAS


def _zabron_wysylki(monkeypatch):
    """Atrapa surowej wysylki, ktora wywraca test przy jakimkolwiek wywolaniu."""
    def _boom(*a, **kw):
        raise AssertionError("W trybie notatki bot NIE moze wysylac wiadomosci do klienta")
    monkeypatch.setattr(qb, "_cw_agent_reply_raw", _boom)


def test_tryb_note_nie_dotyka_surowej_wysylki(monkeypatch):
    """Bariera bezpieczenstwa: tryb 'note' nigdy nie wola _cw_agent_reply_raw."""
    _zabron_wysylki(monkeypatch)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    tryb = qb._reply_mode.set("note")
    try:
        wynik = qb.cw_agent_reply(1, "Dzień dobry, potrzebuję wymiarów.", token="tok")
    finally:
        qb._reply_mode.reset(tryb)
    assert wynik is True
    assert len(notatki) == 1
    assert "Dzień dobry, potrzebuję wymiarów." in notatki[0]


def test_tryb_note_dokleja_prefiks(monkeypatch):
    """Naglowek MUSI realnie trafic na poczatek notatki — sama niepusta stala nic nie dowodzi."""
    _zabron_wysylki(monkeypatch)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    t = qb._reply_mode.set("note")
    try:
        qb.cw_agent_reply(1, "Treść propozycji.", token="tok")
    finally:
        qb._reply_mode.reset(t)
    assert qb._NOTE_PREFIX.strip()
    assert notatki[0].startswith(qb._NOTE_PREFIX)
    assert notatki[0] == qb._NOTE_PREFIX + "Treść propozycji."


def test_prefiks_notatki_bez_emoji():
    """Prefiks doklejamy PO sanitizacji caps, a agent kopiuje notatke w calosci na kanal, ktory
    emoji nie renderuje — naglowek musi wiec sam z siebie byc czystym tekstem."""
    assert _EMOJI_RE.search(qb._NOTE_PREFIX) is None
    assert "**" not in qb._NOTE_PREFIX


def test_kazda_persona_notatki_ma_caps_czystego_tekstu():
    """Inwariant: persona dopisana do BOT_QUOTE_NOTE_PERSONAS bez wpisu w mapie caps dalaby
    notatke z markdownem i emoji do wklejenia wprost na marketplace."""
    assert BOT_QUOTE_NOTE_PERSONAS, "lista person trybu notatki nie moze byc pusta w domysle"
    for persona in BOT_QUOTE_NOTE_PERSONAS:
        caps = caps_for(persona)
        assert caps.get("markdown") is False, "persona %s renderuje markdown" % persona
        assert caps.get("emoji") is False, "persona %s przepuszcza emoji" % persona
        assert caps.get("max_len"), "persona %s bez limitu dlugosci wiadomosci" % persona


def test_tryb_note_uzywa_tokenu_z_kontekstu(monkeypatch):
    """Notatka idzie tokenem bota przypisanego do inboxu (_note_token), nie zaszytym."""
    _zabron_wysylki(monkeypatch)
    uzyte = {}
    monkeypatch.setattr(qb, "cw_note",
                        lambda conv_id, text, **kw: uzyte.update(kw) or True)
    t1 = qb._reply_mode.set("note")
    t2 = qb._note_token.set("token-woodpower-ai")
    try:
        qb.cw_agent_reply(1, "test", token="token-debusia")
    finally:
        qb._reply_mode.reset(t1); qb._note_token.reset(t2)
    assert uzyte.get("token") == "token-woodpower-ai"


def test_tryb_note_skleja_czesci_w_jedna_notatke(monkeypatch):
    """Podzial na wiadomosci (max_len OLX) zostaje widoczny, ale jako JEDNA notatka —
    inaczej agent dostaje lawine notatek zamiast jednej gotowej tresci."""
    _zabron_wysylki(monkeypatch)
    notatki = []
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: notatki.append(text) or True)
    t1 = qb._reply_mode.set("note")
    t2 = qb._reply_caps.set(dict(caps_for("quote_olx"), max_len=40))
    try:
        qb.cw_agent_reply(1, "Zdanie pierwsze. " * 10, token="tok")
    finally:
        qb._reply_mode.reset(t1); qb._reply_caps.reset(t2)
    assert len(notatki) == 1
    # Separator jest NUMEROWANY — przy trzech czesciach agent nie moze dwa razy czytac
    # "druga wiadomość"; kazda granica nazywa numer wiadomosci, ktora po niej nastepuje.
    assert (qb._SEPARATOR_CZESCI_TPL % 2) in notatki[0]


def test_separator_czesci_numeruje_kolejne_wiadomosci():
    """Trzy czesci -> granice numerowane 2 i 3, zaden numer sie nie powtarza."""
    tresc = qb._sklej_czesci_notatki(["A", "B", "C"])
    assert tresc == "A" + (qb._SEPARATOR_CZESCI_TPL % 2) + "B" + (qb._SEPARATOR_CZESCI_TPL % 3) + "C"
    assert "druga wiadomość" not in tresc


def test_tryb_reply_bez_zmian(monkeypatch):
    """Domyslny tryb 'reply' zachowuje sie dokladnie jak dotad (zero regresji na livechacie)."""
    wyslane = []
    monkeypatch.setattr(qb, "_cw_agent_reply_raw",
                        lambda conv_id, text, **kw: wyslane.append(text) or True)
    monkeypatch.setattr(qb, "cw_note",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("nie ta droga")))
    assert qb.cw_agent_reply(1, "Dzień dobry", token="tok") is True
    assert wyslane == ["Dzień dobry"]


def test_tryb_note_blad_zapisu_zwraca_false(monkeypatch):
    """Nieudany zapis notatki musi zwrocic False — od tego zaleza flagi stanu rozmowy."""
    monkeypatch.setattr(qb, "cw_note",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("API padlo")))
    t = qb._reply_mode.set("note")
    try:
        assert qb.cw_agent_reply(1, "test", token="tok") is False
    finally:
        qb._reply_mode.reset(t)


def test_tryb_note_przekazuje_obraz_do_notatki(monkeypatch):
    """Probki i wzorniki trafiaja do notatki jako zalacznik, nie gina."""
    _zabron_wysylki(monkeypatch)
    zlapane = {}
    monkeypatch.setattr(qb, "cw_note",
                        lambda conv_id, text, **kw: zlapane.update(kw) or True)
    t = qb._reply_mode.set("note")
    try:
        assert qb.cw_agent_reply(1, "podpis", image_path="/tmp/probka.jpg",
                                 image_name="probka.jpg", token="tok") is True
    finally:
        qb._reply_mode.reset(t)
    assert zlapane.get("image_path") == "/tmp/probka.jpg"
    assert zlapane.get("image_name") == "probka.jpg"


def test_tryb_dla_persony():
    """Mapowanie persona -> tryb wyjscia. Livechat rozmawia, marketplace pisze notatki."""
    assert qb._tryb_dla_persony("quote") == "reply"
    assert qb._tryb_dla_persony("quote_olx") == "note"
    assert qb._tryb_dla_persony("quote_allegro") == "note"


def test_bramka_w_trybie_notatki_przepuszcza_kazdy_status(monkeypatch):
    """Rozmowa 'open' (przejeta przez agenta) NIE blokuje notatki — notatka jest zawsze
    bezpieczna. To swiadome zniesienie bariery, ktora dzis wycisza OLX przypadkiem.
    W trybie notatki status nie jest nawet odpytywany (oszczedzamy wywolanie API)."""
    def _boom(conv_id):
        raise AssertionError("w trybie notatki status rozmowy nie jest potrzebny")
    monkeypatch.setattr(qb, "cw_conv_status", _boom)
    t = qb._reply_mode.set("note")
    try:
        assert qb._wolno_prowadzic_rozmowe(1) is True
    finally:
        qb._reply_mode.reset(t)


def test_bramka_w_trybie_reply_blokuje_poza_pending(monkeypatch):
    """W trybie 'reply' bramka dziala jak dotad: poza 'pending' bot milczy."""
    monkeypatch.setattr(qb, "cw_conv_status", lambda conv_id: "open")
    assert qb._wolno_prowadzic_rozmowe(1) is False


def test_bramka_w_trybie_reply_przepuszcza_pending(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda conv_id: "pending")
    assert qb._wolno_prowadzic_rozmowe(1) is True


def test_bramka_bez_statusu_rzuca_w_trybie_reply(monkeypatch):
    """Brak odczytu statusu = nie zgadujemy, czy wolno pisac do klienta -> retry w workerze."""
    import pytest
    monkeypatch.setattr(qb, "cw_conv_status", lambda conv_id: None)
    with pytest.raises(RuntimeError):
        qb._wolno_prowadzic_rozmowe(1)


def test_token_notatki_jedno_zrodlo_w_trybie_notatki(monkeypatch):
    """JEDNO zrodlo tokenu notatki na cala ture. Wczesniej wrapper pisal tokenem z contextvara,
    a _lead_note i _do_handoff zaszytym tokenem Debusia — jedna tura zostawiala notatki
    podpisane dwoma roznymi botami."""
    monkeypatch.setattr(qb, "BOT_QUOTE_CW_AGENT_TOKEN", "token-debusia")
    t = qb._note_token.set("token-woodpower-ai")
    try:
        assert qb._token_notatki() == "token-woodpower-ai"
    finally:
        qb._note_token.reset(t)


def test_token_notatki_dla_persony_quote_bez_zmian(monkeypatch):
    """Persona 'quote' (livechat/Messenger): _note_token jest pusty, wiec spadamy na token
    Debusia — zachowanie IDENTYCZNE jak przed wprowadzeniem jednego zrodla."""
    monkeypatch.setattr(qb, "BOT_QUOTE_CW_AGENT_TOKEN", "token-debusia")
    assert qb._note_token.get() is None
    assert qb._token_notatki() == "token-debusia"


def test_lead_note_uzywa_tokenu_notatki(monkeypatch):
    """Notatka leada (LS-01) tez musi isc tokenem bota widocznego na kanale."""
    uzyte = {}
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: uzyte.update(kw) or True)
    monkeypatch.setattr(qb, "_bloki_pozycji", lambda dane, options: [])
    t = qb._note_token.set("token-woodpower-ai")
    try:
        qb._lead_note(1, {"pozycje": []}, {}, wynik=None)
    finally:
        qb._note_token.reset(t)
    assert uzyte.get("token") == "token-woodpower-ai"


def test_token_notatki_uzywa_tokenu_woodpower_ai(monkeypatch):
    """Notatki na OLX/Allegro ida tokenem bota 'WoodPower AI' (przypisanego do inboxu), a nie
    tokenem Debusia z live chatu — chodzi o SPOJNOSC podpisu notatek na kanale."""
    monkeypatch.setattr(qb, "BOT_CW_AGENT_TOKEN", "token-woodpower-ai")
    monkeypatch.setattr(qb, "BOT_QUOTE_CW_AGENT_TOKEN", "token-debusia")
    assert qb._token_notatki_dla_persony("quote_olx") == "token-woodpower-ai"
    assert qb._token_notatki_dla_persony("quote") is None


def test_token_notatki_loguje_ostrzezenie_gdy_brak_tokenu_woodpower_ai(monkeypatch):
    """Fallback na token Debusia jest celowy (niekompletny config nie ma wywracac tury), ale
    musi byc GLOSNY — inaczej znikajaca notatka na OLX/Allegro jest niemozliwa do zdiagnozowania."""
    monkeypatch.setattr(qb, "BOT_CW_AGENT_TOKEN", None)
    monkeypatch.setattr(qb, "BOT_QUOTE_CW_AGENT_TOKEN", "token-debusia")
    ostrzezenia = []
    monkeypatch.setattr(qb, "log", lambda *a, **kw: ostrzezenia.append(a))
    assert qb._token_notatki_dla_persony("quote_olx") == "token-debusia"
    assert any("BOT_CW_AGENT_TOKEN" in str(a) for a in ostrzezenia)
