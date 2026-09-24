# -*- coding: utf-8 -*-
"""
Cron logistyki — co godzinę z crontaba serwera:
    scripts/cron_endpoint.sh POST /production/api/logistics/cron

Endpoint NIE wykonuje długiej pracy: sync worker gunicorna ma 30 s na żądanie.
Przelicza cykl zamówień (szybkie, w bazie) i uruchamia dopychacz Base. w tle.
Etap 2 dołoży tu uruchomienie geokodowania w tle.
"""
import traceback

from flask import current_app, jsonify

from cron_auth import cron_secret_required
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.services import bl_sync, delivery

logger = get_structured_logger('production.logistics.cron')


@logistics_panel_bp.route('/cron', methods=['POST'])
@cron_secret_required
def cron():
    """
    Przelicza cykl logistyki zamówień i uruchamia dopychacz Base. w tle.
    """
    try:
        przeliczone = delivery.przelicz_otwarte()
        db.session.commit()
        uruchomiony = bl_sync.uruchom_w_tle(current_app._get_current_object())
        wstrzymane = bl_sync.wstrzymane_do()
        return jsonify({
            'success': True,
            'przeliczone': przeliczone,
            'dopychacz_uruchomiony': bool(uruchomiony),
            'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
        })
    except Exception as e:
        db.session.rollback()
        logger.error('CRON: błąd przeliczania logistyki', extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return jsonify({'success': False, 'error': str(e)}), 500
