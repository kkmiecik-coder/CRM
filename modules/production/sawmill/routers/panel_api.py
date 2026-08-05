# -*- coding: utf-8 -*-
"""
API panelu trakowni — /production/api/sawmill/*

Wszystkie endpointy mają login_required ORAZ kontrolę dostępu do modułu
produkcji w wariancie JSON. To odstępstwo od wzorca reszty API produkcji,
gdzie require_module_access wisi tylko na trasach HTML — bez tego każdy
zalogowany użytkownik odczytałby ceny zakupu i deklaracje dostawców.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import jsonify, request
from flask_login import current_user, login_required

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.sawmill import sawmill_panel_bp
from modules.production.sawmill.models import (
    STATUS_NEW, SawmillDelivery, SawmillLog, SawmillOrder, SawmillSpecies,
    SawmillSupplier,
)
from modules.production.sawmill.services.numbering import next_order_number
from modules.production.sawmill.services.orders import write_audit

logger = get_structured_logger('production.sawmill.panel_api')

SUPPLIER_FIELDS = (
    'name', 'nip', 'address_street', 'address_zip', 'address_city',
    'contact_person', 'phone', 'email', 'notes',
)


def guard(f):
    """
    require_module_access('production', as_json=True) NA ZEWNĄTRZ,
    login_required wewnątrz — oba sprawdzane W MOMENCIE ŻĄDANIA, nie przy
    rejestracji trasy. Dwie poprawki względem referencyjnego kodu z briefu:

    1) Kolejność. Brief owijał tak: login_required(require_module_access(...)
    (f)) — login_required jako WARSTWA ZEWNĘTRZNA. flask_login.login_required
    nie zna as_json: gdy current_user nie jest zalogowany (a nie tylko: brak
    uprawnień), leci prosto do LoginManager.unauthorized(), które z ustawionym
    login_view w tym repo (patrz extensions.py) robi przekierowanie HTML (302
    na /login), nigdy nie docierając do require_module_access. Sprawdzone
    empirycznie: żądanie zupełnie bez sesji z kolejnością z briefu dostaje
    302 text/html zamiast JSON-a — dokładnie to, przed czym as_json=True miało
    chronić („Endpointy API nie mogą dostać strony HTML, bo frontend próbuje
    ją sparsować jako JSON" — komentarz przy require_module_access). Z
    require_module_access na zewnątrz każdy brak sesji/uprawnień kończy się
    poprawnym JSON-em (401/403) zanim login_required w ogóle się uruchomi;
    login_required zostaje jako wewnętrzna siatka bezpieczeństwa, bo w
    praktyce request, który przeszedł już przez require_module_access, ma
    też realną sesję flask_login (login_user() jest wołane razem z
    session['user_email'] w app.py).

    2) Moment wywołania. require_module_access jest wołane leniwie, przez
    atrybut modułu (`user_decorators.require_module_access`), a nie przez
    skopiowaną referencję z `from ... import ...` uchwyconą raz przy
    dekorowaniu trasy (czyli przy imporcie tego modułu). Ten moduł bywa
    importowany pośrednio przez `modules.production.sawmill.__init__`
    (razem z mobile_api) — mógłby więc zostać zaimportowany przez zupełnie
    inny plik testowy, zanim jakikolwiek test zdąży cokolwiek podmienić przez
    monkeypatch; kolejność zbierania plików testów przez pytest nie jest
    czymś, na czym wolno polegać. Leniwe odwołanie sprawia, że podmiana w
    teście działa niezależnie od tego, kiedy ten moduł został po raz
    pierwszy zaimportowany.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(
            login_required(f)
        )
        return checked(*args, **kwargs)
    return wrapped


class PanelValidationError(Exception):
    def __init__(self, field, detail):
        super().__init__(detail)
        self.field = field
        self.detail = detail


def _fail(exc):
    return jsonify({'error': 'validation_error',
                    'field': exc.field, 'detail': exc.detail}), 422


def _current_user_id():
    return getattr(current_user, 'id', None)


def _decimal(value, field, required=True):
    if value in (None, ''):
        if required:
            raise PanelValidationError(field, u'pole jest wymagane')
        return None
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise PanelValidationError(field, u'wartość nie jest liczbą')


def _parse_date(value, field, required=True):
    if value in (None, ''):
        if required:
            raise PanelValidationError(field, u'pole jest wymagane')
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise PanelValidationError(field, u'oczekiwano formatu RRRR-MM-DD')


# ── Gatunki ─────────────────────────────────────────────────────────────────

def _species_dict(s):
    return {'id': s.id, 'name': s.name, 'short_code': s.short_code,
            'sort_order': s.sort_order, 'is_active': bool(s.is_active)}


@sawmill_panel_bp.route('/species', methods=['GET'])
@guard
def species_list():
    query = SawmillSpecies.query
    if request.args.get('include_inactive') != '1':
        query = query.filter(SawmillSpecies.is_active.is_(True))
    rows = query.order_by(SawmillSpecies.sort_order, SawmillSpecies.name).all()
    return jsonify({'species': [_species_dict(s) for s in rows]})


@sawmill_panel_bp.route('/species', methods=['POST'])
@guard
def species_create():
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    if not name:
        return _fail(PanelValidationError('name', u'nazwa jest wymagana'))
    if SawmillSpecies.query.filter_by(name=name).first():
        return _fail(PanelValidationError('name', u'gatunek o tej nazwie już istnieje'))

    row = SawmillSpecies(
        name=name,
        short_code=(payload.get('short_code') or None),
        sort_order=int(payload.get('sort_order') or 0),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({'species': _species_dict(row)}), 201


@sawmill_panel_bp.route('/species/<int:species_id>', methods=['PATCH'])
@guard
def species_update(species_id):
    row = db.session.query(SawmillSpecies).get(species_id)
    if row is None:
        return jsonify({'error': 'not_found'}), 404
    payload = request.get_json(silent=True) or {}
    if 'name' in payload:
        row.name = (payload['name'] or '').strip() or row.name
    if 'short_code' in payload:
        row.short_code = payload['short_code'] or None
    if 'sort_order' in payload:
        row.sort_order = int(payload['sort_order'] or 0)
    if 'is_active' in payload:
        row.is_active = bool(payload['is_active'])
    db.session.commit()
    return jsonify({'species': _species_dict(row)})


@sawmill_panel_bp.route('/species/<int:species_id>', methods=['DELETE'])
@guard
def species_delete(species_id):
    """Kasowanie miękkie — historyczne zlecenia muszą dalej wskazywać na wiersz."""
    row = db.session.query(SawmillSpecies).get(species_id)
    if row is None:
        return jsonify({'error': 'not_found'}), 404
    row.is_active = False
    db.session.commit()
    return jsonify({'ok': True})


# ── Dostawcy ────────────────────────────────────────────────────────────────

def _supplier_dict(s):
    out = {'id': s.id, 'is_active': bool(s.is_active)}
    for field in SUPPLIER_FIELDS:
        out[field] = getattr(s, field)
    return out


@sawmill_panel_bp.route('/suppliers', methods=['GET'])
@guard
def suppliers_list():
    query = SawmillSupplier.query
    if request.args.get('include_inactive') != '1':
        query = query.filter(SawmillSupplier.is_active.is_(True))
    rows = query.order_by(SawmillSupplier.name).all()
    return jsonify({'suppliers': [_supplier_dict(s) for s in rows]})


@sawmill_panel_bp.route('/suppliers', methods=['POST'])
@guard
def supplier_create():
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    if not name:
        return _fail(PanelValidationError('name', u'nazwa jest wymagana'))
    if SawmillSupplier.query.filter_by(name=name).first():
        return _fail(PanelValidationError('name', u'dostawca o tej nazwie już istnieje'))

    row = SawmillSupplier(name=name, created_by_user_id=_current_user_id())
    for field in SUPPLIER_FIELDS:
        if field != 'name' and field in payload:
            setattr(row, field, payload[field] or None)
    db.session.add(row)
    db.session.commit()
    return jsonify({'supplier': _supplier_dict(row)}), 201


@sawmill_panel_bp.route('/suppliers/<int:supplier_id>', methods=['PATCH'])
@guard
def supplier_update(supplier_id):
    row = db.session.query(SawmillSupplier).get(supplier_id)
    if row is None:
        return jsonify({'error': 'not_found'}), 404
    payload = request.get_json(silent=True) or {}
    for field in SUPPLIER_FIELDS:
        if field in payload:
            setattr(row, field, payload[field] or None)
    if 'is_active' in payload:
        row.is_active = bool(payload['is_active'])
    db.session.commit()
    return jsonify({'supplier': _supplier_dict(row)})


@sawmill_panel_bp.route('/suppliers/<int:supplier_id>', methods=['DELETE'])
@guard
def supplier_delete(supplier_id):
    """Kasowanie miękkie — historyczne dostawy/zlecenia muszą dalej wskazywać na wiersz."""
    row = db.session.query(SawmillSupplier).get(supplier_id)
    if row is None:
        return jsonify({'error': 'not_found'}), 404
    row.is_active = False
    db.session.commit()
    return jsonify({'ok': True})


# ── Dostawy ─────────────────────────────────────────────────────────────────

def _delivery_dict(d):
    return {
        'id': d.id,
        'supplier_id': d.supplier_id,
        'supplier_name': d.supplier.name if d.supplier else None,
        'invoice_number': d.invoice_number,
        'invoice_date': d.invoice_date.isoformat() if d.invoice_date else None,
        'delivery_date': d.delivery_date.isoformat() if d.delivery_date else None,
        'notes': d.notes,
    }


@sawmill_panel_bp.route('/deliveries', methods=['POST'])
@guard
def delivery_create():
    """
    Tworzy dostawę wraz z pozycjami. KAŻDA pozycja to osobne zlecenie TRK.
    Numer i data faktury są opcjonalne, deklarowana objętość nigdy.

    Cała operacja (nagłówek dostawy + wszystkie zlecenia + wpisy audytu)
    idzie w JEDNEJ transakcji — commit dopiero na samym końcu. Błąd walidacji
    NA KTÓREJKOLWIEK pozycji cofa WSZYSTKO przez pojedynczy db.session.rollback(),
    także pozycje, które zdążyły już przejść flush() wcześniej w tej samej
    pętli — inaczej zostałaby osierocona dostawa bez (kompletu) zleceń, stan,
    którego reszta modułu nie przewiduje. Z tego samego powodu next_order_number()
    (który tylko rezerwuje numer i sam nie commituje) nie gubi numeru przy
    nieudanej próbie: rollback cofa też inkrementację licznika, więc numer
    wraca do puli i zostanie wydany ponownie przy kolejnej udanej próbie.
    """
    payload = request.get_json(silent=True) or {}
    try:
        supplier_id = payload.get('supplier_id')
        if not supplier_id or db.session.query(SawmillSupplier).get(supplier_id) is None:
            raise PanelValidationError('supplier_id', u'nieznany dostawca')

        delivery_date = _parse_date(payload.get('delivery_date'), 'delivery_date')
        invoice_date = _parse_date(payload.get('invoice_date'), 'invoice_date', required=False)

        items = payload.get('items') or []
        if not items:
            raise PanelValidationError('items', u'wymagana co najmniej jedna pozycja')

        delivery = SawmillDelivery(
            supplier_id=supplier_id,
            invoice_number=(payload.get('invoice_number') or None),
            invoice_date=invoice_date,
            delivery_date=delivery_date,
            notes=(payload.get('notes') or None),
            created_by_user_id=_current_user_id(),
        )
        db.session.add(delivery)
        db.session.flush()

        created = []
        for item in items:
            species_id = item.get('species_id')
            if not species_id or db.session.query(SawmillSpecies).get(species_id) is None:
                raise PanelValidationError('species_id', u'nieznany gatunek')

            declared = _decimal(item.get('declared_volume_m3'), 'declared_volume_m3')
            if declared <= 0:
                raise PanelValidationError('declared_volume_m3', u'wartość musi być dodatnia')
            price = _decimal(item.get('price_per_m3'), 'price_per_m3', required=False)

            order = SawmillOrder(
                order_number=next_order_number(),
                delivery_id=delivery.id,
                species_id=species_id,
                declared_volume_m3=declared,
                declared_logs_count=item.get('declared_logs_count') or None,
                price_per_m3=price,
                # Wartość liczy serwer — to, co przysłała przeglądarka, ignorujemy.
                declared_value=(declared * price) if price is not None else None,
                notes=(item.get('notes') or None),
                status=STATUS_NEW,
                created_by_user_id=_current_user_id(),
            )
            db.session.add(order)
            db.session.flush()
            write_audit(order.id, 'order_create', user_id=_current_user_id())
            created.append(order)

        db.session.commit()
    except PanelValidationError as exc:
        db.session.rollback()
        return _fail(exc)

    return jsonify({
        'delivery': _delivery_dict(delivery),
        'orders': [{'id': o.id, 'order_number': o.order_number} for o in created],
    }), 201


@sawmill_panel_bp.route('/deliveries/<int:delivery_id>', methods=['PATCH'])
@guard
def delivery_update(delivery_id):
    """
    Korekta nagłówka. Literówka w numerze faktury jest najbardziej
    prawdopodobnym błędem, a numer trafia na protokół PDF idący do dostawcy —
    więc każda zmiana zostawia ślad na wszystkich zleceniach tej dostawy.
    """
    delivery = db.session.query(SawmillDelivery).get(delivery_id)
    if delivery is None:
        return jsonify({'error': 'not_found'}), 404

    payload = request.get_json(silent=True) or {}
    before = _delivery_dict(delivery)
    try:
        if 'invoice_number' in payload:
            delivery.invoice_number = payload['invoice_number'] or None
        if 'invoice_date' in payload:
            delivery.invoice_date = _parse_date(payload['invoice_date'],
                                                'invoice_date', required=False)
        if 'delivery_date' in payload:
            delivery.delivery_date = _parse_date(payload['delivery_date'], 'delivery_date')
        if 'notes' in payload:
            delivery.notes = payload['notes'] or None
    except PanelValidationError as exc:
        db.session.rollback()
        return _fail(exc)

    db.session.flush()
    after = _delivery_dict(delivery)
    for order in SawmillOrder.query.filter_by(delivery_id=delivery.id).all():
        write_audit(order.id, 'delivery_update', before=before, after=after,
                    user_id=_current_user_id())
    db.session.commit()
    return jsonify({'delivery': after})


@sawmill_panel_bp.route('/deliveries/<int:delivery_id>', methods=['DELETE'])
@guard
def delivery_delete(delivery_id):
    """
    Kasuje dostawę wraz ze zleceniami. Przechodzi tylko wtedy, gdy KAŻDE
    zlecenie spełnia warunek usuwalności — zero wierszy w prod_sawmill_logs,
    licząc także soft-skasowane.
    """
    delivery = db.session.query(SawmillDelivery).get(delivery_id)
    if delivery is None:
        return jsonify({'error': 'not_found'}), 404

    orders = SawmillOrder.query.filter_by(delivery_id=delivery.id).all()
    for order in orders:
        if SawmillLog.query.filter_by(order_id=order.id).count() > 0:
            return jsonify({
                'error': 'has_logs',
                'detail': u'zlecenie {} ma zapisane pomiary'.format(order.order_number),
            }), 409

    before = _delivery_dict(delivery)
    for order in orders:
        write_audit(order.id, 'delivery_delete', before=before, user_id=_current_user_id())
        write_audit(order.id, 'order_delete', user_id=_current_user_id())
        db.session.delete(order)
    db.session.delete(delivery)
    db.session.commit()
    return jsonify({'ok': True})
