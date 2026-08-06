# -*- coding: utf-8 -*-
"""
Wspólna aplikacja testowa dla testów panelu trakowni.

Zwykły moduł, nie conftest.py — repo nie ma żadnego conftest, a ten fixture
dotyczy wyłącznie trakowni. Importuj w pliku testów:

    from tests.sawmill_fixtures import BASE, app, client  # noqa: F401
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.sawmill.models import (
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog,
    SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.users.models import User
# Sam import User nie wystarcza — to samo uzasadnienie co w
# tests/test_sawmill_numbering.py i tests/test_sawmill_mobile_api.py: modele
# trakowni (i ProductionConfig.updated_by) mają ForeignKey('users.id'), więc
# tabela 'users' musi w ogóle istnieć w db.metadata (inaczej NoReferencedTableError
# przy sortowaniu topologicznym FK) — stąd User.__table__ w TABLES niżej.
# User.multiplier_id ma z kolei relationship('Multiplier'), a Multiplier siedzi
# razem z Quote, które ma relationship('Client') i relationship('QuoteStatus') —
# configure_mappers() przy pierwszym flush/query próbuje skonfigurować CAŁY
# rejestr mapperów, więc te klasy też muszą być zaimportowane, mimo że
# trakownia ich w ogóle nie dotyka.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

BASE = '/production/api/sawmill'

TABLES = [m.__table__ for m in (
    User, SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery,
    SawmillOrder, SawmillLog, SawmillAudit, ProductionConfig,
)]

SETTINGS = {
    'min_circumference_cm': 30.0, 'max_circumference_cm': None,
    'min_length_cm': 30.0, 'max_length_cm': 20000.0,
    'decimal_places': 1, 'deviation_threshold_pct': 5.0,
}


@pytest.fixture()
def app(monkeypatch):
    """
    Dekorator dostępu podmieniamy na przelotkę — testujemy logikę trakowni,
    nie system uprawnień (ten ma własne testy w modules/users). Podmiana
    działa niezależnie od tego, kiedy panel_api.py zostało po raz pierwszy
    zaimportowane w całym pakiecie testów, bo router odwołuje się do
    require_module_access przez atrybut modułu (leniwie, przy każdym
    żądaniu), a nie przez skopiowaną referencję z `from ... import ...`.

    LOGIN_DISABLED=True neutralizuje prawdziwy flask_login.login_required —
    ta minimalna apka testowa nie ma skonfigurowanego LoginManagera (i nie
    testujemy tu Flask-Login, tylko logikę trakowni), a bez tej flagi
    login_required wywaliłby się na `current_app.login_manager` przy każdym
    żądaniu.
    """
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access',
                        lambda *a, **k: (lambda f: f))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True

    from modules.production.sawmill import sawmill_panel_bp
    app.register_blueprint(sawmill_panel_bp, url_prefix=BASE)
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        db.session.add(ProductionConfig(
            config_key='sawmill_settings', config_value=json.dumps(SETTINGS),
            config_type='json'))
        db.session.add(SawmillSpecies(name='Dąb', short_code='DB', sort_order=10))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()
