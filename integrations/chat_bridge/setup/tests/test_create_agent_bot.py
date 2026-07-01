# -*- coding: utf-8 -*-
# Testy setup/create_agent_bot.py — monkeypatch requests, brak sieci.
import importlib
from unittest import mock

cab = importlib.import_module("setup.create_agent_bot")


# ---------------------------------------------------------------------------
# Pomocnicze: mock odpowiedzi requests
# ---------------------------------------------------------------------------

def _mock_resp(status, body):
    """Tworzy mock obiektu requests.Response."""
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    return r


# ---------------------------------------------------------------------------
# list_agent_bots
# ---------------------------------------------------------------------------

def test_list_agent_bots_zwraca_liste(monkeypatch):
    """list_agent_bots parsuje odpowiedź z payload jako listę."""
    boty = [{"id": 1, "name": "WoodPower AI"}]
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok")
    with mock.patch("requests.get", return_value=_mock_resp(200, {"payload": boty})) as m:
        wynik = cab.list_agent_bots()
    assert wynik == boty
    assert m.call_count == 1


def test_list_agent_bots_zwraca_gola_liste(monkeypatch):
    """list_agent_bots akceptuje gołą listę (bez payload)."""
    boty = [{"id": 2, "name": "inny"}]
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok")
    with mock.patch("requests.get", return_value=_mock_resp(200, boty)):
        wynik = cab.list_agent_bots()
    assert wynik == boty


def test_list_agent_bots_puste_przy_bledzie_http(monkeypatch):
    """list_agent_bots zwraca [] gdy odpowiedź HTTP nie jest 200."""
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok")
    with mock.patch("requests.get", return_value=_mock_resp(403, {"error": "forbidden"})):
        wynik = cab.list_agent_bots()
    assert wynik == []


def test_list_agent_bots_puste_przy_wyjatku(monkeypatch):
    """list_agent_bots zwraca [] gdy requests.get rzuca wyjątek."""
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok")
    with mock.patch("requests.get", side_effect=ConnectionError("brak sieci")):
        wynik = cab.list_agent_bots()
    assert wynik == []


# ---------------------------------------------------------------------------
# ensure_agent_bot — bot już istnieje → bez POST
# ---------------------------------------------------------------------------

def test_ensure_zwraca_istniejacego_bota_bez_post(monkeypatch):
    """Gdy bot 'WoodPower AI' już istnieje w liście — POST nie jest wywoływany."""
    istniejacy = {"id": 42, "name": "WoodPower AI", "access_token": "tok_bot"}
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok_admin")

    # GET /agent_bots → bot już jest
    with mock.patch("requests.get", return_value=_mock_resp(200, [istniejacy])) as m_get, \
         mock.patch("requests.post") as m_post:
        wynik = cab.ensure_agent_bot("WoodPower AI")

    assert wynik["id"] == 42
    assert wynik["name"] == "WoodPower AI"
    # POST nie powinien być wywołany (idempotencja)
    m_post.assert_not_called()
    assert m_get.call_count == 1


# ---------------------------------------------------------------------------
# ensure_agent_bot — bot nieistniejący → POST tworzący
# ---------------------------------------------------------------------------

def test_ensure_tworzy_bota_gdy_brak(monkeypatch):
    """Gdy bota 'WoodPower AI' nie ma — wysyła POST i zwraca nowego bota."""
    nowy_bot = {"id": 7, "name": "WoodPower AI", "access_token": "nowy_tok"}
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok_admin")
    monkeypatch.setenv("BOT_AGENT_WEBHOOK_TOKEN", "sekret123")
    monkeypatch.setenv("BOT_AGENT_WEBHOOK_URL", "https://chatbridge.woodpower.pl/agent-bot")

    # GET → pusta lista; POST → sukces
    with mock.patch("requests.get", return_value=_mock_resp(200, [])), \
         mock.patch("requests.post", return_value=_mock_resp(201, nowy_bot)) as m_post:
        wynik = cab.ensure_agent_bot("WoodPower AI")

    assert wynik["id"] == 7
    assert wynik["access_token"] == "nowy_tok"

    # Sprawdź że POST wysłał właściwy outgoing_url z tokenem
    args, kwargs = m_post.call_args
    payload_wyslany = kwargs.get("json") or (args[1] if len(args) > 1 else {})
    assert "?token=sekret123" in payload_wyslany.get("outgoing_url", "")


def test_ensure_outgoing_url_bez_tokenu(monkeypatch):
    """Gdy BOT_AGENT_WEBHOOK_TOKEN nie jest ustawiony — outgoing_url bez query string."""
    nowy_bot = {"id": 8, "name": "WoodPower AI", "access_token": "tok2"}
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok_admin")
    monkeypatch.delenv("BOT_AGENT_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("BOT_AGENT_WEBHOOK_URL", "https://chatbridge.woodpower.pl/agent-bot")

    with mock.patch("requests.get", return_value=_mock_resp(200, [])), \
         mock.patch("requests.post", return_value=_mock_resp(201, nowy_bot)) as m_post:
        wynik = cab.ensure_agent_bot("WoodPower AI")

    assert wynik["id"] == 8
    args, kwargs = m_post.call_args
    payload_wyslany = kwargs.get("json") or {}
    outgoing = payload_wyslany.get("outgoing_url", "")
    assert "?" not in outgoing, "Brak tokenu -> brak query string w outgoing_url"
    assert outgoing == "https://chatbridge.woodpower.pl/agent-bot"


def test_ensure_rzuca_przy_bledzie_http(monkeypatch):
    """ensure_agent_bot rzuca RuntimeError gdy Chatwoot odpowie błędem HTTP."""
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok_admin")

    with mock.patch("requests.get", return_value=_mock_resp(200, [])), \
         mock.patch("requests.post", return_value=_mock_resp(422, {"error": "invalid"})):
        try:
            cab.ensure_agent_bot("WoodPower AI")
            assert False, "powinno rzucić RuntimeError"
        except RuntimeError as e:
            assert "422" in str(e)


def test_ensure_nie_duplikuje_innego_bota(monkeypatch):
    """Gdy lista ma tylko inne boty — POST tworzący jest wywołany."""
    inny_bot = {"id": 1, "name": "Inny Bot", "access_token": "xxx"}
    nowy_bot = {"id": 9, "name": "WoodPower AI", "access_token": "nowy"}
    monkeypatch.setenv("CHATWOOT_API_TOKEN", "tok_admin")

    with mock.patch("requests.get", return_value=_mock_resp(200, [inny_bot])), \
         mock.patch("requests.post", return_value=_mock_resp(201, nowy_bot)) as m_post:
        wynik = cab.ensure_agent_bot("WoodPower AI")

    assert wynik["id"] == 9
    m_post.assert_called_once()
