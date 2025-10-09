# modules/production/services/sync_service.py
"""
Serwis synchronizacji z Baselinker dla modułu Production - ENHANCED VERSION 2.0
Autor: Konrad Kmiecik  
Wersja: 2.0
Data: 2025-01-22
"""

import json
import math
import requests
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from extensions import db
from modules.logging import get_structured_logger
import pytz

logger = get_structured_logger('production.sync.v2')

def get_local_now():
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)

class SyncError(Exception):
    pass

class BaselinkerSyncService:
    
    def __init__(self):
        self.source_statuses = [155824]
        self.target_production_status = 138619
        self.target_completed_status = 138623
        self.api_endpoint = "https://api.baselinker.com/connector.php"
        self.api_key = None
        self.api_timeout = 30
        self.max_items_per_batch = 1000
        self.max_retries = 3
        self.retry_delay = 5
        self._status_cache = None
        self._status_cache_time = None
        self._status_cache_ttl = 43200
        
        self._load_config()
        
        logger.info("Inicjalizacja BaselinkerSyncService v2.0", extra={
            'source_statuses': self.source_statuses,
            'target_production_status': self.target_production_status,
            'target_completed_status': self.target_completed_status
        })

    def _load_config(self):
        try:
            from flask import current_app
        
            api_config = current_app.config.get('API_BASELINKER', {})
            self.api_key = api_config.get('api_key')
            if api_config.get('endpoint'):
                self.api_endpoint = api_config['endpoint']
        
            logger.info("Załadowano konfigurację API Baselinker", extra={
                'api_key_present': bool(self.api_key),
                'endpoint': self.api_endpoint
            })
        
            try:
                from .config_service import get_config
                self.max_items_per_batch = get_config('MAX_SYNC_ITEMS_PER_BATCH', 1000)
                self.target_completed_status = get_config('BASELINKER_TARGET_STATUS_COMPLETED', 138623)
            except ImportError:
                logger.warning("Nie można załadować konfiguracji z ProductionConfigService")
        
            if not self.api_key:
                logger.error("Brak klucza API Baselinker w konfiguracji")
            
        except Exception as e:
            logger.error("Błąd ładowania konfiguracji", extra={'error': str(e)})
            
            logger.warning("Próba fallback z bezpośrednim czytaniem pliku")
            try:
                import os
                config_path = os.path.join('app', 'config', 'core.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        api_config = config.get('API_BASELINKER', {})
                        self.api_key = api_config.get('api_key')
                        if api_config.get('endpoint'):
                            self.api_endpoint = api_config['endpoint']
                    logger.info("Fallback: Załadowano konfigurację z pliku")
                else:
                    logger.error("Fallback: Plik konfiguracji nie istnieje: %s", config_path)
            except Exception as fallback_error:
                logger.error("Fallback również się nie powiódł", extra={'error': str(fallback_error)})

    def get_baselinker_statuses_from_db(self, force_refresh: bool = False) -> Dict[int, Dict[str, Any]]:
        """
        Pobiera statusy z tabeli baselinker_config z cache
    
        Returns:
            Dict[int, Dict[str, Any]]: {status_id: {'name': str, 'is_default': bool, 'is_active': bool}}
        """
        now = datetime.now()
    
        if not force_refresh and self._status_cache is not None:
            if self._status_cache_time and (now - self._status_cache_time).total_seconds() < self._status_cache_ttl:
                logger.debug("Użyto cache statusów", extra={'cache_age_seconds': (now - self._status_cache_time).total_seconds()})
                return self._status_cache
    
        try:
            from modules.baselinker.models import BaselinkerConfig
        
            status_records = BaselinkerConfig.query.filter_by(
                config_type='order_status',
                is_active=True
            ).all()
        
            statuses = {}
            for record in status_records:
                statuses[record.baselinker_id] = {
                    'name': record.name,
                    'is_default': record.is_default,
                    'is_active': record.is_active
                }
        
            self._status_cache = statuses
            self._status_cache_time = now
        
            logger.info("Załadowano statusy z baselinker_config", extra={
                'statuses_count': len(statuses),
                'status_ids': list(statuses.keys())
            })
        
            return statuses
        
        except Exception as e:
            logger.error("Błąd pobierania statusów z bazy", extra={'error': str(e)})
        
            if self._status_cache is not None:
                logger.warning("Użyto przestarzałego cache statusów")
                return self._status_cache
        
            return {}

    def determine_production_status_by_finish(self, products: List['ProductionItem']) -> int:
        """
        Określa status Baselinker na podstawie wykończenia produktów
        Pobiera ID statusów z bazy danych (tabela baselinker_config)
        """
        FINISH_PATTERNS = {
            'oiling': ['olej'],
            'staining': ['bejc'],
            'varnishing': ['lakie']
        }
    
        statuses_from_db = self.get_baselinker_statuses_from_db()
    
        status_mapping = {}
        for status_id, status_info in statuses_from_db.items():
            name_lower = status_info['name'].lower()
            if 'olejowanie' in name_lower:
                status_mapping['oiling'] = status_id
            elif 'bejcowanie' in name_lower:
                status_mapping['staining'] = status_id
            elif 'lakierowanie' in name_lower:
                status_mapping['varnishing'] = status_id
            elif 'surowe' in name_lower:
                status_mapping['raw'] = status_id
    
        if not status_mapping:
            logger.warning("Brak statusów z bazy, używam hardcoded fallback")
            status_mapping = {
                'oiling': 148832,
                'staining': 148831,
                'varnishing': 148830,
                'raw': 138619
            }
    
        DEFAULT_STATUS = status_mapping.get('raw', 138619)
    
        finishes = set()
    
        for product in products:
            finish = product.parsed_finish_state
        
            if not finish or not finish.strip():
                finishes.add('raw')
                continue
        
            finish_lower = finish.lower()
        
            matched = False
            for finish_type, patterns in FINISH_PATTERNS.items():
                if any(pattern in finish_lower for pattern in patterns):
                    status_id = status_mapping.get(finish_type)
                    if status_id:
                        finishes.add(status_id)
                        matched = True
                    break
        
            if not matched:
                finishes.add('raw')
    
        if len(finishes) == 1:
            finish_value = list(finishes)[0]
            if isinstance(finish_value, int):
                logger.info("Określono status wykończenia", extra={
                    'status_id': finish_value,
                    'products_count': len(products)
                })
                return finish_value
            else:
                return DEFAULT_STATUS
        else:
            logger.info("Mieszanka wykończeń - fallback na surowe", extra={
                'finishes': list(finishes),
                'fallback_status': DEFAULT_STATUS
            })
            return DEFAULT_STATUS

    def sync_paid_orders_only(self) -> Dict[str, Any]:
        sync_started_at = get_local_now()
        sync_log = self._create_sync_log('cron_auto', sync_started_at)
        
        try:
            logger.info("CRON: Rozpoczęcie automatycznej synchronizacji opłaconych zamówień")
            
            orders_data = self._fetch_paid_orders_for_cron()
            logger.info(f"CRON: Pobrano {len(orders_data)} zamówień ze statusu 'Nowe - opłacone'")
            
            if not orders_data:
                result = {
                    'success': True,
                    'orders_processed': 0,
                    'message': 'Brak nowych opłaconych zamówień do synchronizacji',
                    'sync_type': 'cron_auto',
                    'duration_seconds': 0
                }
                
                if sync_log:
                    sync_log.orders_processed = 0
                    sync_log.complete_sync(success=True)
                    db.session.commit()
                    
                return result
            
            processing_result = self.process_orders_with_priority_logic(
                orders_data, 
                sync_type='cron',
                auto_status_change=True
            )

            orders_processed_list = processing_result.get('orders_processed_list', [])
            
            if sync_log:
                sync_log.orders_processed = processing_result['orders_processed']
                sync_log.products_created = processing_result['products_created']
                sync_log.products_updated = processing_result['products_updated']
                sync_log.products_skipped = processing_result['products_skipped']
                sync_log.error_count = processing_result['errors_count']
                sync_log.priority_recalc_triggered = processing_result.get('priority_recalc_triggered', False)
                sync_log.priority_recalc_duration_seconds = processing_result.get('priority_recalc_duration', 0)
                sync_log.manual_overrides_preserved = processing_result.get('manual_overrides_preserved', 0)
                
                if processing_result.get('error_details'):
                    sync_log.error_details_json = json.dumps(processing_result['error_details'])
                
                sync_log.complete_sync(success=processing_result['success'])
                db.session.commit()
            
            duration = (get_local_now() - sync_started_at).total_seconds()
            
            result = {
                'success': processing_result['success'],
                'sync_type': 'cron_auto',
                'duration_seconds': round(duration, 2),
                'orders_processed': processing_result['orders_processed'],
                'orders_processed_list': orders_processed_list,
                'products_created': processing_result['products_created'],
                'products_updated': processing_result['products_updated'],
                'products_skipped': processing_result['products_skipped'],
                'errors_count': processing_result['errors_count'],
                'status_changes': {
                    'orders_moved_to_production': processing_result.get('status_changes_count', 0),
                    'status_change_errors': processing_result.get('status_change_errors', 0)
                },
                'priority_recalculation': {
                    'triggered': processing_result.get('priority_recalc_triggered', False),
                    'products_updated': processing_result.get('priority_products_updated', 0),
                    'manual_overrides_preserved': processing_result.get('manual_overrides_preserved', 0),
                    'duration_seconds': processing_result.get('priority_recalc_duration', 0)
                }
            }
            
            logger.info("CRON: Zakończono automatyczną synchronizację", extra=result)
            return result
            
        except Exception as e:
            logger.error("CRON: Błąd automatycznej synchronizacji", extra={'error': str(e)})
            
            if sync_log:
                sync_log.sync_status = 'failed'
                sync_log.error_count = (sync_log.error_count or 0) + 1
                sync_log.error_details_json = json.dumps({'cron_error': str(e)})
                sync_log.complete_sync(success=False, error_message=str(e))
                db.session.commit()
            
            duration = (get_local_now() - sync_started_at).total_seconds()
            
            return {
                'success': False,
                'error': str(e),
                'sync_type': 'cron_auto',
                'duration_seconds': round(duration, 2),
                'orders_processed': 0,
                'products_created': 0
            }

    def process_orders_with_priority_logic(self, orders_data: List[Dict], sync_type: str = 'manual', auto_status_change: bool = True) -> Dict[str, Any]:
        logger.info("ENHANCED: Rozpoczęcie przetwarzania zamówień", extra={
            'orders_count': len(orders_data),
            'sync_type': sync_type,
            'auto_status_change': auto_status_change
        })

        orders_processed_list = []

        processing_stats = {
            'orders_processed': 0,
            'products_created': 0,
            'products_updated': 0,
            'products_skipped': 0,
            'errors_count': 0,
            'status_changes_count': 0,
            'status_change_errors': 0
        }

        error_details = []
        orders_for_status_change = []

        for order_data in orders_data:
            try:
                order_id = None
                if isinstance(order_data, dict):
                    order_id = order_data.get('order_id') or order_data.get('id')
        
                if not order_id:
                    logger.warning("Pominięto zamówienie bez order_id")
                    processing_stats['errors_count'] += 1
                    continue
        
                logger.debug("Przetwarzanie zamówienia", extra={'order_id': order_id})
        
                payment_date = None
                try:
                    payment_date = self.extract_payment_date_from_order(order_data)
                except Exception as e:
                    logger.warning("Nie udało się wyciągnąć payment_date", extra={
                        'order_id': order_id,
                        'error': str(e)
                    })
        
                validation_result = self.validate_order_products_completeness(order_data)
                is_valid, validation_errors = validation_result
        
                if not is_valid:
                    logger.warning("Zamówienie nie przeszło walidacji", extra={
                        'order_id': order_id,
                        'validation_errors': validation_errors
                    })
    
                    try:
                        # ✅ DODAJ TEN FRAGMENT
                        existing_comment = order_data.get('admin_comments', '')
                        self.add_validation_comment_to_baselinker(order_id, validation_errors, existing_comment)
                        # ✅ KONIEC FRAGMENTU
                    except Exception as comment_error:
                        logger.error("Błąd dodawania komentarza walidacji", extra={
                            'order_id': order_id,
                            'error': str(comment_error)
                        })
                
                    processing_stats['products_skipped'] += len(order_data.get('products', []))
                    processing_stats['errors_count'] += 1
                    error_details.append({
                        'order_id': order_id,
                        'error': 'Validation failed',
                        'details': validation_errors
                    })
                    continue
        
                products = order_data.get('products', [])
                if not products:
                    logger.warning("Zamówienie bez produktów", extra={'order_id': order_id})
                    continue

                total_pieces = sum(int(product.get('quantity', 1)) for product in products)

                try:
                    from ..services.id_generator import ProductIDGenerator
                    id_generation_result = ProductIDGenerator.generate_product_id_for_order(
                        baselinker_order_id=order_id,
                        total_products_count=total_pieces
                    )
    
                    logger.debug("Wygenerowano ID dla zamówienia", extra={
                        'order_id': order_id,
                        'total_pieces': total_pieces,
                        'generated_ids_count': len(id_generation_result['product_ids'])
                    })
    
                except Exception as id_error:
                    logger.error("Błąd generowania ID dla zamówienia", extra={
                        'order_id': order_id,
                        'total_pieces': total_pieces,
                        'error': str(id_error)
                    })
                    processing_stats['errors_count'] += 1
                    continue

                order_products_created = 0
                order_errors = 0
                current_sequence = 1

                for product_data in products:
                    try:
                        quantity = int(product_data.get('quantity', 1))
        
                        logger.debug("Przetwarzanie produktu", extra={
                            'order_id': order_id,
                            'product_name': product_data.get('name', 'unknown')[:50],
                            'quantity': quantity,
                            'starting_sequence': current_sequence
                        })
        
                        for qty_index in range(quantity):
                            try:
                                production_item = self._create_product_from_order_data(
                                    order_data=order_data, 
                                    product_data=product_data, 
                                    payment_date=payment_date,
                                    sequence_number=current_sequence,
                                    id_generation_result=id_generation_result
                                )
                
                                if production_item:
                                    db.session.add(production_item)
                                    order_products_created += 1
                                    processing_stats['products_created'] += 1
                    
                                    logger.debug("Sztuka utworzona", extra={
                                        'order_id': order_id,
                                        'product_id': production_item.short_product_id,
                                        'sequence': current_sequence
                                    })
                                else:
                                    order_errors += 1
                                    processing_stats['products_skipped'] += 1
                
                                current_sequence += 1
                
                            except Exception as piece_error:
                                logger.error("Błąd tworzenia sztuki", extra={
                                    'order_id': order_id,
                                    'sequence': current_sequence,
                                    'error': str(piece_error)
                                })
                
                                order_errors += 1
                                processing_stats['products_skipped'] += 1
                                current_sequence += 1
                
                                error_details.append({
                                    'order_id': order_id,
                                    'product_name': product_data.get('name', 'unknown'),
                                    'sequence': current_sequence - 1,
                                    'error_type': 'piece_creation_failed',
                                    'error_message': str(piece_error)
                                })
                        
                    except Exception as product_error:
                        logger.error("Błąd przetwarzania produktu", extra={
                            'order_id': order_id,
                            'error': str(product_error)
                        })
        
                        quantity = int(product_data.get('quantity', 1))
                        order_errors += quantity
                        processing_stats['products_skipped'] += quantity
                        current_sequence += quantity
            
                if order_products_created > 0:
                    try:
                        db.session.commit()
                        logger.info("Produkty zamówienia zapisane", extra={
                            'order_id': order_id,
                            'products_created': order_products_created
                        })
                    
                        orders_for_status_change.append(order_id)
                        orders_processed_list.append(order_id)
                        processing_stats['orders_processed'] += 1
                    
                    except Exception as db_error:
                        logger.error("Błąd zapisu do bazy", extra={
                            'order_id': order_id,
                            'error': str(db_error)
                        })
                        db.session.rollback()
                        processing_stats['errors_count'] += 1
                        error_details.append({
                            'order_id': order_id,
                            'error': 'Database save failed',
                            'details': str(db_error)
                        })
                else:
                    logger.warning("Brak produktów do zapisania", extra={
                        'order_id': order_id,
                        'errors': order_errors
                    })
                    processing_stats['errors_count'] += 1
        
            except Exception as order_error:
                logger.error("Błąd przetwarzania zamówienia", extra={
                    'order_id': order_id if 'order_id' in locals() else 'unknown',
                    'error': str(order_error)
                })
                processing_stats['errors_count'] += 1
                error_details.append({
                    'order_id': order_id if 'order_id' in locals() else 'unknown',
                    'error': 'Order processing failed',
                    'details': str(order_error)
                })

        if auto_status_change and orders_for_status_change:
            logger.info("Rozpoczęcie zmiany statusu", extra={
                'orders_for_status_change': len(orders_for_status_change)
            })
        
            for order_id in orders_for_status_change:
                try:
                    success = self.change_order_status_in_baselinker(order_id, target_status=None)
                    if success:
                        processing_stats['status_changes_count'] += 1
                    else:
                        processing_stats['status_change_errors'] += 1
                except Exception as status_error:
                    processing_stats['status_change_errors'] += 1
                    logger.error("Exception podczas zmiany statusu", extra={
                        'order_id': order_id,
                        'error': str(status_error)
                    })

        priority_recalc_result = {}
        if processing_stats['products_created'] > 0:
            try:
                logger.info("Rozpoczęcie przeliczania priorytetów")
            
                from ..services.priority_service import get_priority_calculator
                priority_calculator = get_priority_calculator()
                priority_recalc_result = priority_calculator.recalculate_all_priorities()
            
                logger.info("Zakończono przeliczanie priorytetów", extra={
                    'products_updated': priority_recalc_result.get('products_updated', 0),
                    'manual_overrides_preserved': priority_recalc_result.get('manual_overrides_preserved', 0)
                })
            
            except Exception as priority_error:
                logger.error("Błąd przeliczania priorytetów", extra={'error': str(priority_error)})
                priority_recalc_result = {'error': str(priority_error)}

        final_result = {
            'success': processing_stats['errors_count'] == 0 or processing_stats['products_created'] > 0,
            'orders_processed': processing_stats['orders_processed'],
            'orders_processed_list': orders_processed_list,
            'products_created': processing_stats['products_created'],
            'products_updated': processing_stats['products_updated'],
            'products_skipped': processing_stats['products_skipped'],
            'errors_count': processing_stats['errors_count'],
            'status_changes_count': processing_stats['status_changes_count'],
            'status_change_errors': processing_stats['status_change_errors'],
            'priority_recalc_triggered': bool(priority_recalc_result),
            'priority_recalc_duration': priority_recalc_result.get('calculation_duration', '00:00:00'),
            'manual_overrides_preserved': priority_recalc_result.get('manual_overrides_preserved', 0),
            'error_details': error_details
        }

        logger.info("Zakończono przetwarzanie zamówień", extra=final_result)
        return final_result

    def _create_product_from_order_data(self, order_data: Dict[str, Any], product_data: Dict[str, Any], payment_date: Optional[datetime] = None, sequence_number: int = 1, id_generation_result: Dict[str, Any] = None) -> Optional['ProductionItem']:
        try:
            from ..models import ProductionItem
            from ..services.parser_service import ProductNameParser
        
            if not isinstance(product_data, dict):
                logger.error("product_data nie jest dict")
                return None
        
            if not isinstance(order_data, dict):
                logger.error("order_data nie jest dict")
                return None
        
            original_product_name = product_data.get('name', '').strip()
            if not original_product_name:
                logger.error("Brak nazwy produktu")
                return None
        
            order_id = order_data.get('order_id') or order_data.get('id')
            if not order_id:
                logger.error("Brak order_id")
                return None
        
            try:
                parser = ProductNameParser()
                parsed_data = parser.parse_product_name(original_product_name)
            except Exception as parse_error:
                logger.warning("Błąd parsowania nazwy", extra={
                    'product_name': original_product_name[:50],
                    'error': str(parse_error)
                })
                parsed_data = {}
        
            client_data = self.extract_client_data(order_data)
            deadline_date = self._calculate_deadline_date(order_data)
        
            if id_generation_result and sequence_number <= len(id_generation_result['product_ids']):
                product_id = id_generation_result['product_ids'][sequence_number - 1]
            
                logger.debug("Użyto pre-generated ID", extra={
                    'order_id': order_id,
                    'sequence_number': sequence_number,
                    'product_id': product_id
                })
            else:
                logger.error("Brak pre-generated ID", extra={
                    'sequence_number': sequence_number,
                    'available_ids': len(id_generation_result['product_ids']) if id_generation_result else 0
                })
                return None
        
            product_data_dict = self._prepare_product_data_enhanced(
                order=order_data,
                product=product_data,
                product_id=product_id,
                id_result=id_generation_result,
                parsed_data=parsed_data,
                client_data=client_data,
                deadline_date=deadline_date,
                order_product_id=product_data.get('order_product_id'),
                sequence_number=sequence_number,
                payment_date=payment_date
            )
        
            production_item = ProductionItem(**product_data_dict)
        
            logger.debug("Utworzono ProductionItem", extra={
                'product_id': product_id,
                'sequence_number': sequence_number,
                'order_id': order_id
            })
        
            return production_item
        
        except Exception as e:
            logger.error("Błąd tworzenia produktu", extra={
                'error': str(e),
                'sequence_number': sequence_number
            })
            return None

    def extract_payment_date_from_order(self, order_data: Dict[str, Any]) -> Optional[datetime]:
        try:
            order_id = order_data.get('order_id')
        
            logger.debug("Szukanie payment_date w zamówieniu", extra={'order_id': order_id})
        
            if order_data.get('date_in_status'):
                try:
                    timestamp = int(order_data['date_in_status'])
                    payment_date = datetime.fromtimestamp(timestamp)
                
                    logger.info("Extracted payment_date z date_in_status", extra={
                        'order_id': order_id,
                        'payment_date': payment_date.isoformat()
                    })
                
                    return payment_date
                except (TypeError, ValueError, OSError) as e:
                    logger.warning("Błędny format date_in_status", extra={
                        'order_id': order_id,
                        'error': str(e)
                    })
        
            if order_data.get('date_confirmed'):
                try:
                    timestamp = int(order_data['date_confirmed'])
                    payment_date = datetime.fromtimestamp(timestamp)
                
                    logger.info("Fallback payment_date z date_confirmed", extra={
                        'order_id': order_id,
                        'payment_date': payment_date.isoformat()
                    })
                
                    return payment_date
                except (TypeError, ValueError, OSError) as e:
                    logger.warning("Błędny format date_confirmed", extra={
                        'order_id': order_id,
                        'error': str(e)
                    })
        
            if order_data.get('date_add'):
                try:
                    timestamp = int(order_data['date_add'])
                    payment_date = datetime.fromtimestamp(timestamp)
                
                    logger.warning("Ostatni fallback payment_date z date_add", extra={
                        'order_id': order_id,
                        'payment_date': payment_date.isoformat()
                    })
                
                    return payment_date
                except (TypeError, ValueError, OSError) as e:
                    logger.error("Błędny format date_add", extra={
                        'order_id': order_id,
                        'error': str(e)
                    })
        
            logger.error("Brak prawidłowych dat dla payment_date", extra={'order_id': order_id})
            return None
        
        except Exception as e:
            logger.error("Błąd extraction payment_date", extra={
                'order_id': order_data.get('order_id'),
                'error': str(e)
            })
            return None

    def validate_order_products_completeness(self, order_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        try:
            from ..services.parser_service import get_parser_service
            
            products = order_data.get('products', [])
            if not products:
                return False, ['Zamówienie nie zawiera produktów']
            
            parser = get_parser_service()
            validation_errors = []
            
            for i, product in enumerate(products):
                product_name = product.get('name', '').strip()
                if not product_name:
                    validation_errors.append(f'Produkt {i+1}: Brak nazwy produktu')
                    continue
                
                try:
                    parsed_data = parser.parse_product_name(product_name)
                    
                    missing_fields = []
                    
                    if not parsed_data.get('wood_species'):
                        missing_fields.append('gatunek drewna')
                    if not parsed_data.get('finish_state'): 
                        missing_fields.append('stan wykończenia')
                    if not parsed_data.get('thickness_cm'):
                        missing_fields.append('grubość')
                    if not parsed_data.get('wood_class'):
                        missing_fields.append('klasa drewna')
                    if not parsed_data.get('width_cm'):
                        missing_fields.append('szerokość')
                    if not parsed_data.get('length_cm'):
                        missing_fields.append('długość')
                    
                    if missing_fields:
                        validation_errors.append(
                            f'Produkt {i+1} "{product_name[:30]}": Brakujące dane - {", ".join(missing_fields)}'
                        )
                        
                except Exception as parse_error:
                    validation_errors.append(
                        f'Produkt {i+1} "{product_name[:30]}": Błąd parsowania - {str(parse_error)}'
                    )
            
            is_valid = len(validation_errors) == 0
            
            logger.debug("Walidacja produktów zamówienia", extra={
                'order_id': order_data.get('order_id'),
                'products_count': len(products),
                'is_valid': is_valid,
                'errors_count': len(validation_errors)
            })
            
            return is_valid, validation_errors
            
        except Exception as e:
            logger.error("Błąd walidacji produktów zamówienia", extra={
                'order_id': order_data.get('order_id'),
                'error': str(e)
            })
            return False, [f'Błąd walidacji: {str(e)}']

    def add_validation_comment_to_baselinker(self, order_id: int, errors: List[str], existing_comment: str = "") -> bool:
        """
        Dodaje komentarz walidacji do Baselinker, zachowując istniejący komentarz
    
        Args:
            order_id: ID zamówienia
            errors: Lista błędów walidacji
            existing_comment: Istniejący komentarz z zamówienia (już pobrany)
        """
        if not self.api_key or not errors:
            return False
    
        try:
            # Przygotuj nowy komunikat
            error_summary = '; '.join(errors[:2])
            if len(errors) > 2:
                error_summary += f' (+{len(errors)-2})'
        
            validation_message = f"SYSTEM: Brak danych do produkcji. {error_summary}"
        
            # Połącz z istniejącym komentarzem
            if existing_comment and existing_comment.strip():
                # Sprawdź czy nasz komunikat już nie jest w komentarzu
                if "SYSTEM: Brak danych do produkcji" not in existing_comment:
                    new_comment = f"{existing_comment} | {validation_message}"
                else:
                    logger.info("Komentarz walidacji już istnieje", extra={'order_id': order_id})
                    return True
            else:
                new_comment = validation_message
        
            # Obetnij do 200 znaków
            if len(new_comment) > 200:
                new_comment = new_comment[:197] + "..."
        
            request_data = {
                'token': self.api_key,
                'method': 'setOrderFields',
                'parameters': json.dumps({
                    'order_id': order_id,
                    'admin_comments': new_comment
                })
            }
        
            response_data = self._make_api_request(request_data)
        
            if response_data.get('status') == 'SUCCESS':
                logger.info("Dodano komentarz walidacji do Baselinker", extra={
                    'order_id': order_id,
                    'errors_count': len(errors),
                    'existing_comment_preserved': bool(existing_comment.strip())
                })
                return True
            else:
                logger.error("Błąd dodawania komentarza do Baselinker", extra={
                    'order_id': order_id,
                    'api_error': response_data.get('error_message')
                })
                return False
            
        except Exception as e:
            logger.error("Wyjątek podczas dodawania komentarza", extra={
                'order_id': order_id,
                'error': str(e)
            })
            return False

    def change_order_status_in_baselinker(self, order_id: int, target_status: Optional[int] = None) -> bool:
        """
        Zmienia status zamówienia w Baselinker
        Jeśli target_status=None, automatycznie określa status na podstawie wykończenia
        """
        if target_status is None:
            from ..models import ProductionItem
            
            products = ProductionItem.query.filter_by(
                baselinker_order_id=order_id
            ).all()
            
            if not products:
                logger.error("Nie znaleziono produktów dla zamówienia", extra={'order_id': order_id})
                return False
            
            target_status = self.determine_production_status_by_finish(products)
            
            logger.info("Automatycznie określono status na podstawie wykończenia", extra={
                'order_id': order_id,
                'target_status': target_status
            })
        
        if not self.api_key:
            logger.error("Brak klucza API dla zmiany statusu")
            return False
        
        try:
            request_data = {
                'token': self.api_key,
                'method': 'setOrderStatus',
                'parameters': json.dumps({
                    'order_id': order_id,
                    'status_id': target_status
                })
            }
            
            response_data = self._make_api_request(request_data)
            
            if response_data.get('status') == 'SUCCESS':
                logger.info("Zmieniono status zamówienia w Baselinker", extra={
                    'order_id': order_id,
                    'new_status': target_status
                })
                return True
            else:
                error_msg = response_data.get('error_message', 'Unknown error')
                logger.error("Błąd zmiany statusu w Baselinker", extra={
                    'order_id': order_id,
                    'target_status': target_status,
                    'error': error_msg
                })
                return False
                
        except Exception as e:
            logger.error("Wyjątek podczas zmiany statusu", extra={
                'order_id': order_id,
                'error': str(e)
            })
            return False

    def _fetch_paid_orders_for_cron(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            raise SyncError("Brak klucza API Baselinker")
        
        try:
            date_from_timestamp = int((datetime.now() - timedelta(days=14)).timestamp())
            
            logger.info("CRON: Pobieranie opłaconych zamówień", extra={
                'status_id': 155824,
                'days_back': 7
            })
            
            request_data = {
                'token': self.api_key,
                'method': 'getOrders',
                'parameters': json.dumps({
                    'status_id': 155824,
                    'get_unconfirmed_orders': True,
                    'date_confirmed_from': date_from_timestamp,
                    'date_limit': 100
                })
            }
            
            response_data = self._make_api_request(request_data)
            
            if response_data.get('status') == 'SUCCESS':
                orders = response_data.get('orders', [])
                
                logger.info("CRON: Pobrano opłacone zamówienia", extra={
                    'orders_count': len(orders)
                })
                
                return orders
            else:
                error_msg = response_data.get('error_message', 'Unknown error')
                raise SyncError(f'Baselinker API error: {error_msg}')
                
        except Exception as e:
            logger.error("CRON: Błąd pobierania zamówień", extra={'error': str(e)})
            raise SyncError(f'Błąd pobierania zamówień CRON: {str(e)}')

    def _prepare_product_data_enhanced(self, order: Dict[str, Any], product: Dict[str, Any], 
                             product_id: str, id_result: Dict[str, Any], 
                             parsed_data: Dict[str, Any], client_data: Dict[str, str],
                             deadline_date: date, order_product_id: Any,
                             sequence_number: int, payment_date: Optional[datetime]) -> Dict[str, Any]:
    
        product_data = {
            'short_product_id': product_id,
            'internal_order_number': id_result['internal_order_number'],
            'product_sequence_in_order': sequence_number,
            'baselinker_order_id': order['order_id'],
            'baselinker_product_id': str(order_product_id) if order_product_id else None,
            'original_product_name': product.get('name', ''),
            'baselinker_status_id': order.get('order_status_id'),
            'payment_date': payment_date,
            'client_name': client_data.get('client_name', ''),
            'client_email': client_data.get('client_email', ''),
            'client_phone': client_data.get('client_phone', ''),
            'delivery_address': client_data.get('delivery_address', ''),
            'deadline_date': deadline_date,
            'current_status': 'czeka_na_wyciecie',
            'sync_source': 'baselinker_auto'
        }
    
        if deadline_date:
            today = date.today()
            days_until = (deadline_date - today).days
            product_data['days_until_deadline'] = days_until
    
        if parsed_data:
            volume_m3 = parsed_data.get('volume_m3')
            if volume_m3 is None and all(parsed_data.get(key) for key in ['length_cm', 'width_cm', 'thickness_cm']):
                try:
                    length = float(parsed_data['length_cm'])
                    width = float(parsed_data['width_cm'])
                    thickness = float(parsed_data['thickness_cm'])
                    volume_m3 = (length * width * thickness) / 1_000_000
                except (TypeError, ValueError) as e:
                    logger.warning("Błąd obliczania volume_m3", extra={'error': str(e)})
                    volume_m3 = None
        
            product_data.update({
                'parsed_wood_species': parsed_data.get('wood_species'),
                'parsed_technology': parsed_data.get('technology'),
                'parsed_wood_class': parsed_data.get('wood_class'),
                'parsed_length_cm': parsed_data.get('length_cm'),
                'parsed_width_cm': parsed_data.get('width_cm'),
                'parsed_thickness_cm': parsed_data.get('thickness_cm'),
                'parsed_finish_state': parsed_data.get('finish_state'),
                'volume_m3': volume_m3
            })
    
        try:
            price_brutto = float(product.get('price_brutto', 0))
            tax_rate = float(product.get('tax_rate', 23))
    
            custom_fields = order.get('custom_extra_fields', {}) or {}
            price_type = custom_fields.get('106169', '').strip().lower() if custom_fields else ''
    
            if price_type == 'netto':
                unit_price_net = price_brutto
            else:
                unit_price_net = price_brutto / (1 + tax_rate/100)
    
            total_value_net = unit_price_net
    
            product_data.update({
                'unit_price_net': round(unit_price_net, 2),
                'total_value_net': round(total_value_net, 2)
            })
    
        except (ValueError, TypeError) as e:
            logger.error("Błąd konwersji cen", extra={
                'order_id': order['order_id'],
                'error': str(e)
            })
            product_data.update({
                'unit_price_net': 0.0,
                'total_value_net': 0.0
            })
    
        return product_data

    def manual_sync_with_filtering(self, params: Dict[str, Any]) -> Dict[str, Any]:
        sync_started_at = get_local_now()
        sync_log = self._create_sync_log('manual_trigger', sync_started_at)

        stats = {
            'pages_processed': 0,
            'orders_found': 0,
            'orders_matched_status': 0,
            'orders_processed': 0,
            'orders_skipped_existing': 0,
            'products_created': 0,
            'products_updated': 0,
            'products_skipped': 0,
            'errors_count': 0
        }
        error_details: List[Dict[str, Any]] = []
        log_entries: List[Dict[str, Any]] = []

        try:
            recalculate_priorities = params.get('recalculate_priorities', True)
            auto_status_change = params.get('auto_status_change', True)
            respect_manual_overrides = params.get('respect_manual_overrides', True)
            
            target_statuses_raw = params.get('target_statuses') or []
            target_statuses = {
                status for status in (
                    self._safe_int(value) for value in target_statuses_raw
                ) if status is not None
            }

            if not target_statuses:
                target_statuses = {155824}
                logger.info("Użyto domyślnego statusu 'Nowe - opłacone' (155824)")

            try:
                period_days = int(params.get('period_days', 25))
            except (TypeError, ValueError):
                period_days = 25
            period_days = max(1, min(period_days, 90))

            try:
                limit_per_page = int(params.get('limit_per_page', 100))
            except (TypeError, ValueError):
                limit_per_page = 100
            limit_per_page = max(10, min(limit_per_page, 200))

            force_update = bool(params.get('force_update'))
            skip_validation = bool(params.get('skip_validation'))
            dry_run = bool(params.get('dry_run'))
            debug_mode = bool(params.get('debug_mode'))

            excluded_keywords = {
                str(keyword).lower().strip()
                for keyword in params.get('excluded_keywords', [])
                if isinstance(keyword, str) and keyword.strip()
            }

            if sync_log:
                sync_log.processed_status_ids = ','.join(map(str, sorted(target_statuses)))

            def add_log(message: str, level: str = 'info', **context: Any) -> None:
                timestamp = get_local_now().isoformat()
                entry: Dict[str, Any] = {
                    'timestamp': timestamp,
                    'level': level,
                    'message': message
                }
                if context:
                    entry['context'] = context
                log_entries.append(entry)

                if level == 'error':
                    logger.error(message, extra={'context': 'manual_sync_enhanced', **{f'ctx_{k}': v for k, v in context.items()}})
                elif level == 'warning':
                    logger.warning(message, extra={'context': 'manual_sync_enhanced', **{f'ctx_{k}': v for k, v in context.items()}})
                elif level == 'debug':
                    if debug_mode:
                        logger.debug(message, extra={'context': 'manual_sync_enhanced', **{f'ctx_{k}': v for k, v in context.items()}})
                else:
                    logger.info(message, extra={'context': 'manual_sync_enhanced', **{f'ctx_{k}': v for k, v in context.items()}})

            add_log('Rozpoczynanie ręcznej synchronizacji v2.0', 'info')
            add_log(
                'Parametry synchronizacji',
                'info',
                period_days=period_days,
                limit_per_page=limit_per_page,
                force_update=force_update,
                skip_validation=skip_validation,
                dry_run=dry_run,
                debug_mode=debug_mode,
                target_statuses=sorted(target_statuses),
                excluded_keywords=sorted(excluded_keywords),
                recalculate_priorities=recalculate_priorities,
                auto_status_change=auto_status_change,
                respect_manual_overrides=respect_manual_overrides
            )

            date_to = get_local_now()
            date_from = date_to - timedelta(days=period_days)
            add_log(f'Zakres synchronizacji: {date_from.date()} → {date_to.date()}', 'info')

            from modules.reports.service import get_reports_service

            reports_service = get_reports_service()
            if not reports_service:
                raise SyncError('Nie można zainicjować serwisu raportów Baselinker.')

            fetch_result = reports_service.fetch_orders_from_date_range(
                date_from=date_from,
                date_to=date_to,
                get_all_statuses=True,
                limit_per_page=limit_per_page
            )

            if not fetch_result.get('success'):
                raise SyncError(fetch_result.get('error', 'Nie udało się pobrać zamówień z Baselinker.'))

            orders = fetch_result.get('orders', []) or []
            stats['orders_found'] = len(orders)
            stats['pages_processed'] = fetch_result.get('pages_processed') or 0
            if stats['pages_processed'] == 0 and stats['orders_found'] > 0:
                stats['pages_processed'] = max(1, math.ceil(stats['orders_found'] / max(limit_per_page, 1)))

            add_log(f'Pobrano {stats["orders_found"]} zamówień (strony API: {stats["pages_processed"]}).', 'info')

            target_statuses_set = set(target_statuses)
            orders_after_status: List[Dict[str, Any]] = []
            for order in orders:
                status_value = self._safe_int(order.get('order_status_id') or order.get('status_id'))
                if status_value is None:
                    continue

                if status_value not in target_statuses_set:
                    continue

                orders_after_status.append(order)

            stats['orders_matched_status'] = len(orders_after_status)
            add_log(f'Do dalszego przetworzenia zakwalifikowano {stats["orders_matched_status"]} zamówień.', 'info')

            reports_parser = None
            try:
                from modules.reports.parser import ProductNameParser as ReportsProductNameParser
                reports_parser = ReportsProductNameParser()
            except Exception as parser_error:
                add_log('Nie udało się zainicjować parsera nazw produktów z modułu reports.', 'warning')

            excluded_product_types = {'suszenie', 'worek opałowy', 'tarcica', 'deska'}

            qualified_orders = []

            for order in orders_after_status:
                order_id_val = self._safe_int(order.get('order_id'))
                if order_id_val is None:
                    stats['errors_count'] += 1
                    error_details.append({'error': 'Brak identyfikatora zamówienia', 'order': order})
                    add_log('Pominięto zamówienie bez identyfikatora.', 'error')
                    continue

                if not force_update and self._order_already_processed(order_id_val):
                    stats['orders_skipped_existing'] += 1
                    add_log(f'Zamówienie {order_id_val} było już zsynchronizowane - pominięto.', 'info')
                    continue

                if force_update and not dry_run:
                    add_log(f'Force update: zamówienie {order_id_val} będzie przetworzone ponownie.', 'info')

                products = order.get('products') or []
                if not products:
                    continue

                filtered_products: List[Dict[str, Any]] = []

                for product in products:
                    product_name_raw = product.get('name', '')
                    product_name = product_name_raw.strip() if isinstance(product_name_raw, str) else ''
                    if not product_name and skip_validation:
                        product_name = 'Produkt bez nazwy'

                    if not product_name and not skip_validation:
                        skipped_qty = self._coerce_quantity(product.get('quantity', 1))
                        stats['products_skipped'] += skipped_qty
                        add_log(f'Pominięto pozycję bez nazwy w zamówieniu {order_id_val}.', 'warning')
                        continue

                    quantity_value = self._coerce_quantity(product.get('quantity', 1))
                    if quantity_value <= 0:
                        if skip_validation:
                            quantity_value = 1
                        else:
                            stats['products_skipped'] += 1
                            continue

                    name_lower = product_name.lower()
                    if excluded_keywords and any(keyword in name_lower for keyword in excluded_keywords):
                        stats['products_skipped'] += quantity_value
                        continue

                    if reports_parser:
                        try:
                            parsed = reports_parser.parse_product_name(product_name)
                            product_type = (parsed.get('product_type') or '').lower()
                        except Exception as parse_error:
                            product_type = ''
                        if product_type and product_type in excluded_product_types:
                            stats['products_skipped'] += quantity_value
                            continue

                    sanitized_product = dict(product)
                    sanitized_product['name'] = product_name if product_name else product.get('name', '')
                    sanitized_product['quantity'] = quantity_value
                    filtered_products.append(sanitized_product)

                if not filtered_products:
                    continue

                order['products'] = filtered_products
                qualified_orders.append(order)

            filter_order_ids = params.get('filter_order_ids', [])
            selected_orders_only = params.get('selected_orders_only', False)
    
            if selected_orders_only and filter_order_ids:
                logger.info("Filtrowanie po wybranych zamówieniach", extra={
                    'filter_order_ids': filter_order_ids,
                    'qualified_orders_before': len(qualified_orders)
                })
        
                filtered_qualified_orders = []
                for order in qualified_orders:
                    order_id = order.get('order_id') or order.get('id')
                    if order_id in filter_order_ids:
                        filtered_qualified_orders.append(order)
        
                qualified_orders = filtered_qualified_orders
        
                logger.info("Zakończono filtrację po order_ids", extra={
                    'qualified_orders_after': len(qualified_orders)
                })

            if qualified_orders and not dry_run:
                enhanced_result = self.process_orders_with_priority_logic(
                    qualified_orders,
                    sync_type='manual',
                    auto_status_change=auto_status_change
                )
        
                stats['orders_processed'] = enhanced_result.get('orders_processed', 0)
                stats['products_created'] = enhanced_result.get('products_created', 0)
                stats['products_updated'] = enhanced_result.get('products_updated', 0)
                stats['errors_count'] += enhanced_result.get('errors_count', 0)
        
                if enhanced_result.get('error_details'):
                    error_details.extend(enhanced_result['error_details'])
        
                add_log(
                    f'Enhanced processing: {stats["orders_processed"]} zamówień, '
                    f'{stats["products_created"]} produktów utworzonych.',
                    'info'
                )
        
            elif qualified_orders and dry_run:
                for order in qualified_orders:
                    quantity_total = sum(prod.get('quantity', 0) or 0 for prod in order.get('products', []))
                    stats['products_created'] += quantity_total
                    stats['orders_processed'] += 1

            add_log(
                f"Synchronizacja zakończona. Zamówienia przetworzone: {stats['orders_processed']}, "
                f"utworzone produkty: {stats['products_created']}.",
                'info'
            )

            if sync_log:
                sync_log.orders_processed = stats['orders_processed']
                sync_log.products_created = stats['products_created']
                sync_log.products_updated = stats['products_updated']
                sync_log.products_skipped = stats['products_skipped']
                sync_log.error_count = stats['errors_count']
                
                if auto_status_change and stats['products_created'] > 0:
                    sync_log.priority_recalc_triggered = recalculate_priorities
                
                if error_details:
                    sync_log.error_details = json.dumps({'errors': error_details})
                
                success = stats['errors_count'] == 0
                sync_log.complete_sync(success=success)
                db.session.commit()

            sync_completed_at = get_local_now()
            duration_seconds = int((sync_completed_at - sync_started_at).total_seconds())
            status_label = 'dry_run' if dry_run else ('partial' if stats['errors_count'] > 0 else 'completed')

            stats_payload = {
                'pages_processed': int(stats['pages_processed']),
                'orders_found': int(stats['orders_found']),
                'orders_matched': int(stats['orders_matched_status']),
                'orders_processed': int(stats['orders_processed']),
                'orders_skipped_existing': int(stats['orders_skipped_existing']),
                'products_created': int(stats['products_created']),
                'products_updated': int(stats['products_updated']),
                'products_skipped': int(stats['products_skipped']),
                'errors_count': int(stats['errors_count'])
            }

            response = {
                'success': True,
                'message': 'Enhanced synchronizacja Baselinker zakończona pomyślnie.',
                'data': {
                    'sync_id': f"manual_{sync_log.id}" if sync_log else f"manual_{int(sync_started_at.timestamp())}",
                    'status': status_label,
                    'started_at': sync_started_at.isoformat(),
                    'completed_at': sync_completed_at.isoformat(),
                    'duration_seconds': duration_seconds,
                    'options': {
                        'force_update': force_update,
                        'skip_validation': skip_validation,
                        'dry_run': dry_run,
                        'debug_mode': debug_mode,
                        'limit_per_page': limit_per_page,
                        'period_days': period_days,
                        'target_statuses': sorted(target_statuses),
                        'excluded_keywords': sorted(excluded_keywords),
                        'recalculate_priorities': recalculate_priorities,
                        'auto_status_change': auto_status_change,
                        'respect_manual_overrides': respect_manual_overrides
                    },
                    'stats': stats_payload,
                    'log_entries': log_entries,
                    'enhanced_features': {
                        'payment_date_extraction': True,
                        'product_validation': True,
                        'status_change_workflow': auto_status_change,
                        'priority_recalculation': recalculate_priorities and stats['products_created'] > 0
                    }
                }
            }

            return response

        except SyncError as sync_error:
            logger.warning('Enhanced Manual Baselinker sync validation error', extra={'error': str(sync_error)})
            
            if sync_log:
                sync_log.sync_status = 'failed'
                sync_log.error_details = json.dumps({'error': str(sync_error)})
                sync_log.complete_sync(success=False, error_message=str(sync_error))
                db.session.commit()
            
            return {
                'success': False,
                'error': str(sync_error),
                'message': f'Błąd walidacji synchronizacji: {str(sync_error)}',
                'data': {
                    'sync_id': f"manual_{sync_log.id}" if sync_log else f"manual_{int(sync_started_at.timestamp())}",
                    'status': 'failed',
                    'started_at': sync_started_at.isoformat(),
                    'completed_at': get_local_now().isoformat(),
                    'duration_seconds': int((get_local_now() - sync_started_at).total_seconds()),
                    'stats': stats,
                    'log_entries': log_entries
                }
            }

        except Exception as exc:
            logger.exception('Enhanced Manual Baselinker sync unexpected error')
            
            if sync_log:
                sync_log.sync_status = 'failed'
                sync_log.error_details = json.dumps({'error': str(exc)})
                sync_log.complete_sync(success=False, error_message=str(exc))
                db.session.commit()
            
            return {
                'success': False,
                'error': str(exc),
                'message': f'Nieoczekiwany błąd synchronizacji: {str(exc)}',
                'data': {
                    'sync_id': f"manual_{sync_log.id}" if sync_log else f"manual_{int(sync_started_at.timestamp())}",
                    'status': 'failed',
                    'started_at': sync_started_at.isoformat(),
                    'completed_at': get_local_now().isoformat(),
                    'duration_seconds': int((get_local_now() - sync_started_at).total_seconds()),
                    'stats': stats,
                    'log_entries': log_entries
                }
            }

    def sync_orders_from_baselinker(self, sync_type: str = 'cron_auto') -> Dict[str, Any]:
        if sync_type == 'cron_auto':
            return self.sync_paid_orders_only()
        else:
            return self._legacy_sync_orders_from_baselinker(sync_type)
    
    def _legacy_sync_orders_from_baselinker(self, sync_type: str) -> Dict[str, Any]:
        sync_started_at = get_local_now()
        
        from ..services.id_generator import ProductIDGenerator
        ProductIDGenerator.clear_order_cache()
        logger.info("Wyczyszczono cache generatora ID")
    
        sync_log = self._create_sync_log(sync_type, sync_started_at)
        
        try:
            logger.info("Rozpoczęcie synchronizacji Baselinker (legacy)", extra={'sync_type': sync_type})
            
            orders_data = self._fetch_orders_from_baselinker()
            if sync_log:
                sync_log.orders_fetched = len(orders_data)
            
            processing_results = self._process_orders_to_products(orders_data)
            
            if sync_log:
                sync_log.products_created = processing_results['created']
                sync_log.products_updated = processing_results['updated'] 
                sync_log.products_skipped = processing_results['skipped']
                sync_log.error_count = processing_results['errors']
                sync_log.error_details = json.dumps(processing_results['error_details'])
            
            self._update_product_priorities()
            
            if sync_log:
                sync_log.mark_completed()
                db.session.commit()
            
            results = {
                'success': True,
                'sync_duration_seconds': sync_log.sync_duration_seconds if sync_log else 0,
                'orders_fetched': len(orders_data),
                'products_created': processing_results['created'],
                'products_updated': processing_results['updated'],
                'products_skipped': processing_results['skipped'],
                'error_count': processing_results['errors']
            }
            
            logger.info("Zakończono synchronizację Baselinker (legacy)", extra=results)
            return results
            
        except Exception as e:
            logger.error("Błąd synchronizacji Baselinker (legacy)", extra={
                'sync_type': sync_type,
                'error': str(e)
            })
            
            if sync_log:
                sync_log.sync_status = 'failed'
                sync_log.error_count = sync_log.error_count + 1 if sync_log.error_count else 1
                sync_log.error_details = json.dumps({'main_error': str(e)})
                sync_log.mark_completed()
                db.session.commit()
            
            return {
                'success': False,
                'error': str(e),
                'sync_duration_seconds': sync_log.sync_duration_seconds if sync_log else 0
            }

    def _create_sync_log(self, sync_type: str, sync_started_at: datetime) -> Optional['ProductionSyncLog']:
        try:
            from ..models import ProductionSyncLog

            sync_log = ProductionSyncLog(
                sync_type=sync_type,
                sync_started_at=sync_started_at,
                processed_status_ids=','.join(map(str, self.source_statuses))
            )

            db.session.add(sync_log)
            db.session.commit()

            return sync_log

        except Exception as e:
            logger.error("Błąd tworzenia logu synchronizacji", extra={'error': str(e)})
            return None

    def _fetch_orders_from_baselinker(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            raise SyncError("Brak klucza API Baselinker")
        
        all_orders = []
        
        for status_id in self.source_statuses:
            try:
                logger.debug("Pobieranie zamówień dla statusu", extra={'status_id': status_id})
                
                request_data = {
                    'token': self.api_key,
                    'method': 'getOrders',
                    'parameters': json.dumps({
                        'status_id': status_id,
                        'get_unconfirmed_orders': True,
                        'date_confirmed_from': int((datetime.now() - timedelta(days=30)).timestamp()),
                        'date_limit': self.max_items_per_batch
                    })
                }
                
                response_data = self._make_api_request(request_data)
                
                if response_data.get('status') == 'SUCCESS':
                    orders = response_data.get('orders', [])
                    all_orders.extend(orders)
                else:
                    error_msg = response_data.get('error_message', 'Unknown error')
                    logger.warning("Błąd API dla statusu", extra={
                        'status_id': status_id,
                        'error': error_msg
                    })
                    
            except Exception as e:
                logger.error("Błąd pobierania zamówień dla statusu", extra={
                    'status_id': status_id,
                    'error': str(e)
                })
                continue
        
        logger.info("Pobrano wszystkie zamówienia z Baselinker", extra={
            'total_orders': len(all_orders)
        })
        
        return all_orders
    
    def _make_api_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug("Wykonywanie requestu do Baselinker", extra={
                    'attempt': attempt + 1,
                    'method': request_data.get('method')
                })
                
                response = requests.post(
                    self.api_endpoint,
                    data=request_data,
                    timeout=self.api_timeout,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'}
                )
                
                response.raise_for_status()
                
                try:
                    response_data = response.json()
                    return response_data
                except json.JSONDecodeError as e:
                    raise SyncError(f"Nieprawidłowa odpowiedź JSON: {e}")
                    
            except requests.RequestException as e:
                last_error = e
                logger.warning("Błąd requestu API", extra={
                    'attempt': attempt + 1,
                    'error': str(e)
                })
                
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(self.retry_delay * (attempt + 1))
                
        raise SyncError(f"Nie udało się wykonać requestu po {self.max_retries} próbach: {last_error}")

    def _process_orders_to_products(self, orders_data: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, Any]:
        results = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'error_details': []
        }
        
        for order in orders_data:
            try:
                order_id = order.get('order_id')
                if not order_id:
                    results['errors'] += 1
                    continue
                
                if self._order_already_processed(order_id):
                    logger.info("Zamówienie już przetworzone", extra={'order_id': order_id})
                    results['skipped'] += 1
                    continue
                
                products = order.get('products', [])
                if not products:
                    results['skipped'] += 1
                    continue
                
                order_results = self._process_single_order_enhanced(
                    order, products, None, 'legacy'
                )
                
                results['created'] += order_results['created']
                results['updated'] += order_results['updated']
                results['errors'] += order_results['errors']
                results['error_details'].extend(order_results['error_details'])
                
            except Exception as e:
                results['errors'] += 1
                results['error_details'].append({
                    'error': str(e),
                    'order_id': order.get('order_id', 'unknown')
                })
                logger.error("Błąd przetwarzania zamówienia", extra={
                    'order_id': order.get('order_id'),
                    'error': str(e)
                })
        
        return results

    def _order_already_processed(self, baselinker_order_id: int) -> bool:
        try:
            from ..models import ProductionItem
            
            existing = ProductionItem.query.filter_by(
                baselinker_order_id=baselinker_order_id
            ).first()
            
            return existing is not None
            
        except Exception as e:
            logger.error("Błąd sprawdzania istniejącego zamówienia", extra={
                'order_id': baselinker_order_id,
                'error': str(e)
            })
            return False

    def _coerce_quantity(self, value: Any, default: int = 1) -> int:
        try:
            if value is None:
                return default

            if isinstance(value, (int, float)):
                quantity = int(float(value))
            else:
                value_str = str(value).strip()
                if not value_str:
                    return default
                quantity = int(float(value_str.replace(',', '.')))

            if quantity <= 0:
                return default

            return quantity

        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            if value is None:
                return None

            if isinstance(value, (int, float)):
                converted = int(float(value))
            else:
                value_str = str(value).strip()
                if not value_str:
                    return None
                converted = int(float(value_str))

            return converted

        except (TypeError, ValueError):
            return None

    def _update_product_priorities(self):
        try:
            from ..services.priority_service import recalculate_all_priorities
            
            result = recalculate_all_priorities()
            if result.get('success'):
                logger.info("Zaktualizowano priorytety po synchronizacji", extra={
                    'products_updated': result.get('products_prioritized', 0)
                })
            else:
                logger.error("Błąd aktualizacji priorytetów", extra={
                    'error': result.get('error')
                })
                
        except Exception as e:
            logger.error("Wyjątek aktualizacji priorytetów", extra={'error': str(e)})

    def update_order_status_in_baselinker(self, internal_order_number: str) -> bool:
        try:
            from ..models import ProductionItem
            
            products = ProductionItem.query.filter_by(
                internal_order_number=internal_order_number
            ).all()
            
            if not products:
                logger.warning("Nie znaleziono produktów dla zamówienia", extra={
                    'internal_order_number': internal_order_number
                })
                return False
            
            all_packed = all(p.current_status == 'spakowane' for p in products)
            if not all_packed:
                logger.info("Nie wszystkie produkty są spakowane", extra={
                    'internal_order_number': internal_order_number,
                    'packed_count': sum(1 for p in products if p.current_status == 'spakowane'),
                    'total_count': len(products)
                })
                return False
            
            baselinker_order_id = products[0].baselinker_order_id
            
            return self._update_baselinker_order_status(baselinker_order_id, self.target_completed_status)
            
        except Exception as e:
            logger.error("Błąd aktualizacji statusu w Baselinker", extra={
                'internal_order_number': internal_order_number,
                'error': str(e)
            })
            return False

    def _update_baselinker_order_status(self, baselinker_order_id: int, new_status_id: int) -> bool:
        if not self.api_key:
            logger.error("Brak klucza API Baselinker")
            return False
        
        try:
            request_data = {
                'token': self.api_key,
                'method': 'setOrderStatus',
                'parameters': json.dumps({
                    'order_id': baselinker_order_id,
                    'status_id': new_status_id
                })
            }
            
            response_data = self._make_api_request(request_data)
            
            if response_data.get('status') == 'SUCCESS':
                logger.info("Zaktualizowano status zamówienia w Baselinker", extra={
                    'baselinker_order_id': baselinker_order_id,
                    'new_status_id': new_status_id
                })
                return True
            else:
                error_msg = response_data.get('error_message', 'Unknown error')
                logger.error("Błąd aktualizacji statusu w Baselinker", extra={
                    'baselinker_order_id': baselinker_order_id,
                    'error': error_msg
                })
                return False
                
        except Exception as e:
            logger.error("Błąd komunikacji z Baselinker", extra={
                'baselinker_order_id': baselinker_order_id,
                'error': str(e)
            })
            return False

    def get_sync_status(self) -> Dict[str, Any]:
        try:
            from ..models import ProductionSyncLog
            
            last_sync = ProductionSyncLog.query.order_by(
                ProductionSyncLog.sync_started_at.desc()
            ).first()
            
            running_sync = ProductionSyncLog.query.filter_by(
                sync_status='in_progress'
            ).first()
            
            since_24h = get_local_now() - timedelta(hours=24)
            recent_syncs = ProductionSyncLog.query.filter(
                ProductionSyncLog.sync_started_at >= since_24h
            ).all()
            
            return {
                'sync_enabled': bool(self.api_key),
                'is_running': running_sync is not None,
                'last_sync': {
                    'timestamp': last_sync.sync_started_at.isoformat() if last_sync else None,
                    'status': last_sync.sync_status if last_sync else None,
                    'duration_seconds': last_sync.sync_duration_seconds if last_sync else None,
                    'products_created': last_sync.products_created if last_sync else 0,
                    'error_count': last_sync.error_count if last_sync else 0
                } if last_sync else None,
                'recent_stats': {
                    'syncs_count': len(recent_syncs),
                    'success_count': len([s for s in recent_syncs if s.sync_status == 'completed']),
                    'failed_count': len([s for s in recent_syncs if s.sync_status == 'failed']),
                    'total_products_created': sum(s.products_created or 0 for s in recent_syncs),
                    'total_errors': sum(s.error_count or 0 for s in recent_syncs)
                }
            }
            
        except Exception as e:
            logger.error("Błąd pobierania statusu synchronizacji", extra={'error': str(e)})
            return {
                'sync_enabled': bool(self.api_key),
                'is_running': False,
                'error': str(e),
                'last_sync': None,
                'recent_stats': {
                    'syncs_count': 0,
                    'success_count': 0, 
                    'failed_count': 0,
                    'total_products_created': 0,
                    'total_errors': 0
                }
            }

    def extract_client_data(self, order: Dict[str, Any]) -> Dict[str, str]:
        client_name = ""
        if order.get('delivery_fullname') and order['delivery_fullname'].strip():
            client_name = order['delivery_fullname'].strip()
        elif order.get('invoice_fullname') and order['invoice_fullname'].strip():
            client_name = order['invoice_fullname'].strip()
        elif order.get('user_login') and order['user_login'].strip():
            client_name = order['user_login'].strip()
        elif order.get('email') and order['email'].strip():
            client_name = order['email'].strip()

        client_email = order.get('email', '').strip()
        client_phone = order.get('phone', '').strip()

        address_parts = []

        if order.get('delivery_address') and order['delivery_address'].strip():
            address_parts.append(order['delivery_address'].strip())

        if order.get('delivery_postcode') and order['delivery_postcode'].strip():
            if order.get('delivery_city') and order['delivery_city'].strip():
                address_parts.append(f"{order['delivery_postcode'].strip()} {order['delivery_city'].strip()}")
            else:
                address_parts.append(order['delivery_postcode'].strip())
        elif order.get('delivery_city') and order['delivery_city'].strip():
            address_parts.append(order['delivery_city'].strip())

        delivery_address = ', '.join(address_parts)

        return {
            'client_name': client_name,
            'client_email': client_email,
            'client_phone': client_phone,
            'delivery_address': delivery_address
        }

    def _calculate_deadline_date(self, order: Dict[str, Any]) -> date:
        base_timestamp = None

        if order.get('date_in_status'):
            try:
                base_timestamp = int(order['date_in_status'])
            except (TypeError, ValueError):
                pass

        if not base_timestamp and order.get('date_status_change'):
            try:
                base_timestamp = int(order['date_status_change'])
            except (TypeError, ValueError):
                pass

        if not base_timestamp and order.get('date_add'):
            try:
                base_timestamp = int(order['date_add'])
            except (TypeError, ValueError):
                pass

        if base_timestamp:
            try:
                base_date = datetime.fromtimestamp(base_timestamp).date()
            except (OSError, ValueError):
                base_date = date.today()
        else:
            base_date = date.today()

        try:
            from ..models import ProductionConfig
            config_record = ProductionConfig.query.filter_by(config_key='DEADLINE_DEFAULT_DAYS').first()
            if config_record and config_record.parsed_value:
                deadline_days = int(config_record.parsed_value)
            else:
                deadline_days = 14
        except Exception as e:
            deadline_days = 14

        try:
            deadline_date = self._add_business_days(base_date, deadline_days)
        except Exception as e:
            deadline_date = self._add_business_days(date.today(), 14)

        return deadline_date

    def _add_business_days(self, start_date: date, business_days: int) -> date:
        if not isinstance(start_date, date):
            start_date = get_local_now().date()
        if business_days <= 0:
            return start_date
        current_date = start_date
        added_days = 0
        while added_days < business_days:
            current_date += timedelta(days=1)
            if current_date.weekday() < 5:
                added_days += 1
        return current_date

    def _process_single_order_enhanced(self, order: Dict[str, Any], products: List[Dict[str, Any]], 
                                     payment_date: Optional[datetime], sync_type: str) -> Dict[str, Any]:
        results = {
            'created': 0,
            'updated': 0,
            'errors': 0,
            'error_details': []
        }
        
        baselinker_order_id = order['order_id']
        
        try:
            from ..services.id_generator import ProductIDGenerator
            from ..services.parser_service import get_parser_service
            from ..models import ProductionItem
            
            client_data = self.extract_client_data(order)
            deadline_date = self._calculate_deadline_date(order)
            
            total_products_count = sum(self._coerce_quantity(p.get('quantity', 1)) for p in products)
            
            id_result = ProductIDGenerator.generate_product_id_for_order(
                baselinker_order_id, total_products_count
            )
            
            current_id_index = 0
            parser = get_parser_service()
            prepared_items = []
            
            for product_index, product in enumerate(products):
                try:
                    product_name = product.get('name', '')
                    quantity = self._coerce_quantity(product.get('quantity', 1))
                    order_product_id = product.get('order_product_id')
                    
                    parsed_data = parser.parse_product_name(product_name)
                    
                    for qty_index in range(quantity):
                        if current_id_index >= len(id_result['product_ids']):
                            raise Exception(f"Brak ID dla pozycji {current_id_index}")
                        
                        product_id = id_result['product_ids'][current_id_index]
                        current_id_index += 1
                        
                        product_data = self._prepare_product_data_enhanced(
                            order=order,
                            product=product,
                            product_id=product_id,
                            id_result=id_result,
                            parsed_data=parsed_data,
                            client_data=client_data,
                            deadline_date=deadline_date,
                            order_product_id=order_product_id,
                            sequence_number=current_id_index,
                            payment_date=payment_date
                        )
                        
                        production_item = ProductionItem(**product_data)
                        production_item.update_thickness_group()
                        
                        prepared_items.append(production_item)
                        results['created'] += 1
                        
                except Exception as e:
                    results['errors'] += 1
                    results['error_details'].append({
                        'product_name': product.get('name', ''),
                        'product_index': product_index,
                        'error': str(e)
                    })
            
            if prepared_items:
                try:
                    for item in prepared_items:
                        db.session.add(item)
                    
                    db.session.commit()
                    
                    logger.info("Zapisano produkty do bazy", extra={
                        'order_id': baselinker_order_id,
                        'items_saved': len(prepared_items)
                    })
                    
                except Exception as e:
                    db.session.rollback()
                    results['errors'] = len(prepared_items)
                    results['created'] = 0
                    results['error_details'].append({
                        'error': f'Database commit error: {str(e)}',
                        'order_id': baselinker_order_id
                    })
            
        except Exception as e:
            db.session.rollback()
            results['errors'] += 1
            results['error_details'].append({
                'error': str(e),
                'order_id': baselinker_order_id
            })
        
        return results

    def get_baselinker_statuses(self) -> Dict[int, str]:
        if not self.api_key:
            raise SyncError("Brak klucza API Baselinker")
    
        try:
            request_data = {
                'token': self.api_key,
                'method': 'getOrderStatusList',
                'parameters': json.dumps({})
            }
        
            response_data = self._make_api_request(request_data)
        
            if response_data.get('status') == 'SUCCESS':
                statuses_data = response_data.get('statuses', [])
                statuses = {}
            
                if isinstance(statuses_data, list):
                    for status_item in statuses_data:
                        try:
                            if isinstance(status_item, dict):
                                status_id = status_item.get('id')
                                status_name = status_item.get('name', f'Status {status_id}')
                            
                                if status_id is not None:
                                    statuses[int(status_id)] = status_name
                        except (ValueError, TypeError) as e:
                            logger.warning("Błąd parsowania statusu", extra={
                                'status_item': status_item,
                                'error': str(e)
                            })
                            continue
                        
                elif isinstance(statuses_data, dict):
                    for status_id, status_info in statuses_data.items():
                        try:
                            status_id_int = int(status_id)
                            if isinstance(status_info, dict):
                                status_name = status_info.get('name', f'Status {status_id}')
                            else:
                                status_name = str(status_info)
                        
                            statuses[status_id_int] = status_name
                        except (ValueError, TypeError) as e:
                            logger.warning("Błąd parsowania statusu dict", extra={
                                'status_id': status_id,
                                'error': str(e)
                            })
                            continue
            
                logger.info("Pobrano statusy z Baselinker", extra={
                    'statuses_count': len(statuses)
                })
            
                return statuses
            
            else:
                error_msg = response_data.get('error_message', 'Nieznany błąd API')
                raise SyncError(f'Baselinker API error: {error_msg}')
            
        except Exception as e:
            logger.error("Błąd pobierania statusów", extra={'error': str(e)})
            raise SyncError(f'Błąd pobierania statusów: {str(e)}')

_sync_service_instance = None

def get_sync_service() -> BaselinkerSyncService:
    global _sync_service_instance
    
    if _sync_service_instance is None:
        _sync_service_instance = BaselinkerSyncService()
        logger.info("Utworzono singleton BaselinkerSyncService v2.0")
    
    return _sync_service_instance

def sync_orders_from_baselinker(sync_type: str = 'manual_trigger') -> Dict[str, Any]:
    return get_sync_service().sync_orders_from_baselinker(sync_type)

def manual_sync_with_filtering(params: Dict[str, Any]) -> Dict[str, Any]:
    return get_sync_service().manual_sync_with_filtering(params)

def get_sync_status() -> Dict[str, Any]:
    return get_sync_service().get_sync_status()

def sync_paid_orders_only() -> Dict[str, Any]:
    return get_sync_service().sync_paid_orders_only()

def process_orders_with_priority_logic(orders_data: List[Dict[str, Any]], 
                                     sync_type: str = 'manual',
                                     auto_status_change: bool = True) -> Dict[str, Any]:
    return get_sync_service().process_orders_with_priority_logic(orders_data, sync_type, auto_status_change)