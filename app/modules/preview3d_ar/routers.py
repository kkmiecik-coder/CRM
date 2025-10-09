# modules/preview3d_ar/routers.py - NAPRAWIONA WERSJA

from flask import jsonify, request, render_template, current_app, send_file, send_from_directory, url_for, make_response, abort
from . import preview3d_ar_bp
from .models import TextureConfig, RealityGenerator
from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails
from extensions import db
from sqlalchemy.orm import joinedload
import sys
import os
import mimetypes
import zipfile
import re

# Globalna instancja generatora Reality
reality_generator = None

# Dodaj MIME types
mimetypes.add_type('model/vnd.reality', '.reality')
mimetypes.add_type('model/vnd.usdz+zip', '.usdz')

@preview3d_ar_bp.route('/api/product-3d', methods=['POST'])
def generate_product_3d():
    """API endpoint do generowania konfiguracji 3D dla produktu"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Uniwersalne parsowanie danych z różnych źródeł
        variant_code = data.get('variant') or data.get('variant_code')
        if not variant_code:
            return jsonify({'error': 'Missing variant code'}), 400
            
        # Parsowanie wymiarów z różnych formatów
        dimensions = {}
        if 'dimensions' in data:
            dims = data['dimensions']
            dimensions = {
                'length': dims.get('length', 0),
                'width': dims.get('width', 0), 
                'thickness': dims.get('thickness', 0)
            }
        else:
            dimensions = {
                'length': data.get('length') or data.get('length_cm', 0),
                'width': data.get('width') or data.get('width_cm', 0),
                'thickness': data.get('thickness') or data.get('thickness_cm', 0)
            }
        
        quantity = data.get('quantity', 1)
        
        # Walidacja wymiarów
        if not all(dimensions.values()) or any(d <= 0 for d in dimensions.values()):
            return jsonify({'error': 'Invalid dimensions'}), 400
        
        # Pobierz tekstury dla wariantu z fallbackiem
        try:
            textures = TextureConfig.get_all_textures_for_variant(variant_code)
            species, technology, wood_class = TextureConfig.parse_variant(variant_code)
            
            # Sprawdź czy są dostępne tekstury, jeśli nie - dodaj fallback
            for surf in ['face', 'edge', 'side']:
                if surf not in textures:
                    textures[surf] = {'variants': [], 'fallback_color': '#D0D0D0'}
                    
                if not textures[surf].get('variants'):
                    fallback_colors = {'face': '#D0D0D0', 'edge': '#B0B0B0', 'side': '#909090'}
                    color = fallback_colors.get(surf, '#C0C0C0')
                    fallback_url = f'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="{color}"/></svg>'
                    textures[surf]['variants'] = [fallback_url]
                
        except Exception as e:
            print(f"[Preview3D] Texture error: {str(e)}", file=sys.stderr)
            textures = {
                'face': {'variants': ['data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#D0D0D0"/></svg>'], 'fallback_color': '#D0D0D0'},
                'edge': {'variants': ['data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#B0B0B0"/></svg>'], 'fallback_color': '#B0B0B0'},
                'side': {'variants': ['data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#909090"/></svg>'], 'fallback_color': '#909090'}
            }
            species, technology, wood_class = 'unknown', 'unknown', 'unknown'
        
        # Przygotuj odpowiedź w formacie zgodnym z WoodViewer
        response_data = {
            'geometry': {
                'type': 'box',
                'dimensions': dimensions,
                'quantity': quantity
            },
            'materials': textures,
            'metadata': {
                'variant_code': variant_code,
                'species': species,
                'technology': technology,
                'wood_class': wood_class
            }
        }
        
        print(f"[Preview3D] Generated 3D config for {variant_code}: {dimensions}", file=sys.stderr)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[Preview3D] Error generating 3D config: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Server error: {str(e)}'}), 500

# Dodaj to na końcu pliku routers.py (przed ostatnim def get_reality_generator())

@preview3d_ar_bp.route('/api/debug-usdz/<filename>')
def debug_usdz_file(filename):
    """NOWY: Szczegółowe debugowanie pliku USDZ"""
    try:
        cache_dir = os.path.join(
            current_app.root_path,
            'modules', 'preview3d_ar', 'static', 'ar-models', 'cache'
        )
        file_path = os.path.join(cache_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Plik nie istnieje'}), 404
        
        debug_info = {}
        
        # Podstawowe informacje o pliku
        stat = os.stat(file_path)
        debug_info['file_info'] = {
            'size_bytes': stat.st_size,
            'size_mb': round(stat.st_size / (1024*1024), 3),
            'created': stat.st_mtime,
            'permissions': oct(stat.st_mode)[-3:]
        }
        
        # Analiza zawartości USDZ (ZIP)
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                files = zf.namelist()
                debug_info['archive_info'] = {
                    'files_count': len(files),
                    'files_list': files,
                    'first_file': files[0] if files else None,
                    'first_file_is_usd': files[0].endswith(('.usd', '.usda')) if files else False
                }
                
                # Szczegóły każdego pliku w archiwum
                file_details = []
                for file_name in files:
                    file_info = zf.getinfo(file_name)
                    file_details.append({
                        'name': file_name,
                        'compressed_size': file_info.compress_size,
                        'uncompressed_size': file_info.file_size,
                        'compression_ratio': round(file_info.compress_size / max(file_info.file_size, 1), 3),
                        'is_texture': file_name.lower().endswith(('.jpg', '.jpeg', '.png')),
                        'is_usd': file_name.endswith(('.usd', '.usda'))
                    })
                debug_info['file_details'] = file_details
                
                # Analiza zawartości USD
                usd_files = [f for f in files if f.endswith(('.usd', '.usda'))]
                if usd_files:
                    try:
                        with zf.open(usd_files[0]) as usd_file:
                            usd_content = usd_file.read().decode('utf-8')
                            
                            debug_info['usd_analysis'] = {
                                'file_name': usd_files[0],
                                'content_length': len(usd_content),
                                'has_textures': 'DiffuseTexture' in usd_content,
                                'has_material_binding': 'material:binding' in usd_content,
                                'has_uv_coordinates': 'primvars:st' in usd_content,
                                'has_normals': 'normal3f' in usd_content,
                                'material_count': usd_content.count('def Material'),
                                'mesh_count': usd_content.count('def Mesh'),
                                'shader_count': usd_content.count('def Shader'),
                                'texture_references': []
                            }
                            
                            # Znajdź referencje do tekstur
                            import re
                            texture_refs = re.findall(r'asset inputs:file = @\./(.*?)@', usd_content)
                            debug_info['usd_analysis']['texture_references'] = texture_refs
                            
                            # Sprawdź czy referencje do tekstur istnieją w archiwum
                            missing_textures = []
                            for tex_ref in texture_refs:
                                if tex_ref not in files:
                                    missing_textures.append(tex_ref)
                            debug_info['usd_analysis']['missing_textures'] = missing_textures
                            
                            # Fragment USD dla debugowania (pierwsze 1000 znaków)
                            debug_info['usd_preview'] = usd_content[:1000] + "..." if len(usd_content) > 1000 else usd_content
                            
                    except Exception as e:
                        debug_info['usd_analysis'] = {'error': str(e)}
        
        except zipfile.BadZipFile:
            debug_info['archive_info'] = {'error': 'Plik nie jest prawidłowym archiwum ZIP'}
        
        # Walidacja dla iOS QuickLook
        ios_compatibility = {
            'file_size_ok': stat.st_size < 50 * 1024 * 1024,  # < 50MB
            'has_usd_file': any(f.endswith(('.usd', '.usda')) for f in debug_info.get('archive_info', {}).get('files_list', [])),
            'usd_is_first': debug_info.get('archive_info', {}).get('first_file_is_usd', False),
            'texture_sizes_ok': True,  # Sprawdzimy to poniżej
            'no_missing_textures': len(debug_info.get('usd_analysis', {}).get('missing_textures', [])) == 0
        }
        
        # Sprawdź rozmiary tekstur w archiwum
        large_textures = []
        if 'file_details' in debug_info:
            for file_detail in debug_info['file_details']:
                if file_detail['is_texture'] and file_detail['uncompressed_size'] > 2 * 1024 * 1024:  # > 2MB
                    large_textures.append(file_detail['name'])
        
        ios_compatibility['texture_sizes_ok'] = len(large_textures) == 0
        ios_compatibility['large_textures'] = large_textures
        
        # Ogólna ocena kompatybilności
        compatibility_score = sum(ios_compatibility[key] for key in ios_compatibility if isinstance(ios_compatibility[key], bool))
        total_checks = len([key for key in ios_compatibility if isinstance(ios_compatibility[key], bool)])
        ios_compatibility['score'] = f"{compatibility_score}/{total_checks}"
        ios_compatibility['is_compatible'] = compatibility_score == total_checks
        
        debug_info['ios_compatibility'] = ios_compatibility
        
        # Rekomendacje
        recommendations = []
        if not ios_compatibility['file_size_ok']:
            recommendations.append("Plik jest za duży (>50MB) - zmniejsz tekstury lub geometrię")
        if not ios_compatibility['has_usd_file']:
            recommendations.append("Brak pliku USD w archiwum")
        if not ios_compatibility['usd_is_first']:
            recommendations.append("Plik USD powinien być pierwszym plikiem w archiwum")
        if not ios_compatibility['texture_sizes_ok']:
            recommendations.append(f"Tekstury za duże: {large_textures}")
        if not ios_compatibility['no_missing_textures']:
            missing = debug_info.get('usd_analysis', {}).get('missing_textures', [])
            recommendations.append(f"Brakuje tekstur: {missing}")
        
        if not recommendations:
            recommendations.append("✅ Plik wygląda na kompatybilny z iOS QuickLook")
        
        debug_info['recommendations'] = recommendations
        
        return jsonify({
            'filename': filename,
            'debug_info': debug_info,
            'status': 'compatible' if ios_compatibility['is_compatible'] else 'issues_found'
        })
        
    except Exception as e:
        print(f"[debug_usdz_file] Błąd: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': f'Błąd debugowania: {str(e)}'}), 500

@preview3d_ar_bp.route('/api/generate-reality', methods=['POST'])
def generate_reality():
    """POPRAWIONY: Generuje plik Reality/USDZ"""
    try:
        print("[generate_reality] Rozpoczęcie generowania Reality/USDZ", file=sys.stderr)
        
        data = request.json
        if not data:
            return jsonify({'error': 'Brak danych JSON'}), 400
        
        variant_code = data.get('variant_code')
        dimensions = data.get('dimensions')
        
        if not variant_code:
            return jsonify({'error': 'Brak variant_code'}), 400
        
        if not dimensions:
            return jsonify({'error': 'Brak dimensions'}), 400
        
        print(f"[generate_reality] Dane: {variant_code}, {dimensions}", file=sys.stderr)
        
        # Walidacja wymiarów
        if not all(dimensions.values()) or any(d <= 0 for d in dimensions.values()):
            return jsonify({'error': 'Nieprawidłowe wymiary'}), 400
        
        # Przygotuj dane produktu
        product_data = {
            'variant_code': variant_code,
            'dimensions': dimensions
        }
        
        # Generuj Reality/USDZ
        generator = get_reality_generator()
        reality_path = generator.generate_reality(product_data)
        
        if not reality_path or not os.path.exists(reality_path):
            return jsonify({'error': 'Błąd generowania pliku AR'}), 500
        
        # Pobierz informacje o pliku
        model_info = generator.get_model_info(reality_path)
        
        # Określ format na podstawie rozszerzenia
        file_ext = os.path.splitext(reality_path)[1].lower()
        format_name = 'Reality' if file_ext == '.reality' else 'USDZ'
        
        # Zwróć pełny URL
        filename = os.path.basename(reality_path)
        file_url = request.url_root.rstrip('/') + url_for('preview3d_ar.serve_ar_model', filename=filename)
        
        print(f"[generate_reality] {format_name} wygenerowany: {filename}", file=sys.stderr)
        
        response = {
            'success': True,
            'reality_url': file_url,  # Zachowaj nazwę dla kompatybilności
            'filename': filename,
            'model_info': model_info,
            'format': format_name
        }
        
        # Dodaj validację dla USDZ
        if format_name == 'USDZ' and model_info and 'is_valid_usdz' in model_info:
            response['validation'] = model_info['is_valid_usdz']
        
        return jsonify(response)
        
    except Exception as e:
        print(f"[generate_reality] Błąd: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

@preview3d_ar_bp.route('/api/generate-usdz', methods=['POST'])
def generate_usdz():
    """BACKWARD COMPATIBILITY: Przekierowuje do generate_reality"""
    try:
        print("[generate_usdz] Backward compatibility - przekierowanie do Reality generator", file=sys.stderr)
        
        data = request.json
        if not data:
            return jsonify({'error': 'Brak danych JSON'}), 400
        
        variant_code = data.get('variant_code')
        dimensions = data.get('dimensions')
        
        if not variant_code or not dimensions:
            return jsonify({'error': 'Brak variant_code lub dimensions'}), 400
        
        # Użyj tego samego generatora
        generator = get_reality_generator()
        
        product_data = {
            'variant_code': variant_code,
            'dimensions': dimensions
        }
        
        ar_file_path = generator.generate_reality(product_data)
        
        if not ar_file_path or not os.path.exists(ar_file_path):
            return jsonify({'error': 'Błąd generowania pliku'}), 500
        
        filename = os.path.basename(ar_file_path)
        file_url = request.url_root.rstrip('/') + url_for('preview3d_ar.serve_ar_model', filename=filename)
        model_info = generator.get_model_info(ar_file_path)
        
        print(f"[generate_usdz] Backward compatibility response: {filename}", file=sys.stderr)
        
        return jsonify({
            'success': True,
            'usdz_url': file_url,  # Stara nazwa dla kompatybilności
            'filename': filename,
            'model_info': model_info,
            'note': 'Generated via Reality generator for compatibility'
        })
        
    except Exception as e:
        print(f"[generate_usdz] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

@preview3d_ar_bp.route('/ar-models/<filename>')
def serve_ar_model(filename):
    """POPRAWIONY: Serwuje pliki 3D dla AR z proper USDZ handling"""
    try:
        cache_dir = os.path.join(
            current_app.root_path,
            'modules', 'preview3d_ar', 'static', 'ar-models', 'cache'
        )
        file_path = os.path.join(cache_dir, filename)

        if not os.path.exists(file_path):
            print(f"[serve_ar_model] Plik nie istnieje: {file_path}", file=sys.stderr)
            abort(404)

        _, ext = os.path.splitext(filename.lower())
        file_size = os.path.getsize(file_path)

        print(f"[serve_ar_model] Serwowanie: {filename} ({ext}), rozmiar: {file_size} bytes", file=sys.stderr)

        # USDZ - główny format (nawet jeśli nazywa się .reality)
        if ext in ['.usdz', '.reality']:
            # Sprawdź czy to prawdziwy Reality czy USDZ
            is_real_reality = False
            try:
                # Sprawdź nagłówek pliku
                with open(file_path, 'rb') as f:
                    header = f.read(16)
                    # Reality ma specjalny nagłówek binarny
                    # USDZ to ZIP, więc zaczyna się od 'PK'
                    is_real_reality = not header.startswith(b'PK')
            except:
                pass

            if is_real_reality and ext == '.reality':
                # Prawdziwy plik Reality
                print(f"[serve_ar_model] Serwowanie prawdziwego Reality: {filename}", file=sys.stderr)
                
                response = make_response(send_file(
                    file_path,
                    as_attachment=False,
                    download_name=filename,
                    mimetype='model/vnd.reality'
                ))
                
                response.headers['Content-Type'] = 'model/vnd.reality'
                response.headers['X-AR-Format'] = 'Reality'
                response.headers['X-iOS-QuickLook'] = 'true'
                
            else:
                # USDZ (lub USDZ nazywający się .reality)
                print(f"[serve_ar_model] Serwowanie USDZ: {filename}", file=sys.stderr)
                
                # KLUCZOWE: Sprawdź czy USDZ jest prawidłowy
                generator = get_reality_generator()
                validation = generator._validate_usdz(file_path)
                
                if not validation.get('is_valid_zip', False):
                    print(f"[serve_ar_model] BŁĄD: Nieprawidłowy USDZ: {validation}", file=sys.stderr)
                    abort(500)
                
                if not validation.get('has_usd_file', False):
                    print(f"[serve_ar_model] OSTRZEŻENIE: USDZ bez pliku USD", file=sys.stderr)
                
                response = make_response(send_file(
                    file_path,
                    as_attachment=False,
                    download_name=filename.replace('.reality', '.usdz'),  # Wymuszenie .usdz
                    mimetype='model/vnd.usdz+zip'
                ))
                
                response.headers['Content-Type'] = 'model/vnd.usdz+zip'
                response.headers['X-AR-Format'] = 'USDZ'
                response.headers['X-USDZ-Validation'] = 'valid' if validation.get('first_file_is_usd') else 'warning'
            
            # Wspólne nagłówki dla obu formatów
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            response.headers['Content-Length'] = str(file_size)
            response.headers['Accept-Ranges'] = 'bytes'
            response.headers['Cache-Control'] = 'public, max-age=3600'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['X-AR-Model'] = 'true'
            
            return response

        # GLB files
        elif ext == '.glb':
            response = make_response(send_file(
                file_path,
                as_attachment=False,
                download_name=filename,
                mimetype='model/gltf-binary'
            ))
            response.headers['Content-Type'] = 'model/gltf-binary'
            response.headers['Cache-Control'] = 'public, max-age=3600'
            response.headers['X-AR-Format'] = 'GLB'
            return response

        else:
            # Inne pliki
            return send_file(file_path, as_attachment=False, download_name=filename)

    except Exception as e:
        print(f"[serve_ar_model] Błąd serwowania: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

@preview3d_ar_bp.route('/api/check-textures/<variant>')
def check_textures(variant):
    """Sprawdza dostępność tekstur dla danego wariantu"""
    try:
        textures = TextureConfig.get_all_textures_for_variant(variant)
        species, technology, wood_class = TextureConfig.parse_variant(variant)
        
        return jsonify({
            'variant_code': variant,
            'parsed': {
                'species': species,
                'technology': technology, 
                'wood_class': wood_class
            },
            'textures': textures,
            'available_count': sum(1 for tex in textures.values() if tex.get('variants'))
        })
        
    except ValueError as e:
        return jsonify({'error': f'Invalid variant: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@preview3d_ar_bp.route('/<token>')
def show_quote_3d_viewer(token):
    """Endpoint dla wycen - wyświetla viewer 3D używając public_token"""
    try:
        print(f"[show_quote_3d_viewer] Starting for token: {token}", file=sys.stderr)
        
        quote = db.session.query(Quote)\
            .options(joinedload(Quote.client))\
            .filter_by(public_token=token).first()
        
        if not quote:
            return jsonify({'error': 'Quote not found'}), 404
        
        quote_items = db.session.query(QuoteItem)\
            .filter_by(quote_id=quote.id)\
            .order_by(QuoteItem.product_index, QuoteItem.variant_code)\
            .all()
        
        if not quote_items:
            return jsonify({'error': 'No products found in quote'}), 404
        
        # Grupuj produkty po product_index
        products_dict = {}
        for item in quote_items:
            if item.product_index not in products_dict:
                products_dict[item.product_index] = {
                    'product_index': item.product_index,
                    'dimensions': {
                        'length': float(item.length_cm),
                        'width': float(item.width_cm),
                        'thickness': float(item.thickness_cm)
                    },
                    'variants': []
                }
            
            # Sprawdź dostępność tekstur dla wariantu
            try:
                from .models import TextureConfig
                textures = TextureConfig.get_all_textures_for_variant(item.variant_code)
                has_textures = any(len(tex.get('variants', [])) > 0 for tex in textures.values())
            except Exception:
                has_textures = False
            
            # Dodaj wszystkie warianty z dodatkowymi danymi
            products_dict[item.product_index]['variants'].append({
                'id': item.id,
                'variant_code': item.variant_code,
                'quantity': item.get_quantity(),
                'is_selected': item.is_selected,
                'price_brutto': float(item.get_total_price_brutto()),
                'has_textures': has_textures
            })
        
        # Konwertuj słownik na listę posortowaną po product_index (jak oczekuje szablon)
        products = sorted(products_dict.values(), key=lambda x: x['product_index'])
        
        # Znajdź pierwszy wybrany wariant jako domyślny
        default_product = None
        for product in products:
            selected_variant = next((v for v in product['variants'] if v['is_selected']), None)
            if selected_variant:
                default_product = {
                    'product_index': product['product_index'],
                    'dimensions': product['dimensions'],
                    'variant_code': selected_variant['variant_code'],
                    'quantity': selected_variant['quantity']
                }
                break
        
        # Fallback: jeśli nie ma wybranych, użyj pierwszego dostępnego
        if not default_product and products:
            first_product = products[0]
            first_variant = first_product['variants'][0] if first_product['variants'] else None
            if first_variant:
                default_product = {
                    'product_index': first_product['product_index'],
                    'dimensions': first_product['dimensions'],
                    'variant_code': first_variant['variant_code'],
                    'quantity': first_variant['quantity']
                }
        
        if not default_product:
            return jsonify({'error': 'No valid products found'}), 404
        
        print(f"[show_quote_3d_viewer] Found {len(products)} products", file=sys.stderr)
        print(f"[show_quote_3d_viewer] Default product: {default_product}", file=sys.stderr)
        
        return render_template('preview3d_ar/templates/quote_3d_viewer.html',
            quote=quote,
            products=products,  # Lista zamiast słownika
            default_product=default_product
        )
        
    except Exception as e:
        print(f"[show_quote_3d_viewer] Error: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@preview3d_ar_bp.route('/modal')
def show_3d_modal():
    """Modal z 3D viewerem"""
    return render_template('preview3d_ar/templates/3d_modal.html')

@preview3d_ar_bp.route('/test')
def test_endpoint():
    """Endpoint testowy"""
    return jsonify({
        'module': 'preview3d_ar',
        'status': 'active',
        'formats': ['USDZ (primary)', 'Reality (macOS only)', 'GLB (planned)'],
        'endpoints': [
            '/api/product-3d [POST]',
            '/api/generate-reality [POST] - Returns USDZ or Reality',
            '/api/generate-usdz [POST] - Backward compatibility',
            '/api/check-textures/<variant> [GET]',
            '/<token> [GET]',  # ZMIENIONE z '/quote/<quote_id> [GET]'
            '/modal [GET]',
            '/test [GET]'
        ]
    })

@preview3d_ar_bp.route('/api/ar-info', methods=['GET'])
def ar_info():
    """Informacje o możliwościach AR"""
    try:
        generator = get_reality_generator()
        
        formats = ['USDZ (primary)', 'Reality (macOS only)', 'GLB (planned)']
        
        cache_files = []
        if os.path.exists(generator.cache_dir):
            cache_files = os.listdir(generator.cache_dir)
        
        reality_files = [f for f in cache_files if f.endswith('.reality')]
        usdz_files = [f for f in cache_files if f.endswith('.usdz')]
        
        return jsonify({
            'ar_enabled': True,
            'supported_formats': formats,
            'cache_files': {
                'reality': len(reality_files),
                'usdz': len(usdz_files),
                'total': len(cache_files)
            },
            'cache_dir': generator.cache_dir,
            'temp_dir': generator.temp_dir,
            'primary_format': 'USDZ',
            'reality_converter_available': generator._check_reality_converter_available()
        })
        
    except Exception as e:
        print(f"[ar_info] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

@preview3d_ar_bp.route('/api/ar-cleanup', methods=['POST'])
def ar_cleanup():
    """Czyści pliki tymczasowe AR"""
    try:
        generator = get_reality_generator()
        generator.cleanup_temp_files()
        
        return jsonify({
            'success': True,
            'message': 'Pliki tymczasowe wyczyszczone'
        })
        
    except Exception as e:
        print(f"[ar_cleanup] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

@preview3d_ar_bp.route('/api/validate-usdz/<filename>')
def validate_usdz_file(filename):
    """NOWY: Waliduje konkretny plik USDZ"""
    try:
        cache_dir = os.path.join(
            current_app.root_path,
            'modules', 'preview3d_ar', 'static', 'ar-models', 'cache'
        )
        file_path = os.path.join(cache_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Plik nie istnieje'}), 404
        
        generator = get_reality_generator()
        validation = generator._validate_usdz(file_path)
        model_info = generator.get_model_info(file_path)
        
        return jsonify({
            'filename': filename,
            'validation': validation,
            'model_info': model_info,
            'recommendations': _get_usdz_recommendations(validation)
        })
        
    except Exception as e:
        print(f"[validate_usdz_file] Błąd: {str(e)}", file=sys.stderr)
        return jsonify({'error': f'Błąd serwera: {str(e)}'}), 500

def _get_usdz_recommendations(validation):
    """Zwraca rekomendacje na podstawie walidacji USDZ"""
    recommendations = []
    
    if not validation.get('is_valid_zip', False):
        recommendations.append('KRYTYCZNE: Plik nie jest prawidłowym archiwum ZIP')
        return recommendations
    
    if not validation.get('has_usd_file', False):
        recommendations.append('BŁĄD: Brak pliku USD w archiwum')
    
    if not validation.get('first_file_is_usd', False):
        recommendations.append('OSTRZEŻENIE: Pierwszy plik nie jest plikiem USD (może powodować problemy w iOS)')
    
    if validation.get('files_count', 0) == 1:
        recommendations.append('OK: Minimalistyczna struktura (tylko USD)')
    elif validation.get('files_count', 0) > 10:
        recommendations.append('UWAGA: Dużo plików w archiwum (może wpływać na wydajność)')
    
    if len(recommendations) == 0:
        recommendations.append('✅ Plik USDZ wygląda na prawidłowy')
    
    return recommendations

@preview3d_ar_bp.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found in preview3d_ar module'}), 404

def get_reality_generator():
    """Lazy initialization generatora Reality"""
    global reality_generator
    if reality_generator is None:
        reality_generator = RealityGenerator()
    return reality_generator

@preview3d_ar_bp.route('/api/generate-glb', methods=['POST'])
def generate_glb():
    """API endpoint do generowania GLB dla Android AR"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Parsowanie danych
        variant_code = data.get('variant_code')
        if not variant_code:
            return jsonify({'error': 'Missing variant_code'}), 400
            
        dimensions = data.get('dimensions', {})
        if not all(k in dimensions for k in ['length', 'width', 'thickness']):
            return jsonify({'error': 'Missing or invalid dimensions'}), 400
        
        quality = data.get('quality', 'medium')
        
        print(f"[generate_glb] GLB request: {variant_code}, dims: {dimensions}", file=sys.stderr)
        
        # Utwórz dane produktu
        product_data = {
            'variant_code': variant_code,
            'dimensions': {
                'length': float(dimensions['length']),
                'width': float(dimensions['width']),
                'thickness': float(dimensions['thickness'])
            },
            'quality': quality,
            'format': 'glb'
        }
        
        # Użyj tego samego generatora co USDZ, ale z formatem GLB
        generator = get_reality_generator()
        
        try:
            # Wygeneruj GLB file
            glb_result = generator.generate_glb_file(product_data)
            
            if not glb_result.get('success'):
                return jsonify({
                    'success': False,
                    'error': glb_result.get('error', 'GLB generation failed')
                }), 500
            
            # Zwróć URL do pliku GLB
            return jsonify({
                'success': True,
                'glb_url': glb_result['file_url'],
                'file_size': glb_result.get('file_size', 0),
                'cache_key': glb_result.get('cache_key'),
                'format': 'glb',
                'platform': 'android'
            })
            
        except Exception as gen_error:
            print(f"[generate_glb] Generation error: {str(gen_error)}", file=sys.stderr)
            return jsonify({
                'success': False,
                'error': f'GLB generation failed: {str(gen_error)}'
            }), 500
            
    except Exception as e:
        print(f"[generate_glb] Unexpected error: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}'
        }), 500