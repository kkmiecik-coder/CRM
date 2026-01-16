# app/modules/dashboard/services/user_activity_service.py

"""
Serwis do zarządzania aktywnością użytkowników i sesjami
"""

from datetime import datetime, timedelta
from flask import session, request
from extensions import db
from ..models import UserSession
from ...calculator.models import User
import logging
import secrets

logger = logging.getLogger(__name__)

class UserActivityService:
    """Serwis zarządzania aktywnością użytkowników"""
    
    @staticmethod
    def create_session(user_id, ip_address=None, user_agent=None):
        """
        Tworzy nową sesję użytkownika przy logowaniu
        
        Args:
            user_id (int): ID użytkownika
            ip_address (str): Adres IP
            user_agent (str): User agent przeglądarki
            
        Returns:
            UserSession: Utworzona sesja
        """
        try:
            # Oznacz wszystkie poprzednie sesje tego użytkownika jako nieaktywne
            UserSession.query.filter_by(user_id=user_id, is_active=True).update({
                'is_active': False,
                'logout_time': datetime.utcnow()
            })
            
            # Utwórz nową sesję
            new_session = UserSession(
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                current_page='dashboard.dashboard'
            )
            
            db.session.add(new_session)
            db.session.commit()
            
            # Zapisz token sesji w Flask session
            session['user_session_token'] = new_session.session_token
            
            logger.info(f"[UserActivity] Utworzono nową sesję dla user_id={user_id}, token={new_session.session_token[:8]}...")
            return new_session
            
        except Exception as e:
            db.session.rollback()
            logger.exception(f"[UserActivity] Błąd tworzenia sesji dla user_id={user_id}: {e}")
            return None
    
    @staticmethod
    def update_activity(user_id=None, current_page=None, ip_address=None):
        """
        Aktualizuje aktywność użytkownika
        
        Args:
            user_id (int): ID użytkownika
            current_page (str): Aktualna strona/endpoint
            ip_address (str): Adres IP
            
        Returns:
            bool: Czy udało się zaktualizować
        """
        try:
            # Pobierz token sesji z Flask session
            session_token = session.get('user_session_token')
            if not session_token:
                logger.debug("[UserActivity] Brak tokenu sesji w Flask session")
                return False
            
            # Znajdź aktywną sesję
            user_session = UserSession.query.filter_by(
                session_token=session_token,
                is_active=True
            ).first()
            
            if not user_session:
                logger.debug(f"[UserActivity] Nie znaleziono aktywnej sesji dla tokenu {session_token[:8]}...")
                return False
            
            # Aktualizuj aktywność
            user_session.last_activity_at = datetime.utcnow()
            if current_page:
                user_session.current_page = current_page
            if ip_address:
                user_session.ip_address = ip_address
                
            db.session.commit()
            
            logger.debug(f"[UserActivity] Zaktualizowano aktywność user_id={user_session.user_id}, page={current_page}")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.exception(f"[UserActivity] Błąd aktualizacji aktywności: {e}")
            return False
    
    @staticmethod
    def end_session(user_id=None, session_token=None):
        """
        Kończy sesję użytkownika przy wylogowaniu
        
        Args:
            user_id (int): ID użytkownika
            session_token (str): Token sesji
            
        Returns:
            bool: Czy udało się zakończyć sesję
        """
        try:
            # Użyj tokenu z argumentu lub z Flask session
            token = session_token or session.get('user_session_token')
            
            if token:
                user_session = UserSession.query.filter_by(
                    session_token=token,
                    is_active=True
                ).first()
            elif user_id:
                user_session = UserSession.query.filter_by(
                    user_id=user_id,
                    is_active=True
                ).first()
            else:
                logger.warning("[UserActivity] Brak danych do zakończenia sesji")
                return False
            
            if user_session:
                user_session.is_active = False
                user_session.logout_time = datetime.utcnow()
                db.session.commit()
                
                logger.info(f"[UserActivity] Zakończono sesję user_id={user_session.user_id}")
                return True
            else:
                logger.debug("[UserActivity] Nie znaleziono aktywnej sesji do zakończenia")
                return False
                
        except Exception as e:
            db.session.rollback()
            logger.exception(f"[UserActivity] Błąd kończenia sesji: {e}")
            return False
    
    @staticmethod
    def get_active_users(minutes_threshold=15):
        """
        Pobiera listę aktywnych użytkowników
        
        Args:
            minutes_threshold (int): Próg nieaktywności w minutach
            
        Returns:
            list: Lista słowników z danymi aktywnych użytkowników
        """
        try:
            from flask import url_for
            
            active_sessions = UserSession.get_active_sessions(minutes_threshold)
            
            users_data = []
            for session in active_sessions:
                user_data = session.to_dict()
                
                # ✅ POPRAWKA - przetwórz avatar_path przez url_for
                if 'user_avatar' in user_data and user_data['user_avatar']:
                    # Jeśli avatar_path nie zaczyna się od /static/, dodaj prefix
                    if not user_data['user_avatar'].startswith('/static/'):
                        user_data['user_avatar'] = url_for('static', filename=user_data['user_avatar'])
                elif 'user_avatar' in user_data:
                    # Fallback do domyślnego avatara
                    user_data['user_avatar'] = url_for('static', filename='images/avatars/default_avatars/avatar1.svg')
                
                users_data.append(user_data)
            
            return users_data
            
        except Exception as e:
            logger.exception(f"[UserActivity] Błąd pobierania aktywnych użytkowników: {e}")
            return []
    
    @staticmethod
    def get_user_activity_stats():
        """
        Pobiera statystyki aktywności użytkowników
        
        Returns:
            dict: Statystyki aktywności
        """
        try:
            now = datetime.utcnow()
            
            # Aktywni w ostatnich 15 minutach
            active_15min = UserSession.query.filter(
                UserSession.is_active == True,
                UserSession.last_activity_at >= now - timedelta(minutes=15)
            ).count()
            
            # Aktywni w ostatniej godzinie
            active_1hour = UserSession.query.filter(
                UserSession.last_activity_at >= now - timedelta(hours=1)
            ).count()
            
            # Aktywni dzisiaj
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            active_today = UserSession.query.filter(
                UserSession.last_activity_at >= today_start
            ).count()
            
            # Łączna liczba użytkowników
            total_users = User.query.filter_by(active=True).count()
            
            stats = {
                'active_now': active_15min,
                'active_hour': active_1hour,
                'active_today': active_today,
                'total_users': total_users,
                'activity_rate': round((active_15min / total_users * 100) if total_users > 0 else 0, 1)
            }
            
            logger.debug(f"[UserActivity] Statystyki aktywności: {stats}")
            return stats
            
        except Exception as e:
            logger.exception(f"[UserActivity] Błąd pobierania statystyk aktywności: {e}")
            return {
                'active_now': 0,
                'active_hour': 0,
                'active_today': 0,
                'total_users': 0,
                'activity_rate': 0
            }
    
    @staticmethod
    def force_logout_user(user_id, admin_user_id):
        """
        Wymusza wylogowanie użytkownika (tylko dla adminów)
        
        Args:
            user_id (int): ID użytkownika do wylogowania
            admin_user_id (int): ID administratora wykonującego akcję
            
        Returns:
            dict: Wynik operacji
        """
        try:
            # Sprawdź czy admin ma uprawnienia
            admin_user = User.query.get(admin_user_id)
            if not admin_user or admin_user.role != 'admin':
                return {
                    'success': False,
                    'error': 'Brak uprawnień administratora'
                }
            
            # Znajdź aktywne sesje użytkownika
            active_sessions = UserSession.query.filter_by(
                user_id=user_id,
                is_active=True
            ).all()
            
            if not active_sessions:
                return {
                    'success': False,
                    'error': 'Użytkownik nie ma aktywnych sesji'
                }
            
            # Wyloguj wszystkie sesje
            for session in active_sessions:
                session.force_logout()
            
            user = User.query.get(user_id)
            user_name = f"{user.first_name} {user.last_name}".strip() or user.email if user else f"ID:{user_id}"
            
            logger.info(f"[UserActivity] Admin {admin_user.email} wylogował użytkownika {user_name} (ID:{user_id})")
            
            return {
                'success': True,
                'message': f'Użytkownik {user_name} został wylogowany',
                'sessions_closed': len(active_sessions)
            }
            
        except Exception as e:
            logger.exception(f"[UserActivity] Błąd wymuszania wylogowania user_id={user_id}: {e}")
            return {
                'success': False,
                'error': f'Błąd systemu: {str(e)}'
            }
    
    @staticmethod
    def cleanup_old_sessions(days_threshold=30):
        """
        Czyści stare sesje (zadanie w tle)
        
        Args:
            days_threshold (int): Próg w dniach
            
        Returns:
            dict: Wynik czyszczenia
        """
        try:
            # Usuń stare sesje
            deleted_count = UserSession.cleanup_old_sessions(days_threshold)
            
            # Oznacz nieaktywne sesje
            inactive_count = UserSession.mark_inactive_sessions(minutes_threshold=15)
            
            logger.info(f"[UserActivity] Cleanup: usunięto {deleted_count} starych sesji, "
                       f"oznaczono {inactive_count} jako nieaktywne")
            
            return {
                'success': True,
                'deleted_sessions': deleted_count,
                'marked_inactive': inactive_count
            }
            
        except Exception as e:
            logger.exception(f"[UserActivity] Błąd czyszczenia sesji: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_user_session_history(user_id, days=7):
        """
        Pobiera historię sesji użytkownika
        
        Args:
            user_id (int): ID użytkownika
            days (int): Liczba dni wstecz
            
        Returns:
            list: Historia sesji
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            sessions = UserSession.query.filter(
                UserSession.user_id == user_id,
                UserSession.created_at >= start_date
            ).order_by(UserSession.created_at.desc()).all()
            
            history = []
            for session in sessions:
                history.append({
                    'id': session.id,
                    'created_at': session.created_at.isoformat(),
                    'logout_time': session.logout_time.isoformat() if session.logout_time else None,
                    'duration': session.get_session_duration(),
                    'ip_address': session.ip_address,
                    'last_page': session.current_page,
                    'is_active': session.is_active
                })
            
            return history
            
        except Exception as e:
            logger.exception(f"[UserActivity] Błąd pobierania historii user_id={user_id}: {e}")
            return []