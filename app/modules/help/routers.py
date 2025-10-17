"""
Routes dla modułu Help/Dokumentacja
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps

from .services import (
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
    extract_headings,
    get_category_with_articles,
    
    # Search
    search_articles,
    
    # Media
    upload_image,
    get_all_media,
    delete_media,
    get_media_info
)

# Import dekoratora admin z modułu users
from modules.users.decorators import access_control

# Tworzenie blueprintu
help_bp = Blueprint('help', __name__, 
                    template_folder='templates',
                    static_folder='static',
                    url_prefix='/help')


# ==================== PUBLIC ROUTES ====================

@help_bp.route('/')
@login_required
def index():
    """
    Strona główna /help - boxy kategorii z artykułami
    """
    categories = get_all_categories(visible_only=True)
    
    # Dodaj artykuły do każdej kategorii
    categories_with_articles = []
    for category in categories:
        articles = get_all_articles(category_id=category.id, published_only=True)
        categories_with_articles.append({
            'category': category,
            'articles': articles
        })
    
    return render_template('help_main.html', 
                         categories=categories_with_articles)


@help_bp.route('/<slug>')
@login_required
def article(slug):
    """
    Wyświetlanie pojedynczego artykułu /help/<slug>
    """
    article = get_article_by_slug(slug)
    
    if not article:
        flash('Artykuł nie został znaleziony', 'error')
        return redirect(url_for('help.index'))
    
    # Sprawdź czy opublikowany (chyba że admin)
    if not article.is_published and not current_user.is_admin:
        flash('Artykuł nie jest dostępny', 'error')
        return redirect(url_for('help.index'))
    
    # Zwiększ licznik wyświetleń
    article.increment_views()
    
    # Wyciągnij nagłówki dla sidebara
    headings = extract_headings(article.content)
    
    # Pobierz wszystkie kategorie dla sidebara
    all_categories = get_all_categories(visible_only=True)
    
    # Breadcrumbs
    breadcrumbs = [
        {'name': 'Pomoc', 'url': url_for('help.index')},
        {'name': article.category.name, 'url': None},
        {'name': article.title, 'url': None}
    ]
    
    return render_template('help_article.html',
                         article=article,
                         headings=headings,
                         categories=all_categories,
                         breadcrumbs=breadcrumbs)


@help_bp.route('/search')
@login_required
def search():
    """
    Wyszukiwarka /help/search?q=<query>
    """
    query = request.args.get('q', '').strip()
    
    if not query:
        flash('Wprowadź frazę do wyszukania', 'warning')
        return redirect(url_for('help.index'))
    
    # Minimalna długość query
    if len(query) < 2:
        flash('Fraza musi mieć minimum 2 znaki', 'warning')
        return redirect(url_for('help.index'))
    
    # Wyszukaj
    results = search_articles(query, limit=20, published_only=True)
    
    return render_template('help_search_results.html',
                         query=query,
                         results=results,
                         results_count=len(results))


# ==================== ADMIN ROUTES ====================

@help_bp.route('/admin/articles')
@login_required
@access_control(roles=['admin'])
def admin_articles_list():
    """
    Panel admina - lista wszystkich artykułów
    """
    # Filtrowanie po kategorii
    category_id = request.args.get('category_id', type=int)
    
    if category_id:
        articles = get_all_articles(category_id=category_id)
    else:
        articles = get_all_articles()
    
    categories = get_all_categories()
    
    return render_template('help_admin_list.html',
                         articles=articles,
                         categories=categories,
                         selected_category=category_id)


@help_bp.route('/admin/articles/new', methods=['GET', 'POST'])
@login_required
@access_control(roles=['admin'])
def admin_article_new():
    """
    Tworzenie nowego artykułu
    """
    if request.method == 'GET':
        categories = get_all_categories()
        return render_template('help_admin_editor.html',
                             categories=categories,
                             article=None,
                             mode='new')
    
    # POST - zapis artykułu
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category_id = request.form.get('category_id', type=int)
    slug = request.form.get('slug', '').strip()
    is_published = request.form.get('is_published') == 'on'
    
    # Tworzenie
    result = create_article(
        title=title,
        content=content,
        category_id=category_id,
        author_id=current_user.id,
        slug=slug if slug else None,
        is_published=is_published
    )
    
    if result['success']:
        flash('Artykuł został utworzony', 'success')
        return redirect(url_for('help.admin_articles_list'))
    else:
        flash(result['error'], 'error')
        categories = get_all_categories()
        return render_template('help_admin_editor.html',
                             categories=categories,
                             article=None,
                             mode='new',
                             form_data=request.form)


@help_bp.route('/admin/articles/<int:article_id>/edit', methods=['GET', 'POST'])
@login_required
@access_control(roles=['admin'])
def admin_article_edit(article_id):
    """
    Edycja istniejącego artykułu
    """
    article = get_article_by_id(article_id)
    
    if not article:
        flash('Artykuł nie istnieje', 'error')
        return redirect(url_for('help.admin_articles_list'))
    
    if request.method == 'GET':
        categories = get_all_categories()
        return render_template('help_admin_editor.html',
                             categories=categories,
                             article=article,
                             mode='edit')
    
    # POST - aktualizacja
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category_id = request.form.get('category_id', type=int)
    slug = request.form.get('slug', '').strip()
    is_published = request.form.get('is_published') == 'on'
    
    result = update_article(
        article_id=article_id,
        title=title,
        content=content,
        category_id=category_id,
        slug=slug,
        is_published=is_published
    )
    
    if result['success']:
        flash('Artykuł został zaktualizowany', 'success')
        return redirect(url_for('help.admin_articles_list'))
    else:
        flash(result['error'], 'error')
        categories = get_all_categories()
        return render_template('help_admin_editor.html',
                             categories=categories,
                             article=article,
                             mode='edit')


@help_bp.route('/admin/articles/<int:article_id>/delete', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_article_delete(article_id):
    """
    Usuwanie artykułu
    """
    result = delete_article(article_id)
    
    if result['success']:
        flash('Artykuł został usunięty', 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('help.admin_articles_list'))


@help_bp.route('/admin/articles/<int:article_id>/toggle-visibility', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_article_toggle_visibility(article_id):
    """
    AJAX - przełączanie widoczności artykułu
    """
    result = toggle_article_visibility(article_id)
    
    return jsonify(result)


# ==================== ADMIN - KATEGORIE ====================

@help_bp.route('/admin/categories')
@login_required
@access_control(roles=['admin'])
def admin_categories():
    """
    Zarządzanie kategoriami
    """
    categories = get_all_categories()
    
    return render_template('help_admin_categories.html',
                         categories=categories)


@help_bp.route('/admin/categories/create', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_category_create():
    """
    Tworzenie nowej kategorii
    """
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '📄').strip()
    sort_order = request.form.get('sort_order', 0, type=int)
    is_visible = request.form.get('is_visible') == 'on'
    
    result = create_category(
        name=name,
        icon=icon,
        sort_order=sort_order,
        is_visible=is_visible
    )
    
    if result['success']:
        flash('Kategoria została utworzona', 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('help.admin_categories'))


@help_bp.route('/admin/categories/<int:category_id>/edit', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_category_edit(category_id):
    """
    Edycja kategorii
    """
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', '').strip()
    sort_order = request.form.get('sort_order', type=int)
    is_visible = request.form.get('is_visible') == 'on'
    
    result = update_category(
        category_id=category_id,
        name=name,
        icon=icon,
        sort_order=sort_order,
        is_visible=is_visible
    )
    
    if result['success']:
        flash('Kategoria została zaktualizowana', 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('help.admin_categories'))


@help_bp.route('/admin/categories/<int:category_id>/delete', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_category_delete(category_id):
    """
    Usuwanie kategorii (z opcją przeniesienia artykułów)
    """
    move_articles_to = request.form.get('move_to', type=int)
    
    result = delete_category(
        category_id=category_id,
        move_articles_to=move_articles_to
    )
    
    if result['success']:
        flash('Kategoria została usunięta', 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('help.admin_categories'))


# ==================== ADMIN - MEDIA ====================

@help_bp.route('/admin/media')
@login_required
@access_control(roles=['admin'])
def admin_media():
    """
    Galeria mediów
    """
    media_files = get_all_media()
    
    return render_template('help_admin_media.html',
                         media_files=media_files)


@help_bp.route('/admin/media/upload', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_media_upload():
    """
    Upload nowego obrazka
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Brak pliku'})
    
    file = request.files['file']
    
    result = upload_image(file, current_user.id)
    
    return jsonify(result)


@help_bp.route('/admin/media/<filename>/delete', methods=['POST'])
@login_required
@access_control(roles=['admin'])
def admin_media_delete(filename):
    """
    Usuwanie obrazka
    """
    result = delete_media(filename)
    
    if result['success']:
        flash('Plik został usunięty', 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('help.admin_media'))


@help_bp.route('/admin/media/<filename>/info')
@login_required
@access_control(roles=['admin'])
def admin_media_info(filename):
    """
    AJAX - informacje o pliku
    """
    info = get_media_info(filename)
    
    if not info:
        return jsonify({'success': False, 'error': 'Plik nie istnieje'})
    
    return jsonify({'success': True, 'info': info})