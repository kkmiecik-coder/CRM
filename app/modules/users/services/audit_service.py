# app/modules/users/services/audit_service.py
"""
Serwis logowania zmian uprawnień (Audit Log)
=============================================

Logika biznesowa dla audit log:
- Logowanie zmian ról użytkowników
- Logowanie zmian uprawnień (grant/revoke)
- Pobieranie historii zmian
- Filtrowanie i paginacja

Autor: Konrad Kmiecik + Claude AI
Data: 2025-01-13
"""

from extensions import db
from ..models import PermissionAuditLog, User, Module
from flask import request
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)


class AuditService:
    """Serwis logowania zmian uprawnień"""
    
    @staticmethod
    def log_role_change(user_id: int, old_role_id: Optional[int], 
                       new_role_id: int, changed_by_user_id: int,
                       reason: str = None) -> PermissionAuditLog:
        """
        Loguje zmianę roli użytkownika
        
        Args:
            user_id (int): ID użytkownika którego dotyczy zmiana
            old_role_id (int): ID starej roli (None jeśli pierwsza rola)
            new_role_id (int): ID nowej roli
            changed_by_user_id (int): ID użytkownika wykonującego zmianę
            reason (str): Powód zmiany
        
        Returns:
            PermissionAuditLog: Utworzony wpis w logu
        """
        try:
            from ..models import Role
            
            old_role = Role.query.get(old_role_id) if old_role_id else None
            new_role = Role.query.get(new_role_id)
            
            log_entry = PermissionAuditLog(
                user_id=user_id,
                changed_by_user_id=changed_by_user_id,
                change_type='role_changed',
                entity_type='role',
                entity_id=new_role_id,
                old_value=json.dumps({
                    'role_id': old_role_id,
                    'role_name': old_role.role_name if old_role else None
                }) if old_role else None,
                new_value=json.dumps({
                    'role_id': new_role_id,
                    'role_name': new_role.role_name if new_role else None
                }),
                reason=reason,
                ip_address=AuditService._get_client_ip(),
                user_agent=AuditService._get_user_agent()
            )
            
            db.session.add(log_entry)
            db.session.commit()
            
            logger.info(
                f"Audit: Zmiana roli user_id={user_id} "
                f"z {old_role.role_name if old_role else 'None'} "
                f"na {new_role.role_name if new_role else 'None'} "
                f"przez user_id={changed_by_user_id}"
            )
            
            return log_entry
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd logowania zmiany roli: {e}")
            raise
    
    @staticmethod
    def log_module_grant(user_id: int, module_id: int, 
                        changed_by_user_id: int, reason: str = None) -> PermissionAuditLog:
        """
        Loguje nadanie dostępu do modułu
        
        Args:
            user_id (int): ID użytkownika
            module_id (int): ID modułu
            changed_by_user_id (int): ID użytkownika wykonującego zmianę
            reason (str): Powód zmiany
        
        Returns:
            PermissionAuditLog: Utworzony wpis w logu
        """
        try:
            module = Module.query.get(module_id)
            
            log_entry = PermissionAuditLog(
                user_id=user_id,
                changed_by_user_id=changed_by_user_id,
                change_type='module_granted',
                entity_type='module',
                entity_id=module_id,
                old_value=None,
                new_value=json.dumps({
                    'module_id': module_id,
                    'module_key': module.module_key if module else None,
                    'access_type': 'grant'
                }),
                reason=reason,
                ip_address=AuditService._get_client_ip(),
                user_agent=AuditService._get_user_agent()
            )
            
            db.session.add(log_entry)
            db.session.commit()
            
            logger.info(
                f"Audit: Nadano dostęp user_id={user_id} "
                f"do modułu {module.module_key if module else module_id} "
                f"przez user_id={changed_by_user_id}"
            )
            
            return log_entry
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd logowania nadania dostępu: {e}")
            raise
    
    @staticmethod
    def log_module_revoke(user_id: int, module_id: int, 
                         changed_by_user_id: int, reason: str = None) -> PermissionAuditLog:
        """
        Loguje odebranie dostępu do modułu
        
        Args:
            user_id (int): ID użytkownika
            module_id (int): ID modułu
            changed_by_user_id (int): ID użytkownika wykonującego zmianę
            reason (str): Powód zmiany
        
        Returns:
            PermissionAuditLog: Utworzony wpis w logu
        """
        try:
            module = Module.query.get(module_id)
            
            log_entry = PermissionAuditLog(
                user_id=user_id,
                changed_by_user_id=changed_by_user_id,
                change_type='module_revoked',
                entity_type='module',
                entity_id=module_id,
                old_value=json.dumps({
                    'module_id': module_id,
                    'module_key': module.module_key if module else None,
                    'access_type': 'grant'
                }),
                new_value=json.dumps({
                    'module_id': module_id,
                    'module_key': module.module_key if module else None,
                    'access_type': 'revoke'
                }),
                reason=reason,
                ip_address=AuditService._get_client_ip(),
                user_agent=AuditService._get_user_agent()
            )
            
            db.session.add(log_entry)
            db.session.commit()
            
            logger.info(
                f"Audit: Odebrano dostęp user_id={user_id} "
                f"do modułu {module.module_key if module else module_id} "
                f"przez user_id={changed_by_user_id}"
            )
            
            return log_entry
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd logowania odebrania dostępu: {e}")
            raise
    
    @staticmethod
    def get_audit_log(user_id: Optional[int] = None, 
                     change_type: Optional[str] = None,
                     date_from: Optional[datetime] = None,
                     date_to: Optional[datetime] = None,
                     limit: int = 50,
                     offset: int = 0) -> Dict[str, Any]:
        """
        Pobiera logi zmian z filtrami
        
        Args:
            user_id (int): Filtruj po użytkowniku (którego dotyczy zmiana)
            change_type (str): Filtruj po typie zmiany (role_changed, module_granted, module_revoked)
            date_from (datetime): Filtruj od daty
            date_to (datetime): Filtruj do daty
            limit (int): Maksymalna liczba wyników
            offset (int): Offset dla paginacji
        
        Returns:
            dict: {
                'total': int,
                'logs': List[dict],
                'has_more': bool
            }
        """
        try:
            query = PermissionAuditLog.query
            
            # Filtry
            if user_id:
                query = query.filter_by(user_id=user_id)
            
            if change_type:
                query = query.filter_by(change_type=change_type)
            
            if date_from:
                query = query.filter(PermissionAuditLog.created_at >= date_from)
            
            if date_to:
                query = query.filter(PermissionAuditLog.created_at <= date_to)
            
            # Zlicz total
            total = query.count()
            
            # Pobierz wyniki z paginacją
            logs = query.order_by(
                PermissionAuditLog.created_at.desc()
            ).limit(limit).offset(offset).all()
            
            # Konwertuj do słowników
            logs_data = []
            for log in logs:
                user = User.query.get(log.user_id)
                changed_by = User.query.get(log.changed_by_user_id) if log.changed_by_user_id else None
                
                # Parse JSON values
                old_value = json.loads(log.old_value) if log.old_value else None
                new_value = json.loads(log.new_value) if log.new_value else None
                
                logs_data.append({
                    'id': log.id,
                    'user_id': log.user_id,
                    'user_email': user.email if user else None,
                    'user_name': user.get_full_name() if user else 'Nieznany',
                    'changed_by_user_id': log.changed_by_user_id,
                    'changed_by_email': changed_by.email if changed_by else None,
                    'changed_by_name': changed_by.get_full_name() if changed_by else 'System',
                    'change_type': log.change_type,
                    'entity_type': log.entity_type,
                    'entity_id': log.entity_id,
                    'old_value': old_value,
                    'new_value': new_value,
                    'reason': log.reason,
                    'ip_address': log.ip_address,
                    'created_at': log.created_at.isoformat() if log.created_at else None,
                    'created_at_formatted': AuditService._format_datetime(log.created_at)
                })
            
            return {
                'total': total,
                'logs': logs_data,
                'has_more': (offset + limit) < total,
                'limit': limit,
                'offset': offset
            }
        
        except Exception as e:
            logger.exception(f"Błąd pobierania audit log: {e}")
            return {
                'total': 0,
                'logs': [],
                'has_more': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_user_audit_log(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Pobiera ostatnie zmiany dla konkretnego użytkownika
        
        Args:
            user_id (int): ID użytkownika
            limit (int): Maksymalna liczba wyników
        
        Returns:
            List[dict]: Lista zmian
        """
        result = AuditService.get_audit_log(
            user_id=user_id,
            limit=limit,
            offset=0
        )
        return result.get('logs', [])
    
    @staticmethod
    def _get_client_ip() -> Optional[str]:
        """Pobiera adres IP klienta"""
        try:
            if request:
                # Sprawdź X-Forwarded-For (jeśli za proxy/load balancer)
                if request.headers.get('X-Forwarded-For'):
                    return request.headers.get('X-Forwarded-For').split(',')[0].strip()
                # Sprawdź X-Real-IP
                if request.headers.get('X-Real-IP'):
                    return request.headers.get('X-Real-IP')
                # Fallback do remote_addr
                return request.remote_addr
        except Exception as e:
            logger.warning(f"Nie można pobrać IP klienta: {e}")
        return None
    
    @staticmethod
    def _get_user_agent() -> Optional[str]:
        """Pobiera User-Agent przeglądarki"""
        try:
            if request:
                return request.headers.get('User-Agent')
        except Exception:
            pass
        return None
    
    @staticmethod
    def _format_datetime(dt: Optional[datetime]) -> str:
        """
        Formatuje datetime do przyjaznej formy
        
        Args:
            dt (datetime): Data do sformatowania
        
        Returns:
            str: Sformatowana data
        """
        if not dt:
            return ''
        
        try:
            now = datetime.utcnow()
            diff = now - dt
            
            # Mniej niż minutę temu
            if diff.total_seconds() < 60:
                return 'przed chwilą'
            
            # Mniej niż godzinę temu
            if diff.total_seconds() < 3600:
                minutes = int(diff.total_seconds() / 60)
                return f'{minutes} min temu'
            
            # Mniej niż dzień temu
            if diff.total_seconds() < 86400:
                hours = int(diff.total_seconds() / 3600)
                return f'{hours}h temu'
            
            # Mniej niż tydzień temu
            if diff.days < 7:
                return f'{diff.days} dni temu'
            
            # Pełna data
            return dt.strftime('%Y-%m-%d %H:%M')
        
        except Exception as e:
            logger.warning(f"Błąd formatowania daty: {e}")
            return str(dt)