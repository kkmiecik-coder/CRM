"""Logika wyboru/wzbogacania klienta technicznego chat-<conv_id> w /clients/find-or-create (LS-01)."""
from unittest.mock import MagicMock
from modules.calculator.routers.bot_api import _resolve_client


def _query_matching(existing, client_number):
    query = MagicMock()
    query.filter_by.side_effect = lambda **kw: MagicMock(
        first=lambda: existing if kw.get('client_number') == client_number else None)
    return query


def test_client_number_matches_istniejacy_technical_lead_bez_kontaktu():
    existing = MagicMock(id=7, client_name="chat-501", client_number="chat-501",
                         email=None, phone=None)
    query = _query_matching(existing, "chat-501")
    client, created = _resolve_client(query, email=None, phone=None, name=None,
                                      client_number="chat-501")
    assert client is existing and created is False
    assert existing.email is None and existing.phone is None


def test_client_number_wzbogaca_puste_pola_kontaktu():
    existing = MagicMock(id=7, client_name="chat-501", client_number="chat-501",
                         email=None, phone=None)
    query = _query_matching(existing, "chat-501")
    client, created = _resolve_client(query, email="jan@x.pl", phone="500600700",
                                      name="Jan", client_number="chat-501")
    assert client is existing and created is False
    assert existing.email == "jan@x.pl"
    assert existing.phone == "500600700"
    assert existing.client_name == "Jan"  # nazwa techniczna zastapiona realna, gdy klient ja poda


def test_client_number_nie_nadpisuje_juz_wypelnionego_kontaktu():
    existing = MagicMock(id=7, client_name="Jan", client_number="chat-501",
                         email="jan@x.pl", phone="500600700")
    query = _query_matching(existing, "chat-501")
    client, created = _resolve_client(query, email="inny@x.pl", phone=None, name=None,
                                      client_number="chat-501")
    assert existing.email == "jan@x.pl"  # kontakt z biezacej wiadomosci NIE nadpisuje juz zapisanego


def test_email_dopasowanie_ma_pierwszenstwo_przed_client_number():
    """Prawdziwy powracajacy klient (dopasowany po e-mailu) wygrywa z wlasnym leadem technicznym —
    zeby bot poprawnie rozpoznal powracajacego klienta, gdy podal ten sam e-mail co kiedys."""
    real_customer = MagicMock(id=3, client_name="Jan Kowalski", client_number="Jan Kowalski",
                              email="jan@x.pl", phone=None)
    technical_lead = MagicMock(id=7, client_name="chat-501", client_number="chat-501",
                               email=None, phone=None)
    query = MagicMock()
    def filter_by(**kw):
        if kw.get('email') == 'jan@x.pl':
            return MagicMock(first=lambda: real_customer)
        if kw.get('client_number') == 'chat-501':
            return MagicMock(first=lambda: technical_lead)
        return MagicMock(first=lambda: None)
    query.filter_by.side_effect = filter_by
    client, created = _resolve_client(query, email="jan@x.pl", phone=None, name="Jan",
                                      client_number="chat-501")
    assert client is real_customer and created is False


def test_brak_dopasowania_zwraca_none_none():
    query = MagicMock()
    query.filter_by.side_effect = lambda **kw: MagicMock(first=lambda: None)
    client, created = _resolve_client(query, email=None, phone=None, name=None,
                                      client_number="chat-999")
    assert client is None and created is False
