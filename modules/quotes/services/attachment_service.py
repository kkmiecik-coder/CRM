"""
Serwis obsługi załączników do wycen.
Współdzielony przez moduły: calculator, quotes, baselinker.
"""

import os
import uuid
import mimetypes
from werkzeug.utils import secure_filename
from flask import current_app

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'quote_attachments')

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB

BLOCKED_EXTENSIONS = {
    'exe', 'bat', 'sh', 'php', 'py', 'js', 'cmd', 'ps1',
    'vbs', 'com', 'msi', 'scr', 'cgi', 'pl', 'rb', 'jar', 'war',
    'bash', 'zsh', 'fish', 'pif', 'application', 'gadget',
    'hta', 'inf', 'reg', 'rgs', 'sct', 'shb', 'ws', 'wsf', 'wsh'
}

BLOCKED_MIME_TYPES = {
    'application/x-executable',
    'application/x-msdos-program',
    'application/x-msdownload',
    'application/x-sh',
    'application/x-shellscript',
    'text/x-python',
    'text/x-php',
    'application/x-httpd-php',
}


def validate_attachment(file):
    """
    Waliduje załącznik: rozmiar, rozszerzenie, MIME type.
    Zwraca (True, None) lub (False, error_message).
    """
    if not file or not file.filename:
        return False, "Nie wybrano pliku"

    filename = file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext in BLOCKED_EXTENSIONS:
        return False, f"Niedozwolone rozszerzenie pliku: .{ext}"

    if not ext:
        return False, "Plik musi mieć rozszerzenie"

    content_type = file.content_type or ''
    if content_type in BLOCKED_MIME_TYPES:
        return False, f"Niedozwolony typ pliku: {content_type}"

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size > MAX_FILE_SIZE:
        size_kb = round(size / 1024)
        return False, f"Plik jest za duży ({size_kb} KB). Maksymalny rozmiar to 1 MB."

    if size == 0:
        return False, "Plik jest pusty"

    return True, None


def save_attachment(file, quote):
    """
    Zapisuje załącznik na dysk i aktualizuje kolumny Quote.
    Jeśli quote ma już załącznik, stary plik jest usuwany.
    Zwraca (True, None) lub (False, error_message).
    """
    valid, error = validate_attachment(file)
    if not valid:
        return False, error

    if quote.attachment_stored_name:
        _delete_file_from_disk(quote.attachment_stored_name)

    original_filename = file.filename
    if len(original_filename) > 200:
        name, ext = os.path.splitext(original_filename)
        original_filename = name[:200 - len(ext)] + ext

    safe_name = secure_filename(original_filename)
    if not safe_name:
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else 'bin'
        safe_name = f"attachment.{ext}"

    unique_prefix = uuid.uuid4().hex[:8]
    stored_name = f"{unique_prefix}_{safe_name}"

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    filepath = os.path.join(UPLOAD_FOLDER, stored_name)
    try:
        file.save(filepath)
    except Exception as e:
        current_app.logger.error(f"[attachment_service] Błąd zapisu pliku: {e}")
        return False, "Błąd zapisu pliku na serwerze"

    quote.attachment_filename = original_filename
    quote.attachment_stored_name = stored_name

    return True, None


def delete_attachment(quote):
    """
    Usuwa załącznik z dysku i czyści kolumny Quote.
    """
    if quote.attachment_stored_name:
        _delete_file_from_disk(quote.attachment_stored_name)

    quote.attachment_filename = None
    quote.attachment_stored_name = None


def get_attachment_path(quote):
    """
    Zwraca pełną ścieżkę do pliku załącznika lub None.
    """
    if not quote.attachment_stored_name:
        return None

    filepath = os.path.join(UPLOAD_FOLDER, quote.attachment_stored_name)
    if os.path.exists(filepath):
        return filepath
    return None


def get_attachment_info(quote):
    """
    Zwraca dict z info o załączniku lub None.
    Do użycia w API responses.
    """
    if not quote.attachment_filename:
        return None

    return {
        'filename': quote.attachment_filename,
        'exists': os.path.exists(os.path.join(UPLOAD_FOLDER, quote.attachment_stored_name)) if quote.attachment_stored_name else False
    }


def _delete_file_from_disk(stored_name):
    """Usuwa plik z dysku (helper)."""
    filepath = os.path.join(UPLOAD_FOLDER, stored_name)
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        current_app.logger.error(f"[attachment_service] Błąd usuwania pliku {stored_name}: {e}")
