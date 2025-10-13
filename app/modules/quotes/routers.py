# modules/quotes/routers.py
from flask import render_template, jsonify, request, make_response, current_app, send_file, Blueprint, session, redirect, url_for, flash, abort
from . import quotes_bp
from modules.calculator.models import Quote, User, QuoteItemDetails, QuoteItem, QuoteLog, Multiplier
from modules.clients.models import Client
from modules.baselinker.service import BaselinkerService
from modules.baselinker.models import BaselinkerConfig
from modules.users.decorators import require_module_access
from extensions import db, mail
from weasyprint import HTML
from io import BytesIO
from flask_mail import Message
from functools import wraps
import logging
import sys
from sqlalchemy.orm import joinedload
from sqlalchemy import func, text
import re
from datetime import datetime
import base64
import os
import json

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
        
        # DODANE: Pobierz dane użytkownika i jego rolę
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        user_role = user.role if user else 'user'
        user_multiplier = user.multiplier.multiplier if user and user.multiplier else 1.0
                
        # DODANE: Pobierz ceny z bazy danych (tak jak w calculator)
        prices_query = db.session.execute(text("""
            SELECT species, technology, wood_class, thickness_min, thickness_max, 
                   length_min, length_max, price_per_m3 
            FROM prices
        """)).fetchall()
        prices_list = [dict(row._mapping) for row in prices_query]
        for row in prices_list:
            for key in ['thickness_min', 'thickness_max', 'length_min', 'length_max', 'price_per_m3']:
                if key in row and row[key] is not None:
                    row[key] = float(row[key])
        prices_json = json.dumps(prices_list)

        # DODANE: Pobierz mnożniki z bazy danych (tak jak w calculator)  
        multipliers_query = Multiplier.query.all()
        multipliers_list = [
            {"label": m.client_type, "value": float(m.multiplier)}
            for m in multipliers_query
        ]
        multipliers_json = json.dumps(multipliers_list)
        
        # Sprawdź konfigurację Baselinker (istniejący kod - pozostaw bez zmian)
        from modules.baselinker.models import BaselinkerConfig
        from modules.baselinker.service import BaselinkerService
        
        config_count = BaselinkerConfig.query.count()
        
        if config_count == 0:
            print("[quotes_home] Brak konfiguracji Baselinker - rozpoczynam synchronizację", file=sys.stderr)
            
            api_config = current_app.config.get('API_BASELINKER')
            if api_config and api_config.get('api_key'):
                try:
                    service = BaselinkerService()
                    sources_synced = service.sync_order_sources()
                    statuses_synced = service.sync_order_statuses()
                except Exception as e:
                    print(f"[quotes_home] Błąd synchronizacji Baselinker: {e}", file=sys.stderr)
            else:
                print("[quotes_home] Brak konfiguracji API Baselinker", file=sys.stderr)
        else:
            print("[quotes_home] Konfiguracja Baselinker już istnieje", file=sys.stderr)
            
    except Exception as e:
        print(f"[quotes_home] Błąd podczas ładowania danych: {e}", file=sys.stderr)
        # Utwórz puste dane w przypadku błędu
        prices_json = json.dumps([])
        multipliers_json = json.dumps([])
        user_role = 'user'
        user_multiplier = 1.0
    
    # ZMIANA: Przekaż dane do template (tak jak w calculator)
    return render_template('quotes/templates/quotes.html', 
                          prices_json=prices_json,
                          multipliers_json=multipliers_json,
                          user_role=user_role,
                          user_multiplier=user_multiplier)

@quotes_bp.route('/api/quotes')
@require_module_access('quotes')
def api_quotes():

    try:
        # Mapa statusów
        statuses = {
            s.name: {"id": s.id, "name": s.name, "color": s.color_hex}
            for s in QuoteStatus.query.all()
        }

        # ✅ NOWE: Filtrowanie per rola
        base_query = Quote.query.order_by(Quote.created_at.desc())
        quotes = get_filtered_quotes_query(base_query).all()

        results = []
        for q in quotes:
            client = q.client
            user = q.user
            status_data = statuses.get(q.quote_status.name if q.quote_status else None, {})

            result = {
                "id": q.id,
                "quote_number": q.quote_number,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "client_number": client.client_number if client else None,
                "client_name": client.client_name if client else None,
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

        return jsonify(results)

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
            print(f"[generate_quote_pdf] Unsupported format: {format}", file=sys.stderr)
            return {"error": "Unsupported format"}, 400

        # ZMIANA: Wyszukiwanie po tokenie zamiast ID
        quote = Quote.query.filter_by(public_token=token).first()
        if not quote:
            print(f"[generate_quote_pdf] Brak wyceny dla tokenu: {token}", file=sys.stderr)
            return {"error": "Quote not found"}, 404

        # KLUCZOWE: Oblicz koszty (tak jak w send_email i get_client_quote_data)
        selected_items = [item for item in quote.items if item.is_selected]
        finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
        
        cost_products_netto = round(sum(item.get_total_price_netto() for item in selected_items), 2)
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in finishing_details), 2)
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
                    print(f"[PDF] Icon not found: {icons_path}", file=sys.stderr)
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
    print(f"[send_email] Wysylka maila dla wyceny ID {quote_id}", file=sys.stderr)

    data = request.get_json()
    recipient_email = data.get("email")
    print(f"[send_email] Do: {recipient_email}", file=sys.stderr)

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
    cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
    cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
    costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)
    
    # Pobierz detale wykończenia
    finishing_details = db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()
    
    # Załaduj ikony (opcjonalnie - można pominąć dla emaili)
    icons = {}  # Można dodać ikony jeśli potrzebne

    rendered = render_template("quotes/templates/offer_pdf.html", 
                              quote=quote, 
                              client=client, 
                              user=user, 
                              status=status,
                              costs=costs,
                              selected_items=selected_items,
                              finishing_details=finishing_details,
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
    print("[api_quotes_status_counts] Endpoint wywolany", file=sys.stderr)

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
            print(f"[get_quote_details] ❌ Wycena {quote_id} nie znaleziona", file=sys.stderr)
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
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in finishing_details), 2)
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

        # KOŃCOWY PRZEGLĄD JSON
        final_json_items = [item.to_dict() for item in quote_items]
        
        # Analiza końcowego JSON
        final_show_values = [item.get('show_on_client_page') for item in final_json_items]
        final_selected_values = [item.get('is_selected') for item in final_json_items]
        
        # Test pojedynczej pozycji
        test_item = quote_items[5]  # jes-micro-ab (show_on_client_page=False)
        test_dict = test_item.to_dict()
        
        # Test serializacji przez Flask jsonify
        import json
        json_string = json.dumps(test_dict)
        
        # Test deserializacji
        parsed_back = json.loads(json_string)
        
        # Test całej listy
        all_items_dict = [item.to_dict() for item in quote_items]
        all_json = json.dumps(all_items_dict)
        all_parsed = json.loads(all_json)
        
        return jsonify({
            "id": quote.id,
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

            # NOWE POLE: Informacje o użytkowniku akceptującym
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
                "quantity": d.quantity or 1
            } for d in finishing_details],
            "client": {
                "id": quote.client.id if quote.client else None,
                "client_name": quote.client.client_name if quote.client else None,
                "client_number": quote.client.client_number if quote.client else None,
                "client_delivery_name": quote.client.client_delivery_name if quote.client else None,
                "company_name": quote.client.delivery_company if quote.client else None,
                "first_name": quote.client.client_number if quote.client else None,  # client_number zawiera imię i nazwisko
                "last_name": "",  # W bazie nie ma oddzielnych pól
                "email": quote.client.email if quote.client else None,
                "phone": quote.client.phone if quote.client else None
            },
            "user": {
                "id": quote.user.id if quote.user else None,
                "first_name": quote.user.first_name if quote.user else "",
                "last_name": quote.user.last_name if quote.user else ""
            },
            "items": [item.to_dict() for item in quote_items]
        })

    except Exception as e:
        print(f"[get_quote_details] 💥 BŁĄD PODCZAS BUDOWANIA JSON:", file=sys.stderr)
        print(f"[get_quote_details] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        return jsonify({"error": "Błąd serwera"}), 500

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



@quotes_bp.route("/c/<token>")
def client_quote_view(token):
    """Widok strony klienta z redesignem"""
    try:
        
        # Znajdź wycenę po tokenie
        quote = Quote.query.filter_by(public_token=token).first()
        
        if not quote:
            print(f"[client_quote_view] Nie znaleziono wyceny dla tokenu: {token}", file=sys.stderr)
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
        
        return render_template("quotes/templates/client_quote.html", 
                             quote=quote,
                             quote_number=quote_number,
                             token=token,
                             is_accepted=not quote.is_client_editable,
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
        
        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto() for i in quote.items if i.is_selected), 2)
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
        cost_shipping_brutto = quote.shipping_cost_brutto or 0.0
        cost_shipping_netto = quote.shipping_cost_netto or 0.0
        costs = calculate_costs_with_vat(cost_products_netto, cost_finishing_netto, cost_shipping_brutto)
        
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
            finishing_info = {
                "product_index": detail.product_index,
                "finishing_type": detail.finishing_type,
                "finishing_variant": detail.finishing_variant,
                "finishing_color": detail.finishing_color,
                "finishing_gloss_level": detail.finishing_gloss_level,
                "finishing_price_netto": float(detail.finishing_price_netto or 0),
                "finishing_price_brutto": float(detail.finishing_price_brutto or 0),
                "quantity": detail.quantity or 1
            }
            
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
            quote.client_comment = comments
        
        # Ustaw datę akceptacji i status
        quote.acceptance_date = datetime.utcnow()
        quote.is_client_editable = False
        quote.accepted_by_email = email_or_phone
        
        # Zmień status na "Zaakceptowana przez klienta" (ID=7)
        quote.status_id = 7
        
        # Dodaj log
        log_entry = QuoteLog(
            quote_id=quote.id,
            user_id=None,  # Brak użytkownika - akcja klienta
            change_time=datetime.utcnow(),
            description=f"Wycena zaakceptowana przez klienta (email: {email_or_phone})"
        )
        db.session.add(log_entry)
        
        db.session.commit()
                
        # TODO: Wysłanie emaila z potwierdzeniem
        
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
        print(f"[send_acceptance_email_to_salesperson] Brak emaila sprzedawcy dla wyceny {quote.id}", file=sys.stderr)
        return
    
    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()
        
        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto or 0 for i in selected_items), 2)
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
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
        print(f"[send_acceptance_email_to_client] Brak emaila klienta dla wyceny {quote.id}", file=sys.stderr)
        return
    
    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()
        
        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto or 0 for i in selected_items), 2)
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
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
            print(f"[user_accept_quote] BŁĄD: Nie znaleziono statusu akceptacji!", file=sys.stderr)
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
        print(f"[send_user_acceptance_email_to_client] Brak emaila klienta dla wyceny {quote.id}", file=sys.stderr)
        return
    
    try:
        # Przygotuj dane do szablonu
        selected_items = quote.get_selected_items()
        
        # Oblicz koszty
        cost_products_netto = round(sum(i.get_total_price_netto() for i in selected_items), 2)
        cost_finishing_netto = round(sum(d.finishing_price_netto or 0.0 for d in db.session.query(QuoteItemDetails).filter_by(quote_id=quote.id).all()), 2)
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

        # === KRYTYCZNA WALIDACJA BEZPIECZEŃSTWA ===
        # Sprawdź czy podany email LUB telefon pasuje do danych w bazie

        client = quote.client
        if not client:
            return jsonify({"error": "Brak przypisanego klienta do wyceny"}), 400

        # Normalizacja danych do porównania
        client_email = (client.email or "").lower().strip()
        client_phone_digits = re.sub(r'[^\d]', '', client.phone or '')
        input_email = email.lower().strip()
        input_phone_digits = re.sub(r'[^\d]', '', phone)

        # Usuń +48 z początku jeśli istnieje
        if input_phone_digits.startswith('48') and len(input_phone_digits) > 9:
            input_phone_digits = input_phone_digits[2:]
        if client_phone_digits.startswith('48') and len(client_phone_digits) > 9:
            client_phone_digits = client_phone_digits[2:]

        # Sprawdź zgodność email LUB telefonu
        email_matches = client_email and input_email == client_email
        phone_matches = (client_phone_digits and input_phone_digits and 
                        len(input_phone_digits) >= 9 and
                        (input_phone_digits == client_phone_digits or 
                         input_phone_digits in client_phone_digits or 
                         client_phone_digits in input_phone_digits))

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
            print(f"[client_accept_quote_with_data] BŁĄD: Nie znaleziono statusu akceptacji!", file=sys.stderr)
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
            print(f"[client_accept_quote_with_data] Wszystkie zmiany zapisane pomyślnie", file=sys.stderr)
        except Exception as e:
            print(f"[client_accept_quote_with_data] BŁĄD podczas zapisu: {e}", file=sys.stderr)
            db.session.rollback()
            return jsonify({"error": "Błąd zapisu do bazy danych"}), 500
        
        # === WYŚLIJ EMAILE POWIADOMIENIA ===
        try:
            send_acceptance_emails(quote)
            print(f"[client_accept_quote_with_data] Emaile wysłane pomyślnie", file=sys.stderr)
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
            print(f"[validate_client_contact] Klient bez danych kontaktowych - przepuszczam", file=sys.stderr)
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
        
        print(f"[get_multipliers] Zwracam {len(result)} grup cenowych", file=sys.stderr)
        return jsonify(result)
        
    except Exception as e:
        print(f"[get_multipliers] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': 'Błąd pobierania grup cenowych'}), 500

@quotes_bp.route('/api/finishing-data', methods=['GET'])
@require_module_access('quotes')
def get_finishing_data():
    """Pobiera dane wykończenia - typy i kolory z bazy danych"""
    try:
        from modules.calculator.models import FinishingTypePrice, FinishingColor
        
        # Pobierz typy wykończenia z cenami
        finishing_types = FinishingTypePrice.query.filter_by(is_active=True).all()
        types_data = []
        for ft in finishing_types:
            types_data.append({
                'id': ft.id,
                'name': ft.name,
                'price_netto': float(ft.price_netto)
            })
        
        # Pobierz kolory z obrazkami
        finishing_colors = FinishingColor.query.filter_by(is_available=True).all()
        colors_data = []
        for fc in finishing_colors:
            colors_data.append({
                'id': fc.id,
                'name': fc.name,
                'image_path': fc.image_path,
                # Pełna ścieżka URL do obrazka
                'image_url': f"/calculator/static/{fc.image_path}" if fc.image_path else None
            })
                
        return jsonify({
            'finishing_types': types_data,
            'finishing_colors': colors_data
        })
        
    except Exception as e:
        print(f"[get_finishing_data] Błąd: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': 'Błąd pobierania danych wykończenia'}), 500