"""
Serwis generowania unikalnych slugów dla artykułów Help
"""
from slugify import slugify
from ..models import HelpArticle


def generate_unique_slug(title, article_id=None):
    """
    Generuje unikalny slug z tytułu artykułu
    
    Args:
        title (str): Tytuł artykułu
        article_id (int, optional): ID artykułu (przy edycji, aby pominąć sam siebie)
    
    Returns:
        str: Unikalny slug
    
    Example:
        >>> generate_unique_slug("Jak utworzyć wycenę?")
        "jak-utworzyc-wycene"
        
        >>> generate_unique_slug("Jak utworzyć wycenę?")  # jeśli slug istnieje
        "jak-utworzyc-wycene-2"
    """
    if not title or not title.strip():
        raise ValueError("Tytuł nie może być pusty")
    
    # Generuj bazowy slug
    base_slug = slugify(title, max_length=200)
    
    if not base_slug:
        raise ValueError("Nie można wygenerować slug z podanego tytułu")
    
    # Sprawdź unikalność
    slug = base_slug
    counter = 1
    
    while True:
        # Query sprawdzające czy slug istnieje
        query = HelpArticle.query.filter_by(slug=slug)
        
        # Jeśli edytujemy istniejący artykuł, pomiń jego własny slug
        if article_id:
            query = query.filter(HelpArticle.id != article_id)
        
        existing = query.first()
        
        # Jeśli slug jest wolny, zwróć go
        if not existing:
            return slug
        
        # Jeśli zajęty, dodaj numer
        counter += 1
        slug = f"{base_slug}-{counter}"
        
        # Bezpieczeństwo - max 100 prób
        if counter > 100:
            raise ValueError("Nie można wygenerować unikalnego slug (za dużo kolizji)")


def validate_slug(slug, article_id=None):
    """
    Waliduje czy slug jest poprawny i unikalny
    
    Args:
        slug (str): Slug do walidacji
        article_id (int, optional): ID artykułu (przy edycji)
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    
    Example:
        >>> validate_slug("moj-artykul")
        (True, None)
        
        >>> validate_slug("moj artykul")
        (False, "Slug może zawierać tylko małe litery, cyfry i myślniki")
    """
    if not slug or not slug.strip():
        return (False, "Slug nie może być pusty")
    
    slug = slug.strip()
    
    # Sprawdź długość
    if len(slug) < 3:
        return (False, "Slug musi mieć minimum 3 znaki")
    
    if len(slug) > 255:
        return (False, "Slug może mieć maksymalnie 255 znaków")
    
    # Sprawdź format (tylko małe litery, cyfry, myślniki)
    import re
    if not re.match(r'^[a-z0-9-]+$', slug):
        return (False, "Slug może zawierać tylko małe litery, cyfry i myślniki")
    
    # Nie może zaczynać/kończyć się myślnikiem
    if slug.startswith('-') or slug.endswith('-'):
        return (False, "Slug nie może zaczynać ani kończyć się myślnikiem")
    
    # Nie może mieć podwójnych myślników
    if '--' in slug:
        return (False, "Slug nie może zawierać podwójnych myślników")
    
    # Sprawdź unikalność w bazie
    query = HelpArticle.query.filter_by(slug=slug)
    
    if article_id:
        query = query.filter(HelpArticle.id != article_id)
    
    if query.first():
        return (False, f"Slug '{slug}' jest już zajęty")
    
    return (True, None)


def sanitize_slug(slug):
    """
    Oczyszcza slug wprowadzony ręcznie przez użytkownika
    
    Args:
        slug (str): Slug do oczyszczenia
    
    Returns:
        str: Oczyszczony slug
    
    Example:
        >>> sanitize_slug("Mój Artykuł!")
        "moj-artykul"
        
        >>> sanitize_slug("  test--slug  ")
        "test-slug"
    """
    if not slug:
        return ""
    
    # Użyj slugify do normalizacji
    clean_slug = slugify(slug, max_length=255)
    
    # Usuń podwójne myślniki
    import re
    clean_slug = re.sub(r'-+', '-', clean_slug)
    
    # Usuń myślniki na początku/końcu
    clean_slug = clean_slug.strip('-')
    
    return clean_slug