from flask import render_template, session, redirect, url_for, request, flash, jsonify
from functools import wraps
from . import dashboard_bp
from .services.stats_service import get_dashboard_stats
from .services.weather_service import get_weather_data
from .services.chart_service import get_quotes_chart_data, get_top_products_data, get_production_overview
from .services.partner_stats_service import get_partner_dashboard_stats, get_partner_top_products_data
from ..calculator.models import User
import logging
from datetime import datetime
from .services.user_activity_service import UserActivityService
from .models import UserSession
from modules.users.decorators import require_module_access
import traceback

logger = logging.getLogger(__name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@require_module_access('dashboard')
def dashboard():
    """Główna strona dashboard - renderuje odpowiedni widok w zależności od roli"""
    user_email = session.get('user_email')
    user = User.query.filter_by(email=user_email).first()
    
    logger.info("[Dashboard] Starting dashboard route")
    logger.info(f"[Dashboard] User: {user_email}, Role: {user.role if user else 'None'}")
    
    # WARUNEK ROLI - renderuj odpowiedni dashboard
    if user and user.is_partner():
        logger.info("[Dashboard] Renderowanie dashboardu partnera")
        return render_partner_dashboard(user)
    else:
        logger.info("[Dashboard] Renderowanie dashboardu admin/user")
        return render_admin_dashboard(user)

def render_partner_dashboard(user):
    """Renderuje dashboard dla partnera"""
    try:
        # Statystyki TYLKO dla tego partnera
        partner_stats = get_partner_dashboard_stats(user)
        
        # Dane pogodowe (ogólne)
        weather_data = get_weather_data()
        
        # Top produkty partnera
        top_products = get_partner_top_products_data(user.id, limit=5)
        
        logger.info(f"[Dashboard Partner] Statystyki partnera: {partner_stats['quotes']}")
        
        return render_template('dashboard_partner.html',
                             user_email=user.email,
                             user=user,
                             stats=partner_stats,
                             weather=weather_data,
                             top_products=top_products)
    
    except Exception as e:
        logger.exception("[Dashboard] Błąd dashboard partnera")
        logger.error(f"[Dashboard] Exception type: {type(e).__name__}")
        logger.error(f"[Dashboard] Exception message: {str(e)}")    
        logger.error(f"[Dashboard] Full traceback:\n{traceback.format_exc()}")
        
        # Fallback values
        fallback_stats = {
            'quotes': {
                'month_count': 0,
                'accepted_count': 0,
                'acceptance_rate': 0.0,
                'ordered_count': 0,
                'ordered_rate': 0.0,
                'ordered_value_net': 0.0
            },
            'recent': {'quotes': []}
        }
        
        return render_template('dashboard_partner.html',
                             user=user,
                             stats=fallback_stats,
                             weather={'success': False},
                             top_products=[])


def render_admin_dashboard(user):
    """Renderuje dashboard dla admin/user (OBECNA LOGIKA)"""
    try:
        # Podstawowe statystyki
        logger.info("[Dashboard] Getting dashboard stats...")
        dashboard_stats = get_dashboard_stats(user)
        logger.info("[Dashboard] Retrieved stats: %s", dashboard_stats)
        
        # Dane pogodowe
        logger.info("[Dashboard] Getting weather data...")
        weather_data = get_weather_data()
        logger.info("[Dashboard] Retrieved weather: %s", weather_data.get('city', 'unknown'))
        
        # Dane dla wykresu wycen
        logger.info("[Dashboard] Getting chart data...")
        chart_data = get_quotes_chart_data(months=6)
        logger.info("[Dashboard] Retrieved chart data: %s months", len(chart_data.get('labels', [])))
        
        # Top produkty
        logger.info("[Dashboard] Getting top products...")
        top_products = get_top_products_data(limit=5)
        logger.info("[Dashboard] Retrieved top products: %s items", len(top_products))
        
        # Dane produkcji
        logger.info("[Dashboard] Getting production data...")
        production_data = get_production_overview()
        logger.info("[Dashboard] Retrieved production data: %s total items", production_data.get('total_items', 0))
        
        return render_template('dashboard.html',
                             user_email=user.email,
                             user=user,
                             stats=dashboard_stats,
                             weather=weather_data,
                             chart_data=chart_data,
                             top_products=top_products,
                             production_data=production_data)
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania danych")
        
        # Fallback values
        dashboard_stats = {
            'quotes': {'month_count': 0, 'week_count': 0, 'month_value': 0.0, 'accepted_count': 0, 'acceptance_rate': 0.0},
            'clients': {'total_count': 0},
            'recent': {'quotes': [], 'clients': []},
            'user': {'quotes_count': 0}
        }
        weather_data = {'success': False, 'message': 'Błąd pobierania danych pogodowych'}
        chart_data = {'summary': {'total_quotes': 0, 'accepted_quotes': 0, 'ordered_quotes': 0}}
        top_products = []
        production_data = {'total_items': 0, 'statuses': []}
        
        return render_template('dashboard.html',
                             user_email=user.email,
                             user=user,
                             stats=dashboard_stats,
                             weather=weather_data,
                             chart_data=chart_data,
                             top_products=top_products,
                             production_data=production_data)





@dashboard_bp.route('/api/refresh-stats')
@require_module_access('dashboard')  
def refresh_stats():
    """API endpoint do odświeżania statystyk dashboard"""
    try:
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        
        # Pobierz fresh dane
        dashboard_stats = get_dashboard_stats(user)
        chart_data = get_quotes_chart_data(months=6)
        top_products = get_top_products_data(limit=5)
        
        return {
            'success': True,
            'stats': dashboard_stats,
            'chart_data': chart_data,
            'top_products': top_products,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd odświeżania statystyk")
        return {'success': False, 'error': str(e)}, 500

@dashboard_bp.route('/api/weather')
@require_module_access('dashboard')
def refresh_weather():
    """API endpoint do odświeżania danych pogodowych"""
    try:
        weather_data = get_weather_data()
        return {
            'success': True,
            'weather': weather_data,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd odświeżania pogody")
        return {'success': False, 'error': str(e)}, 500

@dashboard_bp.route('/api/chart-data/<chart_type>')
@require_module_access('dashboard')
def get_chart_data(chart_type):
    """API endpoint do pobierania danych wykresów"""
    try:
        if chart_type == 'quotes':
            months = request.args.get('months', 6, type=int)
            data = get_quotes_chart_data(months=months)
        elif chart_type == 'products':
            limit = request.args.get('limit', 5, type=int)
            data = get_top_products_data(limit=limit)
        elif chart_type == 'production':
            data = get_production_overview()
        else:
            return {'success': False, 'error': 'Unknown chart type'}, 400
            
        return {
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception(f"[Dashboard] Błąd pobierania danych wykresu {chart_type}")
        return {'success': False, 'error': str(e)}, 500
    
@dashboard_bp.route('/api/changelog-entries', methods=['POST'])
@require_module_access('dashboard')
def create_changelog_entry():
    try:
        from .models import ChangelogEntry, ChangelogItem
        from extensions import db
        from datetime import datetime
        
        # Sprawdź czy użytkownik to admin
        user_email = session.get('user_email')
        from ..calculator.models import User
        user = User.query.filter_by(email=user_email).first()
        
        if not user or user.role != 'admin':
            return {'success': False, 'error': 'Brak uprawnień'}, 403
        
        # Pobierz dane z formularza
        version = request.form.get('version')
        if not version:
            return {'success': False, 'error': 'Wersja jest wymagana'}, 400
        
        # Sprawdź czy wersja już istnieje
        existing = ChangelogEntry.query.filter_by(version=version).first()
        if existing:
            return {'success': False, 'error': 'Ta wersja już istnieje'}, 400
        
        # Utwórz nowy wpis
        entry = ChangelogEntry(
            version=version,
            created_by=user.id,
            is_visible=True
        )
        db.session.add(entry)
        db.session.flush()  # Żeby uzyskać ID
        
        # Dodaj items z różnych sekcji
        sections = ['added', 'improved', 'fixed']
        for section in sections:
            items = request.form.getlist(f'{section}_items[]')
            for item_text in items:
                if item_text.strip():
                    item = ChangelogItem(
                        entry_id=entry.id,
                        section_type=section,
                        item_text=item_text.strip()
                    )
                    db.session.add(item)
        
        # Obsłuż custom sekcję
        custom_section_name = request.form.get('custom_section_name')
        custom_items = request.form.getlist('custom_items[]')
        for item_text in custom_items:
            if item_text.strip():
                item = ChangelogItem(
                    entry_id=entry.id,
                    section_type='custom',
                    custom_section_name=custom_section_name,
                    item_text=item_text.strip()
                )
                db.session.add(item)
        
        db.session.commit()
        
        return {'success': True, 'message': 'Wpis utworzony pomyślnie'}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': str(e)}, 500
    
@dashboard_bp.route('/api/changelog-entries', methods=['GET'])
@require_module_access('dashboard')
def get_changelog_entries():
    """Pobiera listę wpisów changelog"""
    try:
        from .models import ChangelogEntry, ChangelogItem
        
        # Pobierz wszystkie widoczne wpisy, posortowane od najnowszych
        entries = ChangelogEntry.query.filter_by(is_visible=True)\
                                    .order_by(ChangelogEntry.created_at.desc())\
                                    .all()
        
        entries_data = []
        for entry in entries:
            # Pobierz items dla tego wpisu
            items_data = []
            for item in entry.items:
                items_data.append({
                    'section_type': item.section_type,
                    'item_text': item.item_text,
                    'custom_section_name': item.custom_section_name
                })
            
            entries_data.append({
                'id': entry.id,
                'version': entry.version,
                'created_at': entry.created_at.isoformat(),
                'items': items_data
            })
        
        return {
            'success': True,
            'entries': entries_data
        }
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania changelog entries")
        return {'success': False, 'error': str(e)}, 500

@dashboard_bp.route('/api/changelog-next-version')
@require_module_access('dashboard')
def get_next_version():
    """Pobiera sugerowaną następną wersję"""
    try:
        from .models import ChangelogEntry
        
        # Znajdź najnowszą wersję
        latest = ChangelogEntry.query.order_by(ChangelogEntry.created_at.desc()).first()
        
        if latest:
            # Prosta logika zwiększania wersji
            try:
                parts = latest.version.split('.')
                if len(parts) >= 3:
                    # Format X.Y.Z - zwiększ Z
                    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                    next_version = f"{major}.{minor}.{patch + 1}"
                elif len(parts) == 2:
                    # Format X.Y - dodaj .1
                    major, minor = int(parts[0]), int(parts[1])
                    next_version = f"{major}.{minor}.1"
                else:
                    next_version = "1.0.1"
            except (ValueError, IndexError):
                next_version = "1.0.1"
        else:
            next_version = "1.0.0"
            
        return {
            'success': True, 
            'version': next_version,
            'current_version': latest.version if latest else None
        }
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania następnej wersji")
        return {
            'success': True, 
            'version': '1.0.0',
            'error': 'Nie można określić następnej wersji'
        }

@dashboard_bp.route('/api/changelog-entries/<int:entry_id>', methods=['DELETE'])
@require_module_access('dashboard')
def delete_changelog_entry(entry_id):
    """Usuwa wpis changelog (tylko dla adminów)"""
    try:
        from .models import ChangelogEntry
        from extensions import db
        
        # Sprawdź uprawnienia
        user_email = session.get('user_email')
        from ..calculator.models import User
        user = User.query.filter_by(email=user_email).first()
        
        if not user or user.role != 'admin':
            return {'success': False, 'error': 'Brak uprawnień'}, 403
        
        # Znajdź wpis
        entry = ChangelogEntry.query.get_or_404(entry_id)
        
        # Usuń wpis (cascade usunie też items)
        db.session.delete(entry)
        db.session.commit()
        
        logger.info(f"[Dashboard] Usunięto changelog entry v{entry.version} przez {user.email}")
        
        return {
            'success': True,
            'message': f'Wpis wersji {entry.version} został usunięty'
        }
        
    except Exception as e:
        db.session.rollback()
        logger.exception("[Dashboard] Błąd usuwania changelog entry")
        return {'success': False, 'error': str(e)}, 500


@dashboard_bp.route('/api/changelog-entries/<int:entry_id>/toggle-visibility', methods=['POST'])
@require_module_access('dashboard')
def toggle_changelog_visibility(entry_id):
    """Przełącza widoczność wpisu changelog"""
    try:
        from .models import ChangelogEntry
        from extensions import db
        
        # Sprawdź uprawnienia
        user_email = session.get('user_email')
        from ..calculator.models import User
        user = User.query.filter_by(email=user_email).first()
        
        if not user or user.role != 'admin':
            return {'success': False, 'error': 'Brak uprawnień'}, 403
        
        # Znajdź wpis
        entry = ChangelogEntry.query.get_or_404(entry_id)
        
        # Przełącz widoczność
        entry.is_visible = not entry.is_visible
        db.session.commit()
        
        status = "widoczny" if entry.is_visible else "ukryty"
        logger.info(f"[Dashboard] Wpis v{entry.version} jest teraz {status}")
        
        return {
            'success': True,
            'message': f'Wpis v{entry.version} jest teraz {status}',
            'is_visible': entry.is_visible
        }
        
    except Exception as e:
        db.session.rollback()
        logger.exception("[Dashboard] Błąd przełączania widoczności")
        return {'success': False, 'error': str(e)}, 500

@dashboard_bp.route('/api/active-users')
@require_module_access('dashboard')
def get_active_users():
    """
    API endpoint zwracający listę aktywnych użytkowników (tylko dla adminów)
    
    Returns:
        JSON: Lista aktywnych użytkowników z ich statusami
    """
    try:
        logger.info("[Dashboard] Pobieranie aktywnych użytkowników przez admin")
        
        # Pobierz aktywnych użytkowników
        active_users = UserActivityService.get_active_users(minutes_threshold=15)
        
        # Pobierz statystyki aktywności
        stats = UserActivityService.get_user_activity_stats()
        
        logger.info(f"[Dashboard] Zwracam {len(active_users)} aktywnych użytkowników")
        
        return jsonify({
            'success': True,
            'users': active_users,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania aktywnych użytkowników")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/force-logout/<int:user_id>', methods=['POST'])
@require_module_access('dashboard')
def force_logout_user(user_id):
    """
    API endpoint do wymuszania wylogowania użytkownika (tylko dla adminów)
    
    Args:
        user_id (int): ID użytkownika do wylogowania
        
    Returns:
        JSON: Wynik operacji wylogowania
    """
    try:
        current_user_email = session.get('user_email')
        current_user = User.query.filter_by(email=current_user_email).first()
        
        logger.info(f"[Dashboard] Admin {current_user.email} wymusza wylogowanie user_id={user_id}")
        
        # Sprawdź czy user istnieje
        target_user = User.query.get(user_id)
        if not target_user:
            return jsonify({
                'success': False,
                'error': 'Użytkownik nie został znaleziony'
            }), 404
        
        # Nie pozwól wylogować samego siebie
        if current_user.id == user_id:
            return jsonify({
                'success': False,
                'error': 'Nie możesz wylogować samego siebie'
            }), 400
        
        # Wykonaj wymuszenie wylogowania
        result = UserActivityService.force_logout_user(user_id, current_user.id)
        
        if result['success']:
            logger.info(f"[Dashboard] Pomyślnie wylogowano użytkownika {target_user.email}")
            return jsonify(result)
        else:
            logger.warning(f"[Dashboard] Nie udało się wylogować użytkownika {target_user.email}: {result['error']}")
            return jsonify(result), 400
            
    except Exception as e:
        logger.exception(f"[Dashboard] Błąd wymuszania wylogowania user_id={user_id}")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/user-details/<int:user_id>')
@require_module_access('dashboard')
def get_user_details(user_id):
    """
    API endpoint zwracający szczegółowe informacje o użytkowniku (tylko dla adminów)
    
    Args:
        user_id (int): ID użytkownika
        
    Returns:
        JSON: Szczegóły użytkownika i historia sesji
    """
    try:
        logger.info(f"[Dashboard] Pobieranie szczegółów user_id={user_id}")
        
        # Pobierz użytkownika
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'error': 'Użytkownik nie został znaleziony'
            }), 404
        
        # Pobierz aktualną sesję
        current_session = UserSession.query.filter_by(
            user_id=user_id,
            is_active=True
        ).first()
        
        # Pobierz historię sesji
        session_history = UserActivityService.get_user_session_history(user_id, days=7)
        
        # Przygotuj dane użytkownika
        user_data = {
            'user_id': user.id,
            'user_name': f"{user.first_name} {user.last_name}".strip() or user.email,
            'user_email': user.email,
            'user_role': user.role,
            'user_avatar': url_for('static', filename=user.avatar_path) if user.avatar_path else url_for('static', filename='images/avatars/default_avatars/avatar1.svg'),
            'is_active': user.active
        }
        
        # Dodaj dane z aktualnej sesji jeśli istnieje
        if current_session:
            session_dict = current_session.to_dict()
            user_data.update({
                'status': session_dict['status'],
                'current_page': session_dict['current_page'],
                'last_activity': session_dict['last_activity'],
                'session_duration': session_dict['session_duration'],
                'ip_address': session_dict['ip_address']
            })
        else:
            user_data.update({
                'status': 'offline',
                'current_page': 'Brak aktywnej sesji',
                'last_activity': 'Nieznany',
                'session_duration': 'Brak sesji',
                'ip_address': 'Nieznany'
            })
        
        return jsonify({
            'success': True,
            'user': user_data,
            'sessions': session_history,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.exception(f"[Dashboard] Błąd pobierania szczegółów user_id={user_id}")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/user-activity-stats')
@require_module_access('dashboard')
def get_user_activity_stats():
    """
    API endpoint zwracający statystyki aktywności użytkowników (tylko dla adminów)
    
    Returns:
        JSON: Statystyki aktywności
    """
    try:
        logger.info("[Dashboard] Pobieranie statystyk aktywności użytkowników")
        
        stats = UserActivityService.get_user_activity_stats()
        
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania statystyk aktywności")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/cleanup-sessions', methods=['POST'])
@require_module_access('dashboard')
def cleanup_old_sessions():
    """
    API endpoint do ręcznego czyszczenia starych sesji (tylko dla adminów)
    
    Returns:
        JSON: Wynik operacji czyszczenia
    """
    try:
        current_user_email = session.get('user_email')
        current_user = User.query.filter_by(email=current_user_email).first()
        
        logger.info(f"[Dashboard] Admin {current_user.email} uruchamia cleanup sesji")
        
        # Pobierz parametry z request
        days_threshold = request.json.get('days_threshold', 30) if request.is_json else 30
        
        # Wykonaj cleanup
        result = UserActivityService.cleanup_old_sessions(days_threshold)
        
        if result['success']:
            logger.info(f"[Dashboard] Cleanup zakończony: {result}")
            return jsonify(result)
        else:
            logger.error(f"[Dashboard] Błąd cleanup: {result['error']}")
            return jsonify(result), 500
            
    except Exception as e:
        logger.exception("[Dashboard] Błąd ręcznego cleanup sesji")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/current-user-activity')
@require_module_access('dashboard')
def get_current_user_activity():
    """
    API endpoint zwracający aktywność bieżącego użytkownika
    
    Returns:
        JSON: Informacje o aktywności bieżącego użytkownika
    """
    try:
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        
        if not user:
            return jsonify({
                'success': False,
                'error': 'Użytkownik nie znaleziony'
            }), 404
        
        # Pobierz aktualną sesję
        session_token = session.get('user_session_token')
        current_session = None
        
        if session_token:
            current_session = UserSession.query.filter_by(
                session_token=session_token,
                is_active=True
            ).first()
        
        # Przygotuj odpowiedź
        activity_data = {
            'user_id': user.id,
            'user_name': f"{user.first_name} {user.last_name}".strip() or user.email,
            'has_active_session': bool(current_session),
            'session_duration': current_session.get_session_duration() if current_session else None,
            'last_activity': current_session.get_relative_time() if current_session else None,
            'current_page': current_session.get_page_display_name() if current_session else None
        }
        
        return jsonify({
            'success': True,
            'activity': activity_data,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania aktywności bieżącego użytkownika")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@dashboard_bp.route('/api/open-tickets')
@require_module_access('dashboard')
def get_open_tickets():
    """
    API endpoint zwracający otwarte tickety dla widgetu Issues

    Zwraca maksymalnie 5 ostatnich ticketów użytkownika (lub wszystkich dla admina)
    wykluczając tickety ze statusem 'closed' i 'cancelled'.

    Returns:
        JSON: Lista otwartych ticketów
    """
    try:
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()

        if not user:
            return jsonify({
                'success': False,
                'error': 'Użytkownik nie znaleziony'
            }), 404

        logger.info(f"[Dashboard] Pobieranie otwartych ticketów dla user_id={user.id}, role={user.role}")

        # Import TicketService z modułu issues
        from modules.issues.services import TicketService

        # Pobierz otwarte tickety
        tickets = TicketService.get_open_tickets_for_widget(
            user_id=user.id,
            is_admin=(user.role == 'admin'),
            limit=5
        )

        # Konwertuj do dict
        tickets_data = [ticket.to_dict() for ticket in tickets]

        logger.info(f"[Dashboard] Zwracam {len(tickets_data)} otwartych ticketów")

        return jsonify({
            'success': True,
            'tickets': tickets_data,
            'count': len(tickets_data),
            'timestamp': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.exception("[Dashboard] Błąd pobierania otwartych ticketów")
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500