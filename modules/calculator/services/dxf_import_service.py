"""
DXF Import Service
Parses DXF files and extracts shape data for the calculator module.
All internal coordinates are normalized to centimeters.
"""

import math
from io import BytesIO, StringIO

import ezdxf


# DXF $INSUNITS codes -> (unit_name, scale_factor_to_cm)
_INSUNITS_MAP = {
    4: ('mm', 0.1),    # millimeters -> cm
    5: ('cm', 1.0),    # centimeters -> cm (no conversion)
    6: ('m', 100.0),   # meters -> cm
}

_DEFAULT_UNIT = ('mm', 0.1)  # assume mm when not specified


def _get_unit_info(doc):
    """Returns (unit_name, scale_to_cm) from document header."""
    try:
        insunits = doc.header.get('$INSUNITS', 4)
        return _INSUNITS_MAP.get(insunits, _DEFAULT_UNIT)
    except Exception:
        return _DEFAULT_UNIT


def _normalize_vertices(vertices_raw, scale_to_cm):
    """
    Converts raw (x, y) vertex list to cm, normalizing so min_x/min_y = 0.
    Returns list of (x_cm, y_cm) tuples as plain Python floats.
    """
    pts = [(float(v[0]) * scale_to_cm, float(v[1]) * scale_to_cm) for v in vertices_raw]
    if not pts:
        return pts
    min_x = min(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    return [(x - min_x, y - min_y) for x, y in pts]


def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polygon_area(vertices):
    """Shoelace formula — signed area (positive for CCW)."""
    n = len(vertices)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += vertices[i][0] * vertices[j][1]
        area -= vertices[j][0] * vertices[i][1]
    return abs(area) / 2.0


def _bbox(vertices):
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def _is_right_angle(a, b, c, tol_deg=2.0):
    """Returns True if angle at vertex b is ~90 degrees."""
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag = math.hypot(*ab) * math.hypot(*cb)
    if mag < 1e-10:
        return False
    cos_a = max(-1.0, min(1.0, dot / mag))
    angle = math.degrees(math.acos(cos_a))
    return abs(angle - 90.0) <= tol_deg


def _classify_triangle(verts):
    """
    Classifies a 3-vertex polygon into a triangle subtype.
    Returns (shape_type, params) where params match ShapeGeometry format.
    All verts are in cm.
    """
    a, b, c = verts[0], verts[1], verts[2]
    sides = sorted([_dist(a, b), _dist(b, c), _dist(c, a)])
    s0, s1, s2 = sides  # s0 <= s1 <= s2

    # Check for right angle at each vertex
    has_right = (
        _is_right_angle(c, a, b) or
        _is_right_angle(a, b, c) or
        _is_right_angle(b, c, a)
    )

    # Equilateral: all sides equal within 2%
    rel_tol = 0.02
    if abs(s2 - s0) / max(s2, 1e-10) < rel_tol:
        return 'triangle_equilateral', {'side': round(s1, 4)}

    # Right triangle
    if has_right:
        # legs = two shorter sides, hypotenuse = longest
        # Find the right-angle vertex and extract its two legs
        leg_pairs = []
        for apex, p1, p2 in [(a, b, c), (b, a, c), (c, a, b)]:
            if _is_right_angle(p1, apex, p2):
                leg_pairs = (_dist(apex, p1), _dist(apex, p2))
                break
        if leg_pairs:
            legA, legB = sorted(leg_pairs)
            return 'triangle_right', {'legA': round(legA, 4), 'legB': round(legB, 4)}

    # Isosceles: exactly two sides equal within 2%
    if abs(s0 - s1) / max(s1, 1e-10) < rel_tol:
        base, arm = s2, s0
        return 'triangle_isosceles', {'base': round(base, 4), 'arm': round(arm, 4)}
    if abs(s1 - s2) / max(s2, 1e-10) < rel_tol:
        base, arm = s0, s1
        return 'triangle_isosceles', {'base': round(base, 4), 'arm': round(arm, 4)}

    # Custom triangle: all sides different
    return 'triangle_custom', {
        'sideA': round(s0, 4),
        'sideB': round(s1, 4),
        'sideC': round(s2, 4),
    }


def _vectors_parallel(v1, v2, tol_deg=2.0):
    """Returns True if two direction vectors are parallel (or anti-parallel)."""
    mag1 = math.hypot(*v1)
    mag2 = math.hypot(*v2)
    if mag1 < 1e-10 or mag2 < 1e-10:
        return False
    cos_a = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (mag1 * mag2))
    cos_a = min(1.0, cos_a)
    return math.degrees(math.acos(cos_a)) <= tol_deg


def _classify_quad(verts):
    """
    Classifies a 4-vertex polygon.
    Returns (shape_type, params) matching ShapeGeometry format.
    All verts are in cm.
    """
    a, b, c, d = verts[0], verts[1], verts[2], verts[3]

    # Edge vectors
    ab = (b[0] - a[0], b[1] - a[1])
    bc = (c[0] - b[0], c[1] - b[1])
    cd = (d[0] - c[0], d[1] - c[1])
    da = (a[0] - d[0], a[1] - d[1])

    ab_cd_parallel = _vectors_parallel(ab, cd)
    bc_da_parallel = _vectors_parallel(bc, da)

    area = _polygon_area(verts)
    min_x, min_y, max_x, max_y = _bbox(verts)
    bbox_area = (max_x - min_x) * (max_y - min_y)

    # Rectangular: 4 vertices, area ≈ bbox area (within 2%)
    if bbox_area > 1e-10 and abs(area - bbox_area) / bbox_area < 0.02:
        w = round(max_x - min_x, 4)
        h = round(max_y - min_y, 4)
        length = max(w, h)
        width = min(w, h)
        return 'rectangular', {'length': length, 'width': width}

    # Both pairs of opposite sides parallel => parallelogram or rectangle
    if ab_cd_parallel and bc_da_parallel:
        side_a = round(_dist(a, b), 4)
        side_b = round(_dist(b, c), 4)

        # Compute angle at vertex a (between da and ab)
        da_vec = (a[0] - d[0], a[1] - d[1])
        ab_vec = ab
        mag_da = math.hypot(*da_vec)
        mag_ab = math.hypot(*ab_vec)
        if mag_da > 1e-10 and mag_ab > 1e-10:
            cos_a = max(-1.0, min(1.0,
                (da_vec[0] * ab_vec[0] + da_vec[1] * ab_vec[1]) / (mag_da * mag_ab)
            ))
            angle_deg = round(math.degrees(math.acos(cos_a)), 2)
        else:
            angle_deg = 90.0

        return 'parallelogram', {'sideA': side_a, 'sideB': side_b, 'angle': angle_deg}

    # One pair of parallel sides => trapezoid
    if ab_cd_parallel or bc_da_parallel:
        if ab_cd_parallel:
            base_a = round(_dist(a, b), 4)
            base_b = round(_dist(c, d), 4)
            # height: perpendicular distance between ab and cd lines
            h = round(abs((c[1] + d[1]) / 2 - (a[1] + b[1]) / 2), 4)
            # offset: horizontal shift of top base relative to bottom base
            offset = round(abs(min(c[0], d[0]) - min(a[0], b[0])), 4)
        else:
            base_a = round(_dist(b, c), 4)
            base_b = round(_dist(d, a), 4)
            h = round(abs((a[0] + d[0]) / 2 - (b[0] + c[0]) / 2), 4)
            offset = round(abs(min(a[1], d[1]) - min(b[1], c[1])), 4)

        return 'trapezoid_asymmetric', {
            'baseA': max(base_a, base_b),
            'baseB': min(base_a, base_b),
            'height': h,
            'offset': offset,
        }

    # Fall through to polygon
    return 'polygon', {}


def _classify_polyline(verts):
    """
    Classifies a closed polyline by vertex count and geometry.
    Returns (shape_type, params).
    """
    n = len(verts)
    if n == 3:
        return _classify_triangle(verts)
    if n == 4:
        return _classify_quad(verts)
    # All other closed polylines
    return 'polygon', {}


def _process_lwpolyline(entity, scale_to_cm):
    """
    Processes an LWPOLYLINE entity.
    Returns a product dict or None if the polyline is not closed / degenerate.
    """
    # Only process closed polylines
    if not entity.is_closed:
        return None

    raw_pts = [(pt[0], pt[1]) for pt in entity.get_points('xy')]
    if len(raw_pts) < 3:
        return None

    verts_cm = _normalize_vertices(raw_pts, scale_to_cm)

    shape_type, params = _classify_polyline(verts_cm)

    min_x, min_y, max_x, max_y = _bbox(verts_cm)
    bbox_w_cm = max_x - min_x
    bbox_h_cm = max_y - min_y
    area_cm2 = _polygon_area(verts_cm)

    layer = entity.dxf.layer if entity.dxf.hasattr('layer') else '0'

    return {
        'shape_type': shape_type,
        'bbox_width_mm': round(bbox_w_cm * 10, 4),
        'bbox_height_mm': round(bbox_h_cm * 10, 4),
        'area_mm2': round(area_cm2 * 100, 4),
        'layer': layer,
        'vertices_cm': [(round(x, 6), round(y, 6)) for x, y in verts_cm],
        'params': params,
    }


def _process_circle(entity, scale_to_cm):
    """
    Processes a CIRCLE entity.
    Returns a product dict.
    """
    radius_cm = entity.dxf.radius * scale_to_cm
    diameter_cm = radius_cm * 2
    area_cm2 = math.pi * radius_cm ** 2

    layer = entity.dxf.layer if entity.dxf.hasattr('layer') else '0'

    return {
        'shape_type': 'circle',
        'bbox_width_mm': round(diameter_cm * 10, 4),
        'bbox_height_mm': round(diameter_cm * 10, 4),
        'area_mm2': round(area_cm2 * 100, 4),
        'layer': layer,
        'vertices_cm': [],
        'params': {'diameter': round(diameter_cm, 4)},
    }


def parse_dxf(file_bytes):
    """
    Parses DXF file bytes and extracts shape data for the calculator module.

    Args:
        file_bytes: bytes content of a DXF file

    Returns:
        dict with:
            - products: list of shape dicts (shape_type, bbox_width_mm,
                        bbox_height_mm, area_mm2, layer, vertices_cm, params)
            - units: detected unit string ('mm', 'cm', 'm', or None)
            - layer_names: sorted list of unique layer names found
    """
    # ezdxf.read() requires a text stream (TextIO), not binary
    text = file_bytes.decode('utf-8', errors='surrogateescape')
    doc = ezdxf.read(StringIO(text))

    unit_name, scale_to_cm = _get_unit_info(doc)

    msp = doc.modelspace()
    products = []
    layer_names = set()

    for entity in msp:
        product = None

        if entity.dxftype() == 'LWPOLYLINE':
            product = _process_lwpolyline(entity, scale_to_cm)
        elif entity.dxftype() == 'CIRCLE':
            product = _process_circle(entity, scale_to_cm)

        if product is not None:
            products.append(product)
            layer_names.add(product['layer'])

    return {
        'products': products,
        'units': unit_name,
        'layer_names': sorted(layer_names),
    }
