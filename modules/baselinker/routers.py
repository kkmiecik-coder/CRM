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


def generate_sku_for_modal(item, finishing_details=None):
    """Generuje SKU w formacie BLADEBLIT3501004ABSUR (uproszczona wersja dla modala)"""
    try:
        # Parsuj kod wariantu (np. "dab-lity-ab")
        variant_parts = item.variant_code.lower().split('-') if item.variant_code else []

        # 1. Typ produktu (zawsze BLA dla blat)
        product_type = "BLA"

        # 2. Gatunek drewna
        species_map = {
            'dab': 'DEB',
            'jes': 'JES',
            'buk': 'BUK',
            'brzoza': 'BRZ',
            'sosna': 'SOS'
        }
        species = species_map.get(variant_parts[0] if len(variant_parts) > 0 else '', 'XXX')

        # 3. Technologia
        tech_map = {
            'lity': 'LIT',
            'micro': 'MIC',
            'finger': 'FIN'
        }
        technology = tech_map.get(variant_parts[1] if len(variant_parts) > 1 else '', 'XXX')

        # 4. Wymiary
        length = str(int(item.length_cm or 0)).zfill(3) if item.length_cm else "000"
        width = str(int(item.width_cm or 0)) if item.width_cm else "0"
        thickness = str(int(item.thickness_cm or 0)) if item.thickness_cm else "0"

        # 5. Klasa drewna
        wood_class = variant_parts[2].upper() if len(variant_parts) > 2 else "XX"

        # 6. Wykończenie - najpierw sprawdź nową tabelę FinishingOption
        finishing = "SUR"
        if finishing_details and finishing_details.finishing_type and finishing_details.finishing_type != 'Brak':
            # Spróbuj pobrać kod z nowej hierarchicznej tabeli
            try:
                from modules.calculator.models import FinishingOption
                finishing_opt = FinishingOption.query.filter_by(
                    name=finishing_details.finishing_type,
                    is_active=True
                ).first()

                if finishing_opt:
                    # Użyj kodu z opcji lub jej rodzica
                    code = finishing_opt.get_code()
                    if code:
                        finishing = code
                else:
                    # Fallback: stare mapowanie
                    finishing_map = {
                        'lakier': 'LAK',
                        'olej': 'OLE',
                        'wosk': 'WOS',
                        'bejca': 'BEJ',
                        'lazura': 'LAZ',
                        'surow': 'SUR'
                    }
                    finishing_type = finishing_details.finishing_type.lower()
                    for key, value in finishing_map.items():
                        if key in finishing_type:
                            finishing = value
                            break
            except Exception:
                # Fallback: stare mapowanie
                finishing_map = {
                    'lakier': 'LAK',
                    'olej': 'OLE',
                    'wosk': 'WOS',
                    'bejca': 'BEJ',
                    'lazura': 'LAZ'
                }
                finishing_type = finishing_details.finishing_type.lower()
                for key, value in finishing_map.items():
                    if key in finishing_type:
                        finishing = value
                        break

        # 7. Obróbka krawędzi
        edge_code = ""
        if finishing_details and finishing_details.edges_type and finishing_details.edges_config:
            edges_config = finishing_details.edges_config
            if edges_config and len(edges_config) > 0:
                edge_type_map = {
                    'round': 'ZR',
                    'chamfer': 'FR'
                }
                edge_type = finishing_details.edges_type
                r_value = finishing_details.edges_r_value or 0
                angle_value = finishing_details.edges_angle_value
                edge_prefix = edge_type_map.get(edge_type, 'XX')
                # Dla fazowania dodaj kąt (np. FR45A45), dla zaokrąglenia tylko R (np. ZR5)
                if edge_type == 'chamfer' and angle_value:
                    edge_code = f"{edge_prefix}{r_value}A{angle_value}"
                else:
                    edge_code = f"{edge_prefix}{r_value}"

        return f"{product_type}{species}{technology}{length}{width}{thickness}{wood_class}{finishing}{edge_code}"

    except Exception:
        return f"WP-{item.variant_code.upper()}-{item.id}" if item.variant_code else f"WP-UNKNOWN-{item.id}"

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
        
        # Walidacja konfiguracji - order_source_id jest wymagane (może być 0!)
        # order_status_id jest hardcoded w service.py (105112), nie walidujemy
        if config.get('order_source_id') is None:
            baselinker_logger.error("Niepełna konfiguracja zamówienia",
                                   quote_id=quote_id,
                                   missing_fields={'order_source_id': True})
            return jsonify({'error': 'Niepełna konfiguracja zamówienia - brak źródła'}), 400

        # Sprawdź czy źródło istnieje w bazie
        source_exists = BaselinkerConfig.query.filter_by(
            config_type='order_source',
            baselinker_id=config['order_source_id']
        ).first()

        if not source_exists:
            baselinker_logger.error("Źródło zamówienia nie istnieje w bazie",
                                   quote_id=quote_id,
                                   order_source_id=config['order_source_id'])
            return jsonify({'error': f'Źródło zamówienia o ID {config["order_source_id"]} nie istnieje'}), 400

        # Status jest hardcoded (105112), nie walidujemy

        baselinker_logger.info("Walidacja konfiguracji przeszła pomyślnie",
                              quote_id=quote_id,
                              source_name=source_exists.name,
                              status_id_hardcoded=105112)
        
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

        # Status zamówienia jest hardcoded (105112), nie synchronizujemy statusów
        statuses_synced = True

        sync_success = sources_synced and statuses_synced

        baselinker_logger.info("Synchronizacja konfiguracji zakończona",
                              sources_synced=sources_synced,
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
        # Pobierz użytkownika i określ jego rolę
        user_email = session.get('user_email')
        user_id = session.get('user_id')
        
        if not user_email:
            return jsonify({"error": "Brak sesji użytkownika"}), 401
        
        user = User.query.filter_by(email=user_email).first()
        if not user:
            return jsonify({"error": "Użytkownik nie znaleziony"}), 404
        
        user_role = user.role
        
        # Określ czy flexible partner (to samo co w calculator)
        FLEXIBLE_PARTNER_IDS = [14, 15, 16]
        is_flexible_partner = (user_role == 'partner' and user_id in FLEXIBLE_PARTNER_IDS)
        
        baselinker_logger.debug("Dane użytkownika",
                               user_id=user_id,
                               user_role=user_role,
                               is_flexible_partner=is_flexible_partner)
        
        quote = Quote.query.get_or_404(quote_id)
        
        # Pobierz tryb cen z wyceny
        quote_type = getattr(quote, 'quote_type', 'brutto') or 'brutto'
        
        baselinker_logger.info("Tryb cen wyceny",
                              quote_id=quote_id,
                              quote_type=quote_type)
        
        # Pobierz wybrane produkty
        selected_items = [item for item in quote.items if item.is_selected]
        if not selected_items:
            baselinker_logger.warning("Wycena nie ma wybranych produktów",
                                     quote_id=quote_id)
            return jsonify({'error': 'Wycena nie ma wybranych produktów'}), 400
        
        # Pobierz wszystkie szczegóły wykończenia dla tej wyceny
        finishing_details_list = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
        
        products = []
        
        # Osobno oblicz koszty produktów surowych, wykończenia i krawędzi
        total_products_value_brutto = 0
        total_products_value_netto = 0
        total_finishing_value_brutto = 0
        total_finishing_value_netto = 0
        total_edges_value_brutto = 0
        total_edges_value_netto = 0
        
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
            finishing_total_netto = 0
            finishing_total_brutto = 0

            if finishing_details and finishing_details.finishing_price_netto:
                finishing_total_netto = float(finishing_details.finishing_price_netto or 0)
                finishing_total_brutto = float(finishing_details.finishing_price_brutto or 0)

                # Dodaj do sumy wykończenia
                total_finishing_value_netto += finishing_total_netto
                total_finishing_value_brutto += finishing_total_brutto

            # CENY OBRÓBKI KRAWĘDZI (jeśli istnieje)
            edges_total_netto = 0
            edges_total_brutto = 0

            if finishing_details and finishing_details.edges_price_netto:
                edges_total_netto = float(finishing_details.edges_price_netto or 0)
                edges_total_brutto = float(finishing_details.edges_price_brutto or 0)

                # Dodaj do sumy krawędzi
                total_edges_value_netto += edges_total_netto
                total_edges_value_brutto += edges_total_brutto

            # KOŃCOWE CENY JEDNOSTKOWE (surowe + wykończenie + krawędzie na sztukę)
            finishing_unit_netto = 0
            finishing_unit_brutto = 0
            edges_unit_netto = 0
            edges_unit_brutto = 0

            if finishing_details and finishing_details.finishing_price_netto:
                finishing_unit_netto = finishing_total_netto / quantity if quantity > 0 else 0
                finishing_unit_brutto = finishing_total_brutto / quantity if quantity > 0 else 0

            if finishing_details and finishing_details.edges_price_netto:
                edges_unit_netto = edges_total_netto / quantity if quantity > 0 else 0
                edges_unit_brutto = edges_total_brutto / quantity if quantity > 0 else 0

            final_unit_price_netto = unit_price_netto + finishing_unit_netto + edges_unit_netto
            final_unit_price_brutto = unit_price_brutto + finishing_unit_brutto + edges_unit_brutto
            
            # Przygotuj dane produktu
            product_name = f"{item.variant_code} {item.length_cm}×{item.width_cm}×{item.thickness_cm}cm"

            # Oblicz wagę
            volume_m3 = (item.length_cm * item.width_cm * item.thickness_cm) / 1_000_000
            weight_kg = round(volume_m3 * 650, 2)

            # Generuj SKU
            sku = generate_sku_for_modal(item, finishing_details)

            # Przygotuj dane krawędzi
            edges_data = None
            if finishing_details and finishing_details.edges_config and len(finishing_details.edges_config) > 0:
                # Mapowanie typów na polskie nazwy
                edge_type_names = {
                    'round': 'Zaokrąglenie',
                    'chamfer': 'Fazowanie'
                }
                edge_type = finishing_details.edges_type or ''
                edge_type_name = edge_type_names.get(edge_type, edge_type)
                r_value = finishing_details.edges_r_value or 0

                # Lista liter krawędzi
                edge_letters = [edge.get('letter', '?') for edge in finishing_details.edges_config]

                edges_data = {
                    'type': edge_type,
                    'type_name': edge_type_name,
                    'r_value': r_value,
                    'angle_value': finishing_details.edges_angle_value,
                    'letters': edge_letters,
                    'count': len(edge_letters),
                    'price_netto': edges_total_netto,
                    'price_brutto': edges_total_brutto
                }

            product_data = {
                'product_index': item.product_index,
                'name': product_name,
                'dimensions': f"{item.length_cm}×{item.width_cm}×{item.thickness_cm} cm",
                'quantity': quantity,
                'variant_code': item.variant_code,
                'shape': finishing_details.shape if finishing_details and finishing_details.shape else 'rectangular',
                'sku': sku,
                'unit_price_netto': round(final_unit_price_netto, 2),
                'unit_price_brutto': round(final_unit_price_brutto, 2),
                'total_price_netto': round(final_unit_price_netto * quantity, 2),
                'total_price_brutto': round(final_unit_price_brutto * quantity, 2),
                'weight': weight_kg,
                'finishing': {
                    'type': finishing_details.finishing_type if finishing_details else 'Brak',
                    'variant': finishing_details.finishing_variant if finishing_details else None,
                    'gloss_level': finishing_details.finishing_gloss_level if finishing_details else None,
                    'color': finishing_details.finishing_color if finishing_details else 'Brak',
                    'price_netto': finishing_total_netto if finishing_details and finishing_details.finishing_price_netto else 0,
                    'price_brutto': finishing_total_brutto if finishing_details and finishing_details.finishing_price_brutto else 0,
                    'quantity': quantity
                } if finishing_details else None,
                'edges': edges_data
            }

            products.append(product_data)
        
        # Przygotuj dane klienta
        client_data = {}
        if quote.client:
            client_data = {
                'client_number': quote.client.client_number or '',  # Nazwa klienta/firmy
                'name': quote.client.client_name,
                'delivery_name': quote.client.delivery_name or quote.client.client_name,
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
        
        # ZMIENIONA SEKCJA: Pobierz konfigurację Baselinker z filtrowaniem
        try:
            # Pobierz wszystkie aktywne źródła
            all_order_sources = BaselinkerConfig.query.filter_by(
                config_type='order_source',
                is_active=True
            ).order_by(BaselinkerConfig.name).all()
            
            # FILTRUJ źródła według uprawnień użytkownika
            filtered_sources = [
                source 
                for source in all_order_sources 
                if source.is_allowed_for_role(user_role, is_flexible_partner)
            ]
            
            sources_data = [{'id': source.baselinker_id, 'name': source.name} for source in filtered_sources]
            
            baselinker_logger.info("Przefiltrowano źródła zamówień",
                                  user_role=user_role,
                                  is_flexible_partner=is_flexible_partner,
                                  all_sources_count=len(all_order_sources),
                                  filtered_sources_count=len(filtered_sources))
            
            # Pobierz wszystkie aktywne statusy
            all_order_statuses = BaselinkerConfig.query.filter_by(
                config_type='order_status',
                is_active=True
            ).order_by(BaselinkerConfig.name).all()
            
            # FILTRUJ statusy według uprawnień użytkownika
            filtered_statuses = [
                status 
                for status in all_order_statuses 
                if status.is_allowed_for_role(user_role, is_flexible_partner)
            ]
            
            statuses_data = [{'id': status.baselinker_id, 'name': status.name} for status in filtered_statuses]
            
            baselinker_logger.info("Przefiltrowano statusy zamówień",
                                  user_role=user_role,
                                  is_flexible_partner=is_flexible_partner,
                                  all_statuses_count=len(all_order_statuses),
                                  filtered_statuses_count=len(filtered_statuses))
            
        except Exception as config_error:
            baselinker_logger.error("Błąd podczas pobierania konfiguracji Baselinker", error=str(config_error))
            sources_data = []
            statuses_data = []
        
        config_data = {
            'order_sources': sources_data,
            'order_statuses': statuses_data,
            'payment_methods': ['Przelew bankowy', 'Płatność przy odbiorze'],
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

        # Sugeruj źródło zamówienia na podstawie logiki biznesowej
        suggested_source_id = None
        try:
            from .service import BaselinkerService
            service = BaselinkerService()
            suggested_source_id = service.suggest_order_source(
                client=quote.client,
                user_role=user_role,
                is_flexible_partner=is_flexible_partner
            )
            baselinker_logger.info("Sugerowane źródło zamówienia",
                                  suggested_source_id=suggested_source_id,
                                  client_id=quote.client_id if quote.client else None)
        except Exception as suggest_error:
            baselinker_logger.error("Błąd sugerowania źródła zamówienia", error=str(suggest_error))

        # Oblicz koszty wysyłki
        shipping_cost_brutto = float(quote.shipping_cost_brutto or 0)
        shipping_cost_netto = shipping_cost_brutto / 1.23 if shipping_cost_brutto > 0 else 0

        # Poprawne koszty całkowite (produkty + wykończenie + krawędzie + wysyłka)
        total_value_netto = total_products_value_netto + total_finishing_value_netto + total_edges_value_netto + shipping_cost_netto
        total_value_brutto = total_products_value_brutto + total_finishing_value_brutto + total_edges_value_brutto + shipping_cost_brutto

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
                'notes': quote.notes or '',
                'quote_type': quote_type,
                'attachment_filename': quote.attachment_filename,
                'attachment_stored_name': quote.attachment_stored_name,
            },
            'client': client_data,
            'products': products,
            'costs': {
                'products_brutto': round(total_products_value_brutto, 2),
                'products_netto': round(total_products_value_netto, 2),
                'finishing_brutto': round(total_finishing_value_brutto, 2),
                'finishing_netto': round(total_finishing_value_netto, 2),
                'edges_brutto': round(total_edges_value_brutto, 2),
                'edges_netto': round(total_edges_value_netto, 2),
                'shipping_brutto': round(shipping_cost_brutto, 2),
                'shipping_netto': round(shipping_cost_netto, 2),
                'total_brutto': round(total_value_brutto, 2),
                'total_netto': round(total_value_netto, 2)
            },
            'config': config_data,
            'suggested_source_id': suggested_source_id
        }
        
        baselinker_logger.info("Przygotowano dane dla modalu zamówienia",
                              quote_id=quote_id,
                              quote_type=quote_type,
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


@baselinker_bp.route('/api/order/<int:order_id>/sales-documents')
@require_module_access('baselinker')
def get_sales_documents(order_id):
    """
    Pobiera wszystkie dokumenty sprzedaży dla zamówienia Baselinker
    (faktura, korekta, e-paragon, strona informacyjna)
    """
    baselinker_logger.info("Rozpoczęcie pobierania dokumentów sprzedaży",
                          order_id=order_id,
                          endpoint='get_sales_documents')
    
    try:
        # Znajdź wycenę po base_linker_order_id
        from modules.calculator.models import Quote
        
        quote = Quote.query.filter_by(base_linker_order_id=str(order_id)).first()
        
        if not quote:
            baselinker_logger.warning("Nie znaleziono wyceny dla zamówienia Baselinker",
                                     order_id=order_id)
            return jsonify({
                'status': 'error',
                'error': 'Nie znaleziono wyceny dla tego zamówienia',
                'code': 'QUOTE_NOT_FOUND'
            }), 404
        
        baselinker_logger.debug("Znaleziono wycenę dla zamówienia",
                               order_id=order_id,
                               quote_id=quote.id,
                               quote_number=quote.quote_number)
        
        # Wywołaj service do pobrania dokumentów
        service = BaselinkerService()
        result = service.get_sales_documents(order_id, quote.id)
        
        baselinker_logger.debug("Otrzymano wynik z service",
                               order_id=order_id,
                               result_status=result.get('status'),
                               has_invoice=result.get('invoice', {}).get('exists'),
                               has_correction=result.get('correction', {}).get('exists'),
                               has_receipt=result.get('receipt', {}).get('exists'))
        
        if result.get('status') == 'error':
            baselinker_logger.error("Błąd podczas pobierania dokumentów",
                                   order_id=order_id,
                                   error=result.get('error'),
                                   error_code=result.get('code'))
            return jsonify(result), 500
        
        baselinker_logger.info("Pomyślnie pobrano dokumenty sprzedaży",
                              order_id=order_id,
                              quote_id=quote.id,
                              invoice_exists=result['invoice']['exists'],
                              correction_exists=result['correction']['exists'],
                              receipt_exists=result['receipt']['exists'])
        
        return jsonify(result)
        
    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania dokumentów sprzedaży",
                               order_id=order_id,
                               error=str(e),
                               error_type=type(e).__name__)
        import traceback
        baselinker_logger.debug("Stack trace błędu",
                               traceback=traceback.format_exc())
        
        return jsonify({
            'status': 'error',
            'error': 'Błąd serwera podczas pobierania dokumentów',
            'code': 'SERVER_ERROR'
        }), 500


# ============================================================================
# COURIER API - Diagnostyka i tworzenie paczek (2025-12)
# ============================================================================

@baselinker_bp.route('/api/courier/list')
@require_module_access('baselinker')
def get_couriers_list():
    """
    Pobiera listę dostępnych kurierów z Baselinker.
    Użycie w konsoli JS: fetch('/baselinker/api/courier/list').then(r => r.json()).then(console.log)
    """
    baselinker_logger.info("Pobieranie listy kurierów z Baselinker API")

    try:
        service = BaselinkerService()
        response = service._make_request('getCouriersList', {})

        if response.get('status') == 'SUCCESS':
            couriers = response.get('couriers', [])
            baselinker_logger.info("Pobrano listę kurierów", couriers_count=len(couriers))
            return jsonify({
                'success': True,
                'couriers': couriers
            })
        else:
            error_msg = response.get('error_message', 'Nieznany błąd')
            baselinker_logger.error("Błąd API getCouriersList", error=error_msg)
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania kurierów", error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@baselinker_bp.route('/api/courier/<string:courier_code>/accounts')
@require_module_access('baselinker')
def get_courier_accounts(courier_code):
    """
    Pobiera konta kurierskie dla danego kuriera.
    Użycie w konsoli JS: fetch('/baselinker/api/courier/globkurier/accounts').then(r => r.json()).then(console.log)
    """
    baselinker_logger.info("Pobieranie kont kurierskich", courier_code=courier_code)

    try:
        service = BaselinkerService()
        response = service._make_request('getCourierAccounts', {'courier_code': courier_code})

        if response.get('status') == 'SUCCESS':
            accounts = response.get('accounts', [])
            baselinker_logger.info("Pobrano konta kurierskie",
                                  courier_code=courier_code,
                                  accounts_count=len(accounts))
            return jsonify({
                'success': True,
                'courier_code': courier_code,
                'accounts': accounts
            })
        else:
            error_msg = response.get('error_message', 'Nieznany błąd')
            baselinker_logger.error("Błąd API getCourierAccounts",
                                   courier_code=courier_code,
                                   error=error_msg)
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania kont", error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@baselinker_bp.route('/api/courier/<string:courier_code>/fields')
@require_module_access('baselinker')
def get_courier_fields(courier_code):
    """
    Pobiera pola formularza dla danego kuriera.
    Użycie w konsoli JS: fetch('/baselinker/api/courier/globkurier/fields').then(r => r.json()).then(console.log)
    """
    baselinker_logger.info("Pobieranie pól formularza kuriera", courier_code=courier_code)

    try:
        service = BaselinkerService()
        response = service._make_request('getCourierFields', {'courier_code': courier_code})

        if response.get('status') == 'SUCCESS':
            fields = response.get('fields', [])
            baselinker_logger.info("Pobrano pola formularza",
                                  courier_code=courier_code,
                                  fields_count=len(fields))
            return jsonify({
                'success': True,
                'courier_code': courier_code,
                'fields': fields
            })
        else:
            error_msg = response.get('error_message', 'Nieznany błąd')
            baselinker_logger.error("Błąd API getCourierFields",
                                   courier_code=courier_code,
                                   error=error_msg)
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania pól", error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@baselinker_bp.route('/api/order/<int:order_id>/packages')
@require_module_access('baselinker')
def get_order_packages(order_id):
    """
    Pobiera utworzone przesyłki dla zamówienia.
    Użycie w konsoli JS: fetch('/baselinker/api/order/12345678/packages').then(r => r.json()).then(console.log)
    """
    baselinker_logger.info("Pobieranie przesyłek dla zamówienia", order_id=order_id)

    try:
        service = BaselinkerService()
        response = service._make_request('getOrderPackages', {'order_id': order_id})

        if response.get('status') == 'SUCCESS':
            packages = response.get('packages', [])
            baselinker_logger.info("Pobrano przesyłki",
                                  order_id=order_id,
                                  packages_count=len(packages))
            return jsonify({
                'success': True,
                'order_id': order_id,
                'packages': packages
            })
        else:
            error_msg = response.get('error_message', 'Nieznany błąd')
            baselinker_logger.error("Błąd API getOrderPackages",
                                   order_id=order_id,
                                   error=error_msg)
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        baselinker_logger.error("Wyjątek podczas pobierania przesyłek", error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500