# app/modules/baselinker/service.py - WERSJA Z NOWYM STRUKTURALNYM LOGOWANIEM

import requests
import json
import sys
from typing import Dict, List, Optional
from flask import current_app, session, request
from extensions import db
from .models import BaselinkerOrderLog, BaselinkerConfig
from modules.logging import get_structured_logger
from datetime import datetime

class BaselinkerService:
    """Serwis do komunikacji z API Baselinker"""
    
    def __init__(self):
        self.api_key = current_app.config.get('API_BASELINKER', {}).get('api_key')
        self.endpoint = current_app.config.get('API_BASELINKER', {}).get('endpoint')
        self.logger = get_structured_logger('baselinker.service')
    
    def _make_request(self, method: str, parameters: Dict) -> Dict:
        """Wykonuje żądanie do API Baselinker"""
        if not self.api_key or not self.endpoint:
            self.logger.error("Brak konfiguracji API Baselinker", 
                            method=method, 
                            has_api_key=bool(self.api_key),
                            has_endpoint=bool(self.endpoint))
            raise ValueError("Brak konfiguracji API Baselinker")
        
        headers = {
            'X-BLToken': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'method': method,
            'parameters': json.dumps(parameters)
        }
        
        self.logger.info("Wysyłanie żądania API", 
                        method=method, 
                        endpoint=self.endpoint,
                        params_keys=list(parameters.keys()))
        
        try:
            response = requests.post(self.endpoint, headers=headers, data=data, timeout=30)
            
            self.logger.debug("Otrzymano odpowiedź API", 
                            method=method,
                            status_code=response.status_code,
                            response_size=len(response.content))
            
            response.raise_for_status()
            response_json = response.json()
            
            api_status = response_json.get('status')
            if api_status == 'SUCCESS':
                self.logger.info("Pomyślne wywołanie API", 
                               method=method, 
                               api_status=api_status)
            else:
                self.logger.warning("API zwróciło błąd", 
                                  method=method, 
                                  api_status=api_status,
                                  error_message=response_json.get('error_message'))

            return response_json
            
        except requests.exceptions.RequestException as e:
            self.logger.error("Błąd żądania API", 
                            method=method, 
                            error=str(e),
                            error_type=type(e).__name__)
            raise
    
    def get_order_sources(self) -> List[Dict]:
        """Pobiera dostępne źródła zamówień"""
        self.logger.info("Pobieranie źródeł zamówień z API")
        
        try:
            response = self._make_request('getOrderSources', {})
        
            if response.get('status') == 'SUCCESS':
                sources_data = response.get('sources', {})
                self.logger.debug("Odebrano dane źródeł", 
                                categories_count=len(sources_data),
                                raw_data_keys=list(sources_data.keys()))
            
                sources_list = []
            
                for category, items in sources_data.items():
                    self.logger.debug("Przetwarzanie kategorii źródeł", 
                                    category=category, 
                                    items_count=len(items))
                
                    for source_id, source_name in items.items():
                        sources_list.append({
                            'id': int(source_id) if source_id.isdigit() else 0,
                            'name': f"{source_name} ({category})",
                            'category': category
                        })
                        self.logger.debug("Dodano źródło", 
                                        source_id=source_id, 
                                        source_name=source_name, 
                                        category=category)
            
                self.logger.info("Pomyślnie pobrano źródła zamówień", 
                               total_sources=len(sources_list))
                return sources_list
            else:
                error_msg = response.get('error_message', 'Unknown error')
                self.logger.error("API zwróciło błąd w getOrderSources", 
                                error_message=error_msg)
                raise Exception(f"API Error: {error_msg}")
                
        except Exception as e:
            self.logger.error("Błąd pobierania źródeł zamówień", 
                            error=str(e),
                            error_type=type(e).__name__)
            raise
    
    def get_order_statuses(self) -> List[Dict]:
        """Pobiera dostępne statusy zamówień"""
        self.logger.info("Pobieranie statusów zamówień z API")
        
        try:
            methods_to_try = ['getOrderStatusList', 'getOrderStatuses']
            
            for method_name in methods_to_try:
                try:
                    self.logger.debug("Próba wywołania metody", method=method_name)
                    response = self._make_request(method_name, {})
                    
                    if response.get('status') == 'SUCCESS':
                        statuses = (response.get('order_statuses') or 
                                  response.get('statuses') or 
                                  response.get('order_status_list') or [])
                        
                        self.logger.info("Pomyślnie pobrano statusy", 
                                       method=method_name,
                                       statuses_count=len(statuses))
                        return statuses
                    else:
                        error_msg = response.get('error_message', 'Unknown error')
                        self.logger.warning("Metoda zwróciła błąd", 
                                          method=method_name,
                                          error_message=error_msg)
                        continue
                        
                except Exception as method_error:
                    self.logger.warning("Nieudana próba wywołania metody", 
                                      method=method_name,
                                      error=str(method_error))
                    continue
            
            self.logger.error("Wszystkie metody pobierania statusów nieudane")
            raise Exception("Wszystkie metody pobierania statusów nieudane")
            
        except Exception as e:
            self.logger.error("Błąd pobierania statusów zamówień", 
                            error=str(e),
                            error_type=type(e).__name__)
            raise
    
    def sync_order_sources(self) -> bool:
        """Synchronizuje źródła zamówień z Baselinker"""
        self.logger.info("Rozpoczęcie synchronizacji źródeł zamówień")
        
        try:
            sources = self.get_order_sources()
            self.logger.debug("Pobrano źródła do synchronizacji", sources_count=len(sources))
        
            # DODAJ STANDARDOWE ŹRÓDŁA JEŚLI ICH BRAK
            standard_sources = [
                {'id': 0, 'name': 'Osobiście (personal)', 'category': 'personal'},
                # Możesz dodać więcej standardowych źródeł
            ]
        
            # Połącz źródła z API i standardowe
            all_sources = sources + standard_sources
            
            updated_count = 0
            created_count = 0
        
            for source in all_sources:
                self.logger.debug("Przetwarzanie źródła", 
                                source_id=source.get('id'),
                                source_name=source.get('name'))
            
                existing = BaselinkerConfig.query.filter_by(
                    config_type='order_source',
                    baselinker_id=source.get('id')
                ).first()
            
                if not existing:
                    config = BaselinkerConfig(
                        config_type='order_source',
                        baselinker_id=source.get('id'),
                        name=source.get('name', 'Nieznane zrodlo')
                    )
                    db.session.add(config)
                    created_count += 1
                    self.logger.debug("Utworzono nowe źródło", 
                                    source_name=config.name,
                                    source_id=config.baselinker_id)
                else:
                    existing.name = source.get('name', existing.name)
                    existing.is_active = True
                    updated_count += 1
                    self.logger.debug("Zaktualizowano źródło", 
                                    source_name=existing.name,
                                    source_id=existing.baselinker_id)
        
            db.session.commit()
        
            saved_count = BaselinkerConfig.query.filter_by(config_type='order_source').count()
            self.logger.info("Synchronizacja źródeł zakończona pomyślnie", 
                           created_count=created_count,
                           updated_count=updated_count,
                           total_in_db=saved_count)
        
            return True
        
        except Exception as e:
            db.session.rollback()
            self.logger.error("Błąd synchronizacji źródeł", 
                            error=str(e),
                            error_type=type(e).__name__)
            return False
    
    def sync_order_statuses(self) -> bool:
        """Synchronizuje statusy zamówień z Baselinker"""
        self.logger.info("Rozpoczęcie synchronizacji statusów zamówień")
        
        try:
            statuses = self.get_order_statuses()
            self.logger.debug("Pobrano statusy do synchronizacji", statuses_count=len(statuses))
            
            updated_count = 0
            created_count = 0
            
            for status in statuses:
                self.logger.debug("Przetwarzanie statusu", 
                                status_id=status.get('id'),
                                status_name=status.get('name'))
                
                existing = BaselinkerConfig.query.filter_by(
                    config_type='order_status',
                    baselinker_id=status.get('id')
                ).first()
                
                if not existing:
                    config = BaselinkerConfig(
                        config_type='order_status',
                        baselinker_id=status.get('id'),
                        name=status.get('name', 'Nieznany status')
                    )
                    db.session.add(config)
                    created_count += 1
                    self.logger.debug("Utworzono nowy status", 
                                    status_name=config.name,
                                    status_id=config.baselinker_id)
                else:
                    existing.name = status.get('name', existing.name)
                    existing.is_active = True
                    updated_count += 1
                    self.logger.debug("Zaktualizowano status", 
                                    status_name=existing.name,
                                    status_id=existing.baselinker_id)
            
            db.session.commit()
            
            saved_count = BaselinkerConfig.query.filter_by(config_type='order_status').count()
            self.logger.info("Synchronizacja statusów zakończona pomyślnie", 
                           created_count=created_count,
                           updated_count=updated_count,
                           total_in_db=saved_count)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            self.logger.error("Błąd synchronizacji statusów", 
                            error=str(e),
                            error_type=type(e).__name__)
            return False

    def get_order_details(self, order_id: int) -> Dict:
        """Pobiera szczegóły zamówienia z Baselinker"""
        self.logger.info("Pobieranie szczegółów zamówienia", order_id=order_id)
        
        try:
            parameters = {'order_id': order_id}
            
            response = self._make_request('getOrders', parameters)
            
            if response.get('status') == 'SUCCESS':
                orders = response.get('orders', [])
                self.logger.debug("Otrzymano odpowiedź getOrders", 
                                orders_count=len(orders),
                                order_id=order_id)
                
                if orders:
                    order = orders[0]  # getOrders zwraca listę, ale z order_id powinien być jeden
                    
                    order_details = {
                        'order_id': order.get('order_id'),
                        'order_status_id': order.get('order_status_id'),
                        'payment_done': order.get('payment_done', 0),
                        'currency': order.get('currency'),
                        'order_page': order.get('order_page'),
                        'date_add': order.get('date_add'),
                        'date_confirmed': order.get('date_confirmed')
                    }

                    self.logger.info("Pomyślnie pobrano szczegóły zamówienia",
                                   order_id=order_id,
                                   status_id=order_details['order_status_id'],
                                   payment_done=order_details['payment_done'])

                    return {
                        'success': True,
                        'order': order_details
                    }
                else:
                    self.logger.warning("Zamówienie nie znalezione", order_id=order_id)
                    return {'success': False, 'error': 'Zamówienie nie znalezione'}
            else:
                error_msg = response.get('error_message', 'Unknown error')
                self.logger.error("API zwróciło błąd w get_order_details", 
                                order_id=order_id,
                                error_message=error_msg)
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            self.logger.error("Wyjątek podczas pobierania szczegółów zamówienia", 
                            order_id=order_id,
                            error=str(e),
                            error_type=type(e).__name__)
            import traceback
            self.logger.debug("Stack trace błędu", traceback=traceback.format_exc())
            return {'success': False, 'error': str(e)}

    def create_order_from_quote(self, quote, user_id: int, config: Dict) -> Dict:
        """Tworzy zamówienie w Baselinker na podstawie wyceny"""
        self.logger.info("Rozpoczęcie tworzenia zamówienia z wyceny",
                        quote_id=quote.id,
                        quote_number=quote.quote_number,
                        user_id=user_id)
        if config.get('client_data'):
            client_override = config['client_data']
            self.logger.debug("Otrzymano jednorazowe dane klienta",
                             quote_id=quote.id,
                             delivery_name=client_override.get('delivery_name'),
                             email=client_override.get('email'),
                             want_invoice=client_override.get('want_invoice'))
        
        try:
            # Przygotuj dane zamówienia
            order_data = self._prepare_order_data(quote, config)
            
            self.logger.debug("Przygotowano dane zamówienia",
                            quote_id=quote.id,
                            products_count=len(order_data.get('products', [])),
                            order_source_id=order_data.get('custom_source_id'),
                            order_status_id=order_data.get('order_status_id'))
            
            # Loguj żądanie
            log_entry = BaselinkerOrderLog(
                quote_id=quote.id,
                action='create_order',
                status='pending',
                request_data=json.dumps(order_data),
                created_by=user_id
            )
            db.session.add(log_entry)
            db.session.flush()
            
            self.logger.debug("Utworzono log entry", log_id=log_entry.id)
            
            # Wyślij żądanie do API
            response = self._make_request('addOrder', order_data)
            
            if response.get('status') == 'SUCCESS':
                baselinker_order_id = response.get('order_id')
                
                # Aktualizuj log
                log_entry.status = 'success'
                log_entry.baselinker_order_id = baselinker_order_id
                log_entry.response_data = json.dumps(response)
                
                # Zaktualizuj wycenę
                quote.base_linker_order_id = baselinker_order_id
                
                # NOWE: Zmień status wyceny na "Złożone" (ID=4)
                quote.status_id = 4
                
                db.session.commit()
                
                self.logger.info("Pomyślnie utworzono zamówienie",
                               quote_id=quote.id,
                               baselinker_order_id=baselinker_order_id,
                               log_id=log_entry.id)
                
                return {
                    'success': True,
                    'order_id': baselinker_order_id,
                    'message': 'Zamowienie zostalo utworzone pomyslnie'
                }
            else:
                error_msg = response.get('error_message', 'Nieznany blad API')
                log_entry.status = 'error'
                log_entry.error_message = error_msg
                log_entry.response_data = json.dumps(response)
                db.session.commit()
                
                self.logger.error("Błąd tworzenia zamówienia w API",
                                quote_id=quote.id,
                                error_message=error_msg,
                                log_id=log_entry.id)
                
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            if 'log_entry' in locals():
                log_entry.status = 'error'
                log_entry.error_message = str(e)
                db.session.commit()
                self.logger.debug("Zaktualizowano log entry z błędem", log_id=log_entry.id)
            
            self.logger.error("Wyjątek podczas tworzenia zamówienia", 
                            quote_id=quote.id,
                            error=str(e),
                            error_type=type(e).__name__)
            return {
                'success': False,
                'error': str(e)
            }
    
    def _prepare_order_data(self, quote, config: Dict) -> Dict:
        """Przygotowuje dane zamówienia dla API Baselinker"""
        import time
        from modules.calculator.models import QuoteItemDetails

        self.logger.debug("Rozpoczęcie przygotowania danych zamówienia",
                        quote_id=quote.id,
                        config_keys=list(config.keys()),
                        has_client_data_override=bool(config.get('client_data')))

        creator = getattr(quote, 'user', None)
        creator_name = f"{creator.first_name} {creator.last_name}" if creator else ''

        # 🔧 POPRAWKA: Zabezpieczenie przed błędem AppenderQuery
        try:
            # Konwertuj AppenderQuery na listę przed użyciem len()
            all_items = list(quote.items)
            selected_items = [item for item in all_items if item.is_selected]
    
            self.logger.debug("Wybrane produkty do zamówienia", 
                            selected_items_count=len(selected_items),
                            total_items_count=len(all_items))
        except Exception as e:
            # Fallback gdyby był problem z konwersją
            self.logger.warning("Problem z konwersją quote.items na listę",
                              quote_id=quote.id,
                              error=str(e))
            selected_items = []
            for item in quote.items:
                if item.is_selected:
                    selected_items.append(item)
    
            self.logger.debug("Wybrane produkty do zamówienia (fallback)", 
                            selected_items_count=len(selected_items))

        # Sprawdź czy są wybrane produkty
        if not selected_items:
            self.logger.error("Brak wybranych produktów w wycenie", quote_id=quote.id)
            raise ValueError("Wycena nie ma wybranych produktów")

        # Przygotuj produkty
        products = []
        for i, item in enumerate(selected_items):
            # Pobierz szczegóły wykończenia
            finishing_details = QuoteItemDetails.query.filter_by(
                quote_id=quote.id, 
                product_index=item.product_index
            ).first()

            # Pobierz quantity z QuoteItemDetails
            quantity = finishing_details.quantity if finishing_details else 1
            self.logger.debug("Przetwarzanie produktu",
                            product_index=item.product_index,
                            variant_code=item.variant_code,
                            quantity=quantity,
                            has_finishing=bool(finishing_details))

            # Generuj SKU według schematu
            sku = self._generate_sku(item, finishing_details)

            # Nazwa produktu z wymiarami
            base_name = f"{self._translate_variant_code(item.variant_code)} {item.length_cm}×{item.width_cm}×{item.thickness_cm} cm"

            # NOWE: Używamy cen jednostkowych bezpośrednio z bazy (już nie trzeba dzielić!)
            unit_price_netto = float(item.price_netto or 0)
            unit_price_brutto = float(item.price_brutto or 0)

            self.logger.debug("Ceny produktu z bazy",
                            product_index=item.product_index,
                            unit_price_netto=unit_price_netto,
                            unit_price_brutto=unit_price_brutto)

            # Dodaj cenę wykończenia do ceny jednostkowej (jeśli istnieje)
            if finishing_details and finishing_details.finishing_price_netto:
                # finishing_details.finishing_price_netto to CAŁKOWITY koszt wykończenia
                # Dzielimy przez quantity, żeby otrzymać koszt za 1 sztukę
                finishing_total_netto = float(finishing_details.finishing_price_netto or 0)
                finishing_total_brutto = float(finishing_details.finishing_price_brutto or 0)
    
                finishing_unit_netto = finishing_total_netto / quantity if quantity > 0 else 0
                finishing_unit_brutto = finishing_total_brutto / quantity if quantity > 0 else 0

                unit_price_netto += finishing_unit_netto
                unit_price_brutto += finishing_unit_brutto

                self.logger.debug("Dodano cenę wykończenia jednostkową",
                                product_index=item.product_index,
                                finishing_total_netto=finishing_total_netto,
                                finishing_total_brutto=finishing_total_brutto,
                                quantity=quantity,
                                finishing_unit_netto=finishing_unit_netto,
                                finishing_unit_brutto=finishing_unit_brutto)

            self.logger.debug("Finalne ceny produktu",
                            product_index=item.product_index,
                            final_unit_netto=unit_price_netto,
                            final_unit_brutto=unit_price_brutto,
                            quantity=quantity)

            # Oblicz wagę (zakładając gęstość drewna ~0.7 kg/dm³)
            volume_dm3 = float(item.volume_m3 or 0) * 1000  # m³ na dm³
            weight_kg = round(volume_dm3 * 0.7, 2) if item.volume_m3 else 0.0

            self.logger.debug("Obliczenie wagi produktu",
                            product_index=item.product_index,
                            volume_m3=item.volume_m3,
                            volume_dm3=volume_dm3,
                            weight_kg=weight_kg)

            # Dodaj wykończenie do nazwy jeśli istnieje
            product_name = base_name
            if finishing_details and finishing_details.finishing_type and finishing_details.finishing_type != 'Brak' and finishing_details.finishing_type != 'Surowe':
                finishing_desc = self._translate_finishing_to_adjective(finishing_details)
                if finishing_desc:
                    product_name += f" {finishing_desc}"
            else:
                product_name += " surowa"

            products.append({
                'name': product_name,
                'sku': sku,
                'ean': '',  # EAN opcjonalny
                'price_brutto': round(unit_price_brutto, 2),  # CENA JEDNOSTKOWA (nie całkowita!)
                'price_netto': round(unit_price_netto, 2),    # CENA JEDNOSTKOWA (nie całkowita!)
                'tax_rate': 23,  # VAT 23%
                'quantity': quantity,
                'weight': weight_kg,
                'variant_id': 0
            })

        # 🆕 NOWA LOGIKA: Przygotuj dane klienta z obsługą jednorazowych zmian
        client_data = {}
    
        # Sprawdź czy w config są jednorazowe dane klienta
        if 'client_data' in config and config['client_data']:
            # Użyj jednorazowych danych z formularza
            form_data = config['client_data']
        
            self.logger.info("Używam jednorazowych danych klienta z formularza",
                            quote_id=quote.id,
                            delivery_name=form_data.get('delivery_name'),
                            email=form_data.get('email'),
                            want_invoice=form_data.get('want_invoice'))
        
            client_data = {
                'name': form_data.get('delivery_name', ''),
                'delivery_name': form_data.get('delivery_name', ''),
                'email': form_data.get('email', ''),
                'phone': form_data.get('phone', ''),
                'delivery_address': form_data.get('delivery_address', ''),
                'delivery_postcode': form_data.get('delivery_postcode', ''),
                'delivery_city': form_data.get('delivery_city', ''),
                'delivery_region': form_data.get('delivery_region', ''),
                'delivery_company': form_data.get('delivery_company', ''),
                'invoice_name': form_data.get('invoice_name', ''),
                'invoice_company': form_data.get('invoice_company', ''),
                'invoice_nip': form_data.get('invoice_nip', ''),
                'invoice_address': form_data.get('invoice_address', ''),
                'invoice_postcode': form_data.get('invoice_postcode', ''),
                'invoice_city': form_data.get('invoice_city', ''),
                'invoice_region': form_data.get('invoice_region', ''),
                'want_invoice': form_data.get('want_invoice', False)
            }
        
        elif quote.client:
            # Fallback: użyj danych z bazy (istniejący kod)
            client = quote.client
        
            self.logger.info("Używam danych klienta z bazy danych",
                            quote_id=quote.id,
                            client_id=client.id,
                            client_name=client.client_name)
        
            client_data = {
                'name': client.client_name,
                'delivery_name': client.client_delivery_name or client.client_name,
                'email': client.email,
                'phone': client.phone,
                'delivery_address': client.delivery_address or '',
                'delivery_postcode': client.delivery_zip or '',
                'delivery_city': client.delivery_city or '',
                'delivery_region': client.delivery_region or '',
                'delivery_company': client.delivery_company or '',
                'invoice_name': client.invoice_name or client.client_name or '',
                'invoice_company': client.invoice_company or '',
                'invoice_nip': client.invoice_nip or '',
                'invoice_address': client.invoice_address or '',
                'invoice_postcode': client.invoice_zip or '',
                'invoice_city': client.invoice_city or '',
                'invoice_region': client.invoice_region or '',
                'want_invoice': bool(client.invoice_nip)
            }
        else:
            self.logger.error("Wycena nie ma przypisanego klienta i brak danych w formularzu", 
                             quote_id=quote.id)
            raise ValueError("Wycena nie ma przypisanego klienta")

        # Konfiguracja zamówienia
        order_source_id = config.get('order_source_id')
        order_status_id = config.get('order_status_id')
        payment_method = config.get('payment_method', 'Przelew bankowy')
        delivery_method = config.get('delivery_method', quote.courier_name or 'Przesyłka kurierska')
    
        # Obsługa nadpisanych kosztów wysyłki
        if 'shipping_cost_override' in config and config['shipping_cost_override'] is not None:
            delivery_price = float(config['shipping_cost_override'])
            self.logger.debug("Używam nadpisanych kosztów wysyłki",
                             quote_id=quote.id,
                             override_cost=delivery_price,
                             original_cost=quote.shipping_cost_brutto)
        else:
            delivery_price = float(quote.shipping_cost_brutto or 0)

        self.logger.debug("Konfiguracja zamówienia",
                        order_source_id=order_source_id,
                        order_status_id=order_status_id,
                        payment_method=payment_method,
                        delivery_method=delivery_method,
                        delivery_price=delivery_price)

        total_quantity = sum(p['quantity'] for p in products)
        self.logger.info("Przygotowano produkty do zamówienia",
                    products_count=len(products),
                    total_quantity=total_quantity,
                    using_override_client_data=bool(config.get('client_data')))

        # ✅ DODANE: Zbuduj user_comments z debugowaniem
        user_comments_value = self._build_user_comments(quote)

        order_data = {
            'custom_source_id': order_source_id,
            'order_status_id': order_status_id,
            'date_add': int(time.time()),
            'currency': 'PLN',
            'payment_method': payment_method,
            'payment_method_cod': 'false',
            'paid': '0',
            'user_comments': '',
            'admin_comments': user_comments_value,
            'phone': client_data.get('phone', ''),
            'email': client_data.get('email', ''),
            'user_login': client_data.get('name', ''),
            'delivery_method': delivery_method,
            'delivery_price': delivery_price,
            'delivery_fullname': client_data.get('delivery_name', ''),
            'delivery_company': client_data.get('delivery_company', ''),
            'delivery_address': client_data.get('delivery_address', ''),
            'delivery_postcode': client_data.get('delivery_postcode', ''),
            'delivery_city': client_data.get('delivery_city', ''),
            'delivery_state': client_data.get('delivery_region', ''),
            'delivery_country_code': config.get('delivery_country', 'PL'),
            'delivery_point_id': '',
            'delivery_point_name': '',
            'delivery_point_address': '',
            'delivery_point_postcode': '',
            'delivery_point_city': '',
            'invoice_fullname': client_data.get('invoice_name', ''),
            'invoice_company': client_data.get('invoice_company', ''),
            'invoice_nip': client_data.get('invoice_nip', ''),
            'invoice_address': client_data.get('invoice_address', ''),
            'invoice_postcode': client_data.get('invoice_postcode', ''),
            'invoice_city': client_data.get('invoice_city', ''),
            'invoice_state': client_data.get('invoice_region', ''),
            'invoice_country_code': config.get('delivery_country', 'PL'),
            'want_invoice': client_data.get('want_invoice', False),
            'extra_field_1': '',
            'extra_field_2': '',
            'custom_extra_fields': {
                '105623': creator_name
            },
            'products': products
        }

        self.logger.info("Dane zamówienia przygotowane",
                       order_source_id=order_data['custom_source_id'],
                       order_status_id=order_data['order_status_id'],
                       delivery_method=order_data['delivery_method'],
                       delivery_price=order_data['delivery_price'],
                       products_count=len(products),
                       client_email=order_data['email'],
                       client_delivery_name=order_data['delivery_fullname'],
                       client_invoice_name=order_data['invoice_fullname'])

        return order_data
    
    def _generate_sku(self, item, finishing_details=None):
        """Generuje SKU w formacie BLADEBLIT3501004ABSUR"""
        try:
            # Parsuj kod wariantu (np. "dab-lity-ab")
            variant_parts = item.variant_code.lower().split('-') if item.variant_code else []
            
            # 1. Typ produktu (zawsze BLA dla blat)
            product_type = "BLA"
            
            # 2. Gatunek drewna (pierwsze 3 litery)
            species_map = {
                'dab': 'DEB',
                'jes': 'JES', 
                'buk': 'BUK',
                'brzoza': 'BRZ',
                'sosna': 'SOS'
            }
            species = species_map.get(variant_parts[0] if len(variant_parts) > 0 else '', 'XXX')
            
            # 3. Technologia (pierwsze 3 litery)
            tech_map = {
                'lity': 'LIT',
                'micro': 'MIC',
                'finger': 'FIN'
            }
            technology = tech_map.get(variant_parts[1] if len(variant_parts) > 1 else '', 'XXX')
            
            # 4. Wymiary (bez zer wiodących, ale minimum 3 cyfry dla długości)
            length = str(int(item.length_cm or 0)).zfill(3) if item.length_cm else "000"
            width = str(int(item.width_cm or 0)) if item.width_cm else "0"  
            thickness = str(int(item.thickness_cm or 0)) if item.thickness_cm else "0"
            
            # 5. Klasa drewna
            wood_class = variant_parts[2].upper() if len(variant_parts) > 2 else "XX"
            
            # 6. Wykończenie
            finishing = "SUR"  # Domyślnie surowe
            if finishing_details and finishing_details.finishing_type and finishing_details.finishing_type != 'Brak':
                # Mapowanie wykończeń na 3-literowe kody
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
            
            # Składamy SKU
            sku = f"{product_type}{species}{technology}{length}{width}{thickness}{wood_class}{finishing}"
            
            self.logger.debug("Wygenerowano SKU",
                            item_id=item.id,
                            variant_code=item.variant_code,
                            sku=sku,
                            product_type=product_type,
                            species=species,
                            technology=technology,
                            dimensions=f"{length}x{width}x{thickness}",
                            wood_class=wood_class,
                            finishing=finishing)
            
            return sku
            
        except Exception as e:
            self.logger.error("Błąd generowania SKU", 
                            item_id=getattr(item, 'id', None),
                            variant_code=getattr(item, 'variant_code', None),
                            error=str(e))
            # Fallback na stary format
            fallback_sku = f"WP-{item.variant_code.upper()}-{item.id}" if item.variant_code else f"WP-UNKNOWN-{item.id}"
            self.logger.warning("Użyto fallback SKU", sku=fallback_sku)
            return fallback_sku
    
    def _translate_variant_code(self, code: str) -> str:
        """Tłumaczy kod wariantu na czytelną nazwę"""
        translations = {
            'dab-lity-ab': 'Klejonka dębowa lita A/B',
            'dab-lity-bb': 'Klejonka dębowa lita B/B',
            'dab-micro-ab': 'Klejonka dębowa mikrowczep A/B',
            'dab-micro-bb': 'Klejonka dębowa mikrowczep B/B',
            'jes-lity-ab': 'Klejonka jesionowa lita A/B',
            'jes-micro-ab': 'Klejonka jesionowa mikrowczep A/B',
            'buk-lity-ab': 'Klejonka bukowa lita A/B',
            'buk-micro-ab': 'Klejonka bukowa mikrowczep A/B'
        }
        return translations.get(code, f'Klejonka {code}' if code else 'Nieznany produkt')
    
    def _translate_finishing(self, finishing_details):
        """Tłumaczy szczegóły wykończenia na czytelny opis"""
        if not finishing_details or not finishing_details.finishing_type or finishing_details.finishing_type == 'Brak':
            return None
        
        parts = []
        
        # Typ wykończenia
        if finishing_details.finishing_type:
            parts.append(finishing_details.finishing_type)
        
        # Wariant wykończenia
        if finishing_details.finishing_variant and finishing_details.finishing_variant != finishing_details.finishing_type:
            parts.append(finishing_details.finishing_variant)
        
        # Kolor
        if finishing_details.finishing_color:
            parts.append(finishing_details.finishing_color)
        
        # Poziom połysku
        if finishing_details.finishing_gloss_level:
            parts.append(f"połysk {finishing_details.finishing_gloss_level}")
        
        return ' - '.join(parts) if parts else None

    def _translate_finishing_to_adjective(self, finishing_details):
        """Tłumaczy szczegóły wykończenia na przymiotnik w rodzaju żeńskim (dla klejonki)"""
        if not finishing_details or not finishing_details.finishing_type or finishing_details.finishing_type == 'Brak':
            return None
    
        finishing_type = finishing_details.finishing_type.lower()
    
        # Mapowanie na przymiotniki w rodzaju żeńskim
        if 'lakier' in finishing_type:
            result = 'lakierowana'
        
            # Dodaj wariant lakieru jeśli istnieje
            if finishing_details.finishing_color and finishing_details.finishing_color != 'Brak':
                if finishing_details.finishing_color.lower() == 'bezbarwny' or 'bezbarwn' in finishing_details.finishing_color.lower():
                    result += ' bezbarwnie'
                else:
                    result += f' {finishing_details.finishing_color}'
            else:
                result += ' bezbarwnie'  # Domyślnie bezbarwnie
            
        elif 'olej' in finishing_type or 'olejow' in finishing_type:
            result = 'olejowana'
        
            # Dodaj kolor oleju jeśli istnieje
            if finishing_details.finishing_color and finishing_details.finishing_color != 'Brak':
                result += f' {finishing_details.finishing_color}'
            
        elif 'wosk' in finishing_type:
            result = 'woskowana'
        
        elif 'bejc' in finishing_type:
            result = 'bejcowana'
        
            # Dla bejcy kolor jest zwykle ważny
            if finishing_details.finishing_color and finishing_details.finishing_color != 'Brak':
                result += f' {finishing_details.finishing_color}'
            
        else:
            # Fallback - spróbuj przekształcić automatycznie
            result = finishing_type.replace('owanie', 'owana').replace('enie', 'ona')
        
            # Dodaj kolor jeśli istnieje
            if finishing_details.finishing_color and finishing_details.finishing_color != 'Brak':
                result += f' {finishing_details.finishing_color}'
    
        self.logger.debug("Przetłumaczono wykończenie na przymiotnik",
                         finishing_type=finishing_details.finishing_type,
                         finishing_color=finishing_details.finishing_color,
                         result=result)
    
        return result
    
    def _build_user_comments(self, quote):
        """Buduje komentarz użytkownika z numerem wyceny i notatką"""
        # Zawsze dodaj numer wyceny
        comments = f"Wycena {quote.quote_number}"

        # Dodaj notatkę jeśli istnieje
        if quote.notes and quote.notes.strip():
            comments += f" - {quote.notes}"

        # Ogranicz do 200 znaków (limit Baselinker)
        if len(comments) > 200:
            comments = comments[:197] + "..."
            self.logger.warning("Komentarz został skrócony do 200 znaków",
                              quote_number=quote.quote_number,
                              original_length=len(f"Wycena {quote.quote_number}. {quote.notes}"))

        self.logger.debug("Zbudowano komentarz użytkownika",
                         quote_number=quote.quote_number,
                         has_notes=bool(quote.notes and quote.notes.strip()),
                         comment_length=len(comments))

        return comments
    
    def _calculate_item_weight(self, item) -> float:
        """Oblicza wagę produktu na podstawie objętości (przyjmując gęstość drewna 800kg/m³)"""
        if item.volume_m3:
            weight = round(item.volume_m3 * 800, 2)
            self.logger.debug("Obliczono wagę produktu",
                            item_id=getattr(item, 'id', None),
                            volume_m3=item.volume_m3,
                            weight_kg=weight)
            return weight
        return 0.0

# ============================================
# sprawdzaj dokumenty sprzedaży - faktura, korekta, e-paragon - modal szczegółów wyceny
# ============================================

    def get_sales_documents(self, order_id: int, quote_id: int) -> Dict:
        """
        Pobiera wszystkie dokumenty sprzedaży dla zamówienia (faktura, korekta, e-paragon)
    
        Args:
            order_id: ID zamówienia w Baselinker
            quote_id: ID wyceny w CRM
        
        Returns:
            Dict z danymi dokumentów lub błędem
        """
        self.logger.info("Pobieranie dokumentów sprzedaży",
                        order_id=order_id,
                        quote_id=quote_id)
    
        try:
            from modules.calculator.models import Quote
        
            # Pobierz wycenę z bazy
            quote = Quote.query.get(quote_id)
            if not quote:
                self.logger.error("Wycena nie znaleziona", quote_id=quote_id)
                return {
                    'status': 'error',
                    'error': 'Wycena nie znaleziona',
                    'code': 'QUOTE_NOT_FOUND'
                }
        
            result = {
                'status': 'success',
                'order_page': None,
                'invoice': {'exists': False},
                'correction': {'exists': False},
                'receipt': {'exists': False}
            }
        
            # ============================================
            # OPTYMALIZACJA: Pobierz zamówienie RAZ z custom_extra_fields
            # ============================================
            self.logger.info("Pobieranie szczegółów zamówienia z custom_extra_fields", 
                            order_id=order_id)
        
            order_response = self._make_request('getOrders', {
                'order_id': order_id,
                'include_custom_extra_fields': True  # ✅ Pobierz wszystko naraz
            })
        
            if order_response.get('status') != 'SUCCESS':
                self.logger.error("Nie udało się pobrać szczegółów zamówienia",
                                order_id=order_id,
                                error=order_response.get('error_message'))
                return {
                    'status': 'error',
                    'error': 'Nie udało się pobrać szczegółów zamówienia',
                    'code': 'ORDER_FETCH_FAILED'
                }
        
            orders = order_response.get('orders', [])
            if not orders:
                self.logger.error("Zamówienie nie znalezione", order_id=order_id)
                return {
                    'status': 'error',
                    'error': 'Zamówienie nie znalezione',
                    'code': 'ORDER_NOT_FOUND'
                }
        
            order_data = orders[0]
        
            self.logger.debug("Pobrano szczegóły zamówienia",
                             order_id=order_id,
                             has_custom_fields=bool(order_data.get('custom_extra_fields')),
                             custom_fields_count=len(order_data.get('custom_extra_fields', {})))
        
            # ============================================
            # STRONA INFORMACYJNA - zapisz od razu
            # ============================================
            order_page = order_data.get('order_page')
            if order_page:
                quote.baselinker_order_page = order_page
                result['order_page'] = order_page
                self.logger.debug("Zapisano order_page", order_page=order_page)
        
            # ============================================
            # FAKTURA - sprawdź cache, pobierz jeśli brak
            # ============================================
            if quote.has_invoice():
                # Faktura w cache - użyj bez wywoływania API
                self.logger.info("Faktura w cache", 
                               invoice_number=quote.baselinker_invoice_number)
                result['invoice'] = {
                    'exists': True,
                    'invoice_id': quote.baselinker_invoice_id,
                    'number': quote.baselinker_invoice_number,
                    'file_base64': quote.baselinker_invoice_file
                }
            else:
                # Pobierz fakturę z API
                invoice_data = self._fetch_invoice(order_id, quote)
                result['invoice'] = invoice_data
        
            # ============================================
            # KOREKTA - zawsze sprawdzaj (może się pojawić)
            # ============================================
            correction_data = self._fetch_correction(order_id, quote)
            result['correction'] = correction_data
        
            # ============================================
            # E-PARAGON - przekaż order_data zamiast wywoływać API ponownie
            # ============================================
            receipt_data = self._fetch_receipt_from_order_data(order_data, quote)
            result['receipt'] = receipt_data
        
            # Zapisz zmiany w bazie
            db.session.commit()
        
            self.logger.info("Dokumenty sprzedaży pobrane pomyślnie",
                           order_id=order_id,
                           has_invoice=result['invoice']['exists'],
                           has_correction=result['correction']['exists'],
                           has_receipt=result['receipt']['exists'])
        
            return result
        
        except Exception as e:
            self.logger.error("Błąd podczas pobierania dokumentów sprzedaży",
                            order_id=order_id,
                            quote_id=quote_id,
                            error=str(e),
                            error_type=type(e).__name__)
            import traceback
            self.logger.debug("Stack trace błędu", traceback=traceback.format_exc())
            return {
                'status': 'error',
                'error': str(e),
                'code': 'GENERAL_ERROR'
            }
    
    def _fetch_invoice(self, order_id: int, quote) -> Dict:
        """Pobiera fakturę z API Baselinker i zapisuje w cache"""
        self.logger.info("Pobieranie faktury z API", order_id=order_id)
        
        try:
            # Wywołaj API getInvoices
            response = self._make_request('getInvoices', {'order_id': order_id})
            
            if response.get('status') != 'SUCCESS':
                self.logger.warning("API getInvoices zwróciło błąd",
                                  order_id=order_id,
                                  error=response.get('error_message'))
                return {'exists': False}
            
            invoices = response.get('invoices', [])

            # DEBUG: Wypisz wszystkie faktury
            self.logger.info(f"DEBUG: Znalezione faktury: {invoices}")
            print(f"[DEBUG INVOICES] {invoices}", file=sys.stderr)
            
            # Znajdź fakturę (type="normal" lub type="vat")
            invoice = next((inv for inv in invoices 
                        if inv.get('type') in ['INVOICE', 'NORMAL', 'VAT', 'normal', 'vat', 'invoice']), None)
            
            if not invoice:
                self.logger.info("Faktura nie została jeszcze wystawiona", order_id=order_id)
                return {'exists': False}
            
            invoice_id = invoice.get('invoice_id')
            invoice_number = invoice.get('invoice_number') or invoice.get('number')
            
            # Pobierz plik PDF faktury
            file_response = self._make_request('getInvoiceFile', {
                'invoice_id': invoice_id
            })

            # DEBUG: Sprawdź całą odpowiedź
            self.logger.info(f"DEBUG: Klucze w file_response: {file_response.keys()}")
            self.logger.info(f"DEBUG: Cała odpowiedź getInvoiceFile: {file_response}")
            
            if file_response.get('status') != 'SUCCESS':
                self.logger.error("Błąd pobierania pliku faktury",
                                invoice_id=invoice_id,
                                error=file_response.get('error_message'))
                return {'exists': False}
            
            invoice_file = file_response.get('invoice')

            self.logger.info(f"DEBUG: Typ invoice_file: {type(invoice_file)}")
            self.logger.info(f"DEBUG: Czy invoice_file jest None? {invoice_file is None}")
            if invoice_file:
                self.logger.info(f"DEBUG: Długość: {len(invoice_file)}")
                self.logger.info(f"DEBUG: Pierwsze 50 znaków: {invoice_file[:50]}")
            
            # Zapisz fakturę w cache (baza danych)
            from datetime import datetime
            quote.baselinker_invoice_id = invoice_id
            quote.baselinker_invoice_number = invoice_number
            quote.baselinker_invoice_file = invoice_file
            quote.baselinker_invoice_fetched_at = datetime.utcnow()
            
            self.logger.info("Faktura zapisana w cache",
                           invoice_id=invoice_id,
                           invoice_number=invoice_number)
            
            return {
                'exists': True,
                'invoice_id': invoice_id,
                'number': invoice_number,
                'file_base64': invoice_file
            }
            
        except Exception as e:
            self.logger.error("Wyjątek podczas pobierania faktury",
                            order_id=order_id,
                            error=str(e))
            return {'exists': False, 'error': str(e)}
    
    def _fetch_correction(self, order_id: int, quote) -> Dict:
        """Pobiera korektę faktury z API Baselinker"""
        self.logger.info("Sprawdzanie korekty faktury", order_id=order_id)
        
        try:
            # Wywołaj API getInvoices
            response = self._make_request('getInvoices', {'order_id': order_id})
            
            if response.get('status') != 'SUCCESS':
                from datetime import datetime
                quote.baselinker_correction_last_check = datetime.utcnow()
                return {'exists': False}
            
            invoices = response.get('invoices', [])
            
            # Znajdź korektę (type="correction" lub type="corrective")
            correction = next((inv for inv in invoices 
                             if inv.get('type') in ['CORRECTION', 'CORRECTIVE', 'correction', 'corrective']), None)
            
            if not correction:
                self.logger.info("Korekta nie została wystawiona", order_id=order_id)
                from datetime import datetime
                quote.baselinker_correction_last_check = datetime.utcnow()
                return {'exists': False}
            
            correction_id = correction.get('invoice_id')
            correction_number = correction.get('invoice_number') or correction.get('number')
            
            # Jeśli korekta już w cache - zwróć z cache
            if quote.baselinker_correction_invoice_number == correction_number:
                self.logger.info("Korekta w cache", correction_number=correction_number)
                from datetime import datetime
                quote.baselinker_correction_last_check = datetime.utcnow()
                return {
                    'exists': True,
                    'invoice_id': correction_id,
                    'number': correction_number,
                    'file_base64': quote.baselinker_correction_invoice_file
                }
            
            # Pobierz plik PDF korekty
            file_response = self._make_request('getInvoiceFile', {
                'invoice_id': correction_id
            })
            
            if file_response.get('status') != 'SUCCESS':
                from datetime import datetime
                quote.baselinker_correction_last_check = datetime.utcnow()
                return {'exists': False}
            
            correction_file = file_response.get('invoice')
            
            # Zapisz korektę w cache
            from datetime import datetime
            quote.baselinker_correction_invoice_id = correction_id
            quote.baselinker_correction_invoice_number = correction_number
            quote.baselinker_correction_invoice_file = correction_file
            quote.baselinker_correction_last_check = datetime.utcnow()
            
            self.logger.info("Korekta zapisana w cache",
                           correction_id=correction_id,
                           correction_number=correction_number)
            
            return {
                'exists': True,
                'invoice_id': correction_id,
                'number': correction_number,
                'file_base64': correction_file
            }
            
        except Exception as e:
            self.logger.error("Wyjątek podczas pobierania korekty",
                            order_id=order_id,
                            error=str(e))
            from datetime import datetime
            quote.baselinker_correction_last_check = datetime.utcnow()
            return {'exists': False, 'error': str(e)}
    
    def _fetch_receipt_from_order_data(self, order_data: Dict, quote) -> Dict:
        """
        Pobiera URL e-paragonu z już pobranych danych zamówienia
    
        Args:
            order_data: Dane zamówienia z getOrders (z custom_extra_fields)
            quote: Obiekt Quote z bazy danych
        
        Returns:
            Dict z informacją o e-paragonie
        """
        self.logger.info("Sprawdzanie e-paragonu w danych zamówienia")
    
        try:
            from datetime import datetime
        
            # Pobierz custom_extra_fields z już pobranych danych
            custom_fields = order_data.get('custom_extra_fields', {})
        
            self.logger.debug("Custom extra fields",
                             fields_count=len(custom_fields),
                             field_ids=list(custom_fields.keys()) if custom_fields else [])
        
            # Pobierz wartość pola 78400 (e-paragon)
            receipt_url = custom_fields.get('78400', '').strip()
        
            self.logger.info("Wartość pola 78400 (e-paragon)",
                            receipt_url=receipt_url if receipt_url else 'EMPTY')
        
            if not receipt_url:
                self.logger.info("E-paragon nie został wystawiony (pole 78400 puste)")
                quote.baselinker_receipt_last_check = datetime.utcnow()
                return {'exists': False}
        
            # Zapisz URL e-paragonu w bazie
            quote.baselinker_receipt_url = receipt_url
            quote.baselinker_receipt_last_check = datetime.utcnow()
        
            self.logger.info("E-paragon znaleziony w polu 78400", 
                            receipt_url=receipt_url)
        
            return {
                'exists': True,
                'url': receipt_url
            }
        
        except Exception as e:
            self.logger.error("Wyjątek podczas przetwarzania e-paragonu",
                            error=str(e))
            import traceback
            self.logger.debug("Stack trace", traceback=traceback.format_exc())
        
            from datetime import datetime
            quote.baselinker_receipt_last_check = datetime.utcnow()
            return {'exists': False, 'error': str(e)}