# app/modules/issues/routers.py
"""
Routing i endpointy modułu ticketów

Blueprint: issues_bp
Prefix: /issues

Autor: Konrad Kmiecik
Data: 2025-01-20
"""

from flask import Blueprint, render_template, request, jsonify, session, send_file, flash, redirect, url_for, current_app
from werkzeug.utils import secure_filename
from modules.users.decorators import require_module_access
from modules.users.models import User
from modules.logging import get_logger
from .services import TicketService, AttachmentService, NotificationService
from .models import Ticket, TicketMessage, TicketAttachment
from extensions import db
import os

# Logger
logger = get_logger('issues.routers')

# Blueprint (importowany z __init__.py)
from . import issues_bp


# ============================================================================
# WIDOKI HTML
# ============================================================================

@issues_bp.route('/')
@require_module_access('issues')
def help_center():
    """
    Główny widok: Help Center + formularz + lista ticketów użytkownika
    """
    user_id = session.get('user_id')
    return render_template('issues/issues_help_center.html')


@issues_bp.route('/admin')
@require_module_access('issues')
def admin_panel():
    """
    Panel administratora - dostęp tylko dla adminów
    """
    user = User.query.get(session.get('user_id'))
    if user.role != 'admin':
        flash('Brak uprawnień do panelu administratora', 'error')
        return redirect(url_for('issues.help_center'))
    
    return render_template('issues/issues_admin_panel.html')


@issues_bp.route('/ticket/<ticket_number>')
@require_module_access('issues')
def ticket_detail(ticket_number):
    """
    Szczegóły ticketu - widok konwersacji
    """
    user_id = session.get('user_id')
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
    
    # Sprawdź uprawnienia
    if not TicketService.can_user_access_ticket(user_id, ticket):
        flash('Brak dostępu do tego ticketu', 'error')
        return redirect(url_for('issues.help_center'))
    
    return render_template('issues/issues_ticket_detail.html', ticket=ticket)


# ============================================================================
# API - TICKETY
# ============================================================================

@issues_bp.route('/api/tickets', methods=['GET'])
@require_module_access('issues')
def api_get_tickets():
    """
    API: Pobiera listę ticketów użytkownika
    
    Query params:
        - status: filtrowanie po statusie (opcjonalne)
        - limit: limit wyników (domyślnie 50)
        - offset: offset dla paginacji
    
    Response:
        {
            "success": true,
            "tickets": [...],
            "total": 10
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Parametry
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # Pobierz tickety
        tickets_data = TicketService.get_user_tickets(
            user_id=user_id,
            is_admin=(user.role == 'admin'),
            status=status,
            limit=limit,
            offset=offset
        )
        
        return jsonify({
            'success': True,
            'tickets': [t.to_dict() for t in tickets_data['tickets']],
            'total': tickets_data['total']
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania ticketów: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/tickets', methods=['POST'])
@require_module_access('issues')
def api_create_ticket():
    """
    API: Tworzy nowy ticket
    
    Body:
        {
            "title": "Tytuł zgłoszenia",
            "category": "crm",
            "subcategory": "calculator",
            "priority": "high",
            "message": "Treść pierwszej wiadomości",
            "attachment_ids": [1, 2, 3]  # opcjonalne
        }
    
    Response:
        {
            "success": true,
            "ticket_number": "A4G8Y4A6",
            "ticket": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        data = request.get_json()
        
        # Walidacja
        if not data.get('title') or len(data.get('title')) < 5:
            return jsonify({
                'success': False,
                'error': 'Tytuł musi mieć minimum 5 znaków'
            }), 400
        
        if not data.get('message') or len(data.get('message')) < 10:
            return jsonify({
                'success': False,
                'error': 'Wiadomość musi mieć minimum 10 znaków'
            }), 400
        
        # Utwórz ticket
        ticket = TicketService.create_ticket(
            user_id=user_id,
            title=data.get('title'),
            category=data.get('category'),
            subcategory=data.get('subcategory'),
            priority=data.get('priority', 'medium'),
            initial_message=data.get('message'),
            attachment_ids=data.get('attachment_ids', [])
        )
        
        return jsonify({
            'success': True,
            'ticket_number': ticket.ticket_number,
            'ticket': ticket.to_dict()
        }), 201
    
    except ValueError as e:
        logger.error(f"Błąd walidacji tworzenia ticketu: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    
    except Exception as e:
        logger.error(f"Błąd tworzenia ticketu: {e}")
        return jsonify({
            'success': False,
            'error': 'Wystąpił błąd podczas tworzenia zgłoszenia'
        }), 500


@issues_bp.route('/api/tickets/<ticket_number>', methods=['GET'])
@require_module_access('issues')
def api_get_ticket(ticket_number):
    """
    API: Pobiera szczegóły ticketu
    
    Response:
        {
            "success": true,
            "ticket": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        
        # Sprawdź uprawnienia
        if not TicketService.can_user_access_ticket(user_id, ticket):
            return jsonify({
                'success': False,
                'error': 'Brak dostępu do tego ticketu'
            }), 403
        
        return jsonify({
            'success': True,
            'ticket': ticket.to_dict()
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania ticketu: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/tickets/<ticket_number>/status', methods=['PATCH'])
@require_module_access('issues')
def api_change_status(ticket_number):
    """
    API: Zmiana statusu ticketu (tylko admin)
    
    Body:
        {
            "status": "open"
        }
    
    Response:
        {
            "success": true,
            "ticket": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        data = request.get_json()
        
        new_status = data.get('status')
        if new_status not in ['new', 'open', 'in_progress', 'closed', 'cancelled']:
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowy status'
            }), 400
        
        # Zmień status
        updated_ticket = TicketService.change_status(ticket.id, new_status, user_id)
        
        return jsonify({
            'success': True,
            'ticket': updated_ticket.to_dict()
        })
    
    except Exception as e:
        logger.error(f"Błąd zmiany statusu: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/tickets/<ticket_number>/priority', methods=['PATCH'])
@require_module_access('issues')
def api_change_priority(ticket_number):
    """
    API: Zmiana priorytetu ticketu (tylko admin)
    
    Body:
        {
            "priority": "high"
        }
    
    Response:
        {
            "success": true,
            "ticket": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        data = request.get_json()
        
        new_priority = data.get('priority')
        if new_priority not in ['low', 'medium', 'high', 'critical']:
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowy priorytet'
            }), 400
        
        # Zmień priorytet
        updated_ticket = TicketService.change_priority(ticket.id, new_priority, user_id)
        
        return jsonify({
            'success': True,
            'ticket': updated_ticket.to_dict()
        })
    
    except Exception as e:
        logger.error(f"Błąd zmiany priorytetu: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/tickets/<ticket_number>/assign', methods=['PATCH'])
@require_module_access('issues')
def api_assign_ticket(ticket_number):
    """
    API: Przypisanie ticketu do admina (tylko admin)
    
    Body:
        {
            "admin_user_id": 5
        }
    
    Response:
        {
            "success": true,
            "ticket": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        data = request.get_json()
        
        admin_user_id = data.get('admin_user_id')
        if not admin_user_id:
            return jsonify({
                'success': False,
                'error': 'Brak admin_user_id'
            }), 400
        
        # Przypisz ticket
        updated_ticket = TicketService.assign_ticket(ticket.id, admin_user_id)
        
        return jsonify({
            'success': True,
            'ticket': updated_ticket.to_dict()
        })
    
    except Exception as e:
        logger.error(f"Błąd przypisywania ticketu: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# API - WIADOMOŚCI
# ============================================================================

@issues_bp.route('/api/tickets/<ticket_number>/messages', methods=['GET'])
@require_module_access('issues')
def api_get_messages(ticket_number):
    """
    API: Pobiera wiadomości ticketu
    
    Response:
        {
            "success": true,
            "messages": [...]
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        
        # Sprawdź uprawnienia
        if not TicketService.can_user_access_ticket(user_id, ticket):
            return jsonify({
                'success': False,
                'error': 'Brak dostępu do tego ticketu'
            }), 403
        
        # Pobierz wiadomości
        messages = TicketMessage.query.filter_by(ticket_id=ticket.id).order_by(TicketMessage.created_at).all()
        
        # Filtruj notatki wewnętrzne dla nie-adminów
        if user.role != 'admin':
            messages = [m for m in messages if not m.is_internal_note]
        
        return jsonify({
            'success': True,
            'messages': [m.to_dict() for m in messages]
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania wiadomości: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/tickets/<ticket_number>/messages', methods=['POST'])
@require_module_access('issues')
def api_add_message(ticket_number):
    """
    API: Dodaje wiadomość do ticketu
    
    Body:
        {
            "message": "Treść wiadomości",
            "is_internal_note": false,
            "attachment_ids": [1, 2]
        }
    
    Response:
        {
            "success": true,
            "message": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
        data = request.get_json()
        
        # Sprawdź uprawnienia
        if not TicketService.can_user_add_message(user_id, ticket):
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień do dodawania wiadomości'
            }), 403
        
        # Walidacja
        if not data.get('message') or len(data.get('message')) < 5:
            return jsonify({
                'success': False,
                'error': 'Wiadomość musi mieć minimum 5 znaków'
            }), 400
        
        # Dodaj wiadomość
        message = TicketService.add_message(
            ticket_id=ticket.id,
            user_id=user_id,
            message_text=data.get('message'),
            is_internal_note=data.get('is_internal_note', False),
            attachment_ids=data.get('attachment_ids', [])
        )
        
        return jsonify({
            'success': True,
            'message': message.to_dict()
        }), 201
    
    except ValueError as e:
        logger.error(f"Błąd walidacji dodawania wiadomości: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    
    except Exception as e:
        logger.error(f"Błąd dodawania wiadomości: {e}")
        return jsonify({
            'success': False,
            'error': 'Wystąpił błąd podczas dodawania wiadomości'
        }), 500


# ============================================================================
# API - ZAŁĄCZNIKI
# ============================================================================

@issues_bp.route('/api/attachments/upload', methods=['POST'])
@require_module_access('issues')
def api_upload_attachment():
    """
    API: Upload załącznika (tymczasowy, przed utworzeniem ticketu/wiadomości)
    
    Form-data:
        file: plik do uploadu
    
    Response:
        {
            "success": true,
            "attachment": {...}
        }
    """
    try:
        user_id = session.get('user_id')
        
        # Sprawdź czy plik został wysłany
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Brak pliku'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Nie wybrano pliku'
            }), 400
        
        # Zapisz załącznik
        attachment = AttachmentService.save_attachment(file, user_id)
        
        return jsonify({
            'success': True,
            'attachment': attachment.to_dict()
        }), 201
    
    except ValueError as e:
        logger.error(f"Błąd walidacji załącznika: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    
    except Exception as e:
        logger.error(f"Błąd uploadu załącznika: {e}")
        return jsonify({
            'success': False,
            'error': 'Wystąpił błąd podczas uploadu pliku'
        }), 500


@issues_bp.route('/api/attachments/<int:attachment_id>', methods=['GET'])
@require_module_access('issues')
def api_download_attachment(attachment_id):
    """
    API: Pobieranie załącznika
    """
    try:
        user_id = session.get('user_id')
        attachment = TicketAttachment.query.get_or_404(attachment_id)
        ticket = Ticket.query.get(attachment.ticket_id)
        
        # Sprawdź uprawnienia
        if not TicketService.can_user_access_ticket(user_id, ticket):
            return jsonify({
                'success': False,
                'error': 'Brak dostępu do załącznika'
            }), 403
        
        # Ścieżka do pliku
        file_path = os.path.join(
            current_app.config.get('BASE_DIR', os.getcwd()),
            'modules/issues/uploads',
            attachment.filepath
        )
        
        if not os.path.exists(file_path):
            logger.error(f"Plik nie istnieje: {file_path}")
            return jsonify({
                'success': False,
                'error': 'Plik nie został znaleziony'
            }), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=attachment.original_filename
        )
    
    except Exception as e:
        logger.error(f"Błąd pobierania załącznika: {e}")
        return jsonify({
            'success': False,
            'error': 'Wystąpił błąd podczas pobierania pliku'
        }), 500


# ============================================================================
# API - PANEL ADMINA
# ============================================================================

@issues_bp.route('/api/admin/tickets/active', methods=['GET'])
@require_module_access('issues')
def api_admin_active_tickets():
    """
    API: Lista aktywnych ticketów dla admina
    
    Query params:
        - priority: filtr po priorytecie
        - limit: limit wyników
        - offset: offset dla paginacji
    
    Response:
        {
            "success": true,
            "tickets": [...],
            "total": 25
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        # Parametry
        priority = request.args.get('priority')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # Query
        query = Ticket.query.filter(Ticket.status.in_(['new', 'open', 'in_progress']))
        
        if priority:
            query = query.filter_by(priority=priority)
        
        # Sortowanie: priorytet DESC, updated_at DESC
        priority_order = db.case(
            (Ticket.priority == 'critical', 4),
            (Ticket.priority == 'high', 3),
            (Ticket.priority == 'medium', 2),
            (Ticket.priority == 'low', 1),
            else_=0
        )
        query = query.order_by(priority_order.desc(), Ticket.updated_at.desc())
        
        total = query.count()
        tickets = query.limit(limit).offset(offset).all()
        
        return jsonify({
            'success': True,
            'tickets': [t.to_dict() for t in tickets],
            'total': total
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania aktywnych ticketów: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/admin/tickets/closed', methods=['GET'])
@require_module_access('issues')
def api_admin_closed_tickets():
    """
    API: Lista zamkniętych ticketów dla admina
    
    Query params:
        - limit: limit wyników
        - offset: offset dla paginacji
    
    Response:
        {
            "success": true,
            "tickets": [...],
            "total": 147
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        # Parametry
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        # Query
        query = Ticket.query.filter_by(status='closed').order_by(Ticket.closed_at.desc())
        
        total = query.count()
        tickets = query.limit(limit).offset(offset).all()
        
        return jsonify({
            'success': True,
            'tickets': [t.to_dict() for t in tickets],
            'total': total
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania zamkniętych ticketów: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@issues_bp.route('/api/admin/stats', methods=['GET'])
@require_module_access('issues')
def api_admin_stats():
    """
    API: Statystyki ticketów
    
    Response:
        {
            "success": true,
            "stats": {
                "new": 12,
                "open": 8,
                "in_progress": 5,
                "closed_today": 3,
                "total_active": 25
            }
        }
    """
    try:
        user_id = session.get('user_id')
        user = User.query.get(user_id)
        
        # Sprawdź czy admin
        if user.role != 'admin':
            return jsonify({
                'success': False,
                'error': 'Brak uprawnień'
            }), 403
        
        from datetime import datetime, timedelta
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        stats = {
            'new': Ticket.query.filter_by(status='new').count(),
            'open': Ticket.query.filter_by(status='open').count(),
            'in_progress': Ticket.query.filter_by(status='in_progress').count(),
            'closed_today': Ticket.query.filter(
                Ticket.status == 'closed',
                Ticket.closed_at >= today_start
            ).count(),
            'total_active': Ticket.query.filter(
                Ticket.status.in_(['new', 'open', 'in_progress'])
            ).count()
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    
    except Exception as e:
        logger.error(f"Błąd pobierania statystyk: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# API - KATEGORIE + PODKATEGORIE
# ============================================================================

@issues_bp.route('/api/categories', methods=['GET'])
@require_module_access('issues')
def api_get_categories():
    """
    Zwraca listę kategorii i podkategorii
    GET /issues/api/categories
    """
    try:
        from .config import TICKET_CATEGORIES
        
        # Formatuj do struktury oczekiwanej przez frontend
        categories = []
        for cat_key, cat_data in TICKET_CATEGORIES.items():
            categories.append({
                'key': cat_key,
                'name': cat_data['name'],
                'icon': cat_data['icon'],
                'description': cat_data.get('description', ''),
                'subcategories': [
                    {'key': sub_key, 'name': sub_name}
                    for sub_key, sub_name in cat_data['subcategories'].items()
                ]
            })
        
        return jsonify({
            'success': True,
            'categories': categories
        })
        
    except Exception as e:
        logger.error(f"Błąd pobierania kategorii: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500