# -*- coding: utf-8 -*-
"""Nagłówek Content-Disposition dla NDA musi przejść przez serwer WSGI.

Kandydat z polskimi znakami w imieniu/nazwisku (np. "Przydział") dostawał błąd
przy generowaniu umowy NDA. Nazwa pliku trafiała surowo do Content-Disposition,
a każdy serwer WSGI koduje nagłówki w latin-1 (PEP 3333) — litery ą/ć/ę/ł/ń/ś/ź/ż
nie mieszczą się w tym zestawie, więc odpowiedź rwała się w trakcie wysyłki.
Kandydaci bez ogonków w nazwisku pobierali NDA bez problemu.

Konwencja jak test_bot_api_by_token_integration.py: minimalny Flask + blueprint,
bez pełnego create_app(). WeasyPrint jest podmieniony atrapą — testujemy sposób
zwracania pliku, nie renderowanie PDF-a.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from modules.partner_academy import partner_academy_bp
from modules.sales import sales_bp


FAKE_PDF = b'%PDF-1.4 atrapa'

# Nazwiska/miasta z ogonkami spoza latin-1 — dokładnie te przypadki, na których
# formularz się wykładał.
KANDYDACI = [
    ('Wojciech', 'Przydział'),
    ('Łukasz', 'Wiśniewski'),
    ('Agnieszka', 'Wójcik-Dąbrowska'),
    ('Zbigniew', 'Żółć'),
]


@pytest.fixture(params=[
    ('partner_academy', partner_academy_bp, '/partner-academy'),
    ('sales', sales_bp, '/sales'),
], ids=lambda p: p[0])
def client(request, monkeypatch):
    """Test client dla obu bliźniaczych modułów rekrutacyjnych."""
    modul, blueprint, prefix = request.param

    monkeypatch.setattr(
        f'modules.{modul}.routers.generate_nda_pdf',
        lambda data: FAKE_PDF,
    )

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(blueprint, url_prefix=prefix)

    c = app.test_client()
    c._prefix = prefix
    return c


def _generuj(client, first_name, last_name):
    return client.post(
        f'{client._prefix}/api/application/generate-nda',
        json={
            'first_name': first_name,
            'last_name': last_name,
            'email': 'kandydat@example.com',
            'city': 'Rzeszów',
            'address': 'Łanowa 67D/2',
            'postal_code': '35-213',
            'cooperation_type': 'contract',
        },
    )


@pytest.mark.parametrize('first_name,last_name', KANDYDACI)
def test_naglowek_przechodzi_przez_wsgi(client, first_name, last_name):
    """Content-Disposition musi dać się zakodować w latin-1 — inaczej WSGI rzuca."""
    response = _generuj(client, first_name, last_name)

    assert response.status_code == 200
    assert response.data == FAKE_PDF

    for klucz, wartosc in response.headers.items():
        # To robi serwer WSGI przy wysyłce; UnicodeEncodeError = zerwana odpowiedź.
        wartosc.encode('latin-1')


@pytest.mark.parametrize('first_name,last_name', KANDYDACI)
def test_nazwa_pliku_zachowuje_polskie_znaki(client, first_name, last_name):
    """Ogonki przetrwają w filename* (RFC 5987), a filename zostaje jako fallback."""
    response = _generuj(client, first_name, last_name)

    disposition = response.headers['Content-Disposition']
    assert 'attachment' in disposition
    assert "filename*=UTF-8''" in disposition

    from urllib.parse import unquote

    odkodowana = unquote(disposition.split("filename*=UTF-8''")[1].split(';')[0])
    assert odkodowana == f'NDA_{last_name}_{first_name}.pdf'


def test_nazwisko_bez_ogonkow_bez_zmian(client):
    """Regresja: kandydaci z ASCII-owym nazwiskiem mają nazwę pliku jak dotąd."""
    response = _generuj(client, 'Jan', 'Kowalski')

    assert response.status_code == 200

    disposition = response.headers['Content-Disposition']
    assert 'attachment' in disposition
    # Cudzysłów wokół nazwy jest opcjonalny (RFC 6266) — liczy się sama nazwa.
    assert 'NDA_Kowalski_Jan.pdf' in disposition
    assert "filename*" not in disposition
