# -*- coding: utf-8 -*-
# Test: cw_bot_handoff oddaje rozmowe z pending do agentow (status open).
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BOT_CW_AGENT_TOKEN", "")
os.environ.setdefault("CHATWOOT_API_TOKEN", "admin_token")
import importlib

cw = importlib.import_module("core.chatwoot")


class FakeResp:
	def __init__(self, status_code, text="", json_data=None):
		self.status_code = status_code
		self.text = text
		self._json_data = json_data or {}
	def json(self):
		return self._json_data


def test_cw_bot_handoff_200_zwraca_true(monkeypatch):
	"""Status 200 -> True; sprawdza URL i JSON body."""
	posted_url = None
	posted_headers = None
	posted_json = None

	def fake_post(url, headers=None, json=None, timeout=None):
		nonlocal posted_url, posted_headers, posted_json
		posted_url = url
		posted_headers = headers
		posted_json = json
		return FakeResp(200)

	monkeypatch.setattr("core.chatwoot.requests.post", fake_post)

	result = cw.cw_bot_handoff(123)

	assert result is True
	assert posted_url.endswith("/toggle_status")
	assert posted_json == {"status": "open"}


def test_cw_bot_handoff_non_200_zwraca_false(monkeypatch):
	"""Non-200 status (np. 404) -> False, bez raise."""
	def fake_post(url, headers=None, json=None, timeout=None):
		return FakeResp(404, "Not found")

	monkeypatch.setattr("core.chatwoot.requests.post", fake_post)

	result = cw.cw_bot_handoff(456)

	assert result is False


def test_cw_bot_handoff_exception_zwraca_false(monkeypatch):
	"""Exception z requests.post -> False, bez raise."""
	def fake_post(url, headers=None, json=None, timeout=None):
		raise ConnectionError("Network error")

	monkeypatch.setattr("core.chatwoot.requests.post", fake_post)

	result = cw.cw_bot_handoff(789)

	assert result is False


def test_cw_bot_handoff_uzyt_bot_token_gdy_ustawiony(monkeypatch):
	"""Gdy BOT_CW_AGENT_TOKEN jest ustawiony, header api_access_token == BOT_CW_AGENT_TOKEN."""
	posted_headers = None

	def fake_post(url, headers=None, json=None, timeout=None):
		nonlocal posted_headers
		posted_headers = headers
		return FakeResp(200)

	monkeypatch.setattr("core.chatwoot.requests.post", fake_post)
	monkeypatch.setattr(cw, "BOT_CW_AGENT_TOKEN", "bot_token_123")

	cw.cw_bot_handoff(999)

	assert posted_headers["api_access_token"] == "bot_token_123"


def test_cw_bot_handoff_fallback_do_cw_token(monkeypatch):
	"""Gdy BOT_CW_AGENT_TOKEN jest None/pusty, uzyt CW_TOKEN."""
	posted_headers = None

	def fake_post(url, headers=None, json=None, timeout=None):
		nonlocal posted_headers
		posted_headers = headers
		return FakeResp(200)

	monkeypatch.setattr("core.chatwoot.requests.post", fake_post)
	monkeypatch.setattr(cw, "BOT_CW_AGENT_TOKEN", None)
	monkeypatch.setattr(cw, "CW_TOKEN", "admin_token_456")

	cw.cw_bot_handoff(111)

	assert posted_headers["api_access_token"] == "admin_token_456"
