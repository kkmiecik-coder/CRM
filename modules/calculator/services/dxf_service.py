"""
DXF Generation Service
Generuje pliki DXF z danych wyceny dla maszyn CNC.
"""

import json
import logging
import math
from io import BytesIO, StringIO

import ezdxf
from ezdxf.enums import TextEntityAlignment

from modules.calculator.services import shape_geometry

logger = logging.getLogger(__name__)

# Półosie (cm) różniące się o mniej niż to uznajemy za równe — wtedy wycięcie jest okręgiem
TOLERANCJA_KOLA_CM = 1e-6


# Mapowanie kodów wariantów na czytelne nazwy
VARIANT_LABELS = {
    'dab-lity-ab': 'Dąb Lity A/B',
    'dab-lity-bb': 'Dąb Lity B/B',
    'dab-micro-ab': 'Dąb Mikrowczep A/B',
    'dab-micro-bb': 'Dąb Mikrowczep B/B',
    'jes-lity-ab': 'Jesion Lity A/B',
    'jes-micro-ab': 'Jesion Mikrowczep A/B',
    'buk-lity-ab': 'Buk Lity A/B',
    'buk-micro-ab': 'Buk Mikrowczep A/B',
}

EDGE_TYPE_LABELS = {
    'sharp': 'Ostra',
    'chamfer': 'Fazowanie',
    'round': 'Frezowanie',
}


def _doc_to_bytes(doc):
    """Zapisuje dokument DXF do BytesIO (ASCII format)."""
    text_buf = StringIO()
    doc.write(text_buf, fmt='asc')
    result = BytesIO(text_buf.getvalue().encode('utf-8'))
    result.seek(0)
    return result


def _parse_shape_data(shape_data_raw):
    """Parsuje shape_data z różnych formatów (string JSON lub dict). Zwraca dict albo None."""
    if not shape_data_raw:
        return None
    if isinstance(shape_data_raw, dict):
        return shape_data_raw
    try:
        dane = json.loads(shape_data_raw)
    except (ValueError, TypeError):
        return None
    # JSON-em bywa też lista, tekst albo liczba — tylko obiekt jest shape_data
    return dane if isinstance(dane, dict) else None


def _liczba(wartosc, domyslna=0.0):
    """float albo wartość domyślna dla None, tekstu, NaN i nieskończoności."""
    try:
        x = float(wartosc)
    except (TypeError, ValueError):
        return domyslna
    return x if math.isfinite(x) else domyslna


def _contour_xyb(ring_cm, corners, offset_x, offset_y):
    """Punkty LWPOLYLINE (x, y, bulge) w mm. Łuk narożnika = bulge na punkcie styczności
    (maszyna dostaje prawdziwy łuk), ścięcie = dwa zwykłe punkty."""
    punkty = []
    for s in shape_geometry.contour_segments(ring_cm, corners):
        bulge = shape_geometry.arc_bulge(s) if s['type'] == 'arc' else 0.0
        punkty.append((s['from'][0] * 10 + offset_x, s['from'][1] * 10 + offset_y, bulge))
    return punkty


def _geometria(shape_type, ring_cm, shape_data, details):
    """(narożniki obrysu, wycięcia) gotowe do rysowania. Gdy shape_data jest zepsute,
    zwraca zwykły obrys bez wycięć (i ostrzeżenie w logu) zamiast przerywać eksport DXF."""
    try:
        return shape_geometry.resolve_corners(
            shape_type, ring_cm, shape_data, getattr(details, 'edges_config', None))
    except Exception:
        logger.warning('DXF: nie udało się przygotować narożników i wycięć z shape_data — '
                       'rysuję zwykły obrys bez wycięć', exc_info=True)
        return None, []


def _encje_wyciec(wyciecia, offset_x, offset_y):
    """Opisy encji wycięć: koło → CIRCLE, elipsa → ELLIPSE, wielokąt → polilinia z narożnikami."""
    encje = []
    for c in wyciecia:
        if c['type'] == 'ellipse':
            if not (c['rx'] > 0 and c['ry'] > 0):
                continue   # półoś zerowa albo ujemna — takiego wycięcia nie ma w edytorze
            srodek = (c['cx'] * 10 + offset_x, c['cy'] * 10 + offset_y)
            if abs(c['rx'] - c['ry']) < TOLERANCJA_KOLA_CM:
                encje.append(('circle', srodek, c['rx'] * 10))
                continue
            rx, ry = c['rx'] * 10, c['ry'] * 10
            kat = math.radians(c.get('angle') or 0)
            if rx >= ry:
                os_glowna = (rx * math.cos(kat), rx * math.sin(kat))
                proporcja = ry / rx
            else:
                # Dłuższa oś leży wzdłuż osi Y elipsy
                os_glowna = (-ry * math.sin(kat), ry * math.cos(kat))
                proporcja = rx / ry
            encje.append(('ellipse', srodek, os_glowna, proporcja))
        else:
            encje.append(('polyline', _contour_xyb(c['points'], c['corners'], offset_x, offset_y)))
    return encje


def _draw_cutouts(msp, wyciecia, offset_x, offset_y):
    """Wycięcia na warstwie CUT. Błąd przy którymkolwiek wycięciu cofa wszystkie (plik z połową
    wycięć wprowadziłby maszynę w błąd), zostawia sam obrys i zapisuje ostrzeżenie w logu."""
    dodane = []
    try:
        for opis in _encje_wyciec(wyciecia, offset_x, offset_y):
            if opis[0] == 'circle':
                dodane.append(msp.add_circle(opis[1], opis[2], dxfattribs={"layer": "CUT"}))
            elif opis[0] == 'ellipse':
                dodane.append(msp.add_ellipse(opis[1], major_axis=opis[2], ratio=opis[3],
                                              dxfattribs={"layer": "CUT"}))
            else:
                dodane.append(msp.add_lwpolyline(opis[1], format='xyb', close=True,
                                                 dxfattribs={"layer": "CUT"}))
    except Exception:
        logger.warning('DXF: nie udało się narysować wycięć — plik zawiera sam obrys',
                       exc_info=True)
        for encja in dodane:
            msp.delete_entity(encja)


def _build_edge_info(details):
    """Buduje czytelny opis obróbki krawędzi."""
    if not details.edges_type or details.edges_type == 'sharp':
        return None

    label = EDGE_TYPE_LABELS.get(details.edges_type, details.edges_type)
    if details.edges_type == 'round' and details.edges_r_value:
        return f"{label} R{details.edges_r_value}mm"
    if details.edges_type == 'chamfer' and details.edges_angle_value:
        return f"{label} {details.edges_angle_value}°"
    return label


def _setup_layers(doc):
    """Tworzy warstwy DXF dla CNC."""
    doc.layers.add("CUT", color=1)        # czerwony — kontur cięcia
    doc.layers.add("DIMENSIONS", color=3)  # zielony — wymiary
    doc.layers.add("INFO", color=5)        # niebieski — opisy


def _draw_product(msp, shape_type, shape_data, item, details, offset_x=0, offset_y=0):
    """
    Rysuje jeden produkt w modelspace z przesunięciem (offset).
    Zwraca bounding box (width_mm, height_mm) narysowanego kształtu.
    """
    length_mm = float(item.length_cm or 0) * 10
    width_mm = float(item.width_cm or 0) * 10
    thickness_mm = float(item.thickness_cm or 0) * 10

    drawn_w = 0
    drawn_h = 0

    # Wierzchołki obrysu z shape_data (cm); None, gdy ich nie ma albo dane są zepsute
    vertices_cm = None
    if shape_type != 'circle' and shape_data:
        surowe = shape_data.get('vertices')
        vertices_cm = shape_geometry.polygon_points(surowe)
        if vertices_cm is None and surowe is not None:
            # Zepsute wierzchołki: rysujemy prostokąt z wymiarów produktu (gałąź awaryjna niżej)
            logger.warning('DXF: zepsute wierzchołki obrysu w shape_data (%s) — rysuję prostokąt '
                           'z wymiarów produktu', shape_type)

    # --- Kontur cięcia ---
    if shape_type == 'circle':
        params = shape_data.get('params') if shape_data else None
        params = params if isinstance(params, dict) else {}
        # Średnica z wymiaru produktu: w shape_data starych wycen koła siedzi domyślne 80
        # (edytor nie aktualizował parametru dla koła bez rysunku)
        srednica_rysunku_cm = _liczba(params.get('diameter'))
        srednica_cm = _liczba(item.length_cm) or srednica_rysunku_cm
        diameter_mm = srednica_cm * 10
        radius = diameter_mm / 2
        center = (offset_x + radius, offset_y + radius)
        msp.add_circle(center, radius, dxfattribs={"layer": "CUT"})
        drawn_w = diameter_mm
        drawn_h = diameter_mm

        # Wymiar średnicy
        msp.add_diameter_dim(
            center=center,
            radius=radius,
            angle=45,
            dimstyle="EZDXF",
            override={"dimtxt": max(3, diameter_mm / 30)},
        ).render()
        # Współrzędne wycięć liczone są względem koła z rysunku (środek w params.diameter / 2).
        # Gdy koło produktu ma inną średnicę, środek się przesuwa o różnicę promieni.
        przesuniecie = (srednica_cm - srednica_rysunku_cm) * 10 / 2 if srednica_rysunku_cm > 0 else 0.0
        _, wyciecia = _geometria(shape_type, None, shape_data, details)
        _draw_cutouts(msp, wyciecia, offset_x + przesuniecie, offset_y + przesuniecie)

    elif vertices_cm:
        vertices_mm = [(x * 10, y * 10) for x, y in vertices_cm]

        # Przesuń o offset
        shifted = [(x + offset_x, y + offset_y) for x, y in vertices_mm]
        narozniki, wyciecia = _geometria(shape_type, vertices_cm, shape_data, details)
        punkty = None
        if any(narozniki or []):
            # Obrys z łukami i ścięciami narożników
            try:
                punkty = _contour_xyb(vertices_cm, narozniki, offset_x, offset_y)
            except Exception:
                logger.warning('DXF: nie udało się zbudować narożników — rysuję obrys z ostrymi rogami',
                               exc_info=True)
        if not punkty:
            # Bez narożników: te same wierzchołki co w pliku sprzed rysunku narożników
            punkty = [(x, y, 0.0) for x, y in shifted]
        msp.add_lwpolyline(punkty, format='xyb', close=True, dxfattribs={"layer": "CUT"})
        _draw_cutouts(msp, wyciecia, offset_x, offset_y)

        xs = [p[0] for p in shifted]
        ys = [p[1] for p in shifted]
        drawn_w = max(xs) - min(xs)
        drawn_h = max(ys) - min(ys)

        # Wymiary dla prostokąta — długość i szerokość
        if shape_type == 'rectangular' and len(shifted) == 4:
            dim_offset = max(5, drawn_h / 10)
            # Wymiar dolnej krawędzi (długość)
            msp.add_linear_dim(
                base=(offset_x, offset_y - dim_offset),
                p1=shifted[0],
                p2=shifted[1],
                dimstyle="EZDXF",
                override={"dimtxt": max(3, drawn_w / 40)},
            ).render()
            # Wymiar lewej krawędzi (szerokość)
            msp.add_linear_dim(
                base=(offset_x - dim_offset, offset_y),
                p1=shifted[0],
                p2=shifted[3],
                angle=90,
                dimstyle="EZDXF",
                override={"dimtxt": max(3, drawn_h / 40)},
            ).render()
        else:
            # Dla nie-prostokątów wymiaruj bounding box
            min_x, min_y = min(xs), min(ys)
            max_x, max_y = max(xs), max(ys)
            dim_offset = max(5, drawn_h / 10)
            msp.add_linear_dim(
                base=(min_x, min_y - dim_offset),
                p1=(min_x, min_y),
                p2=(max_x, min_y),
                dimstyle="EZDXF",
                override={"dimtxt": max(3, drawn_w / 40)},
            ).render()
            msp.add_linear_dim(
                base=(min_x - dim_offset, min_y),
                p1=(min_x, min_y),
                p2=(min_x, max_y),
                angle=90,
                dimstyle="EZDXF",
                override={"dimtxt": max(3, drawn_h / 40)},
            ).render()
    else:
        # Fallback: prostokąt z wymiarów
        pts = [
            (offset_x, offset_y),
            (offset_x + length_mm, offset_y),
            (offset_x + length_mm, offset_y + width_mm),
            (offset_x, offset_y + width_mm),
        ]
        # Prostokąt z wymiarów też może mieć narożniki (stare wyceny: tylko w krawędziach)
        # i wycięcia. Bez nich plik jest taki sam jak dawniej.
        kontur_cm = None
        if shape_type == 'rectangular' and length_mm > 0 and width_mm > 0:
            kontur_cm = [(0.0, 0.0), (length_mm / 10, 0.0), (length_mm / 10, width_mm / 10), (0.0, width_mm / 10)]
        narozniki, wyciecia = _geometria(shape_type, kontur_cm, shape_data, details)
        punkty = None
        if any(narozniki or []):
            try:
                punkty = _contour_xyb(kontur_cm, narozniki, offset_x, offset_y)
            except Exception:
                logger.warning('DXF: nie udało się zbudować narożników — rysuję prostokąt z ostrymi rogami',
                               exc_info=True)
        if punkty:
            msp.add_lwpolyline(punkty, format='xyb', close=True, dxfattribs={"layer": "CUT"})
        else:
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CUT"})
        _draw_cutouts(msp, wyciecia, offset_x, offset_y)
        drawn_w = length_mm
        drawn_h = width_mm

        dim_offset = max(5, drawn_h / 10)
        msp.add_linear_dim(
            base=(offset_x, offset_y - dim_offset),
            p1=pts[0],
            p2=pts[1],
            dimstyle="EZDXF",
            override={"dimtxt": max(3, drawn_w / 40)},
        ).render()
        msp.add_linear_dim(
            base=(offset_x - dim_offset, offset_y),
            p1=pts[0],
            p2=pts[3],
            angle=90,
            dimstyle="EZDXF",
            override={"dimtxt": max(3, drawn_h / 40)},
        ).render()

    # --- Etykieta INFO ---
    variant_label = VARIANT_LABELS.get(item.variant_code, item.variant_code or '?')
    quantity = details.quantity if details else 1
    edge_info = _build_edge_info(details) if details else None

    info_lines = [
        variant_label,
        f"Grubość: {thickness_mm:.0f}mm",
        f"Ilość: {quantity} szt.",
    ]
    if edge_info:
        info_lines.append(f"Krawędzie: {edge_info}")

    text_height = max(3, min(drawn_w, drawn_h) / 25)
    text_x = offset_x + drawn_w / 2
    text_y = offset_y + drawn_h + max(8, drawn_h / 8)

    for i, line in enumerate(info_lines):
        msp.add_text(
            line,
            height=text_height,
            dxfattribs={
                "layer": "INFO",
                "halign": 1,  # center
            },
        ).set_placement(
            (text_x, text_y + (len(info_lines) - 1 - i) * text_height * 1.6),
            align=TextEntityAlignment.CENTER,
        )

    return drawn_w, drawn_h


def generate_single_dxf(quote, items_with_details):
    """
    Generuje jeden plik DXF ze wszystkimi produktami ułożonymi obok siebie.

    Args:
        quote: obiekt Quote
        items_with_details: lista krotek (QuoteItem, QuoteItemDetails)

    Returns:
        BytesIO z zawartością pliku DXF
    """
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    _setup_layers(doc)
    msp = doc.modelspace()

    gap_mm = 50  # odstęp między produktami
    current_x = 0

    for item, details in items_with_details:
        shape_type = details.shape if details and details.shape else 'rectangular'
        shape_data = _parse_shape_data(details.shape_data if details else None)

        w, h = _draw_product(msp, shape_type, shape_data, item, details, offset_x=current_x, offset_y=0)
        current_x += w + gap_mm

    return _doc_to_bytes(doc)


def generate_product_dxf(item, details, quote_number=""):
    """
    Generuje plik DXF dla pojedynczego produktu.

    Returns:
        BytesIO z zawartością pliku DXF
    """
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # mm
    _setup_layers(doc)
    msp = doc.modelspace()

    shape_type = details.shape if details and details.shape else 'rectangular'
    shape_data = _parse_shape_data(details.shape_data if details else None)

    _draw_product(msp, shape_type, shape_data, item, details, offset_x=0, offset_y=0)

    return _doc_to_bytes(doc)


def generate_product_filename(item, details, product_index):
    """Generuje czytelną nazwę pliku DXF dla produktu."""
    variant_label = VARIANT_LABELS.get(item.variant_code, item.variant_code or 'produkt')
    # Zamień polskie znaki i spacje na bezpieczne znaki
    safe_name = variant_label.replace(' ', '_').replace('/', '-')
    for pl, en in [('ą', 'a'), ('ć', 'c'), ('ę', 'e'), ('ł', 'l'), ('ń', 'n'),
                   ('ó', 'o'), ('ś', 's'), ('ź', 'z'), ('ż', 'z'),
                   ('Ą', 'A'), ('Ć', 'C'), ('Ę', 'E'), ('Ł', 'L'), ('Ń', 'N'),
                   ('Ó', 'O'), ('Ś', 'S'), ('Ź', 'Z'), ('Ż', 'Z')]:
        safe_name = safe_name.replace(pl, en)
    return f"Produkt_{product_index}_{safe_name}.dxf"
