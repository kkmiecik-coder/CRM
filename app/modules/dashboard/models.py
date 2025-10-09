from extensions import db
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import current_app

class ChangelogEntry(db.Model):
    __tablename__ = 'changelog_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(20), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_visible = db.Column(db.Boolean, default=True)
    
    # Relacje
    items = db.relationship('ChangelogItem', backref='entry', cascade='all, delete-orphan', order_by='ChangelogItem.sort_order')
    creator = db.relationship('User', backref='changelog_entries')
    
    @staticmethod
    def get_next_version():
        """Automatycznie generuje następną wersję"""
        latest = ChangelogEntry.query.order_by(ChangelogEntry.version.desc()).first()
        if not latest:
            return "1.0.0"
        
        # Parsuj aktualną wersję
        version_parts = latest.version.split('.')
        if len(version_parts) == 2:  # X.Y format
            major, minor = int(version_parts[0]), int(version_parts[1])
            return f"{major}.{minor}.1"
        elif len(version_parts) == 3:  # X.Y.Z format
            major, minor, patch = int(version_parts[0]), int(version_parts[1]), int(version_parts[2])
            return f"{major}.{minor}.{patch + 1}"
        else:
            return "1.0.0"
    
    @staticmethod
    def validate_version(version, current_id=None):
        """Waliduje czy wersja jest poprawna"""
        import re
        
        # Sprawdź format
        if not re.match(r'^\d+\.\d+(\.\d+)?$', version):
            return False, "Niepoprawny format wersji. Użyj X.Y lub X.Y.Z"
        
        # Sprawdź czy wersja już istnieje
        query = ChangelogEntry.query.filter_by(version=version)
        if current_id:
            query = query.filter(ChangelogEntry.id != current_id)
        
        if query.first():
            return False, "Ta wersja już istnieje"
        
        # Sprawdź czy nie cofamy się w wersji
        latest = ChangelogEntry.query.order_by(ChangelogEntry.version.desc()).first()
        if latest and current_id != latest.id:
            if version_compare(version, latest.version) <= 0:
                return False, f"Nie możesz utworzyć wersji starszej niż {latest.version}"
        
        return True, None

class ChangelogItem(db.Model):
    __tablename__ = 'changelog_items'
    
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('changelog_entries.id'), nullable=False)
    section_type = db.Column(db.Enum('added', 'improved', 'fixed', 'custom'), nullable=False)
    custom_section_name = db.Column(db.String(100))
    item_text = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

def version_compare(v1, v2):
    """Porównuje wersje. Zwraca: -1 (v1<v2), 0 (v1==v2), 1 (v1>v2)"""
    def normalize(v):
        parts = v.split('.')
        while len(parts) < 3:
            parts.append('0')
        return [int(x) for x in parts]
    
    v1_parts = normalize(v1)
    v2_parts = normalize(v2)
    
    for i in range(3):
        if v1_parts[i] < v2_parts[i]:
            return -1
        elif v1_parts[i] > v2_parts[i]:
            return 1
    return 0

class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_token = db.Column(db.String(255), unique=True, nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    current_page = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    logout_time = db.Column(db.DateTime)
    
    # Relacje
    user = db.relationship('User', backref='sessions')
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.session_token:
            import secrets
            self.session_token = secrets.token_urlsafe(32)
    
    @classmethod
    def get_active_sessions(cls, minutes_threshold=15):
        """
        Pobiera aktywne sesje użytkowników
        
        Args:
            minutes_threshold (int): Próg nieaktywności w minutach
            
        Returns:
            list: Lista aktywnych sesji z użytkownikami
        """
        threshold_time = datetime.utcnow() - timedelta(minutes=minutes_threshold)
        
        return db.session.query(cls).join(cls.user).filter(
            cls.is_active == True,
            cls.last_activity_at >= threshold_time,
            cls.user.has(active=True)
        ).order_by(cls.last_activity_at.desc()).all()
    
    @classmethod
    def cleanup_old_sessions(cls, days_threshold=30):
        """
        Usuwa stare nieaktywne sesje
        
        Args:
            days_threshold (int): Próg w dniach dla usuwania starych sesji
            
        Returns:
            int: Liczba usuniętych sesji
        """
        threshold_time = datetime.utcnow() - timedelta(days=days_threshold)
        
        old_sessions = cls.query.filter(
            cls.last_activity_at < threshold_time
        )
        count = old_sessions.count()
        old_sessions.delete()
        db.session.commit()
        
        return count
    
    @classmethod
    def mark_inactive_sessions(cls, minutes_threshold=15):
        """
        Oznacza sesje jako nieaktywne po przekroczeniu progu
        
        Args:
            minutes_threshold (int): Próg nieaktywności w minutach
            
        Returns:
            int: Liczba oznaczonych sesji
        """
        threshold_time = datetime.utcnow() - timedelta(minutes=minutes_threshold)
        
        inactive_sessions = cls.query.filter(
            cls.is_active == True,
            cls.last_activity_at < threshold_time
        )
        
        count = inactive_sessions.count()
        inactive_sessions.update({'is_active': False})
        db.session.commit()
        
        return count
    
    def update_activity(self, current_page=None):
        """
        Aktualizuje aktywność sesji
        
        Args:
            current_page (str): Aktualna strona/moduł
        """
        self.last_activity_at = datetime.utcnow()
        self.is_active = True
        if current_page:
            self.current_page = current_page
        db.session.commit()
    
    def force_logout(self):
        """
        Wymusza wylogowanie - oznacza sesję jako nieaktywną
        """
        self.is_active = False
        self.logout_time = datetime.utcnow()
        db.session.commit()
    
    def get_status(self):
        """
        Zwraca status aktywności użytkownika
        
        Returns:
            dict: Status z kolorową ikoną i opisem
        """
        if not self.is_active:
            return {
                'status': 'offline',
                'icon': '🔴',
                'description': 'Offline'
            }
        
        time_diff = datetime.utcnow() - self.last_activity_at
        minutes_ago = time_diff.total_seconds() / 60
        
        if minutes_ago <= 2:
            return {
                'status': 'active',
                'icon': '🟢',
                'description': 'Aktywny'
            }
        elif minutes_ago <= 10:
            return {
                'status': 'idle',
                'icon': '🟡',
                'description': 'Bezczynny'
            }
        else:
            return {
                'status': 'away',
                'icon': '🟠',
                'description': 'Nieobecny'
            }
    
    def get_relative_time(self):
        """
        Zwraca czas ostatniej aktywności w czytelnym formacie
        
        Returns:
            str: Relative time string
        """
        if not self.last_activity_at:
            return "Nieznany"
        
        time_diff = datetime.utcnow() - self.last_activity_at
        total_seconds = int(time_diff.total_seconds())
        
        if total_seconds < 60:
            return "przed chwilą"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes} min temu"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h temu"
        else:
            days = total_seconds // 86400
            return f"{days} dni temu"
    
    def get_page_display_name(self):
        """Zwraca czytelną nazwę aktualnej strony"""
        if not self.current_page:
            return "📱 Aplikacja"

        module_name = self.current_page.split('.')[0]
        metadata = current_app.config.get('MODULE_METADATA', {})
        module_meta = metadata.get(module_name)
        if module_meta:
            icon = module_meta.get('icon', '')
            label = module_meta.get('label', module_name.title())
            return f"{icon} {label}".strip()

        # domyślny fallback
        return f"📱 {module_name.title()}"
    
    def to_dict(self):
        """
        Konwertuje sesję do słownika dla API
        
        Returns:
            dict: Słownik z danymi sesji
        """
        status = self.get_status()
        
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': f"{self.user.first_name} {self.user.last_name}".strip() or self.user.email,
            'user_email': self.user.email,
            'user_role': self.user.role,
            'user_avatar': self.user.avatar_path,
            'status': status['status'],
            'status_icon': status['icon'],
            'status_description': status['description'],
            'current_page': self.get_page_display_name(),
            'last_activity': self.get_relative_time(),
            'last_activity_timestamp': self.last_activity_at.isoformat() if self.last_activity_at else None,
            'ip_address': self.ip_address,
            'session_duration': self.get_session_duration(),
            'is_active': self.is_active
        }
    
    def get_session_duration(self):
        """
        Oblicza czas trwania sesji
        
        Returns:
            str: Czas trwania sesji
        """
        if not self.created_at:
            return "Nieznany"
        
        end_time = self.logout_time or datetime.utcnow()
        duration = end_time - self.created_at
        
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes}min"
        else:
            return f"{minutes}min"
    
    def __repr__(self):
        return f"<UserSession {self.id}: User {self.user_id} - {self.get_status()['description']}>"