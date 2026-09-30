# -*- coding: utf-8 -*-
"""
Cron logistyki — co godzinę z crontaba serwera:
    scripts/cron_endpoint.sh POST /production/api/logistics/cron

Endpoint NIE wykonuje długiej pracy: sync worker gunicorna ma 30 s na żądanie.
Przenosi osierocone `czeka_na_logistyke` do pakowania, raz (znacznik w prod_config) przestawia
pozycje już wydanych zamówień na `dostarczone` (okno wdrożenia kroku 4.3), przelicza cykl zamówień
(szybkie, w bazie) i uruchamia w tle dopychacz Base. oraz geokoder adresów.
"""
import traceback

from flask import current_app, jsonify

from cron_auth import cron_secret_required
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.services import bl_sync, delivery, geocoding

logger = get_structured_logger('production.logistics.cron')


@logistics_panel_bp.route('/cron', methods=['POST'])
@cron_secret_required
def cron():
    """
    Przelicza cykl logistyki zamówień i uruchamia w tle dopychacz Base. oraz geokoder adresów.
    """
    try:
        # Najpierw produkty zapisane przez stary kod w oknie wdrożenia (patrz
        # delivery.przenies_osierocone_z_logistyki) — przelicz_otwarte widzi je już
        # w pakowaniu.
        przeniesione = delivery.przenies_osierocone_z_logistyki()
        if przeniesione:
            logger.warning('CRON: produkty w czeka_na_logistyke przeniesione do pakowania', extra={
                'przeniesione': przeniesione})
        # Okno wdrożenia kroku 4.3: pozycje już wydanych odbiorów osobistych przestawiamy na
        # 'dostarczone' dopiero po restarcie (migracja tego nie robi — stary kod nie zna wartości
        # ENUM, patrz delivery.dostarcz_wydane). JEDNORAZOWO: po pierwszym udanym przebiegu w
        # prod_config zostaje znacznik `logistyka_wydane_dostarczone` i kolejne przebiegi zwracają 0
        # bez pytania o pozycje — inaczej co godzinę przestawialibyśmy na 'dostarczone' pozycje wydanego
        # zamówienia, które wróciły z doróbki i są znów spakowane, choć klient ich nie odebrał.
        wydane_dostarczone = delivery.dostarcz_wydane()
        if wydane_dostarczone:
            logger.info('CRON: pozycje wydanych zamówień przestawione na dostarczone', extra={
                'pozycje': wydane_dostarczone})
        przeliczone = delivery.przelicz_otwarte()
        db.session.commit()
        uruchomiony = bl_sync.uruchom_w_tle(current_app._get_current_object())
        geokoder = geocoding.uruchom_w_tle(current_app._get_current_object())
        wstrzymane = bl_sync.wstrzymane_do()
        return jsonify({
            'success': True,
            'przeniesione_z_logistyki': przeniesione,
            'wydane_dostarczone': wydane_dostarczone,
            'przeliczone': przeliczone,
            'dopychacz_uruchomiony': bool(uruchomiony),
            'geokoder_uruchomiony': bool(geokoder),
            'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
        })
    except Exception as e:
        db.session.rollback()
        logger.error('CRON: błąd przeliczania logistyki', extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return jsonify({'success': False, 'error': str(e)}), 500
