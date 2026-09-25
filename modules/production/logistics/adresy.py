# -*- coding: utf-8 -*-
"""
Rozbijanie adresu dostawy na ulicę, numer domu i numer mieszkania.

Funkcje przeniesione 1:1 z modules/reports/routers.py (eksport Routimo), żeby
geokoder logistyki i eksport Routimo dzieliły jedną logikę. Raporty importują
je stąd pod starymi nazwami.
"""
import re

_KOD_POCZTOWY = re.compile(r'\b\d{2}-\d{3}\b')


def usun_kod_pocztowy(tekst):
    """„36-068 Bachórz 14N" → „Bachórz 14N". GUGiK z kodem w zapytaniu potrafi nic nie znaleźć."""
    bez = _KOD_POCZTOWY.sub('', tekst or '')
    return re.sub(r'\s+', ' ', bez).strip(' ,')


# R10 (kontroler): oznaczenie lokalu / klatki / piętra NA KOŃCU adresu, tuż po numerze
# domu (ewentualnie z literą: „12 B m. 3”), oddzielone spacją albo przecinkiem.
# Dłuższe warianty przed krótszymi („mieszkanie” przed „mieszk”, „lokal” przed „lok”).
# Wymóg „po numerze domu” chroni nazwy ulic: w „Parkowa 3” czy „Kolejowa 7” nic nie pasuje,
# a jednoliterowe „m”/„p” liczą się tylko jako osobne słowo przed numerem lokalu.
_OZNACZENIE_LOKALU = re.compile(
    r'(\d(?:\s?[A-Za-z])?)[\s,]+'
    r'(?:mieszkanie|mieszk|lokal|lok|klatka|kl|piętro|pietro|apt|m|p)\.?\s*'
    r'[A-Za-z]?\d+[A-Za-z]?\s*$',  # „lok. U2” — lokal usługowy
    re.IGNORECASE)
# „12 B” → „12B” (na końcu albo przed „/”) — GUGiK zna numer „12B”, nie „12” z ulicą „B”.
_LITERA_ODDZIELONA = re.compile(r'(\d)\s+([A-Za-z])(?=\s*(?:/|$))')
_MIASTO_NA_KONCU = re.compile(r'^(.*\S)\s*,\s*([^,]+)$')


def _norm(tekst):
    return ' '.join((tekst or '').lower().split())


def adres_do_geokodowania(adres, miasto):
    """
    Adres przygotowany WYŁĄCZNIE dla geokodera (R10), przed extract_house_and_apartment_number:
    bez kodu pocztowego, bez końcowego „, <miasto zamówienia>” i bez oznaczeń lokalu na końcu.

    Zmierzone 25.09.2026: „Kraków, Floriańska 10 lok 5” → GUGiK oddawał Floriańską 5
    (accuracy 0.74), czyli zły budynek jako punkt „dokladna”. Eksport Routimo dalej używa
    extract_house_and_apartment_number / clean_street_name bez tej funkcji (1:1).
    """
    tekst = usun_kod_pocztowy(adres)
    miasto = _norm(miasto)
    dopasowanie = _MIASTO_NA_KONCU.match(tekst)
    if miasto and dopasowanie and _norm(dopasowanie.group(2)) == miasto:
        tekst = dopasowanie.group(1)
    # Kilka oznaczeń z rzędu („5 kl. 2 m. 7”) — zdejmujemy od końca, aż nic nie pasuje.
    while True:
        krotszy = _OZNACZENIE_LOKALU.sub(r'\1', tekst)
        if krotszy == tekst:
            break
        tekst = krotszy
    tekst = _LITERA_ODDZIELONA.sub(r'\1\2', tekst)
    return re.sub(r'\s+', ' ', tekst).strip(' ,')


def extract_house_and_apartment_number(address):
    """
    Wyciąga numer domu i mieszkania z adresu oraz zwraca oczyszczoną ulicę
    Obsługuje formaty: "ul. Nazwa 123", "123 Nazwa ulicy", "Nazwa 123/45"

    Args:
        address (str): Pełny adres

    Returns:
        tuple: (house_number, apartment_number, clean_street)
    """
    if not address or not isinstance(address, str):
        return '', '', address or ''

    original_address = address.strip()

    # WZORCE - NUMER PO NAZWIE ULICY (tradycyjne)
    traditional_patterns = [
        # "ul. Nazwa 123/45"
        {
            'pattern': r'^(.+?)\s+(\d+[A-Za-z]*)\/(\d+[A-Za-z]*)$',
            'has_apartment': True,
            'street_group': 1,
            'house_group': 2,
            'apartment_group': 3
        },
        # "ul. Nazwa 123 / 45" (ze spacjami)
        {
            'pattern': r'^(.+?)\s+(\d+[A-Za-z]*)\s*\/\s*(\d+[A-Za-z]*)$',
            'has_apartment': True,
            'street_group': 1,
            'house_group': 2,
            'apartment_group': 3
        },
        # "ul. Nazwa 123m45"
        {
            'pattern': r'^(.+?)\s+(\d+[A-Za-z]*)\s*m\.?\s*(\d+[A-Za-z]*)$',
            'has_apartment': True,
            'street_group': 1,
            'house_group': 2,
            'apartment_group': 3
        },
        # "ul. Nazwa 123" (tylko dom)
        {
            'pattern': r'^(.+?)\s+(\d+[A-Za-z]*)\s*$',
            'has_apartment': False,
            'street_group': 1,
            'house_group': 2,
            'apartment_group': None
        }
    ]

    # WZORCE - NUMER PRZED NAZWĄ ULICY (odwrócone)
    reversed_patterns = [
        # "123/45 Nazwa ulicy"
        {
            'pattern': r'^(\d+[A-Za-z]*)\/(\d+[A-Za-z]*)\s+(.+)$',
            'has_apartment': True,
            'street_group': 3,
            'house_group': 1,
            'apartment_group': 2
        },
        # "123 / 45 Nazwa ulicy" (ze spacjami)
        {
            'pattern': r'^(\d+[A-Za-z]*)\s*\/\s*(\d+[A-Za-z]*)\s+(.+)$',
            'has_apartment': True,
            'street_group': 3,
            'house_group': 1,
            'apartment_group': 2
        },
        # "123m45 Nazwa ulicy"
        {
            'pattern': r'^(\d+[A-Za-z]*)\s*m\.?\s*(\d+[A-Za-z]*)\s+(.+)$',
            'has_apartment': True,
            'street_group': 3,
            'house_group': 1,
            'apartment_group': 2
        },
        # "123 Nazwa ulicy" (tylko dom)
        {
            'pattern': r'^(\d+[A-Za-z]*)\s+(.+)$',
            'has_apartment': False,
            'street_group': 2,
            'house_group': 1,
            'apartment_group': None
        }
    ]

    # Sprawdź wszystkie wzorce - najpierw tradycyjne, potem odwrócone
    all_patterns = traditional_patterns + reversed_patterns

    for pattern_info in all_patterns:
        match = re.search(pattern_info['pattern'], original_address, re.IGNORECASE)
        if match:
            groups = match.groups()

            # Wyciągnij komponenty według grup
            street = groups[pattern_info['street_group'] - 1].strip()
            house = groups[pattern_info['house_group'] - 1].strip()
            apartment = ''

            if pattern_info['has_apartment'] and pattern_info['apartment_group']:
                apartment = groups[pattern_info['apartment_group'] - 1].strip()

            # Sprawdź czy ulica nie jest pusta
            if not street:
                continue

            # Oczyść ulicę delikatnie
            clean_street = clean_street_name(street)

            # Jeśli po czyszczeniu ulica jest pusta, spróbuj następny wzorzec
            if not clean_street:
                continue

            return house, apartment, clean_street

    # Fallback - nie znaleziono wzorca, zwróć oryginalny adres
    return '', '', original_address


def clean_street_name(street):
    """
    Delikatnie czyści nazwę ulicy z niepotrzebnych elementów
    POPRAWKA: Nie usuwa "Aleja" jeśli to część nazwy ulicy

    Args:
        street (str): Surowa nazwa ulicy

    Returns:
        str: Oczyszczona nazwa ulicy
    """
    if not street:
        return ''

    # Usuń zbędne białe znaki
    street = street.strip()

    # Usuń końcowe przecinki i kropki
    street = re.sub(r'[,\.]+$', '', street).strip()

    # Usuń miasto z początku (tylko jeśli po przecinku jest coś więcej)
    # "Warszawa, ul. Nowa" → "ul. Nowa"
    city_pattern = r'^([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)\s*,\s*(.+)$'
    city_match = re.match(city_pattern, street)
    if city_match and city_match.group(2).strip():
        street = city_match.group(2).strip()

    # POPRAWKA: Usuń prefiksy TYLKO jeśli są na początku i po nich jest jeszcze tekst
    # ALE zachowaj "Aleja Nazwa" jako całość - nie traktuj "Aleja" jako prefiksu do usunięcia

    # Lista prefixów do usunięcia TYLKO jeśli są na samym początku
    prefixes_to_remove = ['ul', 'ulica']  # Skróciłem listę!

    for prefix in prefixes_to_remove:
        # Usuń tylko "ul." lub "ulica" na początku, ale zostaw "al.", "pl.", "os."
        pattern = rf'^{prefix}\.?\s+(.+)$'
        match = re.match(pattern, street, re.IGNORECASE)
        if match and match.group(1).strip():
            street = match.group(1).strip()
            break  # Usuń tylko pierwszy pasujący prefiks

    return street
