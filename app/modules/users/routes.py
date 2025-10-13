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
"""

from flask import render_template, request, redirect, url_for, flash, session, current_app
from . import users_bp
from .models import User
from .services.user_service import UserService
from .services.invitation_service import InvitationService
from .decorators import access_control
import os
from werkzeug.utils import secure_filename


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
        member_since=member_since  # ← Nowa zmienna
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
@access_control(roles=['admin', 'user'])
def manage_users():
    """
    Zarządzanie zespołem - tylko dla adminów
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
@access_control(roles=['admin'])
def invite_user():
    """Wysyła zaproszenie dla nowego użytkownika"""
    try:
        invite_email = request.form.get('invite_email')
        invite_role = request.form.get('invite_role', 'user')
        invite_multiplier = request.form.get('invite_multiplier')
        
        if not invite_email:
            flash("Adres email jest wymagany.", "error")
            return redirect(url_for('users.settings'))
        
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
    
    return redirect(url_for('users.settings'))


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
@access_control(roles=['admin'])
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
    
    return redirect(url_for('users.settings'))


@users_bp.route('/<int:user_id>/activate', methods=['POST'])
@access_control(roles=['admin'])
def activate_user(user_id):
    """Aktywacja użytkownika"""
    try:
        UserService.activate_user(user_id)
        flash("Użytkownik został aktywowany.", "success")
    except Exception as e:
        current_app.logger.error(f"Błąd aktywacji użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas aktywacji użytkownika.", "error")
    
    return redirect(url_for('users.settings'))


@users_bp.route('/<int:user_id>/deactivate', methods=['POST'])
@access_control(roles=['admin'])
def deactivate_user(user_id):
    """Dezaktywacja użytkownika"""
    try:
        UserService.deactivate_user(user_id)
        flash("Użytkownik został dezaktywowany.", "info")
    except Exception as e:
        current_app.logger.error(f"Błąd dezaktywacji użytkownika: {str(e)}")
        flash("Wystąpił błąd podczas dezaktywacji użytkownika.", "error")
    
    return redirect(url_for('users.settings'))


@users_bp.route('/<int:user_id>/delete', methods=['POST'])
@access_control(roles=['admin'])
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
    
    return redirect(url_for('users.settings'))