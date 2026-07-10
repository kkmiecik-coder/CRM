# -*- coding: utf-8 -*-
# Testy leadu OLX (T3-lead): numer klienta technicznego dla OLX = STALY prefiks kupujacego
# 'olx-<id>' (bez id watku), spojnie z modules/quotes/chatwoot_match.py, zeby panel "Wyceny CRM"
# zebral historie wycen kupujacego pod jednym klientem. Livechat/inne -> 'chat-<conv_id>'.
from bots import quotebot as qb


def test_olx_buyer_prefix_wyluskuje_staly_prefiks():
    assert qb._olx_buyer_prefix("olx-5028153-25066393520") == "olx-5028153"
    assert qb._olx_buyer_prefix("olx-5028153") == "olx-5028153"
    assert qb._olx_buyer_prefix("OLX-777-1") == "olx-777"  # bez znaczenia wielkosc liter


def test_olx_buyer_prefix_none_dla_nie_olx():
    for x in (None, "", "chat-12", "allegro-5", "jan@kowalski.pl", "olx-"):
        assert qb._olx_buyer_prefix(x) is None


def test_lead_number_olx_uzywa_pelnego_identyfikatora_z_chatwoota():
    # client_number = PELNA nazwa z Chatwoota (z id watku), nie sam prefiks.
    assert qb._lead_number(99, "olx-5028153-777") == "olx-5028153-777"
    assert qb._lead_number(99, "olx-5028153") == "olx-5028153"


def test_lead_number_fallback_chat_dla_nie_olx():
    assert qb._lead_number(99, "") == "chat-99"
    assert qb._lead_number(99, None) == "chat-99"
    assert qb._lead_number(99, "olx-") == "chat-99"  # niepoprawny -> fallback


def test_zapisz_wycene_uzywa_pelnego_identyfikatora_olx_jako_client_number(monkeypatch):
    # identifier przekazuje wolajacy (z kontaktu) — _zapisz_wycene NIE robi wlasnego zapytania.
    zebrane = {}
    def _fake_foc(email, phone, name, client_number=None):
        zebrane["client_number"] = client_number
        return {"ok": False}   # short-circuit: bez kontaktu -> cichy koniec (return True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client", _fake_foc)
    qb._zapisz_wycene(500, {}, {}, "", "", "", identifier="olx-4242-9")
    assert zebrane["client_number"] == "olx-4242-9"   # pelna nazwa z Chatwoota


def test_zapisz_wycene_livechat_zostaje_chat(monkeypatch):
    zebrane = {}
    def _fake_foc(email, phone, name, client_number=None):
        zebrane["client_number"] = client_number
        return {"ok": False}
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client", _fake_foc)
    qb._zapisz_wycene(501, {}, {}, "", "", "")   # brak identifier -> chat-<conv_id>
    assert zebrane["client_number"] == "chat-501"
