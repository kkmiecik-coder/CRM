# -*- coding: utf-8 -*-
"""
API zakładki Logistyka — /production/api/logistics/*

Kontrola dostępu jak w Trakowni (sawmill/routers/panel_api.py:53, tam pełne
uzasadnienie kolejności i leniwego odwołania do dekoratora).
"""
from functools import wraps

from flask import jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp, sposoby
from modules.production.logistics.services import bl_sync, delivery, lista
from modules.production.models import ProductionOrder

logger = get_structured_logger('production.logistics.panel_api')
LIMIT_HURTU = 500


def guard(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(
            login_required(f))
        return checked(*args, **kwargs)
    return wrapped


def _user_id():
    return getattr(current_user, 'id', None)


def _blad(komunikat, status):
    return jsonify({'success': False, 'error': komunikat}), status


@logistics_panel_bp.route('/tab-content', methods=['GET'])
@guard
def tab_content():
    return render_template('logistics/tab_content.html')


@logistics_panel_bp.route('/orders', methods=['GET'])
@guard
def orders():
    zamkniete = request.args.get('zamkniete') == '1'
    q = (request.args.get('q') or '').strip() or None
    if zamkniete and not q:
        return _blad(u'Wyszukiwanie zamkniętych zamówień wymaga frazy.', 422)
    wstrzymane = bl_sync.wstrzymane_do()
    return jsonify({
        'success': True,
        'orders': lista.pobierz(sposob=request.args.get('sposob') or None,
                                etap=request.args.get('etap') or None,
                                q=q, zamkniete=zamkniete),
        'liczniki': lista.liczniki(),
        'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
    })


@logistics_panel_bp.route('/orders/delivery-method', methods=['POST'])
@guard
def delivery_method():
    dane = request.get_json(silent=True) or {}
    if not isinstance(dane, dict):
        # Tablica albo skalar w ciele JSON — bez tego .get() rzuca AttributeError (500).
        return _blad(u'Nieprawidłowe dane żądania.', 422)
    ids = dane.get('order_ids')
    sposob = sposoby.normalizuj(dane.get('sposob'))
    if not isinstance(ids, list) or not ids or len(ids) > LIMIT_HURTU:
        return _blad(u'Podaj od 1 do {} zamówień.'.format(LIMIT_HURTU), 422)
    # bool jest podklasą int w Pythonie — bez wyłączenia [True] przeszłoby jako id=1.
    # Bez tej walidacji element inny niż int (np. dict, string) trafia surowy do
    # ProductionOrder.id.in_(ids) i SQLAlchemy rzuca ProgrammingError z bazy (500,
    # szum w Sentry) zamiast czystego 422 tego endpointu dla złych danych wejściowych.
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        return _blad(u'Identyfikatory zamówień muszą być liczbami całkowitymi.', 422)
    if sposob is None:
        return _blad(u'Nieznany sposób dostawy.', 422)

    zmienione, przepakowanie, bledy = [], [], []
    # selectinload: pozycje wszystkich zamówień jednym zapytaniem, nie zamówienie
    # po zamówieniu (hurt do LIMIT_HURTU zamówień, a pozycji potrzebuje każda zmiana).
    for order in (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).all()):
        try:
            wynik = delivery.ustaw_sposob_dostawy(order, sposob, user_id=_user_id())
        except delivery.LogistykaBlad as e:
            bledy.append({'order_id': order.id, 'komunikat': e.komunikat})
            continue
        if wynik['zmieniono']:
            zmienione.append(order.id)
        if wynik['przepakowanie']:
            przepakowanie.append(order.id)
    db.session.commit()
    logger.info("Logistyka: zmiana sposobu dostawy", extra={
        'user_id': _user_id(), 'sposob': sposob, 'zmienione': len(zmienione),
        'bledy': len(bledy)})

    bl_sync.po_zmianie(zmienione)
    odswiezone = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).all())
    return jsonify({'success': True, 'zmienione': zmienione, 'przepakowanie': przepakowanie,
                    'bledy': bledy, 'orders': [lista.serializuj(o) for o in odswiezone]})


@logistics_panel_bp.route('/orders/<int:order_id>/handed-over', methods=['POST'])
@guard
def handed_over(order_id):
    order = ProductionOrder.query.get(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    try:
        delivery.wydaj_klientowi(order, user_id=_user_id())
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    bl_sync.po_zmianie([order.id])
    return jsonify({'success': True, 'order': lista.serializuj(ProductionOrder.query.get(order_id))})
