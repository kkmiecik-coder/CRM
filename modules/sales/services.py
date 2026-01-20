# app/modules/sales/services.py
"""
Sales Services
==============

Warstwa logiki biznesowej dla modułu Sales.

Services:
- ApplicationService: Obsługa aplikacji rekrutacyjnych
- EmailService: Wysyłka emaili (potwierdzenia, notyfikacje)

Autor: Development Team
Data: 2025-10-24
"""

import os
from werkzeug.utils import secure_filename
from flask import current_app, render_template
from flask_mail import Message
from extensions import db, mail
from modules.sales.models import SalesApplication
from datetime import datetime
import uuid
import json

# Opcjonalny import magic (może nie działać na Windows)
try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False
    print("[sales] Biblioteka 'magic' niedostępna - walidacja MIME będzie ograniczona")


class ApplicationService:
    """Serwis zarządzania aplikacjami rekrutacyjnymi"""
    
    # Konfiguracja uploadów
    UPLOAD_FOLDER = 'modules/sales/static/media/nda_users/'
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'docx', 'odt'}
    ALLOWED_MIME_TYPES = {
        'application/pdf',
        'image/jpeg',
        'image/png',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.oasis.opendocument.text'
    }
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    @classmethod
    def create_application(cls, form_data, files, ip_address, user_agent):
        """
        Utworzenie nowej aplikacji rekrutacyjnej z plikami NDA

        Args:
            form_data (dict): Dane z formularza
            files (list): Lista plików NDA (min 1, max 2)
            ip_address (str): Adres IP użytkownika
            user_agent (str): User agent przeglądarki

        Returns:
            SalesApplication: Utworzona aplikacja

        Raises:
            ValueError: Błędy walidacji
        """

        # Upewnij się że folder istnieje
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)

        # Lista zapisanych plików (do rollbacku w razie błędu)
        saved_files = []
        nda_data = {}

        try:
            # Przetwórz pliki NDA (max 2)
            for i, file in enumerate(files):
                if not file or not file.filename:
                    continue

                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{timestamp}_nda{i+1}_{filename}"

                filepath = os.path.join(cls.UPLOAD_FOLDER, unique_filename)
                file.save(filepath)
                saved_files.append(filepath)

                # Pobierz info o pliku
                filesize = os.path.getsize(filepath)
                if HAS_MAGIC:
                    mime_type = magic.from_file(filepath, mime=True)
                else:
                    # Fallback - określ MIME na podstawie rozszerzenia
                    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                    mime_map = {
                        'pdf': 'application/pdf',
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'png': 'image/png',
                        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'odt': 'application/vnd.oasis.opendocument.text'
                    }
                    mime_type = mime_map.get(ext, 'application/octet-stream')

                if i == 0:
                    # Pierwszy plik - istniejące kolumny
                    nda_data['nda_filename'] = unique_filename
                    nda_data['nda_filepath'] = filepath
                    nda_data['nda_filesize'] = filesize
                    nda_data['nda_mime_type'] = mime_type
                else:
                    # Drugi plik - nowe kolumny z sufiksem _2
                    nda_data['nda_filename_2'] = unique_filename
                    nda_data['nda_filepath_2'] = filepath
                    nda_data['nda_filesize_2'] = filesize
                    nda_data['nda_mime_type_2'] = mime_type

            # Przygotuj dane podstawowe
            application_data = {
                'first_name': form_data['first_name'],
                'last_name': form_data['last_name'],
                'email': form_data['email'],
                'phone': form_data['phone'],
                'city': form_data['city'],
                'address': form_data['address'],
                'postal_code': form_data['postal_code'],
                'voivodeship': form_data['voivodeship'],
                'business_location': form_data['business_location'],
                'about_text': form_data.get('about_text', ''),
                'data_processing_consent': form_data.get('data_processing_consent', 'off') == 'on',
                **nda_data,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'status': 'pending'
            }

            # Obsługa danych B2B
            is_b2b = form_data.get('cooperation_type') == 'b2b'
            application_data['is_b2b'] = is_b2b

            if is_b2b:
                application_data.update({
                    'company_name': form_data.get('company_name', ''),
                    'nip': form_data.get('nip', ''),
                    'regon': form_data.get('regon', ''),
                    'company_address': form_data.get('company_address', ''),
                    'company_city': form_data.get('company_city', ''),
                    'company_postal_code': form_data.get('company_postal_code', '')
                })

            # Utwórz rekord w bazie
            application = SalesApplication(**application_data)

            db.session.add(application)
            db.session.commit()

            current_app.logger.info(
                f"Utworzono aplikację: {application.email} (ID: {application.id}) z {len(saved_files)} plikami NDA"
            )

            return application

        except Exception as e:
            db.session.rollback()
            # Usuń wszystkie zapisane pliki jeśli nie udało się zapisać do bazy
            for filepath in saved_files:
                if os.path.exists(filepath):
                    os.remove(filepath)
            raise e
    
    @classmethod
    def get_application_by_id(cls, application_id):
        """Pobierz aplikację po ID"""
        return SalesApplication.query.get(application_id)
    
    @classmethod
    def get_application_by_email(cls, email):
        """Pobierz aplikację po email"""
        return SalesApplication.query.filter_by(email=email).first()
    
    @classmethod
    def update_application_status(cls, application_id, new_status, notes=None):
        """
        Aktualizacja statusu aplikacji
        
        Args:
            application_id (int): ID aplikacji
            new_status (str): Nowy status (pending, contacted, rejected, accepted)
            notes (str, optional): Notatka do dodania
        """
        application = cls.get_application_by_id(application_id)
        
        if not application:
            raise ValueError(f"Aplikacja o ID {application_id} nie istnieje")
        
        # Sprawdź czy status jest prawidłowy
        valid_statuses = ['pending', 'contacted', 'rejected', 'accepted']
        if new_status not in valid_statuses:
            raise ValueError(f"Nieprawidłowy status: {new_status}")
        
        application.status = new_status
        application.updated_at = datetime.utcnow()
        
        # Dodaj notatkę jeśli została przekazana
        if notes:
            import json
            current_notes = json.loads(application.notes) if application.notes else []
            current_notes.append({
                'timestamp': datetime.utcnow().isoformat(),
                'author': 'system',
                'text': notes
            })
            application.notes = json.dumps(current_notes)
        
        db.session.commit()
        
        current_app.logger.info(
            f"Zaktualizowano status aplikacji {application_id}: {new_status}"
        )
        
        return application
    
    @classmethod
    def get_nda_file_path(cls, application_id):
        """Pobierz ścieżkę do pliku NDA"""
        application = cls.get_application_by_id(application_id)
        if application and application.nda_filepath:
            return application.nda_filepath
        return None


class EmailService:
    """Serwis wysyłki emaili"""
    
    @staticmethod
    def _load_mail_addresses():
        """Wczytaj adresy email z pliku konfiguracyjnego"""
        try:
            # Ścieżka relatywna od services.py
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, 'config', 'mail_addresses.json')
        
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            current_app.logger.error(f"Błąd wczytywania mail_addresses.json: {str(e)}")
            return {"notification_emails": [], "confirmation_emails": []}
    
    @staticmethod
    def send_application_confirmation(application):
        """
        Wyślij email potwierdzający otrzymanie aplikacji
        
        Args:
            application (SalesApplication): Aplikacja rekrutacyjna
        """
        try:
            sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
            
            msg = Message(
                subject='Potwierdzenie otrzymania aplikacji - WoodPower Sales',
                sender=sender,
                recipients=[application.email]
            )
            
            msg.html = render_template(
                'emails/application_received.html',
                first_name=application.first_name,
                last_name=application.last_name,
                email=application.email,
                phone=application.phone,
                city=application.city,
                address=application.address,
                is_b2b=application.is_b2b,
                company_name=application.company_name if application.is_b2b else None
            )
            
            mail.send(msg)
            
            current_app.logger.info(
                f"Wysłano email potwierdzający do: {application.email}"
            )
            
        except Exception as e:
            current_app.logger.error(
                f"Błąd wysyłki emaila do {application.email}: {str(e)}"
            )
            raise
    
    @staticmethod
    def send_admin_notification(application):
        """
        Wyślij notyfikację do admina o nowej aplikacji
        
        Args:
            application (SalesApplication): Aplikacja rekrutacyjna
        """
        try:
            # Wczytaj adresy z pliku konfiguracyjnego
            mail_config = EmailService._load_mail_addresses()
            notification_emails = mail_config.get('notification_emails', [])
            
            if not notification_emails:
                current_app.logger.warning("Brak adresów w notification_emails w mail_addresses.json")
                return
            
            sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
            
            msg = Message(
                subject=f'🎯 Nowa aplikacja Sales: {application.first_name} {application.last_name}',
                sender=sender,
                recipients=notification_emails  # Lista adresów z pliku JSON
            )
            
            msg.html = render_template(
                'emails/application_notification.html',
                application=application
            )
            
            # Dodaj załącznik NDA 1 jeśli istnieje
            if application.nda_filepath and os.path.exists(application.nda_filepath):
                with open(application.nda_filepath, 'rb') as f:
                    msg.attach(
                        application.nda_filename,
                        application.nda_mime_type or "application/pdf",
                        f.read()
                    )

            # Dodaj załącznik NDA 2 jeśli istnieje
            if application.nda_filepath_2 and os.path.exists(application.nda_filepath_2):
                with open(application.nda_filepath_2, 'rb') as f:
                    msg.attach(
                        application.nda_filename_2,
                        application.nda_mime_type_2 or "application/pdf",
                        f.read()
                    )

            mail.send(msg)
            
            current_app.logger.info(
                f"Wysłano notyfikację do {len(notification_emails)} adresów o aplikacji: {application.id}"
            )
            
        except Exception as e:
            current_app.logger.error(
                f"Błąd wysyłki notyfikacji do admina: {str(e)}"
            )
            raise
    
    @staticmethod
    def send_status_update(application, new_status):
        """
        Wyślij email o zmianie statusu aplikacji
        
        Args:
            application (SalesApplication): Aplikacja
            new_status (str): Nowy status
        """
        try:
            status_messages = {
                'contacted': 'Skontaktujemy się z Tobą wkrótce',
                'accepted': 'Twoja aplikacja została zaakceptowana!',
                'rejected': 'Informacja o Twojej aplikacji'
            }
            
            subject = f'WoodPower Sales - {status_messages.get(new_status, "Aktualizacja statusu")}'
            
            sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
            
            msg = Message(
                subject=subject,
                sender=sender,
                recipients=[application.email]
            )
            
            msg.html = render_template(
                f'emails/status_{new_status}.html',
                application=application
            )
            
            mail.send(msg)
            
            current_app.logger.info(
                f"Wysłano email o zmianie statusu do: {application.email} ({new_status})"
            )
            
        except Exception as e:
            current_app.logger.error(
                f"Błąd wysyłki emaila o statusie: {str(e)}"
            )
            raise