# -*- coding: utf-8 -*-
"""Schemat stanowiska „Kierownik hali” (Task 1): kod stanowiska `manager`, znacznik `prod_workers.is_manager`,
kolumna `prod_station_desk.sent_by_worker_id`, katalog pracowników z nowym kształtem 3 i zapis znacznika z panelu."""
import os

import pytest
from flask import Flask
from flask_login import AnonymousUserMixin, LoginManager
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionDevice, ProductionWorker
from modules.production.priorytety.models import StationDesk
from modules.production.routers import mobile_api
from modules.production.routers.api import api_bp
from modules.production.services import mobile_api_service
from modules.production.services.mobile_api_service import generate_token
from modules.production.services.station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS, station_label,
)
from modules.production.services.worker_service import create_worker, update_worker
from tests.logistyka_fixtures import app, client  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-10-19-kierownik-hali.sql')


def test_urzadzenie_kierownika_przechodzi_walidacje(app):
    d = ProductionDevice(device_id='TAB-KIER-1', station_code='manager')
    db.session.add(d)
    db.session.commit()
    assert d.id and station_label('manager') == 'Kierownik hali'


def test_manager_poza_procesem(app):
    # Kierownik nie ma kolejki statusów ani miejsca w drodze produktu; tablet jednak stoi na hali.
    assert 'manager' not in STATION_ORDER and 'manager' not in STATION_PENDING_STATUS
    assert 'manager' in mobile_api_service._STATION_CODES_WITH_TABLETS


def test_kolumny_znacznika_kierownika(app):
    w = ProductionWorker(first_name='Ala', last_name='Nowa')
    db.session.add(w)
    db.session.commit()
    assert w.is_manager is False
    assert hasattr(StationDesk, 'sent_by_worker_id')


def test_katalog_pracownikow_ma_is_manager_i_nowy_ksztalt(app, client):
    kier = create_worker('Jan', 'Kierownik')
    zwykly = create_worker('Ola', 'Zwykla')
    update_worker(kier.id, is_manager=True)
    device = ProductionDevice(device_id='TAB-KIER-KAT', device_name='Tablet', station_code='manager')
    db.session.add(device)
    db.session.commit()

    r = client.get('/api/mobile/workers', headers={'Authorization': 'Bearer ' + generate_token(device)})

    assert r.status_code == 200, r.get_data()[:300]
    profile = {w['id']: w for w in r.get_json()['workers']}
    assert profile[kier.id]['is_manager'] is True and profile[zwykly.id]['is_manager'] is False
    assert mobile_api.KSZTALT_KATALOGU_PRACOWNIKOW == 3
    # Segment kształtu w ETagu — inaczej tablet z zapamiętanym katalogiem dostałby 304 bez is_manager.
    assert r.headers['ETag'].startswith('W/"workers:3:')


def test_update_worker_ustawia_is_manager(app):
    w = create_worker('Jan', 'Kier')
    assert w.is_manager is False
    update_worker(w.id, is_manager=True)
    assert ProductionWorker.query.get(w.id).is_manager is True
    update_worker(w.id, is_manager=False)
    assert ProductionWorker.query.get(w.id).is_manager is False


def test_create_worker_przyjmuje_is_manager(app):
    w = create_worker('Jan', 'Kier', is_manager=True)
    assert ProductionWorker.query.get(w.id).is_manager is True


class _Admin(AnonymousUserMixin):
    id = 1
    email = 'admin@test.local'
    role = 'admin'
    is_authenticated = True


class _Zwykly(_Admin):
    id = 2
    role = 'user'


def _aplikacja_panelu(uzytkownik):
    """Minimalna apka z API panelu produkcji; `admin_required` czyta rolę „zalogowanego”."""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': StaticPool,
                                               'connect_args': {'check_same_thread': False}}
    app.config['LOGIN_DISABLED'] = True
    menedzer = LoginManager()
    menedzer.anonymous_user = uzytkownik
    menedzer.init_app(app)
    menedzer.user_loader(lambda user_id: None)
    app.register_blueprint(api_bp, url_prefix='/production/api')
    db.init_app(app)
    return app


@pytest.mark.parametrize('uzytkownik, status', [(_Zwykly, 403), (_Admin, 200)])
def test_patch_pracownika_is_manager_tylko_admin(uzytkownik, status):
    app = _aplikacja_panelu(uzytkownik)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[ProductionWorker.__table__])
        w = ProductionWorker(first_name='Jan', last_name='Kier')
        db.session.add(w)
        db.session.commit()
        wid = w.id

        r = app.test_client().patch(f'/production/api/workers/{wid}', json={'is_manager': True})

        assert r.status_code == status, r.get_data()[:300]
        db.session.expire_all()
        zapisano = ProductionWorker.query.get(wid).is_manager
        if status == 200:
            assert r.get_json()['worker']['is_manager'] is True and zapisano is True
        else:
            assert zapisano is False
        db.session.remove()


def test_migracja_kierownika_idempotentna():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert 'is_manager' in sql and 'sent_by_worker_id' in sql and 'information_schema' in sql.lower()
    assert 'ADD COLUMN is_manager TINYINT(1) NOT NULL DEFAULT 0' in sql
    assert 'ADD COLUMN sent_by_worker_id INT NULL' in sql
    assert 'DELIMITER' not in sql
