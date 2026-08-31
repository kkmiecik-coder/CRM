# modules/quotes/routers.py
from flask import render_template, jsonify, request, make_response, current_app, send_file, send_from_directory, Blueprint, session, redirect, url_for, flash, abort
from . import quotes_bp
from modules.calculator.models import Quote, User, QuoteItemDetails, QuoteItem, QuoteLog, Multiplier
from modules.clients.models import Client
from .chatwoot_match import olx_buyer_prefix, name_matches_olx_prefix
from modules.baselinker.service import BaselinkerService
from modules.baselinker.models import BaselinkerConfig
from modules.calculator.services.edge_calculator import human_edge_label, EDGE_DEFINITIONS
from modules.quotes.services.svg_sanitizer import sanitize_svg
from modules.users.decorators import require_module_access
from modules.logging import get_logger
from extensions import db, mail
from weasyprint import HTML
from io import BytesIO
import cairosvg
from flask_mail import Message
from functools import wraps
import logging
import sys
from sqlalchemy.orm import joinedload
from sqlalchemy import func, text, or_
import re
from datetime import datetime
import base64
import os
import json

logger = get_logger('quotes.routers')

from modules.quotes.models import (
    Quote,
    QuoteItem,
    QuoteItemDetails,
    QuoteStatus,
    QuoteLog,
    FinishingColor,
    Client,
    User,
    DiscountReason
)

def get_filtered_quotes_query(base_query):
    """
    Filtruje wyceny w zależności od roli użytkownika.
    Partner widzi TYLKO swoje wyceny (gdzie jest opiekunem).
    
    Args:
        base_query: SQLAlchemy Query object
    
    Returns:
        Query object
    """
    user_id = session.get('user_id')
    if not user_id:
        return base_query.filter(Quote.id == -1)
    
    user = User.query.get(user_id)
    if not user:
        return base_query.filter(Quote.id == -1)
    
    # Partner widzi TYLKO swoje wyceny
    if user.role == 'partner':
        return base_query.filter(Quote.user_id == user_id)
    
    # Admin i User widzą wszystkie wyceny
    return base_query

def render_client_error(error_type, error_code, error_message, error_details=None, quote_number=None):
    """Renderuje stronę błędu dla klienta"""
    return render_template(
        'quotes/templates/client_error.html',
        error_type=error_type,
        error_code=error_code,
        error_message=error_message,
        error_details=error_details,
        quote_number=quote_number
    ), error_code

# Funkcje pomocnicze
def calculate_costs_with_vat(products_netto, finishing_netto, shipping_brutto):
    """Oblicza koszty z VAT"""
    vat_rate = 0.23
    
    # Produkty
    products_vat = products_netto * vat_rate
    products_brutto = products_netto + products_vat
    
    # Wykończenie
    finishing_vat = finishing_netto * vat_rate
    finishing_brutto = finishing_netto + finishing_vat
    
    # Shipping - zakładamy że mamy już brutto
    shipping_netto = shipping_brutto / (1 + vat_rate)
    shipping_vat = shipping_brutto - shipping_netto
    
    # Totale
    total_netto = products_netto + finishing_netto + shipping_netto
    total_vat = products_vat + finishing_vat + shipping_vat
    total_brutto = total_netto + total_vat
    
    return {
        'products': {
            'netto': round(products_netto, 2),
            'vat': round(products_vat, 2),
            'brutto': round(products_brutto, 2)
        },
        'finishing': {
            'netto': round(finishing_netto, 2),
            'vat': round(finishing_vat, 2),
            'brutto': round(finishing_brutto, 2)
        },
        'shipping': {
            'netto': round(shipping_netto, 2),
            'vat': round(shipping_vat, 2),
            'brutto': round(shipping_brutto, 2)
        },
        'total': {
            'netto': round(total_netto, 2),
            'vat': round(total_vat, 2),
            'brutto': round(total_brutto, 2)
        }
    }

def validate_email_or_phone(email_or_phone, quote):
    """Waliduje czy podany email lub telefon pasuje do wyceny"""
    if not email_or_phone:
        return False
    
    client = quote.client
    if not client:
        return False
    
    # Sprawdź email
    if '@' in email_or_phone:
        return client.email and client.email.lower() == email_or_phone.lower()
    
    # Sprawdź telefon (usuń wszystkie znaki poza cyframi i porównaj)
    phone_digits = re.sub(r'[^\d]', '', email_or_phone)
    client_phone_digits = re.sub(r'[^\d]', '', client.phone) if client.phone else ''
    
    return len(phone_digits) >= 7 and phone_digits in client_phone_digits

@quotes_bp.route('/')
@require_module_access('quotes')
def quotes_home():
    """Główna strona modułu quotes - z dodanymi danymi dla calculator.js"""
    try:
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        user_role = user.role if user else 'user'
        user_multiplier = user.multiplier.multiplier if user and user.multiplier else 1.0
        user_client_type = user.multiplier.client_type if user and user.multiplier else None
                
        prices_query = db.session.execute(text("""
            SELECT species, technology, wood_class, thickness_min, thickness_max,
                   length_min, length_max, width_min, width_max, price_per_m3
            FROM prices
        """)).fetchall()
        prices_list = [dict(row._mapping) for row in prices_query]
        for row in prices_list:
            for key in ['thickness_min', 'thickness_max', 'length_min', 'length_max', 'width_min', 'width_max', 'price_per_m3']:
                if key in row and row[key] is not None:
                    row[key] = float(row[key])
        prices_json = json.dumps(prices_list)
        
        # ✅ NOWE: Konfiguracja flexible partners
        FLEXIBLE_PARTNER_IDS = [14, 15]
        # Flexible partnerzy mają dostępny tylko mnożnik id 11 (Czernecki, 1.05)
        FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS = {
            14: [11],
            15: [11],
        }
        
        # Pobieranie mnożników z bazy - filtrowanie per user
        if user and user_role == 'partner' and user.id in FLEXIBLE_PARTNER_IDS:
            # Flexible partner - pokaż tylko dozwolone mnożniki
            allowed_ids = FLEXIBLE_PARTNER_ALLOWED_MULTIPLIERS.get(user.id, [])
            multipliers_query = Multiplier.query.filter(Multiplier.id.in_(allowed_ids)).all()
        else:
            # Wszyscy inni (admin, user, standardowi partnerzy) - pokaż wszystkie
            multipliers_query = Multiplier.query.all()
        
        multipliers_list = [
            {"label": m.client_type, "value": float(m.multiplier)}
            for m in multipliers_query
        ]
        multipliers_json = json.dumps(multipliers_list)
        
        # ✅ NOWE: Flaga czy to "flexible partner"
        is_flexible_partner = (user and user_role == 'partner' and user.id in FLEXIBLE_PARTNER_IDS)
        
        from modules.baselinker.models import BaselinkerConfig
        from modules.baselinker.service import BaselinkerService
        
        config_count = BaselinkerConfig.query.count()
        
        if config_count == 0:
            api_config = current_app.config.get('API_BASELINKER')
            if api_config and api_config.get('api_key'):
                try:
                    service = BaselinkerService()
                    sources_synced = service.sync_order_sources()
                    statuses_synced = service.sync_order_statuses()
                except Exception as e:
                    logger.warning(f"[quotes_home] Błąd synchronizacji Baselinker: {e}")
            else:
                logger.warning("[quotes_home] Brak konfiguracji API Baselinker")
            
    except Exception as e:
        print(f"[quotes_home] Błąd podczas ładowania danych: {e}", file=sys.stderr)
        prices_json = json.dumps([])
        multipliers_json = json.dumps([])
        user_role = 'user'
        user_multiplier = 1.0
        user_client_type = None
        is_flexible_partner = False  # ✅ NOWE: Domyślna wartość w przypadku błędu
    
    return render_template('quotes/templates/quotes.html', 
                          prices_json=prices_json,
                          multipliers_json=multipliers_json,
                          user_role=user_role,
                          user_multiplier=user_multiplier,
                          user_client_type=user_client_type,
                          is_flexible_partner=is_flexible_partner)  # ✅ NOWY PARAMETR

@quotes_bp.route('/api/quotes')
@require_module_access('quotes')
def api_quotes():
    try:
        # Pobierz parametry paginacji z query string
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # Pobierz parametry filtrów
        quote_number = request.args.get('quote_number', '').strip()
        client_number = request.args.get('client_number', '').strip()
        client_name = request.args.get('client_name', '').strip()
        source = request.args.get('source', '').strip()
        employee_id = request.args.get('employee_id', type=int)
        user_role_filter = request.args.get('user_role', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        status_filter = request.args.get('status', '').strip()

        # Walidacja parametrów
        if page < 1:
            page = 1
        if per_page < 1 or per_page > 200:
            per_page = 20

        # Mapa statusów
        statuses = {
            s.name: {"id": s.id, "name": s.name, "color": s.color_hex}
            for s in QuoteStatus.query.all()
        }
        # ✅ NOWE: Filtrowanie per rola
        base_query = Quote.query.order_by(Quote.created_at.desc())
        filtered_query = get_filtered_quotes_query(base_query)

        # Dodaj filtry
        if quote_number:
            filtered_query = filtered_query.filter(Quote.quote_number.ilike(f'{quote_number}%'))

        # Sprawdź czy potrzebujemy join z Client
        need_client_join = bool(client_number or client_name)
        if need_client_join:
            filtered_query = filtered_query.join(Client, Quote.client_id == Client.id, isouter=True)
            if client_number:
                filtered_query = filtered_query.filter(Client.client_number.ilike(f'%{client_number}%'))
            if client_name:
                filtered_query = filtered_query.filter(Client.client_name.ilike(f'%{client_name}%'))

        if source:
            filtered_query = filtered_query.filter(Quote.source == source)

        if employee_id:
            filtered_query = filtered_query.filter(Quote.user_id == employee_id)

        # Filtrowanie po roli użytkownika (opiekuna wyceny)
        if user_role_filter:
            # Join z User tylko jeśli jeszcze nie został zrobiony
            filtered_query = filtered_query.join(User, Quote.user_id == User.id, isouter=True).filter(
                User.role == user_role_filter
            )

        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
                filtered_query = filtered_query.filter(Quote.created_at >= date_from_obj)
            except ValueError:
                pass

        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
                # Dodaj 1 dzień aby uwzględnić cały dzień
                date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59)
                filtered_query = filtered_query.filter(Quote.created_at <= date_to_obj)
            except ValueError:
                pass

        if status_filter:
            filtered_query = filtered_query.join(QuoteStatus, Quote.status_id == QuoteStatus.id, isouter=True).filter(
                QuoteStatus.name == status_filter
            )

        # Policz całkowitą liczbę wyników
        total_count = filtered_query.count()

        # Pobierz paginowane wyniki
        quotes = filtered_query.offset((page - 1) * per_page).limit(per_page).all()

        results = []
        for q in quotes:
            client = q.client
            user = q.user
            status_data = statuses.get(q.quote_status.name if q.quote_status else None, {})

            # POPRAWKA: Pobranie opiekuna wyceny (user_id z tabeli quotes)
            quote_caretaker_name = None
            if user:
                quote_caretaker_name = f"{user.first_name} {user.last_name}".strip()

            result = {
                "id": q.id,
                "quote_number": q.quote_number,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "client_number": client.client_number if client else None,
                "client_name": client.client_name if client else None,
                "client_caretaker_name": quote_caretaker_name,  # POPRAWIONE: teraz pokazuje użytkownika wyceny
                "user_id": user.id if user else None,
                "user_name": f"{user.first_name} {user.last_name}" if user else None,
                "source": q.source,
                "status_id": q.status_id,
                "status_name": status_data.get("name", ""),
                "status_color": status_data.get("color", "#ccc"),
                "all_statuses": statuses,
                "public_url": q.get_public_url(),
                "base_linker_order_id": q.base_linker_order_id,
                # DODANE: public_token do pobierania PDF
                "public_token": q.public_token
            }
            results.append(result)

        # Zwróć dane z informacjami o paginacji
        return jsonify({
            "quotes": results,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_count": total_count,
                "total_pages": (total_count + per_page - 1) // per_page  # Zaokrąglenie w górę
            }
        })
    except Exception as e:
        print(f"[api_quotes] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({"error": "Wystapil blad serwera"}), 500

@quotes_bp.route('/api/quotes/<int:quote_id>/status', methods=['PATCH'])
@require_module_access('quotes')
def update_quote_status(quote_id):
    try:
        data = request.get_json()
        status_id = data.get("status_id")

        if not status_id:
            return jsonify({"error": "Brak status_id w żądaniu"}), 400

        quote = Quote.query.get_or_404(quote_id)
        new_status = QuoteStatus.query.get_or_404(status_id)

        quote.status_id = new_status.id
        db.session.commit()

        return jsonify({"message": "Status updated successfully", "new_status": new_status.name})

    except Exception as e:
        print(f"[update_quote_status] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas aktualizacji statusu"}), 500


@quotes_bp.route("/api/quotes/<token>/pdf.<format>", methods=["GET"])
def generate_quote_pdf(token, format):
    
    try:
        if format not in ["pdf", "png"]:
            return {"error": "Unsupported format"}, 400

        # ZMIANA: Wyszukiwanie po tokenie zamiast ID
        quote = Quote.query.filter_by(public_token=token).first()
        if not quote:
            logger.warning(f"[generate_quote_pdf] Brak wyceny dla tokenu: {token}")
            return {"error": "Quote not found"}, 404

        # KLUCZOWE: Oblicz koszty (tak jak w send_email i get_client_quote_data)
        selected_items = [item for item in quote.items if item.is_selected]
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()

        # Podglądy (PNG + oczyszczony SVG) — wspólne dla pobrania PDF i maila
        preview_assets = build_quote_preview_assets(finishing_details, quote.quote_number)
        edges_images = preview_assets['edges_images']
        shape_images = preview_assets['shape_images']
        shape_svg_safe = preview_assets['shape_svg_safe']

        cost_products_netto = round(sum(item.get_total_price_netto() for item in selected_items), 2)
        cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in finishing_details), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        
        # Użyj funkcji calculate_costs_with_vat
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)

        # Funkcja pomocnicza do ładowania ikon
        def load_icon_as_base64(icon_name):
            try:
                # Opcja 1: Bezwzględna ścieżka od root aplikacji
                icons_path = os.path.join(
                    current_app.root_path,  # app/
                    'modules', 'quotes', 'static', 'img', icon_name
                )
                
                if os.path.exists(icons_path):
                    with open(icons_path, 'rb') as icon_file:
                        icon_data = base64.b64encode(icon_file.read()).decode('utf-8')
                    
                    ext = icon_name.split('.')[-1].lower()
                    mime_type = 'image/png' if ext == 'png' else 'image/svg+xml' if ext == 'svg' else 'image/jpeg'
                    
                    return f"data:{mime_type};base64,{icon_data}"
                else:
                    logger.warning(f"[PDF] Nie znaleziono ikony: {icons_path}")
                    return None
            except Exception as e:
                print(f"[PDF] Error loading icon {icon_name}: {e}", file=sys.stderr)
                return None

        # Załaduj wszystkie ikony
        icons = {
            'logo': load_icon_as_base64('logo.png'),
            'phone': load_icon_as_base64('phone.png'),
            'email': load_icon_as_base64('email.png'),
            'location': load_icon_as_base64('location.png'),
            'website': load_icon_as_base64('website.png'),
            'instagram': load_icon_as_base64('instagram.png'),
            'facebook': load_icon_as_base64('facebook.png'),
        }
        
        # KLUCZOWE: Dodaj koszty do obiektu quote lub przekaż jako osobny parametr
        quote.costs = costs  # Dodaj koszty do obiektu quote

        quote.finishing = finishing_details
        
        # Renderuj template z wszystkimi potrzebnymi danymi
        html_out = render_template("quotes/templates/offer_pdf.html",
                                 quote=quote,
                                 client=quote.client,
                                 user=quote.user,
                                 status=quote.quote_status,
                                 costs=costs,  # Przekaż też jako osobny parametr
                                 selected_items=selected_items,  # Dodaj selected_items
                                 finishing_details=finishing_details,  # Dodaj finishing_details
                                 edges_images=edges_images,  # PNG obrazy krawędzi
                                 shape_images=shape_images,  # PNG obrazy kształtów
                                 shape_svg_safe=shape_svg_safe,  # OCZYSZCZONY SVG kształtu (fallback dla |safe)
                                 icons=icons)
                
        # Utwórz HTML object z base_url dla względnych ścieżek
        html = HTML(string=html_out, base_url=request.url_root)
        out = BytesIO()

        if format == "pdf":
            html.write_pdf(out)
            content_type = "application/pdf"
        else:
            html.write_png(out)
            content_type = "image/png"

        out.seek(0)
        filename = f"Oferta_{quote.quote_number}.{format}"

        return make_response(out.read(), 200, {
            "Content-Type": content_type,
            "Content-Disposition": f"inline; filename=\"{filename}\""
        })

    except Exception as e:
        print(f"[generate_quote_pdf] Blad renderowania PDF: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {"error": "Render error"}, 500

@quotes_bp.route("/api/quotes/<int:quote_id>/send_email", methods=["POST"])
@require_module_access('quotes')
def send_email(quote_id):
    data = request.get_json()
    recipient_email = data.get("email")

    quote = db.session.get(Quote, quote_id)
    if not quote:
        return jsonify({"error": "Quote not found"}), 404

    client = db.session.get(Client, quote.client_id)
    user = db.session.get(User, quote.user_id)
    status = db.session.get(QuoteStatus, quote.status_id)

    # Pobierz wybrane produkty
    selected_items = [item for item in quote.items if item.is_selected]
    
    # Oblicz koszty
    cost_products_netto = round(sum(i.get_total_price_netto or 0 for i in selected_items), 2)
    cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
    cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
    costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)
    
    # Pobierz detale wykończenia
    finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
    
    # Załaduj ikony (opcjonalnie - można pominąć dla emaili)
    icons = {}  # Można dodać ikony jeśli potrzebne

    # Te same podglądy co przy pobieraniu PDF. Bez nich warunek {% if shape_images ... %}
    # w szablonie był ZAWSZE fałszywy i załącznik mailowy leciał gałęzią z surowym SVG
    # (WeasyPrint pobiera http(s) — SSRF z serwera CRM + piksel śledzący).
    preview_assets = build_quote_preview_assets(finishing_details, quote.quote_number)

    rendered = render_template("quotes/templates/offer_pdf.html",
                              quote=quote,
                              client=client,
                              user=user,
                              status=status,
                              costs=costs,
                              selected_items=selected_items,
                              finishing_details=finishing_details,
                              edges_images=preview_assets['edges_images'],
                              shape_images=preview_assets['shape_images'],
                              shape_svg_safe=preview_assets['shape_svg_safe'],
                              icons=icons)
    
    pdf_file = BytesIO()
    HTML(string=rendered).write_pdf(pdf_file)
    pdf_file.seek(0)

    msg = Message(subject=f"Wycena {quote.quote_number}",
                  sender=current_app.config['MAIL_USERNAME'],
                  recipients=[recipient_email])
    msg.body = f"Czesc, w zalczniku znajdziesz wycenę nr {quote.quote_number}."
    msg.attach(f"Oferta_{quote.quote_number}.pdf", "application/pdf", pdf_file.read())

    try:
        mail.send(msg)
        return jsonify({"success": True, "message": "Email wysłany pomyślnie"})
    except Exception as e:
        print(f"[send_email] Blad wysylki emaila: {str(e)}", file=sys.stderr)
        return jsonify({"error": "Błąd wysyłki emaila"}), 500

@quotes_bp.route('/api/quotes/status-counts')
@require_module_access('quotes')
def api_quotes_status_counts():
    try:
        # Wyciągamy wszystkie statusy
        statuses = QuoteStatus.query.all()

        # ✅ NOWE: Przygotuj bazowe query z filtrowaniem per rola
        base_query = db.session.query(Quote.status_id, func.count(Quote.id))
        
        # ✅ NOWE: Zastosuj filtrowanie (dla partnera tylko jego wyceny)
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id)
            if user and user.role == 'partner':
                # Partner widzi TYLKO swoje wyceny w licznikach
                base_query = base_query.filter(Quote.user_id == user_id)
        
        # Wykonaj query z grupowaniem
        counts_raw = base_query.group_by(Quote.status_id).all()
        count_map = {status_id: count for status_id, count in counts_raw}

        # Składamy wynik
        counts = []
        for status in statuses:
            counts.append({
                "id": status.id,
                "name": status.name,
                "count": count_map.get(status.id, 0),
                "color": status.color_hex
            })

        return jsonify(sorted(counts, key=lambda s: s["id"]))

    except Exception as e:
        print(f"[api_quotes_status_counts] Blad: {str(e)}", file=sys.stderr)
        return jsonify({"error": "Wystapil blad serwera"}), 500

@quotes_bp.route("/api/users")
@require_module_access('quotes')
def get_users():
    users = User.query.filter_by(active=True).order_by(User.first_name).all()
    return jsonify([
        {"id": user.id, "name": f"{user.first_name} {user.last_name}".strip()} for user in users
    ])

@quotes_bp.route("/api/roles")
@require_module_access('quotes')
def get_roles():
    """Zwraca listę unikalnych ról użytkowników dla filtra"""
    # Słownik mapujący wartości ról na czytelne etykiety
    role_labels = {
        'admin': 'Administrator',
        'user': 'Użytkownik',
        'partner': 'Partner'
    }

    # Pobierz unikalne role z bazy
    roles = db.session.query(User.role).filter(
        User.active == True,
        User.role.isnot(None)
    ).distinct().all()

    result = []
    for (role,) in roles:
        if role:
            result.append({
                "value": role,
                "label": role_labels.get(role, role.capitalize())
            })

    # Sortuj alfabetycznie po etykiecie
    result.sort(key=lambda x: x['label'])
    return jsonify(result)

@quotes_bp.route("/api/quotes/<int:quote_id>")
@require_module_access('quotes')
def get_quote_details(quote_id):
    
    try:
        # Pobierz wycenę z relacjami
        quote = db.session.query(Quote)\
            .options(
                joinedload(Quote.client),
                joinedload(Quote.user),
                joinedload(Quote.quote_status),
                joinedload(Quote.accepted_by_user)  # NOWA RELACJA
            )\
            .filter_by(id=quote_id).first()

        if not quote:
            logger.warning(f"[get_quote_details] Wycena {quote_id} nie znaleziona")
            return jsonify({"error": "Wycena nie znaleziona"}), 404

        # Pobierz szczegóły wykończenia
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote_id).all()

        # POPRAWKA: Pobierz items osobno (ponieważ lazy='dynamic')
        quote_items = quote.items.all()  # .all() na dynamic relationship
        
        # Analiza statystyczna
        show_values = [item.show_on_client_page for item in quote_items]
        selected_values = [item.is_selected for item in quote_items]
        
        # DEBUGOWANIE: Sprawdź to_dict() dla każdej pozycji
        items_data = []
        for i, item in enumerate(quote_items):
            item_dict = item.to_dict()
            items_data.append(item_dict)

        selected_items = [item for item in quote_items if item.is_selected]
        cost_products_netto = round(sum(item.get_total_price_netto() for item in selected_items), 2)
        cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in finishing_details), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)

        # Pobierz wszystkie statusy
        all_statuses = QuoteStatus.query.all()

        # NOWA LOGIKA: Sprawdź czy akceptacja była przez użytkownika wewnętrznego
        accepted_by_user = None
        if (quote.accepted_by_user_id and 
            quote.accepted_by_email and 
            quote.accepted_by_email.startswith('internal_user_')):
            accepted_by_user = quote.accepted_by_user

        return jsonify({
            "id": quote.id,
            "edit_uuid": quote.edit_uuid,
            "quote_number": quote.quote_number,
            "created_at": quote.created_at.isoformat() if quote.created_at else None,
            "source": quote.source,
            "status_id": quote.status_id,
            "status_name": quote.quote_status.name if quote.quote_status else None,
            "acceptance_date": quote.acceptance_date.isoformat() if quote.acceptance_date else None,
            "accepted_by_email": quote.accepted_by_email,
            "is_client_editable": quote.is_client_editable,
            "base_linker_order_id": quote.base_linker_order_id,
            "public_url": quote.get_public_url(),
            "notes": quote.notes or "",
            "attachment_filename": quote.attachment_filename,
            "attachment_stored_name": quote.attachment_stored_name,
            
            # ✅ NOWE: Informacja o trybie wyceny (brutto/netto)
            "quote_type": quote.quote_type if quote.quote_type else "brutto",

            # Informacje o użytkowniku akceptującym
            "accepted_by_user": {
                "id": accepted_by_user.id if accepted_by_user else None,
                "first_name": accepted_by_user.first_name if accepted_by_user else None,
                "last_name": accepted_by_user.last_name if accepted_by_user else None,
                "full_name": f"{accepted_by_user.first_name} {accepted_by_user.last_name}" if accepted_by_user else None
            } if accepted_by_user else None,
            
            # Informacje o mnożniku
            "quote_multiplier": float(quote.quote_multiplier) if quote.quote_multiplier else None,
            "quote_client_type": quote.quote_client_type,
            
            # Koszty
            "costs": costs,
            "cost_products": cost_products_netto,
            "cost_finishing": cost_finishing_netto,
            "cost_shipping": cost_shipping_brutto,
            "courier_name": quote.courier_name or "-",
            
            # Pozostałe pola
            "all_statuses": {s.name: {"id": s.id, "name": s.name, "color": s.color_hex} for s in all_statuses},
            "finishing": [d.to_dict() if hasattr(d, 'to_dict') else {
                "product_index": d.product_index,
                "finishing_type": d.finishing_type,
                "finishing_variant": d.finishing_variant,
                "finishing_color": d.finishing_color,
                "finishing_gloss_level": d.finishing_gloss_level,
                "finishing_price_netto": float(d.finishing_price_netto) if d.finishing_price_netto else 0.0,
                "finishing_price_brutto": float(d.finishing_price_brutto) if d.finishing_price_brutto else 0.0,
                "quantity": d.quantity or 1,
                # Dane obróbki krawędzi
                "edges_config": d.edges_config,
                "edges_type": d.edges_type,
                "edges_mode": d.edges_mode,
                "edges_r_value": d.edges_r_value,
                "edges_price_netto": float(d.edges_price_netto) if d.edges_price_netto else 0.0,
                "edges_price_brutto": float(d.edges_price_brutto) if d.edges_price_brutto else 0.0,
                "edges_svg": d.edges_svg,
                "cut_to_size": bool(d.cut_to_size) if d.cut_to_size is not None else True
            } for d in finishing_details],
            "client": {
                "id": quote.client.id if quote.client else None,
                "client_name": quote.client.client_number if quote.client else None,  # Nazwa klienta (login)
                "client_number": quote.client.client_number if quote.client else None,
                "company_name": quote.client.delivery_company if quote.client else None,
                "first_name": quote.client.client_name if quote.client else None,  # Imię i nazwisko
                "last_name": "",  # W bazie nie ma oddzielnych pól
                "email": quote.client.email if quote.client else None,
                "phone": quote.client.phone if quote.client else None,
                "nip": quote.client.invoice_nip if quote.client else None
            },
            "user": {
                "id": quote.user.id if quote.user else None,
                "first_name": quote.user.first_name if quote.user else "",
                "last_name": quote.user.last_name if quote.user else ""
            },
            "items": [item.to_dict() for item in quote_items]
        })

    except Exception as e:
        print(f"[get_quote_details] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd serwera"}), 500


@quotes_bp.route("/api/quotes/<int:quote_id>/update-quote-type", methods=['PATCH'])
@require_module_access('quotes')
def update_quote_type(quote_id):
    """Aktualizuje tryb wyceny (brutto/netto)"""
    try:
        quote = Quote.query.get_or_404(quote_id)
        
        data = request.get_json()
        new_quote_type = data.get('quote_type')
        
        # Walidacja
        if new_quote_type not in ['brutto', 'netto']:
            return jsonify({"error": "Nieprawidłowa wartość quote_type. Dozwolone: 'brutto' lub 'netto'"}), 400
        
        # Zapisz starą wartość dla logu
        old_quote_type = quote.quote_type or 'brutto'
        
        # Aktualizuj
        quote.quote_type = new_quote_type
        db.session.commit()
        
        # Log zmian
        current_user_id = session.get('user_id')
        if current_user_id:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=current_user_id,
                description=f"Zmieniono tryb wyceny z '{old_quote_type}' na '{new_quote_type}'"
            )
            db.session.add(log_entry)
            db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Tryb wyceny zmieniony na '{new_quote_type}'",
            "quote_type": new_quote_type
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[update_quote_type] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas aktualizacji trybu wyceny"}), 500


@quotes_bp.route("/api/quote_items/<int:item_id>/select", methods=["PATCH"])
@require_module_access('quotes')
def select_quote_item(item_id):
    try:
        item = QuoteItem.query.get_or_404(item_id)

        # Zresetuj wszystkie is_selected w tej grupie product_index
        QuoteItem.query.filter_by(quote_id=item.quote_id, product_index=item.product_index).update({QuoteItem.is_selected: False})

        # Ustaw nowy jako wybrany
        item.is_selected = True
        db.session.commit()

        return jsonify({"message": "Wariant ustawiony jako wybrany"})

    except Exception as e:
        print(f"[select_quote_item] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas wyboru wariantu"}), 500

@quotes_bp.route("/api/discount-reasons")
@require_module_access('quotes')
def get_discount_reasons():
    """Zwraca listę aktywnych powodów rabatów"""
    try:
        reasons = DiscountReason.get_active_reasons_dict()
        return jsonify(reasons)
    except Exception as e:
        print(f"[get_discount_reasons] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas pobierania powodów rabatów"}), 500

@quotes_bp.route("/api/quotes/<int:quote_id>/variant/<int:item_id>/discount", methods=["PATCH"])
@require_module_access('quotes')
def update_variant_discount(quote_id, item_id):
    """Aktualizuje rabat dla pojedynczego wariantu"""
    try:
        data = request.get_json()
        discount_percentage = data.get("discount_percentage", 0)
        reason_id = data.get("reason_id")
        show_on_client_page = data.get("show_on_client_page", True)

        # Walidacja danych
        if not isinstance(discount_percentage, (int, float)) or discount_percentage < -100 or discount_percentage > 100:
            return jsonify({"error": "Rabat musi być liczbą między -100 a 100"}), 400

        item = QuoteItem.query.filter_by(id=item_id, quote_id=quote_id).first_or_404()
        
        # Zastosuj rabat
        item.apply_discount(discount_percentage, reason_id)
        item.show_on_client_page = show_on_client_page
        
        db.session.commit()
                
        return jsonify({
            "message": "Rabat został zastosowany",
            "item": item.to_dict()
        })

    except Exception as e:
        print(f"[update_variant_discount] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas aktualizacji rabatu"}), 500

@quotes_bp.route("/api/quotes/<int:quote_id>/apply-total-discount", methods=["PATCH"])
@require_module_access('quotes')
def apply_total_discount(quote_id):
    """Zastosowuje rabat do wszystkich wariantów (nie tylko is_selected) w wycenie"""
    try:
        data = request.get_json()
        discount_percentage = data.get("discount_percentage", 0)
        reason_id = data.get("reason_id")
        include_finishing = data.get("include_finishing", False)

        # --- WALIDACJA RABATU ---
        if not isinstance(discount_percentage, (int, float)) or discount_percentage < -100 or discount_percentage > 100:
            return jsonify({"error": "Rabat musi być liczbą między -100 a 100"}), 400

        # --- POBIERAMY DANE WYceny ---
        quote = Quote.query.get_or_404(quote_id)

        # --- RABAT DO WSZYSTKICH WARIANTóW ---
        # W metodzie quote.apply_total_discount musi być już zmiana, która nie filtruje po is_selected,
        # tylko pobiera wszystkie QuoteItem z tej wyceny.
        affected_items = quote.apply_total_discount(discount_percentage, reason_id)

        # --- OPCJONALNY RABAT DO WYKOŃCZENIA ---
        if include_finishing and discount_percentage != 0:
            finishing_details = (
                db.session.query(QuoteItemDetails)
                .filter_by(quote_id=quote_id)
                .all()
            )
            for detail in finishing_details:
                if detail.finishing_price_netto is not None and detail.finishing_price_brutto is not None:
                    multiplier = 1 - (discount_percentage / 100)
                    detail.finishing_price_netto = detail.finishing_price_netto * multiplier
                    detail.finishing_price_brutto = detail.finishing_price_brutto * multiplier

        # --- ZAPIS DO BAZY ---
        db.session.commit()

        # --- ODPOWIEDŹ JSON ---
        return jsonify({
            "message": f"Rabat został zastosowany do {affected_items} pozycji",
            "affected_items": affected_items,
            "include_finishing": include_finishing,
            # Jeżeli masz w modelu metody get_total_discount_amount_netto / brutto, to możesz je tu zwrócić
            "total_discount_netto": quote.get_total_discount_amount_netto(),
            "total_discount_brutto": quote.get_total_discount_amount_brutto()
        }), 200

    except Exception as e:
        # loguj błąd na stderr i zwróć 500
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd podczas aktualizacji rabatu całkowitego"}), 500



# ============================================================
# STRONA KLIENTA (publiczna) — helpery wspólne dla widoku i API
# ============================================================

def build_quote_costs(quote):
    """
    Liczy koszty wyceny (produkty + wykończenie + wysyłka) razem z VAT.

    Jedno źródło prawdy dla API strony klienta i dla renderu szablonu —
    dzięki temu modal akceptacji pokazuje dokładnie te same kwoty,
    co podsumowanie wyceny.
    """
    products_netto = round(
        sum(i.get_total_price_netto() for i in quote.items if i.is_selected), 2
    )
    details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
    finishing_netto = round(
        sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in details),
        2
    )
    shipping_brutto = quote.shipping_cost_brutto or 0.0

    return calculate_costs_with_vat(products_netto, finishing_netto, shipping_brutto)


def flatten_costs_for_template(costs):
    """
    Szablon client_quote.html wstrzykuje do window.currentQuoteData PŁASKIE klucze
    total_netto / total_vat / total_brutto, a build_quote_costs zwraca strukturę
    zagnieżdżoną (używaną przez API). Dokładamy płaskie aliasy, zostawiając resztę.
    """
    flat = dict(costs or {})
    total = (costs or {}).get('total') or {}

    for key in ('netto', 'vat', 'brutto'):
        try:
            value = float(total.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        flat['total_' + key] = '{:.2f}'.format(value)

    return flat


def _safe_sanitize_svg(raw):
    """
    Sanitizer SVG nie może wywalić całej publicznej strony wyceny —
    w razie błędu po prostu nie pokazujemy podglądu.
    """
    try:
        return sanitize_svg(raw)
    except Exception as e:
        logger.warning(f"[_safe_sanitize_svg] Nie udało się oczyścić SVG: {e}")
        return None


def build_quote_preview_assets(finishing_details, quote_number=''):
    """
    Buduje podglądy kształtu / krawędzi dla PDF-a oferty (offer_pdf.html).

    Zwraca słownik trzech map, każda kluczowana po product_index:
      * edges_images   — PNG data URI widoku izometrycznego krawędzi
      * shape_images   — PNG data URI widoku kształtu
      * shape_svg_safe — OCZYSZCZONY SVG kształtu; szablon renderuje go przez
                         |safe, gdy konwersja na PNG się nie powiodła

    KLUCZOWE (bezpieczeństwo): kolumny quote_items_details.shape_svg / edges_svg
    zapisujemy do bazy verbatim, więc surowa wartość nie może trafić ANI do
    cairosvg (PNG), ANI do szablonu. Oba parsery pobierają zasoby po http(s)
    z serwera CRM — zapisane w wycenie <image xlink:href="http://atakujacy/x">
    daje żądanie wychodzące (SSRF + piksel śledzący), a WeasyPrint dodatkowo
    renderuje aktywną treść SVG. Dlatego KAŻDE wyjście przechodzi przez
    sanitize_svg (whitelist, fail-closed: None = brak podglądu, nie surowy SVG).

    Helper jest wspólny dla ścieżki pobrania PDF i ścieżki mailowej — mail
    wcześniej nie dostawał żadnej z map, więc zawsze wpadał w gałąź z surowym SVG.
    """
    from modules.baselinker.edges_pdf_generator import EdgesPdfGenerator

    pdf_gen = EdgesPdfGenerator(logger=logger)

    edges_images = {}
    shape_images = {}
    shape_svg_safe = {}

    for detail in finishing_details or []:
        index = getattr(detail, 'product_index', None)

        edges_raw = getattr(detail, 'edges_svg', None)
        if edges_raw:
            try:
                # Sanityzacja NAJPIERW, tuż przy źródle: dalej idzie już tylko
                # _ensure_dashed_lines, które dokłada stroke-dasharray i nie ma
                # jak wprowadzić URL-a. Kolejność 1:1 jak przed zmianą, żeby nie
                # ruszać profilu udanych/nieudanych konwersji cairosvg.
                edges_safe = _safe_sanitize_svg(edges_raw)
                png_data_uri = None
                if edges_safe:
                    svg_fixed = pdf_gen._ensure_dashed_lines(edges_safe)
                    png_data_uri = pdf_gen._svg_to_png_base64(svg_fixed, 300, preserve_aspect=True)
                if png_data_uri:
                    edges_images[index] = png_data_uri
                else:
                    logger.warning(f"[PDF {quote_number}] Poz {index}: edges PNG = None (sanitize/cairo fail) — bez podglądu")
            except Exception as e:
                logger.error(f"[PDF {quote_number}] Poz {index}: edges PNG BŁĄD: {e}", exc_info=True)

        shape_raw = getattr(detail, 'shape_svg', None)
        if shape_raw:
            try:
                shape_safe = _safe_sanitize_svg(shape_raw)
                if shape_safe:
                    # Fallback dla szablonu: inline SVG, ale JUŻ oczyszczony.
                    shape_svg_safe[index] = shape_safe
                png_data_uri = None
                if shape_safe:
                    png_data_uri = pdf_gen._svg_to_png_base64(shape_safe, 300, preserve_aspect=True)
                if png_data_uri:
                    shape_images[index] = png_data_uri
                else:
                    logger.warning(f"[PDF {quote_number}] Poz {index}: shape PNG = None (sanitize/cairo fail) — fallback inline SVG")
            except Exception as e:
                logger.error(f"[PDF {quote_number}] Poz {index}: shape PNG BŁĄD: {e}", exc_info=True)

    return {
        'edges_images': edges_images,
        'shape_images': shape_images,
        'shape_svg_safe': shape_svg_safe,
    }


def build_edges_config_with_labels(edges_config):
    """
    Dopisuje do każdego wpisu edges_config czytelną etykietę PL pod kluczem "label".

    Front zna tylko oznaczenia prostokąta (A-H, N1-N4), więc dla kształtów
    nieregularnych (G1/D1/P1) i krawędzi wycięć (H1.G2) etykietę liczymy na serwerze.
    Całość defensywnie: brak klucza "letter", nietypowy wpis albo błąd translatora
    nie może przerwać serializacji wyceny.
    """
    if not isinstance(edges_config, list):
        return edges_config

    result = []
    for entry in edges_config:
        if not isinstance(entry, dict):
            result.append(entry)
            continue

        enriched = dict(entry)
        letter = enriched.get('letter')
        if letter:
            try:
                label = human_edge_label(letter)
                # human_edge_label nie zna oznaczeń prostokąta (A-H) i oddaje wtedy
                # surowe ID — w takim wypadku sięgamy po pełną nazwę z definicji krawędzi
                if label == str(letter):
                    definition = EDGE_DEFINITIONS.get(letter)
                    if definition:
                        label = definition.get('name_full') or definition.get('name') or label
                enriched['label'] = label
            except Exception as e:
                logger.warning(f"[build_edges_config_with_labels] Nie udało się opisać krawędzi: {e}")

        result.append(enriched)

    return result


def build_client_finishing_entry(detail):
    """
    Buduje PUBLICZNY słownik wykończenia / krawędzi / kształtu dla strony klienta.

    Świadomie jawna biała lista pól — NIE używamy detail.to_dict(), bo wystawiłoby
    to publicznie dane wewnętrzne (id, quote_id, product_type,
    baselinker_order_product_id, round_surcharge_netto/brutto).
    Oba pola SVG przechodzą przez sanitizer.
    """
    return {
        "product_index": detail.product_index,
        "finishing_type": detail.finishing_type,
        "finishing_variant": detail.finishing_variant,
        "finishing_color": detail.finishing_color,
        "finishing_gloss_level": detail.finishing_gloss_level,
        "finishing_price_netto": float(detail.finishing_price_netto or 0),
        "finishing_price_brutto": float(detail.finishing_price_brutto or 0),
        "quantity": detail.quantity or 1,
        # Dane obróbki krawędzi
        "edges_config": build_edges_config_with_labels(detail.edges_config),
        "edges_type": detail.edges_type,
        "edges_mode": detail.edges_mode,
        "edges_r_value": detail.edges_r_value,
        "edges_angle_value": detail.edges_angle_value,
        "edges_price_netto": float(detail.edges_price_netto or 0),
        "edges_price_brutto": float(detail.edges_price_brutto or 0),
        "edges_svg": _safe_sanitize_svg(detail.edges_svg),
        # Kształt produktu (podgląd na stronie klienta)
        "shape": detail.shape,
        "shape_svg": _safe_sanitize_svg(detail.shape_svg),
        "shape_rotation": detail.shape_rotation,
        "cut_to_size": bool(detail.cut_to_size) if detail.cut_to_size is not None else True
    }


def bezpieczny_link_zamowienia(adres):
    """Do href wpuszczamy wyłącznie http/https. Poza tym None.

    Ta sama biała lista, którą ma modal zamawiania (client_accept_modal.js,
    bezpiecznyLinkZamowienia) — szablon obsługuje ścieżkę CZĘSTSZĄ: każde
    wejście na zamówioną wycenę, także po odświeżeniu strony. Wartość
    pochodzi z odpowiedzi BaseLinkera, więc ryzyko jest niskie, ale
    „javascript:..." w href wykonałoby się po kliknięciu, a jedno miejsce
    ze sprawdzeniem i drugie bez to zaproszenie do pomyłki.

    Świadomie ostrzej niż wersja w JS: wymagamy schematu wprost, więc adres
    względny i protokołowo-względny („//gdzies") też odpadają. BaseLinker
    zwraca w order_page pełny adres, więc nic poprawnego na tym nie tracimy.
    """
    if not adres:
        return None
    schemat = str(adres).split(':', 1)[0].strip().lower() if ':' in str(adres) else ''
    if schemat in ('http', 'https'):
        return adres
    logger.warning("[client_quote_view] Odrzucony link do zamówienia o schemacie %r",
                   schemat)
    return None


@quotes_bp.route("/c/<token>")
def client_quote_view(token):
    """Widok strony klienta z redesignem"""
    try:
        
        # Znajdź wycenę po tokenie
        quote = Quote.query.filter_by(public_token=token).first()
        
        if not quote:
            logger.warning(f"[client_quote_view] Nie znaleziono wyceny dla tokenu: {token}")
            return render_client_error(
                error_type='not_found',
                error_code=404,
                error_message="Nie znaleziono wyceny",
                error_details="Sprawdź czy link jest poprawny.",
                quote_number=None
            )
        
        quote_number = quote.quote_number
        
        # Przekazujemy dodatkowe dane potrzebne w nowym designie
        current_year = datetime.now().year

        # Koszty liczone identycznie jak w API strony klienta — szablon wstrzykuje je
        # do window.currentQuoteData, z którego korzysta modal akceptacji.
        # Bez tego modal widział 0.00 i zgadywał kwoty z DOM.
        try:
            costs = flatten_costs_for_template(build_quote_costs(quote))
        except Exception as e:
            logger.warning(f"[client_quote_view] Nie udało się policzyć kosztów dla {quote_number}: {e}")
            costs = None

        # Stany przycisku zamawiania. Sam `is_accepted` nie wystarcza: wycena
        # zaakceptowana, ale jeszcze niezamówiona, dostawała wyłącznie
        # zablokowany przycisk „Wycena zaakceptowana" i klient nie miał czym
        # zamówić — dokładnie tu utknął właściciel.
        ma_zamowienie = bool(quote.base_linker_order_id)
        # is_client_editable = wycena jeszcze nieprzyjęta; endpoint /order
        # zaakceptuje ją po drodze, więc zamówić się da. Wycena już przyjęta
        # idzie prosto do zamówienia i decyduje o niej ta sama reguła
        # kwalifikacji, co po stronie serwera (jedno źródło prawdy).
        mozna_zamowic = (not ma_zamowienie) and bool(
            quote.is_client_editable or quote.is_eligible_for_order())

        # Po próbie, po której nie wiemy, czy zamówienie powstało, przycisku
        # nie ma. Blokada w JavaScripcie znikała przy odświeżeniu strony —
        # a klient, który przeczytał „nie wiemy", odruchowo odświeża. Pytamy
        # bazę tylko wtedy, gdy przycisk faktycznie by się pokazał.
        from modules.quotes.services.checkout_service import (
            istnieje_nierozstrzygnieta_proba)
        niepewna_proba = bool(mozna_zamowic
                              and istnieje_nierozstrzygnieta_proba(quote.id))
        if niepewna_proba:
            mozna_zamowic = False

        return render_template("quotes/templates/client_quote.html",
                             quote=quote,
                             quote_number=quote_number,
                             token=token,
                             is_accepted=not quote.is_client_editable,
                             ma_zamowienie=ma_zamowienie,
                             mozna_zamowic=mozna_zamowic,
                             niepewna_proba=niepewna_proba,
                             link_zamowienia=bezpieczny_link_zamowienia(
                                 quote.baselinker_order_page),
                             costs=costs,
                             current_year=current_year)
        
    except Exception as e:
        print(f"[client_quote_view] BŁĄD: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        return render_client_error(
            error_type='general',
            error_code=500,
            error_message="Wystąpił nieoczekiwany błąd podczas ładowania wyceny.",
            error_details=str(e),
            quote_number=quote_number if 'quote_number' in locals() else None
        )

@quotes_bp.route("/api/client/quote/<token>")
def get_client_quote_data(token):
    """API dla strony klienta - rozszerzone dane dla redesignu"""
    try:
        quote = Quote.query.filter_by(public_token=token).first()
        
        if not quote:
            return jsonify({
                "error": "not_found", 
                "message": "Wycena nie została znaleziona"
            }), 404
        
        # Oblicz koszty (wspólny helper — ten sam, którego używa widok strony klienta)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        cost_shipping_netto = quote.shipping_cost_netto or 0.0
        costs = build_quote_costs(quote)
        
        # Pobierz wszystkie pozycje jeśli wycena jest zaakceptowana, 
        # w przeciwnym razie tylko te oznaczone jako widoczne
        if not quote.is_client_editable:
            visible_items = quote.items
        else:
            visible_items = [item for item in quote.items if item.show_on_client_page]
        
        # Pobierz szczegóły wykończenia
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
        
        # Przygotuj dane o wykończeniach z obrazkami
        finishing_data = []
        for detail in finishing_details:
            finishing_info = build_client_finishing_entry(detail)

            # Dodaj ścieżkę do obrazka jeśli istnieje kolor
            if detail.finishing_color and detail.finishing_color != 'Brak':
                # Sprawdź czy istnieje obrazek w bazie
                color_image = FinishingColor.query.filter_by(name=detail.finishing_color).first()
                if color_image and color_image.image_path:
                    finishing_info["image_path"] = color_image.image_path

            finishing_data.append(finishing_info)
        
        # Przygotuj dane pozycji z cenami jednostkowymi
        items_data = []
        for item in visible_items:
            item_dict = item.to_dict()
            
            # Upewnij się, że ceny są jednostkowe (nie całkowite)
            finishing = next((f for f in finishing_details if f.product_index == item.product_index), None)
            quantity = finishing.quantity if finishing else 1
            
            # Popraw ceny jeśli są już pomnożone przez ilość
            if quantity > 1:
                # Sprawdź czy cena jest już pomnożona
                if item_dict.get('final_price_netto'):
                    # Jeśli cena końcowa istnieje, użyj jej jako jednostkowej
                    item_dict['price_netto'] = item_dict['final_price_netto'] / quantity
                    item_dict['price_brutto'] = item_dict['final_price_brutto'] / quantity
            
            items_data.append(item_dict)
        
        return jsonify({
            "id": quote.id,
            "quote_number": quote.quote_number,
            "created_at": quote.created_at.isoformat() if quote.created_at else None,
            "is_client_editable": quote.is_client_editable,
            "acceptance_date": quote.acceptance_date.isoformat() if quote.acceptance_date else None,
            "costs": costs,
            "shipping_cost_netto": cost_shipping_netto,
            "shipping_cost_brutto": cost_shipping_brutto,
            "courier_name": quote.courier_name or "-",
            "status_name": quote.quote_status.name if quote.quote_status else "-",
            "client_comment": quote.client_comments,
            "items": items_data,
            "finishing": finishing_data,
            "public_token": token
        })
        
    except Exception as e:
        print(f"[get_client_quote_data] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "server_error", "message": str(e)}), 500

@quotes_bp.route("/api/client/quote/<token>/update-variant", methods=["PATCH"])
def client_update_variant(token):
    """Zmiana wariantu przez klienta - tylko dla edytowalnych wycen"""
    try:
        quote = Quote.query.filter_by(public_token=token).first_or_404()
        
        # POPRAWKA: Sprawdzamy czy wycena jest nadal edytowalna
        if not quote.is_client_editable:
            return jsonify({
                "error": "quote_not_editable", 
                "message": "Wycena została już zaakceptowana i nie można jej modyfikować"
            }), 403
        
        data = request.get_json()
        item_id = data.get("item_id")

        if not item_id:
            return jsonify({"error": "Brak wymaganych danych"}), 400

        item = QuoteItem.query.filter_by(id=item_id, quote_id=quote.id).first_or_404()
        if not item.show_on_client_page:
            return jsonify({"error": "Pozycja nie jest dostępna"}), 403

        # Odznacz wszystkie warianty w tej grupie i zaznacz wybrany
        QuoteItem.query.filter_by(quote_id=quote.id, product_index=item.product_index).update({QuoteItem.is_selected: False})
        item.is_selected = True
        db.session.commit()

        return jsonify({"message": "Wariant został zmieniony"})

    except Exception as e:
        print(f"[client_update_variant] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas zmiany wariantu"}), 500

@quotes_bp.route("/api/client/quote/<token>/accept", methods=["POST"])
def client_accept_quote(token):
    """Akceptacja wyceny przez klienta z rozszerzonymi danymi"""
    try:
        quote = Quote.query.filter_by(public_token=token).first()
        
        if not quote:
            return jsonify({"error": "not_found", "message": "Wycena nie została znaleziona"}), 404
        
        if not quote.is_client_editable:
            return jsonify({
                "error": "quote_not_editable", 
                "message": "Wycena została już zaakceptowana"
            }), 403
        
        data = request.get_json()
        email_or_phone = data.get("email_or_phone", "").strip()
        phone = data.get("phone", "").strip()  # Dodatkowe pole telefonu
        comments = data.get("comments", "").strip()
        
        if not email_or_phone:
            return jsonify({"error": "validation_error", "message": "Email jest wymagany"}), 400
        
        # Weryfikacja klienta
        client = quote.client
        if not client:
            return jsonify({"error": "client_error", "message": "Brak danych klienta"}), 400
        
        # Sprawdź email lub telefon
        client_email = (client.email or "").lower().strip()
        client_phone = (client.phone or "").replace(" ", "").replace("-", "")
        input_value = email_or_phone.lower().strip()
        input_phone = phone.replace(" ", "").replace("-", "") if phone else ""
        
        email_matches = input_value == client_email or input_value.endswith(client_email)
        phone_matches = input_phone and (input_phone in client_phone or client_phone in input_phone)
        
        if not (email_matches or phone_matches):
            return jsonify({
                "error": "verification_failed", 
                "message": "Podane dane nie pasują do danych klienta"
            }), 403
        
        # Zapisz komentarz jeśli podany
        if comments:
            quote.client_comments = comments
        
        # Ustaw datę akceptacji i status
        quote.acceptance_date = datetime.utcnow()
        quote.is_client_editable = False
        quote.accepted_by_email = email_or_phone
        
        # Zmień status na "Zaakceptowane" (ID=3) - spójne z accept-with-data
        quote.status_id = 3
        
        # Dodaj log
        log_entry = QuoteLog(
            quote_id=quote.id,
            user_id=None,  # Brak użytkownika - akcja klienta
            change_time=datetime.utcnow(),
            description=f"Wycena zaakceptowana przez klienta (email: {email_or_phone})"
        )
        db.session.add(log_entry)
        
        db.session.commit()

        # Wysłanie emaili z potwierdzeniem
        try:
            send_acceptance_emails(quote)
        except Exception as e:
            print(f"[client_accept_quote] Błąd wysyłki emaili: {e}", file=sys.stderr)

        return jsonify({
            "success": True,
            "message": "Wycena została zaakceptowana",
            "quote_number": quote.quote_number
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[client_accept_quote] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "server_error", "message": "Błąd podczas akceptacji wyceny"}), 500

def send_acceptance_email_to_salesperson(quote):
    """
    Wysyła email do sprzedawcy o akceptacji wyceny przez klienta
    
    Args:
        quote: Obiekt wyceny (Quote model)
    """
    if not quote.user or not quote.user.email:
        logger.warning(f"[send_acceptance_email_to_salesperson] Brak emaila sprzedawcy dla wyceny {quote.id}")
        return
    
    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()
        
        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto() or 0 for i in selected_items), 2)
        cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)

        # Pobierz detale wykończenia
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
        
        # Renderuj szablon HTML
        html_body = render_template('quote_accept_email.html', 
                                  quote=quote,
                                  selected_items=selected_items,
                                  finishing_details=finishing_details,
                                  costs=costs,
                                  acceptance_date=datetime.now(),
                                  base_url=current_app.config.get('BASE_URL', ''))
        
        # Przygotuj wiadomość
        msg = Message(
            subject=f"✅ Akceptacja wyceny {quote.quote_number}",
            sender=current_app.config['MAIL_USERNAME'],  # powiadomienia@woodpower.pl
            recipients=[quote.user.email],
            html=html_body
        )
        
        mail.send(msg)
        
    except Exception as e:
        print(f"[send_acceptance_email_to_salesperson] Błąd wysyłki maila do sprzedawcy: {e}", file=sys.stderr)
        raise

def send_acceptance_email_to_client(quote):
    """
    Wysyła email potwierdzający do klienta o akceptacji wyceny
    Email wysyłany z powiadomienia@woodpower.pl, ale Reply-To ustawione na opiekuna
    
    Args:
        quote: Obiekt wyceny (Quote model)
    """
    if not quote.client or not quote.client.email:
        logger.warning(f"[send_acceptance_email_to_client] Brak emaila klienta dla wyceny {quote.id}")
        return

    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()

        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto() or 0 for i in selected_items), 2)
        cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)

        # Pobierz detale wykończenia
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()

        # Renderuj szablon HTML dla klienta
        html_body = render_template('quote_accept_email_client.html',
                                  quote=quote,
                                  selected_items=selected_items,
                                  finishing_details=finishing_details,
                                  costs=costs,
                                  acceptance_date=datetime.now(),
                                  base_url=current_app.config.get('BASE_URL', ''))
        
        # Przygotuj wiadomość z Reply-To na opiekuna
        msg = Message(
            subject=f"✅ Potwierdzenie akceptacji wyceny {quote.quote_number} - Wood Power",
            sender=current_app.config['MAIL_USERNAME'],  # powiadomienia@woodpower.pl
            recipients=[quote.client.email],
            html=html_body
        )
        
        # Ustaw Reply-To na email opiekuna wyceny (jeśli istnieje)
        if quote.user and quote.user.email:
            msg.reply_to = quote.user.email
        
        mail.send(msg)
        
    except Exception as e:
        print(f"[send_acceptance_email_to_client] Błąd wysyłki maila do klienta: {e}", file=sys.stderr)
        raise

def send_acceptance_emails(quote):
    """
    Funkcja pomocnicza - wysyła oba emaile po akceptacji wyceny
    
    Args:
        quote: Obiekt wyceny (Quote model)
    """
    try:
        # Wyślij email do sprzedawcy
        send_acceptance_email_to_salesperson(quote)
    except Exception as e:
        print(f"[send_acceptance_emails] Błąd wysyłki maila do sprzedawcy: {e}", file=sys.stderr)
    
    try:
        # Wyślij email do klienta (jeśli ma podany email)
        send_acceptance_email_to_client(quote)
    except Exception as e:
        print(f"[send_acceptance_emails] Błąd wysyłki maila do klienta: {e}", file=sys.stderr)

@quotes_bp.route("/test-routing")
def test_quotes_routing():
    """Test czy quotes blueprint działa"""
    return "Quotes routing działa!"

# Add this route to app/modules/quotes/routers.py

@quotes_bp.route("/api/quotes/<int:quote_id>/update-quantity", methods=['PATCH'])
def update_quote_quantity(quote_id):
    """Aktualizuje ilość produktu w wycenie"""
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)
        
        # Pobierz dane z requestu
        data = request.get_json()
        product_index = data.get('product_index')
        new_quantity = data.get('quantity')
        
        # Walidacja danych
        if not product_index or not new_quantity:
            return jsonify({"error": "Brakuje wymaganych danych (product_index, quantity)"}), 400
        
        try:
            product_index = int(product_index)
            new_quantity = int(new_quantity)
        except (ValueError, TypeError):
            return jsonify({"error": "Nieprawidłowe wartości liczbowe"}), 400
        
        if new_quantity < 1:
            return jsonify({"error": "Ilość musi być większa od 0"}), 400
                
        # Znajdź szczegóły wykończenia dla danego produktu
        finishing_details = QuoteItemDetails.query.filter_by(
            quote_id=quote_id,
            product_index=product_index
        ).first()
        
        if not finishing_details:
            return jsonify({"error": f"Nie znaleziono szczegółów produktu {product_index}"}), 404
        
        # Zapisz starą ilość dla logowania
        old_quantity = finishing_details.quantity or 1
        
        # Aktualizuj ilość w QuoteItemDetails
        finishing_details.quantity = new_quantity
                
        # Zaloguj zmianę
        current_user_id = session.get('user_id')
        if current_user_id:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=current_user_id,
                description=f"Zmieniono ilość produktu {product_index} z {old_quantity} na {new_quantity} szt."
            )
            db.session.add(log_entry)
        
        # Zapisz zmiany
        db.session.commit()
                
        return jsonify({
            "message": "Ilość została zaktualizowana",
            "product_index": product_index,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[update_quote_quantity] Błąd podczas aktualizacji ilości: {e}", file=sys.stderr)
        return jsonify({
            "error": "Błąd podczas aktualizacji ilości",
            "message": str(e)
        }), 500
    

@quotes_bp.route('/api/quotes/<int:quote_id>/note', methods=['PATCH'])
@require_module_access('quotes')
def update_quote_note(quote_id):
    """Aktualizuje notatkę wyceny"""
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)

        # Sprawdź czy wycena nie jest już w Baselinkerze
        if quote.base_linker_order_id:
            return jsonify({
                "error": "Nie można edytować notatki - zamówienie zostało już złożone w Baselinker"
            }), 403

        # Pobierz dane z requestu
        data = request.get_json()
        new_note = data.get('notes', '').strip()

        # Walidacja długości (max 180 znaków)
        if len(new_note) > 180:
            return jsonify({
                "error": f"Notatka jest za długa ({len(new_note)} znaków). Maksymalna długość to 180 znaków."
            }), 400

        # Zapisz starą wartość dla logowania
        old_note = quote.notes or ''

        # Aktualizuj notatkę
        quote.notes = new_note

        # Zaloguj zmianę
        user_email = session.get('user_email')
        user = db.session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {'email': user_email}
        ).fetchone()

        if user:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=user.id,
                description=f"Zaktualizowano notatkę wyceny (długość: {len(new_note)} znaków)"
            )
            db.session.add(log_entry)

        # Zapisz zmiany
        db.session.commit()

        return jsonify({
            "message": "Notatka została zaktualizowana",
            "notes": new_note
        })

    except Exception as e:
        db.session.rollback()
        print(f"[update_quote_note] Błąd podczas aktualizacji notatki: {e}", file=sys.stderr)
        return jsonify({
            "error": "Błąd podczas aktualizacji notatki",
            "message": str(e)
        }), 500


def _check_quote_access(quote):
    """Sprawdza czy aktualny użytkownik ma dostęp do wyceny. Partner widzi tylko swoje."""
    user_id = session.get('user_id')
    if not user_id:
        return False
    user = User.query.get(user_id)
    if not user:
        return False
    if user.role == 'partner' and quote.user_id != user_id:
        return False
    return True


@quotes_bp.route('/api/quotes/<int:quote_id>/attachment', methods=['PATCH'])
@require_module_access('quotes')
def upload_quote_attachment(quote_id):
    """Upload lub podmiana załącznika wyceny"""
    try:
        quote = Quote.query.get_or_404(quote_id)

        if not _check_quote_access(quote):
            return jsonify({"error": "Brak dostępu do tej wyceny"}), 403

        if quote.base_linker_order_id:
            return jsonify({
                "error": "Nie można zmieniać załącznika - zamówienie zostało już złożone w Baselinker"
            }), 403

        file = request.files.get('attachment')
        if not file:
            return jsonify({"error": "Nie przesłano pliku"}), 400

        from modules.quotes.services.attachment_service import save_attachment
        success, error = save_attachment(file, quote)
        if not success:
            return jsonify({"error": error}), 400

        # Logowanie
        user_email = session.get('user_email')
        user = db.session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {'email': user_email}
        ).fetchone()

        if user:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=user.id,
                description=f"Dodano/zmieniono załącznik: {quote.attachment_filename}"
            )
            db.session.add(log_entry)

        db.session.commit()

        return jsonify({
            "message": "Załącznik został zapisany",
            "attachment": {
                "filename": quote.attachment_filename,
                "stored_name": quote.attachment_stored_name
            }
        })

    except Exception as e:
        db.session.rollback()
        print(f"[upload_quote_attachment] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas zapisywania załącznika"}), 500


@quotes_bp.route('/api/quotes/<int:quote_id>/attachment', methods=['DELETE'])
@require_module_access('quotes')
def delete_quote_attachment(quote_id):
    """Usunięcie załącznika wyceny"""
    try:
        quote = Quote.query.get_or_404(quote_id)

        if not _check_quote_access(quote):
            return jsonify({"error": "Brak dostępu do tej wyceny"}), 403

        if quote.base_linker_order_id:
            return jsonify({
                "error": "Nie można usunąć załącznika - zamówienie zostało już złożone w Baselinker"
            }), 403

        if not quote.attachment_filename:
            return jsonify({"error": "Wycena nie ma załącznika"}), 404

        from modules.quotes.services.attachment_service import delete_attachment
        old_filename = quote.attachment_filename
        delete_attachment(quote)

        # Logowanie
        user_email = session.get('user_email')
        user = db.session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {'email': user_email}
        ).fetchone()

        if user:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=user.id,
                description=f"Usunięto załącznik: {old_filename}"
            )
            db.session.add(log_entry)

        db.session.commit()

        return jsonify({"message": "Załącznik został usunięty"})

    except Exception as e:
        db.session.rollback()
        print(f"[delete_quote_attachment] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas usuwania załącznika"}), 500


@quotes_bp.route('/api/attachment/<path:stored_name>', methods=['GET'])
@require_module_access('quotes')
def get_quote_attachment(stored_name):
    """Serwuje plik załącznika po nazwie pliku na dysku (UUID + nazwa)"""
    try:
        quote = Quote.query.filter_by(attachment_stored_name=stored_name).first()
        if not quote:
            return jsonify({"error": "Załącznik nie został znaleziony"}), 404

        if not _check_quote_access(quote):
            return jsonify({"error": "Brak dostępu do tej wyceny"}), 403

        from modules.quotes.services.attachment_service import UPLOAD_FOLDER
        filepath = os.path.join(UPLOAD_FOLDER, quote.attachment_stored_name)

        if not os.path.exists(filepath):
            return jsonify({"error": "Plik załącznika nie został znaleziony na serwerze"}), 404

        return send_from_directory(
            UPLOAD_FOLDER,
            quote.attachment_stored_name,
            download_name=quote.attachment_filename,
            as_attachment=False
        )

    except Exception as e:
        print(f"[get_quote_attachment] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd podczas pobierania załącznika"}), 500


@quotes_bp.route('/api/quotes/<int:quote_id>/reassign-client', methods=['PATCH'])
@require_module_access('quotes')
def reassign_quote_client(quote_id):
    """
    Przepina wycenę pod innego klienta i aktualizuje jego dane.
    Używane gdy użytkownik wpisuje email istniejącego klienta w formularzu Baselinker.
    """
    try:
        quote = Quote.query.get_or_404(quote_id)
        data = request.get_json()

        new_client_id = data.get('new_client_id')
        client_data = data.get('client_data', {})

        if not new_client_id:
            return jsonify({"error": "Brak ID nowego klienta"}), 400

        new_client = Client.query.get_or_404(new_client_id)
        old_client_id = quote.client_id

        # Przepnij wycenę pod nowego klienta
        quote.client_id = new_client_id

        # Zaktualizuj dane klienta na podstawie formularza
        if client_data:
            # Nazwa klienta/firmy - NIE nadpisujemy client_number, bo jest unikalny i już istnieje
            # Tylko aktualizujemy jeśli klient go nie ma (co nie powinno się zdarzyć)

            # Imię i nazwisko (client_name w bazie = imię i nazwisko osoby kontaktowej)
            client_delivery_name = client_data.get('client_delivery_name', '').strip()
            if client_delivery_name:
                new_client.client_name = client_delivery_name

            # Kontakt
            new_client.phone = client_data.get('phone', '').strip()
            # Email nie zmieniamy - to właśnie po nim znaleźliśmy tego klienta

            # Dane dostawy
            delivery = client_data.get('delivery', {})
            new_client.delivery_name = delivery.get('name', '').strip()
            new_client.delivery_company = delivery.get('company', '').strip()
            new_client.delivery_address = delivery.get('address', '').strip()
            new_client.delivery_zip = delivery.get('zip', '').strip()
            new_client.delivery_city = delivery.get('city', '').strip()
            new_client.delivery_region = delivery.get('region', '').strip()
            new_client.delivery_country = delivery.get('country', '').strip()

            # Dane do faktury
            invoice = client_data.get('invoice', {})
            new_client.invoice_name = invoice.get('name', '').strip()
            new_client.invoice_company = invoice.get('company', '').strip()
            new_client.invoice_address = invoice.get('address', '').strip()
            new_client.invoice_zip = invoice.get('zip', '').strip()
            new_client.invoice_city = invoice.get('city', '').strip()
            new_client.invoice_nip = invoice.get('nip', '').strip()

        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Wycena została przepięta do klienta: {new_client.client_name or new_client.client_number}",
            "new_client_id": new_client_id
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"[reassign_quote_client] Błąd: {e}", file=sys.stderr)
        print(f"[reassign_quote_client] Traceback: {traceback.format_exc()}", file=sys.stderr)
        return jsonify({
            "error": "Błąd podczas przepinania klienta",
            "message": str(e)
        }), 500


@quotes_bp.route('/api/quotes/<int:quote_id>/user-accept', methods=['POST'])
@require_module_access('quotes')
def user_accept_quote(quote_id):
    """Akceptacja wyceny przez użytkownika wewnętrznego (opiekuna oferty)"""
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)
        
        # Pobierz aktualnego użytkownika
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        
        if not user:
            return jsonify({"error": "Nie znaleziono użytkownika"}), 401
        
        # Sprawdź czy wycena nie została już zaakceptowana
        if not quote.is_client_editable:
            return jsonify({
                "error": "Wycena została już zaakceptowana",
                "message": "Ta wycena została już wcześniej zaakceptowana"
            }), 403
                
        # Znajdź status "Zaakceptowane" (ID 3)
        accepted_status = QuoteStatus.query.filter_by(id=3).first()
        if not accepted_status:
            # Fallback - spróbuj różne nazwy
            accepted_status = QuoteStatus.query.filter(
                QuoteStatus.name.in_(["Zaakceptowane", "Zaakceptowana", "Accepted", "Zatwierdzone"])
            ).first()
        
        if not accepted_status:
            logger.error("[user_accept_quote] Nie znaleziono statusu akceptacji w bazie")
            return jsonify({"error": "Błąd konfiguracji statusów"}), 500
        
        # Zaktualizuj wycenę
        old_status_id = quote.status_id
        quote.status_id = accepted_status.id
        quote.is_client_editable = False
        
        # NOWA LOGIKA: Wypełnij pola akceptacji przez użytkownika wewnętrznego
        quote.accepted_by_user_id = user.id  # AKTYWACJA TEJ KOLUMNY
        
        # Sprawdź czy nie było wcześniejszej akceptacji przez klienta
        if not quote.acceptance_date:  
            # Jeśli nie było akceptacji przez klienta, ustaw datę akceptacji przez użytkownika
            quote.acceptance_date = datetime.now()
            quote.accepted_by_email = f"internal_user_{user.id}"  # Oznaczenie akceptacji wewnętrznej
        else:
            # Jeśli była już akceptacja przez klienta, dodaj oznaczenie że użytkownik też zaakceptował
            quote.accepted_by_email = f"internal_user_{user.id}"
                
        # Zapisz zmiany
        try:
            db.session.commit()
        except Exception as e:
            print(f"[user_accept_quote] BŁĄD podczas zapisu: {e}", file=sys.stderr)
            db.session.rollback()
            return jsonify({"error": "Błąd zapisu do bazy danych"}), 500
        
        # Wyślij email do klienta o akceptacji wyceny przez opiekuna
        try:
            if quote.client and quote.client.email:
                send_user_acceptance_email_to_client(quote, user)
        except Exception as e:
            print(f"[user_accept_quote] Błąd wysyłki maila: {e}", file=sys.stderr)
        
        return jsonify({
            "message": "Wycena została zaakceptowana przez opiekuna",
            "acceptance_date": quote.acceptance_date.isoformat() if quote.acceptance_date else None,
            "accepted_by_user": f"{user.first_name} {user.last_name}",
            "accepted_by_user_id": user.id,
            "new_status": accepted_status.name,
            "new_status_id": accepted_status.id
        })
        
    except Exception as e:
        print(f"[user_accept_quote] WYJĄTEK: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        db.session.rollback()
        return jsonify({"error": "Błąd podczas akceptacji wyceny"}), 500


def send_user_acceptance_email_to_client(quote, accepting_user):
    """
    Wysyła email do klienta o akceptacji wyceny przez opiekuna oferty
    
    Args:
        quote: Obiekt wyceny (Quote model)
        accepting_user: Użytkownik który zaakceptował wycenę
    """
    if not quote.client or not quote.client.email:
        logger.warning(f"[send_user_acceptance_email_to_client] Brak emaila klienta dla wyceny {quote.id}")
        return
    
    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()

        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto() or 0 for i in selected_items), 2)
        cost_finishing_netto = round(sum(float(d.finishing_price_netto or 0) + float(d.edges_price_netto or 0) for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)

        # Pobierz detale wykończenia
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
        
        # Renderuj szablon HTML dla klienta (podobny do istniejącego)
        html_body = render_template('quote_accept_email_client.html', 
                                  quote=quote,
                                  selected_items=selected_items,
                                  finishing_details=finishing_details,
                                  costs=costs,
                                  acceptance_date=datetime.now(),
                                  accepting_user=accepting_user,  # Dodatkowy parametr
                                  acceptance_by='user',  # Oznaczenie że to akceptacja przez użytkownika
                                  base_url=current_app.config.get('BASE_URL', ''))
        
        # Przygotuj wiadomość
        msg = Message(
            subject=f"✅ Wycena {quote.quote_number} została zaakceptowana - Wood Power",
            sender=current_app.config['MAIL_USERNAME'],  # powiadomienia@woodpower.pl
            recipients=[quote.client.email],
            html=html_body
        )
        
        # Ustaw Reply-To na email akceptującego użytkownika
        if accepting_user.email:
            msg.reply_to = accepting_user.email
        
        mail.send(msg)
        
    except Exception as e:
        print(f"[send_user_acceptance_email_to_client] Błąd wysyłki maila do klienta: {e}", file=sys.stderr)
        raise

def dopasowanie_danych_klienta(client, email, phone):
    """Zwraca (email_pasuje, telefon_pasuje) dla danych podanych przez klienta.

    Wydzielone z client_accept_quote_with_data, żeby checkout używał DOKŁADNIE
    tej samej reguły tożsamości i żeby dała się przetestować bez Flaska.

    Świadomie zwracamy PARĘ, a nie jeden bool: akceptacja używa obu flag osobno
    (zgodność telefonu pozwala uzupełnić telefon, ale NIE nadpisać adresu email,
    na który idzie mail z akceptacją). Sklejenie ich otwierałoby przejęcie
    adresu przez kogoś, kto zna tylko numer telefonu.
    """
    client_email = (client.email or "").lower().strip()
    client_phone_digits = re.sub(r'[^\d]', '', client.phone or '')
    input_email = (email or "").lower().strip()
    input_phone_digits = re.sub(r'[^\d]', '', phone or '')

    # Usuń +48 z początku jeśli istnieje
    if input_phone_digits.startswith('48') and len(input_phone_digits) > 9:
        input_phone_digits = input_phone_digits[2:]
    if client_phone_digits.startswith('48') and len(client_phone_digits) > 9:
        client_phone_digits = client_phone_digits[2:]

    email_matches = bool(client_email) and input_email == client_email
    phone_matches = bool(
        client_phone_digits and input_phone_digits and
        len(input_phone_digits) >= 9 and
        (input_phone_digits == client_phone_digits or
         input_phone_digits in client_phone_digits or
         client_phone_digits in input_phone_digits)
    )
    return email_matches, phone_matches


def dane_pasuja_do_klienta(client, email, phone):
    """Bramka tożsamości: email LUB telefon musi zgadzać się z klientem wyceny."""
    email_matches, phone_matches = dopasowanie_danych_klienta(client, email, phone)
    return email_matches or phone_matches


@quotes_bp.route("/api/client/quote/<token>/accept-with-data", methods=["POST"])
def client_accept_quote_with_data(token):
    """Akceptacja wyceny przez klienta z pełnymi danymi - ROZSZERZONA WERSJA"""
    try:
        data = request.get_json()
        
        quote = Quote.query.filter_by(public_token=token).first()
        if not quote:
            return jsonify({"error": "Nie znaleziono wyceny"}), 404
        
        if not quote.is_client_editable:
            return jsonify({"error": "Wycena została już zaakceptowana"}), 400
        
        # === WALIDACJA DANYCH ===

        # Wymagane dane kontaktowe
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()

        if not email:
            return jsonify({"error": "Email jest wymagany"}), 400

        if not phone:
            return jsonify({"error": "Numer telefonu jest wymagany"}), 400

        # Walidacja formatu email
        import re
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, email):
            return jsonify({"error": "Nieprawidłowy format adresu email"}), 400

        # Walidacja telefonu (tylko długość)
        phone_digits = re.sub(r'[^\d]', '', phone)
        if len(phone_digits) < 9 or len(phone_digits) > 15:
            return jsonify({"error": "Nieprawidłowy numer telefonu"}), 400

        # Pobierz dodatkowe dane z formularza
        is_self_pickup = data.get('is_self_pickup', False)
        wants_invoice = data.get('wants_invoice', False)
        invoice_nip = data.get('invoice_nip', '').strip() if wants_invoice else None

        # === KRYTYCZNA WALIDACJA BEZPIECZEŃSTWA ===
        # Sprawdź czy podany email LUB telefon pasuje do danych w bazie

        client = quote.client
        if not client:
            return jsonify({"error": "Brak przypisanego klienta do wyceny"}), 400

        # Zgodność email LUB telefonu — jedna reguła wspólna z checkoutem
        # (dopasowanie_danych_klienta wyżej w tym pliku). Obie flagi są potrzebne
        # osobno: niżej decydują, które pole klienta wolno uzupełnić.
        email_matches, phone_matches = dopasowanie_danych_klienta(client, email, phone)

        if not (email_matches or phone_matches):
            return jsonify({
                "error": "Podane dane nie pasują do danych przypisanych do tej wyceny. Sprawdź email lub numer telefonu."
            }), 403

        # === UZUPEŁNIENIE/AKTUALIZACJA DANYCH ===
        # Aktualizuj dane klienta - uzupełnij brakujące lub zaktualizuj istniejące

        # Jeśli email się zgadza lub jest pusty w bazie, użyj nowego
        if email_matches or not client.email:
            client.email = email

        # Jeśli telefon się zgadza lub jest pusty w bazie, użyj nowego
        if phone_matches or not client.phone:
            # Normalizacja telefonu - usuń spacje i myślniki
            normalized_phone = re.sub(r'[\s\-\(\)]', '', phone)
            if normalized_phone.startswith('+48'):
                normalized_phone = normalized_phone[3:]
            client.phone = normalized_phone
        
        # === DANE DOSTAWY ===
        # UWAGA (stan zastany, świadomie nietknięty). Bramka wyżej przepuszcza
        # na zgodność SAMEGO telefonu, a poniżej adres dostawy bierze się
        # w całości z żądania. Adres e-mail klienta jest broniony osobną flagą
        # (email_matches), adres dostawy — nie, bo klient wpisuje go w modalu
        # i inaczej być nie może.
        # Co się zmieniło: dotąd zgodność samego telefonu pozwalała najwyżej
        # OZNACZYĆ wycenę jako zaakceptowaną. Odkąd ta sama ścieżka tworzy
        # zamówienie w BaseLinkerze, pozwala WYSŁAĆ TOWAR pod wskazany adres.
        # Ryzyko zależy więc od jakości danych w clients.phone — decyzja
        # właściciela, osobny tor (patrz też dopasowanie przez podciąg
        # w dopasowanie_danych_klienta).
        if not is_self_pickup:
            client.delivery_name = data.get('delivery_name', '').strip()
            client.delivery_company = data.get('delivery_company', '').strip()
            client.delivery_address = data.get('delivery_address', '').strip()
            client.delivery_zip = data.get('delivery_postcode', '').strip()
            client.delivery_city = data.get('delivery_city', '').strip()
            client.delivery_region = data.get('delivery_region', '').strip()
            client.delivery_country = 'Polska'
            
        else:
            # Oznacz jako odbiór osobisty
            client.delivery_name = client.client_name or email
            client.delivery_address = 'ODBIÓR OSOBISTY'
            client.delivery_city = 'ODBIÓR OSOBISTY'
            client.delivery_company = ''
            client.delivery_zip = ''
            client.delivery_region = ''
            client.delivery_country = 'Polska'
                    
        # === DANE DO FAKTURY ===
        if wants_invoice:
            client.invoice_name = data.get('invoice_name', '').strip()
            client.invoice_company = data.get('invoice_company', '').strip()
            client.invoice_address = data.get('invoice_address', '').strip()
            client.invoice_zip = data.get('invoice_postcode', '').strip()
            client.invoice_city = data.get('invoice_city', '').strip()
            client.invoice_nip = invoice_nip
            
        else:
            # Wyczyść dane faktury jeśli nie chce faktury
            client.invoice_name = None
            client.invoice_company = None
            client.invoice_address = None
            client.invoice_zip = None
            client.invoice_city = None
            client.invoice_nip = None
                    
        # === UWAGI ===
        comments = data.get('comments', '').strip()
        quote.client_comments = comments if comments else None
        
        # === ZMIANA STATUSU WYCENY ===
        
        # Znajdź status "Zaakceptowane" 
        from modules.quotes.models import QuoteStatus
        accepted_status = QuoteStatus.query.filter_by(id=3).first()
        if not accepted_status:
            # Fallback - spróbuj różne nazwy
            accepted_status = QuoteStatus.query.filter(
                QuoteStatus.name.in_(["Zaakceptowane", "Zaakceptowana", "Accepted", "Zatwierdzone"])
            ).first()
        
        if not accepted_status:
            logger.error("[client_accept_quote_with_data] Nie znaleziono statusu akceptacji w bazie")
            return jsonify({"error": "Błąd konfiguracji statusów"}), 500
        
        # Aktualizuj wycenę
        old_status_id = quote.status_id
        quote.status_id = accepted_status.id
        quote.is_client_editable = False
        quote.acceptance_date = datetime.now()
        quote.accepted_by_email = email
                
        # === ZAPISZ ZMIANY ===
        try:
            db.session.commit()
        except Exception as e:
            print(f"[client_accept_quote_with_data] BŁĄD podczas zapisu: {e}", file=sys.stderr)
            db.session.rollback()
            return jsonify({"error": "Błąd zapisu do bazy danych"}), 500

        # === WYŚLIJ EMAILE POWIADOMIENIA ===
        try:
            send_acceptance_emails(quote)
        except Exception as e:
            print(f"[client_accept_quote_with_data] Błąd wysyłki maili: {e}", file=sys.stderr)
            # Nie przerywaj procesu z powodu błędu emaila
        
        # === PRZYGOTUJ ODPOWIEDŹ ===
        response_data = {
            "message": "Wycena została zaakceptowana pomyślnie",
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
            "acceptance_date": quote.acceptance_date.isoformat(),
            "client_updated": True,
            "new_status": accepted_status.name,
            "new_status_id": accepted_status.id,
            "delivery_method": "Odbiór osobisty" if is_self_pickup else "Dostawa kurierska",
            "invoice_requested": wants_invoice,
            "redirect_url": f"/quotes/c/{quote.public_token}?accepted=true"
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[client_accept_quote_with_data] WYJĄTEK: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        db.session.rollback()
        return jsonify({"error": "Wystąpił błąd podczas przetwarzania żądania"}), 500

KONTAKT_WOODPOWER = "biuro@woodpower.pl lub telefonicznie +48 690 002 109"


def komunikat_bledu_zamowienia(numer_wyceny, niepewne, zamowienie_utworzone=False):
    """Zdanie dla klienta po nieudanej próbie złożenia zamówienia.

    Rozstrzyga to, co klient naprawdę chce wiedzieć: czy zamówienie powstało.

    Bierze SAM NUMER wyceny, a nie obiekt: w tych ścieżkach sesja bazy bywa po
    rollbacku i sięgnięcie po atrybut wyceny potrafi wystrzelić kolejnym błędem
    — akurat w miejscu, w którym mamy klientowi powiedzieć prawdę.

    zamowienie_utworzone=True — addOrder potwierdził, zamówienie ISTNIEJE, padł
    dopiero zapis po naszej stronie. Nie wolno powiedzieć ani „nie powstało",
    ani „nie wiemy": mówimy wprost, że zamówienie jest, i prosimy o kontakt.

    niepewne=False — żądanie nie wyszło albo BaseLinker je odrzucił: zamówienia
    NA PEWNO nie ma i powtórka jest bezpieczna.

    niepewne=True — łączność padła w trakcie: zamówienie mogło powstać po
    stronie BaseLinkera, a my nie mamy jak tego stwierdzić (numer zamówienia
    nie zapisał się na wycenie). Komunikat NIE MOŻE wtedy twierdzić ani
    „zamówiliśmy", ani „nie zamówiliśmy" — i musi odwieść od ponowienia,
    bo drugie kliknięcie to drugie REALNE zamówienie w BaseLinkerze.
    """
    numer = numer_wyceny or "-"
    if zamowienie_utworzone:
        return (
            "Twoje zamówienie zostało złożone, ale nie udało nam się zapisać go "
            "do końca po naszej stronie. Prosimy: nie składaj go ponownie. "
            "Skontaktuj się z nami — {kontakt} — i podaj numer wyceny {numer}. "
            "Prześlemy potwierdzenie i dane do płatności.".format(
                kontakt=KONTAKT_WOODPOWER, numer=numer)
        )
    if niepewne:
        return (
            "Straciliśmy łączność z systemem zamówień i nie wiemy, czy Twoje "
            "zamówienie zostało przyjęte. Prosimy: nie składaj go ponownie. "
            "Skontaktuj się z nami — {kontakt} — i podaj numer wyceny {numer}. "
            "Sprawdzimy to i potwierdzimy.".format(kontakt=KONTAKT_WOODPOWER, numer=numer)
        )
    return (
        "Nie udało się złożyć zamówienia — NIE zostało złożone. Spróbuj ponownie "
        "za kilka minut. Jeśli to nie pomoże, skontaktuj się z nami — {kontakt} — "
        "i podaj numer wyceny {numer}.".format(kontakt=KONTAKT_WOODPOWER, numer=numer)
    )


@quotes_bp.route("/api/client/quote/<token>/order", methods=["POST"])
def client_place_order(token):
    """Klient składa zamówienie ze strony wyceny.

    Akceptacja wyceny (dane klienta, status, maile) idzie tą samą ścieżką co
    /accept-with-data; następnie tworzymy zamówienie w BaseLinkerze i zwracamy
    link do strony zamówienia. Idempotencja siedzi w checkout_service — tu
    NIE dokładamy własnej, żeby nie było dwóch reguł na jedno zamówienie.
    """
    from modules.quotes.services.checkout_config import ID_ZRODLA_DEBUS
    from modules.quotes.services.checkout_service import zloz_zamowienie_klienta

    data = request.get_json(silent=True) or {}

    if not data.get("akceptacja_regulaminu"):
        return jsonify({"error": "Wymagana akceptacja warunków zamówienia"}), 400

    quote = Quote.query.filter_by(public_token=token).first()
    if not quote:
        return jsonify({"error": "Nie znaleziono wyceny"}), 404

    # Numer wyceny czytamy TERAZ, dopóki sesja bazy jest na pewno zdrowa —
    # ścieżki błędu niżej bywają wołane po rollbacku i wtedy odczyt atrybutu
    # z wyceny potrafi rzucić kolejnym wyjątkiem.
    numer_wyceny = quote.quote_number

    client = quote.client
    if not client:
        return jsonify({"error": "Brak przypisanego klienta do wyceny"}), 400

    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not dane_pasuja_do_klienta(client, email, phone):
        return jsonify({
            "error": "Podane dane nie pasują do danych przypisanych do tej wyceny. "
                     "Sprawdź email lub numer telefonu."
        }), 403

    # Konfigurację sprawdzamy PRZED akceptacją. Gdyby szła po niej, brak źródła
    # zostawiałby wycenę zaakceptowaną (z mailami do klienta i handlowca), ale
    # bez zamówienia — czyli w stanie, w który klient sam się wepchnął, a nie
    # w takim, o który prosił.
    # Szukamy po baselinker_id, a NIE po nazwie: nazwa źródła jest polem
    # redagowalnym w panelu BaseLinkera, więc wiązanie się z nią znaczyło, że
    # przemianowanie źródła kładzie cały checkout. Nie filtrujemy też po
    # is_active — to flaga widoczności na listach w panelu CRM, a nie
    # włącznik składania zamówień.
    zrodlo = BaselinkerConfig.query.filter_by(
        config_type="order_source", baselinker_id=ID_ZRODLA_DEBUS).first()
    if not zrodlo:
        logger.error("[client_place_order] Brak źródła zamówień o baselinker_id=%s "
                     "w baselinker_config — nie wykonała się migracja?", ID_ZRODLA_DEBUS)
        return jsonify({
            "error": komunikat_bledu_zamowienia(numer_wyceny, niepewne=False),
            "niepewne": False,
            "zamowienie_utworzone": False,
            "quote_number": numer_wyceny,
        }), 503

    # Kwalifikacja — również PRZED akceptacją, z tego samego powodu co źródło.
    # Pełnego is_eligible_for_order() nie da się tu wywołać: wymaga statusu 3,
    # który nadaje dopiero akceptacja. Sprawdzamy więc te warunki, których
    # akceptacja NIE zmienia (zaznaczone pozycje, klient, dane kontaktowe) —
    # bez tego wycena bez pozycji zostawała zaakceptowana wraz z mailami do
    # klienta i handlowca, a klient zaraz potem czytał, że zamówić się nie da.
    # Wycena, która ma już zamówienie, celowo NIE jest tu odrzucana: to
    # powtórka, którą checkout_service obsługuje jako duplikat.
    if not quote.base_linker_order_id and not quote.ma_dane_do_zamowienia():
        logger.warning("[client_place_order] Wycena %s nie kwalifikuje się do "
                       "zamówienia — odmowa przed akceptacją", numer_wyceny)
        return jsonify({
            "error": "Tej wyceny nie można zamówić przez stronę. Skontaktuj się "
                     "z nami — {kontakt} — i podaj numer wyceny {numer}.".format(
                         kontakt=KONTAKT_WOODPOWER, numer=numer_wyceny or "-"),
            "niepewne": False,
            "zamowienie_utworzone": False,
            "quote_number": numer_wyceny,
        }), 400

    # Akceptacja jest warunkiem kwalifikacji (status_id == 3). Gdy wycena jest
    # jeszcze edytowalna, przeprowadzamy ją tą samą drogą co /accept-with-data
    # — łącznie z zapisem danych klienta i mailami. Wycena zaakceptowana
    # wcześniej idzie prosto do zamówienia.
    blad_akceptacji = None
    if quote.is_client_editable:
        odpowiedz_akceptacji = client_accept_quote_with_data(token)
        if isinstance(odpowiedz_akceptacji, tuple):
            kod = odpowiedz_akceptacji[1]
        else:
            kod = getattr(odpowiedz_akceptacji, 'status_code', 200)
        if kod != 200:
            # Nie odsyłamy błędu od razu. Przy podwójnym kliknięciu równoległe
            # żądanie mogło zdążyć zaakceptować wycenę i akceptacja odbija się
            # wtedy z 400 „już zaakceptowana", choć zamówienie jest jak najbardziej
            # na miejscu. O tym, czy wycena nadaje się do zamówienia, rozstrzyga
            # jedno miejsce — guard w checkout_service, czytający stan pod blokadą.
            # Jeśli powie NIE, oddajemy klientowi konkretny błąd akceptacji
            # (np. „Email jest wymagany") zamiast ogólnika.
            blad_akceptacji = odpowiedz_akceptacji

    # Konto bota może nie istnieć w bazie (BOT_USER_ID=0 lub nieustawione).
    # created_by w logu BaseLinkera jest nullable, więc zamiast łamać FK
    # zostawiamy None — tak samo jak /api/bot (bot_api.py:226-231).
    bot_user_id = current_app.config.get("BOT_USER_ID")
    if bot_user_id and not User.query.get(bot_user_id):
        bot_user_id = None

    wynik = zloz_zamowienie_klienta(
        quote,
        order_source_id=zrodlo.baselinker_id,
        bot_user_id=bot_user_id,
        # Wybór dostawy z tego samego formularza, z którego czyta go akceptacja.
        # Bez przekazania go dalej zamówienie jechało kurierem i z kosztem
        # dostawy mimo zaznaczonego odbioru osobistego.
        is_self_pickup=bool(data.get("is_self_pickup")),
    )

    if not wynik["ok"]:
        if wynik["error"] == "NIEKWALIFIKOWANA":
            if blad_akceptacji is not None:
                return blad_akceptacji
            # Ten sam powód, który strona pokazuje zamiast przycisku „Zamów"
            # — klient ma dostać zdanie, a nie klasyfikację.
            return jsonify({
                "error": "Tej wyceny nie można zamówić przez stronę. Skontaktuj się "
                         "z nami — {kontakt} — i podaj numer wyceny {numer}.".format(
                             kontakt=KONTAKT_WOODPOWER, numer=numer_wyceny or "-"),
                "niepewne": False,
                "zamowienie_utworzone": False,
                "quote_number": numer_wyceny,
            }), 400
        logger.error("[client_place_order] Błąd BaseLinkera: %s "
                     "(niepewne=%s zamowienie_utworzone=%s order_id=%s)",
                     wynik["error"], wynik["niepewne"],
                     wynik["zamowienie_utworzone"], wynik["order_id"])
        # Treść błędu API zostaje w logu — klient dostaje komunikat bez szczegółów,
        # za to rozstrzygający, czy zamówienie powstało (albo mówiący wprost, że
        # tego nie wiemy).
        return jsonify({
            "error": komunikat_bledu_zamowienia(
                numer_wyceny, niepewne=wynik["niepewne"],
                zamowienie_utworzone=wynik["zamowienie_utworzone"]),
            "niepewne": wynik["niepewne"],
            # Ta flaga wyłącza w przeglądarce ponowienie tak samo jak `niepewne`,
            # ale niesie mocniejszą wiedzę: zamówienie NA PEWNO istnieje.
            "zamowienie_utworzone": wynik["zamowienie_utworzone"],
            "quote_number": numer_wyceny,
        }), 502

    logger.info("[client_place_order] Zamówienie złożone przez klienta: quote=%s "
                "order_id=%s duplikat=%s",
                numer_wyceny, wynik["order_id"], wynik["duplikat"])

    return jsonify({
        "ok": True,
        "order_id": wynik["order_id"],
        "quote_number": numer_wyceny,
        "order_page_url": wynik["order_page_url"],
        "duplikat": wynik["duplikat"],
    }), 200


@quotes_bp.route("/api/client/quote/<token>/validate-contact", methods=["POST"])
def validate_client_contact(token):
    """Waliduje dane kontaktowe klienta przed przejściem do następnego kroku"""
    try:
        data = request.get_json()
        
        quote = Quote.query.filter_by(public_token=token).first()
        if not quote:
            return jsonify({"error": "Nie znaleziono wyceny"}), 404
        
        if not quote.is_client_editable:
            return jsonify({"error": "Wycena została już zaakceptowana"}), 400
        
        email = data.get('email', '').strip().lower()
        phone = data.get('phone', '').strip()
        
        if not email and not phone:
            return jsonify({"error": "Podaj email lub telefon"}), 400
        
        client = quote.client
        if not client:
            return jsonify({"error": "Brak danych klienta"}), 400
        
        # SPECJALNY PRZYPADEK: Jeśli klient nie ma ani email ani telefonu w bazie
        # to przepuścić bez walidacji (nowi klienci)
        client_email = (client.email or "").lower().strip()
        client_phone_digits = re.sub(r'[^\d]', '', client.phone or '')
        
        if not client_email and not client_phone_digits:
            return jsonify({
                "success": True,
                "message": "Walidacja przeszła - nowy klient",
                "client_has_data": False
            })
        
        # Normalizacja danych wejściowych
        input_phone_digits = re.sub(r'[^\d]', '', phone)
        
        # Usuń +48 z początku jeśli istnieje
        if input_phone_digits.startswith('48') and len(input_phone_digits) > 9:
            input_phone_digits = input_phone_digits[2:]
        if client_phone_digits.startswith('48') and len(client_phone_digits) > 9:
            client_phone_digits = client_phone_digits[2:]
        
        # Sprawdź zgodność
        email_matches = client_email and email == client_email
        phone_matches = (client_phone_digits and input_phone_digits and 
                        len(input_phone_digits) >= 9 and
                        (input_phone_digits == client_phone_digits or 
                         input_phone_digits in client_phone_digits or 
                         client_phone_digits in input_phone_digits))
        
        if email_matches or phone_matches:
            return jsonify({
                "success": True,
                "message": "Dane zostały zweryfikowane",
                "client_has_data": True,
                "matched_email": email_matches,
                "matched_phone": phone_matches
            })
        else:
            return jsonify({
                "error": "Podane dane nie pasują do danych przypisanych do tej wyceny. Sprawdź email lub numer telefonu."
            }), 403
            
    except Exception as e:
        print(f"[validate_client_contact] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd podczas walidacji danych"}), 500

@quotes_bp.route("/api/client/quote/<token>/client-data", methods=["GET"])
def get_client_data_for_modal(token):
    """Pobiera dane klienta do wypełnienia modalboxa - ENDPOINT DO AUTO-UZUPEŁNIENIA"""
    try:
        quote = Quote.query.filter_by(public_token=token).first_or_404()
        
        if not quote.client:
            return jsonify({"error": "Brak przypisanego klienta"}), 404
        
        client = quote.client
        
        # Przygotuj dane do zwrócenia
        response_data = {
            "id": client.id,
            "client_name": client.client_name,
            "email": client.email,
            "phone": client.phone,
            "delivery": {
                "name": client.delivery_name,
                "company": client.delivery_company,
                "address": client.delivery_address,
                "zip": client.delivery_zip,
                "city": client.delivery_city,
                "region": client.delivery_region,
                "country": client.delivery_country,
            },
            "invoice": {
                "name": client.invoice_name,
                "company": client.invoice_company,
                "address": client.invoice_address,
                "zip": client.invoice_zip,
                "city": client.invoice_city,
                "nip": client.invoice_nip,
            } if client.invoice_nip else None
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[get_client_data_for_modal] Błąd: {e}", file=sys.stderr)
        return jsonify({"error": "Błąd pobierania danych klienta"}), 500

def normalize_phone_for_comparison(phone1, phone2):
    """Porównuje dwa numery telefonu po normalizacji"""
    if not phone1 or not phone2:
        return False
    
    import re
    
    def normalize(phone):
        # Usuń wszystkie znaki oprócz cyfr i +
        cleaned = re.sub(r'[^\d+]', '', phone)
        # Usuń +48 jeśli na początku
        if cleaned.startswith('+48'):
            cleaned = cleaned[3:]
        return cleaned
    
    return normalize(phone1) == normalize(phone2)


def normalize_email_for_comparison(email1, email2):
    """Porównuje dwa emaile (case insensitive)"""
    if not email1 or not email2:
        return False
    
    return email1.lower().strip() == email2.lower().strip()

@quotes_bp.route('/debug-static')
def debug_static_files():
    """Debug endpoint do sprawdzenia routingu plików statycznych"""
    import os
    from flask import current_app
    
    # Sprawdź ścieżki
    static_folder = quotes_bp.static_folder
    static_url_path = quotes_bp.static_url_path
    
    # Sprawdź czy folder img istnieje
    img_folder = os.path.join(static_folder, 'img')
    img_exists = os.path.exists(img_folder)
    
    # Lista plików w folderze img
    img_files = []
    if img_exists:
        img_files = os.listdir(img_folder)
    
    debug_info = {
        'blueprint_name': quotes_bp.name,
        'static_folder': static_folder,
        'static_url_path': static_url_path,
        'img_folder_exists': img_exists,
        'img_folder_path': img_folder,
        'img_files': img_files,
        'registered_rules': [str(rule) for rule in current_app.url_map.iter_rules() if 'static' in str(rule)]
    }
    
    return f"<pre>{debug_info}</pre>"

@quotes_bp.route('/api/check-quote-by-order/<order_id>')
@require_module_access('quotes')
def check_quote_by_order(order_id):
    """
    Sprawdza czy zamówienie z Baselinker ma powiązaną wycenę w systemie
    """    
    try:
        # Sprawdź czy istnieje wycena z tym base_linker_order_id
        quote = Quote.query.filter_by(base_linker_order_id=str(order_id)).first()
        
        if quote:
            
            return jsonify({
                'hasQuote': True,
                'quoteId': quote.id,
                'quoteNumber': quote.quote_number,
                'quoteToken': quote.public_token,
                'createdAt': quote.created_at.isoformat() if quote.created_at else None,
                'status': quote.quote_status.name if quote.quote_status else None
            })
        else:
            
            return jsonify({
                'hasQuote': False,
                'quoteId': None,
                'quoteNumber': None
            })
            
    except Exception as e:
        print(f"[check_quote_by_order] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({
            'error': 'Błąd podczas sprawdzania wyceny',
            'hasQuote': False
        }), 500

@quotes_bp.route("/api/quotes/<int:quote_id>/update-variant", methods=['PATCH'])
@require_module_access('quotes')
def update_quote_variant(quote_id):
    """Aktualizuje wybrany wariant dla produktu w wycenie"""
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)
        
        # Pobierz dane z requestu
        data = request.get_json()
        product_index = data.get('product_index')
        variant_code = data.get('variant_code')
        quote_item_id = data.get('quote_item_id')
        
        # Walidacja danych
        if not product_index or not variant_code:
            return jsonify({"error": "Brakuje wymaganych danych (product_index, variant_code)"}), 400
        
        try:
            product_index = int(product_index)
        except (ValueError, TypeError):
            return jsonify({"error": "Nieprawidłowa wartość product_index"}), 400
                
        # Znajdź docelowy item do ustawienia jako wybrany
        if quote_item_id:
            # Jeśli podano konkretny ID, użyj go
            target_item = QuoteItem.query.filter_by(
                id=quote_item_id,
                quote_id=quote_id,
                product_index=product_index
            ).first()
        else:
            # Jeśli nie podano ID, znajdź po product_index i variant_code
            target_item = QuoteItem.query.filter_by(
                quote_id=quote_id,
                product_index=product_index,
                variant_code=variant_code
            ).first()
        
        if not target_item:
            return jsonify({"error": f"Nie znaleziono wariantu {variant_code} dla produktu {product_index}"}), 404
        
        # Sprawdź czy item już jest wybrany
        if target_item.is_selected:
            return jsonify({"message": "Wariant już jest wybrany", "already_selected": True})
        
        # Zapisz stary wariant dla logowania
        old_selected = QuoteItem.query.filter_by(
            quote_id=quote_id,
            product_index=product_index,
            is_selected=True
        ).first()
        old_variant_code = old_selected.variant_code if old_selected else "Brak"
        
        # Odznacz wszystkie warianty w tej grupie produktów
        QuoteItem.query.filter_by(
            quote_id=quote_id,
            product_index=product_index
        ).update({QuoteItem.is_selected: False})
        
        # Ustaw nowy wariant jako wybrany
        target_item.is_selected = True
        
        # Zapisz zmiany
        db.session.commit()
                
        # Zaloguj zmianę
        current_user_id = session.get('user_id')
        if current_user_id:
            log_entry = QuoteLog(
                quote_id=quote_id,
                user_id=current_user_id,
                description=f"Zmieniono wariant produktu {product_index} z '{old_variant_code}' na '{variant_code}'"
            )
            db.session.add(log_entry)
            db.session.commit()
        
        return jsonify({
            "message": "Wariant został zmieniony",
            "product_index": product_index,
            "old_variant": old_variant_code,
            "new_variant": variant_code,
            "item_id": target_item.id
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"[update_quote_variant] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd podczas zmiany wariantu"}), 500

@quotes_bp.route('/api/multipliers', methods=['GET'])
def get_multipliers():
    """Pobiera listę grup cenowych z bazy danych - dostosowane do modelu z calculator"""
    try:
        from modules.calculator.models import Multiplier
        
        multipliers = Multiplier.query.order_by(Multiplier.id).all()
        
        result = []
        for multiplier in multipliers:
            result.append({
                'id': multiplier.id,
                'client_type': multiplier.client_type,
                'multiplier': float(multiplier.multiplier)  # Konwersja na float dla JSON
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[get_multipliers] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': 'Błąd pobierania grup cenowych'}), 500

@quotes_bp.route('/api/finishing-data', methods=['GET'])
@require_module_access('quotes')
def get_finishing_data():
    """Pobiera dane wykończenia - hierarchiczne drzewko opcji z bazy danych"""
    try:
        from modules.calculator.models import FinishingOption, FinishingTypePrice, FinishingColor

        # Spróbuj najpierw pobrać z nowej tabeli hierarchicznej
        try:
            tree = FinishingOption.get_tree()
            flat = FinishingOption.get_flat_list()

            # Jeśli są dane w nowej tabeli, użyj ich
            if tree:
                # Legacy format dla kompatybilności wstecznej
                finishing_types = []
                finishing_colors = []

                for opt in flat:
                    # Typy główne i pierwszy poziom (0-1)
                    if opt['level'] <= 1:
                        finishing_types.append({
                            'id': opt['id'],
                            'name': opt['full_path'] if opt['level'] > 0 else opt['name'],
                            'price_netto': opt['effective_price_netto']
                        })

                    # Kolory - opcje z obrazkami
                    if opt.get('image_path'):
                        finishing_colors.append({
                            'id': opt['id'],
                            'name': opt['name'],
                            'image_path': opt['image_path'],
                            'image_url': f"/calculator/static/{opt['image_path']}" if opt['image_path'] else None
                        })

                return jsonify({
                    'success': True,
                    'tree': tree,  # Nowy hierarchiczny format
                    'flat': flat,  # Płaska lista z depth info
                    'finishing_types': finishing_types,  # Legacy
                    'finishing_colors': finishing_colors  # Legacy
                })
        except Exception as tree_error:
            print(f"[get_finishing_data] Błąd nowej tabeli, fallback do starej: {tree_error}", file=sys.stderr)

        # Fallback: Pobierz ze starych tabel (kompatybilność wsteczna)
        finishing_types = FinishingTypePrice.query.filter_by(is_active=True).all()
        types_data = []
        for ft in finishing_types:
            types_data.append({
                'id': ft.id,
                'name': ft.name,
                'price_netto': float(ft.price_netto)
            })

        finishing_colors = FinishingColor.query.filter_by(is_available=True).all()
        colors_data = []
        for fc in finishing_colors:
            colors_data.append({
                'id': fc.id,
                'name': fc.name,
                'image_path': fc.image_path,
                'image_url': f"/calculator/static/{fc.image_path}" if fc.image_path else None
            })

        return jsonify({
            'success': True,
            'finishing_types': types_data,
            'finishing_colors': colors_data
        })

    except Exception as e:
        print(f"[get_finishing_data] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'success': False, 'error': 'Błąd pobierania danych wykończenia'}), 500


@quotes_bp.route('/api/quotes/<int:quote_id>/invoice/download')
@require_module_access('quotes')
def download_invoice(quote_id):
    """
    Pobiera PDF faktury z cache (bazy danych)
    """
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)
        
        # Sprawdź czy faktura istnieje w cache
        if not quote.has_invoice() or not quote.baselinker_invoice_file:
            return jsonify({
                'error': 'Faktura nie jest dostępna'
            }), 404
        
        # Dekoduj base64 do binary
        import base64
        
        # Usuń prefix "data:application/pdf;base64," jeśli istnieje
        invoice_data = quote.baselinker_invoice_file
        if invoice_data.startswith('data:'):
            parts = invoice_data.split(',', 1)
            if len(parts) > 1:
                invoice_data = parts[1]
            else:
                invoice_data = invoice_data.replace('data:', '')
        
        # Dekoduj base64
        pdf_binary = base64.b64decode(invoice_data)
        
        # Przygotuj nazwę pliku (usuń znaki specjalne z numeru faktury)
        safe_number = quote.baselinker_invoice_number.replace('/', '_')
        filename = f"Faktura_{safe_number}.pdf"
        
        # Zwróć PDF jako Response
        from flask import Response
        
        return Response(
            pdf_binary,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'application/pdf',
                'Content-Length': len(pdf_binary)
            }
        )
        
    except Exception as e:
        print(f"[download_invoice] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        return jsonify({
            'error': 'Błąd pobierania faktury',
            'details': str(e)
        }), 500

@quotes_bp.route('/api/quotes/<int:quote_id>/correction/download')
@require_module_access('quotes')
def download_correction(quote_id):
    """
    Pobiera PDF korekty faktury z cache (bazy danych)
    """
    try:
        # Pobierz wycenę
        quote = Quote.query.get_or_404(quote_id)
        
        # Sprawdź czy korekta istnieje w cache
        if not quote.has_correction() or not quote.baselinker_correction_invoice_file:
            return jsonify({
                'error': 'Korekta faktury nie jest dostępna'
            }), 404
        
        # Dekoduj base64 do binary
        import base64
        
        # Usuń prefix "data:application/pdf;base64," jeśli istnieje
        correction_data = quote.baselinker_correction_invoice_file
        if correction_data.startswith('data:'):
            parts = correction_data.split(',', 1)
            if len(parts) > 1:
                correction_data = parts[1]
            else:
                correction_data = correction_data.replace('data:', '')
        
        # Dekoduj base64
        pdf_binary = base64.b64decode(correction_data)
        
        # Przygotuj nazwę pliku (usuń znaki specjalne z numeru korekty)
        safe_number = quote.baselinker_correction_invoice_number.replace('/', '_')
        filename = f"Korekta_{safe_number}.pdf"
        
        # Zwróć PDF jako Response
        from flask import Response
        
        return Response(
            pdf_binary,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'application/pdf',
                'Content-Length': len(pdf_binary)
            }
        )
        
    except Exception as e:
        print(f"[download_correction] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        return jsonify({
            'error': 'Błąd pobierania korekty',
            'details': str(e)
        }), 500


# ============================================
# DXF / CNC ENDPOINTS
# ============================================

@quotes_bp.route("/api/quotes/<token>/dxf", methods=["GET"])
@require_module_access('quotes')
def generate_quote_dxf_single(token):
    """Generuje jeden plik DXF ze wszystkimi produktami wyceny."""
    from modules.calculator.services.dxf_service import generate_single_dxf

    quote = Quote.query.filter_by(public_token=token).first()
    if not quote:
        return jsonify({"error": "Wycena nie znaleziona"}), 404

    if not quote.base_linker_order_id:
        return jsonify({"error": "Wycena nie ma zamówienia BaseLinker"}), 400

    selected_items = [item for item in quote.items if item.is_selected]
    if not selected_items:
        return jsonify({"error": "Brak wybranych produktów"}), 400

    details_map = {}
    all_details = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
    for d in all_details:
        details_map[d.product_index] = d

    items_with_details = []
    for item in selected_items:
        detail = details_map.get(item.product_index)
        items_with_details.append((item, detail))

    try:
        buf = generate_single_dxf(quote, items_with_details)
        safe_number = (quote.quote_number or "wycena").replace("/", "-")
        filename = f"CNC_{safe_number}.dxf"

        return make_response(buf.read(), 200, {
            "Content-Type": "application/dxf",
            "Content-Disposition": f'attachment; filename="{filename}"',
        })
    except Exception as e:
        print(f"[DXF] Błąd generowania: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd generowania pliku DXF", "details": str(e)}), 500


@quotes_bp.route("/api/quotes/<token>/dxf/<int:product_index>", methods=["GET"])
@require_module_access('quotes')
def generate_quote_dxf_product(token, product_index):
    """Generuje plik DXF dla pojedynczego produktu wyceny."""
    from modules.calculator.services.dxf_service import generate_product_dxf, generate_product_filename

    quote = Quote.query.filter_by(public_token=token).first()
    if not quote:
        return jsonify({"error": "Wycena nie znaleziona"}), 404

    if not quote.base_linker_order_id:
        return jsonify({"error": "Wycena nie ma zamówienia BaseLinker"}), 400

    item = next((i for i in quote.items if i.product_index == product_index and i.is_selected), None)
    if not item:
        return jsonify({"error": f"Produkt {product_index} nie znaleziony"}), 404

    detail = QuoteItemDetails.query.filter_by(quote_id=quote.id, product_index=product_index).first()

    try:
        buf = generate_product_dxf(item, detail, quote.quote_number)
        filename = generate_product_filename(item, detail, product_index)

        return make_response(buf.read(), 200, {
            "Content-Type": "application/dxf",
            "Content-Disposition": f'attachment; filename="{filename}"',
        })
    except Exception as e:
        print(f"[DXF] Błąd generowania produktu {product_index}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd generowania pliku DXF", "details": str(e)}), 500


@quotes_bp.route("/api/quotes/<token>/dxf-zip", methods=["GET"])
@require_module_access('quotes')
def generate_quote_dxf_zip(token):
    """Generuje ZIP z osobnymi plikami DXF per produkt."""
    import zipfile
    from modules.calculator.services.dxf_service import generate_product_dxf, generate_product_filename

    quote = Quote.query.filter_by(public_token=token).first()
    if not quote:
        return jsonify({"error": "Wycena nie znaleziona"}), 404

    if not quote.base_linker_order_id:
        return jsonify({"error": "Wycena nie ma zamówienia BaseLinker"}), 400

    selected_items = [item for item in quote.items if item.is_selected]
    if not selected_items:
        return jsonify({"error": "Brak wybranych produktów"}), 400

    details_map = {}
    all_details = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
    for d in all_details:
        details_map[d.product_index] = d

    try:
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for item in selected_items:
                detail = details_map.get(item.product_index)
                dxf_buf = generate_product_dxf(item, detail, quote.quote_number)
                fname = generate_product_filename(item, detail, item.product_index)
                zf.writestr(fname, dxf_buf.read())

        zip_buf.seek(0)
        safe_number = (quote.quote_number or "wycena").replace("/", "-")
        filename = f"CNC_{safe_number}.zip"

        return make_response(zip_buf.read(), 200, {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{filename}"',
        })
    except Exception as e:
        print(f"[DXF-ZIP] Błąd generowania: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": "Błąd generowania archiwum DXF", "details": str(e)}), 500


# ============================================================
# INTEGRACJA CHATWOOT — Dashboard App (podgląd wycen klienta)
# ============================================================
# Endpoint osadzany jako iframe w panelu rozmowy Chatwoota.
# Chatwoot przekazuje kontekst (e-mail kontaktu) przez postMessage,
# a my po e-mailu pokazujemy wyceny danego klienta + przyciski:
#  - "Otwórz wycenę" -> wewnętrzny moduł quotes z modalem (/quotes/?open_quote=<id>)
#  - "Podgląd klienta" -> publiczny link tokenowy (/quotes/c/<token>)
# Ochrona: współdzielony token z config/core.json (CHATWOOT_INTEGRATION.iframe_token).

def _chatwoot_token_ok():
    """Sprawdza współdzielony token z core.json (CHATWOOT_INTEGRATION.iframe_token)."""
    cfg = current_app.config.get('CHATWOOT_INTEGRATION') or {}
    expected = cfg.get('iframe_token')
    provided = request.args.get('token', '')
    return bool(expected) and provided == expected


def _serialize_quotes(quotes):
    """Serializuje wyceny do formatu panelu Chatwoota (wspolne dla obu sciezek dopasowania)."""
    data = []
    for q in quotes:
        data.append({
            "id": q.id,
            "number": q.quote_number,
            "status": q.quote_status.name if q.quote_status else "—",
            "status_color": (q.quote_status.color_hex if (q.quote_status and q.quote_status.color_hex) else "#9ca3af"),
            "total": (f"{float(q.total_price):.2f}" if q.total_price is not None else None),
            "created": (q.created_at.strftime("%Y-%m-%d") if q.created_at else ""),
            "open_url": f"/quotes/?open_quote={q.id}",
            "public_url": (f"/quotes/c/{q.public_token}" if q.public_token else None),
        })
    return data


@quotes_bp.route('/chatwoot/api/quotes', methods=['GET'])
def chatwoot_client_quotes():
    """Zwraca wyceny klienta dopasowanego po identyfikatorze OLX lub e-mailu/telefonie/nazwie (iframe Chatwoota)."""
    if not _chatwoot_token_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    email = (request.args.get('email') or '').strip().lower()
    phone = (request.args.get('phone') or '').strip()
    name = (request.args.get('name') or '').strip()
    identifier = (request.args.get('identifier') or '').strip()

    if not (email or phone or name or identifier):
        return jsonify({"ok": True, "client": None, "quotes": []})

    # Kontakt OLX: dopasowanie po STALYM id kupujacego, nie po nazwie (imiona sie powtarzaja).
    # Most tworzy identyfikator kontaktu jako "olx-<id_kupujacego>-<id_watku>"
    # (integrations/chat_bridge/channels/olx.py), a agent wkleja go w pole "Nazwa klienta" w CRM.
    # UWAGA: pola w tabeli clients sa mylnie nazwane — UI "Nazwa klienta" zapisuje sie do kolumny
    # client_number, a client_name trzyma "Imie i nazwisko" (patrz modules/clients/routers.py).
    # Dlatego szukamy identyfikatora w OBU kolumnach (glownie client_number).
    # Ten sam kupujacy moze prowadzic wiele watkow -> wiele kart klienta z tym samym prefiksem;
    # agregujemy wyceny ze wszystkich, by pokazac pelna historie kupujacego. Dla OLX nie ma
    # fallbacku po nazwie — brak trafienia po prefiksie oznacza pusta liste.
    buyer_prefix = olx_buyer_prefix(identifier)
    if buyer_prefix:
        like = '%' + buyer_prefix + '%'
        candidates = Client.query.filter(
            or_(Client.client_number.ilike(like), Client.client_name.ilike(like))
        ).all()
        clients = [c for c in candidates
                   if name_matches_olx_prefix(c.client_number, buyer_prefix)
                   or name_matches_olx_prefix(c.client_name, buyer_prefix)]
        if not clients:
            return jsonify({"ok": True, "client": None, "quotes": []})
        client_ids = [c.id for c in clients]
        quotes = (Quote.query
                  .filter(Quote.client_id.in_(client_ids))
                  .order_by(Quote.created_at.desc())
                  .all())
        return jsonify({
            "ok": True,
            "matched_by": "olx_identifier",
            "client": {"name": name or buyer_prefix, "email": "", "phone": ""},
            "quotes": _serialize_quotes(quotes),
        })

    # Dopasowanie klienta: e-mail -> telefon -> nazwa (pierwsze trafienie wygrywa)
    client = None
    matched_by = None

    # 1) E-mail (case-insensitive)
    if email:
        client = Client.query.filter(func.lower(Client.email) == email).first()
        if client:
            matched_by = "email"

    # 2) Telefon (normalizacja: tylko cyfry, porównanie po 9 ostatnich)
    if client is None and phone:
        digits = re.sub(r'\D', '', phone)
        if len(digits) >= 9:
            last9 = digits[-9:]
            # Usuwamy z zapisanego telefonu spacje/myślniki/plus/nawiasy przed porównaniem
            phone_norm = func.replace(
                func.replace(
                    func.replace(
                        func.replace(
                            func.replace(Client.phone, ' ', ''),
                            '-', ''),
                        '+', ''),
                    '(', ''),
                ')', '')
            client = Client.query.filter(Client.phone.isnot(None), phone_norm.like('%' + last9)).first()
            if client:
                matched_by = "phone"

    # 3) Nazwa klienta (case-insensitive, dokładne dopasowanie po przycięciu)
    if client is None and name:
        client = Client.query.filter(func.lower(func.trim(Client.client_name)) == name.lower()).first()
        if client:
            matched_by = "name"

    if not client:
        return jsonify({"ok": True, "client": None, "quotes": []})

    quotes = (Quote.query
              .filter_by(client_id=client.id)
              .order_by(Quote.created_at.desc())
              .all())

    return jsonify({
        "ok": True,
        "matched_by": matched_by,
        "client": {"name": client.client_name, "email": client.email, "phone": client.phone},
        "quotes": _serialize_quotes(quotes),
    })


# Mapowania kodów wariantu na etykiety (jak w module quotes/baselinker)
_CW_SPECIES = {'dab': 'Dąb', 'jes': 'Jesion', 'buk': 'Buk', 'brzoza': 'Brzoza', 'sosna': 'Sosna'}
_CW_TECH = {'lity': 'Lity', 'micro': 'Mikrowczep', 'finger': 'Finger-joint'}
_CW_SHAPE = {'rectangular': 'Prostokąt', 'round': 'Okrągły'}


def _cw_variant_label(code):
    """'dab-lity-ab' -> 'Dąb lity A/B'"""
    if not code:
        return '—'
    p = code.lower().split('-')
    sp = _CW_SPECIES.get(p[0], p[0].capitalize()) if len(p) > 0 else ''
    te = _CW_TECH.get(p[1], p[1].capitalize()) if len(p) > 1 else ''
    cl = '/'.join(list(p[2].upper())) if len(p) > 2 and p[2] else ''
    return ' '.join(x for x in [sp, te, cl] if x)


def _cw_num(x):
    """Formatuje wymiar: 198.0 -> '198', 4.5 -> '4.5'"""
    f = float(x or 0)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


@quotes_bp.route('/chatwoot/api/quote/<int:quote_id>/items', methods=['GET'])
def chatwoot_quote_items(quote_id):
    """Lista produktów (wybranych) danej wyceny + podsumowanie objętość/waga."""
    if not _chatwoot_token_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    quote = Quote.query.get(quote_id)
    if not quote:
        return jsonify({"ok": False, "error": "not_found"}), 404

    # Szczegóły per product_index (wykończenie, kształt)
    details = {d.product_index: d for d in QuoteItemDetails.query.filter_by(quote_id=quote.id).all()}

    items = [it for it in quote.items if it.is_selected]
    if not items:
        items = list(quote.items)

    rows = []
    vol_total = 0.0
    for it in items:
        d = details.get(it.product_index)
        qty = it.get_quantity()
        unit_vol = float(it.volume_m3 or 0)
        vol_total += unit_vol * qty
        shape_code = (d.shape if d else 'rectangular') or 'rectangular'
        finishing = (d.finishing_type if (d and d.finishing_type) else 'Surowe')
        rows.append({
            "lp": it.product_index,
            "shape": _CW_SHAPE.get(shape_code, shape_code.capitalize()),
            "variant": _cw_variant_label(it.variant_code),
            "dimensions": f"{_cw_num(it.length_cm)}×{_cw_num(it.width_cm)}×{_cw_num(it.thickness_cm)}",
            "finishing": finishing,
            "quantity": qty,
            "netto": f"{it.get_total_price_netto():.2f}",
            "brutto": f"{it.get_total_price_brutto():.2f}",
        })

    # Waga: ~0,8 kg/dm³ (spójnie z widokiem szczegółów wyceny, np. 0,268 m³ -> 214,4 kg)
    weight = vol_total * 800.0
    return jsonify({
        "ok": True,
        "quote_number": quote.quote_number,
        "items": rows,
        "summary": {"volume_m3": round(vol_total, 4), "weight_kg": round(weight, 1)},
    })


# Strona iframe (HTML+JS). Token wstrzykiwany przez prosty replace (bez Jinja),
# żeby uniknąć kolizji z nawiasami klamrowymi w JS/CSS.
_CHATWOOT_PANEL_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wyceny klienta</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; font-size:13px; color:#1f2933; background:#f8fafc; }
  .wrap { padding:10px; }
  .muted { color:#6b7280; }
  .hdr { font-weight:600; margin-bottom:2px; }
  .sub { font-size:12px; color:#6b7280; margin-bottom:10px; }
  .empty { padding:24px 10px; text-align:center; color:#6b7280; }
  .q { background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:10px; margin-bottom:8px; }
  .q-top { display:flex; justify-content:space-between; align-items:center; gap:8px; }
  .q-num { font-weight:600; }
  .q-meta { font-size:12px; color:#6b7280; margin-top:2px; }
  .badge { display:inline-block; padding:2px 8px; border-radius:999px; color:#fff; font-size:11px; white-space:nowrap; }
  .total { font-weight:600; white-space:nowrap; }
  .actions { margin-top:8px; display:flex; gap:6px; }
  .btn { flex:1; text-align:center; text-decoration:none; padding:6px 8px; border-radius:6px; font-size:12px; cursor:pointer; }
  .btn-primary { background:#2563eb; color:#fff; }
  .btn-ghost { background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }
  .spin { padding:24px; text-align:center; color:#6b7280; }
  .toggle { margin-top:8px; width:100%; background:#fff; border:1px dashed #cbd5e1; color:#475569; border-radius:6px; padding:6px; font-size:12px; cursor:pointer; }
  .items { display:none; margin-top:8px; }
  .it { border-top:1px solid #eef2f7; padding:6px 0; }
  .it-h { font-weight:600; font-size:12px; }
  .it-m { font-size:12px; color:#6b7280; margin-top:1px; }
  .sum { margin-top:6px; padding-top:6px; border-top:1px solid #e5e7eb; font-size:12px; font-weight:600; color:#334155; }
</style>
</head>
<body>
<div class="wrap">
  <div id="root">
    <div class="spin">Ładowanie kontekstu rozmowy…</div>
  </div>
</div>
<script>
  var CW_TOKEN = "__CW_TOKEN__";
  var root = document.getElementById('root');

  // Delegacja: rozwijanie listy produktów per wycena (lazy-load)
  root.addEventListener('click', function(ev){
    var btn = ev.target.closest ? ev.target.closest('.toggle') : null;
    if(!btn) return;
    var qid = btn.getAttribute('data-qid');
    var box = document.getElementById('cwitems-' + qid);
    if(!box) return;
    if(box.style.display === 'block'){ box.style.display = 'none'; btn.textContent = 'Pokaż produkty ▾'; return; }
    btn.textContent = 'Ukryj produkty ▴';
    box.style.display = 'block';
    if(box.dataset.loaded === '1') return;
    box.innerHTML = '<div class="spin">Ładowanie produktów…</div>';
    fetch('/quotes/chatwoot/api/quote/' + encodeURIComponent(qid) + '/items?token=' + encodeURIComponent(CW_TOKEN))
      .then(function(r){ return r.json(); })
      .then(function(res){ renderItems(box, res); box.dataset.loaded = '1'; })
      .catch(function(){ box.innerHTML = '<div class="empty">Błąd pobierania produktów.</div>'; });
  });

  function renderItems(box, res){
    if(!res || !res.ok || !res.items || res.items.length === 0){
      box.innerHTML = '<div class="empty">Brak pozycji.</div>'; return;
    }
    var h = '';
    res.items.forEach(function(it){
      h += '<div class="it">';
      h += '<div class="it-h">' + esc(it.shape) + ' · ' + esc(it.variant) + '</div>';
      h += '<div class="it-m">' + esc(it.dimensions) + ' cm · ' + esc(it.finishing) + ' · ×' + esc(it.quantity) + ' · ' + esc(it.brutto) + ' zł</div>';
      h += '</div>';
    });
    if(res.summary){
      h += '<div class="sum">Objętość: ' + esc(res.summary.volume_m3) + ' m³ · Waga: ~' + esc(res.summary.weight_kg) + ' kg</div>';
    }
    box.innerHTML = h;
  }

  function esc(s){ return (s==null?'':String(s)).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

  function render(payload){
    if(!payload || !payload.client){
      root.innerHTML = '<div class="empty">Nie znaleziono klienta w CRM.<br><span class="muted">Dla OLX dopasowujemy po identyfikatorze kupującego (olx-…) wklejonym w nazwę klienta; dla pozostałych kontaktów po e-mailu, telefonie lub nazwie. Sprawdź, czy odpowiednie dane są zapisane w CRM.</span></div>';
      return;
    }
    var c = payload.client;
    var html = '<div class="hdr">' + esc(c.name) + '</div>';
    html += '<div class="sub">' + esc(c.email || '') + (c.phone ? ' · ' + esc(c.phone) : '') + '</div>';
    if(!payload.quotes || payload.quotes.length === 0){
      html += '<div class="empty">Ten klient nie ma jeszcze wycen.</div>';
      root.innerHTML = html; return;
    }
    payload.quotes.forEach(function(q){
      html += '<div class="q">';
      html += '<div class="q-top"><span class="q-num">' + esc(q.number) + '</span>';
      html += '<span class="badge" style="background:' + esc(q.status_color) + '">' + esc(q.status) + '</span></div>';
      html += '<div class="q-meta">' + esc(q.created) + (q.total ? ' · <span class="total">' + esc(q.total) + ' zł</span>' : '') + '</div>';
      html += '<div class="actions">';
      html += '<a class="btn btn-primary" target="_blank" rel="noopener" href="' + esc(q.open_url) + '">Otwórz wycenę</a>';
      if(q.public_url){ html += '<a class="btn btn-ghost" target="_blank" rel="noopener" href="' + esc(q.public_url) + '">Podgląd klienta</a>'; }
      html += '</div>';
      html += '<button class="toggle" data-qid="' + esc(q.id) + '">Pokaż produkty ▾</button>';
      html += '<div class="items" id="cwitems-' + esc(q.id) + '"></div>';
      html += '</div>';
    });
    root.innerHTML = html;
  }

  function loadQuotes(email, phone, name, identifier){
    email = email || ''; phone = phone || ''; name = name || ''; identifier = identifier || '';
    if(!email && !phone && !name && !identifier){
      root.innerHTML = '<div class="empty">Ta rozmowa nie ma danych kontaktu (e-mail / telefon / nazwa).</div>';
      return;
    }
    // Dla kontaktow OLX identyfikatorem jest "olx-<kupujacy>-<watek>" — pokazujemy nazwe kontaktu.
    var label = name || email || phone || identifier;
    root.innerHTML = '<div class="spin">Szukam wycen dla ' + esc(label) + '…</div>';
    var qs = 'token=' + encodeURIComponent(CW_TOKEN)
           + '&email=' + encodeURIComponent(email)
           + '&phone=' + encodeURIComponent(phone)
           + '&name=' + encodeURIComponent(name)
           + '&identifier=' + encodeURIComponent(identifier);
    fetch('/quotes/chatwoot/api/quotes?' + qs)
      .then(function(r){ return r.json(); })
      .then(render)
      .catch(function(){ root.innerHTML = '<div class="empty">Błąd pobierania wycen z CRM.</div>'; });
  }

  // Chatwoot przekazuje kontekst przez postMessage (event: appContext)
  window.addEventListener('message', function(event){
    var payload = event.data;
    if(typeof payload === 'string'){
      try { payload = JSON.parse(payload); } catch(e){ return; }
    }
    if(payload && payload.event === 'appContext'){
      var d = payload.data || {};
      var contact = d.contact || {};
      // Identyfikator OLX (olx-<kupujacy>-<watek>) bierzemy z kontaktu, a gdyby go tam brakowalo —
      // z nadawcy rozmowy (conversation.meta.sender.identifier), gdzie most tez go ustawia.
      var conv = d.conversation || {};
      var sender = (conv.meta && conv.meta.sender) || {};
      var ident = contact.identifier || sender.identifier || '';
      loadQuotes(contact.email || '', contact.phone_number || '', contact.name || '', ident);
    }
  });

  // Fallback: jeśli po 4s brak kontekstu, pokaż komunikat
  setTimeout(function(){
    if(root.querySelector('.spin')){
      root.innerHTML = '<div class="empty">Oczekiwanie na kontekst z Chatwoota…<br><span class="muted">Otwórz rozmowę, aby zobaczyć wyceny.</span></div>';
    }
  }, 4000);
</script>
</body>
</html>"""


@quotes_bp.route('/chatwoot/panel', methods=['GET'])
def chatwoot_panel():
    """Strona iframe dla Dashboard App Chatwoota (podgląd wycen klienta)."""
    cfg = current_app.config.get('CHATWOOT_INTEGRATION') or {}
    expected = cfg.get('iframe_token')
    token = request.args.get('token', '')
    if not expected or token != expected:
        return "Brak autoryzacji", 401

    html = _CHATWOOT_PANEL_HTML.replace("__CW_TOKEN__", token)
    resp = current_app.response_class(html, mimetype="text/html")
    # Pozwól osadzić iframe tylko w panelu Chatwoota
    resp.headers['Content-Security-Policy'] = "frame-ancestors https://chat.woodpower.pl"
    resp.headers.pop('X-Frame-Options', None)
    return resp