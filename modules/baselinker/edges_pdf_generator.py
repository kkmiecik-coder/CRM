"""
Generator PDF z wizualizacją obróbki krawędzi dla BaseLinker.

Generuje wielostronicowy PDF (format 105x80mm) z wizualizacją krawędzi
i legendą dla każdego produktu. Dokument techniczny dla produkcji.
Używa WeasyPrint do renderowania HTML z SVG - ta sama metoda co w PDF oferty.
"""

import io
import re
import base64
from weasyprint import HTML, CSS


class EdgesPdfGenerator:
    """Generator PDF z wizualizacją obróbki krawędzi dla BaseLinker"""

    # Mapowanie typów na polskie nazwy
    TYPE_NAMES = {
        'round': 'Zaokrąglenie',
        'chamfer': 'Fazowanie'
    }

    def __init__(self, logger=None):
        self.logger = logger

    def generate_pdf(self, products_with_edges: list) -> bytes:
        """
        Generuje wielostronicowy PDF z wizualizacją krawędzi.

        Args:
            products_with_edges: Lista słowników z danymi produktów

        Returns:
            bytes: Zawartość PDF jako bajty
        """
        html_content = self._generate_html(products_with_edges)

        # Generuj PDF z HTML używając WeasyPrint
        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer.read()

    def generate_pdf_base64(self, products_with_edges: list) -> dict:
        """
        Generuje PDF i zwraca w formacie dla BaseLinker API.

        Returns:
            dict: {'title': 'filename.pdf', 'file': 'base64_content...'}
        """
        pdf_bytes = self.generate_pdf(products_with_edges)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # BaseLinker API wymaga formatu: "data:" + base64 (bez typu MIME)
        return {
            'title': 'krawedzie.pdf',
            'file': f'data:{pdf_base64}'
        }

    def _convert_css_to_svg_attributes(self, svg_html: str) -> str:
        """
        Konwertuje inline CSS styles na atrybuty SVG.
        WeasyPrint nie obsługuje właściwości SVG (fill, stroke, stroke-width) jako CSS,
        więc musimy je przekonwertować na natywne atrybuty SVG.

        Przykład: style="fill: rgb(184, 184, 184); stroke: none;"
        Na: fill="rgb(184, 184, 184)" stroke="none"
        """
        if not svg_html:
            return svg_html

        # Właściwości SVG które trzeba przekonwertować z CSS na atrybuty
        svg_properties = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin']

        def convert_style_to_attrs(match):
            """Konwertuje style="" na atrybuty SVG"""
            full_tag = match.group(0)
            tag_name = match.group(1)

            # Znajdź atrybut style
            style_match = re.search(r'style="([^"]*)"', full_tag)
            if not style_match:
                return full_tag

            style_content = style_match.group(1)

            # Wyciągnij właściwości SVG ze stylu
            new_attrs = []
            remaining_styles = []

            # Parsuj style CSS
            for style_part in style_content.split(';'):
                style_part = style_part.strip()
                if not style_part:
                    continue

                if ':' not in style_part:
                    continue

                prop, value = style_part.split(':', 1)
                prop = prop.strip()
                value = value.strip()

                if prop in svg_properties:
                    # Dodaj jako atrybut SVG
                    new_attrs.append(f'{prop}="{value}"')
                else:
                    # Zostaw w style
                    remaining_styles.append(f'{prop}: {value}')

            # Usuń stary style i dodaj nowe atrybuty
            new_tag = full_tag

            # Usuń atrybut style
            if remaining_styles:
                new_style = '; '.join(remaining_styles)
                new_tag = re.sub(r'style="[^"]*"', f'style="{new_style}"', new_tag)
            else:
                new_tag = re.sub(r'\s*style="[^"]*"', '', new_tag)

            # Dodaj nowe atrybuty przed zamknięciem tagu
            if new_attrs:
                attrs_str = ' ' + ' '.join(new_attrs)
                # Wstaw przed > lub />
                if new_tag.rstrip().endswith('/>'):
                    new_tag = re.sub(r'\s*/>', f'{attrs_str}/>', new_tag)
                else:
                    new_tag = re.sub(r'>$', f'{attrs_str}>', new_tag)

            return new_tag

        # Konwertuj wszystkie tagi SVG które mają style
        # Dopasuj tagi: <tagname ... style="..." ...>
        svg_html = re.sub(
            r'<(polygon|line|rect|circle|ellipse|path|polyline|g)([^>]*style="[^"]*"[^>]*)>',
            convert_style_to_attrs,
            svg_html
        )

        return svg_html

    def _ensure_dashed_lines(self, svg_html: str) -> str:
        """
        Upewnia się, że ukryte krawędzie (F, G, N3) mają linie przerywane.
        Dodaje stroke-dasharray do linii z klasą 'hidden' jeśli brakuje.
        """
        if not svg_html:
            return svg_html

        # Najpierw konwertuj CSS styles na atrybuty SVG
        svg_html = self._convert_css_to_svg_attributes(svg_html)

        # Dodaj style dla linii przerywanych jeśli ich brak
        # Szukamy linii z klasą zawierającą 'hidden' i dodajemy stroke-dasharray
        if 'stroke-dasharray' not in svg_html:
            # Dodaj CSS dla linii ukrytych wewnątrz SVG
            svg_style = """
            <style>
                .edge-hidden, .hidden, line[class*="hidden"] {
                    stroke-dasharray: 5,3 !important;
                }
            </style>
            """
            # Wstaw style zaraz po otwarciu tagu <svg>
            svg_html = re.sub(
                r'(<svg[^>]*>)',
                r'\1' + svg_style,
                svg_html,
                count=1
            )

        return svg_html

    def _generate_html(self, products_with_edges: list) -> str:
        """Generuje HTML z wizualizacją krawędzi dla wszystkich produktów"""

        pages_html = []
        for product in products_with_edges:
            page_html = self._generate_product_page(product)
            pages_html.append(page_html)

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{
            size: 105mm 80mm;
            margin: 4mm;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: Arial, Helvetica, sans-serif;
            font-size: 12px;
            line-height: 1.3;
        }}

        .page {{
            page-break-after: always;
            height: 72mm;
            padding: 2mm;
        }}

        .page:last-child {{
            page-break-after: avoid;
        }}

        .header {{
            border-bottom: 1px solid #ccc;
            padding-bottom: 2mm;
            margin-bottom: 2mm;
        }}

        .title {{
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 1mm;
        }}

        .dimensions {{
            font-size: 12px;
            color: #555;
        }}

        .content {{
            display: flex;
            gap: 3mm;
        }}

        .svg-container {{
            flex-shrink: 0;
            width: 45mm;
            height: 45mm;
        }}

        .svg-container svg {{
            width: 45mm;
            height: 45mm;
        }}

        .legend {{
            flex-grow: 1;
        }}

        .legend-item {{
            margin-bottom: 1.5mm;
            font-size: 12px;
        }}

        .legend-item strong {{
            color: #333;
        }}

        .edges-list {{
            margin-top: 2mm;
        }}

        .edges-list-title {{
            font-weight: bold;
            margin-bottom: 1mm;
            font-size: 12px;
        }}

        .edge-row {{
            font-size: 12px;
            margin-bottom: 0.5mm;
        }}
    </style>
</head>
<body>
    {''.join(pages_html)}
</body>
</html>
"""
        return html

    def _generate_product_page(self, product: dict) -> str:
        """Generuje HTML dla pojedynczego produktu"""

        product_index = product.get('product_index', '?')
        product_name = product.get('product_name', 'Nieznany')

        # Skróć nazwę jeśli za długa
        if len(product_name) > 35:
            product_name = product_name[:32] + '...'

        dims = product.get('dimensions', {})
        length = dims.get('length', 0)
        width = dims.get('width', 0)
        thickness = dims.get('thickness', 0)

        edge_type = self.TYPE_NAMES.get(product.get('edges_type', ''), product.get('edges_type', ''))
        r_value = product.get('edges_r_value', 0)

        # SVG z bazy danych - z dodaniem linii przerywanych
        svg_html = product.get('edges_svg', '')
        if svg_html:
            svg_html = self._ensure_dashed_lines(svg_html)
        else:
            svg_html = '<div style="width:45mm;height:45mm;background:#f5f5f5;display:flex;align-items:center;justify-content:center;font-size:8px;color:#999;">Brak wizualizacji</div>'

        # Lista krawędzi
        edges_config = product.get('edges_config', [])
        edges_html = ''
        for edge in edges_config:
            letter = edge.get('letter', '?')
            length_cm = edge.get('length_cm', 0)
            edges_html += f'<div class="edge-row">• {letter}: {length_cm} cm</div>'

        return f"""
        <div class="page">
            <div class="header">
                <div class="title">#{product_index}: {product_name}</div>
                <div class="dimensions">{length} × {width} × {thickness} cm</div>
            </div>
            <div class="content">
                <div class="svg-container">
                    {svg_html}
                </div>
                <div class="legend">
                    <div class="legend-item"><strong>Typ:</strong> {edge_type}</div>
                    <div class="legend-item"><strong>Promień:</strong> R{r_value}</div>

                    <div class="edges-list">
                        <div class="edges-list-title">Krawędzie:</div>
                        {edges_html}
                    </div>
                </div>
            </div>
        </div>
"""
