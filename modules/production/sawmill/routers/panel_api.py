# -*- coding: utf-8 -*-
"""
API panelu trakowni — /production/api/sawmill/*

Wszystkie endpointy mają login_required ORAZ kontrolę dostępu do modułu
produkcji w wariancie JSON. To odstępstwo od wzorca reszty API produkcji,
gdzie require_module_access wisi tylko na trasach HTML — bez tego każdy
zalogowany użytkownik odczytałby ceny zakupu i deklaracje dostawców.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import jsonify, make_response, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.sawmill import sawmill_panel_bp
from modules.production.sawmill.models import (
    STATUS_NEW, STATUS_SETTLED, SawmillAudit, SawmillDelivery, SawmillLog,
    SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.sawmill.services.numbering import next_order_number
from modules.production.sawmill.services.orders import (
    SawmillStateError, add_log, compute_differences, delete_log, order_totals,
    reopen_order, settle_order, unsettle_order, update_log, write_audit,
)
from modules.production.sawmill.services.serializers import (
    serialize_log_for_panel, serialize_order_for_panel,
)
from modules.production.sawmill.services.settings import (
    get_sawmill_settings, save_sawmill_settings,
)
from modules.production.sawmill.services.validation import (
    SawmillValidationError, parse_measured_at, validate_measurements,
)

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


# ── Zakładka panelu (HTML) ──────────────────────────────────────────────────

@sawmill_panel_bp.route('/tab-content', methods=['GET'])
@guard
def tab_content():
    """Zawartość zakładki, doczytywana AJAX-em jak pozostałe zakładki panelu."""
    settings = get_sawmill_settings()
    return render_template(
        'sawmill/tab_content.html',
        species=SawmillSpecies.query.filter_by(is_active=True)
                 .order_by(SawmillSpecies.sort_order, SawmillSpecies.name).all(),
        suppliers=SawmillSupplier.query.filter_by(is_active=True)
                   .order_by(SawmillSupplier.name).all(),
        deviation_threshold_pct=settings.get('deviation_threshold_pct', 5.0),
        today=date.today().isoformat(),
    )


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


# ── Zlecenia ────────────────────────────────────────────────────────────────

def _order_query():
    return (
        db.session.query(SawmillOrder)
        .options(joinedload(SawmillOrder.delivery).joinedload(SawmillDelivery.supplier),
                 joinedload(SawmillOrder.species))
    )


def _panel_payload(order, threshold_pct):
    count, volume = order_totals(order.id)
    differences = compute_differences(order, volume, threshold_pct)
    return serialize_order_for_panel(order, count, volume, differences)


def _state_error(exc):
    return jsonify({'error': 'invalid_state', 'detail': exc.detail}), 409


@sawmill_panel_bp.route('/orders', methods=['GET'])
@guard
def orders_list():
    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    query = _order_query()

    status = request.args.get('status')
    if status:
        query = query.filter(SawmillOrder.status == status)

    # JEDEN join do SawmillDelivery, niezależnie od tego, ile filtrów go
    # potrzebuje. Referencyjny kod z briefu wołał `.join(SawmillDelivery)`
    # osobno w każdym `if` — przy kilku filtrach naraz (np. supplier_id +
    # date_from + date_to + q) dawało to WIELOKROTNY JOIN do tej samej
    # tabeli bez aliasu. Sprawdzone empirycznie na SQLite: cztery filtry
    # naraz kończyły się `OperationalError: ambiguous column name:
    # prod_sawmill_deliveries.supplier_id`, bo silnik nie wie, do którego
    # z czterech wystąpień tabeli w FROM odnosi się WHERE. Na MySQL
    # dokładnego błędu może nie być (dialekt bywa łaskawszy dla powtórzonych
    # JOIN-ów bez aliasu), ale to i tak zbędna praca serwera — jeden JOIN
    # w zupełności wystarcza do zastosowania wszystkich filtrów po SawmillDelivery.
    needs_delivery_join = any(request.args.get(key) for key in
                              ('supplier_id', 'date_from', 'date_to', 'q'))
    if needs_delivery_join:
        query = query.join(SawmillDelivery)

    if request.args.get('supplier_id'):
        query = query.filter(SawmillDelivery.supplier_id == int(request.args['supplier_id']))
    if request.args.get('species_id'):
        query = query.filter(SawmillOrder.species_id == int(request.args['species_id']))
    if request.args.get('date_from'):
        query = query.filter(
            SawmillDelivery.delivery_date >= date.fromisoformat(request.args['date_from']))
    if request.args.get('date_to'):
        query = query.filter(
            SawmillDelivery.delivery_date <= date.fromisoformat(request.args['date_to']))
    if request.args.get('q'):
        wzorzec = '%{}%'.format(request.args['q'].strip())
        query = query.filter(
            db.or_(SawmillOrder.order_number.like(wzorzec),
                   SawmillDelivery.invoice_number.like(wzorzec)))

    rows = query.order_by(SawmillOrder.id.desc()).all()
    payload = [_panel_payload(o, threshold) for o in rows]

    # Filtr odchyleń stosujemy po wyliczeniu różnic, po stronie Pythona —
    # nie da się go wyrazić w SQL, skoro is_deviation zależy od sumy pomiarów
    # (agregat per zlecenie liczony osobnym zapytaniem w order_totals) i progu
    # z ustawień, nie od żadnej kolumny w prod_sawmill_orders. Endpoint nie ma
    # paginacji (brak page/per_page, brak pola `total` w odpowiedzi) — samo
    # przefiltrowanie już zmaterializowanej listy `payload` nie psuje więc
    # żadnego licznika ani offsetu, bo takich tu po prostu nie ma.
    if request.args.get('only_deviation') == '1':
        payload = [p for p in payload if p['is_deviation']]

    return jsonify({'orders': payload, 'deviation_threshold_pct': threshold})


@sawmill_panel_bp.route('/orders/<int:order_id>', methods=['GET'])
@guard
def order_details(order_id):
    order = _order_query().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return jsonify({'error': 'not_found'}), 404

    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    logs = (SawmillLog.query.filter_by(order_id=order_id)
            .order_by(SawmillLog.sequence_no).all())
    audit = (SawmillAudit.query.filter_by(order_id=order_id)
             .order_by(SawmillAudit.id.desc()).limit(200).all())

    return jsonify({
        'order': _panel_payload(order, threshold),
        'delivery': _delivery_dict(order.delivery),
        'logs': [serialize_log_for_panel(l) for l in logs],
        'audit': [{
            'id': a.id, 'action': a.action, 'log_id': a.log_id,
            'before': json.loads(a.before_json) if a.before_json else None,
            'after': json.loads(a.after_json) if a.after_json else None,
            'device_id': a.device_id, 'user_id': a.user_id,
            'created_at': a.created_at.isoformat() if a.created_at else None,
        } for a in audit],
    })


@sawmill_panel_bp.route('/orders/<int:order_id>', methods=['PATCH'])
@guard
def order_update(order_id):
    order = _order_query().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return jsonify({'error': 'not_found'}), 404
    if order.status == STATUS_SETTLED:
        return jsonify({'error': 'invalid_state',
                        'detail': u'zlecenie rozliczone — cofnij rozliczenie'}), 409

    payload = request.get_json(silent=True) or {}
    before = {'declared_volume_m3': str(order.declared_volume_m3),
              'price_per_m3': str(order.price_per_m3)}
    try:
        if 'declared_volume_m3' in payload:
            # Symetrycznie do delivery_create: deklaracja niedodatnia (0 albo
            # ujemna) nigdy nie trafia do bazy. Zero w declared_volume_m3
            # wywraca dzielenie w compute_differences() — a ta funkcja liczy
            # się przy KAŻDYM odczycie listy zleceń (_panel_payload w
            # orders_list), więc jeden taki wiersz kładłby odczyt WSZYSTKICH
            # zleceń, nie tylko tego edytowanego.
            declared = _decimal(payload['declared_volume_m3'], 'declared_volume_m3')
            if declared <= 0:
                raise PanelValidationError('declared_volume_m3', u'wartość musi być dodatnia')
            order.declared_volume_m3 = declared
        if 'price_per_m3' in payload:
            order.price_per_m3 = _decimal(payload['price_per_m3'], 'price_per_m3',
                                          required=False)
        if 'declared_logs_count' in payload:
            order.declared_logs_count = payload['declared_logs_count'] or None
        if 'species_id' in payload:
            order.species_id = payload['species_id']
        if 'notes' in payload:
            order.notes = payload['notes'] or None
    except PanelValidationError as exc:
        db.session.rollback()
        return _fail(exc)

    order.declared_value = (order.declared_volume_m3 * order.price_per_m3
                            if order.price_per_m3 is not None else None)
    write_audit(order.id, 'order_update', before=before, user_id=_current_user_id(),
                after={'declared_volume_m3': str(order.declared_volume_m3),
                       'price_per_m3': str(order.price_per_m3)})
    db.session.commit()
    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    return jsonify({'order': _panel_payload(order, threshold)})


@sawmill_panel_bp.route('/orders/<int:order_id>', methods=['DELETE'])
@guard
def order_delete(order_id):
    """
    Warunek liczy WSZYSTKIE wiersze, także is_deleted=1. To jedyne miejsce
    w module, gdzie soft-delete nie jest pomijany — inaczej zlecenie
    z dwudziestoma skasowanymi kłodami dałoby się usunąć razem z audytem.
    """
    order = db.session.query(SawmillOrder).get(order_id)
    if order is None:
        return jsonify({'error': 'not_found'}), 404
    if SawmillLog.query.filter_by(order_id=order_id).count() > 0:
        return jsonify({'error': 'has_logs',
                        'detail': u'zlecenie ma zapisane pomiary'}), 409

    write_audit(order.id, 'order_delete', user_id=_current_user_id())
    db.session.delete(order)
    db.session.commit()
    return jsonify({'ok': True})


# ── Eksporty ────────────────────────────────────────────────────────────────

@sawmill_panel_bp.route('/export.xlsx', methods=['GET'])
@guard
def export_xlsx():
    """
    Eksportuje DOKŁADNIE to, co widać w tabeli po zastosowaniu filtrów —
    woła `orders_list()` WPROST, w tym samym żądaniu, więc parsowanie
    `request.args` (status/dostawca/gatunek/zakres dat/wyszukiwarka/
    only_deviation) nie jest duplikowane tutaj drugi raz.
    """
    from modules.production.sawmill.services.exports import build_orders_xlsx

    payload = orders_list().get_json()['orders']
    resp = make_response(build_orders_xlsx(payload))
    resp.headers['Content-Type'] = \
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = 'attachment; filename=trakownia.xlsx'
    return resp


@sawmill_panel_bp.route('/orders/<int:order_id>/protocol.pdf', methods=['GET'])
@guard
def order_protocol_pdf(order_id):
    """
    Protokół pomiaru — samodzielny dokument (CSS inline w szablonie, patrz
    `templates/sawmill/protocol_pdf.html`), załącznik do ewentualnej
    reklamacji u dostawcy. `weasyprint` importowany leniwie — koszt importu
    ponoszą wyłącznie żądania tego endpointu.
    """
    from weasyprint import HTML

    from modules.production.sawmill.services.exports import build_protocol_context

    order = _order_query().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return jsonify({'error': 'not_found'}), 404

    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    count, volume = order_totals(order.id)
    logs = (SawmillLog.query.filter_by(order_id=order_id, is_deleted=False)
            .order_by(SawmillLog.sequence_no).all())

    html = render_template('sawmill/protocol_pdf.html', **build_protocol_context(
        order, order.delivery, logs, count, volume,
        compute_differences(order, volume, threshold)))

    resp = make_response(HTML(string=html).write_pdf())
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = 'inline; filename={}.pdf'.format(
        order.order_number.replace('/', '-'))
    return resp


# ── Pomiary z panelu ────────────────────────────────────────────────────────

@sawmill_panel_bp.route('/orders/<int:order_id>/logs', methods=['POST'])
@guard
def order_add_log_manual(order_id):
    """Ścieżka awaryjna, gdy tablet padł albo kolejka została wyczyszczona."""
    order = _order_query().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return jsonify({'error': 'not_found'}), 404

    payload = request.get_json(silent=True) or {}
    try:
        measurements = validate_measurements(payload, get_sawmill_settings())
        measured_at = parse_measured_at(payload.get('measured_at'))
    except SawmillValidationError as exc:
        return jsonify({'error': 'validation_error',
                        'field': exc.field, 'detail': exc.detail}), 422

    try:
        log = add_log(order, measurements, measured_at,
                      user_id=_current_user_id(), manual=True)
    except SawmillStateError as exc:
        db.session.rollback()
        return _state_error(exc)

    db.session.commit()
    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    return jsonify({'log': serialize_log_for_panel(log),
                    'order': _panel_payload(order, threshold)}), 201


@sawmill_panel_bp.route('/logs/<int:log_id>', methods=['PATCH'])
@guard
def panel_update_log(log_id):
    log = db.session.query(SawmillLog).get(log_id)
    if log is None or log.is_deleted:
        return jsonify({'error': 'not_found'}), 404

    payload = request.get_json(silent=True) or {}
    try:
        measurements = validate_measurements(payload, get_sawmill_settings())
    except SawmillValidationError as exc:
        return jsonify({'error': 'validation_error',
                        'field': exc.field, 'detail': exc.detail}), 422
    try:
        update_log(log, measurements, user_id=_current_user_id())
    except SawmillStateError as exc:
        db.session.rollback()
        return _state_error(exc)

    db.session.commit()
    return jsonify({'log': serialize_log_for_panel(log)})


@sawmill_panel_bp.route('/logs/<int:log_id>', methods=['DELETE'])
@guard
def panel_delete_log(log_id):
    log = db.session.query(SawmillLog).get(log_id)
    if log is None or log.is_deleted:
        return jsonify({'error': 'not_found'}), 404
    try:
        delete_log(log, user_id=_current_user_id())
    except SawmillStateError as exc:
        db.session.rollback()
        return _state_error(exc)
    db.session.commit()
    return jsonify({'ok': True})


# ── Akcje na zleceniu ───────────────────────────────────────────────────────

def _action(order_id, action_fn):
    """
    `action_fn` to callable przyjmujący WYŁĄCZNIE `order` (funkcje serwisowe
    domyka się w miejscu wywołania przez lambda z argumentami nazwanymi).

    Referencyjny kod z briefu miał sygnaturę `_action(order_id, fn, *args)`
    i wołał `fn(order, *args)` — dla `settle_order(order, agreed_volume_m3,
    notes, user_id)` trzy pozycyjne argumenty w *args muszą trafić w idealnie
    tej kolejności, inaczej `notes` i `user_id` (oba akceptują None i string/
    int bez żadnej weryfikacji typu w czasie wykonania) po cichu zamieniłyby
    się miejscami — literówka w kolejności argumentów w wywołaniu `_action(...)`
    nie dałaby żadnego błędu, tylko zapisała złe dane. Domykanie w lambdzie
    z jawnymi słowami kluczowymi (`agreed_volume_m3=...`, `notes=...`,
    `user_id=...`) sprawia, że pomyłka kolejności staje się z miejsca
    widoczna w diffie i przy każdej zmianie sygnatury funkcji serwisowej
    wywali się głośno (TypeError), zamiast po cichu przestawić wartości.
    """
    order = _order_query().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return jsonify({'error': 'not_found'}), 404
    try:
        action_fn(order)
    except SawmillStateError as exc:
        db.session.rollback()
        return _state_error(exc)
    db.session.commit()
    threshold = get_sawmill_settings().get('deviation_threshold_pct', 5.0)
    return jsonify({'order': _panel_payload(order, threshold)})


@sawmill_panel_bp.route('/orders/<int:order_id>/reopen', methods=['POST'])
@guard
def order_reopen(order_id):
    return _action(order_id, lambda order: reopen_order(order, user_id=_current_user_id()))


@sawmill_panel_bp.route('/orders/<int:order_id>/settle', methods=['POST'])
@guard
def order_settle(order_id):
    payload = request.get_json(silent=True) or {}
    notes = payload.get('settlement_notes') or None
    try:
        # _decimal (istniejący helper) zamiast surowego Decimal(str(...)) z
        # briefu — wpisanie w agreed_volume_m3 wartości nie będącej liczbą
        # (np. literówki z panelu) rzucało tam InvalidOperation, które nie
        # jest nigdzie łapane → 500 zamiast czytelnego 422.
        agreed = _decimal(payload.get('agreed_volume_m3'), 'agreed_volume_m3',
                          required=False)
    except PanelValidationError as exc:
        return _fail(exc)
    return _action(order_id, lambda order: settle_order(
        order, agreed_volume_m3=agreed, notes=notes, user_id=_current_user_id()))


@sawmill_panel_bp.route('/orders/<int:order_id>/unsettle', methods=['POST'])
@guard
def order_unsettle(order_id):
    return _action(order_id, lambda order: unsettle_order(order, user_id=_current_user_id()))


# ── Statystyki kafelka ──────────────────────────────────────────────────────

@sawmill_panel_bp.route('/dashboard-stats', methods=['GET'])
@guard
def dashboard_stats():
    """
    „Dziś" liczone po measured_at, nie created_at — patrz docstring
    `sawmill_dashboard_stats` w services/exports.py.
    """
    from modules.production.sawmill.services.exports import sawmill_dashboard_stats
    return jsonify(sawmill_dashboard_stats())


# ── Ustawienia ──────────────────────────────────────────────────────────────

@sawmill_panel_bp.route('/settings', methods=['GET'])
@guard
def settings_read():
    return jsonify({'settings': get_sawmill_settings()})


@sawmill_panel_bp.route('/settings', methods=['PATCH'])
@guard
def settings_write():
    """
    Zapisuje wyłącznie klucze z EDITABLE_KEYS. decimal_places jest stałą
    zgodną ze schematem DECIMAL(x,1) i nie da się go zmienić tą drogą —
    zmiana precyzji wymaga ALTER TABLE.
    """
    payload = request.get_json(silent=True) or {}
    try:
        settings = save_sawmill_settings(payload, user_id=_current_user_id())
    except (TypeError, ValueError):
        db.session.rollback()
        return _fail(PanelValidationError('settings', u'wartości muszą być liczbami'))
    db.session.commit()
    return jsonify({'settings': settings})
