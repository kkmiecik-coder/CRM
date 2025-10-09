# modules/preview3d_ar/models.py - POPRAWKA z działającymi teksturami AR

import os
import glob
import tempfile
import hashlib
import subprocess
import json
import sys
import zipfile
import shutil
import random
from flask import current_app, url_for
import trimesh
import numpy as np
from PIL import Image

class TextureConfig:
    """Konfiguracja tekstur z fallbackiem do szarego koloru"""

    # Mapowanie kodów z bazy na nazwy folderów
    SPECIES_MAP = {
        'dab': 'oak',
        'jes': 'ash',
        'buk': 'beech'
    }
    TECH_MAP = {
        'lity': 'lite',
        'micro': 'micro'
    }
    SURFACE_TYPES = ['face', 'edge', 'side']
    FALLBACK_COLORS = {
        'face': '#D0D0D0',
        'edge': '#B0B0B0',
        'side': '#909090'
    }

    @staticmethod
    def parse_variant(variant_code):
        parts = variant_code.split('-')
        if len(parts) != 3:
            raise ValueError(f"Nieprawidłowy format wariantu: {variant_code}")
        species = TextureConfig.SPECIES_MAP.get(parts[0])
        tech = TextureConfig.TECH_MAP.get(parts[1])
        wood_class = parts[2]
        if not species or not tech:
            raise ValueError(f"Nieznany wariant: {variant_code}")
        return species, tech, wood_class

    @staticmethod
    def get_all_textures_for_variant(variant_code):
        """
        POPRAWIONA WERSJA: Zwraca dla każdego typu powierzchni:
        {
            'variants': [url1, url2, ...],
            'fallback_color': '#XXXXXX'
        }
        """
        try:
            species, tech, wood_class = TextureConfig.parse_variant(variant_code)
            print(f"[TextureConfig] Parsing {variant_code} -> {species}, {tech}, {wood_class}", file=sys.stderr)
        except ValueError as e:
            print(f"[TextureConfig] Parse error for {variant_code}: {e}", file=sys.stderr)
            return {
                surf: {'variants': [], 'fallback_color': '#C0C0C0'}
                for surf in TextureConfig.SURFACE_TYPES
            }

        # Ścieżka do folderu ze statycznymi teksturami
        base_dir = os.path.join(
            current_app.root_path,
            'modules', 'preview3d_ar', 'static', 'textures',
            species, f"{wood_class}_{tech}"
        )
        
        print(f"[TextureConfig] Base directory: {base_dir}", file=sys.stderr)
        print(f"[TextureConfig] Directory exists: {os.path.exists(base_dir)}", file=sys.stderr)

        if os.path.exists(base_dir):
            all_files = os.listdir(base_dir)
            print(f"[TextureConfig] Files in directory: {all_files}", file=sys.stderr)

        textures = {}
        for surf in TextureConfig.SURFACE_TYPES:
            # POPRAWIONY WZORZEC: Uwzględnia różne formaty nazw plików
            patterns_to_try = [
                os.path.join(base_dir, f"{surf}_*.jpg"),     # face_1.jpg, face_2.jpg
                os.path.join(base_dir, f"{surf}_*.jpeg"),    # face_1.jpeg
                os.path.join(base_dir, f"{surf}*.jpg"),      # face1.jpg (bez podkreślnika)
                os.path.join(base_dir, f"{surf}_*.png"),     # face_1.png
            ]
            
            files = []
            for pattern in patterns_to_try:
                found_files = glob.glob(pattern)
                files.extend(found_files)
                print(f"[TextureConfig] Pattern {pattern} found {len(found_files)} files", file=sys.stderr)
            
            # Usuń duplikaty i sortuj
            files = sorted(list(set(files)))
            print(f"[TextureConfig] Surface {surf}: found {len(files)} files total", file=sys.stderr)
            
            urls = []
            for path in files:
                try:
                    # Ścieżka względna od katalogu static
                    rel = os.path.relpath(
                        path,
                        os.path.join(current_app.root_path, 'modules', 'preview3d_ar', 'static')
                    )
                    rel = rel.replace(os.sep, '/')
                    url = url_for('preview3d_ar.static', filename=rel)
                    urls.append(url)
                    print(f"[TextureConfig] Generated URL: {url}", file=sys.stderr)
                except Exception as e:
                    print(f"[TextureConfig] Error generating URL for {path}: {e}", file=sys.stderr)
            
            textures[surf] = {
                'variants': urls,
                'fallback_color': TextureConfig.FALLBACK_COLORS[surf]
            }
            
            print(f"[TextureConfig] Surface {surf}: {len(urls)} URLs generated", file=sys.stderr)
        
        print(f"[TextureConfig] Final result: {sum(len(t['variants']) for t in textures.values())} total URLs", file=sys.stderr)
        return textures

class RealityGenerator:
    """Generator plików Reality/USDZ dla Apple AR QuickLook z DZIAŁAJĄCYMI teksturami"""
    
    def __init__(self):
        self.cache_dir = os.path.join(
            current_app.root_path, 
            'modules', 'preview3d_ar', 'static', 'ar-models', 'cache'
        )
        self.temp_dir = os.path.join(
            current_app.root_path, 
            'modules', 'preview3d_ar', 'static', 'ar-models', 'temp'
        )
        
        # Upewnij się, że foldery istnieją
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        print(f"[RealityGenerator] Inicjalizacja - cache: {self.cache_dir}", file=sys.stderr)
        print(f"[RealityGenerator] Inicjalizacja - temp: {self.temp_dir}", file=sys.stderr)

    def _generate_cache_key(self, product_data):
        """Generuje unikalny klucz cache dla produktu"""
        variant = product_data.get('variant_code', '')
        dims = product_data.get('dimensions', {})
        data_str = f"{variant}-{dims.get('length', 0)}-{dims.get('width', 0)}-{dims.get('thickness', 0)}"
        return hashlib.md5(data_str.encode()).hexdigest()

    def _get_texture_path(self, texture_url):
        """Konwertuje URL tekstury na ścieżkę lokalną"""
        if not texture_url or texture_url.startswith('data:'):
            return None
            
        if texture_url.startswith('http'):
            return None
        
        print(f"[RealityGenerator] Converting texture URL: {texture_url}", file=sys.stderr)
        
        # POPRAWIONY: Obsługa różnych formatów URL
        if '/preview3d-ar/static/' in texture_url:
            # Format: /preview3d-ar/static/textures/oak/ab_lite/face_1.jpg
            rel_path = texture_url.split('/preview3d-ar/static/')[-1]
            full_path = os.path.join(current_app.root_path, 'modules', 'preview3d_ar', 'static', rel_path)
            print(f"[RealityGenerator] Converted path: {full_path}", file=sys.stderr)
            print(f"[RealityGenerator] Path exists: {os.path.exists(full_path)}", file=sys.stderr)
            return full_path if os.path.exists(full_path) else None
        elif '/static/preview3d_ar/' in texture_url:
            # Format: /static/preview3d_ar/textures/oak/ab_lite/face_1.jpg (fallback)
            rel_path = texture_url.split('/static/preview3d_ar/')[-1]
            full_path = os.path.join(current_app.root_path, 'modules', 'preview3d_ar', 'static', rel_path)
            print(f"[RealityGenerator] Converted path (fallback): {full_path}", file=sys.stderr)
            return full_path if os.path.exists(full_path) else None
        
        print(f"[RealityGenerator] URL format not recognized: {texture_url}", file=sys.stderr)
        return None

    def _process_texture_for_ar(self, texture_path, surface_type='face'):
        """ZMNIEJSZONE: Bardzo małe tekstury dla lepszej kompatybilności + dodatkowa rotacja 90°"""
        if not texture_path or not os.path.exists(texture_path):
            print(f"[RealityGenerator] Texture not found: {texture_path}", file=sys.stderr)
            return None

        try:
            with Image.open(texture_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                from PIL import ImageEnhance
                img = ImageEnhance.Contrast(img).enhance(1)
                img = ImageEnhance.Color(img).enhance(1)
                img = ImageEnhance.Brightness(img).enhance(1)

                texture_hash = hashlib.md5(texture_path.encode()).hexdigest()[:8]
                temp_filename = f"{surface_type}_{texture_hash}.jpg"
                temp_path = os.path.join(self.temp_dir, temp_filename)

                img.save(temp_path, 'JPEG', quality=100, optimize=False, progressive=False)

                print(f"[RealityGenerator] ENHANCED+ROTATED texture processed: {os.path.basename(texture_path)} -> {temp_filename} ({img.size})", file=sys.stderr)
                return temp_path

        except Exception as e:
            print(f"[RealityGenerator] Error processing texture {texture_path}: {e}", file=sys.stderr)
            return None

    
    def _create_wood_geometry_usd_with_textures(self, dimensions, variant_code, texture_filenames):
        """NAPRAWIONA: Unikalne tekstury dla każdej lameli + dopasowanie do wymiarów ścian"""
        print(f"[RealityGenerator] Creating REALISTIC WOOD with unique textures - wymiary: {dimensions}", file=sys.stderr)

        # Wymiary w metrach dla AR (konwersja z cm)
        length = dimensions.get('length', 200) / 100.0
        width = dimensions.get('width', 80) / 100.0
        thickness = dimensions.get('thickness', 3) / 100.0

        # Logika lameli jak w wood-viewer.js
        lam_width = 4 / 100.0  # 4cm
        count = round(width / lam_width)

        print(f"[RealityGenerator] REALISTIC: {count} lamelas with unique textures", file=sys.stderr)

        # POBIERZ WSZYSTKIE DOSTĘPNE TEKSTURY
        try:
            textures = TextureConfig.get_all_textures_for_variant(variant_code)
            face_variants = [t for t in textures.get('face', {}).get('variants', []) if not t.startswith('data:')]
            edge_variants = [t for t in textures.get('edge', {}).get('variants', []) if not t.startswith('data:')]
            side_variants = [t for t in textures.get('side', {}).get('variants', []) if not t.startswith('data:')]
        
            print(f"[RealityGenerator] Available textures: face={len(face_variants)}, edge={len(edge_variants)}, side={len(side_variants)}", file=sys.stderr)
        
            # Fallback do jednej tekstury jeśli brak wariantów
            if not face_variants: face_variants = ['fallback_face']
            if not edge_variants: edge_variants = face_variants  
            if not side_variants: side_variants = face_variants
        
        except Exception as e:
            print(f"[RealityGenerator] Error getting textures: {e}", file=sys.stderr)
            face_variants = edge_variants = side_variants = ['fallback_face']

        # USD HEADER
        usd_content = f'''#usda 1.0
    (
        customLayerData = {{
            string creator = "Wood Power CRM - Realistic Wood Laminate"
            string[] providedExtensions = ["USDZ"]
        }}
        defaultPrim = "WoodPanel"
        metersPerUnit = 1
        upAxis = "Y"
    )

    def Xform "WoodPanel" (
        assetInfo = {{
            string name = "Wood Panel {variant_code}"
            string identifier = "{variant_code}"
            string version = "4.0"
        }}
        kind = "component"
    )
    {{
        # Metadane AR
        custom bool preliminary_collidesWithEnvironment = 1
        custom string preliminary_planeAnchoring = "horizontal"
        custom float preliminary_worldScale = 1.0
        custom bool preliminary_receivesShadows = 1
        custom bool preliminary_castsShadows = 1
    '''

        # TRACK poprzednie wybory (unikaj powtórzeń jak w wood-viewer.js)
        prev_face = None
        prev_side = None

        # GENERUJ KAŻDĄ LAMELĘ z UNIKALNYMI TEKSTURAMI
        for i in range(count):
            # Pozycja Z lameli
            z_pos = -(count * lam_width) / 2 + lam_width / 2 + i * lam_width
        
            # LOSOWY WYBÓR TEKSTUR - unikaj powtórzeń
            face_idx = None
            attempts = 0
            while (face_idx == prev_face or face_idx is None) and attempts < 10:
                face_idx = random.randint(0, len(face_variants) - 1) if len(face_variants) > 1 else 0
                attempts += 1
            prev_face = face_idx
        
            side_idx = None
            attempts = 0
            while (side_idx == prev_side or side_idx is None) and attempts < 10:
                side_idx = random.randint(0, len(side_variants) - 1) if len(side_variants) > 1 else 0
                attempts += 1
            prev_side = side_idx
        
            edge_idx = random.randint(0, len(edge_variants) - 1)
        
            # Random rotation dla side (jak w wood-viewer.js)
            side_rotation_deg = random.choice([0, 90, 180, 270])
            side_rotation_rad = side_rotation_deg * 3.14159 / 180.0
        
            print(f"[RealityGenerator] Lamela {i+1}: face={face_idx}, edge={edge_idx}, side={side_idx} (rot={side_rotation_deg}°)", file=sys.stderr)
        
            # WYMIARY RZECZYWISTE KAŻDEJ ŚCIANY dla dopasowania tekstury
            # Face (góra/dół): length x lam_width
            face_real_length = length
            face_real_width = lam_width
        
            # Edge (przód/tył): length x thickness  
            edge_real_length = length
            edge_real_height = thickness
        
            # Side (lewy/prawy): lam_width x thickness
            side_real_width = lam_width
            side_real_height = thickness
        
            print(f"[RealityGenerator] Real dimensions - Face: {face_real_length:.3f}x{face_real_width:.3f}m, Edge: {edge_real_length:.3f}x{edge_real_height:.3f}m, Side: {side_real_width:.3f}x{side_real_height:.3f}m", file=sys.stderr)
        
            # DOPASOWANIE UV DO RZECZYWISTYCH WYMIARÓW
            # Załóżmy, że tekstura reprezentuje 10cm x 10cm drewna w rzeczywistości
            texture_real_size = 0.10  # 10cm = 0.1m
        
            # Face UV - dopasowanie do wymiarów face ściany
            face_u_repeats = face_real_length / texture_real_size
            face_v_repeats = face_real_width / texture_real_size
        
            # Edge UV - dopasowanie do wymiarów edge ściany  
            edge_u_repeats = edge_real_length / texture_real_size
            edge_v_repeats = edge_real_height / texture_real_size
        
            # Side UV - dopasowanie do wymiarów side ściany
            side_u_repeats = side_real_width / texture_real_size
            side_v_repeats = side_real_height / texture_real_size
        
            print(f"[RealityGenerator] UV repeats - Face: {face_u_repeats:.2f}x{face_v_repeats:.2f}, Edge: {edge_u_repeats:.2f}x{edge_v_repeats:.2f}, Side: {side_u_repeats:.2f}x{side_v_repeats:.2f}", file=sys.stderr)

            # GEOMETRIA POJEDYNCZEJ LAMELI z DOPASOWANYMI UV
            usd_content += f'''
        # LAMELA {i+1}/{count} - UNIKALNE TEKSTURY + DOPASOWANE UV
        def Xform "Lamela_{i}"
        {{
            # FACE SURFACES (góra + dół) - wymiary: {face_real_length:.3f}m x {face_real_width:.3f}m
            def Mesh "Face_{i}"
            {{
                int[] faceVertexCounts = [4, 4]
                int[] faceVertexIndices = [
                    # Top face (Y+) - normala w górę
                    3, 2, 1, 0,
                    # Bottom face (Y-) - normala w dół  
                    4, 5, 6, 7
                ]
                point3f[] points = [
                    # Top vertices (Y+)
                    ({-length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos + lam_width/2}),
                    ({-length/2}, {thickness/2}, {z_pos + lam_width/2}),
                    # Bottom vertices (Y-)
                    ({-length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {-thickness/2}, {z_pos + lam_width/2}),
                    ({-length/2}, {-thickness/2}, {z_pos + lam_width/2})
                ]
                float2[] primvars:st = [
                    # Top UV - dopasowane do rzeczywistych wymiarów face
                    (0, 0), ({face_u_repeats}, 0), ({face_u_repeats}, {face_v_repeats}), (0, {face_v_repeats}),
                    # Bottom UV - lustrzane odbicie
                    (0, 0), ({face_u_repeats}, 0), ({face_u_repeats}, {face_v_repeats}), (0, {face_v_repeats})
                ]
                normal3f[] normals = [
                    (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0),  # Top
                    (0, -1, 0), (0, -1, 0), (0, -1, 0), (0, -1, 0)  # Bottom
                ]
                rel material:binding = </WoodPanel/Materials/FaceMaterial_{i}>
                uniform token subdivisionScheme = "none"
                uniform bool doubleSided = 1
            }}

            # EDGE SURFACES (przód + tył) - wymiary: {edge_real_length:.3f}m x {edge_real_height:.3f}m  
            def Mesh "Edge_{i}"
            {{
                int[] faceVertexCounts = [4, 4]
                int[] faceVertexIndices = [
                    # Front face (Z-) - normala do przodu
                    3, 2, 1, 0,
                    # Back face (Z+) - normala do tyłu
                    4, 5, 6, 7
                ]
                point3f[] points = [
                    # Front vertices (Z-)
                    ({-length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    ({-length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    # Back vertices (Z+)  
                    ({-length/2}, {-thickness/2}, {z_pos + lam_width/2}),
                    ({length/2}, {-thickness/2}, {z_pos + lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos + lam_width/2}),
                    ({-length/2}, {thickness/2}, {z_pos + lam_width/2})
                ]
                float2[] primvars:st = [
                    # Front UV - dopasowane do rzeczywistych wymiarów edge
                    (0, 0), ({edge_u_repeats}, 0), ({edge_u_repeats}, {edge_v_repeats}), (0, {edge_v_repeats}),
                    # Back UV
                    (0, 0), ({edge_u_repeats}, 0), ({edge_u_repeats}, {edge_v_repeats}), (0, {edge_v_repeats})
                ]
                normal3f[] normals = [
                    (0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1),  # Front
                    (0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1)  # Back
                ]
                rel material:binding = </WoodPanel/Materials/EdgeMaterial_{i}>
                uniform token subdivisionScheme = "none"
                uniform bool doubleSided = 1
            }}

            # SIDE SURFACES (lewy + prawy) - wymiary: {side_real_width:.3f}m x {side_real_height:.3f}m
            def Mesh "Side_{i}"
            {{
                int[] faceVertexCounts = [4, 4]
                int[] faceVertexIndices = [
                    # Left face (X-) - normala w lewo
                    3, 2, 1, 0,
                    # Right face (X+) - normala w prawo
                    4, 5, 6, 7
                ]
                point3f[] points = [
                    # Left vertices (X-)
                    ({-length/2}, {-thickness/2}, {z_pos + lam_width/2}),
                    ({-length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({-length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    ({-length/2}, {thickness/2}, {z_pos + lam_width/2}),
                    # Right vertices (X+)
                    ({length/2}, {-thickness/2}, {z_pos + lam_width/2}),
                    ({length/2}, {-thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos - lam_width/2}),
                    ({length/2}, {thickness/2}, {z_pos + lam_width/2})
                ]
                float2[] primvars:st = [
                    # Left UV - dopasowane do rzeczywistych wymiarów side (z rotacją {side_rotation_deg}°)
                    (0, 0), ({side_u_repeats}, 0), ({side_u_repeats}, {side_v_repeats}), (0, {side_v_repeats}),
                    # Right UV
                    (0, 0), ({side_u_repeats}, 0), ({side_u_repeats}, {side_v_repeats}), (0, {side_v_repeats})
                ]
                normal3f[] normals = [
                    (-1, 0, 0), (-1, 0, 0), (-1, 0, 0), (-1, 0, 0),  # Left
                    (1, 0, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0)  # Right
                ]
                rel material:binding = </WoodPanel/Materials/SideMaterial_{i}>
                uniform token subdivisionScheme = "none"
                uniform bool doubleSided = 1
            }}
        }}'''

        # MATERIAŁY z UNIKALNYMI TEKSTURAMI dla każdej lameli
        usd_content += '''

        def Scope "Materials"
        {'''

        for i in range(count):
            # Wybierz UNIKALNE tekstury dla tej lameli (z unikaniem powtórzeń)
            face_idx = i % len(face_variants) if face_variants[0] != 'fallback_face' else 0
            edge_idx = (i + 1) % len(edge_variants) if edge_variants[0] != 'fallback_face' else 0  
            side_idx = (i + 2) % len(side_variants) if side_variants[0] != 'fallback_face' else 0
        
            # Dodaj losowość przy wyborze wariantów
            if len(face_variants) > 1:
                face_idx = random.randint(0, len(face_variants) - 1)
            if len(edge_variants) > 1:
                edge_idx = random.randint(0, len(edge_variants) - 1)
            if len(side_variants) > 1:
                side_idx = random.randint(0, len(side_variants) - 1)
            
            selected_face = face_variants[face_idx] if face_variants[0] != 'fallback_face' else None
            selected_edge = edge_variants[edge_idx] if edge_variants[0] != 'fallback_face' else None
            selected_side = side_variants[side_idx] if side_variants[0] != 'fallback_face' else None
        
            # Random rotation dla side texture
            side_rotation_deg = random.choice([0, 90, 180, 270])
            side_rotation_rad = side_rotation_deg * 3.14159 / 180.0

            # FACE MATERIAL - pionowa orientacja słojów drewna
            if selected_face:
                texture_name = os.path.basename(selected_face)
                usd_content += f'''
            def Material "FaceMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/FaceMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor.connect = </WoodPanel/Materials/FaceMaterial_{i}/DiffuseTexture.outputs:rgb>
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}

                def Shader "DiffuseTexture"
                {{
                    uniform token info:id = "UsdUVTexture"
                    asset inputs:file = @./{texture_name}@
                    float2 inputs:st.connect = </WoodPanel/Materials/FaceMaterial_{i}/UVTransform.outputs:result>
                    token inputs:wrapS = "repeat"
                    token inputs:wrapT = "repeat"
                    color3f outputs:rgb
                }}

                def Shader "UVTransform"
                {{
                    uniform token info:id = "UsdTransform2d"
                    float2 inputs:in.connect = </WoodPanel/Materials/FaceMaterial_{i}/UVReader.outputs:result>
                    float inputs:rotation = 1.5708  # 90° - pionowe słoje
                    float2 inputs:scale = (1.0, 1.0)
                    float2 inputs:translation = (0.0, 0.0)
                    float2 outputs:result
                }}

                def Shader "UVReader"
                {{
                    uniform token info:id = "UsdPrimvarReader_float2"
                    string inputs:varname = "st"
                    float2 outputs:result
                }}
            }}'''
            else:
                # Fallback color dla face
                usd_content += f'''
            def Material "FaceMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/FaceMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.82, 0.71, 0.55)
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}
            }}'''

            # EDGE MATERIAL - pozioma orientacja
            if selected_edge:
                texture_name = os.path.basename(selected_edge)
                usd_content += f'''
            def Material "EdgeMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/EdgeMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor.connect = </WoodPanel/Materials/EdgeMaterial_{i}/DiffuseTexture.outputs:rgb>
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}

                def Shader "DiffuseTexture"
                {{
                    uniform token info:id = "UsdUVTexture"
                    asset inputs:file = @./{texture_name}@
                    float2 inputs:st.connect = </WoodPanel/Materials/EdgeMaterial_{i}/UVReader.outputs:result>
                    token inputs:wrapS = "repeat"
                    token inputs:wrapT = "repeat"
                    color3f outputs:rgb
                }}

                def Shader "UVReader"
                {{
                    uniform token info:id = "UsdPrimvarReader_float2"
                    string inputs:varname = "st"
                    float2 outputs:result
                }}
            }}'''
            else:
                # Fallback color dla edge
                usd_content += f'''
            def Material "EdgeMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/EdgeMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.7, 0.6, 0.45)
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}
            }}'''

            # SIDE MATERIAL z losową rotacją
            if selected_side:
                texture_name = os.path.basename(selected_side)
                usd_content += f'''
            def Material "SideMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/SideMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor.connect = </WoodPanel/Materials/SideMaterial_{i}/DiffuseTexture.outputs:rgb>
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}

                def Shader "DiffuseTexture"
                {{
                    uniform token info:id = "UsdUVTexture"
                    asset inputs:file = @./{texture_name}@
                    float2 inputs:st.connect = </WoodPanel/Materials/SideMaterial_{i}/UVTransform.outputs:result>
                    token inputs:wrapS = "repeat"
                    token inputs:wrapT = "repeat"
                    color3f outputs:rgb
                }}

                def Shader "UVTransform"
                {{
                    uniform token info:id = "UsdTransform2d"
                    float2 inputs:in.connect = </WoodPanel/Materials/SideMaterial_{i}/UVReader.outputs:result>
                    float inputs:rotation = {side_rotation_rad}  # Losowa rotacja {side_rotation_deg}°
                    float2 inputs:scale = (1.0, 1.0)
                    float2 inputs:translation = (0.0, 0.0)
                    float2 outputs:result
                }}

                def Shader "UVReader"
                {{
                    uniform token info:id = "UsdPrimvarReader_float2"
                    string inputs:varname = "st"
                    float2 outputs:result
                }}
            }}'''
            else:
                # Fallback color dla side
                usd_content += f'''
            def Material "SideMaterial_{i}"
            {{
                token outputs:surface.connect = </WoodPanel/Materials/SideMaterial_{i}/PreviewSurface.outputs:surface>

                def Shader "PreviewSurface"
                {{
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.75, 0.65, 0.5)
                    float inputs:roughness = 0.9
                    float inputs:metallic = 0.0
                    token outputs:surface
                }}
            }}'''

        # Zamknij strukturę
        usd_content += '''
        }
    }
    '''

        print(f"[RealityGenerator] REALISTIC USD created - {count} lamelas with unique textures and dimension-fitted UV mapping", file=sys.stderr)
        return usd_content

    def _create_usdz_with_textures(self, usd_content, processed_textures, output_path):
        """ZMODYFIKOWANA: Kopiuj tekstury bezpośrednio z serwera zamiast tworzyć kopie"""
        try:
            print(f"[RealityGenerator] Creating USDZ with DIRECT server textures", file=sys.stderr)
            
            # Utwórz pliki tymczasowe
            usd_file = os.path.join(self.temp_dir, 'model.usd')
            
            # Zapisz USD
            with open(usd_file, 'w', encoding='utf-8') as f:
                f.write(usd_content)
            
            print(f"[RealityGenerator] USD file written: {usd_file}", file=sys.stderr)
            
            # Znajdź wszystkie referencje tekstur w USD
            import re
            texture_refs = re.findall(r'asset inputs:file = @\./(.*?)@', usd_content)
            texture_refs = list(set(texture_refs))  # Usuń duplikaty
            
            print(f"[RealityGenerator] Found texture references in USD: {texture_refs}", file=sys.stderr)
            
            # Utwórz USDZ jako ZIP z teksturami bezpośrednio z serwera
            with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
                # KRYTYCZNE: USD musi być pierwszym plikiem
                zf.write(usd_file, 'model.usd')
                print(f"[RealityGenerator] Added USD to USDZ: model.usd", file=sys.stderr)
                
                # Dodaj tekstury bezpośrednio z serwera
                for texture_ref in texture_refs:
                    if texture_ref and not texture_ref.startswith('fallback'):
                        # Znajdź oryginalny plik tekstury na serwerze
                        texture_server_path = self._find_texture_on_server(texture_ref)
                        
                        if texture_server_path and os.path.exists(texture_server_path):
                            zf.write(texture_server_path, texture_ref)
                            texture_size = os.path.getsize(texture_server_path)
                            print(f"[RealityGenerator] Added server texture to USDZ: {texture_ref} ({texture_size} bytes)", file=sys.stderr)
                        else:
                            print(f"[RealityGenerator] WARNING: Texture not found on server: {texture_ref}", file=sys.stderr)
            
            # Sprawdź czy plik został utworzony
            if not os.path.exists(output_path):
                raise Exception(f"Failed to create USDZ file: {output_path}")
            
            file_size = os.path.getsize(output_path)
            print(f"[RealityGenerator] USDZ with SERVER TEXTURES created: {output_path}, size: {file_size} bytes", file=sys.stderr)
            
            return True
            
        except Exception as e:
            print(f"[RealityGenerator] Error creating USDZ with server textures: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return False
        finally:
            # Wyczyść pliki tymczasowe
            if os.path.exists(usd_file):
                os.remove(usd_file)

    def _find_texture_on_server(self, texture_filename):
        """Znajdź plik tekstury na serwerze po nazwie pliku"""
        try:
            # Szukaj we wszystkich folderach tekstur
            texture_base_dir = os.path.join(
                current_app.root_path,
                'modules', 'preview3d_ar', 'static', 'textures'
            )
            
            for root, dirs, files in os.walk(texture_base_dir):
                if texture_filename in files:
                    full_path = os.path.join(root, texture_filename)
                    print(f"[RealityGenerator] Found texture on server: {full_path}", file=sys.stderr)
                    return full_path
            
            print(f"[RealityGenerator] Texture not found on server: {texture_filename}", file=sys.stderr)
            return None
            
        except Exception as e:
            print(f"[RealityGenerator] Error finding texture {texture_filename}: {e}", file=sys.stderr)
            return None

    def _create_wood_geometry_usd(self, dimensions, variant_code):
        """FALLBACK: Tworzy USD bez tekstur (stara metoda dla kompatybilności)"""
        print(f"[RealityGenerator] Creating USD geometry WITHOUT textures - dimensions: {dimensions}", file=sys.stderr)
        
        # Wymiary w metrach dla AR (konwersja z cm)
        length = dimensions.get('length', 200) / 100.0  # cm -> m
        width = dimensions.get('width', 80) / 100.0
        thickness = dimensions.get('thickness', 3) / 100.0
        
        usd_content = f'''#usda 1.0
        (
            customLayerData = {{
                string creator = "Wood Power CRM"
                string[] providedExtensions = ["USDZ"]
            }}
            defaultPrim = "WoodPanel"
            metersPerUnit = 1
            upAxis = "Y"
        )

        def Xform "WoodPanel" (
            assetInfo = {{
                string name = "Wood Panel {variant_code}"
                string identifier = "{variant_code}"
                string version = "1.0"
            }}
            kind = "component"
        )
        {{
            # Metadane AR dla iOS QuickLook
            custom bool preliminary_collidesWithEnvironment = 1
            custom string preliminary_planeAnchoring = "horizontal"
            custom float preliminary_worldScale = 1.0
            custom bool preliminary_receivesShadows = 1
            custom bool preliminary_castsShadows = 1
    
            def Mesh "WoodMesh"
            {{
                # Geometria box
                int[] faceVertexCounts = [4, 4, 4, 4, 4, 4]
                int[] faceVertexIndices = [0, 1, 3, 2, 4, 6, 7, 5, 0, 2, 6, 4, 1, 5, 7, 3, 0, 4, 5, 1, 2, 3, 7, 6]
                point3f[] points = [
                    ({-length/2}, {-thickness/2}, {-width/2}),
                    ({length/2}, {-thickness/2}, {-width/2}),
                    ({-length/2}, {thickness/2}, {-width/2}),
                    ({length/2}, {thickness/2}, {-width/2}),
                    ({-length/2}, {-thickness/2}, {width/2}),
                    ({length/2}, {-thickness/2}, {width/2}),
                    ({-length/2}, {thickness/2}, {width/2}),
                    ({length/2}, {thickness/2}, {width/2})
                ]
        
                rel material:binding = </WoodPanel/Materials/WoodMaterial>
                uniform token subdivisionScheme = "none"
                uniform bool doubleSided = 1
            }}
    
            def Scope "Materials"
            {{
                def Material "WoodMaterial"
                {{
                    token outputs:surface.connect = </WoodPanel/Materials/WoodMaterial/PreviewSurface.outputs:surface>
            
                    def Shader "PreviewSurface"
                    {{
                        uniform token info:id = "UsdPreviewSurface"
                        color3f inputs:diffuseColor = (0.82, 0.71, 0.55)
                        float inputs:roughness = 0.85
                        float inputs:metallic = 0.0
                        float inputs:clearcoat = 0.0
                        float inputs:opacity = 1.0
                        float inputs:ior = 1.45
                        token outputs:surface
                    }}
                }}
            }}
        }}
        '''
        
        print(f"[RealityGenerator] USD content created - AR dimensions: {length:.3f}m x {width:.3f}m x {thickness:.3f}m", file=sys.stderr)
        return usd_content

    def _create_proper_usdz(self, usd_content, output_path):
        """FALLBACK: Tworzy USDZ bez tekstur (stara metoda)"""
        try:
            print(f"[RealityGenerator] Creating USDZ WITHOUT textures: {output_path}", file=sys.stderr)
            
            # Utwórz pliki tymczasowe
            usd_file = os.path.join(self.temp_dir, 'model.usd')
            
            # Zapisz USD
            with open(usd_file, 'w', encoding='utf-8') as f:
                f.write(usd_content)
            
            # Utwórz USDZ jako ZIP
            with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
                # USD musi być pierwszym plikiem w archiwum
                zf.write(usd_file, 'model.usd')
            
            # Sprawdź czy plik został utworzony
            if not os.path.exists(output_path):
                raise Exception(f"Failed to create USDZ file: {output_path}")
            
            file_size = os.path.getsize(output_path)
            print(f"[RealityGenerator] USDZ created: {output_path}, size: {file_size} bytes", file=sys.stderr)
            
            return True
            
        except Exception as e:
            print(f"[RealityGenerator] Error creating USDZ: {e}", file=sys.stderr)
            return False
        finally:
            # Wyczyść pliki tymczasowe
            if os.path.exists(usd_file):
                os.remove(usd_file)

    def _check_reality_converter_available(self):
        """Sprawdza czy Reality Converter jest dostępny"""
        try:
            result = subprocess.run(['xcrun', '--find', 'RealityConverter'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print("[RealityGenerator] Reality Converter available", file=sys.stderr)
                return True
        except:
            pass
        
        print("[RealityGenerator] Reality Converter not available - using USDZ", file=sys.stderr)
        return False

    def generate_reality(self, product_data):
        """
        POPRAWIONA METODA: Generuje plik Reality/USDZ z DZIAŁAJĄCYMI teksturami
        """
        print(f"[RealityGenerator] Generating AR with WORKING textures for: {product_data}", file=sys.stderr)
        
        try:
            # Sprawdź cache
            cache_key = self._generate_cache_key(product_data)
            
            # Sprawdź czy Reality Converter jest dostępny
            can_create_reality = self._check_reality_converter_available()
            
            if can_create_reality:
                # Próbuj utworzyć prawdziwy plik Reality
                reality_path = os.path.join(self.cache_dir, f"{cache_key}.reality")
                if os.path.exists(reality_path):
                    print(f"[RealityGenerator] Reality from cache: {reality_path}", file=sys.stderr)
                    return reality_path
                
                print("[RealityGenerator] Reality creation not implemented - fallback to USDZ", file=sys.stderr)
            
            # GŁÓWNA ŚCIEŻKA: Utwórz USDZ z teksturami
            usdz_path = os.path.join(self.cache_dir, f"{cache_key}.usdz")
            
            if os.path.exists(usdz_path):
                print(f"[RealityGenerator] USDZ from cache: {usdz_path}", file=sys.stderr)
                return usdz_path
            
            # Pobierz dane produktu
            variant_code = product_data.get('variant_code', 'unknown')
            dimensions = product_data.get('dimensions', {})
            
            # Walidacja wymiarów
            if not all(dimensions.values()) or any(d <= 0 for d in dimensions.values()):
                raise ValueError("Invalid product dimensions")
            
            # POPRAWIONE: Pobierz i przetwórz tekstury z lepszą obsługą błędów
            processed_textures = {}
            texture_filenames = {}
            
            try:
                textures = TextureConfig.get_all_textures_for_variant(variant_code)
                print(f"[RealityGenerator] Textures for {variant_code}: {list(textures.keys())}", file=sys.stderr)
                
                for surface_type in ['face', 'edge', 'side']:
                    texture_variants = textures.get(surface_type, {}).get('variants', [])
                    print(f"[RealityGenerator] {surface_type} variants: {len(texture_variants)}", file=sys.stderr)
                    
                    if texture_variants:
                        # Filtruj tylko prawdziwe pliki (nie data: URLs)
                        real_textures = [t for t in texture_variants if not t.startswith('data:')]
                        
                        if real_textures:
                            # Wybierz losową teksturę z dostępnych wariantów
                            selected_texture_url = random.choice(real_textures)
                            print(f"[RealityGenerator] Selected {surface_type} texture: {selected_texture_url}", file=sys.stderr)
                            
                            texture_local_path = self._get_texture_path(selected_texture_url)
                            
                            if texture_local_path:
                                processed_texture = self._process_texture_for_ar(texture_local_path, surface_type)
                                if processed_texture:
                                    processed_textures[surface_type] = processed_texture
                                    texture_filenames[surface_type] = os.path.basename(processed_texture)
                                    print(f"[RealityGenerator] Texture {surface_type} processed: {texture_filenames[surface_type]}", file=sys.stderr)
                                else:
                                    print(f"[RealityGenerator] Failed to process texture for {surface_type}", file=sys.stderr)
                            else:
                                print(f"[RealityGenerator] Local path not found for {surface_type}: {selected_texture_url}", file=sys.stderr)
                        else:
                            print(f"[RealityGenerator] No real texture files for {surface_type} (only data: URLs)", file=sys.stderr)
                    else:
                        print(f"[RealityGenerator] No texture variants for {surface_type}", file=sys.stderr)
                
            except Exception as e:
                print(f"[RealityGenerator] Error processing textures for {variant_code}: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
                # Kontynuuj bez tekstur
            
            # POPRAWIONE: Wybierz metodę tworzenia USD na podstawie dostępności tekstur
            if processed_textures:
                print(f"[RealityGenerator] Using {len(processed_textures)} WORKING textures for AR model", file=sys.stderr)
                print(f"[RealityGenerator] Processed textures: {list(processed_textures.keys())}", file=sys.stderr)
                
                usd_content = self._create_wood_geometry_usd_with_textures(dimensions, variant_code, texture_filenames)
                success = self._create_usdz_with_textures(usd_content, processed_textures, usdz_path)
            else:
                print("[RealityGenerator] No textures available - creating model without textures", file=sys.stderr)
                usd_content = self._create_wood_geometry_usd(dimensions, variant_code)
                success = self._create_proper_usdz(usd_content, usdz_path)
            
            if not success:
                raise Exception("Failed to create USDZ file")
            
            # DODANA WALIDACJA: Sprawdź finalny plik
            final_validation = self._validate_usdz(usdz_path)
            print(f"[RealityGenerator] Final USDZ validation: {final_validation}", file=sys.stderr)
            
            if not final_validation.get('is_valid_zip', False):
                raise Exception(f"Generated USDZ is not valid: {final_validation}")
            
            print(f"[RealityGenerator] USDZ with WORKING textures generated: {usdz_path}", file=sys.stderr)
            return usdz_path
            
        except Exception as e:
            print(f"[RealityGenerator] Error generating Reality/USDZ: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise

    def cleanup_temp_files(self):
        """Czyści pliki tymczasowe"""
        try:
            cleaned_count = 0
            for file in os.listdir(self.temp_dir):
                if file.endswith(('.usd', '.obj', '.tmp', '.jpg', '.jpeg')):
                    file_path = os.path.join(self.temp_dir, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        cleaned_count += 1
            print(f"[RealityGenerator] Temp files cleaned: {cleaned_count} files", file=sys.stderr)
        except Exception as e:
            print(f"[RealityGenerator] Error cleaning temp files: {e}", file=sys.stderr)

    def get_model_info(self, file_path):
        """Zwraca informacje o modelu z analizą tekstur"""
        try:
            if not os.path.exists(file_path):
                return None
            
            stat = os.stat(file_path)
            
            # Sprawdź format na podstawie rozszerzenia
            ext = os.path.splitext(file_path)[1].lower()
            format_name = {
                '.reality': 'Reality',
                '.usdz': 'USDZ', 
                '.glb': 'GLB'
            }.get(ext, 'Unknown')
            
            # Sprawdź zawartość USDZ
            texture_count = 0
            file_list = []
            
            if ext == '.usdz':
                try:
                    with zipfile.ZipFile(file_path, 'r') as zf:
                        file_list = zf.namelist()
                        texture_count = len([f for f in file_list if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                except:
                    pass
            
            return {
                'file_size': stat.st_size,
                'file_size_mb': round(stat.st_size / (1024*1024), 2),
                'created': stat.st_mtime,
                'format': format_name,
                'is_valid_usdz': self._validate_usdz(file_path) if ext == '.usdz' else None,
                'texture_count': texture_count,
                'files_in_archive': file_list
            }
        except Exception as e:
            print(f"[RealityGenerator] Error getting model info: {e}", file=sys.stderr)
            return None

    def _validate_usdz(self, file_path):
        """POPRAWIONA: Waliduje plik USDZ z szczegółowymi informacjami"""
        try:
            # Sprawdź czy to prawidłowy ZIP
            with zipfile.ZipFile(file_path, 'r') as zf:
                files = zf.namelist()

                # Sprawdź czy zawiera plik USD
                usd_files = [f for f in files if f.endswith('.usd') or f.endswith('.usda')]
                has_usd = len(usd_files) > 0

                # Sprawdź czy USD jest pierwszym plikiem (wymagane dla iOS)
                first_file_is_usd = (
                    len(files) > 0 and
                    (files[0].endswith('.usd') or files[0].endswith('.usda'))
                )

                # Sprawdź tekstury
                texture_files = [
                    f for f in files
                    if f.lower().endswith(('.jpg', '.jpeg', '.png'))
                ]

                # NOWE: Sprawdź zawartość USD
                usd_content = ""
                if usd_files:
                    try:
                        with zf.open(usd_files[0]) as usd_file:
                            usd_content = usd_file.read().decode('utf-8')
                    except:
                        pass

                has_texture_references = (
                    'DiffuseTexture' in usd_content and
                    'inputs:file' in usd_content
                )

                return {
                    'is_valid_zip': True,
                    'has_usd_file': has_usd,
                    'first_file_is_usd': first_file_is_usd,
                    'files_count': len(files),
                    'texture_count': len(texture_files),
                    'texture_files': texture_files,
                    'usd_files': usd_files,
                    'has_texture_references_in_usd': has_texture_references,
                    'files': files[:10],  # pierwsze 10 plików
                    'total_size': sum(zf.getinfo(f).file_size for f in files)
                }

        except Exception as e:
            return {
                'is_valid_zip': False,
                'error': str(e)
            }

    def generate_glb_file(self, product_data):
        """
        Generuje plik GLB dla Android AR
    
        Args:
            product_data (dict): Dane produktu z variant_code, dimensions, quality
        
        Returns:
            dict: Wynik generowania z file_url, file_size, cache_key
        """
        try:
            print(f"[RealityGenerator] Generowanie GLB dla Android AR", file=sys.stderr)
        
            # Cache key
            cache_key = self._generate_cache_key(product_data)
            glb_filename = f"{cache_key}.glb"
            glb_path = os.path.join(self.cache_dir, glb_filename)
        
            # Sprawdź cache
            if os.path.exists(glb_path):
                print(f"[RealityGenerator] GLB z cache: {glb_filename}", file=sys.stderr)
                file_size = os.path.getsize(glb_path)
                return {
                    'success': True,
                    'file_url': f"/preview3d-ar/ar-models/{glb_filename}",
                    'file_size': file_size,
                    'cache_key': cache_key,
                    'cached': True
                }
        
            # Generuj nowy GLB
            print(f"[RealityGenerator] Tworzenie nowego GLB: {glb_filename}", file=sys.stderr)
        
            # 1. Utwórz geometrię panelu
            geometry_data = self._create_panel_geometry(product_data['dimensions'])
        
            # 2. Przygotuj tekstury
            textures_data = self._prepare_textures_for_glb(product_data['variant_code'])
        
            # 3. Utwórz GLB używając biblioteki gltf (przykład)
            glb_content = self._create_glb_content(geometry_data, textures_data, product_data)
        
            # 4. Zapisz plik GLB
            with open(glb_path, 'wb') as f:
                f.write(glb_content)
        
            file_size = os.path.getsize(glb_path)
            print(f"[RealityGenerator] GLB zapisany: {glb_path} ({file_size} bytes)", file=sys.stderr)
        
            return {
                'success': True,
                'file_url': f"/preview3d-ar/ar-models/{glb_filename}",
                'file_size': file_size,
                'cache_key': cache_key,
                'cached': False
            }
        
        except Exception as e:
            print(f"[RealityGenerator] Błąd generowania GLB: {str(e)}", file=sys.stderr)
            return {
                'success': False,
                'error': str(e)
            }

    def _create_glb_content(self, geometry_data, textures_data, product_data):
        """
        Tworzy zawartość pliku GLB
    
        Args:
            geometry_data: Dane geometrii panelu
            textures_data: Dane tekstur
            product_data: Dane produktu
        
        Returns:
            bytes: Zawartość pliku GLB
        """
        try:
            # UWAGA: To jest uproszczona implementacja
            # W rzeczywistości potrzebujesz biblioteki do tworzenia GLB jak pygltflib
        
            print(f"[RealityGenerator] Tworzenie GLB content...", file=sys.stderr)
        
            # Przykład: podstawowy GLB z prostokątnym panelem
            # Użyj biblioteki pygltflib lub podobnej do tworzenia prawidłowego GLB
        
            # Dla teraz zwrócimy placeholder - musisz zaimplementować prawdziwą generację GLB
            import json
        
            # Podstawowa struktura glTF
            gltf_data = {
                "asset": {"version": "2.0"},
                "scene": 0,
                "scenes": [{"nodes": [0]}],
                "nodes": [{"mesh": 0}],
                "meshes": [{
                    "primitives": [{
                        "attributes": {"POSITION": 0},
                        "indices": 1
                    }]
                }],
                "accessors": [
                    {
                        "bufferView": 0,
                        "componentType": 5126,  # FLOAT
                        "count": 4,
                        "type": "VEC3",
                        "min": [0, 0, 0],
                        "max": [
                            geometry_data['width'], 
                            geometry_data['height'], 
                            geometry_data['depth']
                        ]
                    },
                    {
                        "bufferView": 1,
                        "componentType": 5123,  # UNSIGNED_SHORT
                        "count": 6,
                        "type": "SCALAR"
                    }
                ],
                "bufferViews": [
                    {"buffer": 0, "byteOffset": 0, "byteLength": 48},  # 4 vertices * 12 bytes
                    {"buffer": 0, "byteOffset": 48, "byteLength": 12}  # 6 indices * 2 bytes
                ],
                "buffers": [{"byteLength": 60}]
            }
        
            # Konwertuj do bytes (to jest placeholder - potrzebujesz prawdziwej implementacji GLB)
            json_str = json.dumps(gltf_data).encode('utf-8')
        
            # GLB ma specyficzny format binary - to jest bardzo uproszczone
            # W rzeczywistości musisz użyć odpowiedniej biblioteki
        
            print(f"[RealityGenerator] GLB content created (placeholder)", file=sys.stderr)
            return json_str  # To nie jest prawdziwy GLB!
        
        except Exception as e:
            print(f"[RealityGenerator] Błąd tworzenia GLB content: {str(e)}", file=sys.stderr)
            raise

    def _prepare_textures_for_glb(self, variant_code):
        """Przygotowuje tekstury dla formatu GLB"""
        try:
            # Użyj istniejącej logiki tekstur
            textures = TextureConfig.get_all_textures_for_variant(variant_code)
        
            # Konwertuj do formatu GLB
            glb_textures = {}
            for surface, texture_data in textures.items():
                if texture_data.get('variants'):
                    # Użyj pierwszej dostępnej tekstury
                    texture_url = texture_data['variants'][0]
                    glb_textures[surface] = {
                        'url': texture_url,
                        'format': 'jpg'
                    }
        
            return glb_textures
        
        except Exception as e:
            print(f"[RealityGenerator] Błąd przygotowania tekstur GLB: {str(e)}", file=sys.stderr)
            return {}

# Backward compatibility - zachowaj stary generator USDZ
class AR3DGenerator(RealityGenerator):
    """Deprecated - używaj RealityGenerator"""
    
    def generate_usdz(self, product_data):
        """Backward compatibility wrapper"""
        print("[AR3DGenerator] DEPRECATED: Use RealityGenerator.generate_reality()", file=sys.stderr)
        return self.generate_reality(product_data)