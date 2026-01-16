"""
FileService - serwis obsługi plików do pobrania na dashboardzie
"""

import os
import uuid
import logging
from werkzeug.utils import secure_filename
from extensions import db
from ..models import DownloadableFile

logger = logging.getLogger(__name__)


class FileService:
    """Serwis do zarządzania plikami do pobrania"""

    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

    # Dozwolone typy plików
    ALLOWED_EXTENSIONS = {
        'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
        'txt', 'csv', 'zip', 'rar', '7z',
        'jpg', 'jpeg', 'png', 'gif', 'svg', 'webp'
    }

    @classmethod
    def get_all_files(cls):
        """Pobiera wszystkie aktywne pliki"""
        return DownloadableFile.query.filter_by(is_active=True)\
            .order_by(DownloadableFile.uploaded_at.desc()).all()

    @classmethod
    def get_file_by_id(cls, file_id: int):
        """Pobiera plik po ID"""
        return DownloadableFile.query.filter_by(id=file_id, is_active=True).first()

    @classmethod
    def save_file(cls, file, display_name: str, user_id: int) -> DownloadableFile:
        """
        Zapisuje plik i tworzy rekord w bazie

        Args:
            file: Obiekt pliku z request.files
            display_name: Nazwa wyświetlana dla użytkowników
            user_id: ID użytkownika uploadującego plik

        Returns:
            DownloadableFile: Utworzony rekord w bazie

        Raises:
            ValueError: Gdy plik jest nieprawidłowy
        """
        if not file or not file.filename:
            raise ValueError("Nie wybrano pliku")

        original_filename = secure_filename(file.filename)
        if not original_filename:
            raise ValueError("Nieprawidłowa nazwa pliku")

        # Pobierz rozszerzenie
        extension = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''

        if extension not in cls.ALLOWED_EXTENSIONS:
            raise ValueError(f"Niedozwolony typ pliku: .{extension}. Dozwolone: {', '.join(cls.ALLOWED_EXTENSIONS)}")

        # Sprawdź rozmiar
        file.seek(0, 2)  # Przejdź na koniec
        file_size = file.tell()
        file.seek(0)  # Wróć na początek

        if file_size > cls.MAX_FILE_SIZE:
            max_mb = cls.MAX_FILE_SIZE // (1024 * 1024)
            raise ValueError(f"Plik za duży. Maksymalny rozmiar: {max_mb} MB")

        if file_size == 0:
            raise ValueError("Plik jest pusty")

        # Generuj unikalną nazwę
        stored_filename = f"{uuid.uuid4().hex}_{original_filename}"

        # Utwórz folder jeśli nie istnieje
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)

        # Zapisz plik
        filepath = os.path.join(cls.UPLOAD_FOLDER, stored_filename)

        try:
            file.save(filepath)
            logger.info(f"[FileService] Zapisano plik: {stored_filename}")
        except Exception as e:
            logger.error(f"[FileService] Błąd zapisu pliku: {e}")
            raise ValueError("Wystąpił błąd podczas zapisywania pliku")

        # Utwórz rekord w bazie
        db_file = DownloadableFile(
            display_name=display_name,
            original_filename=original_filename,
            stored_filename=stored_filename,
            filepath=stored_filename,
            filesize=file_size,
            mimetype=file.content_type,
            extension=extension,
            uploaded_by_id=user_id
        )

        try:
            db.session.add(db_file)
            db.session.commit()
            logger.info(f"[FileService] Utworzono rekord w bazie dla pliku ID: {db_file.id}")
        except Exception as e:
            # Usuń plik jeśli zapis do bazy nie powiódł się
            if os.path.exists(filepath):
                os.remove(filepath)
            logger.error(f"[FileService] Błąd zapisu do bazy: {e}")
            db.session.rollback()
            raise ValueError("Wystąpił błąd podczas zapisywania do bazy danych")

        return db_file

    @classmethod
    def delete_file(cls, file_id: int, hard_delete: bool = False) -> bool:
        """
        Usuwa plik

        Args:
            file_id: ID pliku do usunięcia
            hard_delete: Jeśli True, usuwa fizycznie plik z dysku

        Returns:
            bool: True jeśli usunięto pomyślnie
        """
        db_file = DownloadableFile.query.get(file_id)
        if not db_file:
            return False

        if hard_delete:
            # Fizyczne usunięcie pliku
            filepath = os.path.join(cls.UPLOAD_FOLDER, db_file.stored_filename)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    logger.info(f"[FileService] Usunięto plik z dysku: {db_file.stored_filename}")
                except Exception as e:
                    logger.error(f"[FileService] Błąd usuwania pliku z dysku: {e}")

            # Usuń rekord z bazy
            db.session.delete(db_file)
        else:
            # Soft delete - oznacz jako nieaktywny
            db_file.is_active = False

        db.session.commit()
        logger.info(f"[FileService] Usunięto plik ID: {file_id} (hard_delete={hard_delete})")

        return True

    @classmethod
    def get_file_path(cls, file_id: int) -> tuple:
        """
        Zwraca ścieżkę do pliku i oryginalną nazwę

        Args:
            file_id: ID pliku

        Returns:
            tuple: (ścieżka_do_pliku, oryginalna_nazwa) lub (None, None)
        """
        db_file = DownloadableFile.query.get(file_id)
        if not db_file or not db_file.is_active:
            return None, None

        filepath = os.path.join(cls.UPLOAD_FOLDER, db_file.stored_filename)

        if not os.path.exists(filepath):
            logger.warning(f"[FileService] Plik nie istnieje na dysku: {filepath}")
            return None, None

        return filepath, db_file.original_filename

    @classmethod
    def increment_download_count(cls, file_id: int):
        """Zwiększa licznik pobrań pliku"""
        db_file = DownloadableFile.query.get(file_id)
        if db_file:
            db_file.download_count += 1
            db.session.commit()
