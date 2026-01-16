# modules/reports/service.py
"""
Serwis do komunikacji z Baselinker API dla modułu Reports
"""

import requests
import json
import sys
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from flask import current_app
from extensions import db
from .models import BaselinkerReportOrder, ReportsSyncLog
from .utils import PostcodeToStateMapper
from .parser import ProductNameParser
from modules.logging import get_structured_logger
from decimal import Decimal

# Inicjalizacja loggera
reports_logger = get_structured_logger('reports.routers')
reports_logger.info("✅ reports_logger zainicjowany poprawnie w service.py")

class BaselinkerReportsService:
    """
    Serwis do synchronizacji danych z Baselinker dla modułu Reports
    """
    
    def __init__(self):
        self.api_key = current_app.config.get('API_BASELINKER', {}).get('api_key')
        self.endpoint = current_app.config.get('API_BASELINKER', {}).get('endpoint')
        self.logger = get_structured_logger('reports.service')
        self.parser = ProductNameParser()
        
        # Mapowanie statusów Baselinker
        self.status_map = {
            155824: "Nowe - opłacone",
            105112: "Nowe - nieopłacone",
            138619: "W produkcji - surowe",
            148830: "W produkcji - lakierowanie",
            148831: "W produkcji - bejcowanie", 
            148832: "W produkcji - olejowanie",
            332355: "W produkcji - suszenie usługowe",
            138620: "Produkcja zakończona",
            138623: "Zamówienie spakowane",
            105113: "Paczka zgłoszona do wysyłki", 
            105114: "Wysłane - kurier",
            138624: "Dostarczona - kurier",
            149763: "Wysłane - transport WoodPower",
            149777: "Czeka na odbiór osobisty",
            149778: "Dostarczona - trans. WoodPower",
            149779: "Odebrane",
            316636: "Reklamacja",
            138625: "Zamówienie anulowane"
        }

        # NOWE właściwości dla obsługi objętości
        self.volume_fixes = {}  # {product_key: {'volume': X, 'wood_species': Y, ...}}

    def _is_service_product(self, product_name: str) -> bool:
        """
        Rozpoznaje czy produkt to usługa na podstawie nazwy
        ROZSZERZONE: dodano obsługę suszenia usługowego

        Args:
            product_name (str): Nazwa produktu z Baselinker
    
        Returns:
            bool: True jeśli produkt to usługa, False w przeciwnym razie
        """
        if not product_name:
            return False

        service_keywords = [
            'usługa', 'usluga', 'usługi', 'uslugi', 
            'klejenie', 'klejenia', 'oklejanie', 
            'przycięcie', 'montaż',
            # NOWE: suszenie usługowe
            'suszenie', 'suszenia', 'wysuszenie', 'wysuszenia',
            'usługa suszenia', 'suszenie usługowe'
        ]
        product_name_lower = product_name.lower()

        is_service = any(keyword in product_name_lower for keyword in service_keywords)

        if is_service:
            self.logger.debug("Rozpoznano usługę", 
                             product_name=product_name,
                             matched_keywords=[kw for kw in service_keywords if kw in product_name_lower])

        return is_service

    def set_volume_fixes(self, volume_fixes_dict):
        """
        NOWA METODA: Ustawia poprawki objętości dla produktów.
        
        Args:
            volume_fixes_dict (dict): Słownik z poprawkami w formacie:
                {product_key: {'volume': float, 'wood_species': str, ...}}
        """
        self.volume_fixes = volume_fixes_dict or {}
        
    def clear_volume_fixes(self):
        """NOWA METODA: Czyści poprawki objętości."""
        self.volume_fixes = {}

    def generate_product_key(self, order_id, product, product_index=None):
        """
        ✅ ZSYNCHRONIZOWANA METODA: Preferuje product_index gdy jest podany
        """
        order_product_id = product.get('order_product_id')
        product_id_raw = product.get('product_id')

        # ✅ PRIORYTET 1: product_index z prefiksem "idx_" (gdy podany)
        if product_index is not None:
            return f"{order_id}_idx_{product_index}"

        # PRIORYTET 2: order_product_id (najbardziej unikalne)
        if order_product_id and str(order_product_id).strip():
            return f"{order_id}_{order_product_id}"

        # PRIORYTET 3: product_id (jeśli nie jest pusty)
        if product_id_raw and str(product_id_raw).strip() and str(product_id_raw) != "":
            return f"{order_id}_{product_id_raw}"

        # OSTATECZNOŚĆ: 'unknown' (może powodować konflikty)
        return f"{order_id}_unknown"
        
    def get_volume_fix(self, product_key):
        """Pobiera poprawki objętości dla konkretnego produktu"""
        if not hasattr(self, 'volume_fixes'):
            return None
        return self.volume_fixes.get(product_key)
        
    def get_volume_fix_attribute(self, product_key, attribute):
        """Pobiera konkretny atrybut z poprawek objętości"""
        fix = self.get_volume_fix(product_key)
        return fix.get(attribute) if fix else None
    
    def get_existing_order_ids(self, order_ids):
        """Zwraca listę ID zamówień które już istnieją w bazie"""
        existing = db.session.query(BaselinkerReportOrder.baselinker_order_id).filter(
            BaselinkerReportOrder.baselinker_order_id.in_(order_ids)
        ).distinct().all()
        return [order.baselinker_order_id for order in existing]


    def calculate_volume_from_dimensions(self, length_cm, width_cm, thickness_cm, quantity):
        """
        ULEPSZONA METODA: Oblicza objętość z wymiarów z lepszą obsługą błędów.
        
        Args:
            length_cm (float): Długość w cm
            width_cm (float): Szerokość w cm  
            thickness_cm (float): Grubość w cm
            quantity (int): Ilość sztuk
            
        Returns:
            float: Objętość w m³
        """
        try:
            length_cm = float(length_cm or 0)
            width_cm = float(width_cm or 0)
            thickness_cm = float(thickness_cm or 0)
            quantity = int(quantity or 0)
            
            if length_cm <= 0 or width_cm <= 0 or thickness_cm <= 0 or quantity <= 0:
                return 0.0
                
            # Konwersja z cm na m i obliczenie objętości
            length_m = length_cm / 100
            width_m = width_cm / 100
            thickness_m = thickness_cm / 100
            
            volume_per_piece = length_m * width_m * thickness_m
            total_volume = volume_per_piece * quantity
            
            return round(total_volume, 4)
            
        except (ValueError, TypeError) as e:
            reports_logger.warning(f"Błąd obliczania objętości z wymiarów: {e}")
            return 0.0

    def extract_product_attributes_from_name(self, product_name):
        """
        NOWA METODA: Wyodrębnia atrybuty produktu z nazwy (gatunek, technologia, klasa).
        
        Args:
            product_name (str): Nazwa produktu
            
        Returns:
            dict: Słownik z atrybutami {'wood_species': str, 'technology': str, 'wood_class': str}
        """
        # Importuj funkcje z routera (lub przenieś je do utils)
        from .routers import (
            extract_wood_species_from_product_name,
            extract_technology_from_product_name, 
            extract_wood_class_from_product_name
        )
        
        return {
            'wood_species': extract_wood_species_from_product_name(product_name),
            'technology': extract_technology_from_product_name(product_name),
            'wood_class': extract_wood_class_from_product_name(product_name)
        }

    def prepare_order_record_data_with_volume_analysis(self, order_data, product_data, product_index=None):
        """
        ULEPSZONA METODA: Przygotowuje dane rekordu zamówienia z analizą objętości.
        UŻYWA ISTNIEJĄCEJ LOGIKI z _convert_order_to_records zamiast duplikować kod.

        Args:
            order_data (dict): Dane zamówienia z Baselinker
            product_data (dict): Dane produktu z zamówienia
            product_index (int): Indeks produktu w zamówieniu (NOWY PARAMETR)

        Returns:
            dict: Przygotowane dane do zapisu w bazie
        """
        try:
            # ✅ UŻYJ ISTNIEJĄCEJ LOGIKI: Stwórz tymczasowe zamówienie z jednym produktem
            temp_order = {**order_data, 'products': [product_data]}

            # ✅ WYKORZYSTAJ _convert_order_to_records (ale nie zapisuj do bazy)
            records = self._convert_order_to_records(temp_order)

            if not records:
                raise Exception("Nie udało się przetworzyć zamówienia")
    
            # Weź pierwszy (i jedyny) rekord
            record = records[0]

            # ✅ SPRAWDŹ CZY TO USŁUGA PRZED DALSZYM PRZETWARZANIEM
            product_name = product_data.get('name', '')
            if self._is_service_product(product_name):
                # Dla usług: użyj danych z _convert_order_to_records bez modyfikacji
                self.logger.debug("Przetwarzanie usługi - używam danych z _convert_order_to_records",
                                product_name=product_name,
                                value_net=record.value_net)
                return self._convert_record_to_dict(record, order_data)

            # ✅ KONWERTUJ BaselinkerReportOrder z powrotem na słownik (TYLKO dla produktów fizycznych)
            record_data = {
                # Podstawowe pola
                'date_created': record.date_created,
                'baselinker_order_id': record.baselinker_order_id,
                'internal_order_number': record.internal_order_number,
                'customer_name': record.customer_name,
                'delivery_postcode': record.delivery_postcode,
                'delivery_city': record.delivery_city,
                'delivery_address': record.delivery_address,
                'delivery_state': record.delivery_state,
                'phone': record.phone,
                'caretaker': record.caretaker,
                'delivery_method': record.delivery_method,
                'order_source': record.order_source,
    
                # Dane produktu - ✅ POPRAWKA: Użyj group_type z record (już ustawione przez _convert_order_to_records)
                'group_type': record.group_type,  # To już zawiera 'usługa' lub 'towar'
                'product_type': record.product_type,
                'finish_state': record.finish_state,
                'raw_product_name': record.raw_product_name,
                'quantity': record.quantity,
    
                # Wymiary (z parsera)
                'length_cm': record.length_cm,
                'width_cm': record.width_cm,
                'thickness_cm': record.thickness_cm,
    
                # Ceny i wartości
                'price_gross': record.price_gross,
                'price_net': record.price_net,
                'value_gross': record.value_gross,
                'value_net': record.value_net,
                'price_type': record.price_type,
                'original_amount_from_baselinker': record.original_amount_from_baselinker,
                'payment_method': record.payment_method,
                'paid_amount_net': record.paid_amount_net,
                'balance_due': record.balance_due,
    
                # ✅ DODAJ ATRYBUTY DREWNA
                'wood_species': record.wood_species,
                'technology': record.technology,
                'wood_class': record.wood_class,

                # Objętości (z istniejącej logiki)
                'volume_per_piece': record.volume_per_piece,
                'total_volume': record.total_volume,
                'price_per_m3': record.price_per_m3,
    
                # Pozostałe pola
                'current_status': record.current_status,
                'delivery_cost': record.delivery_cost,
                'baselinker_status_id': record.baselinker_status_id,
                'email': record.email,
            }

            custom_fields = order_data.get('custom_extra_fields', {})
            price_type_from_api = custom_fields.get('106169', '').strip()
            payment_done = order_data.get('payment_done', 0)
            paid_amount_net = self._calculate_paid_amount_net(payment_done, price_type_from_api)

            # DODAJ price_type do record_data
            if price_type_from_api.lower() == 'netto':
                record_data['price_type'] = 'netto'
            elif price_type_from_api.lower() == 'brutto':
                record_data['price_type'] = 'brutto'
            else:
                record_data['price_type'] = ''  # Domyślnie puste

            # DODAJ DEBUG:
            self.logger.debug("Price type mapping",
                              order_id=order_data.get('order_id'),
                              price_type_from_api=price_type_from_api,
                              final_price_type=record_data['price_type'])

            record_data['paid_amount_net'] = paid_amount_net
            record_data['payment_done'] = payment_done

            # ✅ POPRAWKA: Sprawdź czy to usługa PRZED dodawaniem analizy objętości
            product_name = product_data.get('name', '')
            is_service = self._is_service_product(product_name)
    
            if is_service:
                # ✅ DLA USŁUG: Pomiń analizę objętości - usługi nie mają objętości ani atrybutów drewna
                self.logger.debug("Przetwarzanie usługi - pomijam analizę objętości",
                                 product_name=product_name,
                                 group_type=record_data.get('group_type'))
                return record_data

            # ✅ OBLICZ ŁĄCZNĄ WARTOŚĆ NETTO TYLKO PRODUKTÓW FIZYCZNYCH (bez usług)
            total_products_value_net = 0
            for prod in order_data.get('products', []):
                prod_name = prod.get('name', '')
                if not self._is_service_product(prod_name):
                    # Oblicz wartość netto tego produktu
                    orig_price = float(prod.get('price_brutto', 0))
                    custom_fields = order_data.get('custom_extra_fields', {})
                    price_type_api = custom_fields.get('106169', '').strip()
            
                    if price_type_api.lower() == 'netto':
                        prod_price_net = orig_price
                    elif price_type_api.lower() == 'brutto':
                        prod_price_net = orig_price / 1.23
                    else:
                        prod_price_net = orig_price / 1.23
            
                    prod_quantity = int(prod.get('quantity', 1))
                    total_products_value_net += prod_price_net * prod_quantity
    
            # ✅ NADPISZ order_amount_net na łączną wartość produktów fizycznych
            record_data['order_amount_net'] = total_products_value_net
    
            self.logger.debug("Obliczono order_amount_net dla zamówienia",
                              order_id=order_data.get('order_id'),
                              total_products_value_net=total_products_value_net,
                              current_product=product_data.get('name'))

            # ✅ TYLKO DLA PRODUKTÓW FIZYCZNYCH: DODAJ ANALIZĘ OBJĘTOŚCI
            # ✅ UŻYJ NOWEJ METODY GENEROWANIA KLUCZY
            product_key = self.generate_product_key(order_data.get('order_id'), product_data, product_index)

            # ✅ DODAJ DEBUG GENEROWANIA KLUCZA
            # ✅ SZCZEGÓŁOWY DEBUG GENEROWANIA KLUCZA
            order_product_id_raw = product_data.get('order_product_id')
            product_id_raw = product_data.get('product_id')

            self.logger.info("🔑 SZCZEGÓŁOWY DEBUG GENEROWANIA KLUCZA:")
            self.logger.info(f"   📦 order_id: {order_data.get('order_id')}")
            self.logger.info(f"   🏷️  product_name: {product_data.get('name', 'BRAK')}")
            self.logger.info(f"   🆔 order_product_id: '{order_product_id_raw}' (type: {type(order_product_id_raw)})")
            self.logger.info(f"   🔢 product_id: '{product_id_raw}' (type: {type(product_id_raw)})")
            self.logger.info(f"   📍 product_index: {product_index}")
            self.logger.info(f"   ✅ order_product_id not empty: {order_product_id_raw and str(order_product_id_raw).strip()}")
            self.logger.info(f"   ✅ product_id not empty: {product_id_raw and str(product_id_raw).strip() and str(product_id_raw) != ''}")

            product_key = self.generate_product_key(order_data.get('order_id'), product_data, product_index)

            self.logger.info(f"   🎯 WYGENEROWANY KLUCZ: {product_key}")

            # Przeprowadź analizę produktu
            from .routers import analyze_product_for_volume_and_attributes
            analysis = analyze_product_for_volume_and_attributes(product_name)

            # Nadpisz objętość według nowej analizy
            if analysis['analysis_type'] == 'volume_only':
                # ✅ POPRAWKA: objętość z nazwy to już total_volume całej pozycji
                total_volume = float(analysis.get('volume', 0))
                quantity = record_data.get('quantity', 1)

                record_data['total_volume'] = total_volume  # NIE MNÓŻ!
                record_data['volume_per_piece'] = total_volume / quantity  # PODZIEL!
    
                # Wyczyść wymiary (bo ich nie ma)
                record_data['length_cm'] = None
                record_data['width_cm'] = None
                record_data['thickness_cm'] = None
    
            elif analysis['analysis_type'] == 'manual_input_needed':
                # Użyj ręcznie wprowadzonych danych
                volume_fix = self.get_volume_fix(product_key)
            
                # ✅ DODAJ SZCZEGÓŁOWY DEBUG
                self.logger.info("🔍 MANUAL_INPUT_NEEDED DEBUG:")
                self.logger.info(f"   📦 Product key: {product_key}")
                self.logger.info(f"   🔍 Volume fix found: {volume_fix is not None}")
                self.logger.info(f"   📊 Volume fix data: {volume_fix}")
                self.logger.info(f"   🔢 Quantity: {record_data.get('quantity', 1)}")
            
                if volume_fix and volume_fix.get('volume'):
                    total_volume = float(volume_fix['volume'])
                    quantity = record_data.get('quantity', 1)

                    record_data['total_volume'] = total_volume  # NIE MNÓŻ!
                    record_data['volume_per_piece'] = total_volume / quantity  # PODZIEL!
                
                    # ✅ DODAJ DEBUG PO USTAWIENIU
                    self.logger.info("🔍 PO USTAWIENIU OBJĘTOŚCI:")
                    self.logger.info(f"   📊 record_data['total_volume']: {record_data.get('total_volume')}")
                    self.logger.info(f"   📦 record_data['volume_per_piece']: {record_data.get('volume_per_piece')}")

                    # Wyczyść wymiary (bo ich nie ma)
                    record_data['length_cm'] = None
                    record_data['width_cm'] = None  
                    record_data['thickness_cm'] = None
                else:
                    # ✅ DODAJ DEBUG BRAKU DANYCH
                    self.logger.warning("⚠️ BRAK VOLUME_FIX - ustawiam objętość na 0")
                    record_data['total_volume'] = 0
                    record_data['volume_per_piece'] = 0
        
            # ✅ DODAJ SZCZEGÓŁOWY DEBUG PRZED POBIERANIEM ATRYBUTÓW
            volume_fix = self.get_volume_fix(product_key)
            self.logger.debug("Volume fix lookup",
                              product_key=product_key,
                              volume_fix_found=volume_fix is not None,
                              volume_fix_data=volume_fix,
                              available_fixes=list(self.volume_fixes.keys()) if hasattr(self, 'volume_fixes') else [])

            # ✅ TYLKO DLA PRODUKTÓW FIZYCZNYCH: Dodaj atrybuty z ręcznego wprowadzenia lub analizy
            # (dla usług te wartości pozostaną None jak ustawione w _convert_order_to_records)
            # Ręczne dane mają pierwszeństwo przed auto-analizą nazwy
            wood_species = self.get_volume_fix_attribute(product_key, 'wood_species') or analysis.get('wood_species')
            technology = self.get_volume_fix_attribute(product_key, 'technology') or analysis.get('technology')
            wood_class = self.get_volume_fix_attribute(product_key, 'wood_class') or analysis.get('wood_class')

            # ✅ NADPISZ TYLKO JEŚLI MAMY NOWE WARTOŚCI (nie nadpisuj None na None)
            if wood_species:
                record_data['wood_species'] = wood_species
            if technology:
                record_data['technology'] = technology  
            if wood_class:
                record_data['wood_class'] = wood_class

            # DODAJ DEBUG REZULTATÓW
            self.logger.debug("Attributes assignment",
                              product_key=product_key,
                              wood_species=wood_species,
                              technology=technology,
                              wood_class=wood_class,
                              from_analysis_wood_species=analysis.get('wood_species'),
                              from_analysis_technology=analysis.get('technology'),
                              from_analysis_wood_class=analysis.get('wood_class'),
                              from_fixes_wood_species=self.get_volume_fix_attribute(product_key, 'wood_species'),
                              from_fixes_technology=self.get_volume_fix_attribute(product_key, 'technology'),
                              from_fixes_wood_class=self.get_volume_fix_attribute(product_key, 'wood_class'))

            # ✅ NOWE: Dodaj avg_order_price_per_m3 do record_data
            # Dla pojedynczych produktów będzie to cena tego produktu
            record_data['avg_order_price_per_m3'] = record_data.get('price_per_m3', 0.0)

            return record_data

        except Exception as e:
            self.logger.error("Błąd przygotowywania danych z analizą objętości",
                             order_id=order_data.get('order_id'),
                             product_name=product_data.get('name'),
                             error=str(e))
            raise

    def _convert_record_to_dict(self, record, order_data):
        """
        POMOCNICZA METODA: Konwertuje obiekt BaselinkerReportOrder na słownik
        """
        return {
            'date_created': record.date_created,
            'baselinker_order_id': record.baselinker_order_id,
            'internal_order_number': record.internal_order_number,
            'customer_name': record.customer_name,
            'delivery_postcode': record.delivery_postcode,
            'delivery_city': record.delivery_city,
            'delivery_address': record.delivery_address,
            'delivery_state': record.delivery_state,
            'phone': record.phone,
            'caretaker': record.caretaker,
            'delivery_method': record.delivery_method,
            'order_source': record.order_source,
            'group_type': record.group_type,
            'product_type': record.product_type,
            'finish_state': record.finish_state,
            'raw_product_name': record.raw_product_name,
            'quantity': record.quantity,
            'length_cm': record.length_cm,
            'width_cm': record.width_cm,
            'thickness_cm': record.thickness_cm,
            'price_gross': record.price_gross,
            'price_net': record.price_net,
            'value_gross': record.value_gross,
            'value_net': record.value_net,  # ✅ KLUCZOWE: To będzie poprawna wartość dla usług
            'price_type': record.price_type,
            'original_amount_from_baselinker': record.original_amount_from_baselinker,
            'payment_method': record.payment_method,
            'paid_amount_net': record.paid_amount_net,
            'balance_due': record.balance_due,
            'wood_species': record.wood_species,
            'technology': record.technology,
            'wood_class': record.wood_class,
            'volume_per_piece': record.volume_per_piece,
            'total_volume': record.total_volume,
            'price_per_m3': record.price_per_m3,
            'current_status': record.current_status,
            'delivery_cost': record.delivery_cost,
            'baselinker_status_id': record.baselinker_status_id,
            'email': record.email,
            'order_amount_net': self._calculate_order_amount_net_for_record(order_data, record),
            'total_m3': record.total_m3
        }

    def _calculate_order_amount_net_for_record(self, order_data, current_record):
        """
        Oblicza poprawną wartość order_amount_net dla danego rekordu
        (aby każdy rekord miał tę samą wartość order_amount_net = suma wszystkich produktów)
        """
        total_order_value_net = 0
    
        for prod in order_data.get('products', []):
            prod_name = prod.get('name', '')
            orig_price = float(prod.get('price_brutto', 0))
            price_type_api = order_data.get('custom_extra_fields', {}).get('106169', '').strip()
        
            # Rozróżnij typ ceny
            if price_type_api.lower() == 'netto':
                prod_price_net = orig_price
            elif price_type_api.lower() == 'brutto':
                prod_price_net = orig_price / 1.23
            else:
                prod_price_net = orig_price / 1.23
        
            prod_quantity = int(prod.get('quantity', 1))
            total_order_value_net += prod_price_net * prod_quantity
    
        return total_order_value_net

    def get_single_order_from_baselinker(self, order_id):
        """
        NOWA METODA: Pobiera pojedyncze zamówienie z Baselinker.
        
        Args:
            order_id (int): ID zamówienia
            
        Returns:
            dict or None: Dane zamówienia lub None w przypadku błędu
        """
        try:
            # Wykorzystaj istniejącą metodę fetch_orders_from_baselinker
            # ale z filtrem dla konkretnego zamówienia
            date_from = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            date_to = datetime.now().strftime('%Y-%m-%d')
            
            # Pobierz wszystkie zamówienia i znajdź konkretne
            result = self.fetch_orders_from_baselinker(date_from, date_to)
            
            if not result.get('success'):
                return None
                
            orders = result.get('orders', [])
            target_order = None
            
            for order in orders:
                if order.get('order_id') == order_id:
                    target_order = order
                    break
                    
            return target_order
            
        except Exception as e:
            reports_logger.error(f"Błąd pobierania zamówienia {order_id}: {e}")
            return None

    def save_order_record(self, record_data):
        """
        ULEPSZONA METODA: Zapisuje rekord zamówienia do bazy z obsługą objętości.
    
        Args:
            record_data (dict): Dane rekordu do zapisu
        
        Returns:
            BaselinkerReportOrder: Zapisany rekord
        """
        try:
            # ✅ DODAJ DEBUG PRZED TWORZENIEM REKORDU
            volume_per_piece_input = record_data.get('volume_per_piece')
            total_volume_input = record_data.get('total_volume')
        
            # Utwórz nowy rekord
            record = BaselinkerReportOrder()
        
            # Podstawowe pola
            record.date_created = record_data.get('date_created')
            record.baselinker_order_id = record_data.get('baselinker_order_id')
            record.internal_order_number = record_data.get('internal_order_number')
            record.customer_name = record_data.get('customer_name')
            record.delivery_postcode = record_data.get('delivery_postcode')
            record.delivery_city = record_data.get('delivery_city')
            record.delivery_address = record_data.get('delivery_address')
            record.delivery_state = record_data.get('delivery_state')
            record.phone = record_data.get('phone')
            record.caretaker = record_data.get('caretaker')
            record.delivery_method = record_data.get('delivery_method')
            record.order_source = record_data.get('order_source')
        
            # Dane produktu
            record.group_type = record_data.get('group_type')
            record.product_type = record_data.get('product_type')
            record.finish_state = record_data.get('finish_state')
        
            # NOWE: Atrybuty z analizy objętości
            record.wood_species = record_data.get('wood_species')
            record.technology = record_data.get('technology')
            record.wood_class = record_data.get('wood_class')
        
            # Wymiary (mogą być None dla produktów z objętością)
            record.length_cm = record_data.get('length_cm')
            record.width_cm = record_data.get('width_cm')
            record.thickness_cm = record_data.get('thickness_cm')
            record.quantity = record_data.get('quantity')
        
            # Ceny i wartości
            record.price_gross = record_data.get('price_gross')
            record.price_net = record_data.get('price_net')
            record.value_gross = record_data.get('value_gross')  
            record.value_net = record_data.get('value_net')
        
            # ✅ WAŻNE: Objętości - ustaw PRZED calculate_fields()
            record.volume_per_piece = record_data.get('volume_per_piece')
            record.total_volume = record_data.get('total_volume')  # To trafia do kolumny używanej w statystykach
            record.price_per_m3 = record_data.get('price_per_m3')
            record.avg_order_price_per_m3 = record_data.get('avg_order_price_per_m3', 0.0)
        
            # Pozostałe pola
            record.realization_date = record_data.get('realization_date')
            record.current_status = record_data.get('current_status')
            record.delivery_cost = record_data.get('delivery_cost')
            record.payment_method = record_data.get('payment_method')
            record.paid_amount_net = record_data.get('paid_amount_net', 0)
            record.balance_due = record_data.get('balance_due')
            record.production_volume = record_data.get('production_volume', 0)
            record.production_value_net = record_data.get('production_value_net', 0)
            record.ready_pickup_volume = record_data.get('ready_pickup_volume', 0)
            record.ready_pickup_value_net = record_data.get('ready_pickup_value_net', 0)
        
            # Pola techniczne
            record.baselinker_status_id = record_data.get('baselinker_status_id')
            record.raw_product_name = record_data.get('raw_product_name')
            record.email = record_data.get('email')
        
            # Oblicz total_m3 na poziomie zamówienia
            record.total_m3 = record_data.get('total_volume', 0)
            record.order_amount_net = record_data.get('order_amount_net', 0)
        
            # ✅ OBLICZ automatycznie wszystkie pola (w tym datę realizacji)
            # UWAGA: Ta metoda może nadpisać objętości!
            record.calculate_fields()

            # ✅ NOWE: Ustaw avg_order_price_per_m3 (metoda calculate_fields może to ustawić już poprawnie)
            # Ale sprawdź czy jest potrzebne dodatkowe ustawienie
            if not hasattr(record, 'avg_order_price_per_m3') or record.avg_order_price_per_m3 is None:
                record.avg_order_price_per_m3 = record.price_per_m3 if record.price_per_m3 else 0.0

            # Zapisz do bazy
            db.session.add(record)
            db.session.commit()

            return record
        
        except Exception as e:
            db.session.rollback()
            reports_logger.error(f"Błąd zapisu rekordu zamówienia: {e}")
            raise

    def _create_order_record(self, order: Dict, product: Dict, parsed_product: Dict, 
                       total_m3_all_products: float, total_order_value_net: float) -> BaselinkerReportOrder:
        """
        Tworzy rekord zamówienia z automatycznym uzupełnianiem województwa
        """
        try:
            # Pobierz dane adresowe
            postcode = order.get('delivery_postcode', '').strip()
            current_state = order.get('delivery_state', '').strip()
        
            # NOWA LOGIKA: Automatyczne uzupełnianie województwa zgodnie z wymaganiami
            final_state = self._auto_fill_state_for_order(postcode, current_state)
            
            # NOWE: Pobierz typ ceny z custom_extra_fields
            custom_fields = order.get('custom_extra_fields', {})
            price_type_from_api = custom_fields.get('106169', '').strip()
            
            # Pobierz opiekuna z custom_extra_fields (pole 105623)
            caretaker_name = custom_fields.get('105623') or order.get('user_comments') or "Brak danych"
        
            # Oblicz wartości produktu z uwzględnieniem typu ceny
            quantity = product.get('quantity', 1)
            original_price_from_baselinker = safe_float_convert(product.get('price_brutto', 0))
            
            # POPRAWIONA LOGIKA: Rozróżnianie typu ceny
            if price_type_from_api == 'netto':
                # PRZYPADEK 1: Zamówienie ma oznaczenie "Netto"
                # Kwota z Baselinker jest rzeczywiście NETTO
                price_net = original_price_from_baselinker
                price_gross = price_net * 1.23
                price_type_to_save = 'netto'
            elif price_type_from_api == 'brutto':
                # PRZYPADEK 2: Zamówienie ma oznaczenie "Brutto"
                # Kwota z Baselinker jest rzeczywiście BRUTTO
                price_gross = original_price_from_baselinker
                price_net = price_gross / 1.23
                price_type_to_save = 'brutto'
            else:
                # PRZYPADEK 3: Zamówienie bez oznaczenia (domyślnie BRUTTO)
                price_gross = original_price_from_baselinker
                price_net = price_gross / 1.23
                price_type_to_save = ''
                
            # Oblicz pozostałe wartości
            value_gross = price_gross * quantity
            value_net = price_net * quantity
            volume_per_piece = parsed_product.get('volume_per_piece') or Decimal('0')
            total_volume = float(volume_per_piece) * quantity
            price_per_m3 = (price_net / float(volume_per_piece)) if volume_per_piece > 0 else 0
        
            record = BaselinkerReportOrder(
                # Dane zamówienia
                date_created=datetime.strptime(order['date_add'], '%Y-%m-%d %H:%M:%S').date(),
                total_m3=total_m3_all_products,
                order_amount_net=total_order_value_net,
                baselinker_order_id=order.get('order_id'),
                internal_order_number=order.get('extra_field_1'),
                customer_name=order.get('delivery_fullname'),
                delivery_postcode=postcode,
                delivery_city=order.get('delivery_city'),
                delivery_address=order.get('delivery_address'),
                delivery_state=final_state,  # ZMIANA: Użyj przetworzonego województwa
                phone=order.get('phone'),
                caretaker=caretaker_name,  # ZMIANA: Użyj opiekuna z custom_fields
                delivery_method=order.get('delivery_method'),
                order_source=order.get('order_source'),
                
                # NOWE POLA: Informacje o typie ceny
                price_type=price_type_to_save,
                original_amount_from_baselinker=original_price_from_baselinker,
            
                # Dane produktu z Baselinker - POPRAWIONE CENY
                raw_product_name=product.get('name'),
                quantity=quantity,
                price_gross=price_gross,      # POPRAWIONA: uwzględnia typ ceny
                price_net=price_net,          # POPRAWIONA: uwzględnia typ ceny
                value_gross=value_gross,      # POPRAWIONA: uwzględnia typ ceny
                value_net=value_net,          # POPRAWIONA: uwzględnia typ ceny
                volume_per_piece=float(volume_per_piece),
                total_volume=total_volume,
                price_per_m3=price_per_m3,
            
                # Dane z parsera
                group_type='towar',
                product_type=parsed_product.get('product_type') or 'klejonka',
                finish_state=parsed_product.get('finish_state') or 'surowy',
                wood_species=parsed_product.get('wood_species'),
                technology=parsed_product.get('technology'),
                wood_class=parsed_product.get('wood_class'),
                length_cm=float(parsed_product.get('length_cm') or 0),
                width_cm=float(parsed_product.get('width_cm') or 0),
                thickness_cm=float(parsed_product.get('thickness_cm') or 0),
            
                # Status i pozostałe
                current_status=self.status_map.get(order.get('order_status_id'), 'Nieznany'),
                delivery_cost=safe_float_convert(order.get('delivery_price', 0)),
                payment_method=order.get('payment_method'),
                paid_amount_net=self._calculate_paid_amount_net(
                    order.get('payment_done', 0), 
                    price_type_from_api
                ),
                balance_due=max(0, value_net - (safe_float_convert(order.get('paid', 0)) / 1.23)),

                # Dane produkcji (zostaną zaktualizowane przez metodę update_production_fields)
                production_volume=0,
                production_value_net=0,
                ready_pickup_volume=0,
                ready_pickup_value_net=0
            )
            
            # Debug log - pokaż co się dzieje z cenami
            self.logger.debug("Przetworzono ceny produktu",
                            order_id=order.get('order_id'),
                            product_name=product.get('name'),
                            price_type_from_api=price_type_from_api,
                            original_price=original_price_from_baselinker,
                            final_price_net=price_net,
                            final_price_gross=price_gross,
                            price_type_saved=price_type_to_save)
        
            # Aktualizuj pola produkcji na podstawie statusu
            record.update_production_fields()
        
            return record
        
        except Exception as e:
            self.logger.error("Błąd tworzenia rekordu zamówienia",
                            order_id=order.get('order_id'),
                            product_name=product.get('name'),
                            error=str(e),
                            error_type=type(e).__name__)
            raise

    def _auto_fill_state_for_order(self, postcode: str, current_state: str) -> str:
        """
        Automatyczne uzupełnianie województwa zgodnie z wymaganiami:
        """
        # KROK 1: Jeśli województwo jest wpisane - puszczamy dalej
        if current_state and current_state.strip():
            self.logger.debug("Województwo już wpisane, pomijamy auto-fill",
                             current_state=current_state,
                             postcode=postcode)
            return current_state.strip()
    
        # KROK 2: Jeśli nie ma województwa, sprawdzamy kod pocztowy i uzupełniamy
        if postcode and postcode.strip():
            auto_state = PostcodeToStateMapper.get_state_from_postcode(postcode)
            if auto_state:
                self.logger.info("Automatyczne uzupełnienie województwa z kodu pocztowego",
                               postcode=postcode,
                               auto_filled_state=auto_state)
                return auto_state
            else:
                self.logger.debug("Nie rozpoznano województwa z kodu pocztowego",
                                postcode=postcode)
    
        # KROK 3: Jeśli nie ma województwa ani kodu pocztowego - puszczamy dalej
        self.logger.debug("Brak danych do auto-fill województwa",
                         postcode=postcode or 'BRAK',
                         current_state=current_state or 'BRAK')
        return current_state or ''

    def update_existing_record(self, record: BaselinkerReportOrder, order: Dict, 
                         product: Dict, parsed_product: Dict) -> bool:
        """
        Aktualizuje istniejący rekord z automatycznym uzupełnianiem województwa
        """
        try:
            changes_made = False
        
            # Pobierz dane adresowe
            postcode = order.get('delivery_postcode', '').strip()
            current_state = order.get('delivery_state', '').strip()
        
            # NOWA LOGIKA: Automatyczne uzupełnianie województwa
            auto_state = self._auto_fill_state_for_order(postcode, current_state or record.delivery_state)
        
            # Sprawdź czy województwo się zmieniło
            if record.delivery_state != auto_state:
                self.logger.info("Aktualizacja województwa w istniejącym rekordzie",
                               record_id=record.id,
                               order_id=order.get('order_id'),
                               postcode=postcode,
                               old_state=record.delivery_state or 'BRAK',
                               new_state=auto_state)
                record.delivery_state = auto_state
                changes_made = True
        
            # Sprawdź inne pola, które mogły się zmienić
            new_status = self.status_map.get(order.get('order_status_id'), 'Nieznany')
            if record.current_status != new_status:
                record.current_status = new_status
                changes_made = True
        
            # Sprawdź dane kontaktowe
            new_phone = order.get('phone', '').strip()
            if record.phone != new_phone:
                record.phone = new_phone
                changes_made = True
        
            # Sprawdź kod pocztowy
            if record.delivery_postcode != postcode:
                record.delivery_postcode = postcode
                changes_made = True
        
            # Sprawdź miasto
            new_city = order.get('delivery_city', '').strip()
            if record.delivery_city != new_city:
                record.delivery_city = new_city
                changes_made = True
        
            # Sprawdź adres
            new_address = order.get('delivery_address', '').strip()
            if record.delivery_address != new_address:
                record.delivery_address = new_address
                changes_made = True
        
            # Jeśli zaszły zmiany, zaktualizuj pola produkcji
            if changes_made:
                record.update_production_fields()
                record.updated_at = datetime.utcnow()
        
            return changes_made
        
        except Exception as e:
            self.logger.error("Błąd aktualizacji rekordu",
                            record_id=record.id,
                            order_id=order.get('order_id'),
                            error=str(e))
            return False
    
    def fetch_orders_from_baselinker(self, date_from: datetime = None, order_id: int = None, 
                                max_orders: int = 500, include_excluded_statuses: bool = False) -> List[Dict]:
        """
        Pobiera zamówienia z Baselinker z prawidłową paginacją zgodną z dokumentacją API
    
        Args:
            date_from (datetime): Data od której pobierać zamówienia (opcjonalne)
            order_id (int): Konkretny numer zamówienia (jeśli podany, date_from ignorowane)
            max_orders (int): Maksymalna liczba zamówień do pobrania (domyślnie 500)
            include_excluded_statuses (bool): Czy dołączyć anulowane i nieopłacone (domyślnie False)

        Returns:
            List[Dict]: Lista zamówień z Baselinker (bez duplikatów)
        """
        if not self.api_key or not self.endpoint:
            self.logger.error("Brak konfiguracji API Baselinker")
            raise ValueError("Brak konfiguracji API Baselinker")

        headers = {
            'X-BLToken': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # Jeśli pobieramy konkretne zamówienie
        if order_id:
            parameters = {
                "order_id": order_id,
                "include_custom_extra_fields": True,
                "get_unconfirmed_orders": True
            }
            if not include_excluded_statuses:
                parameters["filter_order_status_id"] = "!105112,!138625"
        
            data = {
                'method': 'getOrders',
                'parameters': json.dumps(parameters)
            }

            try:
                response = requests.post(self.endpoint, headers=headers, data=data, timeout=30)
                response.raise_for_status()
                result = response.json()
            
                if result.get('status') == 'SUCCESS':
                    orders = result.get('orders', [])
                    self.logger.info("Pobrano pojedyncze zamówienie", 
                                   order_id=order_id,
                                   orders_count=len(orders))
                    return orders
                else:
                    error_msg = result.get('error_message', 'Nieznany błąd API')
                    self.logger.error("Błąd API Baselinker", error_message=error_msg)
                    return []
            except Exception as e:
                self.logger.error("Błąd pobierania pojedynczego zamówienia", order_id=order_id, error=str(e))
                return []

        # POBIERANIE WIELU ZAMÓWIEŃ Z PRAWIDŁOWĄ PAGINACJĄ
        all_orders = []
        seen_order_ids = set()
        current_date_confirmed_from = date_from
    
        self.logger.info("Rozpoczęcie pobierania zamówień",
                        date_from=current_date_confirmed_from.isoformat() if current_date_confirmed_from else None,
                        max_orders=max_orders,
                        include_excluded_statuses=include_excluded_statuses)

        iteration = 0
        max_iterations = 50
    
        while len(all_orders) < max_orders and iteration < max_iterations:
            iteration += 1

            # Parametry zapytania
            parameters = {
                "include_custom_extra_fields": True,
                "get_unconfirmed_orders": True,
            }
        
            if not include_excluded_statuses:
                parameters["filter_order_status_id"] = "!105112,!138625"

            if current_date_confirmed_from:
                if isinstance(current_date_confirmed_from, date) and not isinstance(current_date_confirmed_from, datetime):
                    current_date_confirmed_from = datetime.combine(current_date_confirmed_from, datetime.min.time())
                timestamp_from = int(current_date_confirmed_from.timestamp())
                parameters["date_confirmed_from"] = timestamp_from

            data = {
                'method': 'getOrders',
                'parameters': json.dumps(parameters)
            }

            try:
                response = requests.post(self.endpoint, headers=headers, data=data, timeout=30)
                response.raise_for_status()
                result = response.json()
            
                if result.get('status') == 'SUCCESS':
                    batch_orders = result.get('orders', [])
                
                    if not batch_orders:
                        break
                
                    # Znajdź najnowszą date_confirmed dla następnej iteracji
                    latest_date_confirmed = None
                    new_orders_in_batch = 0
                
                    for order in batch_orders:
                        order_id_val = order.get('order_id')
                    
                        # Pomiń duplikaty
                        if order_id_val in seen_order_ids:
                            continue
                        
                        # Dodaj zamówienie
                        all_orders.append(order)
                        seen_order_ids.add(order_id_val)
                        new_orders_in_batch += 1
                    
                        # Śledź najnowszą datę
                        order_date_confirmed = order.get('date_confirmed')
                        if order_date_confirmed:
                            order_datetime = datetime.fromtimestamp(int(order_date_confirmed))
                            if latest_date_confirmed is None or order_datetime > latest_date_confirmed:
                                latest_date_confirmed = order_datetime

                    # Aktualizuj date_confirmed_from zgodnie z dokumentacją Baselinker
                    if latest_date_confirmed:
                        current_date_confirmed_from = latest_date_confirmed + timedelta(seconds=1)
                
                    # Warunki końca paginacji
                    if len(batch_orders) < 100:
                        self.logger.info("Partia zawiera mniej niż 100 zamówień - koniec paginacji",
                                       iteration=iteration, batch_size=len(batch_orders))
                        break
                
                    if new_orders_in_batch == 0:
                        self.logger.info("Brak nowych zamówień w partii - koniec", iteration=iteration)
                        break
            
                else:
                    error_msg = result.get('error_message', 'Nieznany błąd API')
                    error_code = result.get('error_code', 'Brak kodu błędu')
                    self.logger.error("Błąd API Baselinker", iteration=iteration, 
                                     error_message=error_msg, error_code=error_code)
                    break
        
            except requests.exceptions.Timeout:
                self.logger.error("Timeout przy pobieraniu partii", iteration=iteration)
                continue
    
            except requests.exceptions.RequestException as e:
                self.logger.error("Błąd połączenia", iteration=iteration, error=str(e))
                continue

        if iteration >= max_iterations:
            self.logger.warning("Osiągnięto maksymalną liczbę iteracji", 
                              max_iterations=max_iterations, total_collected=len(all_orders))

        self.logger.info("Zakończono pobieranie zamówień",
                        total_orders=len(all_orders),
                        iterations_processed=iteration,
                        unique_orders=len(seen_order_ids),
                        filtered_excluded_statuses=not include_excluded_statuses)

        return all_orders
    
    def fetch_order_statuses(self) -> List[Dict]:
        """
        Pobiera listę statusów zamówień z API Baselinker i zwraca
        listę słowników: {'status_id': int, 'status_name': str}
        """
        if not self.api_key or not self.endpoint:
            self.logger.error("Brak konfiguracji API Baselinker")
            raise ValueError("Brak konfiguracji API Baselinker")

        headers = {
            'X-BLToken': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # Przygotuj payload
        data = {
            'method': 'getOrderStatusList',
            'parameters': json.dumps({})  # brak dodatkowych parametrów
        }

        try:
            self.logger.info("Pobieram statusy zamówień z Baselinker")
            response = requests.post(self.endpoint, headers=headers, data=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get('status') != 'SUCCESS':
                msg = result.get('error_message', 'Nieznany błąd API')
                code = result.get('error_code', '')
                self.logger.error("Błąd API przy pobieraniu statusów",
                                  status=msg, code=code)
                return []

            raw_statuses = result.get('orders_statuses', [])
            statuses = []
            for s in raw_statuses:
                try:
                    sid = int(s.get('orders_status_id', 0))
                    name = s.get('name', '').strip()
                    statuses.append({'status_id': sid, 'status_name': name})
                except Exception:
                    self.logger.warning("Nieprawidłowy wpis statusu", raw=s)

            self.logger.info("Pobrano statusy zamówień", count=len(statuses))
            return statuses

        except requests.exceptions.RequestException as e:
            self.logger.error("Błąd HTTP przy pobieraniu statusów", error=str(e))
            return []

    def sync_orders(self, date_from: Optional[datetime] = None, sync_type: str = 'manual', orders_list: Optional[List[Dict]] = None) -> Dict[str, any]:
        """
        Synchronizuje zamówienia z Baselinker
    
        Args:
            date_from (datetime): Data od której synchronizować (ignorowane jeśli orders_list podane)
            sync_type (str): 'manual', 'auto' lub 'selected'
            orders_list (List[Dict]): Lista zamówień do synchronizacji (opcjonalne)
        
        Returns:
            Dict: Raport synchronizacji
        """
        sync_start = datetime.utcnow()
    
        try:
            self.logger.info("Rozpoczęcie synchronizacji", 
                           sync_type=sync_type,
                           date_from=date_from.isoformat() if date_from else None,
                           orders_list_provided=orders_list is not None,
                           orders_list_count=len(orders_list) if orders_list else 0)
        
            # ZMIANA: Użyj podanej listy zamówień lub pobierz z Baselinker
            if orders_list is not None:
                # Synchronizacja wybranych zamówień
                orders = orders_list
                self.logger.info("Używam podanej listy zamówień", orders_count=len(orders))
            else:
                # Pobierz zamówienia z Baselinker
                orders = self.fetch_orders_from_baselinker(date_from)
                self.logger.info("Pobrano zamówienia z Baselinker", orders_count=len(orders))
        
            if not orders:
                self.logger.info("Brak zamówień do synchronizacji")
                return {
                    'success': True,
                    'message': 'Brak zamówień do synchronizacji',
                    'orders_processed': 0,
                    'orders_added': 0,
                    'orders_updated': 0,
                    'new_orders': []
                }
        
            # Sprawdź które zamówienia już istnieją
            order_ids = [order['order_id'] for order in orders]
            existing_order_ids = self._get_existing_order_ids(order_ids)
        
            self.logger.info("Analiza istniejących zamówień",
                           total_orders=len(orders),
                           existing_orders=len(existing_order_ids),
                           new_orders=len(order_ids) - len(existing_order_ids))
        
            # Przefiltruj nowe zamówienia
            new_orders = [order for order in orders if order['order_id'] not in existing_order_ids]
            existing_orders = [order for order in orders if order['order_id'] in existing_order_ids]
        
            # Dodaj nowe zamówienia
            added_count = 0
            if new_orders:
                self.logger.info("Dodawanie nowych zamówień", count=len(new_orders))
                added_count = self.add_orders_to_database(new_orders)
        
            # Aktualizuj istniejące zamówienia (statusy i płatności)
            updated_count = 0
            if existing_orders:
                self.logger.info("Aktualizowanie istniejących zamówień", count=len(existing_orders))
                updated_count = self._update_existing_orders(existing_orders, existing_order_ids)
        
            # Przygotuj listę nowych zamówień do zwrócenia
            new_orders_info = []
            for order in new_orders:
                new_orders_info.append({
                    'order_id': order['order_id'],
                    'customer_name': order.get('delivery_fullname', 'Nieznany klient'),
                    'total_value': sum(p.get('price_brutto', 0) * p.get('quantity', 1) 
                                     for p in order.get('products', []))
                })
        
            # Zapisz raport synchronizacji
            sync_log = ReportsSyncLog(
                sync_type=sync_type,
                orders_processed=len(orders),
                orders_added=added_count,
                orders_updated=updated_count,
                status='success',
                duration_seconds=int((datetime.utcnow() - sync_start).total_seconds())
            )
            db.session.add(sync_log)
            db.session.commit()
        
            self.logger.info("Synchronizacja zakończona pomyślnie",
                           orders_processed=len(orders),
                           orders_added=added_count,
                           orders_updated=updated_count,
                           duration_seconds=sync_log.duration_seconds)
        
            return {
                'success': True,
                'message': f'Synchronizacja zakończona pomyślnie',
                'orders_processed': len(orders),
                'orders_added': added_count,
                'orders_updated': updated_count,
                'new_orders': new_orders_info,
                'sync_log_id': sync_log.id
            }
        
        except Exception as e:
            # Zapisz błąd do logów
            error_duration = int((datetime.utcnow() - sync_start).total_seconds())
            sync_log = ReportsSyncLog(
                sync_type=sync_type,
                status='error',
                error_message=str(e),
                duration_seconds=error_duration
            )
            db.session.add(sync_log)
            db.session.commit()
        
            self.logger.error("Błąd podczas synchronizacji", 
                             error=str(e),
                             error_type=type(e).__name__,
                             sync_type=sync_type)
        
            return {
                'success': False,
                'error': str(e),
                'orders_processed': 0,
                'orders_added': 0,
                'orders_updated': 0
            }
    
    def add_orders_to_database(self, orders: List[Dict]) -> int:
        """
        Dodaje zamówienia do bazy danych
        
        Args:
            orders (List[Dict]): Lista zamówień z Baselinker
            
        Returns:
            int: Liczba dodanych rekordów (produktów)
        """
        added_count = 0
        
        for order in orders:
            try:
                # Konwertuj zamówienie na rekordy w bazie
                records = self._convert_order_to_records(order)
                
                for record in records:
                    db.session.add(record)
                    added_count += 1
                
                self.logger.debug("Dodano zamówienie do bazy",
                                order_id=order['order_id'],
                                products_count=len(records))
                
            except Exception as e:
                self.logger.error("Błąd dodawania zamówienia",
                                order_id=order.get('order_id'),
                                error=str(e))
                continue
        
        try:
            db.session.commit()
            self.logger.info("Dodano rekordy do bazy", added_count=added_count)
        except Exception as e:
            db.session.rollback()
            self.logger.error("Błąd zapisu do bazy", error=str(e))
            raise
        
        return added_count

    def _calculate_average_order_price_per_m3(self, records: List) -> float:
        """
        Oblicza średnią cenę za m³ w zamówieniu na podstawie już obliczonych cen produktów.
    
        Args:
            records (List): Lista rekordów BaselinkerReportOrder dla danego zamówienia
        
        Returns:
            float: Średnia cena za m³ w zamówieniu
        """
        try:
            price_per_m3_values = []
        
            for record in records:
                # Pomiń usługi i produkty bez ceny za m³
                if record.price_per_m3 and record.price_per_m3 > 0:
                    price_per_m3_values.append(float(record.price_per_m3))
        
            # Oblicz średnią arytmetyczną
            if price_per_m3_values:
                avg_price = sum(price_per_m3_values) / len(price_per_m3_values)
                return round(avg_price, 2)
            else:
                return 0.0
            
        except Exception as e:
            self.logger.error("Błąd obliczania średniej ceny za m³ w zamówieniu", error=str(e))
            return 0.0
    
    def _convert_order_to_records(self, order: Dict) -> List[BaselinkerReportOrder]:
        """
        Konwertuje zamówienie z Baselinker na rekordy w bazie (jeden rekord = jeden produkt)
        """
        records = []
        products = order.get('products', [])

        if not products:
            self.logger.warning("Zamówienie bez produktów",
                            order_id=order.get('order_id'))
            return records

        # NOWE: Pobierz informację o typie ceny z custom_extra_fields
        custom_fields = order.get('custom_extra_fields', {})
        price_type_from_api = custom_fields.get('106169', '').strip()
    
        self.logger.debug("Pobrano typ ceny z custom_extra_fields",
                        order_id=order.get('order_id'),
                        price_type_from_api=price_type_from_api)

        # Podstawowe dane zamówienia (wspólne dla wszystkich produktów)
        base_data = self._extract_base_order_data(order)

        # POPRAWIONA LOGIKA: Oblicz łączną wartość zamówienia netto (dla order_amount_net)
        total_order_value_gross = 0
        total_order_value_net = 0 
        total_order_value_net_products_only = 0  # ✅ NOWE: Tylko produkty fizyczne

        for product in products:
            original_price_from_baselinker = float(product.get('price_brutto', 0))

            # POPRAWIONA LOGIKA: Rozróżnianie typu ceny (zamiast process_baselinker_amount)
            if price_type_from_api.lower() == 'netto':
                # PRZYPADEK 1: Zamówienie ma oznaczenie "Netto"
                # Kwota z Baselinker jest rzeczywiście NETTO
                price_net = original_price_from_baselinker
                price_gross = price_net * 1.23
            elif price_type_from_api.lower() == 'brutto':
                # PRZYPADEK 2: Zamówienie ma oznaczenie "Brutto"
                # Kwota z Baselinker jest rzeczywiście BRUTTO
                price_gross = original_price_from_baselinker
                price_net = price_gross / 1.23
            else:
                # PRZYPADEK 3: Zamówienie bez oznaczenia (domyślnie BRUTTO)
                price_gross = original_price_from_baselinker
                price_net = price_gross / 1.23

            quantity = int(product.get('quantity', 1))

            # POPRAWIONE: Dodaj do obu sum
            product_value_gross = price_gross * quantity
            product_value_net = price_net * quantity

            total_order_value_gross += product_value_gross
            total_order_value_net += product_value_net

            # ✅ NOWE: Dodaj do sumy produktów tylko jeśli to NIE usługa
            product_name = product.get('name', '')
            if not self._is_service_product(product_name):
                total_order_value_net_products_only += product_value_net

        # POPRAWIONA LOGIKA: Oblicz łączną objętość wszystkich produktów w zamówieniu
        # ✅ UWZGLĘDNIJ TAKŻE volume_fixes zamiast tylko parsera!
        total_m3_all_products = 0.0
        product_type_map = {}
        group_type_map = {}
        product_volume_map = {}
        for product_index, product in enumerate(products):
            try:
                product_name = product.get('name', '')
                quantity = int(product.get('quantity', 1))
                group_type = 'usługa' if self._is_service_product(product_name) else 'towar'
                product_type = None
                product_volume = 0.0

                # ✅ UŻYJ NOWEJ METODY GENEROWANIA KLUCZY
                product_key = self.generate_product_key(order.get('order_id'), product, product_index)

                self.logger.debug("Processing product for volume calculation",
                                order_id=order.get('order_id'),
                                product_name=product_name,
                                product_index=product_index,
                                order_product_id=product.get('order_product_id'),
                                product_id_raw=product.get('product_id'),
                                generated_key=product_key)

                # ✅ NOWA LOGIKA: Sprawdź volume_fixes NAJPIERW
                volume_fix = self.get_volume_fix(product_key) if hasattr(self, 'volume_fixes') else None

                if volume_fix and volume_fix.get('volume'):
                    # PRZYPADEK 1: Mamy ręczne poprawki objętości
                    product_volume = float(volume_fix['volume'])
                    total_m3_all_products += product_volume

                    self.logger.debug("Użyto volume_fix dla produktu",
                                    order_id=order.get('order_id'),
                                    product_name=product_name,
                                    product_key=product_key,
                                    volume_from_fix=product_volume,
                                    quantity=quantity)
                else:
                    # PRZYPADEK 2: Użyj analizy nazwy produktu
                    from .routers import analyze_product_for_volume_and_attributes
                    analysis = analyze_product_for_volume_and_attributes(product_name)

                    product_type = analysis.get('product_type')
                    if product_type == 'suszenie':
                        group_type = 'usługa'
                    elif product_type in ['worek opałowy', 'tarcica', 'klejonka', 'deska']:
                        group_type = 'towar'
                    else:
                        group_type = 'usługa' if self._is_service_product(product_name) else 'towar'

                    if analysis['analysis_type'] == 'volume_only' and analysis.get('volume'):
                        # Objętość z nazwy produktu
                        product_volume = float(analysis.get('volume', 0))
                        total_m3_all_products += product_volume

                        self.logger.debug("Użyto objętości z nazwy produktu",
                                        order_id=order.get('order_id'),
                                        product_name=product_name,
                                        volume_from_name=product_volume,
                                        quantity=quantity)
                    else:
                        # PRZYPADEK 3: Użyj parsera wymiarów (dotychczasowa logika)
                        parsed_product = self.parser.parse_product_name(product_name)

                        # POPRAWKA: Bezpieczna konwersja wszystkich wymiarów na float
                        product_type = parsed_product.get('product_type')
                        length_cm = parsed_product.get('length_cm')
                        width_cm = parsed_product.get('width_cm')
                        thickness_mm = parsed_product.get('thickness_mm')

                        # Bezpieczna konwersja Decimal/None na float
                        def safe_float_convert(value):
                            if value is None:
                                return 0.0
                            if isinstance(value, Decimal):
                                return float(value)
                            try:
                                return float(value)
                            except (ValueError, TypeError):
                                return 0.0

                        length_m = safe_float_convert(length_cm) / 100 if length_cm else 0.0
                        width_m = safe_float_convert(width_cm) / 100 if width_cm else 0.0
                        thickness_m = safe_float_convert(thickness_mm) / 1000 if thickness_mm else 0.0

                        if length_m > 0 and width_m > 0 and thickness_m > 0:
                            product_m3 = length_m * width_m * thickness_m * quantity
                            total_m3_all_products += product_m3
                            product_volume = product_m3

                            self.logger.debug("Obliczono objętość produktu z wymiarów",
                                            order_id=order.get('order_id'),
                                            product_name=product_name,
                                            length_m=round(length_m, 4),
                                            width_m=round(width_m, 4),
                                            thickness_m=round(thickness_m, 4),
                                            quantity=quantity,
                                            product_m3=round(product_m3, 6))
                        else:
                            self.logger.debug("Nie można obliczyć objętości - brak wymiarów i volume_fix",
                                            order_id=order.get('order_id'),
                                            product_name=product_name,
                                            product_key=product_key,
                                            has_volume_fix=volume_fix is not None,
                                            parsed_dimensions={
                                                'length_cm': safe_float_convert(length_cm) if length_cm else None,
                                                'width_cm': safe_float_convert(width_cm) if width_cm else None,
                                                'thickness_mm': safe_float_convert(thickness_mm) if thickness_mm else None
                                            })

                product_type_map[product_index] = product_type
                group_type_map[product_index] = group_type
                product_volume_map[product_index] = product_volume
    
            except Exception as e:
                self.logger.warning("Błąd obliczania objętości produktu",
                                  order_id=order.get('order_id'),
                                  product_name=product.get('name'),
                                  error=str(e),
                                  error_type=type(e).__name__)
                continue

        self.logger.info("Obliczono łączną objętość zamówienia",
                        order_id=order.get('order_id'),
                        total_m3=round(total_m3_all_products, 6),
                        products_count=len(products))

        # Teraz utwórz rekordy dla każdego produktu z tą samą łączną objętością
        for product_index, product in enumerate(products):
            try:
                # Pobierz nazwę produktu i sprawdź czy to usługa
                product_name = product.get('name', '')
        
                # POPRAWIONA LOGIKA: Przetwórz cenę produktu (zamiast process_baselinker_amount)
                original_price_from_baselinker = float(product.get('price_brutto', 0))
        
                # Rozróżnianie typu ceny - TAKA SAMA LOGIKA jak wyżej
                if price_type_from_api.lower() == 'netto':
                    # Kwota z Baselinker jest NETTO
                    price_net = original_price_from_baselinker
                    price_gross = price_net * 1.23
                    price_type_to_save = 'netto'
                elif price_type_from_api.lower() == 'brutto':
                    # Kwota z Baselinker jest BRUTTO
                    price_gross = original_price_from_baselinker
                    price_net = price_gross / 1.23
                    price_type_to_save = 'brutto'
                else:
                    # Domyślnie BRUTTO
                    price_gross = original_price_from_baselinker
                    price_net = price_gross / 1.23
                    price_type_to_save = ''

                # Debug log
                self.logger.debug("Przetworzono ceny produktu w _convert_order_to_records",
                                order_id=order.get('order_id'),
                                product_name=product_name,
                                price_type_from_api=price_type_from_api,
                                original_price=original_price_from_baselinker,
                                final_price_net=price_net,
                                final_price_gross=price_gross,
                                price_type_saved=price_type_to_save)
        
                # NOWE: Sprawdź czy to usługa
                product_type = product_type_map.get(product_index)
                group_type = group_type_map.get(product_index)
                if self._is_service_product(product_name):
                    # === OBSŁUGA USŁUG ===
                    record = BaselinkerReportOrder(
                        # Dane zamówienia (bez zmian)
                        date_created=datetime.fromtimestamp(order.get('date_add')).date() if order.get('date_add') else datetime.now().date(),
                        baselinker_order_id=order.get('order_id'),
                        internal_order_number=order.get('extra_field_1'),
                        customer_name=order.get('delivery_fullname') or order.get('delivery_company') or order.get('user_login') or 'Nieznany klient',
                        delivery_postcode=order.get('delivery_postcode'),
                        delivery_city=order.get('delivery_city'),
                        delivery_address=order.get('delivery_address'),
                        delivery_state=order.get('delivery_state'),
                        phone=order.get('phone'),
                        caretaker=(order.get('custom_extra_fields', {}).get('105623') or "Brak danych"),
                        delivery_method=order.get('delivery_method'),
                        order_source=order.get('order_source'),
                        group_type=group_type,
                        product_type=product_type,
                        current_status=self.status_map.get(order.get('order_status_id'), f'Status {order.get("order_status_id")}'),
                        baselinker_status_id=order.get('order_status_id'),
            
                        # FINANSE (bez zmian)
                        order_amount_net=total_order_value_net_products_only,
                        delivery_cost=float(order.get('delivery_price', 0)),
                        paid_amount_net=self._calculate_paid_amount_net(
                            order.get('payment_done', 0), 
                            price_type_from_api
                        ),
                        payment_method=order.get('payment_method'),
            
                        # DANE USŁUGI
                        total_m3=total_m3_all_products,
                        raw_product_name=product_name,
                        quantity=product.get('quantity', 1),
                        price_gross=price_gross,
                        price_net=price_net,
                        price_type=price_type_to_save,
                        original_amount_from_baselinker=original_price_from_baselinker,
                
                        # Wartości finansowe
                        value_gross=price_gross * product.get('quantity', 1),
                        value_net=price_net * product.get('quantity', 1),
            
                        # USŁUGA: brak atrybutów produktowych
                        wood_species=None,
                        technology=None,
                        wood_class=None,
                        finish_state=None,
                        length_cm=None,
                        width_cm=None,
                        thickness_cm=None,
                        volume_per_piece=None,
                        total_volume=None,
                        price_per_m3=None,
            
                        # Pola techniczne
                        is_manual=False,
                        email=order.get('email')
                    )
                    record_total_volume = product_volume_map.get(product_index)
                    if record_total_volume and record_total_volume > 0:
                        record.total_volume = record_total_volume
                        qty = record.quantity or 1
                        record.volume_per_piece = record_total_volume / qty

                    self.logger.debug("Utworzono rekord usługi",
                                    order_id=order.get('order_id'),
                                    service_name=product_name,
                                    quantity=product.get('quantity', 1))
                else:
                    # === ISTNIEJĄCA LOGIKA DLA PRODUKTÓW FIZYCZNYCH ===
                    parsed_product = self.parser.parse_product_name(product_name)

                    # ✅ WYGENERUJ KLUCZ PRODUKTU ZGODNIE Z FRONTENDEM
                    product_key = self.generate_product_key(order.get('order_id'), product, product_index)
                
                    self.logger.debug("Generated product key for physical product",
                                    order_id=order.get('order_id'),
                                    product_name=product_name,
                                    product_index=product_index,
                                    order_product_id=product.get('order_product_id'),
                                    product_id_raw=product.get('product_id'),
                                    generated_key=product_key)

                    record = BaselinkerReportOrder(
                        # Dane zamówienia (bez zmian)
                        date_created=datetime.fromtimestamp(order.get('date_add')).date() if order.get('date_add') else datetime.now().date(),
                        baselinker_order_id=order.get('order_id'),
                        internal_order_number=order.get('extra_field_1'),
                        customer_name=order.get('delivery_fullname') or order.get('delivery_company') or order.get('user_login') or 'Nieznany klient',
                        delivery_postcode=order.get('delivery_postcode'),
                        delivery_city=order.get('delivery_city'),
                        delivery_address=order.get('delivery_address'),
                        delivery_state=order.get('delivery_state'),
                        phone=order.get('phone'),
                        caretaker=(order.get('custom_extra_fields', {}).get('105623') or "Brak danych"),
                        delivery_method=order.get('delivery_method'),
                        order_source=order.get('order_source'),
                        current_status=self.status_map.get(order.get('order_status_id'), f'Status {order.get("order_status_id")}'),
                        baselinker_status_id=order.get('order_status_id'),
            
                        # FINANSE (bez zmian)
                        order_amount_net=total_order_value_net_products_only,
                        delivery_cost=float(order.get('delivery_price', 0)),
                        paid_amount_net=self._calculate_paid_amount_net(
                            order.get('payment_done', 0), 
                            price_type_from_api
                        ),
                        payment_method=order.get('payment_method'),
            
                        # DANE PRODUKTU - z istniejącej logiki
                        total_m3=total_m3_all_products,
                        raw_product_name=product_name,
                        quantity=product.get('quantity', 1),
                        price_gross=price_gross,
                        price_net=price_net,
                        price_type=price_type_to_save,
                        original_amount_from_baselinker=original_price_from_baselinker,
                
                        # Wartości
                        value_gross=price_gross * product.get('quantity', 1),
                        value_net=price_net * product.get('quantity', 1),
            
                        # Dane z parsera
                        group_type='towar',
                        product_type=parsed_product.get('product_type') or 'klejonka',
                        wood_species=parsed_product.get('wood_species'),
                        technology=parsed_product.get('technology'),
                        wood_class=parsed_product.get('wood_class'),
                        finish_state=parsed_product.get('finish_state', 'surowy'),
                        length_cm=parsed_product.get('length_cm'),
                        width_cm=parsed_product.get('width_cm'),
                        thickness_cm=parsed_product.get('thickness_cm'),

                        # Pola techniczne
                        is_manual=False,
                        email=order.get('email')
                    )

                    # ✅ PRZEPROWADŹ ANALIZĘ NAZWY I ZASTOSUJ POPRAWKI OBJĘTOŚCI ORAZ ATRYBUTÓW
                    from .routers import analyze_product_for_volume_and_attributes
                    analysis = analyze_product_for_volume_and_attributes(product_name)

                    if analysis['analysis_type'] == 'volume_only' and analysis.get('volume'):
                        total_volume = float(analysis.get('volume', 0))
                        qty = record.quantity or 1
                        record.total_volume = total_volume
                        record.volume_per_piece = total_volume / qty
                        record.length_cm = None
                        record.width_cm = None
                        record.thickness_cm = None
                    elif analysis['analysis_type'] == 'manual_input_needed':
                        volume_fix = self.get_volume_fix(product_key)
                        if volume_fix and volume_fix.get('volume'):
                            total_volume = float(volume_fix['volume'])
                            qty = record.quantity or 1
                            record.total_volume = total_volume
                            record.volume_per_piece = total_volume / qty
                            record.length_cm = None
                            record.width_cm = None
                            record.thickness_cm = None

                    # ✅ ATRYBUTY DREWNA – PIERWSZEŃSTWO MAJĄ DANE RĘCZNE
                    wood_species = self.get_volume_fix_attribute(product_key, 'wood_species') or analysis.get('wood_species')
                    technology = self.get_volume_fix_attribute(product_key, 'technology') or analysis.get('technology')
                    wood_class = self.get_volume_fix_attribute(product_key, 'wood_class') or analysis.get('wood_class')
                    if wood_species:
                        record.wood_species = wood_species
                    if technology:
                        record.technology = technology
                    if wood_class:
                        record.wood_class = wood_class

                    # Atrybuty drewna – pierwszeństwo mają dane ręczne
                    wood_species = self.get_volume_fix_attribute(product_key, 'wood_species') or analysis.get('wood_species')
                    technology = self.get_volume_fix_attribute(product_key, 'technology') or analysis.get('technology')
                    wood_class = self.get_volume_fix_attribute(product_key, 'wood_class') or analysis.get('wood_class')
                    if wood_species:
                        record.wood_species = wood_species
                    if technology:
                        record.technology = technology
                    if wood_class:
                        record.wood_class = wood_class

                # Oblicz pola pochodne (dla obu typów)
                record.calculate_fields()
                records.append(record)
        
            except Exception as e:
                self.logger.error("Błąd przetwarzania produktu",
                                order_id=order.get('order_id'),
                                product_name=product.get('name'),
                                error=str(e))
                continue

        # PRZENIEŚ OBLICZANIE ŚREDNIEJ CENY TUTAJ (PO calculate_fields)
        # Oblicz średnią cenę za m³ dla całego zamówienia
        avg_order_price_per_m3 = self._calculate_average_order_price_per_m3(records)
    
        # USTAW ŚREDNIĄ CENĘ PO calculate_fields (żeby nie została nadpisana)
        for record in records:
            record.avg_order_price_per_m3 = avg_order_price_per_m3

        # DEBUG: Sprawdź czy wartości zostały ustawione
        self.logger.info("DEBUG: Obliczono średnią cenę za m³ w zamówieniu",
                        order_id=order.get('order_id'),
                        avg_order_price_per_m3=avg_order_price_per_m3,
                        records_count=len(records))

        return records
    
    def _extract_base_order_data(self, order: Dict) -> Dict:
        """
        Wyciąga podstawowe dane zamówienia (wspólne dla wszystkich produktów)
        """
        # Konwertuj timestamp na datę
        date_add = order.get('date_add')
        if date_add:
            date_created = datetime.fromtimestamp(date_add).date()
        else:
            date_created = datetime.now().date()
        
        # Wyciągnij nazwę klienta (priorytet: delivery_fullname > delivery_company > user_login)
        customer_name = (
            order.get('delivery_fullname') or 
            order.get('delivery_company') or 
            order.get('user_login') or 
            'Nieznany klient'
        )
        
        # Mapuj status
        status_id = order.get('order_status_id')
        current_status = self.status_map.get(status_id, f'Status {status_id}')
        
        # Oblicz zapłaconą kwotę netto z brutto
        payment_done = order.get('payment_done', 0)
        custom_fields = order.get('custom_extra_fields', {})
        price_type_from_api = custom_fields.get('106169', '').strip()
        
        paid_amount_net = self._calculate_paid_amount_net(payment_done, price_type_from_api)
        
        # Oblicz koszt dostawy netto
        delivery_price_gross = order.get('delivery_price', 0)
        delivery_cost_original = float(delivery_price_gross) if delivery_price_gross else 0

        # Pobieramy custom fields i wyciągamy opiekuna
        custom_fields = order.get('custom_extra_fields') or {}
        caretaker_name = custom_fields.get('105623') or "Brak danych"
        
        return {
            'date_created': date_created,
            'baselinker_order_id': order.get('order_id'),
            'internal_order_number': order.get('extra_field_1'),
            'customer_name': customer_name,
            'delivery_postcode': order.get('delivery_postcode'),
            'delivery_city': order.get('delivery_city'),
            'delivery_address': order.get('delivery_address'),
            'delivery_state': order.get('delivery_state'),
            'phone': order.get('phone'),
            'caretaker': caretaker_name,
            'delivery_method': order.get('delivery_method'),
            'order_source': order.get('order_source'),
            'current_status': current_status,
            'baselinker_status_id': status_id,
            'delivery_cost': float(order.get('delivery_price', 0)),
            'payment_method': order.get('payment_method'),
            'paid_amount_net': paid_amount_net,  # Zapłacono netto
            'email': order.get('email')
        }
    
    def _get_existing_order_ids(self, order_ids: List[int]) -> set:
        """
        Pobiera ID zamówień które już istnieją w bazie
        """
        existing = db.session.query(BaselinkerReportOrder.baselinker_order_id)\
            .filter(BaselinkerReportOrder.baselinker_order_id.in_(order_ids))\
            .distinct().all()
        
        return {row[0] for row in existing}
    
    def _update_existing_orders(self, orders: List[Dict], existing_order_ids: set) -> int:
        """
        Aktualizuje statusy istniejących zamówień
        """
        updated_count = 0
        
        for order in orders:
            order_id = order['order_id']
            if order_id not in existing_order_ids:
                continue
            
            try:
                # Pobierz status z Baselinker
                status_id = order.get('order_status_id')
                new_status = self.status_map.get(status_id, f'Status {status_id}')
                
                # Oblicz zapłaconą kwotę netto z brutto
                payment_done = order.get('payment_done', 0)
                custom_fields = order.get('custom_extra_fields', {})
                price_type_from_api = custom_fields.get('106169', '').strip()
                
                paid_amount_net = self._calculate_paid_amount_net(payment_done, price_type_from_api)
                
                # Aktualizuj wszystkie rekordy tego zamówienia
                records = BaselinkerReportOrder.query.filter_by(baselinker_order_id=order_id).all()
                
                # NOWE: Sprawdź czy trzeba zaktualizować pola price_type
                custom_fields = order.get('custom_extra_fields', {})
                price_type_from_api = custom_fields.get('106169', '').strip()

                for record in records:
                    if record.current_status != new_status or record.paid_amount_net != paid_amount_net:
                        record.current_status = new_status
                        record.baselinker_status_id = status_id
                        record.paid_amount_net = paid_amount_net
                        record.updated_at = datetime.utcnow()
        
                        record.update_production_fields()
                        record.calculate_fields()
        
                        updated_count += 1

                    if not record.price_type and price_type_from_api:
                        # Zaktualizuj price_type dla starych rekordów
                        normalized_type = 'netto' if price_type_from_api.lower() == 'netto' else 'brutto' if price_type_from_api.lower() == 'brutto' else ''
                        if normalized_type != record.price_type:
                            record.price_type = normalized_type
                            self.logger.info("Zaktualizowano price_type dla istniejącego rekordu",
                                           record_id=record.id,
                                           order_id=order_id,
                                           new_price_type=normalized_type)
                
            except Exception as e:
                self.logger.error("Błąd aktualizacji zamówienia",
                                order_id=order_id,
                                error=str(e))
                continue
        
        if updated_count > 0:
            try:
                db.session.commit()
                self.logger.info("Zaktualizowano rekordy", updated_count=updated_count)
            except Exception as e:
                db.session.rollback()
                self.logger.error("Błąd zapisu aktualizacji", error=str(e))
                raise
        
        return updated_count
    
    def get_order_details(self, order_id: int, include_excluded_statuses: bool = False) -> Optional[Dict]:
        """
        Pobiera szczegóły pojedynczego zamówienia z Baselinker
        """
        try:
            # POPRAWKA: Używaj nowej metody z filtrowaniem statusów
            orders = self.fetch_orders_from_baselinker(
                order_id=order_id, 
                include_excluded_statuses=include_excluded_statuses
            )
        
            if orders and len(orders) > 0:
                order = orders[0]
            
                # Sprawdź czy zamówienie nie ma wykluczanego statusu (dodatkowa walidacja)
                if not include_excluded_statuses:
                    status_id = order.get('order_status_id')
                    if status_id in [105112, 138625]:  # Nowe - nieopłacone, Anulowane
                        self.logger.info("Zamówienie wykluczono ze względu na status",
                                       order_id=order_id,
                                       status_id=status_id,
                                       status_name=self.status_map.get(status_id, f'Status {status_id}'))
                        return None
            
                # NOWE: Przetwórz ceny produktów w pojedynczym zamówieniu
                custom_fields = order.get('custom_extra_fields', {})
                price_type_from_api = custom_fields.get('106169', '').strip()
            
                # Jeśli zamówienie ma produkty, przetworz ich ceny
                if 'products' in order and order['products']:
                    for product in order['products']:
                        original_price = float(product.get('price_brutto', 0))
                    
                        # Utwórz tymczasowy rekord do przetworzenia
                        temp_record = BaselinkerReportOrder()
                        processed_price, _ = temp_record.process_baselinker_amount(
                            original_price, price_type_from_api
                        )
                    
                        # Zaktualizuj cenę w produkcie
                        product['price_brutto'] = processed_price
                    
                        self.logger.debug("Przetworzono cenę produktu w get_order_details",
                                        order_id=order.get('order_id'),
                                        product_name=product.get('name'),
                                        original_price=original_price,
                                        processed_price=processed_price,
                                        price_type=price_type_from_api)
            
                return order
        
            return None
        
        except Exception as e:
            self.logger.error("Błąd pobierania szczegółów zamówienia",
                             order_id=order_id,
                             include_excluded_statuses=include_excluded_statuses,
                             error=str(e))
            return None
        
    def check_for_new_orders(self, hours_back: int = 24) -> Tuple[bool, int]:
        """
        Sprawdza czy są nowe zamówienia w Baselinker (dla automatycznego sprawdzania)
    
        Args:
            hours_back (int): Ile godzin wstecz sprawdzać (domyślnie 24h)
        
        Returns:
            Tuple[bool, int]: (czy_są_nowe, liczba_nowych)
        """
        try:
            self.logger.info("Rozpoczęcie sprawdzania nowych zamówień", 
                            hours_back=hours_back)
        
            date_from = datetime.now() - timedelta(hours=hours_back)
            orders = self.fetch_orders_from_baselinker(date_from)
        
            if not orders:
                self.logger.info("Brak zamówień w sprawdzanym okresie",
                               date_from=date_from.isoformat())
                return False, 0
        
            # Sprawdź które zamówienia już mamy
            order_ids = [order['order_id'] for order in orders]
            existing_ids = self._get_existing_order_ids(order_ids)
        
            new_orders_count = len(order_ids) - len(existing_ids)
            has_new = new_orders_count > 0
        
            self.logger.info("Sprawdzenie nowych zamówień zakończone",
                           total_orders=len(orders),
                           existing_orders=len(existing_ids),
                           new_orders=new_orders_count,
                           has_new_orders=has_new)
        
            return has_new, new_orders_count
        
        except Exception as e:
            self.logger.error("Błąd sprawdzania nowych zamówień", 
                             error=str(e),
                             error_type=type(e).__name__,
                             hours_back=hours_back)
            return False, 0

    def _fetch_single_chunk(self, date_from: datetime, date_to: datetime, get_all_statuses: bool = False, limit_per_page: int = 100) -> Dict[str, any]:
        """
        Pobiera zamówienia dla pojedynczego chunka czasowego (wewnętrzna metoda pomocnicza).
    
        Args:
            date_from (datetime): Data początkowa chunka
            date_to (datetime): Data końcowa chunka
            get_all_statuses (bool): Czy pobierać wszystkie statusy
            limit_per_page (int): Limit zamówień na stronę
        
        Returns:
            Dict: {
                'success': bool,
                'orders': List[Dict],
                'error': str|None
            }
        """
        try:
            if not self.api_key or not self.endpoint:
                self.logger.error("Brak konfiguracji API Baselinker")
                return {
                    'success': False,
                    'orders': [],
                    'error': 'Brak konfiguracji API Baselinker'
                }

            headers = {
                'X-BLToken': self.api_key,
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            # Konwertuj daty na timestampy
            date_from_ts = int(date_from.timestamp())
            date_to_ts = int(date_to.timestamp())

            # Przygotuj parametry
            parameters = {
                "date_confirmed_from": date_from_ts,
                "date_confirmed_to": date_to_ts,
                "include_custom_extra_fields": True,
                "get_unconfirmed_orders": True,
            }

            # Filtrowanie statusów (jeśli nie pobieramy wszystkich)
            if not get_all_statuses:
                parameters["filter_order_status_id"] = "!105112,!138625"

            data = {
                'method': 'getOrders',
                'parameters': json.dumps(parameters)
            }

            self.logger.debug("Pobieranie chunka zamówień",
                             date_from=date_from.date(),
                             date_to=date_to.date(),
                             date_from_ts=date_from_ts,
                             date_to_ts=date_to_ts,
                             get_all_statuses=get_all_statuses)

            # Wykonaj request do API
            response = requests.post(
                self.endpoint, 
                headers=headers, 
                data=data, 
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get('status') == 'SUCCESS':
                orders = result.get('orders', [])
            
                self.logger.debug("Chunk pobrany pomyślnie",
                                orders_count=len(orders),
                                date_from=date_from.date(),
                                date_to=date_to.date())
            
                return {
                    'success': True,
                    'orders': orders,
                    'error': None
                }
            else:
                error_msg = result.get('error_message', 'Nieznany błąd API')
                error_code = result.get('error_code', 'Brak kodu')
            
                self.logger.error("Błąd API przy pobieraniu chunka",
                                error_message=error_msg,
                                error_code=error_code,
                                date_from=date_from.date(),
                                date_to=date_to.date())
            
                return {
                    'success': False,
                    'orders': [],
                    'error': f'{error_code}: {error_msg}'
                }

        except requests.exceptions.Timeout:
            self.logger.error("Timeout przy pobieraniu chunka",
                             date_from=date_from.date(),
                             date_to=date_to.date())
            return {
                'success': False,
                'orders': [],
                'error': 'Timeout połączenia z API Baselinker'
            }

        except requests.exceptions.RequestException as e:
            self.logger.error("Błąd połączenia przy pobieraniu chunka",
                             error=str(e),
                             date_from=date_from.date(),
                             date_to=date_to.date())
            return {
                'success': False,
                'orders': [],
                'error': f'Błąd połączenia: {str(e)}'
            }

        except Exception as e:
            self.logger.error("Nieoczekiwany błąd przy pobieraniu chunka",
                             error=str(e),
                             error_type=type(e).__name__,
                             date_from=date_from.date(),
                             date_to=date_to.date())
            return {
                'success': False,
                'orders': [],
                'error': f'Błąd: {str(e)}'
            }

    def fetch_orders_from_date_range(self, date_from: datetime, date_to: datetime, get_all_statuses: bool = False, limit_per_page: int = 100) -> Dict[str, any]:
        """
        Pobiera zamówienia z Baselinker dla zakresu dat używając chunków (po 3 dni).
    
        Logika:
        - 1-3 dni = 1 chunk
        - 4-7 dni = 2-3 chunki
        - 8-14 dni = 3-5 chunków
        - 30 dni = 10 chunków
    
        Args:
            date_from (datetime): Data początkowa zakresu
            date_to (datetime): Data końcowa zakresu
            get_all_statuses (bool): Czy pobierać również anulowane/nieopłacone
            limit_per_page (int): Limit zamówień na stronę API (100)
        
        Returns:
            Dict: {
                'success': bool,
                'orders': List[Dict],
                'error': str|None,
                'chunks_processed': int,
                'duration_seconds': float
            }
        """
        try:
            import time
            from datetime import timedelta
        
            start_time = time.time()
        
            # Oblicz ile dni
            days_diff = (date_to - date_from).days + 1
        
            self.logger.info("Rozpoczęcie pobierania zamówień z chunkowaniem",
                            date_from=date_from.isoformat(),
                            date_to=date_to.isoformat(),
                            days_total=days_diff,
                            get_all_statuses=get_all_statuses)
        
            # Wielkość chunka: 3 dni
            CHUNK_SIZE_DAYS = 3
        
            all_orders = []
            seen_order_ids = set()
            chunks_processed = 0
        
            current_date = date_from
        
            while current_date <= date_to:
                chunks_processed += 1
            
                # Oblicz koniec chunka (maksymalnie 3 dni lub do końca zakresu)
                chunk_end = min(
                    current_date + timedelta(days=CHUNK_SIZE_DAYS - 1),
                    date_to
                )
            
                # Pobierz zamówienia dla tego chunka
                result = self._fetch_single_chunk(
                    date_from=current_date,
                    date_to=chunk_end,
                    get_all_statuses=get_all_statuses,
                    limit_per_page=limit_per_page
                )
            
                if not result['success']:
                    self.logger.warning("Błąd podczas pobierania chunka",
                                      chunk_number=chunks_processed,
                                      chunk_start=current_date.date(),
                                      chunk_end=chunk_end.date(),
                                      error=result['error'])
                    # Kontynuuj mimo błędu w jednym chunku
                    current_date = chunk_end + timedelta(days=1)
                    continue
            
                # Dodaj zamówienia z tego chunka (deduplikacja)
                chunk_orders = result['orders']
                new_in_chunk = 0
            
                for order in chunk_orders:
                    order_id = order.get('order_id')
                    if order_id and order_id not in seen_order_ids:
                        all_orders.append(order)
                        seen_order_ids.add(order_id)
                        new_in_chunk += 1
            
                # Przejdź do następnego chunka
                current_date = chunk_end + timedelta(days=1)
        
            # Oblicz czas wykonania
            total_duration = time.time() - start_time
        
            self.logger.info("Zakończono pobieranie zamówień z chunkowaniem",
                            total_orders=len(all_orders),
                            unique_orders=len(seen_order_ids),
                            chunks_processed=chunks_processed,
                            date_from=date_from.isoformat(),
                            date_to=date_to.isoformat(),
                            duration_seconds=round(total_duration, 2),
                            get_all_statuses=get_all_statuses)
        
            return {
                'success': True,
                'orders': all_orders,
                'error': None,
                'chunks_processed': chunks_processed,
                'duration_seconds': round(total_duration, 2)
            }
        
        except Exception as e:
            self.logger.error("Nieoczekiwany błąd podczas pobierania zamówień z chunkowaniem",
                             error=str(e),
                             error_type=type(e).__name__,
                             date_from=date_from.isoformat(),
                             date_to=date_to.isoformat())
            return {
                'success': False,
                'orders': [],
                'error': f'Błąd serwera: {str(e)}',
                'chunks_processed': 0,
                'duration_seconds': 0
            }

    def set_dimension_fixes(self, fixes: Dict):
        """
        Ustawia poprawki wymiarów dla produktów
        
        Args:
            fixes (Dict): {order_id: {product_id: {length_cm: X, width_cm: Y, thickness_mm: Z}}}
        """
        self.dimension_fixes = fixes
        self.logger.info("Ustawiono poprawki wymiarów", fixes_count=len(fixes))
    
    def clear_dimension_fixes(self):
        """Czyści poprawki wymiarów"""
        self.dimension_fixes = {}
        self.logger.info("Wyczyszczono poprawki wymiarów")
    
    def _apply_dimension_fixes(self, order_id: int, product_id: int, parsed_data: Dict) -> Dict:
        """
        Stosuje poprawki wymiarów dla konkretnego produktu
        
        Args:
            order_id (int): ID zamówienia
            product_id (int): ID produktu
            parsed_data (Dict): Sparsowane dane produktu
            
        Returns:
            Dict: Poprawione dane produktu
        """
        if not self.dimension_fixes:
            return parsed_data
            
        order_fixes = self.dimension_fixes.get(str(order_id), {})
        product_fixes = order_fixes.get(str(product_id), {})
        
        if product_fixes:
            # Zastosuj poprawki
            if 'length_cm' in product_fixes:
                parsed_data['length_cm'] = float(product_fixes['length_cm'])
            if 'width_cm' in product_fixes:
                parsed_data['width_cm'] = float(product_fixes['width_cm'])
            if 'thickness_mm' in product_fixes:
                parsed_data['thickness_mm'] = float(product_fixes['thickness_mm'])
            # NOWE: nadpisanie objętości per sztuka
            if 'volume_m3' in product_fixes:
                parsed_data['volume_override_m3'] = float(product_fixes['volume_m3'])
                
            self.logger.info("Zastosowano poprawki wymiarów",
                           order_id=order_id,
                           product_id=product_id,
                           fixes=product_fixes)
        
        return parsed_data
    
    def _create_report_record(self, order: Dict, product: Dict) -> BaselinkerReportOrder:
        """
        Tworzy rekord raportu z zastosowaniem poprawek wymiarów.
        """
        try:
            # Parsuj nazwę produktu
            product_name = product.get('name', '')
            parsed_data = self.parser.parse_product_name(product_name)

            # Zastosuj poprawki wymiarów jeśli są dostępne
            order_id = order.get('order_id')
            product_id = product.get('product_id')
            if order_id and product_id:
                parsed_data = self._apply_dimension_fixes(order_id, product_id, parsed_data)

            # Oblicz objętość (m³) z priorytetem nadpisania ręcznego
            quantity = float(product.get('quantity', 0))
            total_m3 = None
            # Ręczne nadpisanie objętości per sztuka
            if parsed_data.get('volume_override_m3') is not None:
                total_m3 = quantity * parsed_data['volume_override_m3']
            # Automatyczne obliczenie z wymiarów jeśli brak nadpisania
            elif all(parsed_data.get(key) for key in ['length_cm', 'width_cm', 'thickness_mm']):
                length_m = parsed_data['length_cm'] / 100
                width_m = parsed_data['width_cm'] / 100
                thickness_m = parsed_data['thickness_mm'] / 1000
                total_m3 = quantity * length_m * width_m * thickness_m

            # Budowanie rekordu raportu
            record = BaselinkerReportOrder(
                order_id=order_id,
                product_id=product_id,
                product_name=product_name,
                quantity=quantity,
                length_cm=parsed_data.get('length_cm'),
                width_cm=parsed_data.get('width_cm'),
                thickness_mm=parsed_data.get('thickness_mm'),
                # Zapisz objętość do kolumny total_m3 w bazie i ttl m3 w UI
                total_volume=total_m3,
                # ... inne pola zgodnie z modelem BaselinkerReportOrder
            )

            return record

        except Exception as e:
            self.logger.error(
                "Błąd tworzenia rekordu z poprawkami wymiarów",
                order_id=order.get('order_id'),
                product_id=order.get('product_id'),
                error=str(e)
            )
            raise
    
    def _calculate_paid_amount_net(self, payment_done, price_type_from_api):
        """
        Oblicza paid_amount_net na podstawie typu ceny z custom_extra_fields
    
        Args:
            payment_done (float): Kwota zapłacona z Baselinker (payment_done)
            price_type_from_api (str): Typ ceny z extra_field_106169
        
        Returns:
            float: Przeliczona kwota netto
        """
        if not payment_done:
            return 0.0
        
        # Normalizuj wartość z API
        price_type = (price_type_from_api or '').strip().lower()
    
        if price_type == 'netto':
            # Dla zamówień netto: payment_done jest już kwotą netto, nie dziel przez 1.23
            paid_amount_net = float(payment_done)
            self.logger.debug("Obliczono paid_amount_net dla zamówienia NETTO",
                             payment_done=payment_done,
                             paid_amount_net=paid_amount_net)
        else:
            # Dla zamówień brutto lub pustych: payment_done to brutto, podziel przez 1.23
            paid_amount_net = float(payment_done) / 1.23
            self.logger.debug("Obliczono paid_amount_net dla zamówienia BRUTTO",
                             payment_done=payment_done,
                             paid_amount_net=paid_amount_net)
    
        return paid_amount_net
    
    def save_order_with_volume_analysis(self, order_data):
        """
        NOWA METODA: Zapisuje zamówienie z uwzględnieniem pełnej analizy objętości
        """
        try:
            order_id = order_data.get('order_id')
            products = order_data.get('products', [])
        
            if not products:
                return {
                    'success': False,
                    'error': f'Zamówienie {order_id} nie zawiera produktów'
                }
        
            # Sprawdź czy zamówienie już istnieje
            if self.order_exists(order_id):
                return {
                    'success': False,
                    'error': f'Zamówienie {order_id} już istnieje w bazie danych'
                }
        
            saved_records = []
            processing_errors = []
        
            # ✅ POPRAWKA: Dodaj enumerate() aby mieć product_index
            for product_index, product in enumerate(products):
                try:
                    # ✅ POPRAWKA: Przekaż product_index jako trzeci parametr
                    record_data = self.prepare_order_record_data_with_volume_analysis(
                        order_data, product, product_index
                    )
                
                    # Zapisz rekord
                    record = self.create_report_record(record_data)
                    saved_records.append(record)
                
                    # Loguj szczegóły
                    volume_info = f"objętość: {record_data.get('total_volume', 0):.4f}m³"
                    if record_data.get('wood_species'):
                        volume_info += f", gatunek: {record_data.get('wood_species')}"
                    if record_data.get('technology'):
                        volume_info += f", technologia: {record_data.get('technology')}"
                                
                except Exception as e:
                    error_msg = f"Błąd zapisywania produktu {product.get('name', 'unknown')}: {str(e)}"
                    processing_errors.append(error_msg)
                    reports_logger.error(error_msg)
                    continue
        
            if not saved_records:
                return {
                    'success': False,
                    'error': f'Nie udało się zapisać żadnych produktów z zamówienia {order_id}',
                    'details': processing_errors
                }
        
            # Commit transakcji
            db.session.commit()
        
            result = {
                'success': True,
                'order_id': order_id,
                'products_saved': len(saved_records),
                'message': f'Pomyślnie zapisano {len(saved_records)} produktów z zamówienia {order_id}'
            }
        
            if processing_errors:
                result['warnings'] = processing_errors
                result['products_failed'] = len(processing_errors)
        
            return result
        
        except Exception as e:
            db.session.rollback()
            error_msg = f"Krytyczny błąd zapisywania zamówienia {order_data.get('order_id', 'unknown')} z analizą objętości: {str(e)}"
            reports_logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def set_volume_fixes(self, volume_fixes):
        """
        NOWA METODA: Ustawia poprawki objętości dla produktów
        """
        self.volume_fixes = volume_fixes.copy()
        
        # Debug log dla każdej poprawki
        for product_key, fixes in volume_fixes.items():
            volume = fixes.get('volume', 0)
            attributes = []
            if fixes.get('wood_species'):
                attributes.append(f"gatunek: {fixes['wood_species']}")
            if fixes.get('technology'):
                attributes.append(f"technologia: {fixes['technology']}")
            if fixes.get('wood_class'):
                attributes.append(f"klasa: {fixes['wood_class']}")
            
            attr_str = ", " + ", ".join(attributes) if attributes else ""

    def clear_volume_fixes(self):
        """
        NOWA METODA: Czyści poprawki objętości
        """
        fixes_count = len(self.volume_fixes) if hasattr(self, 'volume_fixes') else 0
        self.volume_fixes = {}

    def create_report_record(self, record_data):
        """
        ULEPSZONA METODA: Tworzy rekord raportu w bazie danych z debugiem objętości
        """
        try:
            # ✅ DODAJ DEBUG PRZED TWORZENIEM REKORDU
            volume_per_piece_input = record_data.get('volume_per_piece')
            total_volume_input = record_data.get('total_volume')
        
            # ✅ UTWÓRZ REKORD BEZPOŚREDNIO (zamiast przez konstruktor)
            record = BaselinkerReportOrder()
        
            # ✅ USTAW WSZYSTKIE POLA RĘCZNIE (jak w save_order_record)
            # Podstawowe pola
            record.date_created = record_data.get('date_created')
            record.baselinker_order_id = record_data.get('baselinker_order_id')
            record.internal_order_number = record_data.get('internal_order_number')
            record.customer_name = record_data.get('customer_name')
            record.delivery_postcode = record_data.get('delivery_postcode')
            record.delivery_city = record_data.get('delivery_city')
            record.delivery_address = record_data.get('delivery_address')
            record.delivery_state = record_data.get('delivery_state')
            record.phone = record_data.get('phone')
            record.caretaker = record_data.get('caretaker')
            record.delivery_method = record_data.get('delivery_method')
            record.order_source = record_data.get('order_source')
        
            # Dane produktu
            record.group_type = record_data.get('group_type')
            record.product_type = record_data.get('product_type')
            record.finish_state = record_data.get('finish_state')
        
            # Atrybuty z analizy objętości
            record.wood_species = record_data.get('wood_species')
            record.technology = record_data.get('technology')
            record.wood_class = record_data.get('wood_class')
        
            # Wymiary (mogą być None dla produktów z objętością)
            record.length_cm = record_data.get('length_cm')
            record.width_cm = record_data.get('width_cm')
            record.thickness_cm = record_data.get('thickness_cm')
            record.quantity = record_data.get('quantity')
        
            # Ceny i wartości
            record.price_gross = record_data.get('price_gross')
            record.price_net = record_data.get('price_net')
            record.value_gross = record_data.get('value_gross')  
            record.value_net = record_data.get('value_net')
        
            # ✅ WAŻNE: Objętości - ustaw PRZED calculate_fields()
            record.volume_per_piece = record_data.get('volume_per_piece')
            record.total_volume = record_data.get('total_volume')
            record.price_per_m3 = record_data.get('price_per_m3')
            record.avg_order_price_per_m3 = record_data.get('avg_order_price_per_m3', 0.0)
        
            # Pozostałe pola
            record.realization_date = record_data.get('realization_date')
            record.current_status = record_data.get('current_status')
            record.delivery_cost = record_data.get('delivery_cost')
            record.payment_method = record_data.get('payment_method')
            record.paid_amount_net = record_data.get('paid_amount_net', 0)
            record.balance_due = record_data.get('balance_due')
            record.production_volume = record_data.get('production_volume', 0)
            record.production_value_net = record_data.get('production_value_net', 0)
            record.ready_pickup_volume = record_data.get('ready_pickup_volume', 0)
            record.ready_pickup_value_net = record_data.get('ready_pickup_value_net', 0)
        
            # Pola techniczne
            record.baselinker_status_id = record_data.get('baselinker_status_id')
            record.raw_product_name = record_data.get('raw_product_name')
            record.email = record_data.get('email')
        
            # Oblicz total_m3 na poziomie zamówienia
            record.total_m3 = record_data.get('total_volume', 0)
            record.order_amount_net = record_data.get('order_amount_net', 0)
            record.price_type = record_data.get('price_type')
            record.original_amount_from_baselinker = record_data.get('original_amount_from_baselinker')
        
            # ✅ OBLICZ automatycznie wszystkie pola (w tym datę realizacji) 
            # UWAGA: Ta metoda może nadpisać objętości!
            record.calculate_fields()
        
            # Dodaj do sesji (nie commituj tutaj)
            db.session.add(record)
        
            return record
        
        except Exception as e:
            reports_logger.error(f"Błąd tworzenia rekordu: {str(e)}")
            raise

    def order_exists(self, order_id):
        """
        NOWA METODA: Sprawdza czy zamówienie już istnieje w bazie
        """
        return BaselinkerReportOrder.query.filter(
            BaselinkerReportOrder.baselinker_order_id == order_id
        ).first() is not None

# ===== FUNKCJE POMOCNICZE =====

def get_reports_service() -> BaselinkerReportsService:
    """
    Factory function dla serwisu
    """
    return BaselinkerReportsService()


def sync_recent_orders(days_back: int = None) -> Dict:
    """
    Synchronizuje zamówienia z ostatnich X dni lub wszystkie jeśli days_back=None
    
    Args:
        days_back (int): Ile dni wstecz synchronizować (None = wszystkie)
        
    Returns:
        Dict: Wynik synchronizacji
    """
    service = get_reports_service()
    
    if days_back is not None:
        date_from = datetime.now() - timedelta(days=days_back)
        service.logger.info("Synchronizacja zamówień z ostatnich dni", 
                          days_back=days_back,
                          date_from=date_from.isoformat())
    else:
        date_from = None
        service.logger.info("Synchronizacja wszystkich zamówień")
    
    return service.sync_orders(date_from=date_from, sync_type='manual')

def check_new_orders_available() -> Tuple[bool, int]:
    """
    Sprawdza czy są dostępne nowe zamówienia
    """
    service = get_reports_service()
    return service.check_for_new_orders()

# Funkcja pomocnicza do bezpiecznej konwersji
def safe_float_convert(value) -> float:
    """Bezpiecznie konwertuje wartość do float"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
    