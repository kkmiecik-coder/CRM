"""
Eksport funkcji z serwisów modułu Help
"""

# Help Service (główna logika CRUD)
from .help_service import (
    # Kategorie
    get_all_categories,
    get_category_by_id,
    create_category,
    update_category,
    delete_category,
    
    # Artykuły
    get_all_articles,
    get_article_by_id,
    get_article_by_slug,
    create_article,
    update_article,
    delete_article,
    toggle_article_visibility,
    
    # Pomocnicze
    sanitize_html,
    extract_headings,
    get_category_with_articles
)

# Slug Generator
from .slug_generator import (
    generate_unique_slug,
    validate_slug,
    sanitize_slug
)

# Search Service
from .search_service import (
    search_articles,
    generate_excerpt,
    highlight_text,
    strip_html_tags,
    get_popular_searches,
    log_search_query
)

# Media Service
from .media_service import (
    upload_image,
    get_all_media,
    delete_media,
    get_media_info,
    allowed_file
)


__all__ = [
    # Help Service
    'get_all_categories',
    'get_category_by_id',
    'create_category',
    'update_category',
    'delete_category',
    'get_all_articles',
    'get_article_by_id',
    'get_article_by_slug',
    'create_article',
    'update_article',
    'delete_article',
    'toggle_article_visibility',
    'sanitize_html',
    'extract_headings',
    'get_category_with_articles',
    
    # Slug Generator
    'generate_unique_slug',
    'validate_slug',
    'sanitize_slug',
    
    # Search Service
    'search_articles',
    'generate_excerpt',
    'highlight_text',
    'strip_html_tags',
    'get_popular_searches',
    'log_search_query',
    
    # Media Service
    'upload_image',
    'get_all_media',
    'delete_media',
    'get_media_info',
    'allowed_file'
]