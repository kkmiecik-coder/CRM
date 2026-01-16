"""
Serwis wyszukiwania artykułów Help (full-text search)
"""
from ..models import HelpArticle, HelpCategory
from sqlalchemy import or_, func
import re
from html import unescape
from bs4 import BeautifulSoup


def search_articles(query, limit=20, published_only=True):
    """
    Wyszukuje artykuły po tytule i treści
    
    Args:
        query (str): Fraza do wyszukania
        limit (int): Maksymalna liczba wyników
        published_only (bool): Czy szukać tylko opublikowane
    
    Returns:
        list: Lista słowników z wynikami:
            {
                'article': HelpArticle object,
                'relevance': float (0-1),
                'excerpt': str (fragment z podświetleniem),
                'match_type': str ('title' | 'content' | 'both')
            }
    """
    if not query or not query.strip():
        return []
    
    query = query.strip()
    
    # Bazowe query
    base_query = HelpArticle.query
    
    if published_only:
        base_query = base_query.filter(HelpArticle.is_published == True)
    
    # Wyszukiwanie - LIKE dla kompatybilności (FULLTEXT wymaga MySQL z MyISAM/InnoDB z full-text index)
    search_pattern = f"%{query}%"
    
    results = base_query.filter(
        or_(
            HelpArticle.title.ilike(search_pattern),
            HelpArticle.content.ilike(search_pattern)
        )
    ).all()
    
    # Przetwarzanie wyników z oceną trafności
    processed_results = []
    
    for article in results:
        # Sprawdź gdzie wystąpiła fraza
        title_match = query.lower() in article.title.lower()
        content_match = query.lower() in strip_html_tags(article.content).lower()
        
        # Określ typ dopasowania
        if title_match and content_match:
            match_type = 'both'
            relevance = 1.0
        elif title_match:
            match_type = 'title'
            relevance = 0.9
        else:
            match_type = 'content'
            relevance = 0.7
        
        # Wygeneruj excerpt (fragment z podświetleniem)
        excerpt = generate_excerpt(article.content, query)
        
        processed_results.append({
            'article': article,
            'relevance': relevance,
            'excerpt': excerpt,
            'match_type': match_type
        })
    
    # Sortuj po trafności (title match > content match)
    processed_results.sort(key=lambda x: x['relevance'], reverse=True)
    
    return processed_results[:limit]


def generate_excerpt(html_content, query, excerpt_length=200):
    """
    Generuje fragment treści z podświetleniem szukanej frazy
    
    Args:
        html_content (str): Treść HTML artykułu
        query (str): Szukana fraza
        excerpt_length (int): Długość fragmentu (w znakach)
    
    Returns:
        str: Fragment z podświetleniem, np:
            "...przejdź do kalkulatora i wybierz <strong class="highlight">gatunek</strong> drewna..."
    """
    # Usuń tagi HTML
    plain_text = strip_html_tags(html_content)
    
    # Znajdź pierwsze wystąpienie frazy (case-insensitive)
    query_lower = query.lower()
    text_lower = plain_text.lower()
    
    match_pos = text_lower.find(query_lower)
    
    if match_pos == -1:
        # Jeśli nie znaleziono, zwróć początek tekstu
        return plain_text[:excerpt_length] + ('...' if len(plain_text) > excerpt_length else '')
    
    # Wyznacz początek i koniec fragmentu (wokół znalezionej frazy)
    start = max(0, match_pos - excerpt_length // 2)
    end = min(len(plain_text), match_pos + len(query) + excerpt_length // 2)
    
    # Wytnij fragment
    excerpt = plain_text[start:end]
    
    # Dodaj "..." jeśli fragment nie jest na początku/końcu
    if start > 0:
        excerpt = '...' + excerpt
    if end < len(plain_text):
        excerpt = excerpt + '...'
    
    # Podświetl szukaną frazę (case-insensitive)
    excerpt = highlight_text(excerpt, query)
    
    return excerpt


def highlight_text(text, query):
    """
    Podświetla szukaną frazę w tekście (case-insensitive)
    
    Args:
        text (str): Tekst do podświetlenia
        query (str): Fraza do podświetlenia
    
    Returns:
        str: Tekst z podświetleniem
    
    Example:
        >>> highlight_text("To jest test", "test")
        'To jest <strong class="highlight">test</strong>'
    """
    if not query or not text:
        return text
    
    # Regex dla case-insensitive replacement (zachowuje oryginalną wielkość liter)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    
    def replace_match(match):
        return f'<strong class="highlight">{match.group(0)}</strong>'
    
    return pattern.sub(replace_match, text)


def strip_html_tags(html_content):
    """
    Usuwa tagi HTML z treści
    
    Args:
        html_content (str): Treść HTML
    
    Returns:
        str: Czysty tekst
    
    Example:
        >>> strip_html_tags("<p>Hello <strong>world</strong>!</p>")
        'Hello world!'
    """
    if not html_content:
        return ""
    
    # Użyj BeautifulSoup do czyszczenia
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ', strip=True)
    
    # Unescape HTML entities
    text = unescape(text)
    
    # Usuń wielokrotne spacje
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def get_popular_searches(limit=10):
    """
    Zwraca najpopularniejsze frazy wyszukiwania
    (placeholder - wymaga tabeli search_logs w przyszłości)
    
    Args:
        limit (int): Liczba wyników
    
    Returns:
        list: Lista tupli (fraza, liczba_wyszukań)
    """
    # TODO: Implementacja wymaga tabeli search_logs
    # Na razie zwracamy pustą listę
    return []


def log_search_query(query, user_id=None, results_count=0):
    """
    Loguje zapytanie wyszukiwania (dla statystyk)
    (placeholder - wymaga tabeli search_logs w przyszłości)
    
    Args:
        query (str): Szukana fraza
        user_id (int, optional): ID użytkownika
        results_count (int): Liczba znalezionych wyników
    """
    # TODO: Implementacja wymaga tabeli search_logs
    # Na razie nic nie robimy
    pass