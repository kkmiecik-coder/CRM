# app/modules/users/services/role_service.py
"""
Serwis zarządzania rolami i ich uprawnieniami
==============================================

Logika biznesowa dla operacji na rolach:
- Pobieranie ról z modułami
- Tworzenie i edycja ról
- Zarządzanie uprawnieniami ról
- Walidacja zmian

Autor: Konrad Kmiecik + Claude AI
Data: 2025-01-13
"""

from extensions import db
from ..models import Role, RolePermission, Module, User
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class RoleService:
    """Serwis zarządzania rolami i uprawnieniami"""
    
    @staticmethod
    def get_all_roles(active_only: bool = True) -> List[Role]:
        """
        Pobiera wszystkie role
        
        Args:
            active_only (bool): Czy tylko aktywne role
        
        Returns:
            List[Role]: Lista ról
        """
        try:
            query = Role.query
            
            if active_only:
                query = query.filter_by(is_active=True)
            
            return query.order_by(Role.id).all()
        
        except Exception as e:
            logger.exception(f"Błąd pobierania ról: {e}")
            return []
    
    @staticmethod
    def get_role_by_id(role_id: int) -> Optional[Role]:
        """
        Pobiera rolę po ID
        
        Args:
            role_id (int): ID roli
        
        Returns:
            Role lub None
        """
        return Role.query.get(role_id)
    
    @staticmethod
    def get_role_by_name(role_name: str) -> Optional[Role]:
        """
        Pobiera rolę po nazwie
        
        Args:
            role_name (str): Nazwa roli (np. 'admin', 'user')
        
        Returns:
            Role lub None
        """
        return Role.query.filter_by(role_name=role_name).first()
    
    @staticmethod
    def get_role_with_modules(role_id: int) -> Dict[str, Any]:
        """
        Pobiera rolę wraz z listą modułów do których ma dostęp
        
        Args:
            role_id (int): ID roli
        
        Returns:
            dict: Dane roli z listą modułów
            
        Example:
            {
                'role_id': 1,
                'role_name': 'admin',
                'display_name': 'Administrator',
                'modules': [
                    {
                        'module_id': 2,
                        'module_key': 'quotes',
                        'display_name': 'Wyceny',
                        'icon': '📊',
                        'has_access': True
                    },
                    ...
                ]
            }
        """
        try:
            role = Role.query.get(role_id)
            if not role:
                return {'error': 'Role not found'}
            
            # Pobierz wszystkie aktywne moduły
            all_modules = Module.query.filter_by(is_active=True).order_by(Module.sort_order).all()
            
            # Pobierz uprawnienia roli
            role_permissions = {
                rp.module_id: True 
                for rp in RolePermission.query.filter_by(role_id=role_id).all()
            }
            
            modules_list = []
            for module in all_modules:
                # Moduły public (np. dashboard) pomijamy - są zawsze dostępne
                if module.access_type == 'public':
                    continue
                
                modules_list.append({
                    'module_id': module.id,
                    'module_key': module.module_key,
                    'display_name': module.display_name,
                    'icon': module.icon,
                    'access_type': module.access_type,
                    'has_access': module.id in role_permissions
                })
            
            return {
                'role_id': role.id,
                'role_name': role.role_name,
                'display_name': role.display_name,
                'description': role.description,
                'is_system': role.is_system,
                'is_active': role.is_active,
                'modules': modules_list
            }
        
        except Exception as e:
            logger.exception(f"Błąd pobierania roli z modułami: {e}")
            return {'error': str(e)}
    
    @staticmethod
    def create_role(role_name: str, display_name: str, 
                   description: str = None, module_ids: List[int] = None) -> Role:
        """
        Tworzy nową rolę
        
        Args:
            role_name (str): Klucz roli (np. 'manager')
            display_name (str): Nazwa wyświetlana (np. 'Manager')
            description (str): Opis roli
            module_ids (List[int]): Lista ID modułów do przypisania
        
        Returns:
            Role: Utworzona rola
        
        Raises:
            ValueError: Jeśli rola już istnieje
        """
        try:
            # Sprawdź czy rola już istnieje
            existing = Role.query.filter_by(role_name=role_name).first()
            if existing:
                raise ValueError(f"Rola '{role_name}' już istnieje")
            
            # Utwórz rolę
            role = Role(
                role_name=role_name,
                display_name=display_name,
                description=description,
                is_system=False,  # Nowe role nie są systemowe
                is_active=True
            )
            
            db.session.add(role)
            db.session.flush()  # Pobierz ID bez commita
            
            # Przypisz moduły jeśli podano
            if module_ids:
                for module_id in module_ids:
                    perm = RolePermission(
                        role_id=role.id,
                        module_id=module_id
                    )
                    db.session.add(perm)
            
            db.session.commit()
            logger.info(f"Utworzono rolę: {role_name} (ID: {role.id})")
            
            return role
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd tworzenia roli: {e}")
            raise
    
    @staticmethod
    def update_role_permissions(role_id: int, module_ids: List[int], 
                               changed_by_user_id: int = None) -> bool:
        """
        Aktualizuje uprawnienia roli (które moduły ma)
        
        Args:
            role_id (int): ID roli
            module_ids (List[int]): Lista ID modułów które rola powinna mieć
            changed_by_user_id (int): ID użytkownika wykonującego zmianę
        
        Returns:
            bool: True jeśli sukces
        
        Raises:
            ValueError: Jeśli rola systemowa lub nie istnieje
        """
        try:
            role = Role.query.get(role_id)
            if not role:
                raise ValueError(f"Rola o ID {role_id} nie istnieje")
            
            # Zabezpieczenie - możemy edytować uprawnienia ról systemowych
            # (ale nie usuwać ich)
            
            # Usuń stare uprawnienia
            RolePermission.query.filter_by(role_id=role_id).delete()
            
            # Dodaj nowe uprawnienia
            for module_id in module_ids:
                # Sprawdź czy moduł istnieje
                module = Module.query.get(module_id)
                if not module:
                    logger.warning(f"Moduł o ID {module_id} nie istnieje - pomijam")
                    continue
                
                perm = RolePermission(
                    role_id=role_id,
                    module_id=module_id,
                    created_by_user_id=changed_by_user_id
                )
                db.session.add(perm)
            
            db.session.commit()
            
            logger.info(
                f"Zaktualizowano uprawnienia roli {role.role_name} (ID: {role_id}), "
                f"moduły: {module_ids}"
            )
            
            return True
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd aktualizacji uprawnień roli: {e}")
            raise
    
    @staticmethod
    def delete_role(role_id: int, force: bool = False) -> bool:
        """
        Usuwa rolę
        
        Args:
            role_id (int): ID roli
            force (bool): Czy wymusić usunięcie (nawet jeśli ma użytkowników)
        
        Returns:
            bool: True jeśli usunięto
        
        Raises:
            ValueError: Jeśli rola systemowa lub ma użytkowników
        """
        try:
            role = Role.query.get(role_id)
            if not role:
                raise ValueError(f"Rola o ID {role_id} nie istnieje")
            
            # Zabezpieczenie - nie usuwaj ról systemowych
            if role.is_system and not force:
                raise ValueError(
                    f"Nie można usunąć roli systemowej '{role.role_name}' "
                    f"bez parametru force=True"
                )
            
            # Sprawdź czy są użytkownicy z tą rolą
            users_count = User.query.filter_by(role_id=role_id).count()
            if users_count > 0 and not force:
                raise ValueError(
                    f"Nie można usunąć roli - ma {users_count} użytkowników. "
                    f"Najpierw zmień ich role lub użyj force=True"
                )
            
            # Usuń rolę (kaskadowo usuną się też RolePermission)
            db.session.delete(role)
            db.session.commit()
            
            logger.info(f"Usunięto rolę: {role.role_name} (ID: {role_id})")
            
            return True
        
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Błąd usuwania roli: {e}")
            raise
    
    @staticmethod
    def get_users_count_by_role(role_id: int) -> int:
        """
        Zwraca liczbę użytkowników przypisanych do roli
        
        Args:
            role_id (int): ID roli
        
        Returns:
            int: Liczba użytkowników
        """
        try:
            return User.query.filter_by(role_id=role_id).count()
        except Exception as e:
            logger.exception(f"Błąd liczenia użytkowników roli: {e}")
            return 0
    
    @staticmethod
    def get_role_statistics() -> Dict[str, Any]:
        """
        Zwraca statystyki ról
        
        Returns:
            dict: Statystyki
            
        Example:
            {
                'total_roles': 5,
                'active_roles': 4,
                'system_roles': 3,
                'roles': [
                    {
                        'role_name': 'admin',
                        'display_name': 'Administrator',
                        'users_count': 3,
                        'modules_count': 10
                    },
                    ...
                ]
            }
        """
        try:
            all_roles = Role.query.all()
            active_roles = [r for r in all_roles if r.is_active]
            system_roles = [r for r in all_roles if r.is_system]
            
            roles_data = []
            for role in all_roles:
                users_count = User.query.filter_by(role_id=role.id).count()
                modules_count = RolePermission.query.filter_by(role_id=role.id).count()
                
                roles_data.append({
                    'role_id': role.id,
                    'role_name': role.role_name,
                    'display_name': role.display_name,
                    'users_count': users_count,
                    'modules_count': modules_count,
                    'is_system': role.is_system,
                    'is_active': role.is_active
                })
            
            return {
                'total_roles': len(all_roles),
                'active_roles': len(active_roles),
                'system_roles': len(system_roles),
                'roles': roles_data
            }
        
        except Exception as e:
            logger.exception(f"Błąd pobierania statystyk ról: {e}")
            return {'error': str(e)}