# app/modules/users/routes.py
"""
Endpointy zarządzania użytkownikami
====================================

Wszystkie trasy związane z użytkownikami (bez login/logout - te zostają w app.py).

Endpointy:
- GET  /users/settings - ustawienia użytkownika i zarządzanie zespołem
- POST /users/invite - wysłanie zaproszenia
- POST /users/update-password - zmiana hasła
- POST /users/update-avatar - zmiana avatara
- POST /users/<id>/edit - edycja użytkownika
- POST /users/<id>/activate - aktywacja użytkownika
- POST /users/<id>/deactivate - dezaktywacja użytkownika
- POST /users/<id>/delete - usunięcie użytkownika

Autor: Konrad Kmiecik
Data: 2025-01-10
Aktualizacja: 2025-01-13 - Migracja do nowego systemu uprawnień
"""

from flask import render_template, request, redirect, url_for, flash, session, current_app, jsonify
import os
from werkzeug.utils import secure_filename

from . import users_bp
from .models import User, UserPermission, Module, Role, RolePermission  # ← DODAJ Role, RolePermission
from .decorators import access_control, require_module_access
from .services.user_service import UserService
from .services.invitation_service import InvitationService
from .services.permission_service import PermissionService
from .services.role_service import RoleService
from .services.audit_service import AuditService
from extensions import db


# ============================================================================
# SETTINGS - Ustawienia użytkownika i zarządzanie zespołem
# ============================================================================

@users_bp.route('/settings', methods=['GET', 'POST'])
@access_control(allow_all=True)
def settings():
    """
    Strona ustawień użytkownika - dostępna dla WSZYSTKICH
    - Profil (imię, nazwisko, avatar)
    - Zmiana hasła
    - Informacje o koncie
    """
    from datetime import datetime
    
    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()
    
    if not current_user:
        flash("Błąd sesji. Zaloguj się ponownie.", "error")
        return redirect(url_for('login'))
    
    # Pobierz dane użytkownika
    user_name = current_user.get_full_name()
    user_avatar = current_user.avatar_path or url_for('static', filename='images/avatars/default_avatars/avatar1.svg')
    
    # Oblicz czas członkostwa od created_at
    member_since = "kilku dni"  # Domyślna wartość
    if current_user.created_at:
        try:
            now = datetime.utcnow()
            delta = now - current_user.created_at
            
            # Oblicz lata, miesiące, dni
            years = delta.days // 365
            months = (delta.days % 365) // 30
            days = delta.days % 30
            
            # Formatuj ładnie po polsku
            if years > 0:
                if years == 1:
                    member_since = "1 roku"
                elif years < 5:
                    member_since = f"{years} lat"
                else:
                    member_since = f"{years} lat"
            elif months > 0:
                if months == 1:
                    member_since = "1 miesiąca"
                elif months < 5:
                    member_since = f"{months} miesięcy"
                else:
                    member_since = f"{months} miesięcy"
            else:
                if days == 1:
                    member_since = "1 dnia"
                else:
                    member_since = f"{days} dni"
        except Exception as e:
            current_app.logger.error(f"Błąd obliczania member_since: {str(e)}")
            member_since = "pewnego czasu"
    
    return render_template(
        'settings.html',
        user_email=user_email,
        user_name=user_name,
        user_avatar=user_avatar,
        current_user=current_user,
        member_since=member_since
    )

# ============================================================================
# PROFILE - Aktualizacja profilu (imię, nazwisko)
# ============================================================================

@users_bp.route('/update-profile', methods=['POST'])
@access_control(allow_all=True)
def update_profile():
    """Aktualizacja danych profilu użytkownika (imię, nazwisko)"""
    try:
        user_email = session.get('user_email')
        current_user = User.query.filter_by(email=user_email).first()
        
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        
        # Aktualizuj dane
        UserService.update_user(
            current_user.id,
            first_name=first_name,
            last_name=last_name
        )
        
        flash("Dane profilu zostały zaktualizowane.", "success")
        
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        current_app.logger.error(f"Błąd aktualizacji profilu: {str(e)}")
        flash("Wystąpił błąd podczas aktualizacji profilu.", "error")
    
    return redirect(url_for('users.settings'))

@users_bp.route('/manage', methods=['GET'])
@require_module_access('users')
def manage_users():
    """
    Zarządzanie zespołem - tylko dla użytkowników z dostępem do modułu 'users'
    Lista użytkowników + zaproszenia
    """
    from modules.calculator.models import Multiplier
    
    users_list = UserService.get_all_users()
    multipliers = Multiplier.query.all()
    
    return render_template(
        'users-management.html',
        users_list=users_list,
        multipliers=multipliers
    )

# ============================================================================
# INVITATION - Zapraszanie użytkowników
# ============================================================================

@users_bp.route('/invite', methods=['POST'])
@require_module_access('users')
def invite_user():
    """Wysyła zaproszenie dla nowego użytkownika"""
    try:
        invite_email = request.form.get('invite_email')
        invite_role = request.form.get('invite_role', 'user')
        invite_multiplier = request.form.get('invite_multiplier')
        
        if not invite_email:
            flash("Adres email jest wymagany.", "error")
            return redirect(url_for('users.manage_users'))
        
        # Multiplier tylko dla partnerów
        multiplier_id = int(invite_multiplier) if invite_role == "partner" and invite_multiplier else None
        
        # Utwórz zaproszenie
        invitation = InvitationService.create_invitation(
            email=invite_email,
            role=invite_role,
            multiplier_id=multiplier_id
        )
        
        # Wyślij email
        if InvitationService.send_invitation_email(invitation):
            flash(f"Zaproszenie wysłane do {invite_email}", "success")
        else:
            flash(f"Zaproszenie utworzone, ale email nie został wysłany. Sprawdź konfigurację SMTP.", "warning")
        
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        current_app.logger.error(f"Błąd wysyłania zaproszenia: {str(e)}")
        flash("Wystąpił błąd podczas wysyłania zaproszenia.", "error")
    
    return redirect(url_for('users.manage_users'))


# ============================================================================
# PASSWORD - Zmiana hasła
# ============================================================================

@users_bp.route('/update-password', methods=['POST'])
@access_control(allow_all=True)
def update_password():
    """Zmiana hasła użytkownika"""
    try:
        user_email = session.get('user_email')
        current_user = User.query.filter_by(email=user_email).first()
        
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Walidacja
        if not all([old_password, new_password, confirm_password]):
            flash("Wszystkie pola są wymagane.", "error")
            return redirect(url_for('users.settings'))
        
        if new_password != confirm_password:
            flash("Nowe hasła muszą być identyczne.", "error")
            return redirect(url_for('users.settings'))
        
        # Zmień hasło
        UserService.update_password(current_user.id, old_password, new_password)
        flash("Hasło zostało zmienione.", "success")
        
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        current_app.logger.error(f"Błąd zmiany hasła: {str(e)}")
        flash("Wystąpił błąd podczas zmiany hasła.", "error")
    
    return redirect(url_for('users.settings'))


# ============================================================================
# AVATAR - Zmiana avatara
# ============================================================================

@users_bp.route('/update-avatar', methods=['POST'])
@access_control(allow_all=True)
def update_avatar():
    """Zmiana avatara użytkownika"""
    try:
        user_email = session.get('user_email')
        current_user = User.query.filter_by(email=user_email).first()
        
        # Sprawdź czy wybrano domyślny avatar
        default_avatar = request.form.get('default_avatar')
        
        if default_avatar:
            # Użyj domyślnego avatara
            avatar_path = default_avatar
        else:
            # Sprawdź czy wgrano plik
            avatar_file = request.files.get('avatar_file')
            
            if not avatar_file or avatar_file.filename == '':
                flash("Nie wybrano avatara.", "error")
                return redirect(url_for('users.settings'))
            
            # Zapisz plik
            from datetime import datetime
            filename = secure_filename(avatar_file.filename)
            timestamp = int(datetime.now().timestamp())
            filename = f"user_{current_user.id}_{timestamp}_{filename}"
            
            upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'avatars', 'custom')
            os.makedirs(upload_folder, exist_ok=True)
            
            filepath = os.path.join(upload_folder, filename)
            avatar_file.save(filepath)
            
            avatar_path = f"custom/{filename}"
        
        # Aktualizuj avatar
        UserService.update_avatar(current_user.id, avatar_path)
        flash("Avatar został zmieniony.", "success")
        
    except Exception as e:
        current_app.logger.error(f"Błąd zmiany avatara: {str(e)}")
        flash("Wystąpił błąd podczas zmiany avatara.", "error")
    
    return redirect(url_for('users.settings'))


# ============================================================================
# USER MANAGEMENT - Zarządzanie użytkownikami (tylko admin)
# ============================================================================

@users_bp.route('/<int:user_id>/edit', methods=['POST'])
@require_module_access('users')
def edit_user(user_id):
    """Edycja danych użytkownika"""
    try:
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role = request.form.get('role')
        email = request.form.get('email')
        
        # Aktualizuj użytkownika
        UserService.update_user(
            user_id,
            first_name=first_name,
            last_name=last_name,
            role=role,
            email=email
        )
        
        flash("Zaktualizowano dane użytkownika.", "success")
        
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        current_app.logger.error(f"Błąd edycji użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas edycji użytkownika.", "error")
    
    return redirect(url_for('users.manage_users'))


@users_bp.route('/<int:user_id>/activate', methods=['POST'])
@require_module_access('users')
def activate_user(user_id):
    """Aktywacja użytkownika"""
    try:
        UserService.activate_user(user_id)
        flash("Użytkownik został aktywowany.", "success")
    except Exception as e:
        current_app.logger.error(f"Błąd aktywacji użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas aktywacji użytkownika.", "error")
    
    return redirect(url_for('users.manage_users'))


@users_bp.route('/<int:user_id>/deactivate', methods=['POST'])
@require_module_access('users')
def deactivate_user(user_id):
    """Dezaktywacja użytkownika"""
    try:
        UserService.deactivate_user(user_id)
        flash("Użytkownik został dezaktywowany.", "info")
    except Exception as e:
        current_app.logger.error(f"Błąd dezaktywacji użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas dezaktywacji użytkownika.", "error")
    
    return redirect(url_for('users.manage_users'))


@users_bp.route('/<int:user_id>/delete', methods=['POST'])
@require_module_access('users')
def delete_user(user_id):
    """Usunięcie użytkownika"""
    try:
        # Usuń powiązane zaproszenia
        from .models import Invitation
        user = UserService.get_user_by_id(user_id)
        
        if user:
            Invitation.query.filter_by(email=user.email).delete()
            UserService.delete_user(user_id)
            flash("Użytkownik został usunięty.", "success")
        
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        current_app.logger.error(f"Błąd usuwania użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas usuwania użytkownika.", "error")
    
    return redirect(url_for('users.manage_users'))

@users_bp.route('/api/user-permissions/<int:user_id>', methods=['GET'])
@require_module_access('users')
def get_user_permissions_api(user_id):
    """
    API: Pobiera uprawnienia użytkownika
    
    GET /users/api/user-permissions/5
    
    Response:
    {
        "success": true,
        "user_id": 5,
        "email": "jan.kowalski@example.com",
        "role_id": 2,
        "role_name": "user",
        "modules": [
            {
                "module_id": 2,
                "module_key": "quotes",
                "display_name": "Wyceny",
                "has_access": true,
                "access_source": "role",
                "individual_override": null
            },
            ...
        ]
    }
    """
    try:
        result = PermissionService.get_user_permissions_details(user_id)
        
        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 404
        
        return jsonify({
            'success': True,
            **result
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_user_permissions: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@users_bp.route('/api/update-user-permissions', methods=['POST'])
@require_module_access('users')
def update_user_permissions_api():
    """
    API: Aktualizuje uprawnienia użytkownika
    
    POST /users/api/update-user-permissions
    
    Request Body:
    {
        "user_id": 5,
        "role_id": 2,
        "modules": {
            "2": "grant",      // quotes - nadaj
            "3": "revoke",     // production - odbierz
            "5": null          // clients - usuń nadpisanie (użyj roli)
        },
        "reason": "Projekt specjalny X"
    }
    
    Response:
    {
        "success": true,
        "message": "Uprawnienia zaktualizowane",
        "audit_log_ids": [123, 124],
        "changes": {
            "role_changed": false,
            "modules_granted": ["quotes"],
            "modules_revoked": ["production"],
            "modules_cleared": ["clients"]
        }
    }
    """
    try:
        data = request.get_json()
        
        # Walidacja
        if not data:
            return jsonify({
                'success': False,
                'error': 'Brak danych w request'
            }), 400
        
        user_id = data.get('user_id')
        new_role_id = data.get('role_id')
        modules = data.get('modules', {})
        reason = data.get('reason')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Brak user_id'
            }), 400
        
        # Pobierz użytkownika
        target_user = User.query.get(user_id)
        if not target_user:
            return jsonify({
                'success': False,
                'error': f'Użytkownik o ID {user_id} nie istnieje'
            }), 404
        
        # Pobierz ID zalogowanego admina
        admin_email = session.get('user_email')
        admin_user = User.query.filter_by(email=admin_email).first()
        admin_user_id = admin_user.id if admin_user else None
        
        audit_log_ids = []
        changes = {
            'role_changed': False,
            'modules_granted': [],
            'modules_revoked': [],
            'modules_cleared': []
        }
        
        # 1. Zmiana roli (jeśli podano)
        if new_role_id and new_role_id != target_user.role_id:
            old_role_id = target_user.role_id
            
            # Zaktualizuj rolę
            target_user.role_id = new_role_id
            
            # Zaktualizuj też stare pole role dla kompatybilności
            new_role = RoleService.get_role_by_id(new_role_id)
            if new_role:
                target_user.role = new_role.role_name
            
            db.session.commit()
            
            # Loguj zmianę
            log = AuditService.log_role_change(
                user_id=user_id,
                old_role_id=old_role_id,
                new_role_id=new_role_id,
                changed_by_user_id=admin_user_id,
                reason=reason
            )
            audit_log_ids.append(log.id)
            changes['role_changed'] = True
        
        # 2. Zmiany w modułach
        for module_id_str, access_type in modules.items():
            try:
                module_id = int(module_id_str)
                
                # Sprawdź czy moduł istnieje
                module = Module.query.get(module_id)
                if not module:
                    current_app.logger.warning(f"Moduł o ID {module_id} nie istnieje - pomijam")
                    continue
                
                # Pobierz istniejące nadpisanie
                existing = UserPermission.query.filter_by(
                    user_id=user_id,
                    module_id=module_id
                ).first()
                
                # NULL = usuń nadpisanie (użyj roli)
                if access_type is None or access_type == '':
                    if existing:
                        db.session.delete(existing)
                        changes['modules_cleared'].append(module.module_key)
                
                # "grant" = nadaj dostęp
                elif access_type == 'grant':
                    if existing:
                        # Aktualizuj istniejące
                        if existing.access_type != 'grant':
                            existing.access_type = 'grant'
                            existing.reason = reason
                            existing.created_by_user_id = admin_user_id
                    else:
                        # Utwórz nowe
                        new_perm = UserPermission(
                            user_id=user_id,
                            module_id=module_id,
                            access_type='grant',
                            reason=reason,
                            created_by_user_id=admin_user_id
                        )
                        db.session.add(new_perm)
                    
                    # Loguj
                    log = AuditService.log_module_grant(
                        user_id=user_id,
                        module_id=module_id,
                        changed_by_user_id=admin_user_id,
                        reason=reason
                    )
                    audit_log_ids.append(log.id)
                    changes['modules_granted'].append(module.module_key)
                
                # "revoke" = odbierz dostęp
                elif access_type == 'revoke':
                    if existing:
                        # Aktualizuj istniejące
                        if existing.access_type != 'revoke':
                            existing.access_type = 'revoke'
                            existing.reason = reason
                            existing.created_by_user_id = admin_user_id
                    else:
                        # Utwórz nowe
                        new_perm = UserPermission(
                            user_id=user_id,
                            module_id=module_id,
                            access_type='revoke',
                            reason=reason,
                            created_by_user_id=admin_user_id
                        )
                        db.session.add(new_perm)
                    
                    # Loguj
                    log = AuditService.log_module_revoke(
                        user_id=user_id,
                        module_id=module_id,
                        changed_by_user_id=admin_user_id,
                        reason=reason
                    )
                    audit_log_ids.append(log.id)
                    changes['modules_revoked'].append(module.module_key)
            
            except (ValueError, TypeError) as e:
                current_app.logger.warning(f"Błąd parsowania module_id '{module_id_str}': {e}")
                continue
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Uprawnienia zaktualizowane pomyślnie',
            'audit_log_ids': audit_log_ids,
            'changes': changes
        })
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Błąd API update_user_permissions: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@users_bp.route('/api/audit-log', methods=['GET'])
@require_module_access('users')
def get_audit_log_api():
    """
    API: Pobiera audit log z filtrami
    
    GET /users/api/audit-log?user_id=5&change_type=module_granted&limit=20&offset=0
    
    Query params:
    - user_id (int): Filtruj po użytkowniku
    - change_type (str): role_changed, module_granted, module_revoked
    - date_from (str): ISO format (2025-01-01T00:00:00)
    - date_to (str): ISO format
    - limit (int): Domyślnie 50
    - offset (int): Domyślnie 0
    
    Response:
    {
        "success": true,
        "total": 150,
        "logs": [...],
        "has_more": true,
        "limit": 50,
        "offset": 0
    }
    """
    try:
        from datetime import datetime
        
        # Parsuj parametry
        user_id = request.args.get('user_id', type=int)
        change_type = request.args.get('change_type', type=str)
        date_from_str = request.args.get('date_from', type=str)
        date_to_str = request.args.get('date_to', type=str)
        limit = request.args.get('limit', default=20, type=int)
        offset = request.args.get('offset', default=0, type=int)
        
        # Parsuj daty
        date_from = None
        date_to = None
        
        if date_from_str:
            try:
                date_from = datetime.fromisoformat(date_from_str.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if date_to_str:
            try:
                date_to = datetime.fromisoformat(date_to_str.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # Pobierz logi
        result = AuditService.get_audit_log(
            user_id=user_id,
            change_type=change_type,
            date_from=date_from,
            date_to=date_to,
            limit=min(limit, 20),
            offset=offset
        )
        
        return jsonify({
            'success': True,
            **result
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_audit_log: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@users_bp.route('/api/modules', methods=['GET'])
@require_module_access('users')
def get_modules_api():
    """
    API: Pobiera wszystkie moduły
    
    GET /users/api/modules
    
    Response:
    {
        "success": true,
        "modules": [
            {
                "id": 1,
                "module_key": "dashboard",
                "display_name": "Dashboard",
                "icon": "🏠",
                "access_type": "public"
            },
            ...
        ]
    }
    """
    try:
        modules = Module.query.filter_by(is_active=True).order_by(Module.sort_order).all()
        
        modules_data = [m.to_dict() for m in modules]
        
        return jsonify({
            'success': True,
            'modules': modules_data
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_modules: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@users_bp.route('/api/role-permissions/<int:role_id>', methods=['GET'])
@require_module_access('users')
def get_role_permissions_api(role_id):
    """
    API: Pobiera listę module_id dla danej roli
    
    GET /users/api/role-permissions/1
    
    Response:
    {
        "success": true,
        "role_id": 1,
        "role_name": "admin",
        "module_ids": [2, 3, 4]
    }
    """
    try:
        role_data = RoleService.get_role_with_modules(role_id)
        
        if 'error' in role_data:
            return jsonify({
                'success': False,
                'error': role_data['error']
            }), 404
        
        # Wyciągnij ID modułów które mają has_access=True
        module_ids = [
            m['module_id'] 
            for m in role_data['modules'] 
            if m['has_access']
        ]
        
        return jsonify({
            'success': True,
            'role_id': role_id,
            'role_name': role_data['role_name'],
            'module_ids': module_ids
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_role_permissions: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================================================
# API - ZARZĄDZANIE UPRAWNIENIAMI RÓL
# ============================================================================

@users_bp.route('/api/roles', methods=['GET'])
@require_module_access('users')
def get_roles_api():
    """
    API: Pobiera listę wszystkich ról z liczbą uprawnień
    
    GET /users/api/roles
    
    Response:
    {
        "success": true,
        "roles": [
            {
                "role_id": 1,
                "role_name": "admin",
                "display_name": "Administrator",
                "is_system": true,
                "modules_count": 10,
                "users_count": 5
            },
            ...
        ]
    }
    """
    try:
        from sqlalchemy import func
        
        roles = Role.query.filter_by(is_active=True).all()
        
        roles_data = []
        for role in roles:
            # Policz uprawnienia (moduły)
            modules_count = RolePermission.query.filter_by(role_id=role.id).count()
            
            # Policz użytkowników z tą rolą
            users_count = User.query.filter_by(role_id=role.id, active=True).count()
            
            roles_data.append({
                'role_id': role.id,
                'role_name': role.role_name,
                'display_name': role.display_name,
                'description': role.description,
                'is_system': role.is_system,
                'modules_count': modules_count,
                'users_count': users_count
            })
        
        return jsonify({
            'success': True,
            'roles': roles_data
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_roles: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@users_bp.route('/api/role-modules/<int:role_id>', methods=['GET'])
@require_module_access('users')
def get_role_modules_api(role_id):
    """
    API: Pobiera listę modułów dla roli z informacją czy rola ma dostęp
    
    GET /users/api/role-modules/1
    
    Response:
    {
        "success": true,
        "role_id": 1,
        "role_name": "admin",
        "modules": [
            {
                "module_id": 2,
                "module_key": "quotes",
                "display_name": "Wyceny",
                "icon": "📊",
                "access_type": "protected",
                "has_access": true
            },
            ...
        ]
    }
    """
    try:
        role = Role.query.get_or_404(role_id)
        
        # Pobierz wszystkie aktywne moduły (oprócz public i custom)
        all_modules = Module.query.filter_by(is_active=True)\
                                   .filter(Module.access_type.in_(['protected']))\
                                   .order_by(Module.sort_order).all()
        
        # Pobierz uprawnienia roli
        role_module_ids = [rp.module_id for rp in RolePermission.query.filter_by(role_id=role_id).all()]
        
        modules_data = []
        for module in all_modules:
            modules_data.append({
                'module_id': module.id,
                'module_key': module.module_key,
                'display_name': module.display_name,
                'icon': module.icon,
                'access_type': module.access_type,
                'has_access': module.id in role_module_ids
            })
        
        return jsonify({
            'success': True,
            'role_id': role_id,
            'role_name': role.role_name,
            'display_name': role.display_name,
            'modules': modules_data
        })
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API get_role_modules: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@users_bp.route('/api/update-role-modules', methods=['POST'])
@require_module_access('users')
def update_role_modules_api():
    """
    API: Aktualizuje uprawnienia roli (które moduły ma)
    
    POST /users/api/update-role-modules
    
    Request Body:
    {
        "role_id": 3,
        "module_ids": [2, 8, 11]  // Lista ID modułów które rola powinna mieć
    }
    
    Response:
    {
        "success": true,
        "message": "Uprawnienia roli zaktualizowane",
        "role_id": 3,
        "modules_count": 3
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Brak danych w request'
            }), 400
        
        role_id = data.get('role_id')
        module_ids = data.get('module_ids', [])
        
        if not role_id:
            return jsonify({
                'success': False,
                'error': 'Brak role_id'
            }), 400
        
        # Pobierz rolę
        role = Role.query.get(role_id)
        if not role:
            return jsonify({
                'success': False,
                'error': f'Rola o ID {role_id} nie istnieje'
            }), 404
        
        # Pobierz ID zalogowanego admina
        admin_email = session.get('user_email')
        admin_user = User.query.filter_by(email=admin_email).first()
        admin_user_id = admin_user.id if admin_user else None
        
        # Użyj RoleService do aktualizacji
        success = RoleService.update_role_permissions(
            role_id=role_id,
            module_ids=module_ids,
            changed_by_user_id=admin_user_id
        )
        
        if success:
            current_app.logger.info(f"Zaktualizowano uprawnienia roli {role.role_name}", extra={
                'role_id': role_id,
                'modules_count': len(module_ids),
                'admin_user_id': admin_user_id
            })
            
            return jsonify({
                'success': True,
                'message': f'Uprawnienia roli "{role.display_name}" zaktualizowane',
                'role_id': role_id,
                'modules_count': len(module_ids)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Błąd aktualizacji uprawnień'
            }), 500
    
    except Exception as e:
        current_app.logger.exception(f"Błąd API update_role_modules: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500