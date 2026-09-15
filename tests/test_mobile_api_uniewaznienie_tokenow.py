# -*- coding: utf-8 -*-
"""
Unieważnianie tokenów tabletów przez bump `token_version`.

Wdrożenie podziału stanowiska Wykańczanie na Krawędzie i Lakiernię opiera się
na jednym założeniu operacyjnym: po podbiciu `prod_devices.token_version`
tablet dostaje 401 `invalid_token` i sam rejestruje się ponownie, po czym
dostaje token zgodny z bieżącym stanem bazy. Mechanizm istnieje w kodzie od
dawna, ale do tej pory nie miał ani jednego testu — `grep -rn "token_version"
tests/` nie dawał trafień. Ten plik jest bramką regresji, nie zamówieniem na
nową funkcję.

Najważniejszy jest ostatni test. `validate_token` czyta z claimów wyłącznie
`device_id` i `token_version`, a stanowisko bierze z bazy. Claim
`station_code` jest ozdobny i niesie wartość sprzed roku (JWT żyje 365 dni).
Gdyby ktoś kiedyś „poprawił" walidację tak, żeby ufała claimowi, każdy tablet
sprzed wdrożenia po cichu meldowałby się na stanowisko, którego już nie ma.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu z models.py trzyma globalny cache
dostępności tabeli, więc założenie jej w jednym pliku przestawiłoby go na
stałe dla całego procesu i wywróciło pozostałe testy produktów.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionDevice
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import (
    generate_token,
    register_device,
    validate_token,
)
# Importy rejestrujące mappery — configure_mappers() przy pierwszym query
# potrzebuje ich do rozwiązania relationshipów z modules/users/models.py.
# Wzorzec i uzasadnienie jak w tests/test_mobile_api_alias_krawedzi.py.
from modules.users.models import User  # noqa: F401
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

# Żądanie z unieważnionym tokenem odpada w dekoratorze, zanim handler dotknie
# czegokolwiek poza prod_devices — więcej tabel ten plik nie potrzebuje.
_TABLES = [ProductionDevice.__table__]

DEVICE_ID = 'tablet-hala-01'


@pytest.fixture()
def app():
    """Minimalny Flask + SQLAlchemy na SQLite in-memory (StaticPool — jedno
    współdzielone połączenie, żeby zapis z jednego request-contextu był
    widoczny w kolejnym zapytaniu w tym samym teście)."""
    flask_app = Flask(__name__)
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    flask_app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64,
        'jwt_expiry_days': 365,
        'ip_whitelist': [],
        'min_supported_app_version': '0.0.0',
    }
    flask_app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(flask_app)
    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield flask_app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def _zarejestrowane_urzadzenie(station_code):
    """Wiersz w prod_devices w stanie zastanym — `station_code` jest tu
    TREŚCIĄ testu: symulujemy tablet sprzed migracji krawędzi."""
    device = ProductionDevice(
        device_id=DEVICE_ID,
        device_name='Tablet hali 01',
        station_code=station_code,
    )
    db.session.add(device)
    db.session.commit()
    return device


# ---- unieważnienie ------------------------------------------------------

def test_bump_token_version_uniewaznia_stary_token(app):
    """Token wydany przed podbiciem wersji przestaje przechodzić walidację."""
    with app.app_context():
        device = _zarejestrowane_urzadzenie('finishing')
        stary_token = generate_token(device)

        # Dokładnie ten krok wykonuje operator na produkcji przed instalacją
        # nowego APK (UPDATE prod_devices SET token_version = token_version + 1).
        device.revoke_tokens()
        db.session.commit()

        with pytest.raises(ValueError) as exc:
            validate_token(stary_token)

        assert 'token_version' in str(exc.value), (
            u'komunikat ma wskazywać przyczynę odrzucenia — po nim operator '
            u'odróżnia unieważnienie od wygasłego podpisu'
        )


def test_uniewazniony_token_daje_401_a_nie_403(app, client):
    """
    Po stronie HTTP unieważniony token musi dać 401 `invalid_token`.

    Nie 403: ten status jest w BLEDY_DO_PONOWIENIA, więc @with_idempotency
    zachowuje się przy nim inaczej niż przy 401. Kontrakt appki wiąże
    automatyczną ponowną rejestrację właśnie z 401 — inny status zostawia
    tablet martwy do ręcznej interwencji na hali.

    Endpoint heartbeatu wybrany celowo: dotyka wyłącznie prod_devices, więc
    gdy dekorator przepuści token, żądanie kończy się czystym 204 zamiast
    błędu na brakującej tabeli — porażka tego strażnika ma być czytelna.
    """
    with app.app_context():
        device = _zarejestrowane_urzadzenie('finishing')
        stary_token = generate_token(device)
        device.revoke_tokens()
        db.session.commit()

    resp = client.post(
        '/api/mobile/devices/heartbeat',
        json={'app_version_code': 16, 'app_version_name': '1.0.15'},
        headers={'Authorization': 'Bearer ' + stary_token},
    )

    assert resp.status_code == 401
    assert resp.get_json()['error'] == 'invalid_token'


# ---- ponowna rejestracja ------------------------------------------------

def test_ponowna_rejestracja_po_uniewaznieniu_daje_dzialajacy_token(app):
    """
    Tablet po 401 rejestruje się ponownie tym samym device_id i wraca do gry.

    Rejestracja jest idempotentna po device_id: aktualizuje istniejący wiersz
    zamiast dokładać drugi, więc historia urządzenia (last_seen_at, telemetria)
    nie rozjeżdża się na dwa rekordy.
    """
    with app.app_context():
        device = _zarejestrowane_urzadzenie('finishing')
        device.revoke_tokens()
        db.session.commit()

        _, nowy_token = register_device(DEVICE_ID, 'Tablet hali 01', 'edges')

        odzyskane, _claims = validate_token(nowy_token)
        assert odzyskane.device_id == DEVICE_ID

        assert ProductionDevice.query.filter_by(device_id=DEVICE_ID).count() == 1, (
            u'ponowna rejestracja dołożyła drugi wiersz dla tego samego '
            u'device_id — historia urządzenia rozpada się na dwa rekordy'
        )


def test_ponowna_rejestracja_zapisuje_kod_kanoniczny(app):
    """Appka melduje się kodem docelowym, a wiersz i świeży claim go przyjmują."""
    with app.app_context():
        _zarejestrowane_urzadzenie('finishing')

        _, nowy_token = register_device(DEVICE_ID, 'Tablet hali 01', 'edges')

        wiersz = ProductionDevice.query.filter_by(device_id=DEVICE_ID).one()
        assert wiersz.station_code == 'edges'

        _device, claims = validate_token(nowy_token)
        assert claims['station_code'] == 'edges'


# ---- claim station_code jest ozdobny ------------------------------------

def test_stary_claim_station_code_nie_wplywa_na_autoryzacje(app):
    """
    Strażnik kluczowy: tożsamość stanowiska bierze się z bazy, nie z claimu.

    JWT żyje 365 dni, więc tablet zarejestrowany przed migracją nosi w
    payloadzie stary kod jeszcze długo po niej. Dopóki `token_version` się
    zgadza, taki token ma przechodzić, a urządzenie ma być widziane na
    stanowisku zapisanym w prod_devices — tym, które poprawiła migracja.
    """
    with app.app_context():
        device = _zarejestrowane_urzadzenie('finishing')
        token_sprzed_migracji = generate_token(device)

        # Migracja poprawia wiersz, token_version zostaje nietknięty —
        # tablet nie dostaje 401 i nie musi się przerejestrowywać.
        device.station_code = 'edges'
        db.session.commit()

        odzyskane, claims = validate_token(token_sprzed_migracji)

        assert claims['station_code'] == 'finishing', (
            u'stary claim ma zostać taki, jaki był — test opisuje zastany '
            u'token, nie postulat'
        )
        assert odzyskane.station_code == 'edges', (
            u'walidacja zaufała claimowi zamiast bazie: każdy tablet sprzed '
            u'wdrożenia meldowałby się na stanowisko, którego już nie ma'
        )
