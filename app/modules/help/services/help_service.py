"""
Główny serwis logiki biznesowej dla modułu Help
"""
from extensions import db
from ..models import HelpArticle, HelpCategory
from .slug_generator import generate_unique_slug, validate_slug
from bs4 import BeautifulSoup
import bleach
from datetime import datetime


# ==================== KATEGORIE ====================

def get_all_categories(visible_only=False):
    """
    Zwraca wszystkie kategorie z liczbą artykułów
    
    Args:
        visible_only (bool): Czy tylko widoczne
    
    Returns:
        list: Lista obiektów HelpCategory
    """
    query = HelpCategory.query
    
    if visible_only:
        query = query.filter_by(is_visible=True)
    
    return query.order_by(HelpCategory.sort_order.asc()).all()


def get_category_by_id(category_id):
    """
    Pobiera kategorię po ID
    
    Args:
        category_id (int): ID kategorii
    
    Returns:
        HelpCategory or None
    """
    return HelpCategory.query.get(category_id)


def create_category(name, icon='📄', sort_order=0, is_visible=True):
    """
    Tworzy nową kategorię
    
    Args:
        name (str): Nazwa kategorii
        icon (str): Emoji ikona
        sort_order (int): Kolejność sortowania
        is_visible (bool): Czy widoczna
    
    Returns:
        dict: {'success': bool, 'category': HelpCategory, 'error': str}
    """
    # Walidacja
    if not name or len(name.strip()) < 2:
        return {'success': False, 'error': 'Nazwa kategorii musi mieć minimum 2 znaki'}
    
    try:
        category = HelpCategory(
            name=name.strip(),
            icon=icon,
            sort_order=sort_order,
            is_visible=is_visible
        )
        
        db.session.add(category)
        db.session.commit()
        
        return {'success': True, 'category': category}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas tworzenia kategorii: {str(e)}'}


def update_category(category_id, name=None, icon=None, sort_order=None, is_visible=None):
    """
    Aktualizuje kategorię
    
    Args:
        category_id (int): ID kategorii
        name (str, optional): Nowa nazwa
        icon (str, optional): Nowa ikona
        sort_order (int, optional): Nowa kolejność
        is_visible (bool, optional): Nowa widoczność
    
    Returns:
        dict: {'success': bool, 'category': HelpCategory, 'error': str}
    """
    category = get_category_by_id(category_id)
    
    if not category:
        return {'success': False, 'error': 'Kategoria nie istnieje'}
    
    try:
        if name is not None:
            if len(name.strip()) < 2:
                return {'success': False, 'error': 'Nazwa musi mieć minimum 2 znaki'}
            category.name = name.strip()
        
        if icon is not None:
            category.icon = icon
        
        if sort_order is not None:
            category.sort_order = sort_order
        
        if is_visible is not None:
            category.is_visible = is_visible
        
        category.updated_at = datetime.utcnow()
        db.session.commit()
        
        return {'success': True, 'category': category}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas aktualizacji: {str(e)}'}


def delete_category(category_id, move_articles_to=None):
    """
    Usuwa kategorię (z opcją przeniesienia artykułów)
    
    Args:
        category_id (int): ID kategorii do usunięcia
        move_articles_to (int, optional): ID kategorii docelowej dla artykułów
    
    Returns:
        dict: {'success': bool, 'error': str}
    """
    category = get_category_by_id(category_id)
    
    if not category:
        return {'success': False, 'error': 'Kategoria nie istnieje'}
    
    # Sprawdź czy są artykuły
    articles_count = category.articles.count()
    
    if articles_count > 0:
        if not move_articles_to:
            return {
                'success': False,
                'error': f'Kategoria zawiera {articles_count} artykułów. Przenieś je lub usuń przed usunięciem kategorii.',
                'articles_count': articles_count
            }
        
        # Przenieś artykuły do innej kategorii
        target_category = get_category_by_id(move_articles_to)
        
        if not target_category:
            return {'success': False, 'error': 'Docelowa kategoria nie istnieje'}
        
        if target_category.id == category_id:
            return {'success': False, 'error': 'Nie można przenieść do tej samej kategorii'}
        
        try:
            # Przenieś wszystkie artykuły
            for article in category.articles:
                article.category_id = move_articles_to
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': f'Błąd podczas przenoszenia artykułów: {str(e)}'}
    
    # Usuń kategorię
    try:
        db.session.delete(category)
        db.session.commit()
        return {'success': True}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas usuwania: {str(e)}'}


# ==================== ARTYKUŁY ====================

def get_all_articles(category_id=None, published_only=False):
    """
    Zwraca wszystkie artykuły (z opcją filtrowania)
    
    Args:
        category_id (int, optional): Filtruj po kategorii
        published_only (bool): Tylko opublikowane
    
    Returns:
        list: Lista obiektów HelpArticle
    """
    query = HelpArticle.query
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if published_only:
        query = query.filter_by(is_published=True)
    
    return query.order_by(
        HelpArticle.sort_order.asc(),
        HelpArticle.updated_at.desc()
    ).all()


def get_article_by_id(article_id):
    """
    Pobiera artykuł po ID
    
    Args:
        article_id (int): ID artykułu
    
    Returns:
        HelpArticle or None
    """
    return HelpArticle.query.get(article_id)


def get_article_by_slug(slug):
    """
    Pobiera artykuł po slug
    
    Args:
        slug (str): Slug artykułu
    
    Returns:
        HelpArticle or None
    """
    return HelpArticle.query.filter_by(slug=slug).first()


def create_article(title, content, category_id, author_id, slug=None, 
                   sort_order=0, is_published=True):
    """
    Tworzy nowy artykuł
    
    Args:
        title (str): Tytuł artykułu
        content (str): Treść HTML
        category_id (int): ID kategorii
        author_id (int): ID autora
        slug (str, optional): Własny slug (lub auto-generowany)
        sort_order (int): Kolejność
        is_published (bool): Czy opublikowany
    
    Returns:
        dict: {'success': bool, 'article': HelpArticle, 'error': str}
    """
    # Walidacja tytułu
    if not title or len(title.strip()) < 3:
        return {'success': False, 'error': 'Tytuł musi mieć minimum 3 znaki'}
    
    # Walidacja treści
    if not content or len(content.strip()) < 10:
        return {'success': False, 'error': 'Treść musi mieć minimum 10 znaków'}
    
    # Walidacja kategorii
    category = get_category_by_id(category_id)
    if not category:
        return {'success': False, 'error': 'Kategoria nie istnieje'}
    
    # Generuj lub waliduj slug
    if not slug:
        slug = generate_unique_slug(title)
    else:
        is_valid, error = validate_slug(slug)
        if not is_valid:
            return {'success': False, 'error': error}
    
    # Sanityzuj HTML
    clean_content = sanitize_html(content)
    
    try:
        article = HelpArticle(
            title=title.strip(),
            slug=slug,
            content=clean_content,
            category_id=category_id,
            author_id=author_id,
            sort_order=sort_order,
            is_published=is_published
        )
        
        db.session.add(article)
        db.session.commit()
        
        return {'success': True, 'article': article}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas tworzenia artykułu: {str(e)}'}


def update_article(article_id, title=None, content=None, category_id=None,
                   slug=None, sort_order=None, is_published=None):
    """
    Aktualizuje artykuł
    
    Args:
        article_id (int): ID artykułu
        title (str, optional): Nowy tytuł
        content (str, optional): Nowa treść
        category_id (int, optional): Nowa kategoria
        slug (str, optional): Nowy slug
        sort_order (int, optional): Nowa kolejność
        is_published (bool, optional): Nowy status publikacji
    
    Returns:
        dict: {'success': bool, 'article': HelpArticle, 'error': str}
    """
    article = get_article_by_id(article_id)
    
    if not article:
        return {'success': False, 'error': 'Artykuł nie istnieje'}
    
    try:
        if title is not None:
            if len(title.strip()) < 3:
                return {'success': False, 'error': 'Tytuł musi mieć minimum 3 znaki'}
            article.title = title.strip()
        
        if content is not None:
            if len(content.strip()) < 10:
                return {'success': False, 'error': 'Treść musi mieć minimum 10 znaków'}
            article.content = sanitize_html(content)
        
        if category_id is not None:
            category = get_category_by_id(category_id)
            if not category:
                return {'success': False, 'error': 'Kategoria nie istnieje'}
            article.category_id = category_id
        
        if slug is not None:
            is_valid, error = validate_slug(slug, article_id=article_id)
            if not is_valid:
                return {'success': False, 'error': error}
            article.slug = slug
        
        if sort_order is not None:
            article.sort_order = sort_order
        
        if is_published is not None:
            article.is_published = is_published
        
        article.updated_at = datetime.utcnow()
        db.session.commit()
        
        return {'success': True, 'article': article}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas aktualizacji: {str(e)}'}


def delete_article(article_id):
    """
    Usuwa artykuł (hard delete)
    
    Args:
        article_id (int): ID artykułu
    
    Returns:
        dict: {'success': bool, 'error': str}
    """
    article = get_article_by_id(article_id)
    
    if not article:
        return {'success': False, 'error': 'Artykuł nie istnieje'}
    
    try:
        db.session.delete(article)
        db.session.commit()
        return {'success': True}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd podczas usuwania: {str(e)}'}


def toggle_article_visibility(article_id):
    """
    Przełącza widoczność artykułu (published/unpublished)
    
    Args:
        article_id (int): ID artykułu
    
    Returns:
        dict: {'success': bool, 'is_published': bool, 'error': str}
    """
    article = get_article_by_id(article_id)
    
    if not article:
        return {'success': False, 'error': 'Artykuł nie istnieje'}
    
    try:
        article.is_published = not article.is_published
        article.updated_at = datetime.utcnow()
        db.session.commit()
        
        return {'success': True, 'is_published': article.is_published}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'error': f'Błąd: {str(e)}'}


# ==================== POMOCNICZE ====================

def sanitize_html(html_content):
    """
    Oczyszcza HTML z potencjalnie niebezpiecznych tagów (XSS)
    
    Args:
        html_content (str): Surowy HTML
    
    Returns:
        str: Oczyszczony HTML
    """
    # Whitelist dozwolonych tagów
    allowed_tags = [
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'p', 'br', 'strong', 'em', 'u', 'strike',
        'ul', 'ol', 'li',
        'a', 'img', 'iframe',
        'blockquote', 'code', 'pre',
        'table', 'thead', 'tbody', 'tr', 'th', 'td'
    ]
    
    # Whitelist dozwolonych atrybutów
    allowed_attributes = {
        '*': ['class', 'id'],
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
        'iframe': ['src', 'width', 'height', 'frameborder', 'allowfullscreen']
    }
    
    # Użyj bleach do czyszczenia
    clean_html = bleach.clean(
        html_content,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )
    
    return clean_html


def extract_headings(html_content):
    """
    Wyciąga nagłówki H1-H3 z treści artykułu (dla nawigacji sidebar)
    
    Args:
        html_content (str): Treść HTML
    
    Returns:
        list: Lista słowników:
            [
                {'level': 1, 'text': 'Nagłówek', 'id': 'naglowek'},
                {'level': 2, 'text': 'Podtytuł', 'id': 'podtytul'}
            ]
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    headings = []
    
    for tag in soup.find_all(['h1', 'h2', 'h3']):
        level = int(tag.name[1])  # h1 -> 1, h2 -> 2, h3 -> 3
        text = tag.get_text(strip=True)
        
        # Generuj ID dla anchor link (jeśli nie ma)
        heading_id = tag.get('id')
        if not heading_id:
            from .slug_generator import sanitize_slug
            heading_id = sanitize_slug(text)[:50]  # Max 50 znaków
        
        headings.append({
            'level': level,
            'text': text,
            'id': heading_id
        })
    
    return headings


def get_category_with_articles(category_id):
    """
    Zwraca kategorię z wszystkimi jej artykułami
    
    Args:
        category_id (int): ID kategorii
    
    Returns:
        dict or None: {'category': HelpCategory, 'articles': list}
    """
    category = get_category_by_id(category_id)
    
    if not category:
        return None
    
    articles = get_all_articles(category_id=category_id, published_only=True)
    
    return {
        'category': category,
        'articles': articles
    }