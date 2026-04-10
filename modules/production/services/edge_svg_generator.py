"""
Generator SVG izometrycznego prostokąta z zaznaczonymi krawędziami.

Dokładny port logiki z modules/calculator/static/js/edges.js:generateRectPreviewSVG().
Używany jako fallback dla zamówień sklepowych (brak QuoteItemDetails).
"""
import math


class EdgeSvgGenerator:
    """Generuje izometryczny SVG prostokąta z zaznaczonymi krawędziami."""

    # Kolory — te same co w edges.js CSS
    ACTIVE_STROKE = '#f59e0b'
    INACTIVE_STROKE = '#666'
    ACTIVE_WIDTH = 2.5
    INACTIVE_WIDTH = 2
    HIDDEN_DASH = '5,3'

    FACE_BACK = 'rgba(148,163,184,0.06)'
    FACE_LEFT = 'rgba(148,163,184,0.04)'
    FACE_TOP = 'rgba(148,163,184,0.1)'
    FACE_FRONT = 'rgba(148,163,184,0.08)'
    FACE_RIGHT = 'rgba(148,163,184,0.05)'
    FACE_STROKE = '#555'

    LABEL_R = 10
    LABEL_OFFSET = 14  # offset labelki od krawędzi
    LABEL_BG_ACTIVE = '#f59e0b'
    LABEL_BG_INACTIVE = '#333'
    LABEL_STROKE_INACTIVE = '#666'
    LABEL_TEXT_ACTIVE = '#fff'
    LABEL_TEXT_INACTIVE = '#999'

    # Viewbox — stały jak w kalkulatorze
    VB_W = 320
    VB_H = 220
    MARGIN = 20

    def generate(self, length_cm, width_cm, thickness_cm, active_edges):
        """
        Generuje SVG izometrycznego prostokąta — port z edges.js.

        Args:
            length_cm: długość w cm
            width_cm: szerokość w cm
            thickness_cm: grubość w cm
            active_edges: lista aktywnych krawędzi np. ['A', 'B', 'N1']

        Returns:
            str: SVG jako string
        """
        active_set = set(active_edges or [])

        # Projekcja izometryczna 30° — identyczna jak w kalkulatorze
        iso_angle = math.pi / 6
        cos_a = math.cos(iso_angle)
        sin_a = math.sin(iso_angle)

        max_dim = max(length_cm, width_cm)
        effective_thickness = max(thickness_cm, max_dim * 0.15)

        work_w = self.VB_W - 2 * self.MARGIN
        work_h = self.VB_H - 2 * self.MARGIN

        projected_w = (length_cm + width_cm) * cos_a
        projected_h = (length_cm + width_cm) * sin_a + effective_thickness

        scale = min(work_w / projected_w, work_h / projected_h) * 0.85

        L = length_cm * scale
        W = width_cm * scale
        T = effective_thickness * scale

        vecX = (cos_a, sin_a)    # prawo-dół
        vecY = (-cos_a, sin_a)   # lewo-dół
        # vecZ = (0, -1) — grubość idzie w górę

        total_proj_w = L * vecX[0] + W * abs(vecY[0])
        total_proj_h = L * vecX[1] + W * vecY[1] + T

        start_x = (self.VB_W - total_proj_w) / 2 + W * abs(vecY[0])
        start_y = (self.VB_H - total_proj_h) / 2 + T

        # 8 wierzchołków — nazewnictwo z kalkulatora:
        # TLD = Top-Left-Down (góra, lewy, dół = na płaszczyźnie dolnej)
        # TLG = Top-Left-Gora (góra, lewy, góra = na płaszczyźnie górnej)
        pTLD = (start_x, start_y)
        pTPD = (pTLD[0] + L * vecX[0], pTLD[1] + L * vecX[1])
        pPPD = (pTPD[0] + W * vecY[0], pTPD[1] + W * vecY[1])
        pPLD = (pTLD[0] + W * vecY[0], pTLD[1] + W * vecY[1])
        pTLG = (pTLD[0], pTLD[1] - T)
        pTPG = (pTPD[0], pTPD[1] - T)
        pPPG = (pPPD[0], pPPD[1] - T)
        pPLG = (pPLD[0], pPLD[1] - T)

        def f(pt):
            return f'{pt[0]:.1f},{pt[1]:.1f}'

        def mid(a, b):
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

        def ec(edge):
            return self.ACTIVE_STROKE if edge in active_set else self.INACTIVE_STROKE

        def ew(edge):
            return self.ACTIVE_WIDTH if edge in active_set else self.INACTIVE_WIDTH

        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.VB_W} {self.VB_H}">']

        # Ściany (tło) — kolejność rysowania z kalkulatora
        parts.append(f'<polygon points="{f(pTLD)} {f(pTPD)} {f(pTPG)} {f(pTLG)}" fill="{self.FACE_BACK}" stroke="{self.FACE_STROKE}" stroke-width="1"/>')
        parts.append(f'<polygon points="{f(pTLD)} {f(pPLD)} {f(pPLG)} {f(pTLG)}" fill="{self.FACE_LEFT}" stroke="{self.FACE_STROKE}" stroke-width="1"/>')
        parts.append(f'<polygon points="{f(pTLG)} {f(pTPG)} {f(pPPG)} {f(pPLG)}" fill="{self.FACE_TOP}" stroke="{self.FACE_STROKE}" stroke-width="1"/>')
        parts.append(f'<polygon points="{f(pPLD)} {f(pPPD)} {f(pPPG)} {f(pPLG)}" fill="{self.FACE_FRONT}" stroke="{self.FACE_STROKE}" stroke-width="1"/>')
        parts.append(f'<polygon points="{f(pTPD)} {f(pPPD)} {f(pPPG)} {f(pTPG)}" fill="{self.FACE_RIGHT}" stroke="{self.FACE_STROKE}" stroke-width="1"/>')

        # Krawędzie — ukryte (hidden) mają dashed, reszta solid
        # F i G są z tyłu (hidden), N3 pionowa z tyłu (hidden)
        def line(name, p1, p2, hidden=False):
            color = ec(name)
            width = ew(name)
            dash = f' stroke-dasharray="{self.HIDDEN_DASH}"' if hidden and name not in active_set else ''
            return f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="{color}" stroke-width="{width}"{dash} fill="none"/>'

        # Ukryte krawędzie (z tyłu)
        parts.append(line('F', pTLD, pTPD, hidden=True))
        parts.append(line('G', pTLD, pPLD, hidden=True))
        parts.append(line('N3', pTLG, pTLD, hidden=True))

        # Widoczne krawędzie
        parts.append(line('A', pPLG, pPPG))
        parts.append(line('B', pTLG, pTPG))
        parts.append(line('C', pTLG, pPLG))
        parts.append(line('D', pTPG, pPPG))
        parts.append(line('E', pPLD, pPPD))
        parts.append(line('H', pTPD, pPPD))
        parts.append(line('N1', pPLG, pPLD))
        parts.append(line('N2', pPPG, pPPD))
        parts.append(line('N4', pTPG, pTPD))

        # Labelki — pozycje z kalkulatora (offsetowane od krawędzi)
        R = self.LABEL_R
        OFF = self.LABEL_OFFSET

        labels = {
            'A':  (mid(pPLG, pPPG)[0],       mid(pPLG, pPPG)[1] - OFF),
            'B':  (mid(pTLG, pTPG)[0],        mid(pTLG, pTPG)[1] - OFF),
            'C':  (mid(pTLG, pPLG)[0] - OFF,  mid(pTLG, pPLG)[1]),
            'D':  (mid(pTPG, pPPG)[0] + OFF,  mid(pTPG, pPPG)[1]),
            'E':  (mid(pPLD, pPPD)[0],        mid(pPLD, pPPD)[1] + OFF),
            'H':  (mid(pTPD, pPPD)[0] + OFF,  mid(pTPD, pPPD)[1]),
            'N1': (pPLG[0] - OFF,             mid(pPLG, pPLD)[1]),
            'N2': (pPPG[0] + OFF,             mid(pPPG, pPPD)[1]),
            'N4': (pTPG[0] + OFF,             mid(pTPG, pTPD)[1]),
        }
        # F, G, N3 — ukryte z tyłu, labelki tylko jeśli aktywne
        if 'F' in active_set:
            labels['F'] = (mid(pTLD, pTPD)[0], mid(pTLD, pTPD)[1] - OFF)
        if 'G' in active_set:
            labels['G'] = (mid(pTLD, pPLD)[0] - OFF, mid(pTLD, pPLD)[1])
        if 'N3' in active_set:
            labels['N3'] = (pTLG[0] - OFF, mid(pTLG, pTLD)[1])

        parts.append('<g class="edges-labels">')
        for name, (lx, ly) in labels.items():
            is_active = name in active_set
            bg = self.LABEL_BG_ACTIVE if is_active else self.LABEL_BG_INACTIVE
            tc = self.LABEL_TEXT_ACTIVE if is_active else self.LABEL_TEXT_INACTIVE
            stroke_attr = '' if is_active else f' stroke="{self.LABEL_STROKE_INACTIVE}" stroke-width="1"'
            font_size = 8 if len(name) > 1 else 10
            parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{R}" fill="{bg}"{stroke_attr}/>')
            parts.append(f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle" fill="{tc}" font-size="{font_size}" font-weight="bold" font-family="Arial,sans-serif">{name}</text>')
        parts.append('</g>')

        parts.append('</svg>')
        return '\n'.join(parts)
