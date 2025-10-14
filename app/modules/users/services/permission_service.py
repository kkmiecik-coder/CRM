# app/modules/users/services/permission_service.py
"""
Serwis sprawdzania uprawnień użytkowników
==========================================

Główna logika sprawdzania dostępu do modułów.

Algorytm sprawdzania dostępu:
1. Moduły 'public' (dashboard) - zawsze dostępne
2. Moduły 'custom' (production) - zwraca True, moduł sam sprawdza
3. Indywidualne 'revoke' - DENY wygrywa zawsze
4. Indywidualne 'grant' - nadaje dostęp
5. Uprawnienia z roli - sprawdza domyślne uprawnienia

Fallback dla kompatybilności wstecznej:
- Jeśli moduł nie ma wpisu w users_modules, użyj starego systemu (users.role)

Autor: Konrad Kmiecik + Claude AI
Data: 2025-01-13
"""

from typing import Optional
from ..models import Module, User, UserPermission, RolePermission
import logging

logger = logging.getLogger(__name__)


class PermissionService:
    """Serwis sprawdzania uprawnień użytkowników"""
    
    @staticmethod
    def user_has_module_access(user_id: int, module_key: str) -> bool:
        """
        Sprawdza czy użytkownik ma dostęp do modułu
        
        Args:
            user_id (int): ID użytkownika
            module_key (str): Klucz modułu (np. 'quotes', 'production')
        
        Returns:
            bool: True jeśli użytkownik ma dostęp, False jeśli nie
        
        Examples:
            >>> PermissionService.user_has_module_access(1, 'quotes')
            True
            >>> PermissionService.user_has_module_access(2, 'users')
            False
        """
        try:
            # 1. Pobierz moduł
            module = Module.query.filter_by(module_key=module_key).first()
            
            # FALLBACK: Jeśli moduł nie istnieje w nowym systemie
            if not module:
                logger.warning(f"Moduł '{module_key}' nie znaleziony w users_modules - fallback do starego systemu")
                return PermissionService._fallback_old_system(user_id, module_key)
            
            # Sprawdź czy moduł jest aktywny
            if not module.is_active:
                logger.warning(f"Moduł '{module_key}' jest nieaktywny")
                return False
            
            # 2. Moduły 'public' - zawsze dostępne dla zalogowanych
            if module.access_type == 'public':
                return True
            
            # 3. Moduły 'custom' - specjalna obsługa
            if module.access_type == 'custom':
                if module_key == 'production':
                    # Kontynuuj sprawdzanie uprawnień
                    pass
                else:
                    return True
            
            # 4. Sprawdź indywidualne uprawnienia użytkownika
            individual_permission = UserPermission.query.filter_by(
                user_id=user_id,
                module_id=module.id
            ).first()
            
            if individual_permission:
                # REVOKE (odbierz) - DENY zawsze wygrywa
                if individual_permission.access_type == 'revoke':
                    logger.info(f"User {user_id}: DENY dla modułu '{module_key}' (indywidualne revoke)")
                    return False
                
                # GRANT (nadaj) - nadaje dostęp niezależnie od roli
                if individual_permission.access_type == 'grant':
                    logger.info(f"User {user_id}: ALLOW dla modułu '{module_key}' (indywidualne grant)")
                    return True
            
            # 5. Sprawdź uprawnienia z roli użytkownika
            user = User.query.get(user_id)
            if not user:
                logger.error(f"Użytkownik {user_id} nie istnieje")
                return False
            
            if not user.role_id:
                logger.warning(f"User {user_id} nie ma przypisanej role_id")
                # FALLBACK: użyj starego systemu
                return PermissionService._fallback_old_system(user_id, module_key)
            
            # Sprawdź czy rola ma dostęp do modułu
            role_permission = RolePermission.query.filter_by(
                role_id=user.role_id,
                module_id=module.id
            ).first()
            
            if role_permission:
                logger.info(f"User {user_id}: ALLOW dla modułu '{module_key}' (z roli)")
                return True
            
            # 6. Brak dostępu
            logger.info(f"User {user_id}: DENY dla modułu '{module_key}' (brak uprawnień)")
            return False
        
        except Exception as e:
            logger.exception(f"Błąd sprawdzania uprawnień dla user_id={user_id}, module_key={module_key}: {e}")
            return False
    
    @staticmethod
    def _fallback_old_system(user_id: int, module_key: str) -> bool:
        """
        FALLBACK: Stary system uprawnień (używany podczas migracji)
        
        Sprawdza dostęp na podstawie pola users.role (bez users_modules)
        
        Args:
            user_id (int): ID użytkownika
            module_key (str): Klucz modułu
        
        Returns:
            bool: True jeśli użytkownik ma dostęp według starego systemu
        """
        try:
            user = User.query.get(user_id)
            if not user or not user.role:
                return False
            
            role = user.role.lower()
            
            # Admin ma dostęp do wszystkiego
            if role == 'admin':
                return True
            
            # Partner: tylko dashboard + quotes
            if role == 'partner':
                return module_key in ['dashboard', 'quotes']
            
            # User: wszystko oprócz 'users'
            if role == 'user':
                return module_key != 'users'
            
            return False
        
        except Exception as e:
            logger.exception(f"Błąd fallback dla user_id={user_id}, module_key={module_key}: {e}")
            return False
    
    @staticmethod
    def get_user_modules(user_id: int) -> list:
        """
        Pobiera listę modułów dostępnych dla użytkownika
        
        Args:
            user_id (int): ID użytkownika
        
        Returns:
            list: Lista słowników z modułami i źródłem dostępu
        
        Example:
            >>> PermissionService.get_user_modules(1)
            [
                {
                    'module_key': 'dashboard',
                    'display_name': 'Dashboard',
                    'icon': '🏠',
                    'access_source': 'public'
                },
                {
                    'module_key': 'quotes',
                    'display_name': 'Wyceny',
                    'icon': '📊',
                    'access_source': 'role'
                },
                ...
            ]
        """
        try:
            modules = []
            
            # Pobierz wszystkie aktywne moduły
            all_modules = Module.query.filter_by(is_active=True).order_by(Module.sort_order).all()
            
            for module in all_modules:
                has_access = PermissionService.user_has_module_access(user_id, module.module_key)
                
                if has_access:
                    # Określ źródło dostępu
                    access_source = PermissionService._get_access_source(user_id, module.id)
                    
                    modules.append({
                        'module_key': module.module_key,
                        'display_name': module.display_name,
                        'icon': module.icon,
                        'access_type': module.access_type,
                        'access_source': access_source
                    })
            
            return modules
        
        except Exception as e:
            logger.exception(f"Błąd pobierania modułów dla user_id={user_id}: {e}")
            return []
    
    @staticmethod
    def _get_access_source(user_id: int, module_id: int) -> str:
        """
        Określa źródło dostępu do modułu
        
        Returns:
            str: 'public', 'custom', 'individual', 'role'
        """
        try:
            module = Module.query.get(module_id)
            
            if module.access_type == 'public':
                return 'public'
            
            if module.access_type == 'custom':
                return 'custom'
            
            # Sprawdź indywidualne uprawnienia
            individual = UserPermission.query.filter_by(
                user_id=user_id,
                module_id=module_id
            ).first()
            
            if individual:
                return 'individual'
            
            # Sprawdź uprawnienia z roli
            user = User.query.get(user_id)
            if user and user.role_id:
                role_perm = RolePermission.query.filter_by(
                    role_id=user.role_id,
                    module_id=module_id
                ).first()
                
                if role_perm:
                    return 'role'
            
            return 'unknown'
        
        except Exception as e:
            logger.exception(f"Błąd określania źródła dostępu: {e}")
            return 'unknown'
    
    @staticmethod
    def get_user_permissions_details(user_id: int) -> dict:
        """
        Pobiera szczegółowe informacje o uprawnieniach użytkownika
        
        Args:
            user_id (int): ID użytkownika
        
        Returns:
            dict: Szczegóły uprawnień użytkownika
        
        Example:
            {
                'user_id': 5,
                'role': 'user',
                'role_id': 2,
                'modules': [
                    {
                        'module_key': 'quotes',
                        'has_access': True,
                        'access_source': 'role',
                        'individual_override': None
                    },
                    {
                        'module_key': 'production',
                        'has_access': True,
                        'access_source': 'individual',
                        'individual_override': 'grant'
                    }
                ]
            }
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'error': 'User not found'}
            
            result = {
                'user_id': user_id,
                'email': user.email,
                'role': user.assigned_role.role_name if user.assigned_role else None,
                'role_id': user.role_id,
                'modules': []
            }
            
            # Pobierz wszystkie moduły
            all_modules = Module.query.filter_by(is_active=True).order_by(Module.sort_order).all()
            
            for module in all_modules:
                # Sprawdź indywidualne nadpisanie
                individual = UserPermission.query.filter_by(
                    user_id=user_id,
                    module_id=module.id
                ).first()
                
                has_access = PermissionService.user_has_module_access(user_id, module.module_key)
                access_source = PermissionService._get_access_source(user_id, module.id)
                
                result['modules'].append({
                    'module_key': module.module_key,
                    'display_name': module.display_name,
                    'has_access': has_access,
                    'access_source': access_source,
                    'individual_override': individual.access_type if individual else None
                })
            
            return result
        
        except Exception as e:
            logger.exception(f"Błąd pobierania szczegółów uprawnień dla user_id={user_id}: {e}")
            return {'error': str(e)}