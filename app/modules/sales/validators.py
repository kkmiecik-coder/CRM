# app/modules/sales/validators.py
"""
Sales Validators
================

Walidatory dla danych formularzy i plików.

Validators:
- validate_application_data: Walidacja danych formularza rekrutacyjnego
- validate_file: Walidacja pliku NDA

Autor: Development Team
Data: 2025-10-24
"""

import re
from werkzeug.datastructures import FileStorage


def validate_application_data(form_data):
    """
    Walidacja danych z formularza aplikacyjnego
    
    Args:
        form_data (dict): Dane z formularza
        
    Returns:
        tuple: (is_valid: bool, errors: dict)
    """
    errors = {}
    
    # ============================================================================
    # DANE OSOBOWE - WYMAGANE
    # ============================================================================
    
    # Imię
    if not form_data.get('first_name'):
        errors['first_name'] = 'Imię jest wymagane'
    elif len(form_data['first_name']) < 2:
        errors['first_name'] = 'Imię musi mieć minimum 2 znaki'
    elif len(form_data['first_name']) > 100:
        errors['first_name'] = 'Imię może mieć maksymalnie 100 znaków'
    
    # Nazwisko
    if not form_data.get('last_name'):
        errors['last_name'] = 'Nazwisko jest wymagane'
    elif len(form_data['last_name']) < 2:
        errors['last_name'] = 'Nazwisko musi mieć minimum 2 znaki'
    elif len(form_data['last_name']) > 100:
        errors['last_name'] = 'Nazwisko może mieć maksymalnie 100 znaków'
    
    # Email
    if not form_data.get('email'):
        errors['email'] = 'Email jest wymagany'
    else:
        email = form_data['email']
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            errors['email'] = 'Nieprawidłowy format email'
        elif len(email) > 255:
            errors['email'] = 'Email może mieć maksymalnie 255 znaków'
    
    # Telefon
    if not form_data.get('phone'):
        errors['phone'] = 'Telefon jest wymagany'
    else:
        phone = form_data['phone']
        # Usuń wszystkie znaki oprócz cyfr
        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) < 9:
            errors['phone'] = 'Numer telefonu musi zawierać minimum 9 cyfr'
        elif len(phone_digits) > 15:
            errors['phone'] = 'Numer telefonu może zawierać maksymalnie 15 cyfr'
    
    # Miasto
    if not form_data.get('city'):
        errors['city'] = 'Miasto jest wymagane'
    elif len(form_data['city']) < 2:
        errors['city'] = 'Nazwa miasta musi mieć minimum 2 znaki'
    elif len(form_data['city']) > 100:
        errors['city'] = 'Nazwa miasta może mieć maksymalnie 100 znaków'
    
    # Adres
    if not form_data.get('address'):
        errors['address'] = 'Adres jest wymagany'
    elif len(form_data['address']) < 5:
        errors['address'] = 'Adres musi mieć minimum 5 znaków'
    elif len(form_data['address']) > 255:
        errors['address'] = 'Adres może mieć maksymalnie 255 znaków'
    
    # Kod pocztowy
    if not form_data.get('postal_code'):
        errors['postal_code'] = 'Kod pocztowy jest wymagany'
    else:
        postal_code = form_data['postal_code']
        if not re.match(r'^\d{2}-\d{3}$', postal_code):
            errors['postal_code'] = 'Kod pocztowy musi być w formacie 00-000'

    # Województwo
    if not form_data.get('voivodeship'):
        errors['voivodeship'] = 'Województwo jest wymagane'
    elif form_data['voivodeship'] not in [
        'dolnośląskie', 'kujawsko-pomorskie', 'lubelskie', 'lubuskie',
        'łódzkie', 'małopolskie', 'mazowieckie', 'opolskie',
        'podkarpackie', 'podlaskie', 'pomorskie', 'śląskie',
        'świętokrzyskie', 'warmińsko-mazurskie', 'wielkopolskie', 'zachodniopomorskie'
    ]:
        errors['voivodeship'] = 'Nieprawidłowe województwo'

    # Miejscowość działalności
    if not form_data.get('business_location'):
        errors['business_location'] = 'Miejscowość działalności jest wymagana'
    elif len(form_data['business_location']) < 2:
        errors['business_location'] = 'Miejscowość musi mieć minimum 2 znaki'
    elif len(form_data['business_location']) > 100:
        errors['business_location'] = 'Miejscowość może mieć maksymalnie 100 znaków'
    
    # ============================================================================
    # DANE OPCJONALNE
    # ============================================================================
    
    # About text (opcjonalne)
    if form_data.get('about_text'):
        if len(form_data['about_text']) > 5000:
            errors['about_text'] = 'Tekst może mieć maksymalnie 5000 znaków'
    
    # ============================================================================
    # DANE B2B (WALIDOWANE TYLKO JEŚLI cooperation_type = 'b2b')
    # ============================================================================
    
    is_b2b = form_data.get('cooperation_type') == 'b2b'
    
    if is_b2b:
        # Nazwa firmy
        if not form_data.get('company_name'):
            errors['company_name'] = 'Nazwa firmy jest wymagana dla rozliczenia B2B'
        elif len(form_data['company_name']) < 2:
            errors['company_name'] = 'Nazwa firmy musi mieć minimum 2 znaki'
        elif len(form_data['company_name']) > 255:
            errors['company_name'] = 'Nazwa firmy może mieć maksymalnie 255 znaków'
        
        # NIP
        if not form_data.get('nip'):
            errors['nip'] = 'NIP jest wymagany dla rozliczenia B2B'
        else:
            nip = re.sub(r'\D', '', form_data['nip'])  # Usuń wszystko oprócz cyfr
            if not re.match(r'^\d{10}$', nip):
                errors['nip'] = 'NIP musi składać się z 10 cyfr'
            else:
                # Walidacja sumy kontrolnej NIP
                if not _validate_nip_checksum(nip):
                    errors['nip'] = 'Nieprawidłowy numer NIP (błędna suma kontrolna)'
        
        # REGON (opcjonalny)
        if form_data.get('regon'):
            regon = re.sub(r'\D', '', form_data['regon'])
            if not re.match(r'^(\d{9}|\d{14})$', regon):
                errors['regon'] = 'REGON musi składać się z 9 lub 14 cyfr'
        
        # Adres firmy
        if not form_data.get('company_address'):
            errors['company_address'] = 'Adres firmy jest wymagany dla rozliczenia B2B'
        elif len(form_data['company_address']) < 5:
            errors['company_address'] = 'Adres firmy musi mieć minimum 5 znaków'
        elif len(form_data['company_address']) > 255:
            errors['company_address'] = 'Adres firmy może mieć maksymalnie 255 znaków'
        
        # Miasto firmy
        if not form_data.get('company_city'):
            errors['company_city'] = 'Miasto firmy jest wymagane dla rozliczenia B2B'
        elif len(form_data['company_city']) < 2:
            errors['company_city'] = 'Nazwa miasta musi mieć minimum 2 znaki'
        elif len(form_data['company_city']) > 100:
            errors['company_city'] = 'Nazwa miasta może mieć maksymalnie 100 znaków'
        
        # Kod pocztowy firmy
        if not form_data.get('company_postal_code'):
            errors['company_postal_code'] = 'Kod pocztowy firmy jest wymagany dla rozliczenia B2B'
        else:
            company_postal_code = form_data['company_postal_code']
            if not re.match(r'^\d{2}-\d{3}$', company_postal_code):
                errors['company_postal_code'] = 'Kod pocztowy musi być w formacie 00-000'
    
    # ============================================================================
    # ZGODY
    # ============================================================================
    
    # Zgoda na przetwarzanie danych
    if form_data.get('data_processing_consent', 'off') != 'on':
        errors['data_processing_consent'] = 'Zgoda na przetwarzanie danych jest wymagana'
    
    # ============================================================================
    # RETURN
    # ============================================================================
    
    is_valid = len(errors) == 0
    return is_valid, errors


def _validate_nip_checksum(nip):
    """
    Walidacja sumy kontrolnej NIP
    
    Args:
        nip (str): Numer NIP (10 cyfr)
        
    Returns:
        bool: True jeśli suma kontrolna jest prawidłowa
    """
    if len(nip) != 10 or not nip.isdigit():
        return False
    
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    checksum = 0
    
    for i in range(9):
        checksum += int(nip[i]) * weights[i]
    
    checksum = checksum % 11
    
    if checksum == 10:
        return False
    
    return checksum == int(nip[9])


def validate_file(file):
    """
    Walidacja pliku NDA
    
    Args:
        file (FileStorage): Plik z formularza
        
    Returns:
        tuple: (is_valid: bool, error: str or None)
    """
    if not file or not isinstance(file, FileStorage):
        return False, 'Plik NDA jest wymagany'
    
    if file.filename == '':
        return False, 'Nie wybrano pliku'
    
    # Sprawdź rozszerzenie
    allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png', 'docx', 'odt'}
    filename = file.filename.lower()
    
    if '.' not in filename:
        return False, 'Plik musi mieć rozszerzenie'
    
    extension = filename.rsplit('.', 1)[1]
    if extension not in allowed_extensions:
        return False, f'Dozwolone formaty: {", ".join(allowed_extensions).upper()}'
    
    # Sprawdź rozmiar (5MB max)
    file.seek(0, 2)  # Przejdź na koniec pliku
    file_size = file.tell()
    file.seek(0)  # Wróć na początek
    
    max_size = 5 * 1024 * 1024  # 5MB
    if file_size > max_size:
        size_mb = file_size / (1024 * 1024)
        return False, f'Plik jest za duży ({size_mb:.1f}MB). Maksymalny rozmiar to 5MB'
    
    return True, None