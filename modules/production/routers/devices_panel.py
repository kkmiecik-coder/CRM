# -*- coding: utf-8 -*-
"""
Zakładka „Urządzenia mobilne” — /production/api/devices/* (spec 2026-10-12-urzadzenia-mobilne-zatwierdzanie-design.md,
sekcja 5): prośby o dostęp, urządzenia, zablokowane i wydania APK (przeniesione z Ustawień).

Cienki router: walidacja ciała, commit, mapowanie `BladPanelu` na {"success": false, "error", "message"}. Logika:
services/device_access_service.py (dostęp) i services/mobile_api_service.py (wydania APK). Cała zakładka tylko dla
admina: `guard` (login + moduł production) i `admin_required`, oba leniwe, w chwili żądania — wzór i powód:
priorytety/routers/panel_api.py.
"""
from functools import wraps

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.services import device_access_service as dostep

# Szablony leżą w modules/production/templates (components/devices-tab-content.html).
devices_panel_bp = Blueprint('devices_panel', __name__, template_folder='../templates')
logger = get_structured_logger('production.devices_panel')

KOMUNIKAT_BLAD_SERWERA = 'Nie udało się zapisać zmian. Spróbuj ponownie za chwilę.'


def guard(f):
    """Login + dostęp do modułu `production`; brak sesji → 401 JSON, brak modułu → 403 JSON."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(login_required(f))
        return checked(*args, **kwargs)
    return wrapped


def admin_required(f):
    """`common_api.admin_required` (403 JSON) wołany leniwie — import na górze modułu robiłby cykl importów."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        from modules.production.routers.api.common_api import admin_required as admin_common
        return admin_common(f)(*args, **kwargs)
    return wrapped


def _user_id():
    """Id zalogowanego — czytać PRZED commitem (commit wygasza atrybuty ORM)."""
    return getattr(current_user, 'id', None)


def _akcja(funkcja, *args):
    """Akcja serwisu + commit. `BladPanelu` → odpowiedź z kodem; inny wyjątek → 500 z rollbackiem, treść tylko w logu."""
    try:
        wynik = funkcja(*args)
        db.session.commit()
    except dostep.BladPanelu as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': e.kod, 'message': e.komunikat}), e.status
    except Exception as e:
        db.session.rollback()
        logger.error('Urządzenia: akcja panelu nie powiodła się', extra={'akcja': funkcja.__name__, 'error': str(e)})
        return jsonify({'success': False, 'error': 'blad_serwera', 'message': KOMUNIKAT_BLAD_SERWERA}), 500
    tresc = {'success': True}
    if isinstance(wynik, dict):
        tresc.update(wynik)
    return jsonify(tresc), 200


def _cialo():
    cialo = request.get_json(silent=True)
    return cialo if isinstance(cialo, dict) else {}


# ── zakładka i lista ──────────────────────────────────────────────────────────────────────────────────────────────

@devices_panel_bp.route('/tab-content')
@guard
@admin_required
def tab_content():
    """Gotowy HTML zakładki (jak Pracownicy) — loader wstawia go przez innerHTML i odpala skrypty inline."""
    return render_template('components/devices-tab-content.html',
                           dane=dostep.lista_dla_panelu(), wydania=dostep.wydania_z_liczbami())


@devices_panel_bp.route('/lista')
@guard
@admin_required
def lista():
    return jsonify({'success': True, **dostep.lista_dla_panelu()})


# ── akcje na urządzeniu ───────────────────────────────────────────────────────────────────────────────────────────

@devices_panel_bp.route('/<int:pk>/zatwierdz', methods=['POST'])
@guard
@admin_required
def zatwierdz(pk):
    return _akcja(dostep.zatwierdz, pk, _cialo().get('nazwa'), _user_id())


@devices_panel_bp.route('/<int:pk>/odrzuc', methods=['POST'])
@guard
@admin_required
def odrzuc(pk):
    return _akcja(dostep.odrzuc, pk, _user_id())


@devices_panel_bp.route('/<int:pk>/zablokuj', methods=['POST'])
@guard
@admin_required
def zablokuj(pk):
    return _akcja(dostep.zablokuj, pk, _user_id())


@devices_panel_bp.route('/<int:pk>/odblokuj', methods=['POST'])
@guard
@admin_required
def odblokuj(pk):
    return _akcja(dostep.odblokuj, pk, _user_id())


@devices_panel_bp.route('/<int:pk>/nazwa', methods=['PATCH'])
@guard
@admin_required
def nazwa(pk):
    return _akcja(dostep.zmien_nazwe, pk, _cialo().get('nazwa'))


@devices_panel_bp.route('/<int:pk>/przyjmij-mac', methods=['POST'])
@guard
@admin_required
def przyjmij_mac(pk):
    return _akcja(dostep.przyjmij_mac, pk)


@devices_panel_bp.route('/bez-mac')
@guard
@admin_required
def bez_mac():
    return jsonify({'success': True, **dostep.podglad_bez_mac()})


@devices_panel_bp.route('/zablokuj-bez-mac', methods=['POST'])
@guard
@admin_required
def zablokuj_bez_mac():
    ids = _cialo().get('ids')
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return jsonify({'success': False, 'error': 'ids_niepoprawne',
                        'message': 'Lista urządzeń do blokady jest niepoprawna — otwórz podgląd ponownie.'}), 400
    return _akcja(dostep.zablokuj_bez_mac, ids, _user_id())


# ── wydania APK (dawniej /settings/api/mobile-releases/*) ─────────────────────────────────────────────────────────

@devices_panel_bp.route('/releases', methods=['POST'])
@guard
@admin_required
def release_upload():
    """
    Upload nowego APK + rejestracja release'u. Release powstaje NIEAKTYWNY, chyba że formularz przyśle `activate=1`
    („Aktywuj od razu”). Format odpowiedzi jak w dawnych Ustawieniach — skrypt uploadu czyta pole `error`.
    """
    from modules.production.services.mobile_api_service import flaga_aktywacji, register_release

    apk_file = request.files.get('apk')
    if apk_file is None:
        return jsonify({'success': False, 'error': 'Brak pliku APK'}), 400

    version_code_raw = request.form.get('version_code', '').strip()
    version_name = request.form.get('version_name', '').strip()
    release_notes = request.form.get('release_notes', '').strip()
    activate = flaga_aktywacji(request.form.get('activate'))

    if not version_code_raw:
        return jsonify({'success': False, 'error': 'Pole `version_code` jest wymagane (z build.gradle.kts)'}), 400
    try:
        version_code = int(version_code_raw)
    except ValueError:
        return jsonify({'success': False,
                        'error': f'Pole `version_code` musi być liczbą całkowitą (otrzymano: {version_code_raw!r})'}), 400
    if version_code <= 0:
        return jsonify({'success': False, 'error': 'Pole `version_code` musi być większe od 0'}), 400
    if not version_name:
        return jsonify({'success': False, 'error': 'Pole `version_name` jest wymagane (z build.gradle.kts)'}), 400
    if len(version_name) > 32:
        return jsonify({'success': False, 'error': 'Pole `version_name` może mieć maksymalnie 32 znaki'}), 400

    try:
        release = register_release(file_storage=apk_file, version_code=version_code, version_name=version_name,
                                   release_notes=release_notes, user_id=_user_id(), activate=activate)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('Urządzenia: upload APK nie powiódł się', extra={'error': str(e)})
        return jsonify({'success': False, 'error': KOMUNIKAT_BLAD_SERWERA}), 500

    return jsonify({'success': True, 'release': {
        'id': release.id, 'version_code': release.version_code, 'version_name': release.version_name,
        'sha256': release.sha256, 'file_size_bytes': release.file_size_bytes, 'is_active': release.is_active,
    }}), 201


@devices_panel_bp.route('/releases/<int:release_id>/active', methods=['PATCH'])
@guard
@admin_required
def release_toggle_active(release_id):
    from modules.production.services.mobile_api_service import set_release_active

    data = _cialo()
    if 'is_active' not in data or not isinstance(data['is_active'], bool):
        return jsonify({'success': False, 'error': 'Wymagane pole boolean `is_active` w body JSON'}), 400
    try:
        release = set_release_active(release_id, data['is_active'])
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error('Urządzenia: przełącznik release nie powiódł się', extra={'error': str(e)})
        return jsonify({'success': False, 'error': KOMUNIKAT_BLAD_SERWERA}), 500
    return jsonify({'success': True, 'release': {
        'id': release.id, 'version_code': release.version_code, 'is_active': release.is_active}}), 200
