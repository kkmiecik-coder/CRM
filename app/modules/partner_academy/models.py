# app/modules/partner_academy/models.py
"""
Partner Academy Models
======================

Modele dla systemu rekrutacji i szkoleń partnerów handlowych.

Tabele:
- partner_applications: Dane aplikacji rekrutacyjnych
- partner_learning_sessions: Sesje e-learningowe i progress tracking

Autor: Development Team
Data: 2025-09-30
Ostatnia aktualizacja: 2025-10-02 - Poprawka nazwy kolumny adress -> address
"""

from extensions import db
from datetime import datetime
from sqlalchemy import JSON, Text

class PartnerApplication(db.Model):
    """
    Model dla aplikacji rekrutacyjnych partnerów
    
    Przechowuje dane z formularza rekrutacyjnego, plik NDA,
    zgody RODO i status aplikacji.
    """
    __tablename__ = 'partner_applications'
    
    # ============================================================================
    # PRIMARY KEY
    # ============================================================================
    id = db.Column(db.Integer, primary_key=True)
    
    # ============================================================================
    # DANE OSOBOWE
    # ============================================================================
    first_name = db.Column(db.String(100), nullable=False, comment='Imię kandydata')
    last_name = db.Column(db.String(100), nullable=False, comment='Nazwisko kandydata')
    email = db.Column(db.String(255), nullable=False, unique=True, index=True, comment='Email kontaktowy')
    phone = db.Column(db.String(20), nullable=False, comment='Numer telefonu')
    city = db.Column(db.String(100), nullable=False, comment='Miasto')
    address = db.Column(db.String(255), nullable=False, comment='Adres (ulica i numer)')  # POPRAWIONO: adress -> address
    postal_code = db.Column(db.String(6), nullable=False, comment='Kod pocztowy kandydata (format: 00-000)')
    pesel = db.Column(db.String(11), nullable=False, comment='PESEL kandydata')
    voivodeship = db.Column(db.String(50), nullable=False, comment='Województwo działalności')
    business_location = db.Column(db.String(100), nullable=False, comment='Miejscowość działalności')
    
    # ============================================================================
    # DODATKOWE INFORMACJE
    # ============================================================================
    about_text = db.Column(db.Text, comment='Tekst o sobie (dlaczego chcę zostać partnerem)')
    
    # ============================================================================
    # DANE B2B (OPCJONALNE)
    # ============================================================================
    is_b2b = db.Column(db.Boolean, default=False, nullable=False, comment='Czy rozliczenie jako firma (B2B)')
    company_name = db.Column(db.String(255), comment='Nazwa firmy (tylko B2B)')
    nip = db.Column(db.String(10), comment='NIP firmy (tylko B2B)')
    regon = db.Column(db.String(14), comment='REGON firmy (opcjonalnie)')
    company_address = db.Column(db.String(255), comment='Adres firmy - ulica i numer')
    company_city = db.Column(db.String(100), comment='Miasto firmy')
    company_postal_code = db.Column(db.String(6), comment='Kod pocztowy firmy (format: 00-000)')
    
    # ============================================================================
    # ZGODY RODO
    # ============================================================================
    data_processing_consent = db.Column(
        db.Boolean, 
        nullable=False, 
        default=False,
        comment='Zgoda na przetwarzanie danych osobowych (wymagana)'
    )
    
    # ============================================================================
    # PLIK NDA
    # ============================================================================
    nda_filename = db.Column(db.String(255), comment='Nazwa pliku NDA')
    nda_filepath = db.Column(db.String(500), comment='Ścieżka do pliku NDA')
    nda_filesize = db.Column(db.Integer, comment='Rozmiar pliku w bajtach')
    nda_mime_type = db.Column(db.String(100), comment='Typ MIME pliku')
    
    # ============================================================================
    # NOTATKI ADMINA
    # ============================================================================
    notes = db.Column(
        Text,
        default='[]',
        comment='Notatki admina w formacie JSON [{timestamp, author, text}]'
    )

    # ============================================================================
    # STATUS APLIKACJI
    # ============================================================================
    status = db.Column(
        db.String(50), 
        default='pending', 
        index=True,
        comment='Status: pending, contacted, rejected, accepted'
    )
    
    # ============================================================================
    # METADATA
    # ============================================================================
    created_at = db.Column(
        db.DateTime, 
        default=datetime.utcnow, 
        nullable=False,
        index=True,
        comment='Data utworzenia aplikacji'
    )
    updated_at = db.Column(
        db.DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        comment='Data ostatniej aktualizacji'
    )
    ip_address = db.Column(db.String(45), comment='Adres IP kandydata')
    user_agent = db.Column(db.Text, comment='User agent przeglądarki')
    
    def to_dict(self):
        """Konwersja do słownika (dla JSON API)"""
        result = {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'city': self.city,
            'address': self.address,  # POPRAWIONO: locality -> address
            'postal_code': self.postal_code,
            'pesel': self.pesel,
            'voivodeship': self.voivodeship,
            'business_location': self.business_location,
            'about_text': self.about_text,
            'is_b2b': self.is_b2b,
            'status': self.status,
            'has_nda_file': bool(self.nda_filepath),
            'notes': self.notes or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        # Dodaj dane B2B tylko jeśli is_b2b=True
        if self.is_b2b:
            result.update({
                'company_name': self.company_name,
                'nip': self.nip,
                'regon': self.regon,
                'company_address': self.company_address,
                'company_city': self.company_city,
                'company_postal_code': self.company_postal_code
            })
        
        return result
    
    def __repr__(self):
        return f'<PartnerApplication {self.email} - {self.status}>'


class PartnerLearningSession(db.Model):
    """
    Model dla sesji e-learningowych partnerów
    
    Przechowuje progress użytkownika na platformie szkoleniowej,
    wyniki quizów, czasy spędzone na poszczególnych krokach.
    """
    __tablename__ = 'partner_learning_sessions'
    
    # PRIMARY KEY
    id = db.Column(db.Integer, primary_key=True)
    
    # DANE SESJI
    session_id = db.Column(db.String(64), nullable=False, unique=True, index=True, comment='Unikalny identyfikator sesji')
    current_step = db.Column(db.String(10), default='1.1', comment='Aktualny krok (np. 1.1, M1, 3.1)')
    
    # PROGRESS TRACKING
    completed_steps = db.Column(JSON, default=list, comment='Lista ukończonych kroków')
    locked_steps = db.Column(JSON, default=list, comment='Lista zablokowanych kroków')
    
    # QUIZ RESULTS
    quiz_results = db.Column(JSON, default=dict, comment='Wyniki quizów: {M1: {attempts: 2, passed: true}}')
    
    # TIME TRACKING
    total_time_spent = db.Column(db.Integer, default=0, comment='Całkowity czas spędzony w sekundach')
    step_times = db.Column(JSON, default=dict, comment='Czasy spędzone na krokach: {1.1: 300, 1.2: 450}')
    last_activity_at = db.Column(db.DateTime, comment='Ostatnia aktywność')
    
    # METADATA
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, comment='Data utworzenia sesji')
    completed_at = db.Column(db.DateTime, comment='Data ukończenia szkolenia')
    
    def __repr__(self):
        return f'<PartnerLearningSession {self.session_id} - Step {self.current_step}>'