# -*- coding: utf-8 -*-
# Testy wpiecia caps w wysylke quote-bota (T1-wire). Wrapper cw_agent_reply w quotebot
# naklada zdolnosci kanalu (caps) z kontekstu tury na KAZDE wywolanie: sanitizuje tekst,
# rozbija w limicie, pomija obraz gdy images=False. DEFAULT_CAPS = zachowanie jak dotad.
import pytest
from bots import quotebot
from bots.channel_caps import DEFAULT_CAPS, OLX_CAPS


class _Calls(list):
    """Lista wywolan z mozliwoscia ustawienia sekwencji zwrotow atrapy."""


@pytest.fixture
def zebrane(monkeypatch):
    """Podmienia surowa wysylke (_cw_agent_reply_raw) na atrape zbierajaca wywolania."""
    calls = _Calls()
    wyniki = {"seq": None}  # opcjonalna sekwencja zwrotow (True/False) per wywolanie

    def fake(conv_id, text, image_path=None, image_name=None, image_mime="image/jpeg", token=None):
        calls.append({"conv_id": conv_id, "text": text, "image_path": image_path, "token": token})
        if wyniki["seq"] is not None:
            return wyniki["seq"][len(calls) - 1]
        return True

    monkeypatch.setattr(quotebot, "_cw_agent_reply_raw", fake)
    calls.set_results = lambda seq: wyniki.__setitem__("seq", seq)  # helper do testu zwrotu
    return calls


def _z_caps(caps, fn):
    tok = quotebot._reply_caps.set(caps)
    try:
        return fn()
    finally:
        quotebot._reply_caps.reset(tok)


def test_default_caps_przekazuje_tekst_i_obraz_bez_zmian(zebrane):
    # Livechat/Messenger: markdown i emoji zostaja, obraz idzie, jedno wywolanie.
    _z_caps(DEFAULT_CAPS, lambda: quotebot.cw_agent_reply(
        7, "Twoja wycena: **1200 zł** 😊", image_path="probka.jpg", token="T"))
    assert len(zebrane) == 1
    assert zebrane[0]["text"] == "Twoja wycena: **1200 zł** 😊"
    assert zebrane[0]["image_path"] == "probka.jpg"
    assert zebrane[0]["token"] == "T"


def test_olx_caps_sanitizuje_tekst_i_pomija_obraz(zebrane):
    _z_caps(OLX_CAPS, lambda: quotebot.cw_agent_reply(
        7, "Twoja wycena: **1200 zł** 😊\n[link](https://woodpower.pl/q/x)",
        image_path="probka.jpg", token="T"))
    laczny = "\n".join(c["text"] for c in zebrane)
    assert "**" not in laczny and "😊" not in laczny
    assert "1200 zł" in laczny
    assert "https://woodpower.pl/q/x" in laczny
    assert all(c["image_path"] is None for c in zebrane)  # obraz pominiety na OLX


def test_olx_caps_rozbija_dlugi_tekst_w_limicie(zebrane):
    caps = {"markdown": False, "images": False, "emoji": False, "max_len": 50}
    tekst = ("Pierwsze zdanie wyceny. Drugie zdanie wyceny. Trzecie zdanie wyceny. "
             "Czwarte zdanie wyceny. Piąte zdanie wyceny.")
    _z_caps(caps, lambda: quotebot.cw_agent_reply(7, tekst, token="T"))
    assert len(zebrane) > 1
    assert all(len(c["text"]) <= 50 for c in zebrane)


def test_zwraca_false_gdy_ktorakolwiek_wysylka_nieudana(zebrane):
    caps = {"markdown": False, "images": False, "emoji": False, "max_len": 40}
    zebrane.set_results([True, False, True])  # druga czesc padnie
    tekst = "Zdanie jeden aaa. Zdanie dwa bbb. Zdanie trzy ccc ddd eee."
    wynik = _z_caps(caps, lambda: quotebot.cw_agent_reply(7, tekst, token="T"))
    assert wynik is False
    assert len(zebrane) >= 2


def test_pusty_tekst_z_obrazem_default_wysyla_raz_z_obrazem(zebrane):
    # Regresja: podpis moze byc pusty przy obrazie (livechat) -> nadal jedno wywolanie z obrazem.
    _z_caps(DEFAULT_CAPS, lambda: quotebot.cw_agent_reply(
        7, "", image_path="podpis.jpg", token="T"))
    assert len(zebrane) == 1
    assert zebrane[0]["text"] == ""
    assert zebrane[0]["image_path"] == "podpis.jpg"


def test_pusty_tekst_bez_obrazu_wysyla_raz_pusty(zebrane):
    _z_caps(DEFAULT_CAPS, lambda: quotebot.cw_agent_reply(7, "", token="T"))
    assert len(zebrane) == 1
    assert zebrane[0]["text"] == ""
    assert zebrane[0]["image_path"] is None
