"""
Generator SVG izometrycznego prostokąta z zaznaczonymi krawędziami.

Port logiki z modules/calculator/static/js/edges.js:generateRectPreviewSVG().
Używany jako fallback dla zamówień sklepowych (brak QuoteItemDetails).
"""


class EdgeSvgGenerator:
    """Generuje izometryczny SVG prostokąta z zaznaczonymi krawędziami."""

    # Kolory
    ACTIVE_COLOR = '#f59e0b'
    INACTIVE_COLOR = '#475569'
    FACE_FILL = 'rgba(148,163,184,0.05)'
    FACE_FILL_TOP = 'rgba(148,163,184,0.08)'
    LABEL_BG_ACTIVE = '#f59e0b'
    LABEL_BG_INACTIVE = '#2a2a3e'
    LABEL_TEXT_ACTIVE = '#fff'
    LABEL_TEXT_INACTIVE = '#94a3b8'

    # Wektory projekcji izometrycznej (te same co w edges.js)
    ISO_X = (0.95, 0.0)     # oś X kształtu → ekran
    ISO_Y = (-0.36, -0.75)  # oś Y kształtu → ekran
    ISO_Z = (0.04, 0.65)    # oś Z (grubość) → ekran

    # Definicje krawędzi prostokąta
    EDGE_DEFS = {
        # Górne (z=0)
        'A': {'start': (0, 0, 0), 'end': (1, 0, 0), 'label_pos': 0.5},
        'B': {'start': (0, 1, 0), 'end': (1, 1, 0), 'label_pos': 0.5},
        'C': {'start': (0, 0, 0), 'end': (0, 1, 0), 'label_pos': 0.5},
        'D': {'start': (1, 0, 0), 'end': (1, 1, 0), 'label_pos': 0.5},
        # Dolne (z=1)
        'E': {'start': (0, 0, 1), 'end': (1, 0, 1), 'label_pos': 0.5},
        'F': {'start': (0, 1, 1), 'end': (1, 1, 1), 'label_pos': 0.5},
        'G': {'start': (0, 0, 1), 'end': (0, 1, 1), 'label_pos': 0.5},
        'H': {'start': (1, 0, 1), 'end': (1, 1, 1), 'label_pos': 0.5},
        # Narożniki pionowe
        'N1': {'start': (0, 0, 0), 'end': (0, 0, 1), 'label_pos': 0.5},
        'N2': {'start': (1, 0, 0), 'end': (1, 0, 1), 'label_pos': 0.5},
        'N3': {'start': (1, 1, 0), 'end': (1, 1, 1), 'label_pos': 0.5},
        'N4': {'start': (0, 1, 0), 'end': (0, 1, 1), 'label_pos': 0.5},
    }

    def _project(self, x, y, z, length, width, thickness):
        """Rzutuje punkt 3D na 2D izometryczne."""
        px = x * length
        py = y * width
        pz = z * thickness

        screen_x = px * self.ISO_X[0] + py * self.ISO_Y[0] + pz * self.ISO_Z[0]
        screen_y = px * self.ISO_X[1] + py * self.ISO_Y[1] + pz * self.ISO_Z[1]

        return screen_x, screen_y

    def generate(self, length_cm, width_cm, thickness_cm, active_edges):
        """
        Generuje SVG izometrycznego prostokąta.

        Args:
            length_cm: długość w cm
            width_cm: szerokość w cm
            thickness_cm: grubość w cm
            active_edges: lista aktywnych krawędzi np. ['A', 'B', 'N1']

        Returns:
            str: SVG jako string
        """
        active_set = set(active_edges or [])

        # Normalizuj wymiary do rozmiaru SVG
        max_dim = max(length_cm, width_cm, thickness_cm * 5, 1)
        scale = 150 / max_dim
        L = length_cm * scale
        W = width_cm * scale
        T = max(thickness_cm * scale, 8)

        # 8 wierzchołków prostopadłościanu
        corners = {}
        for name, (xf, yf, zf) in [
            ('TFL', (0, 0, 0)), ('TFR', (1, 0, 0)),
            ('TBR', (1, 1, 0)), ('TBL', (0, 1, 0)),
            ('BFL', (0, 0, 1)), ('BFR', (1, 0, 1)),
            ('BBR', (1, 1, 1)), ('BBL', (0, 1, 1)),
        ]:
            corners[name] = self._project(xf, yf, zf, L, W, T)

        # Bounding box + padding
        all_x = [c[0] for c in corners.values()]
        all_y = [c[1] for c in corners.values()]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        padding = 30
        vb_w = max_x - min_x + padding * 2
        vb_h = max_y - min_y + padding * 2
        ox = -min_x + padding
        oy = -min_y + padding

        def p(name):
            x, y = corners[name]
            return x + ox, y + oy

        def fmt(x, y):
            return f'{x:.1f},{y:.1f}'

        parts = []
        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.0f} {vb_h:.0f}">')

        # Ściany
        faces = [
            ('back',  ['TBL', 'TBR', 'BBR', 'BBL'], self.FACE_FILL),
            ('left',  ['TBL', 'TFL', 'BFL', 'BBL'], self.FACE_FILL),
            ('top',   ['TFL', 'TFR', 'TBR', 'TBL'], self.FACE_FILL_TOP),
            ('front', ['TFL', 'TFR', 'BFR', 'BFL'], self.FACE_FILL),
            ('right', ['TFR', 'TBR', 'BBR', 'BFR'], self.FACE_FILL),
        ]

        for face_name, verts, fill in faces:
            points = ' '.join(fmt(*p(v)) for v in verts)
            parts.append(
                f'<polygon points="{points}" fill="{fill}" '
                f'stroke="{self.INACTIVE_COLOR}" stroke-width="1" opacity="0.6"/>'
            )

        # Krawędzie
        for edge_name, edge_def in self.EDGE_DEFS.items():
            sx, sy, sz = edge_def['start']
            ex, ey, ez = edge_def['end']

            x1, y1 = self._project(sx, sy, sz, L, W, T)
            x2, y2 = self._project(ex, ey, ez, L, W, T)
            x1 += ox; y1 += oy
            x2 += ox; y2 += oy

            is_active = edge_name in active_set
            color = self.ACTIVE_COLOR if is_active else self.INACTIVE_COLOR
            width = 3 if is_active else 1.5
            opacity = '' if is_active else ' opacity="0.6"'

            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"{opacity}/>'
            )

        # Labelki
        label_r = 11
        for edge_name, edge_def in self.EDGE_DEFS.items():
            sx, sy, sz = edge_def['start']
            ex, ey, ez = edge_def['end']
            t = edge_def['label_pos']

            mx = sx + (ex - sx) * t
            my = sy + (ey - sy) * t
            mz = sz + (ez - sz) * t

            lx, ly = self._project(mx, my, mz, L, W, T)
            lx += ox; ly += oy

            is_active = edge_name in active_set
            bg = self.LABEL_BG_ACTIVE if is_active else self.LABEL_BG_INACTIVE
            tc = self.LABEL_TEXT_ACTIVE if is_active else self.LABEL_TEXT_INACTIVE
            stroke = '' if is_active else f' stroke="{self.INACTIVE_COLOR}" stroke-width="1"'

            parts.append(
                f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{label_r}" fill="{bg}"{stroke}/>'
            )
            font_size = 8 if len(edge_name) > 1 else 9
            parts.append(
                f'<text x="{lx:.1f}" y="{ly + 3:.1f}" text-anchor="middle" '
                f'fill="{tc}" font-size="{font_size}" font-weight="bold" '
                f'font-family="Arial,sans-serif">{edge_name}</text>'
            )

        parts.append('</svg>')
        return '\n'.join(parts)
