# app/modules/baselinker/routers.py
from flask import render_template, jsonify, request, session, redirect, url_for, flash
from . import baselinker_bp
from .service import BaselinkerService
from .models import BaselinkerOrderLog, BaselinkerConfig
from modules.calculator.models import Quote, User, QuoteItemDetails
from modules.clients.models import Client
from extensions import db
import sys
from modules.users.decorators import require_module_access
from modules.logging import get_structured_logger

# Inicjalizacja loggera dla całego modułu
baselinker_logger = get_structured_logger('baselinker.routers')

@baselinker_bp.route('/api/quote/<int:quote_id>/create-order', methods=['POST'])
@require_module_access('baselinker')
def create_order(quote_id):
    """Tworzy zamówienie w Baselinker na podstawie wyceny"""
    baselinker_logger.info("Rozpoczęcie tworzenia zamówienia w Baselinker",
                          quote_id=quote_id,
                          endpoint='create_order')
    
    try:
        # Pobierz wycenę z eager loading
        quote = Quote.query.get_or_404(quote_id)
        
        baselinker_logger.debug("Pobrano wycenę do przetworzenia",
                            quote_id=quote_id,
                            quote_number=quote.quote_number,
                            client_id=quote.client_id,
                            status_id=quote.status_id,
                            notes=quote.notes,  # ✅ DODANE: Dodaj do logowania
                            has_notes=bool(quote.notes and quote.notes.strip()))
        
        # Sprawdź czy wycena ma wybrane produkty
        selected_items = [item for item in quote.items if item.is_selected]
        if not selected_items:
            baselinker_logger.warning("Próba utworzenia zamówienia bez wybranych produktów",
                                     quote_id=quote_id,
                                     quote_number=quote.quote_number)
            return jsonify({'error': 'Wycena nie ma wybranych produktów'}), 400
        
        baselinker_logger.debug("Znaleziono wybrane produkty",
                               quote_id=quote_id,
                               selected_items_count=len(selected_items))
        
        # Pobierz konfigurację z żądania
        config = request.get_json()
        if not config:
            baselinker_logger.error("Brak konfiguracji w żądaniu",
                                   quote_id=quote_id,
                                   content_type=request.content_type)
            return jsonify({'error': 'Brak konfiguracji zamówienia'}), 400
        
        baselinker_logger.debug("Otrzymana konfiguracja zamówienia",
                               quote_id=quote_id,
                               config_keys=list(config.keys()),
                               order_source_id=config.get('order_source_id'),
                               order_status_id=config.get('order_status_id'))
        
        # Pobierz użytkownika
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        if not user:
            baselinker_logger.error("Nie znaleziono użytkownika w sesji",
                                   user_email=user_email,
                                   quote_id=quote_id)
            return jsonify({'error': 'Błąd autoryzacji'}), 401
        
        baselinker_logger.debug("Zidentyfikowano użytkownika",
                               user_id=user.id,
                               user_email=user_email,
                               user_role=user.role)
        
        # Walidacja konfiguracji
        if not config.get('order_source_id') or not config.get('order_status_id'):
            baselinker_logger.error("Niepełna konfiguracja zamówienia",
                                   quote_id=quote_id,
                                   missing_fields={
                                       'order_source_id': not config.get('order_source_id'),
                                       'order_status_id': not config.get('order_status_id')
                                   })
            return jsonify({'error': 'Niepełna konfiguracja zamówienia'}), 400
        
        # Sprawdź czy źródło i status istnieją w bazie
        source_exists = BaselinkerConfig.query.filter_by(
            config_type='order_source',
            baselinker_id=config['order_source_id']
        ).first()
        
        status_exists = BaselinkerConfig.query.filter_by(
            config_type='order_status',
            baselinker_id=config['order_status_id']
        ).first()
        
        if not source_exists:
            baselinker_logger.error("Źródło zamówienia nie istnieje w bazie",
                                   quote_id=quote_id,
                                   order_source_id=config['order_source_id'])
            return jsonify({'error': f'Źródło zamówienia o ID {config["order_source_id"]} nie istnieje'}), 400
            
        if not status_exists:
            baselinker_logger.error("Status zamówienia nie istnieje w bazie",
                                   quote_id=quote_id,
                                   order_status_id=config['order_status_id'])
            return jsonify({'error': f'Status zamówienia o ID {config["order_status_id"]} nie istnieje'}), 400
        
        baselinker_logger.info("Walidacja konfiguracji przeszła pomyślnie",
                              quote_id=quote_id,
                              source_name=source_exists.name,
                              status_name=status_exists.name)
        
        # Utwórz zamówienie
        service = BaselinkerService()
        result = service.create_order_from_quote(quote, user.id, config)
        
        baselinker_logger.info("Otrzymano wynik z serwisu Baselinker",
                              quote_id=quote_id,
                              service_success=result.get('success'),
                              baselinker_order_id=result.get('order_id'),
                              error=result.get('error'))
        
        if result['success']:
            # Zaktualizuj status wyceny na "Złożone" (ID: 4)
            try:
                from modules.quotes.models import QuoteStatus
                ordered_status = QuoteStatus.query.filter_by(id=4).first()
                if ordered_status:
                    old_status_id = quote.status_id
                    quote.status_id = ordered_status.id
                    db.session.commit()
                    
                    baselinker_logger.info("Status wyceny został zaktualizowany",
                                          quote_id=quote_id,
                                          old_status_id=old_status_id,
                                          new_status_id=ordered_status.id,
                                          new_status_name=ordered_status.name)
                else:
                    baselinker_logger.warning("Nie znaleziono statusu 'Złożone' w bazie",
                                             expected_status_id=4,
                                             quote_id=quote_id)
            except Exception as status_error:
                baselinker_logger.error("Błąd podczas zmiany statusu wyceny",
                                       quote_id=quote_id,
                                       error=str(status_error),
                                       error_type=type(status_error).__name__)
            
            baselinker_logger.info("Zamówienie zostało pomyślnie utworzone",
                                  quote_id=quote_id,
                                  quote_number=quote.quote_number,
                                  baselinker_order_id=result['order_id'],
                                  user_id=user.id)
            
            return jsonify({
                'success': True,
                'order_id': result['order_id'],
                'quote_number': quote.quote_number,
                'message': 'Zamówienie zostało pomyślnie utworzone w Baselinker'
            })
        else:
            baselinker_logger.error("Tworzenie zamówienia nie powiodło się",
                                   quote_id=quote_id,
                                   error=result.get('error', 'Nieznany błąd'),
                                   user_id=user.id)
            return jsonify({
                'success': False,
                'error': result.get('error', 'Nieznany błąd podczas tworzenia zamówienia')
            }), 500
        
    except Exception as e:
        baselinker_logger.error("Nieoczekiwany błąd podczas tworzenia zamówienia",
                               quote_id=quote_id,
                               error=str(e),
                               error_type=type(e).__name__)
        import traceback
        baselinker_logger.debug("Stack trace błędu",
                               traceback=traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

@baselinker_bp.route('/api/sync-config')
@require_module_access('baselinker') 
def sync_config():
    """Synchronizuje konfigurację z Baselinker (źródła, statusy)"""
    baselinker_logger.info("Rozpoczęcie synchronizacji konfiguracji Baselinker",
                          endpoint='sync_config')
    
    try:
        service = BaselinkerService()
        
        baselinker_logger.debug("Rozpoczęcie synchronizacji źródeł zamówień")
        sources_synced = service.sync_order_sources()
        
        baselinker_logger.debug("Rozpoczęcie synchronizacji statusów zamówień")
        statuses_synced = service.sync_order_statuses()
        
        sync_success = sources_synced and statuses_synced
        
        baselinker_logger.info("Synchronizacja konfiguracji zakończona",
                              sources_synced=sources_synced,
                              statuses_synced=statuses_synced,
                              overall_success=sync_success)
        
        if sync_success:
            return jsonify({
                'success': True,
                'message': 'Konfiguracja została zsynchronizowana'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Błąd synchronizacji konfiguracji'
            }), 500
            
    except Exception as e:
        baselinker_logger.error("Błąd podczas synchronizacji konfiguracji",
                               error=str(e),
                               error_type=type(e).__name__)
        return jsonify({'error': 'Błąd synchronizacji'}), 500

@baselinker_bp.route('/api/quote/<int:quote_id>/order-logs')
@require_module_access('baselinker')
def get_order_logs(quote_id):
    """Pobiera logi operacji Baselinker dla wyceny"""
    baselinker_logger.info("Pobieranie logów operacji Baselinker",
                          quote_id=quote_id,
                          endpoint='get_order_logs')
    
    try:
        logs = BaselinkerOrderLog.query.filter_by(quote_id=quote_id)\
            .order_by(BaselinkerOrderLog.created_at.desc()).all()
        
        baselinker_logger.debug("Pobrano logi z bazy danych",
                               quote_id=quote_id,
                               logs_count=len(logs))
        
        logs_data = [log.to_dict() for log in logs]
        
        baselinker_logger.info("Pomyślnie pobrano logi operacji",
                              quote_id=quote_id,
                              returned_logs=len(logs_data))
        
        return jsonify(logs_data)
        
    except Exception as e:
        baselinker_logger.error("Błąd podczas pobierania logów",
                               quote_id=quote_id,
                               error=str(e),
                               error_type=type(e).__name__)
        return jsonify({'error': 'Błąd pobierania logów'}), 500
    
@baselinker_bp.route('/api/order/<int:order_id>/status')
@require_module_access('baselinker')
def get_order_status(order_id):
    """Pobiera status zamówienia z Baselinker"""
    baselinker_logger.info("Rozpoczęcie pobierania statusu zamówienia",
                          order_id=order_id,
                          endpoint='get_order_status')
    
    try:
        service = BaselinkerService()
        baselinker_logger.debug("Utworzono instancję BaselinkerService")
        
        result = service.get_order_details(order_id)
        baselinker_logger.debug("Otrzymano wynik z get_order_details",
                               order_id=order_id,
                               result_success=result.get('success'),
                               has_order_data=bool(result.get('order')))
        
        if result['success']:
            order_data = result.get('order', {})
            baselinker_logger.debug("Szczegóły zamówienia z API",
                                   order_id=order_id,
                                   baselinker_order_id=order_data.get('order_id'),
                                   status_id=order_data.get('order_status_id'))
            
            # Mapuj ID statusu na nazwę (można rozszerzyć)
            status_map = {
                105112: 'Nowe - nieopłacone',
                155824: 'Nowe - opłacone',
                138619: 'W produkcji - surowe',
                148832: 'W produkcji - olejowanie',
                148831: 'W produkcji - bejcowanie',
                148830: 'W produkcji - lakierowanie',
                138620: 'Produkcja zakończona',
                138623: 'Zamówienie spakowane',
                105113: 'Paczka zgłoszona do wysyłki',
                105114: 'Wysłane - kurier',
                149763: 'Wysłane - transport WoodPower',
                149777: 'Czeka na odbiór osobisty',
                138624: 'Dostarczona - kurier',
                149778: 'Dostarczona - transport WoodPower',
                149779: 'Odebrane',
                138625: 'Zamówienie anulowane'
            }
            
            order_status_id = order_data.get('order_status_id')
            status_name = status_map.get(order_status_id, f'Status {order_status_id}')
            
            baselinker_logger.info("Pomyślnie zmapowano status zamówienia",
                                  order_id=order_id,
                                  baselinker_order_id=order_data.get('order_id'),
                                  status_id=order_status_id,
                                  status_name=status_name)
            
            response_data = {
                'success': True,
                'status_id': order_status_id,
                'status_name': status_name
            }
            
            return jsonify(response_data)
        else:
            error_msg = result.get('error', 'Nieznany błąd')
            baselinker_logger.warning("Nie udało się pobrać szczegółów zamówienia",
                                     order_id=order_id,
                                     error=error_msg)
            
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400
            
    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania statusu zamówienia",
                               order_id=order_id,
                               error=str(e),
                               error_type=type(e).__name__)
        import traceback
        baselinker_logger.debug("Stack trace błędu pobierania statusu",
                               traceback=traceback.format_exc())
        
        return jsonify({'error': 'Błąd pobierania statusu zamówienia'}), 500

@baselinker_bp.route('/api/config/sources')
@require_module_access('baselinker')
def get_order_sources():
    """Pobiera dostępne źródła zamówień z bazy"""
    baselinker_logger.info("Pobieranie źródeł zamówień z bazy",
                          endpoint='get_order_sources')
    
    try:
        sources = BaselinkerConfig.query.filter_by(
            config_type='order_source',
            is_active=True
        ).order_by(BaselinkerConfig.name).all()
        
        sources_data = [
            {
                'id': source.baselinker_id,
                'name': source.name
            }
            for source in sources
        ]
        
        baselinker_logger.debug("Pobrano źródła zamówień z bazy",
                               sources_count=len(sources_data))
        
        return jsonify({
            'success': True,
            'sources': sources_data
        })
        
    except Exception as e:
        baselinker_logger.error("Błąd podczas pobierania źródeł zamówień",
                               error=str(e),
                               error_type=type(e).__name__)
        return jsonify({'error': 'Błąd pobierania źródeł'}), 500

@baselinker_bp.route('/api/config/statuses')
@require_module_access('baselinker')
def get_order_statuses():
    """Pobiera dostępne statusy zamówień z bazy"""
    baselinker_logger.info("Pobieranie statusów zamówień z bazy",
                          endpoint='get_order_statuses')
    
    try:
        statuses = BaselinkerConfig.query.filter_by(
            config_type='order_status',
            is_active=True
        ).order_by(BaselinkerConfig.name).all()
        
        statuses_data = [
            {
                'id': status.baselinker_id,
                'name': status.name
            }
            for status in statuses
        ]
        
        baselinker_logger.debug("Pobrano statusy zamówień z bazy",
                               statuses_count=len(statuses_data))
        
        return jsonify({
            'success': True,
            'statuses': statuses_data
        })
        
    except Exception as e:
        baselinker_logger.error("Błąd podczas pobierania statusów zamówień",
                               error=str(e),
                               error_type=type(e).__name__)
        return jsonify({'error': 'Błąd pobierania statusów'}), 500

@baselinker_bp.route('/api/quote/<int:quote_id>/order-modal-data')
@require_module_access('baselinker')
def get_order_modal_data(quote_id):
    """Pobiera dane do wyświetlenia w modalu zamówienia"""
    baselinker_logger.info("Pobieranie danych dla modalu zamówienia",
                          quote_id=quote_id,
                          endpoint='get_order_modal_data')
    
    try:
        quote = Quote.query.get_or_404(quote_id)
        
        # Pobierz wybrane produkty
        selected_items = [item for item in quote.items if item.is_selected]
        if not selected_items:
            baselinker_logger.warning("Wycena nie ma wybranych produktów",
                                     quote_id=quote_id)
            return jsonify({'error': 'Wycena nie ma wybranych produktów'}), 400
        
        # Pobierz wszystkie szczegóły wykończenia dla tej wyceny
        finishing_details_list = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
        
        products = []
        
        # POPRAWKA 1: Osobno oblicz koszty produktów surowych i wykończenia
        total_products_value_brutto = 0  # Tylko surowe produkty
        total_products_value_netto = 0   # Tylko surowe produkty
        total_finishing_value_brutto = 0 # Tylko wykończenie
        total_finishing_value_netto = 0  # Tylko wykończenie
        
        for item in selected_items:
            # Pobierz szczegóły wykończenia dla tego produktu
            finishing_details = QuoteItemDetails.query.filter_by(
                quote_id=quote.id, 
                product_index=item.product_index
            ).first()
            
            # Oblicz quantity
            quantity = finishing_details.quantity if finishing_details and finishing_details.quantity else 1
            
            # CENY SUROWEGO PRODUKTU (bez wykończenia)
            unit_price_netto = float(item.price_netto or 0)
            unit_price_brutto = float(item.price_brutto or 0)
            
            # Dodaj do sumy surowych produktów
            total_products_value_netto += unit_price_netto * quantity
            total_products_value_brutto += unit_price_brutto * quantity
            
            # CENY WYKOŃCZENIA (jeśli istnieje)
            if finishing_details and finishing_details.finishing_price_netto:
                # finishing_price_netto to już CAŁKOWITA kwota za wykończenie wszystkich sztuk
                finishing_total_netto = float(finishing_details.finishing_price_netto or 0)
                finishing_total_brutto = float(finishing_details.finishing_price_brutto or 0)
                
                # Dodaj do sumy wykończenia (bez mnożenia przez quantity!)
                total_finishing_value_netto += finishing_total_netto
                total_finishing_value_brutto += finishing_total_brutto
            
            # KOŃCOWE CENY JEDNOSTKOWE (surowe + wykończenie na sztukę)
            finishing_unit_netto = 0
            finishing_unit_brutto = 0
            
            if finishing_details and finishing_details.finishing_price_netto:
                finishing_unit_netto = float(finishing_details.finishing_price_netto or 0) / quantity if quantity > 0 else 0
                finishing_unit_brutto = float(finishing_details.finishing_price_brutto or 0) / quantity if quantity > 0 else 0
            
            final_unit_price_netto = unit_price_netto + finishing_unit_netto
            final_unit_price_brutto = unit_price_brutto + finishing_unit_brutto
            
            # Przygotuj dane produktu dla frontendu
            product_name = f"{item.variant_code} {item.length_cm}×{item.width_cm}×{item.thickness_cm}cm"
            
            # Oblicz wagę
            volume_m3 = (item.length_cm * item.width_cm * item.thickness_cm) / 1_000_000
            weight_kg = round(volume_m3 * 650, 2)  # gęstość drewna
            
            product_data = {
                'product_index': item.product_index,
                'name': product_name,
                'dimensions': f"{item.length_cm}×{item.width_cm}×{item.thickness_cm} cm",
                'quantity': quantity,
                'variant_code': item.variant_code,
                'unit_price_netto': round(final_unit_price_netto, 2),
                'unit_price_brutto': round(final_unit_price_brutto, 2),
                'total_price_netto': round(final_unit_price_netto * quantity, 2),
                'total_price_brutto': round(final_unit_price_brutto * quantity, 2),
                'weight': weight_kg,
                'finishing': {
                    'type': finishing_details.finishing_type if finishing_details else 'Brak',
                    'color': finishing_details.finishing_color if finishing_details else 'Brak',
                    'price_netto': finishing_total_netto if finishing_details and finishing_details.finishing_price_netto else 0,
                    'price_brutto': finishing_total_brutto if finishing_details and finishing_details.finishing_price_brutto else 0,
                    'quantity': quantity
                } if finishing_details else None
            }
            
            products.append(product_data)
        
        # Przygotuj dane klienta
        client_data = {}
        if quote.client:
            client_data = {
                'name': quote.client.client_name,
                'delivery_name': quote.client.client_delivery_name or quote.client.client_name,
                'email': quote.client.email,
                'phone': quote.client.phone,
                'delivery_address': quote.client.delivery_address or '',
                'delivery_postcode': quote.client.delivery_zip or '',
                'delivery_city': quote.client.delivery_city or '',
                'delivery_region': quote.client.delivery_region or '',
                'delivery_company': quote.client.delivery_company or '',
                'invoice_name': quote.client.invoice_name or quote.client.client_name or '',
                'invoice_company': quote.client.invoice_company or '',
                'invoice_nip': quote.client.invoice_nip or '',
                'invoice_address': quote.client.invoice_address or '',
                'invoice_postcode': quote.client.invoice_zip or '',
                'invoice_city': quote.client.invoice_city or '',
                'invoice_region': quote.client.invoice_region or '',
                'want_invoice': bool(quote.client.invoice_nip)
            }
        
        # Pobierz konfigurację Baselinker
        try:
            order_sources = BaselinkerConfig.query.filter_by(
                config_type='order_source',
                is_active=True
            ).order_by(BaselinkerConfig.name).all()
            
            sources_data = [{'id': source.baselinker_id, 'name': source.name} for source in order_sources]
            
            order_statuses = BaselinkerConfig.query.filter_by(
                config_type='order_status',
                is_active=True
            ).order_by(BaselinkerConfig.name).all()
            
            statuses_data = [{'id': status.baselinker_id, 'name': status.name} for status in order_statuses]
            
        except Exception as config_error:
            baselinker_logger.error("Błąd podczas pobierania konfiguracji Baselinker", error=str(config_error))
            sources_data = []
            statuses_data = []
        
        config_data = {
            'order_sources': sources_data,
            'order_statuses': statuses_data,
            'payment_methods': ['Przelew bankowy', 'Płatność przy odbiorze', 'Karta płatnicza'],
            'delivery_countries': [
                {'code': 'PL', 'name': 'Polska'},
                {'code': 'DE', 'name': 'Niemcy'},
                {'code': 'CZ', 'name': 'Czechy'}
            ],
            'delivery_methods': [
                'Kurier DPD', 'Kurier InPost', 'Kurier UPS', 'Kurier DHL',
                'Paczkomaty InPost', 'Odbiór osobisty', 'Transport własny'
            ]
        }
        
        # POPRAWKA 2: Oblicz koszty wysyłki
        shipping_cost_brutto = float(quote.shipping_cost_brutto or 0)
        shipping_cost_netto = shipping_cost_brutto / 1.23 if shipping_cost_brutto > 0 else 0
        
        # POPRAWKA 3: Poprawne koszty całkowite
        total_value_netto = total_products_value_netto + total_finishing_value_netto + shipping_cost_netto
        total_value_brutto = total_products_value_brutto + total_finishing_value_brutto + shipping_cost_brutto

        response_data = {
            'quote': {
                'id': quote.id,
                'client_id': quote.client_id,
                'quote_number': quote.quote_number,
                'created_at': quote.created_at.isoformat(),
                'courier_name': quote.courier_name,
                'source': getattr(quote, 'source', ''),
                'status_name': quote.quote_status.name if quote.quote_status else 'Nieznany',
                'status_id': quote.status_id,
                'notes': quote.notes or ''
            },
            'client': client_data,
            'products': products,
            'costs': {
                # POPRAWKA 4: Osobne koszty dla produktów surowych i wykończenia
                'products_brutto': round(total_products_value_brutto, 2),
                'products_netto': round(total_products_value_netto, 2),
                'finishing_brutto': round(total_finishing_value_brutto, 2),
                'finishing_netto': round(total_finishing_value_netto, 2),
                'shipping_brutto': round(shipping_cost_brutto, 2),
                'shipping_netto': round(shipping_cost_netto, 2),
                'total_brutto': round(total_value_brutto, 2),
                'total_netto': round(total_value_netto, 2)
            },
            'config': config_data
        }
        
        baselinker_logger.info("Przygotowano dane dla modalu zamówienia",
                              quote_id=quote_id,
                              products_count=len(products),
                              products_value_brutto=total_products_value_brutto,
                              finishing_value_brutto=total_finishing_value_brutto,
                              total_value_brutto=total_value_brutto,
                              has_client=bool(quote.client),
                              sources_count=len(config_data['order_sources']),
                              statuses_count=len(config_data['order_statuses']))
        
        return jsonify(response_data)
        
    except Exception as e:
        baselinker_logger.error("Błąd podczas przygotowywania danych modalu",
                               quote_id=quote_id,
                               error=str(e),
                               error_type=type(e).__name__)
        import traceback
        baselinker_logger.debug("Stack trace błędu", traceback=traceback.format_exc())
        return jsonify({'error': 'Błąd pobierania danych'}), 500