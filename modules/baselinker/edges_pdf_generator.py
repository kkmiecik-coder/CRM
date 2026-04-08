"""
Generator PDF specyfikacji produktów dla BaseLinker.

Generuje wielostronicowy PDF (format A4) z wizualizacją kształtów i krawędzi.
Siatka 2x3 — do 6 produktów na stronę.
Używa WeasyPrint do renderowania HTML z obrazkami PNG (konwertowanymi z SVG przez CairoSVG).
"""

import io
import re
import base64
from weasyprint import HTML
import cairosvg


class EdgesPdfGenerator:
    """Generator PDF specyfikacji produktów dla BaseLinker"""

    # Mapowanie typów krawędzi
    EDGE_TYPE_NAMES = {
        'round': 'Zaokrąglenie',
        'chamfer': 'Fazowanie'
    }

    # Mapowanie nazw kształtów
    SHAPE_NAMES = {
        'rectangular': 'Prostokąt',
        'circle': 'Koło',
        'round': 'Okrągły',
        'triangle_right': 'Trójkąt prostokątny',
        'triangle_equilateral': 'Trójkąt równoboczny',
        'triangle_isosceles': 'Trójkąt równoramienny',
        'triangle_custom': 'Trójkąt dowolny',
        'trapezoid_symmetric': 'Trapez symetryczny',
        'trapezoid_asymmetric': 'Trapez niesymetryczny',
        'trapezoid_custom': 'Trapez dowolny',
        'parallelogram': 'Równoległobok',
        'polygon': 'Wielokąt'
    }

    def __init__(self, logger=None):
        self.logger = logger

    def generate_pdf(self, products: list, quote_number: str = '') -> bytes:
        """
        Generuje PDF specyfikacji produktów.

        Args:
            products: Lista słowników z danymi produktów
            quote_number: Numer wyceny

        Returns:
            bytes: Zawartość PDF jako bajty
        """
        html_content = self._generate_html(products, quote_number)

        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer.read()

    def generate_pdf_base64(self, products: list, quote_number: str = '') -> dict:
        """
        Generuje PDF i zwraca w formacie dla BaseLinker API.

        Returns:
            dict: {'title': 'filename.pdf', 'file': 'data:base64_content...'}
        """
        pdf_bytes = self.generate_pdf(products, quote_number)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        return {
            'title': 'specyfikacja.pdf',
            'file': f'data:{pdf_base64}'
        }

    # ============================================
    # KONWERSJA SVG
    # ============================================

    def _convert_css_to_svg_attributes(self, svg_html: str) -> str:
        """
        Konwertuje inline CSS styles na atrybuty SVG.
        WeasyPrint nie obsługuje właściwości SVG jako CSS.
        """
        if not svg_html:
            return svg_html

        svg_properties = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray',
                         'stroke-linecap', 'stroke-linejoin']

        def convert_style_to_attrs(match):
            full_tag = match.group(0)
            style_match = re.search(r'style="([^"]*)"', full_tag)
            if not style_match:
                return full_tag

            style_content = style_match.group(1)
            new_attrs = []
            remaining_styles = []

            for style_part in style_content.split(';'):
                style_part = style_part.strip()
                if not style_part or ':' not in style_part:
                    continue

                prop, value = style_part.split(':', 1)
                prop = prop.strip()
                value = value.strip()

                if prop in svg_properties:
                    new_attrs.append(f'{prop}="{value}"')
                else:
                    remaining_styles.append(f'{prop}: {value}')

            new_tag = full_tag
            if remaining_styles:
                new_style = '; '.join(remaining_styles)
                new_tag = re.sub(r'style="[^"]*"', f'style="{new_style}"', new_tag)
            else:
                new_tag = re.sub(r'\s*style="[^"]*"', '', new_tag)

            if new_attrs:
                for attr in new_attrs:
                    attr_name = attr.split('=')[0]
                    new_tag = re.sub(rf'\s+{re.escape(attr_name)}="[^"]*"', '', new_tag)
                attrs_str = ' ' + ' '.join(new_attrs)
                if new_tag.rstrip().endswith('/>'):
                    new_tag = re.sub(r'\s*/>', f'{attrs_str}/>', new_tag)
                else:
                    new_tag = re.sub(r'>$', f'{attrs_str}>', new_tag)

            return new_tag

        svg_html = re.sub(
            r'<(polygon|line|rect|circle|ellipse|path|polyline|g|text)\b([^>]*?)>',
            convert_style_to_attrs,
            svg_html
        )

        return svg_html

    def _fix_svg_for_conversion(self, svg_html: str, output_width=300) -> str:
        """Naprawia SVG przed konwersją na PNG"""
        if not svg_html:
            return svg_html

        svg_html = re.sub(r'\s*style=""', '', svg_html)

        # Usuń istniejące width/height TYLKO z tagu <svg>, nie z elementów wewnętrznych
        svg_html = re.sub(r'(<svg\s[^>]*?)\s+width="[^"]*"', r'\1', svg_html)
        svg_html = re.sub(r'(<svg\s[^>]*?)\s+height="[^"]*"', r'\1', svg_html)
        svg_html = re.sub(
            r'<svg\s+',
            f'<svg width="{output_width}" height="{output_width}" ',
            svg_html,
            count=1
        )

        if 'xmlns=' not in svg_html:
            svg_html = re.sub(
                r'<svg\s+',
                '<svg xmlns="http://www.w3.org/2000/svg" ',
                svg_html,
                count=1
            )

        return svg_html

    def _sanitize_svg_text(self, svg_html: str) -> str:
        """Zamienia znaki specjalne, fonty i kolory nieobsługiwane przez CairoSVG"""
        if not svg_html:
            return svg_html

        # Usuń znak ∅ (U+2300) — CairoSVG nie renderuje tego znaku
        svg_html = svg_html.replace('\u2300', '')

        # Zamień font Poppins na Arial (CairoSVG nie ma Poppins)
        svg_html = svg_html.replace('Poppins,sans-serif', 'Arial,sans-serif')
        svg_html = svg_html.replace('Poppins', 'Arial')

        # Zamień rgba() na odpowiedniki SVG (CairoSVG nie obsługuje rgba w atrybutach)
        # Zwiększ opacity z 0.15 do 0.3 żeby kształt był widoczny na druku
        def rgba_to_svg(match):
            r, g, b = match.group(1), match.group(2), match.group(3)
            a = float(match.group(4))
            if a < 0.25:
                a = 0.3
            return f'rgb({r},{g},{b})" fill-opacity="{a}'
        svg_html = re.sub(
            r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)',
            rgba_to_svg,
            svg_html
        )

        return svg_html

    def _generate_simple_shape_svg(self, shape: str, length: float, width: float) -> str:
        """Generuje prosty SVG kształtu gdy brak shape_svg z kalkulatora (stare wyceny)"""
        pad = 5
        sw = 1.5
        fill = 'rgb(230,126,34)'
        fill_op = '0.3'
        stroke = '#e67e22'

        if shape == 'circle' or shape == 'round':
            r = length / 2
            total = length + pad * 2
            return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}">'
                    f'<circle cx="{r + pad}" cy="{r + pad}" r="{r}" '
                    f'fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-width="{sw}"/>'
                    f'</svg>')

        # Prostokąt
        total_w = length + pad * 2
        total_h = width + pad * 2
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}">'
                f'<rect x="{pad}" y="{pad}" width="{length}" height="{width}" '
                f'fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-width="{sw}" rx="1"/>'
                f'</svg>')

    def _svg_to_png_base64(self, svg_html: str, output_width=300) -> str:
        """Konwertuje SVG na PNG base64 data URI"""
        if not svg_html:
            return None

        try:
            svg_html = self._sanitize_svg_text(svg_html)
            svg_html = self._convert_css_to_svg_attributes(svg_html)
            svg_html = self._fix_svg_for_conversion(svg_html, output_width)

            png_bytes = cairosvg.svg2png(
                bytestring=svg_html.encode('utf-8'),
                output_width=output_width,
                output_height=output_width
            )

            png_base64 = base64.b64encode(png_bytes).decode('utf-8')
            return f'data:image/png;base64,{png_base64}'

        except Exception as e:
            if self.logger:
                self.logger.error(f'Błąd konwersji SVG na PNG: {e}')
            return None

    def _ensure_dashed_lines(self, svg_html: str) -> str:
        """Dodaje stroke-dasharray do linii ukrytych"""
        if not svg_html:
            return svg_html

        svg_html = self._convert_css_to_svg_attributes(svg_html)
        svg_html = self._fix_svg_for_conversion(svg_html)

        def add_dasharray(match):
            tag = match.group(0)
            if 'stroke-dasharray' not in tag:
                tag = re.sub(r'>$', ' stroke-dasharray="5,3">', tag)
            return tag

        svg_html = re.sub(
            r'<line[^>]*class="[^"]*hidden[^"]*"[^>]*>',
            add_dasharray,
            svg_html
        )

        return svg_html

    # ============================================
    # GENEROWANIE HTML
    # ============================================

    def _generate_html(self, products: list, quote_number: str = '') -> str:
        """Generuje HTML z siatką 2x3 produktów na stronę"""

        # Podziel produkty na strony po 6
        pages = []
        for i in range(0, len(products), 6):
            pages.append(products[i:i+6])

        pages_html = []
        for page_products in pages:
            cells_html = []
            for product in page_products:
                cells_html.append(self._generate_product_cell(product))

            # Siatka 2xN jako tabela (kompatybilna ze starszym WeasyPrint)
            # Tylko tyle wierszy ile potrzeba (bez pustych)
            rows_html = ''
            for row_idx in range(0, len(cells_html), 2):
                c1 = cells_html[row_idx]
                c2 = cells_html[row_idx + 1] if row_idx + 1 < len(cells_html) else '<td></td>'
                if row_idx + 1 < len(cells_html):
                    rows_html += f'<tr><td>{c1}</td><td>{c2}</td></tr>'
                else:
                    rows_html += f'<tr><td>{c1}</td><td></td></tr>'

            pages_html.append(f"""
            <div class="page">
                <div class="page-title">Specyfikacja wyceny{' ' + quote_number if quote_number else ''}</div>
                <table class="grid-table">
                    {rows_html}
                </table>
            </div>
            """)

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{
            size: A4;
            margin: 8mm;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: Arial, Helvetica, sans-serif;
            font-size: 9px;
            line-height: 1.3;
        }}

        .page {{
            page-break-after: always;
        }}

        .page:last-child {{
            page-break-after: avoid;
        }}

        .page-title {{
            font-size: 14px;
            font-weight: bold;
            text-align: center;
            padding-bottom: 4mm;
            margin-bottom: 4mm;
            border-bottom: 2px solid #ED6B24;
            color: #333;
        }}

        .grid-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 4mm 4mm;
        }}

        .grid-table td {{
            width: 50%;
            vertical-align: top;
            padding: 0;
        }}

        .cell {{
            border: 1px solid #ddd;
            border-radius: 3mm;
            padding: 3mm;
            overflow: hidden;
            height: 100%;
        }}

        .cell.empty {{
            border-color: transparent;
        }}

        .cell-header {{
            padding-bottom: 2mm;
            margin-bottom: 1mm;
            border-bottom: 1px solid #eee;
        }}

        .cell-header-table {{
            width: 100%;
            border-collapse: collapse;
        }}

        .cell-header-table td {{
            padding: 0;
            vertical-align: top;
        }}

        .cell-header-table .cell-badge-col {{
            width: 1px;
            white-space: nowrap;
            vertical-align: middle;
        }}

        .cell-position {{
            font-size: 11px;
            font-weight: bold;
            color: #ED6B24;
        }}

        .cell-dims {{
            font-size: 8px;
            color: #666;
            margin-top: 1mm;
        }}

        .cell-shape-badge {{
            background: #e67e22;
            color: #fff;
            padding: 1px 5px;
            border-radius: 3px;
            font-size: 7px;
            font-weight: bold;
        }}

        .cell-body {{
            overflow: hidden;
        }}

        .cell-preview-labels {{
            overflow: hidden;
            margin-bottom: 1mm;
        }}

        .cell-preview-label {{
            width: 48%;
            float: left;
            font-size: 6px;
            font-weight: bold;
            color: #aaa;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            text-align: center;
        }}

        .cell-preview-label + .cell-preview-label {{
            margin-left: 4%;
        }}

        .cell-previews {{
            overflow: hidden;
            text-align: center;
        }}

        .cell-preview-box {{
            width: 48%;
            float: left;
            text-align: center;
            overflow: hidden;
        }}

        .cell-preview-box + .cell-preview-box {{
            margin-left: 4%;
        }}

        .cell-preview-box img {{
            max-width: 100%;
            max-height: 35mm;
            object-fit: contain;
        }}

        /* Gdy tylko jeden podgląd — większy */
        .cell-preview-box.single {{
            width: 100%;
        }}

        .cell-preview-box.single img {{
            max-height: 45mm;
        }}

        .cell-info {{
            font-size: 8px;
            color: #555;
        }}

        .cell-info div {{
            margin-bottom: 0.5mm;
        }}

        .cell-info strong {{
            color: #333;
        }}

        .cell-note {{
            font-size: 7px;
            color: #888;
            font-style: italic;
            margin-top: 1mm;
        }}
    </style>
</head>
<body>
    {''.join(pages_html)}
</body>
</html>
"""
        return html

    def _generate_product_cell(self, product: dict) -> str:
        """Generuje HTML komórki dla jednego produktu"""

        product_index = product.get('product_index', '?')
        product_name = product.get('product_name', 'Nieznany')
        quantity = product.get('quantity', 1)

        dims = product.get('dimensions', {})
        length = dims.get('length', 0)
        width = dims.get('width', 0)
        thickness = dims.get('thickness', 0)

        shape = product.get('shape', 'rectangular')
        shape_name = self.SHAPE_NAMES.get(shape, shape)
        shape_badge = f'<span class="cell-shape-badge">{shape_name}</span>'

        # Podgląd kształtu 2D
        shape_svg = product.get('shape_svg', '')
        shape_img_html = ''
        has_shape = False

        # Jeśli brak shape_svg — wygeneruj prosty SVG dla prostokąta/koła
        if not shape_svg and length > 0 and width > 0:
            shape_svg = self._generate_simple_shape_svg(shape, length, width)

        if shape_svg:
            png_uri = self._svg_to_png_base64(shape_svg, 250)
            if png_uri:
                has_shape = True
                shape_img_html = f'<div class="cell-preview-box"><img src="{png_uri}" alt="Kształt" /></div>'

        # Podgląd izometryczny krawędzi 3D
        edges_svg = product.get('edges_svg', '')
        edges_img_html = ''
        has_edges_img = False
        if edges_svg:
            svg_fixed = self._ensure_dashed_lines(edges_svg)
            png_uri = self._svg_to_png_base64(svg_fixed, 250)
            if png_uri:
                has_edges_img = True
                edges_img_html = f'<div class="cell-preview-box"><img src="{png_uri}" alt="Krawędzie" /></div>'

        # Jeśli tylko jeden podgląd — dodaj klasę single (większy obrazek)
        only_one = has_shape != has_edges_img
        if only_one:
            if has_shape:
                shape_img_html = shape_img_html.replace('cell-preview-box', 'cell-preview-box single')
            if has_edges_img:
                edges_img_html = edges_img_html.replace('cell-preview-box', 'cell-preview-box single')

        # Nagłówki podglądów (oddzielone od obrazków)
        labels_html = ''
        previews_html = ''
        if has_shape or has_edges_img:
            label_items = ''
            if has_shape:
                label_items += '<div class="cell-preview-label">Kształt</div>'
            if has_edges_img:
                label_items += '<div class="cell-preview-label">Izometria</div>'
            labels_html = f'<div class="cell-preview-labels">{label_items}</div>'
            previews_html = f'<div class="cell-previews">{shape_img_html}{edges_img_html}</div>'

        # Info o krawędziach
        edges_info_html = ''
        edges_config = product.get('edges_config')
        if edges_config and len(edges_config) > 0:
            edge_type = self.EDGE_TYPE_NAMES.get(
                product.get('edges_type', ''), product.get('edges_type', ''))
            r_value = product.get('edges_r_value', '-')
            angle_value = product.get('edges_angle_value')
            letters = ', '.join(sorted([e.get('letter', '?') for e in edges_config]))

            angle_html = ''
            if product.get('edges_type') == 'chamfer' and angle_value:
                angle_html = f' ({angle_value}°)'

            edges_info_html = f"""
            <div class="cell-info">
                <div><strong>Obróbka:</strong> {edge_type} R{r_value}{angle_html}</div>
                <div><strong>Krawędzie:</strong> {letters}</div>
                <div class="cell-note">Krawędzie zaznaczone kolorem pomarańczowym zostaną poddane obróbce.</div>
            </div>"""

        # Info o wykończeniu
        finishing_html = ''
        finishing_type = product.get('finishing_type')
        if finishing_type and finishing_type != 'Brak':
            finishing_variant = product.get('finishing_variant', '')
            finishing_text = finishing_type
            if finishing_variant:
                finishing_text += f' | {finishing_variant}'
            finishing_html = f'<div><strong>Wykończenie:</strong> {finishing_text}</div>'

        # Złóż info
        info_html = ''
        if finishing_html or edges_info_html:
            info_parts = finishing_html + edges_info_html
            if finishing_html and not edges_info_html:
                info_html = f'<div class="cell-info">{finishing_html}</div>'
            else:
                info_html = edges_info_html
                if finishing_html:
                    info_html = f'<div class="cell-info">{finishing_html}</div>{edges_info_html}'

        return f"""
        <div class="cell">
            <div class="cell-header">
                <table class="cell-header-table"><tr>
                    <td>
                        <div class="cell-position">#{product_index}: {product_name}</div>
                        <div class="cell-dims">{length} x {width} x {thickness} cm | {quantity} szt.</div>
                    </td>
                    <td class="cell-badge-col">{shape_badge}</td>
                </tr></table>
            </div>
            <div class="cell-body">
                {labels_html}
                {previews_html}
                {info_html}
            </div>
        </div>"""
