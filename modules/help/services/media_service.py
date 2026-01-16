"""
Serwis zarządzania mediami (upload, kompresja, galeria)
"""
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image
import re


# Konfiguracja (można przenieść do config.py później)
UPLOAD_FOLDER = 'app/modules/help/static/media/uploads'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'svg'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
IMAGE_MAX_WIDTH = 1920
IMAGE_QUALITY = 85


def allowed_file(filename):
    """
    Sprawdza czy plik ma dozwolone rozszerzenie
    
    Args:
        filename (str): Nazwa pliku
    
    Returns:
        bool: True jeśli dozwolone
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_unique_filename(original_filename):
    """
    Generuje unikalną nazwę pliku
    
    Args:
        original_filename (str): Oryginalna nazwa pliku
    
    Returns:
        str: Unikalna nazwa w formacie: timestamp_uuid.ext
        
    Example:
        >>> generate_unique_filename("moje_zdjecie.jpg")
        "1705392000_a1b2c3d4.jpg"
    """
    # Pobierz rozszerzenie
    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    
    # Generuj unikalną nazwę
    timestamp = int(datetime.utcnow().timestamp())
    unique_id = str(uuid.uuid4())[:8]
    
    return f"{timestamp}_{unique_id}.{ext}"


def upload_image(file, user_id):
    """
    Uploaduje i kompresuje obraz
    
    Args:
        file (FileStorage): Plik z request.files
        user_id (int): ID użytkownika uploadującego
    
    Returns:
        dict: Informacje o uploadowanym pliku:
            {
                'success': bool,
                'filename': str,
                'url': str,
                'size': int,
                'width': int,
                'height': int,
                'error': str (jeśli success=False)
            }
    """
    # Walidacja - czy plik istnieje
    if not file or file.filename == '':
        return {'success': False, 'error': 'Brak pliku'}
    
    # Walidacja - dozwolone rozszerzenie
    if not allowed_file(file.filename):
        return {
            'success': False,
            'error': f'Niedozwolony typ pliku. Dozwolone: {", ".join(ALLOWED_EXTENSIONS)}'
        }
    
    # Walidacja - rozmiar pliku
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        return {
            'success': False,
            'error': f'Plik za duży. Maksymalny rozmiar: {MAX_FILE_SIZE / (1024*1024):.1f} MB'
        }
    
    try:
        # Generuj unikalną nazwę
        filename = generate_unique_filename(file.filename)
        
        # Upewnij się że folder istnieje
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        # Sprawdź rozszerzenie
        ext = filename.rsplit('.', 1)[1].lower()
        
        # SVG - zapisz bez kompresji
        if ext == 'svg':
            file.save(filepath)
            
            return {
                'success': True,
                'filename': filename,
                'url': f'/static/help/media/uploads/{filename}',
                'size': file_size,
                'width': None,
                'height': None
            }
        
        # Obrazy rastrowe (JPG, PNG, WebP) - kompresja
        img = Image.open(file)
        
        # Pobierz oryginalne wymiary
        original_width, original_height = img.size
        
        # Kompresja - zmniejsz jeśli za szerokie
        if original_width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / original_width
            new_height = int(original_height * ratio)
            img = img.resize((IMAGE_MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
        
        # Konwersja RGBA -> RGB (dla JPG)
        if ext in ['jpg', 'jpeg'] and img.mode in ['RGBA', 'LA', 'P']:
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        # Zapisz z kompresją
        img.save(filepath, quality=IMAGE_QUALITY, optimize=True)
        
        # Pobierz faktyczny rozmiar po kompresji
        final_size = os.path.getsize(filepath)
        final_width, final_height = img.size
        
        return {
            'success': True,
            'filename': filename,
            'url': f'/static/help/media/uploads/{filename}',
            'size': final_size,
            'width': final_width,
            'height': final_height
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Błąd podczas uploadu: {str(e)}'
        }


def get_all_media():
    """
    Zwraca listę wszystkich plików w galerii
    
    Returns:
        list: Lista słowników z informacjami o plikach:
            {
                'filename': str,
                'url': str,
                'size': int,
                'uploaded_at': datetime,
                'width': int or None,
                'height': int or None
            }
    """
    if not os.path.exists(UPLOAD_FOLDER):
        return []
    
    media_files = []
    
    for filename in os.listdir(UPLOAD_FOLDER):
        # Pomiń ukryte pliki i .gitkeep
        if filename.startswith('.'):
            continue
        
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        # Pobierz informacje o pliku
        file_stat = os.stat(filepath)
        file_size = file_stat.st_size
        uploaded_at = datetime.fromtimestamp(file_stat.st_mtime)
        
        # Sprawdź wymiary (tylko dla obrazów rastrowych)
        width, height = None, None
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        if ext in ['jpg', 'jpeg', 'png', 'webp']:
            try:
                with Image.open(filepath) as img:
                    width, height = img.size
            except:
                pass
        
        media_files.append({
            'filename': filename,
            'url': f'/static/help/media/uploads/{filename}',
            'size': file_size,
            'uploaded_at': uploaded_at,
            'width': width,
            'height': height
        })
    
    # Sortuj po dacie (najnowsze pierwsze)
    media_files.sort(key=lambda x: x['uploaded_at'], reverse=True)
    
    return media_files


def delete_media(filename):
    """
    Usuwa plik z galerii
    
    Args:
        filename (str): Nazwa pliku do usunięcia
    
    Returns:
        dict: {'success': bool, 'error': str (jeśli failure)}
    """
    # Walidacja nazwy pliku (bezpieczeństwo - zapobiega path traversal)
    if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
        return {'success': False, 'error': 'Nieprawidłowa nazwa pliku'}
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    # Sprawdź czy plik istnieje
    if not os.path.exists(filepath):
        return {'success': False, 'error': 'Plik nie istnieje'}
    
    try:
        os.remove(filepath)
        return {'success': True}
    except Exception as e:
        return {'success': False, 'error': f'Błąd podczas usuwania: {str(e)}'}


def get_media_info(filename):
    """
    Zwraca szczegółowe informacje o pliku
    
    Args:
        filename (str): Nazwa pliku
    
    Returns:
        dict or None: Informacje o pliku lub None jeśli nie istnieje
    """
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(filepath):
        return None
    
    file_stat = os.stat(filepath)
    
    # Pobierz wymiary
    width, height = None, None
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if ext in ['jpg', 'jpeg', 'png', 'webp']:
        try:
            with Image.open(filepath) as img:
                width, height = img.size
        except:
            pass
    
    return {
        'filename': filename,
        'url': f'/static/help/media/uploads/{filename}',
        'size': file_stat.st_size,
        'uploaded_at': datetime.fromtimestamp(file_stat.st_mtime),
        'width': width,
        'height': height,
        'mime_type': get_mime_type(ext)
    }


def get_mime_type(ext):
    """
    Zwraca MIME type na podstawie rozszerzenia
    
    Args:
        ext (str): Rozszerzenie pliku
    
    Returns:
        str: MIME type
    """
    mime_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp',
        'svg': 'image/svg+xml'
    }
    
    return mime_types.get(ext.lower(), 'application/octet-stream')