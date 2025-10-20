"""
Routes dla modułu Help/Dokumentacja
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps
import os
from datetime import datetime

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
@access_control(roles=['admin'])
def admin_media():
    """
    Galeria mediów
    """
    media_files = get_all_media()
    
    return render_template('help_admin_media.html',
                         media_files=media_files)


@help_bp.route('/admin/media/upload', methods=['POST'])
@access_control(roles=['admin'])
def admin_media_upload():
    """Upload pliku do galerii mediów"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Brak pliku'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Nie wybrano pliku'}), 400
        
        # Sprawdź rozszerzenie
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}
        filename = file.filename.lower()
        
        if not any(filename.endswith('.' + ext) for ext in allowed_extensions):
            return jsonify({'success': False, 'error': 'Niedozwolony format pliku'}), 400
        
        # Bezpieczna nazwa pliku
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        
        # Unikalna nazwa (jeśli plik już istnieje)
        original_filename = filename
        counter = 1
        
        # POPRAWNA ŚCIEŻKA - używamy current_app.static_folder
        upload_dir = os.path.join(current_app.static_folder, 'help_media')
        
        # Utwórz folder jeśli nie istnieje
        os.makedirs(upload_dir, exist_ok=True)
        
        print(f"[UPLOAD] Upload dir: {upload_dir}")
        print(f"[UPLOAD] Original filename: {original_filename}")
        
        # Sprawdź czy plik już istnieje i dodaj numer
        while os.path.exists(os.path.join(upload_dir, filename)):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            counter += 1
        
        # Zapisz plik
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        print(f"[UPLOAD] File saved to: {filepath}")
        
        # Zwróć URL do pliku
        file_url = url_for('static', filename=f'help_media/{filename}')
        
        return jsonify({
            'success': True,
            'filename': filename,
            'url': file_url
        })
        
    except Exception as e:
        print(f"[UPLOAD] ERROR: {str(e)}")
        import traceback
        print(f"[UPLOAD] TRACEBACK:\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@help_bp.route('/admin/media/<filename>/delete', methods=['POST'])
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
@access_control(roles=['admin'])
def admin_media_info(filename):
    """
    AJAX - informacje o pliku
    """
    info = get_media_info(filename)
    
    if not info:
        return jsonify({'success': False, 'error': 'Plik nie istnieje'})
    
    return jsonify({'success': True, 'info': info})

@help_bp.route('/admin/media/list')
@access_control(roles=['admin'])
def admin_media_list():
    """API endpoint - zwraca listę plików w galerii"""
    try:
        print("[MEDIA LIST] Starting...")
        
        media_dir = os.path.join(current_app.static_folder, 'help_media')
        print(f"[MEDIA LIST] Media dir: {media_dir}")
        print(f"[MEDIA LIST] Exists: {os.path.exists(media_dir)}")
        
        if not os.path.exists(media_dir):
            print("[MEDIA LIST] Directory doesn't exist, returning empty list")
            return jsonify({'success': True, 'media_files': []})
        
        media_files = []
        
        print(f"[MEDIA LIST] Listing files...")
        for filename in os.listdir(media_dir):
            filepath = os.path.join(media_dir, filename)
            
            if os.path.isfile(filepath):
                print(f"[MEDIA LIST] Processing file: {filename}")
                file_stat = os.stat(filepath)
                
                file_info = {
                    'filename': filename,
                    'url': url_for('static', filename=f'help_media/{filename}'),
                    'size': file_stat.st_size,
                    'uploaded_at': datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                }
                
                # Get image dimensions if it's an image
                try:
                    from PIL import Image
                    img = Image.open(filepath)
                    file_info['width'] = img.width
                    file_info['height'] = img.height
                    print(f"[MEDIA LIST] Image dimensions: {img.width}x{img.height}")
                except Exception as img_error:
                    print(f"[MEDIA LIST] Could not get dimensions for {filename}: {img_error}")
                    pass
                
                media_files.append(file_info)
        
        # Sort by upload date (newest first)
        media_files.sort(key=lambda x: x['uploaded_at'], reverse=True)
        
        print(f"[MEDIA LIST] Returning {len(media_files)} files")
        return jsonify({'success': True, 'media_files': media_files})
        
    except Exception as e:
        print(f"[MEDIA LIST] ERROR: {str(e)}")
        print(f"[MEDIA LIST] ERROR TYPE: {type(e).__name__}")
        import traceback
        print(f"[MEDIA LIST] TRACEBACK:\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500