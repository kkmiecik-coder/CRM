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
from ..models import get_local_now

logger = get_structured_logger('production.sync.v2')

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

            # Pusta tabela (np. świeża baza lokalna) → spróbuj zasiać z BL API
            if not status_records:
                logger.info("Tabela baselinker_config (order_status) pusta - próba auto-seed z BL API")
                try:
                    from modules.baselinker.service import BaselinkerService
                    if BaselinkerService().sync_order_statuses():
                        status_records = BaselinkerConfig.query.filter_by(
                            config_type='order_status',
                            is_active=True
                        ).all()
                        logger.info("Auto-seed statusów udany", extra={
                            'seeded_count': len(status_records),
                        })
                    else:
                        logger.warning("Auto-seed statusów nieudany - pozostajemy z pustą listą")
                except Exception as seed_error:
                    logger.error("Wyjątek podczas auto-seed statusów", extra={
                        'error': str(seed_error),
                    })

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

        # Mapowanie sync_type na sync_source dla bazy danych
        sync_source_map = {
            'cron': 'baselinker_auto',
            'manual': 'manual_entry',
            'auto': 'baselinker_auto'
        }
        sync_source = sync_source_map.get(sync_type, 'manual_entry')

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

                # Odfiltruj pozycje nieprodukcyjne (usługi/dopłaty) ZANIM trafią do
                # walidacji i tworzenia produktów. Pozycje typu "Docięcie do wymiaru -
                # usługa..." nie mają wymiarów i bez tego filtra blokowałyby całe
                # zamówienie komunikatem "Brak danych do produkcji".
                all_products = order_data.get('products', []) if isinstance(order_data, dict) else []
                production_products, ignored_products = self._split_production_items(all_products)

                if ignored_products:
                    ignored_qty = sum(self._coerce_quantity(p.get('quantity', 1)) for p in ignored_products)
                    processing_stats['products_skipped'] += ignored_qty
                    logger.info("Pominięto pozycje usługowe w zamówieniu", extra={
                        'order_id': order_id,
                        'ignored_count': len(ignored_products),
                        'ignored_quantity': ignored_qty,
                        'ignored_names': [str(p.get('name', ''))[:50] for p in ignored_products]
                    })
                    # Dalsze przetwarzanie widzi już tylko realne produkty
                    order_data['products'] = production_products

                    # Zamówienie wyłącznie usługowe → brak produkcji, komentarz informacyjny
                    if not production_products:
                        try:
                            existing_comment = order_data.get('admin_comments', '')
                            self.add_service_only_comment_to_baselinker(order_id, existing_comment)
                        except Exception as comment_error:
                            logger.error("Błąd dodawania komentarza o pozycjach usługowych", extra={
                                'order_id': order_id,
                                'error': str(comment_error)
                            })
                        continue

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

                # NOWA LOGIKA: liczymy pozycje zamówienia, nie sztuki
                total_positions = len(products)

                try:
                    from ..services.id_generator import ProductIDGenerator
                    id_generation_result = ProductIDGenerator.generate_product_id_for_order(
                        baselinker_order_id=order_id,
                        total_products_count=total_positions
                    )
    
                    logger.debug("Wygenerowano ID dla zamówienia", extra={
                        'order_id': order_id,
                        'total_positions': total_positions,
                        'generated_ids_count': len(id_generation_result['product_ids'])
                    })
    
                except Exception as id_error:
                    logger.error("Błąd generowania ID dla zamówienia", extra={
                        'order_id': order_id,
                        'total_positions': total_positions,
                        'error': str(id_error)
                    })
                    processing_stats['errors_count'] += 1
                    continue

                order_products_created = 0
                order_errors = 0
                current_sequence = 1
                # Flaga: czy zamówienie zostało odrzucone z powodu nieznanej technologii
                order_rejected_unknown_technology = False

                for product_data in products:
                    if order_rejected_unknown_technology:
                        break

                    try:
                        quantity = int(product_data.get('quantity', 1))

                        logger.debug("Przetwarzanie produktu", extra={
                            'order_id': order_id,
                            'product_name': product_data.get('name', 'unknown')[:50],
                            'quantity': quantity,
                            'sequence': current_sequence
                        })

                        # NOWA LOGIKA: jeden rekord z quantity zamiast pętli
                        try:
                            production_item = self._create_product_from_order_data(
                                order_data=order_data,
                                product_data=product_data,
                                payment_date=payment_date,
                                sequence_number=current_sequence,
                                id_generation_result=id_generation_result,
                                sync_source=sync_source,
                                quantity=quantity  # NOWY PARAMETR
                            )

                            if production_item:
                                db.session.add(production_item)
                                order_products_created += 1
                                processing_stats['products_created'] += 1

                                logger.debug("Pozycja utworzona", extra={
                                    'order_id': order_id,
                                    'product_id': production_item.short_product_id,
                                    'sequence': current_sequence,
                                    'quantity': quantity
                                })
                            else:
                                order_errors += 1
                                processing_stats['products_skipped'] += 1

                            current_sequence += 1

                        except ValueError as tech_error:
                            # Nierozpoznana technologia — odrzucamy całe zamówienie
                            logger.error("Nierozpoznana technologia — odrzucenie zamówienia", extra={
                                'order_id': order_id,
                                'product_name': product_data.get('name', 'unknown')[:50],
                                'sequence': current_sequence,
                                'error': str(tech_error)
                            })

                            # Cofnij wszystkie pozycje tego zamówienia dodane do sesji
                            db.session.rollback()
                            order_rejected_unknown_technology = True

                            # Cofnij liczniki już dodanych pozycji tego zamówienia
                            processing_stats['products_created'] -= order_products_created
                            order_products_created = 0

                            # Zapisz błąd do rejestru prod_errors
                            try:
                                from ..models import ProductionError
                                production_error = ProductionError(
                                    error_type='validation_error',
                                    error_message=str(tech_error),
                                    error_details_json={
                                        'order_id': order_id,
                                        'product_name': product_data.get('name', 'unknown'),
                                        'sequence': current_sequence,
                                        'error_subtype': 'unknown_technology'
                                    },
                                    related_order_id=order_id
                                )
                                db.session.add(production_error)
                                db.session.commit()
                            except Exception as err_log_error:
                                logger.error("Błąd zapisu ProductionError", extra={
                                    'order_id': order_id,
                                    'error': str(err_log_error)
                                })
                                try:
                                    db.session.rollback()
                                except Exception:
                                    pass

                            processing_stats['errors_count'] += 1
                            error_details.append({
                                'order_id': order_id,
                                'product_name': product_data.get('name', 'unknown'),
                                'sequence': current_sequence,
                                'error_type': 'unknown_technology',
                                'error_message': str(tech_error)
                            })

                        except Exception as item_error:
                            logger.error("Błąd tworzenia pozycji", extra={
                                'order_id': order_id,
                                'sequence': current_sequence,
                                'error': str(item_error)
                            })

                            order_errors += 1
                            processing_stats['products_skipped'] += 1
                            current_sequence += 1

                            error_details.append({
                                'order_id': order_id,
                                'product_name': product_data.get('name', 'unknown'),
                                'sequence': current_sequence - 1,
                                'error_type': 'item_creation_failed',
                                'error_message': str(item_error)
                            })

                    except Exception as product_error:
                        logger.error("Błąd przetwarzania produktu", extra={
                            'order_id': order_id,
                            'error': str(product_error)
                        })

                        order_errors += 1
                        processing_stats['products_skipped'] += 1
                        current_sequence += 1

                if order_rejected_unknown_technology:
                    # Zamówienie odrzucone — nie zmieniamy statusu w BaseLinker
                    logger.warning("Zamówienie odrzucone z powodu nieznanej technologii", extra={
                        'order_id': order_id
                    })
                elif order_products_created > 0:
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
        
            from .baselinker_status_sync import set_status_for_imported_order

            for order_id in orders_for_status_change:
                try:
                    success = set_status_for_imported_order(order_id)
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

    def _create_product_from_order_data(self, order_data: Dict[str, Any], product_data: Dict[str, Any], payment_date: Optional[datetime] = None, sequence_number: int = 1, id_generation_result: Dict[str, Any] = None, sync_source: str = 'baselinker_auto', quantity: int = 1) -> Optional['ProductionItem']:
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
                payment_date=payment_date,
                sync_source=sync_source,
                quantity=quantity  # NOWY PARAMETR
            )
        
            # Odfiltruj klucze pomocnicze (prefiks '_') — np. '_quote_detail' cache
            # nie jest polem ProductionItem i powodowałby TypeError przy konstrukcji.
            product_data_clean = {k: v for k, v in product_data_dict.items() if not k.startswith('_')}
            production_item = self._create_production_product_from_data(product_data_clean)

            logger.debug("Utworzono ProductionItem", extra={
                'product_id': product_id,
                'sequence_number': sequence_number,
                'order_id': order_id
            })
        
            return production_item
        
        except ValueError:
            # Nierozpoznana technologia — propaguj błąd wyżej, aby odrzucić całe zamówienie
            raise
        except Exception as e:
            logger.error("Błąd tworzenia produktu", extra={
                'error': str(e),
                'sequence_number': sequence_number
            })
            return None

    def _has_attachment_in_order(self, order_data: Dict[str, Any]) -> bool:
        """
        Sprawdza czy zamówienie ma załącznik w custom_extra_fields

        Returns:
            bool: True jeśli zamówienie ma załącznik
        """
        try:
            custom_fields = order_data.get('custom_extra_fields', {})
            if not custom_fields or not isinstance(custom_fields, dict):
                return False

            # ID pola załącznika w Baselinker (sprawdzone w teście API)
            ATTACHMENT_FIELD_ID = '56476'

            attachment_data = custom_fields.get(ATTACHMENT_FIELD_ID)

            if attachment_data and isinstance(attachment_data, dict):
                url = attachment_data.get('url', '').strip()
                return bool(url)

            return False

        except Exception as e:
            logger.warning("Błąd sprawdzania załącznika", extra={
                'order_id': order_data.get('order_id'),
                'error': str(e)
            })
            return False

    def _extract_attachment_from_order(self, order_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Ekstraktuje dane załącznika z zamówienia

        Returns:
            Dict z kluczami 'title' i 'url' lub None
        """
        try:
            custom_fields = order_data.get('custom_extra_fields')
            if not isinstance(custom_fields, dict):
                custom_fields = {}

            # BL trzyma pola custom albo w custom_extra_fields (ID jako klucz),
            # albo top-level w order_data jako "extra_field_<ID>" — szukamy w obu.
            candidates = []

            # 1) custom_extra_fields: znane ID najpierw (back-compat)
            ATTACHMENT_FIELD_IDS = ['56476']
            for fid in ATTACHMENT_FIELD_IDS:
                if fid in custom_fields:
                    candidates.append((f'custom_extra_fields.{fid}', custom_fields[fid]))
            for k, v in custom_fields.items():
                if k not in ATTACHMENT_FIELD_IDS:
                    candidates.append((f'custom_extra_fields.{k}', v))

            # 2) top-level extra_field_* (np. extra_field_56476)
            for k, v in order_data.items():
                if isinstance(k, str) and k.startswith('extra_field_'):
                    candidates.append((k, v))

            for key, value in candidates:
                if not (value and isinstance(value, dict)):
                    continue
                title = (value.get('title') or '').strip()
                url = (value.get('url') or '').strip()
                if url:
                    logger.info("Znaleziono załącznik w zamówieniu", extra={
                        'order_id': order_data.get('order_id'),
                        'field_id': key,
                        'attachment_name': title,
                        'attachment_url': url[:100]
                    })
                    return {'title': title or url.rsplit('/', 1)[-1], 'url': url}

            return None

        except Exception as e:
            logger.error("Błąd ekstrakcji załącznika", extra={
                'order_id': order_data.get('order_id'),
                'error': str(e)
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
        """
        Walidacja kompletności danych produktów w zamówieniu.
        NOWA LOGIKA: Produkty bez wymiarów są akceptowane TYLKO jeśli zamówienie ma załącznik.
        """
        try:
            from ..services.parser_service import get_parser_service

            products = order_data.get('products', [])
            if not products:
                return False, ['Zamówienie nie zawiera produktów']

            # Sprawdź czy zamówienie ma załącznik
            order_has_attachment = self._has_attachment_in_order(order_data)

            parser = get_parser_service()
            validation_errors = []
            products_without_dimensions_count = 0

            for i, product in enumerate(products):
                product_name = product.get('name', '').strip()
                if not product_name:
                    validation_errors.append(f'Produkt {i+1}: Brak nazwy produktu')
                    continue

                try:
                    parsed_data = parser.parse_product_name(product_name)

                    # Sprawdź czy produkt ma wymiary
                    has_dimensions = all([
                        parsed_data.get('width_cm'),
                        parsed_data.get('length_cm'),
                        parsed_data.get('thickness_cm')
                    ])

                    if not has_dimensions:
                        products_without_dimensions_count += 1

                        # Jeśli brak wymiarów ORAZ brak załącznika → BŁĄD
                        if not order_has_attachment:
                            validation_errors.append(
                                f'Produkt {i+1} "{product_name[:40]}": Brak wymiarów (szerokość, długość, grubość) i brak załącznika w zamówieniu'
                            )
                        else:
                            # Produkt bez wymiarów ALE z załącznikiem → OK, tylko logujemy
                            logger.info("Produkt bez wymiarów z załącznikiem - akceptuję", extra={
                                'order_id': order_data.get('order_id'),
                                'product_index': i+1,
                                'product_name': product_name[:50]
                            })

                except Exception as parse_error:
                    validation_errors.append(
                        f'Produkt {i+1} "{product_name[:30]}": Błąd parsowania - {str(parse_error)}'
                    )

            is_valid = len(validation_errors) == 0

            logger.debug("Walidacja produktów zamówienia", extra={
                'order_id': order_data.get('order_id'),
                'products_count': len(products),
                'products_without_dimensions': products_without_dimensions_count,
                'order_has_attachment': order_has_attachment,
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

    def _upsert_system_order_comment(self, order_id: int, message: str, dedup_marker: str, existing_comment: str = "") -> bool:
        """
        Dodaje systemowy komentarz do zamówienia w Baselinker, zachowując istniejący
        komentarz i unikając duplikatów.

        Args:
            order_id: ID zamówienia
            message: Pełny komunikat do dodania
            dedup_marker: Fragment, którego obecność w istniejącym komentarzu oznacza,
                że komunikat już był dodany (zapobiega duplikatom)
            existing_comment: Istniejący komentarz z zamówienia (już pobrany)
        """
        if not self.api_key:
            return False

        try:
            # Połącz z istniejącym komentarzem (z deduplikacją po markerze)
            if existing_comment and existing_comment.strip():
                if dedup_marker in existing_comment:
                    logger.info("Komentarz systemowy już istnieje", extra={
                        'order_id': order_id,
                        'marker': dedup_marker
                    })
                    return True
                new_comment = f"{existing_comment} | {message}"
            else:
                new_comment = message

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
                logger.info("Dodano komentarz systemowy do Baselinker", extra={
                    'order_id': order_id,
                    'marker': dedup_marker,
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

        error_summary = '; '.join(errors[:2])
        if len(errors) > 2:
            error_summary += f' (+{len(errors)-2})'

        message = f"SYSTEM: Brak danych do produkcji. {error_summary}"
        return self._upsert_system_order_comment(
            order_id, message, "SYSTEM: Brak danych do produkcji", existing_comment
        )

    def _split_production_items(self, products: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Dzieli pozycje zamówienia na produkcyjne i nieprodukcyjne (usługi/dopłaty).

        Pozycje usługowe (np. "Docięcie do wymiaru - usługa...") nie mają wymiarów
        i nie powinny trafiać do produkcji ani blokować walidacji zamówienia.

        Args:
            products: Lista pozycji zamówienia (słowniki z BaseLinker)

        Returns:
            Tuple[production_items, ignored_items] — zachowuje oryginalną kolejność
            i referencje do obiektów wejściowych.
        """
        from ..services.parser_service import is_non_production_item, get_parser_service

        parser = get_parser_service()
        production_items: List[Dict[str, Any]] = []
        ignored_items: List[Dict[str, Any]] = []

        for product in products:
            name = product.get('name', '') if isinstance(product, dict) else ''
            if is_non_production_item(name):
                # Zabezpieczenie przed fałszywym trafieniem: ignorujemy pozycję tylko,
                # gdy oprócz frazy usługi NIE ma sparsowanych wymiarów. Realny produkt
                # z "usługą" w nazwie (np. "Blat 120x80x4 + usługa olejowania") ma
                # wymiary i musi trafić do produkcji.
                parsed = parser.parse_product_name(name)
                has_dimensions = all(parsed.get(dim) for dim in ('length_cm', 'width_cm', 'thickness_cm'))
                if not has_dimensions:
                    ignored_items.append(product)
                    continue

            production_items.append(product)

        return production_items, ignored_items

    def add_service_only_comment_to_baselinker(self, order_id: int, existing_comment: str = "") -> bool:
        """
        Dodaje informacyjny komentarz do Baselinker dla zamówienia zawierającego
        wyłącznie pozycje usługowe (brak produktów do produkcji).

        Args:
            order_id: ID zamówienia
            existing_comment: Istniejący komentarz z zamówienia (już pobrany)
        """
        message = "SYSTEM: Zamówienie zawiera wyłącznie pozycje usługowe - pominięto w produkcji"
        return self._upsert_system_order_comment(
            order_id, message, "SYSTEM: Zamówienie zawiera wyłącznie pozycje usługowe", existing_comment
        )

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

    def _get_initial_station_by_technology(self, technology):
        """
        Zwraca początkowy status produkcyjny na podstawie technologii.
        - mikrowczep → czeka_na_wyciecie (stanowisko Wycinanie)
        - lity → czeka_na_skladanie (stanowisko Składanie)

        Raises:
            ValueError: Gdy technologia nie jest rozpoznana
        """
        technology_to_station = {
            'mikrowczep': 'czeka_na_wyciecie',
            'lity': 'czeka_na_skladanie',
        }
        station = technology_to_station.get(technology)
        if station is None:
            raise ValueError(f"Nierozpoznana technologia: '{technology}' — dozwolone: mikrowczep, lity")
        return station

    def _prepare_product_data_enhanced(self, order: Dict[str, Any], product: Dict[str, Any],
                             product_id: str, id_result: Dict[str, Any],
                             parsed_data: Dict[str, Any], client_data: Dict[str, str],
                             deadline_date: date, order_product_id: Any,
                             sequence_number: int, payment_date: Optional[datetime],
                             sync_source: str = 'baselinker_auto',
                             quantity: int = 1) -> Dict[str, Any]:

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
            # DANE DOSTAWY - ROZSZERZONE (2025-12)
            'delivery_method': client_data.get('delivery_method'),
            'delivery_fullname': client_data.get('delivery_fullname'),
            'delivery_company': client_data.get('delivery_company'),
            'delivery_city': client_data.get('delivery_city'),
            'delivery_postcode': client_data.get('delivery_postcode'),
            'delivery_country_code': client_data.get('delivery_country_code'),
            'deadline_date': deadline_date,
            'current_status': self._get_initial_station_by_technology(parsed_data.get('technology')),
            'sync_source': sync_source,
            'quantity': quantity  # NOWE: ilość sztuk z zamówienia
        }

        # Ekstrakcja załącznika z zamówienia
        attachment_info = self._extract_attachment_from_order(order)
        if attachment_info:
            product_data['attachment_file_name'] = attachment_info['title']
            product_data['attachment_file_url'] = attachment_info['url']
            logger.debug("Dodano załącznik do produktu", extra={
                'product_id': product_id,
                'attachment_name': attachment_info['title']
            })

        # Ekstrakcja dodatkowych pól z Baselinker (2025-11)
        # custom_extra_fields[170043] = numer wyceny
        custom_fields = order.get('custom_extra_fields', {}) or {}
        quote_number = (custom_fields.get('170043') or '').strip() or None
        if quote_number:
            product_data['quote_number'] = quote_number[:16]
            logger.debug("Dodano quote_number", extra={
                'product_id': product_id,
                'quote_number': quote_number
            })

        # extra_field_1 = wewnętrzny numer zamówienia klienta
        client_order_number = order.get('extra_field_1', '').strip() if order.get('extra_field_1') else None
        if client_order_number:
            product_data['client_order_number'] = client_order_number
            logger.debug("Dodano client_order_number", extra={
                'product_id': product_id,
                'client_order_number': client_order_number
            })

        # admin_comments = uwagi do zamówienia
        order_notes = order.get('admin_comments', '').strip() if order.get('admin_comments') else None
        if order_notes:
            product_data['order_notes'] = order_notes
            logger.debug("Dodano order_notes", extra={
                'product_id': product_id,
                'order_notes_length': len(order_notes)
            })
    
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
                'parsed_finish_type': parsed_data.get('finish_type', 'surowe'),
                'parsed_finish_color_type': parsed_data.get('finish_color_type'),
                'parsed_finish_gloss': parsed_data.get('finish_gloss'),
                'parsed_finish_color': parsed_data.get('finish_color'),
                'parsed_edge_processing': parsed_data.get('edge_processing', False),
                'parsed_edge_type': parsed_data.get('edge_type'),
                'parsed_edge_radius': parsed_data.get('edge_radius'),
                'parsed_edge_angle': parsed_data.get('edge_angle'),
                'parsed_edge_letters': parsed_data.get('edge_letters'),
                'parsed_edges_groups': parsed_data.get('edges_groups'),
                'volume_m3': volume_m3
            })

        # Cut_to_size z QuoteItemDetails (niezależne od edge processing)
        product_data = self._resolve_cut_to_size(product_data, order)

        # Wzbogać dane krawędzi z QuoteItemDetails (kaskada)
        product_data = self._enrich_edge_data_from_quote(product_data, order)

        try:
            price_brutto = float(product.get('price_brutto', 0))
            tax_rate = float(product.get('tax_rate', 23))
    
            custom_fields = order.get('custom_extra_fields', {}) or {}
            price_type = custom_fields.get('106169', '').strip().lower() if custom_fields else ''
    
            if price_type == 'netto':
                unit_price_net = price_brutto
            else:
                unit_price_net = price_brutto / (1 + tax_rate/100)

            # total_value_net = unit_price_net * quantity
            total_value_net = unit_price_net * quantity

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

    def _create_production_product_from_data(self, product_data: dict):
        """
        Tworzy ProductionProduct z flat dict, upsertując ProductionOrder
        i find-or-create ProductionConfiguration.
        Helper do migracji z monolitycznego ProductionItem(**dict).

        Args:
            product_data: flat dict z polami zarówno order-level jak i product-level
                          (jak zwracane przez _prepare_product_data_enhanced)

        Returns:
            ProductionProduct: niedodany do sesji (caller robi db.session.add)
        """
        from modules.production.models import ProductionOrder, ProductionProduct, ProductionConfiguration

        ORDER_LEVEL_KEYS = {
            'baselinker_order_id', 'internal_order_number', 'baselinker_status_id',
            'payment_date', 'client_order_number', 'quote_number', 'order_notes',
            'client_name', 'client_email', 'client_phone', 'delivery_address',
            'delivery_method', 'delivery_fullname', 'delivery_company',
            'delivery_city', 'delivery_postcode', 'delivery_country_code',
            'override_delivery_method', 'logistics_completed_at',
            'shipping_package_id', 'shipping_tracking_number', 'shipping_courier_name',
            'shipping_price', 'shipping_label_base64', 'shipping_created_at',
            'attachment_file_name', 'attachment_file_url', 'sync_source',
        }
        CONFIG_KEYS = {'parsed_wood_species', 'parsed_technology', 'parsed_wood_class'}

        bl_id = product_data.get('baselinker_order_id')
        if not bl_id:
            raise ValueError("baselinker_order_id wymagane do utworzenia produktu")

        # 1. Upsert ProductionOrder
        order = ProductionOrder.query.filter_by(baselinker_order_id=bl_id).first()
        if order is None:
            order = ProductionOrder(baselinker_order_id=bl_id)
            db.session.add(order)

        for key in ORDER_LEVEL_KEYS:
            if key in product_data and product_data[key] is not None:
                # NIE nadpisuj istniejących danych orderu pustym stringiem
                value = product_data[key]
                if isinstance(value, str) and not value.strip():
                    continue
                setattr(order, key, value)

        db.session.flush()  # żeby order.id było dostępne

        # 2. Find-or-create ProductionConfiguration
        config = ProductionConfiguration.find_or_create(
            species=product_data.get('parsed_wood_species'),
            technology=product_data.get('parsed_technology'),
            wood_class=product_data.get('parsed_wood_class'),
        )

        # 3. Stwórz ProductionProduct (tylko pola product-level)
        product_only_data = {
            k: v for k, v in product_data.items()
            if k not in ORDER_LEVEL_KEYS and k not in CONFIG_KEYS
        }
        product_only_data['order_id'] = order.id
        product_only_data['configuration_id'] = config.id

        return ProductionProduct(**product_only_data)

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
                            add_log(f'Pominięto produkt "{product_name}" w zamówieniu {order_id_val} — ilość <= 0.', 'warning')
                            continue

                    name_lower = product_name.lower()
                    if excluded_keywords and any(keyword in name_lower for keyword in excluded_keywords):
                        stats['products_skipped'] += quantity_value
                        add_log(f'Pominięto produkt "{product_name}" w zamówieniu {order_id_val} — wykluczony keyword.', 'warning')
                        continue

                    if reports_parser:
                        try:
                            parsed = reports_parser.parse_product_name(product_name)
                            product_type = (parsed.get('product_type') or '').lower()
                        except Exception as parse_error:
                            product_type = ''
                        if product_type and product_type in excluded_product_types:
                            stats['products_skipped'] += quantity_value
                            add_log(f'Pominięto produkt "{product_name}" w zamówieniu {order_id_val} — wykluczony typ: {product_type}.', 'warning')
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

    def get_order_from_baselinker(self, order_id: int) -> Optional[Dict[str, Any]]:
        """
        Pobiera pojedyncze zamówienie z Baselinker po ID

        Args:
            order_id: ID zamówienia w Baselinker

        Returns:
            Dict z danymi zamówienia lub None jeśli nie znaleziono
        """
        try:
            logger.info("Pobieranie zamówienia z Baselinker", extra={'order_id': order_id})

            request_data = {
                'token': self.api_key,
                'method': 'getOrders',
                'parameters': json.dumps({
                    'order_id': order_id,
                    'include_custom_extra_fields': True
                })
            }

            response_data = self._make_api_request(request_data)

            if response_data.get('status') == 'SUCCESS':
                orders = response_data.get('orders', [])
                if orders:
                    order = orders[0]
                    logger.info("Pobrano zamówienie z Baselinker", extra={
                        'order_id': order_id,
                        'products_count': len(order.get('products', []))
                    })
                    return order
                else:
                    logger.warning("Zamówienie nie znalezione w Baselinker", extra={'order_id': order_id})
                    return None
            else:
                error_msg = response_data.get('error_message', 'Unknown error')
                logger.error("Błąd API Baselinker", extra={
                    'order_id': order_id,
                    'error': error_msg
                })
                return None

        except Exception as e:
            logger.error("Błąd pobierania zamówienia z Baselinker", extra={
                'order_id': order_id,
                'error': str(e)
            })
            return None

    def compare_order_with_baselinker(self, baselinker_order_id: int) -> Dict[str, Any]:
        """
        Porównuje zamówienie w bazie z danymi z Baselinkera.

        Zwraca strukturę zmian:
        {
            'success': True/False,
            'order_id': baselinker_order_id,
            'order_number': '...',  # wewnętrzny numer zamówienia
            'has_changes': True/False,
            'changes': {
                'products_to_add': [...],     # nowe produkty do dodania
                'products_to_remove': [...],  # produkty do usunięcia
                'products_to_update': [...]   # produkty ze zmianami
            },
            'current_products': [...],  # aktualne produkty w bazie
            'baselinker_products': [...],  # produkty z Baselinker
            'error': None lub string
        }
        """
        from ..models import ProductionItem, ProductionOrder

        result = {
            'success': False,
            'order_id': baselinker_order_id,
            'order_number': None,
            'has_changes': False,
            'changes': {
                'products_to_add': [],
                'products_to_remove': [],
                'products_to_update': []
            },
            'current_products': [],
            'baselinker_products': [],
            'error': None
        }

        try:
            # 1. Pobierz zamówienie z Baselinker
            bl_order = self.get_order_from_baselinker(baselinker_order_id)
            if not bl_order:
                result['error'] = f'Zamówienie {baselinker_order_id} nie znalezione w Baselinker'
                return result

            # 2. Pobierz aktualne produkty z bazy
            current_products = ProductionItem.query.join(ProductionOrder).filter(
                ProductionOrder.baselinker_order_id == baselinker_order_id
            ).all()

            if not current_products:
                result['error'] = f'Brak produktów dla zamówienia {baselinker_order_id} w bazie danych'
                return result

            _first = current_products[0]
            result['order_number'] = _first.order.internal_order_number if _first.order else None

            # 3. Przygotuj mapę aktualnych produktów (po baselinker_product_id)
            current_products_map = {}
            for p in current_products:
                bp_id = str(p.baselinker_product_id) if p.baselinker_product_id else None
                if bp_id:
                    current_products_map[bp_id] = p
                result['current_products'].append({
                    'id': p.id,
                    'short_product_id': p.short_product_id,
                    'baselinker_product_id': p.baselinker_product_id,
                    'original_product_name': p.original_product_name,
                    'quantity': p.quantity or 1,
                    'current_status': p.current_status,
                    'wood_species': p.configuration.species if p.configuration else None,
                    'dimensions': None,
                    'technology': p.configuration.technology if p.configuration else None,
                })

            # 4. Przygotuj mapę produktów z Baselinker
            bl_products = bl_order.get('products', [])
            bl_products_map = {}

            for bp in bl_products:
                bp_id = str(bp.get('order_product_id', ''))
                if bp_id:
                    bl_products_map[bp_id] = bp

                    # Parsuj dane produktu
                    from .parser_service import ProductNameParser
                    parser = ProductNameParser()
                    parsed = parser.parse_product_name(bp.get('name', ''))

                    result['baselinker_products'].append({
                        'order_product_id': bp_id,
                        'name': bp.get('name', ''),
                        'quantity': bp.get('quantity', 1),
                        'sku': bp.get('sku', ''),
                        'price_brutto': bp.get('price_brutto', 0),
                        'parsed': parsed
                    })

            # 5. Znajdź zmiany
            current_bp_ids = set(current_products_map.keys())
            bl_bp_ids = set(bl_products_map.keys())

            # Produkty do usunięcia (są w bazie, nie ma w BL)
            products_to_remove = current_bp_ids - bl_bp_ids
            for bp_id in products_to_remove:
                p = current_products_map[bp_id]
                result['changes']['products_to_remove'].append({
                    'id': p.id,
                    'short_product_id': p.short_product_id,
                    'baselinker_product_id': bp_id,
                    'original_product_name': p.original_product_name,
                    'quantity': p.quantity or 1
                })

            # Produkty do dodania (są w BL, nie ma w bazie)
            products_to_add = bl_bp_ids - current_bp_ids
            for bp_id in products_to_add:
                bp = bl_products_map[bp_id]
                from .parser_service import ProductNameParser
                parser = ProductNameParser()
                parsed = parser.parse_product_name(bp.get('name', ''))

                result['changes']['products_to_add'].append({
                    'order_product_id': bp_id,
                    'name': bp.get('name', ''),
                    'quantity': bp.get('quantity', 1),
                    'parsed': parsed
                })

            # Produkty ze zmianami (są w obu, porównaj dane)
            products_to_compare = current_bp_ids & bl_bp_ids
            for bp_id in products_to_compare:
                p = current_products_map[bp_id]
                bp = bl_products_map[bp_id]

                changes = []

                # Porównaj quantity
                current_qty = p.quantity or 1
                bl_qty = bp.get('quantity', 1)
                if current_qty != bl_qty:
                    changes.append({
                        'field': 'quantity',
                        'label': 'Ilość',
                        'old_value': current_qty,
                        'new_value': bl_qty
                    })

                # Porównaj nazwę produktu
                if p.original_product_name != bp.get('name', ''):
                    changes.append({
                        'field': 'original_product_name',
                        'label': 'Nazwa produktu',
                        'old_value': p.original_product_name,
                        'new_value': bp.get('name', '')
                    })

                if changes:
                    result['changes']['products_to_update'].append({
                        'id': p.id,
                        'short_product_id': p.short_product_id,
                        'baselinker_product_id': bp_id,
                        'changes': changes
                    })

            # Porównaj też dane na poziomie zamówienia
            order_level_changes = []

            _first_order = current_products[0].order if current_products and current_products[0].order else None

            # client_order_number (extra_field_1)
            bl_client_order = bl_order.get('extra_field_1', '').strip() if bl_order.get('extra_field_1') else None
            current_client_order = _first_order.client_order_number if _first_order else None
            if bl_client_order != current_client_order:
                order_level_changes.append({
                    'field': 'client_order_number',
                    'label': 'Nr zamówienia klienta',
                    'old_value': current_client_order,
                    'new_value': bl_client_order
                })

            # quote_number (custom_extra_fields[170043])
            bl_custom = bl_order.get('custom_extra_fields', {}) or {}
            bl_quote_number = (bl_custom.get('170043') or '').strip() or None
            current_quote_number = _first_order.quote_number if _first_order else None
            if bl_quote_number != current_quote_number:
                order_level_changes.append({
                    'field': 'quote_number',
                    'label': 'Numer wyceny',
                    'old_value': current_quote_number,
                    'new_value': bl_quote_number
                })

            # order_notes (admin_comments)
            bl_notes = bl_order.get('admin_comments', '').strip() if bl_order.get('admin_comments') else None
            current_notes = _first_order.order_notes if _first_order else None
            if bl_notes != current_notes:
                order_level_changes.append({
                    'field': 'order_notes',
                    'label': 'Uwagi do zamówienia',
                    'old_value': current_notes[:100] + '...' if current_notes and len(current_notes) > 100 else current_notes,
                    'new_value': bl_notes[:100] + '...' if bl_notes and len(bl_notes) > 100 else bl_notes
                })

            # załącznik (custom_extra_fields)
            bl_attachment = self._extract_attachment_from_order(bl_order)
            bl_att_name = bl_attachment['title'] if bl_attachment else None
            bl_att_url = bl_attachment['url'] if bl_attachment else None
            current_att_name = _first_order.attachment_file_name if _first_order else None
            current_att_url = _first_order.attachment_file_url if _first_order else None
            if bl_att_url != current_att_url or bl_att_name != current_att_name:
                order_level_changes.append({
                    'field': 'attachment',
                    'label': 'Załącznik',
                    'old_value': current_att_name or '(brak)',
                    'new_value': bl_att_name or '(brak)',
                    'new_attachment': {
                        'name': bl_att_name,
                        'url': bl_att_url,
                    },
                })

            if order_level_changes:
                result['changes']['order_level'] = order_level_changes

            # 6. Określ czy są zmiany
            has_changes = (
                len(result['changes']['products_to_add']) > 0 or
                len(result['changes']['products_to_remove']) > 0 or
                len(result['changes']['products_to_update']) > 0 or
                len(order_level_changes) > 0
            )

            result['has_changes'] = has_changes
            result['success'] = True

            logger.info("Porównanie zamówienia zakończone", extra={
                'order_id': baselinker_order_id,
                'has_changes': has_changes,
                'to_add': len(result['changes']['products_to_add']),
                'to_remove': len(result['changes']['products_to_remove']),
                'to_update': len(result['changes']['products_to_update'])
            })

            return result

        except Exception as e:
            logger.error("Błąd porównania zamówienia", extra={
                'order_id': baselinker_order_id,
                'error': str(e)
            })
            result['error'] = f'Błąd porównania: {str(e)}'
            return result

    def apply_baselinker_changes(self, baselinker_order_id: int, changes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Aplikuje zmiany z porównania do bazy danych.

        Args:
            baselinker_order_id: ID zamówienia
            changes: Struktura zmian z compare_order_with_baselinker

        Returns:
            Dict z wynikiem operacji
        """
        from ..models import ProductionItem, ProductionOrder
        from .parser_service import ProductNameParser

        result = {
            'success': False,
            'added': 0,
            'removed': 0,
            'updated': 0,
            'errors': [],
            'error': None
        }

        try:
            parser = ProductNameParser()

            # 1. Usuń produkty
            for product_to_remove in changes.get('products_to_remove', []):
                try:
                    product = ProductionItem.query.get(product_to_remove['id'])
                    if product:
                        db.session.delete(product)
                        result['removed'] += 1
                        logger.info("Usunięto produkt", extra={
                            'product_id': product_to_remove['short_product_id'],
                            'order_id': baselinker_order_id
                        })
                except Exception as e:
                    result['errors'].append(f"Błąd usuwania {product_to_remove['short_product_id']}: {str(e)}")

            # 2. Aktualizuj produkty
            for product_to_update in changes.get('products_to_update', []):
                try:
                    product = ProductionItem.query.get(product_to_update['id'])
                    if product:
                        for change in product_to_update['changes']:
                            field = change['field']
                            new_value = change['new_value']

                            if field == 'quantity':
                                product.quantity = new_value
                            elif field == 'original_product_name':
                                product.original_product_name = new_value
                                # Re-parsuj dane produktu
                                parsed = parser.parse_product_name(new_value)
                                if parsed:
                                    # Ensure configuration exists before updating parsed fields
                                    if not product.configuration:
                                        from modules.production.models import ProductionConfiguration
                                        product.configuration = ProductionConfiguration.find_or_create(
                                            species=parsed.get('wood_species'),
                                            technology=parsed.get('technology'),
                                            wood_class=parsed.get('wood_class'),
                                        )
                                    else:
                                        product.configuration.species = parsed.get('wood_species')
                                        product.configuration.wood_class = parsed.get('wood_class')
                                        product.configuration.technology = parsed.get('technology')
                                    product.parsed_length_cm = parsed.get('length_cm')
                                    product.parsed_width_cm = parsed.get('width_cm')
                                    product.parsed_thickness_cm = parsed.get('thickness_cm')
                                    product.volume_m3 = parsed.get('volume_m3')

                        result['updated'] += 1
                        logger.info("Zaktualizowano produkt", extra={
                            'product_id': product_to_update['short_product_id'],
                            'changes_count': len(product_to_update['changes'])
                        })
                except Exception as e:
                    result['errors'].append(f"Błąd aktualizacji {product_to_update['short_product_id']}: {str(e)}")

            # 3. Dodaj nowe produkty
            if changes.get('products_to_add'):
                # Pobierz zamówienie z BL dla pełnych danych
                bl_order = self.get_order_from_baselinker(baselinker_order_id)
                if bl_order:
                    # Pobierz istniejący produkt z tego zamówienia dla kontekstu
                    existing_product = ProductionItem.query.join(ProductionOrder).filter(
                        ProductionOrder.baselinker_order_id == baselinker_order_id
                    ).first()

                    if existing_product:
                        # Znajdź najwyższy numer sekwencji
                        max_seq = db.session.query(db.func.max(ProductionItem.product_sequence_in_order))\
                            .join(ProductionOrder)\
                            .filter(ProductionOrder.baselinker_order_id == baselinker_order_id)\
                            .scalar() or 0

                        for idx, product_to_add in enumerate(changes['products_to_add']):
                            try:
                                seq_num = max_seq + idx + 1
                                bp_id = product_to_add['order_product_id']

                                # Znajdź dane produktu z BL
                                bl_product = None
                                for p in bl_order.get('products', []):
                                    if str(p.get('order_product_id', '')) == bp_id:
                                        bl_product = p
                                        break

                                if not bl_product:
                                    continue

                                # Generuj ID produktu
                                order_num = existing_product.order.internal_order_number if existing_product.order else None
                                short_product_id = f"{order_num}_{seq_num}"

                                # Parsuj dane produktu
                                parsed = parser.parse_product_name(bl_product.get('name', ''))

                                # Konstruujemy flat dict — _create_production_product_from_data
                                # rozdzieli order-level (idzie na existing_product.order przez upsert)
                                # od product-level
                                new_product_data = {
                                    'short_product_id': short_product_id,
                                    'internal_order_number': order_num,
                                    'product_sequence_in_order': seq_num,
                                    'baselinker_order_id': baselinker_order_id,
                                    'baselinker_product_id': bp_id,
                                    'original_product_name': bl_product.get('name', ''),
                                    'quantity': bl_product.get('quantity', 1),
                                    'current_status': 'czeka_na_wyciecie',
                                    'sync_source': 'admin_update',
                                    'client_name': existing_product.order.client_name if existing_product.order else None,
                                    'client_email': existing_product.order.client_email if existing_product.order else None,
                                    'client_phone': existing_product.order.client_phone if existing_product.order else None,
                                    'delivery_address': existing_product.order.delivery_address if existing_product.order else None,
                                    'deadline_date': existing_product.deadline_date,
                                    'payment_date': existing_product.order.payment_date if existing_product.order else None,
                                    'client_order_number': existing_product.order.client_order_number if existing_product.order else None,
                                    'order_notes': existing_product.order.order_notes if existing_product.order else None,
                                    'attachment_file_name': existing_product.order.attachment_file_name if existing_product.order else None,
                                    'attachment_file_url': existing_product.order.attachment_file_url if existing_product.order else None,
                                    'cut_to_size': True,
                                }
                                new_product = self._create_production_product_from_data(new_product_data)

                                # Dodaj sparsowane dane
                                if parsed:
                                    from modules.production.models import ProductionConfiguration
                                    new_product.configuration = ProductionConfiguration.find_or_create(
                                        species=parsed.get('wood_species'),
                                        technology=parsed.get('technology'),
                                        wood_class=parsed.get('wood_class'),
                                    )
                                    new_product.parsed_length_cm = parsed.get('length_cm')
                                    new_product.parsed_width_cm = parsed.get('width_cm')
                                    new_product.parsed_thickness_cm = parsed.get('thickness_cm')
                                    new_product.volume_m3 = parsed.get('volume_m3')

                                db.session.add(new_product)
                                result['added'] += 1

                                logger.info("Dodano nowy produkt", extra={
                                    'product_id': short_product_id,
                                    'order_id': baselinker_order_id
                                })

                            except Exception as e:
                                result['errors'].append(f"Błąd dodawania produktu: {str(e)}")

            # 4. Aktualizuj dane na poziomie zamówienia (na ProductionOrder, nie produktach)
            if changes.get('order_level'):
                order_obj = ProductionOrder.query.filter_by(
                    baselinker_order_id=baselinker_order_id
                ).first()

                if order_obj:
                    for change in changes['order_level']:
                        field = change['field']
                        new_value = change['new_value']
                        if field == 'attachment':
                            new_attachment = change.get('new_attachment') or {}
                            order_obj.attachment_file_name = new_attachment.get('name')
                            order_obj.attachment_file_url = new_attachment.get('url')
                        else:
                            setattr(order_obj, field, new_value)

                logger.info("Zaktualizowano dane zamówienia", extra={
                    'order_id': baselinker_order_id,
                    'fields_updated': [c['field'] for c in changes['order_level']]
                })

            db.session.commit()
            result['success'] = True

            logger.info("Zastosowano zmiany z Baselinker", extra={
                'order_id': baselinker_order_id,
                'added': result['added'],
                'removed': result['removed'],
                'updated': result['updated']
            })

            return result

        except Exception as e:
            db.session.rollback()
            logger.error("Błąd aplikowania zmian", extra={
                'order_id': baselinker_order_id,
                'error': str(e)
            })
            result['error'] = f'Błąd aplikowania zmian: {str(e)}'
            return result

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
            from ..models import ProductionOrder

            existing = ProductionOrder.query.filter_by(
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

    def _update_baselinker_order_status(self, baselinker_order_id: int, new_status_id: int) -> bool:
        """Niskopoziomowe wywołanie setOrderStatus. Używane przez baselinker_status_sync."""
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

        # delivery_address = tylko ulica (bez kodu i miasta)
        delivery_address = order.get('delivery_address', '').strip() if order.get('delivery_address') else None

        return {
            'client_name': client_name,
            'client_email': client_email,
            'client_phone': client_phone,
            'delivery_address': delivery_address,
            # DANE DOSTAWY - ROZSZERZONE (2025-12)
            'delivery_method': order.get('delivery_method', '').strip() if order.get('delivery_method') else None,
            'delivery_fullname': order.get('delivery_fullname', '').strip() if order.get('delivery_fullname') else None,
            'delivery_company': order.get('delivery_company', '').strip() if order.get('delivery_company') else None,
            'delivery_city': order.get('delivery_city', '').strip() if order.get('delivery_city') else None,
            'delivery_postcode': order.get('delivery_postcode', '').strip() if order.get('delivery_postcode') else None,
            'delivery_country_code': order.get('delivery_country_code', '').strip() if order.get('delivery_country_code') else None,
        }

    def _order_has_finished_product(self, order: Dict[str, Any]) -> bool:
        """
        Sprawdza czy zamówienie zawiera choć jeden produkt wykończony
        (olejowany / lakierowany / inny niż surowy).

        Reguła deadline'u jest na poziomie ZAMÓWIENIA: jeśli choć jedna
        pozycja nie jest surowa, całe zamówienie (łącznie z surowymi
        pozycjami) traktujemy jako wykończone i dajemy dłuższy termin.
        """
        try:
            from ..services.parser_service import ProductNameParser
            parser = ProductNameParser()
        except Exception as e:
            # Brak parsera — bezpieczny fallback: traktuj jak surowe (krótszy termin)
            logger.warning("Nie udało się zainicjalizować parsera przy ocenie wykończenia", extra={
                'error': str(e)
            })
            return False

        for product in order.get('products', []):
            if not isinstance(product, dict):
                continue
            name = (product.get('name') or '').strip()
            if not name:
                continue
            try:
                parsed = parser.parse_product_name(name)
            except Exception:
                # Nierozpoznana nazwa — nie traktujemy jako wykończona
                continue
            finish_type = parsed.get('finish_type')
            if finish_type and finish_type != 'surowe':
                return True

        return False

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

        # Wybór liczby dni: surowe zamówienie = 16, wykończone (choć 1 produkt) = 21.
        # Wartości konfigurowalne w panelu (z fallbackiem do defaultów przez config service).
        try:
            from .config_service import get_config_service
            config = get_config_service()
            if self._order_has_finished_product(order):
                deadline_days = int(config.get_config('DEADLINE_FINISHED_DAYS', 21))
            else:
                deadline_days = int(config.get_config('DEADLINE_DEFAULT_DAYS', 16))
        except Exception as e:
            logger.warning("Błąd odczytu konfiguracji deadline — fallback", extra={
                'error': str(e)
            })
            deadline_days = 21 if self._order_has_finished_product(order) else 16

        try:
            deadline_date = self._add_business_days(base_date, deadline_days)
        except Exception as e:
            deadline_date = self._add_business_days(date.today(), deadline_days)

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

        # Mapowanie sync_type na sync_source dla bazy danych
        sync_source_map = {
            'cron': 'baselinker_auto',
            'manual': 'manual_entry',
            'auto': 'baselinker_auto'
        }
        sync_source = sync_source_map.get(sync_type, 'manual_entry')

        baselinker_order_id = order['order_id']
        
        try:
            from ..services.id_generator import ProductIDGenerator
            from ..services.parser_service import get_parser_service
            from ..models import ProductionItem
            
            client_data = self.extract_client_data(order)
            deadline_date = self._calculate_deadline_date(order)

            # NOWA LOGIKA: liczymy pozycje, nie sztuki
            total_positions = len(products)

            id_result = ProductIDGenerator.generate_product_id_for_order(
                baselinker_order_id, total_positions
            )

            parser = get_parser_service()
            prepared_items = []

            for product_index, product in enumerate(products):
                try:
                    product_name = product.get('name', '')
                    quantity = self._coerce_quantity(product.get('quantity', 1))
                    order_product_id = product.get('order_product_id')

                    parsed_data = parser.parse_product_name(product_name)

                    if product_index >= len(id_result['product_ids']):
                        raise Exception(f"Brak ID dla pozycji {product_index}")

                    product_id = id_result['product_ids'][product_index]

                    # NOWA LOGIKA: jeden rekord z quantity
                    product_data = self._prepare_product_data_enhanced(
                        order=order,
                        product=product,
                        product_id=product_id,
                        id_result=id_result,
                        parsed_data=parsed_data,
                        client_data=client_data,
                        deadline_date=deadline_date,
                        order_product_id=order_product_id,
                        sequence_number=product_index + 1,
                        payment_date=payment_date,
                        sync_source=sync_source,
                        quantity=quantity
                    )

                    # Odfiltruj klucze pomocnicze (prefiks '_') — np. '_quote_detail' cache
                    product_data_clean = {k: v for k, v in product_data.items() if not k.startswith('_')}
                    production_item = self._create_production_product_from_data(product_data_clean)
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

    def _resolve_cut_to_size(self, product_data, order_data):
        """
        Pobiera cut_to_size z QuoteItemDetails dla danego produktu.
        Default TRUE gdy: brak matchu z wyceną, legacy quote bez pola, lub błąd.

        Niezależne od edge processing — działa dla każdego produktu.
        """
        baselinker_order_id = product_data.get('baselinker_order_id')

        detail = self._try_match_via_pdf(order_data, product_data)
        if not detail:
            detail = self._try_match_via_order_product_id(
                baselinker_order_id,
                product_data.get('baselinker_product_id')
            )
        if not detail:
            detail = self._try_match_via_quote_position(product_data, order_data)

        # Cache resolved detail for downstream consumers (np. _enrich_edge_data_from_quote)
        # — unika ponownego dopasowania (PDF fetch / DB lookup) na ten sam produkt.
        product_data['_quote_detail'] = detail

        if detail is not None:
            value = getattr(detail, 'cut_to_size', None)
            if value is None:
                product_data['cut_to_size'] = True
            else:
                product_data['cut_to_size'] = bool(value)
        else:
            product_data['cut_to_size'] = True

        logger.debug("Cut_to_size rozstrzygnięty",
                     extra={'baselinker_product_id': product_data.get('baselinker_product_id'),
                            'cut_to_size': product_data['cut_to_size'],
                            'matched_quote': detail is not None})

        return product_data

    def _enrich_edge_data_from_quote(self, product_data, order_data):
        """
        Kaskada wzbogacania danych z QuoteItemDetails.
        Zawsze próbuje znaleźć detail i kopiuje pola wizualne (shape_svg,
        lamella_direction). Pola edge'owe kopiuje tylko gdy parsed_edge_processing=True.
        Poziom 1: Metadane PDF → Poziom 2: order_product_id → Poziom 3: fallback SVG.
        """
        # Reużyj cache z _resolve_cut_to_size (jeśli było wywołane wcześniej)
        if '_quote_detail' in product_data:
            detail = product_data['_quote_detail']
        else:
            # Poziom 1: Metadane PDF
            detail = self._try_match_via_pdf(order_data, product_data)

            # Poziom 2: order_product_id
            if not detail:
                detail = self._try_match_via_order_product_id(
                    product_data.get('baselinker_order_id'),
                    product_data.get('baselinker_product_id')
                )

            # Poziom 2.5: pozycyjnie po quote_number + product_index
            # (fallback gdy baselinker_order_product_id w wycenie jest pusty)
            if not detail:
                detail = self._try_match_via_quote_position(product_data, order_data)

        if detail:
            self._apply_quote_detail_to_product_data(product_data, detail)
            logger.info("Wzbogacono dane z QuoteItemDetails",
                       extra={'detail_id': detail.id, 'source': 'quote',
                              'has_shape_svg': bool(detail.shape_svg),
                              'has_edge_processing': bool(product_data.get('parsed_edge_processing'))})
        else:
            # Poziom 3: Generuj SVG z parsera (tylko prostokąty z literkami)
            if product_data.get('parsed_edge_letters'):
                self._generate_fallback_svg(product_data)

        return product_data

    def _apply_quote_detail_to_product_data(self, product_data, detail):
        """
        Kopiuje pola wizualne z QuoteItemDetails do product_data.
        Pola kształtu/lameli kopiowane ZAWSZE; pola krawędzi tylko gdy produkt
        ma obróbkę krawędzi (parsed_edge_processing). Wydzielone, by ta sama
        logika działała w sync i w backfillu historycznych rekordów.
        """
        # Pola wizualne — kopiuj ZAWSZE gdy detail znaleziony
        if detail.shape_svg:
            product_data['shape_svg'] = detail.shape_svg
        if detail.shape:
            product_data['shape'] = detail.shape
        if detail.lamella_direction is not None:
            product_data['lamella_direction'] = detail.lamella_direction
        product_data['quote_item_detail_id'] = detail.id

        # Pola edge'owe — tylko gdy produkt ma obróbkę krawędzi
        if product_data.get('parsed_edge_processing'):
            if detail.edges_type:
                edge_type_map = {'round': 'zaokrąglenie', 'chamfer': 'fazowanie'}
                product_data['parsed_edge_type'] = edge_type_map.get(detail.edges_type, detail.edges_type)
            if detail.edges_r_value:
                product_data['parsed_edge_radius'] = detail.edges_r_value
            if detail.edges_angle_value:
                product_data['parsed_edge_angle'] = detail.edges_angle_value
            if detail.edges_config:
                product_data['parsed_edge_letters'] = [
                    e.get('letter') for e in detail.edges_config if e.get('letter')
                ]
            # Multi-group: jeśli advanced — zgrupuj edges_config po (type, radius, angle)
            if detail.edges_mode == 'advanced' and detail.edges_config:
                edge_type_map = {'round': 'zaokrąglenie', 'chamfer': 'fazowanie'}
                groups_dict = {}
                groups_order = []
                for entry in detail.edges_config:
                    if not entry or not entry.get('letter'):
                        continue
                    e_type_raw = entry.get('type')
                    if not e_type_raw:
                        continue
                    e_type = edge_type_map.get(e_type_raw, e_type_raw)
                    e_radius = entry.get('r_value') or entry.get('radius')
                    e_angle = entry.get('angle_value') or entry.get('angle')
                    key = (e_type, e_radius, e_angle)
                    if key not in groups_dict:
                        groups_dict[key] = {
                            'type': e_type,
                            'radius': e_radius,
                            'angle': e_angle,
                            'letters': [],
                        }
                        groups_order.append(key)
                    groups_dict[key]['letters'].append(entry['letter'])
                if groups_order:
                    product_data['parsed_edges_groups'] = [groups_dict[k] for k in groups_order]
                    product_data['parsed_edge_type'] = 'mixed' if len(groups_order) > 1 else groups_dict[groups_order[0]]['type']
                    if len(groups_order) > 1:
                        product_data['parsed_edge_radius'] = None
                        product_data['parsed_edge_angle'] = None
            elif detail.edges_config:
                # Basic mode — pojedyncza grupa wynika z edges_type/r_value/angle_value
                if detail.edges_type and detail.edges_r_value:
                    edge_type_map = {'round': 'zaokrąglenie', 'chamfer': 'fazowanie'}
                    product_data['parsed_edges_groups'] = [{
                        'type': edge_type_map.get(detail.edges_type, detail.edges_type),
                        'radius': detail.edges_r_value,
                        'angle': detail.edges_angle_value,
                        'letters': [e.get('letter') for e in detail.edges_config if e.get('letter')],
                    }]
            if detail.edges_svg:
                product_data['edge_svg'] = detail.edges_svg

        return product_data

    def _try_match_via_pdf(self, order_data, product_data):
        """Próbuje powiązać przez metadane PDF z załącznika zamówienia."""
        import io
        import json

        try:
            from modules.calculator.models import QuoteItemDetails

            # Szukaj linku do PDF specyfikacji w custom_extra_fields
            custom_fields = order_data.get('custom_extra_fields', {})
            pdf_url = None
            for field_id, value in custom_fields.items():
                if isinstance(value, str) and value.endswith('.pdf'):
                    pdf_url = value
                    break

            if not pdf_url:
                return None

            import requests
            from pypdf import PdfReader

            response = requests.get(pdf_url, timeout=15)
            if response.status_code != 200:
                return None

            reader = PdfReader(io.BytesIO(response.content))
            meta = reader.metadata
            woodpower_meta = meta.get('/WoodPowerMeta') if meta else None

            if not woodpower_meta:
                return None

            meta_data = json.loads(woodpower_meta)
            items = meta_data.get('items', [])

            # Znajdź detail_id dla tego produktu (po pozycji)
            sequence = product_data.get('product_sequence_in_order', 1)
            for item in items:
                if item.get('position') == sequence:
                    detail_id = item.get('detail_id')
                    if detail_id:
                        return QuoteItemDetails.query.get(detail_id)

        except Exception as e:
            logger.warning("Błąd odczytu metadanych PDF", extra={'error': str(e)})

        return None

    def _try_match_via_order_product_id(self, baselinker_order_id, baselinker_product_id):
        """Próbuje powiązać przez order_product_id."""
        if not baselinker_product_id:
            return None

        try:
            from modules.calculator.models import QuoteItemDetails
            from modules.calculator.models import Quote

            # Znajdź quote z tym baselinker_order_id
            quote = Quote.query.filter_by(
                base_linker_order_id=str(baselinker_order_id)
            ).first()

            if not quote:
                return None

            # Szukaj QuoteItemDetails z tym order_product_id
            detail = QuoteItemDetails.query.filter_by(
                quote_id=quote.id,
                baselinker_order_product_id=int(baselinker_product_id)
            ).first()

            return detail

        except Exception as e:
            logger.warning("Błąd matchowania order_product_id", extra={'error': str(e)})

        return None

    def _try_match_via_quote_position(self, product_data, order_data):
        """
        Fallback pozycyjny: dopasowanie detalu wyceny po quote_number + pozycji.
        Używany gdy PDF i baselinker_order_product_id zawiodą (typowo wycena
        bez wypełnionego baselinker_order_product_id).

        Bezpieczny tylko przy mapowaniu 1:1 — liczba detali wyceny musi być
        równa liczbie pozycji w zamówieniu BaseLinker. Dopasowanie po
        product_index detalu == product_sequence_in_order produktu.
        """
        quote_number = product_data.get('quote_number')
        sequence = product_data.get('product_sequence_in_order')
        if not quote_number or not sequence:
            return None

        try:
            from modules.calculator.models import QuoteItemDetails, Quote

            quote = Quote.query.filter_by(quote_number=quote_number).first()
            if not quote:
                return None

            details = QuoteItemDetails.query.filter_by(quote_id=quote.id)\
                .order_by(QuoteItemDetails.product_index).all()
            if not details:
                return None

            # Guard liczności — pozycyjny match tylko gdy 1:1 z pozycjami zamówienia
            order_products_count = len(order_data.get('products') or [])
            if order_products_count and order_products_count != len(details):
                logger.debug("Pomijam match pozycyjny — różna liczba pozycji",
                             extra={'quote_number': quote_number,
                                    'order_products': order_products_count,
                                    'quote_details': len(details)})
                return None

            for d in details:
                if d.product_index == sequence:
                    logger.info("Dopasowano detal wyceny pozycyjnie",
                                extra={'quote_number': quote_number,
                                       'product_index': sequence,
                                       'detail_id': d.id})
                    return d

        except Exception as e:
            logger.warning("Błąd matchowania pozycyjnego", extra={'error': str(e)})

        return None

    def _generate_fallback_svg(self, product_data):
        """Generuje SVG prostokąta z parsera (fallback dla zamówień sklepowych)."""
        try:
            from modules.production.services.edge_svg_generator import EdgeSvgGenerator

            length = float(product_data.get('parsed_length_cm') or 0)
            width = float(product_data.get('parsed_width_cm') or 0)
            thickness = float(product_data.get('parsed_thickness_cm') or 0)

            if length > 0 and width > 0 and thickness > 0:
                generator = EdgeSvgGenerator()
                product_data['edge_svg'] = generator.generate(
                    length, width, thickness,
                    product_data.get('parsed_edge_letters', [])
                )
        except Exception as e:
            logger.warning("Błąd generowania fallback SVG", extra={'error': str(e)})

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