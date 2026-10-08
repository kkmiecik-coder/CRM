"""
Geometria kształtu blatu: narożniki (frezowanie = łuk, fazowanie = ścięcie) i wycięcia.

Ten sam algorytm co JS (modules/calculator/static/js/shape-corners.js
i shape-cutouts.js). Zgodność obu stron pilnują wspólne przypadki
tests/fixtures/narozniki_przypadki.json.

Jednostki: współrzędne i długości w cm, wymiar narożnika w mm (`r_mm`).
Narożnik: {'type': 'round'|'chamfer', 'r_mm': int} albo None (ostry).
Wycięcie: {'type': 'ellipse', 'cx', 'cy', 'rx', 'ry', 'angle'} albo
          {'type': 'polygon', 'points': [[x, y], ...], 'corners': [...]}.
"""
import json
import math
import re

KROK_LUKU_STOPNIE = 5.0
PUNKTY_ELIPSY = 72
KAT_MAKS_NAROZNIKA = 175.0
TYPY_NAROZNIKOW = ('round', 'chamfer')
# Litery narożników prostokąta w kolejności wierzchołków v0, v1, v2, v3 (jak PROSTOKAT_NAROZNIKI w JS)
LITERY_NAROZNIKOW_PROSTOKATA = ('N1', 'N2', 'N4', 'N3')
_LITERA_NAROZNIKA_WYCIECIA = re.compile(r'^H(\d+)\.P(\d+)$')
_LITERA_NAROZNIKA_OBRYSU = re.compile(r'^P(\d+)$')


def _skonczona(v):
    """Liczba skończona (nie bool, nie NaN, nie nieskończoność)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _punkt(p):
    """Punkt [x, y] jako para floatów albo None, gdy dane są nie do użycia (zepsute shape_data)."""
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        return None
    try:
        x, y = float(p[0]), float(p[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def polygon_points(punkty):
    """Lista punktów wielokąta (≥ 3) albo None, gdy choć jeden punkt jest nie do użycia."""
    if not isinstance(punkty, (list, tuple)) or len(punkty) < 3:
        return None
    wynik = [_punkt(p) for p in punkty]
    return None if any(p is None for p in wynik) else wynik


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _len(v):
    return math.hypot(v[0], v[1])


def _unit(v):
    d = _len(v)
    if d < 1e-12:
        return None
    return (v[0] / d, v[1] / d)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _signed_area(pts):
    suma = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        # Kolejność dodawania i odejmowania jak w dawnym _shoelaceArea (JS), żeby
        # zwykły kształt dawał po zaokrągleniu dokładnie to samo pole co dotąd.
        suma += x1 * y2
        suma -= x2 * y1
    return suma / 2.0


def normalize_corners(corners, n):
    """Lista długości n: poprawne narożniki albo None (ostry róg)."""
    wynik = []
    for i in range(n):
        c = corners[i] if isinstance(corners, list) and i < len(corners) else None
        if (isinstance(c, dict) and c.get('type') in TYPY_NAROZNIKOW
                and _skonczona(c.get('r_mm')) and c['r_mm'] >= 1):
            # floor(x + 0.5), a nie round(): Python zaokrągla .5 do parzystej, JS (Math.round) w górę
            wynik.append({'type': c['type'], 'r_mm': int(math.floor(c['r_mm'] + 0.5))})
        else:
            wynik.append(None)
    return wynik


def corner_angle(prev, v, nxt):
    """Kąt θ (rad) między promieniami V→P i V→N oraz dwusieczna; None gdy zdegenerowany.

    Łuk/ścięcie zawsze leży w klinie o kącie θ < 180° — dla rogu wypukłego to
    wnętrze blatu, dla wklęsłego wcięcie. Wzory są dla obu takie same.
    """
    u1 = _unit(_sub(prev, v))
    u2 = _unit(_sub(nxt, v))
    if u1 is None or u2 is None:
        return None
    cos_t = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    b = _unit((u1[0] + u2[0], u1[1] + u2[1]))
    if b is None:
        return None
    return {'theta': math.acos(cos_t), 'u1': u1, 'u2': u2, 'bisector': b}


def corner_factor(theta, corner_type):
    """Ile cm boku zużywa narożnik o wymiarze 1 cm: łuk 1/tan(θ/2), ścięcie 1."""
    if corner_type == 'chamfer':
        return 1.0
    return 1.0 / math.tan(theta / 2.0)


def corner_is_allowed(theta):
    return math.degrees(theta) <= KAT_MAKS_NAROZNIKA + 1e-9


def corner_geometry(prev, v, nxt, corner):
    """Punkty styczności/ścięcia narożnika i jego łuk; None gdy róg ostry albo zbyt płaski."""
    if not corner:
        return None
    ang = corner_angle(prev, v, nxt)
    if ang is None or not corner_is_allowed(ang['theta']):
        return None
    theta = ang['theta']
    wartosc_cm = corner['r_mm'] / 10.0
    t = wartosc_cm * corner_factor(theta, corner['type'])
    u1, u2 = ang['u1'], ang['u2']
    geom = {
        'type': corner['type'],
        't1': (v[0] + u1[0] * t, v[1] + u1[1] * t),
        't2': (v[0] + u2[0] * t, v[1] + u2[1] * t),
        'theta': theta,
        # Kierunek skrętu obrysu w tym wierzchołku (lewo = CCW) — z niego znak łuku
        'ccw': _cross(_sub(v, prev), _sub(nxt, v)) > 0,
        'extent': t,
    }
    if corner['type'] == 'round':
        b = ang['bisector']
        d = wartosc_cm / math.sin(theta / 2.0)
        geom['center'] = (v[0] + b[0] * d, v[1] + b[1] * d)
        geom['radius'] = wartosc_cm
        geom['sweep'] = math.pi - theta
    return geom


def _extent(ring, corners, i):
    n = len(ring)
    g = corner_geometry(ring[(i - 1) % n], ring[i], ring[(i + 1) % n], corners[i])
    return g['extent'] if g else 0.0


def max_corner_mm(ring, corners, index, corner_type):
    """Największy wymiar (mm) narożnika `index`, który mieści się między sąsiadami."""
    n = len(ring)
    corners = normalize_corners(corners, n)
    prev_i, next_i = (index - 1) % n, (index + 1) % n
    ang = corner_angle(ring[prev_i], ring[index], ring[next_i])
    if ang is None or not corner_is_allowed(ang['theta']):
        return 0
    k = corner_factor(ang['theta'], corner_type)
    limit_cm = float('inf')
    for sasiad in (prev_i, next_i):
        bok = _len(_sub(ring[sasiad], ring[index]))
        limit_cm = min(limit_cm, (bok - _extent(ring, corners, sasiad)) / k)
    return max(0, int(math.floor(limit_cm * 10 + 1e-9)))


def max_uniform_mm(ring, corner_type):
    """Największy wspólny wymiar (mm), gdy wszystkie rogi dostają ten sam typ i wymiar."""
    n = len(ring)
    wsp = []
    for i in range(n):
        ang = corner_angle(ring[(i - 1) % n], ring[i], ring[(i + 1) % n])
        if ang is None or not corner_is_allowed(ang['theta']):
            wsp.append(0.0)
        else:
            wsp.append(corner_factor(ang['theta'], corner_type))
    limit_cm = float('inf')
    for i in range(n):
        j = (i + 1) % n
        k = wsp[i] + wsp[j]
        if k > 0:
            limit_cm = min(limit_cm, _len(_sub(ring[j], ring[i])) / k)
    if limit_cm == float('inf'):
        return 0
    return max(0, int(math.floor(limit_cm * 10 + 1e-9)))


def clamp_corners(ring, corners):
    """Przycina każdy narożnik do jego limitu (jedno przejście wystarcza — przycinanie tylko zmniejsza)."""
    n = len(ring)
    wynik = normalize_corners(corners, n)
    if n < 3:
        return wynik
    for i in range(n):
        c = wynik[i]
        if not c:
            continue
        maks = max_corner_mm(ring, wynik, i, c['type'])
        if maks < 1:
            wynik[i] = None
        elif c['r_mm'] > maks:
            wynik[i] = {'type': c['type'], 'r_mm': maks}
    return wynik


def contour_segments(ring, corners):
    """Obrys jako lista odcinków i łuków (zamknięta, kolejno od wyjścia z wierzchołka 0)."""
    n = len(ring)
    if n < 3:
        return []
    corners = normalize_corners(corners, n)
    geoms = [corner_geometry(ring[(i - 1) % n], ring[i], ring[(i + 1) % n], corners[i]) for i in range(n)]
    wejscie = [g['t1'] if g else (float(ring[i][0]), float(ring[i][1])) for i, g in enumerate(geoms)]
    wyjscie = [g['t2'] if g else (float(ring[i][0]), float(ring[i][1])) for i, g in enumerate(geoms)]
    segmenty = []
    for i in range(n):
        j = (i + 1) % n
        if _len(_sub(wejscie[j], wyjscie[i])) > 1e-9:
            segmenty.append({'type': 'line', 'from': wyjscie[i], 'to': wejscie[j]})
        g = geoms[j]
        if g and g['type'] == 'round':
            segmenty.append({'type': 'arc', 'from': g['t1'], 'to': g['t2'], 'center': g['center'],
                             'radius': g['radius'], 'sweep': g['sweep'], 'ccw': g['ccw']})
        elif g:
            segmenty.append({'type': 'line', 'from': g['t1'], 'to': g['t2']})
    return segmenty


def flatten_segments(segments, step_deg=KROK_LUKU_STOPNIE):
    """Zamienia łuki na odcinki (krok ≤ step_deg). Pierścień bez powtórzonego punktu końcowego."""
    punkty = []
    for s in segments:
        if s['type'] != 'arc':
            punkty.append(tuple(s['from']))
            continue
        c = s['center']
        a0 = math.atan2(s['from'][1] - c[1], s['from'][0] - c[0])
        sweep = s['sweep'] if s['ccw'] else -s['sweep']
        kroki = max(1, int(math.ceil(math.degrees(abs(sweep)) / step_deg - 1e-9)))
        for k in range(kroki):
            a = a0 + sweep * k / kroki
            punkty.append((c[0] + s['radius'] * math.cos(a), c[1] + s['radius'] * math.sin(a)))
    return punkty


def contour_area(ring, corners):
    """Dokładne pole obrysu z narożnikami: wielokąt cięciw + odcinki koła łuków."""
    if not ring or len(ring) < 3:
        return 0.0
    segmenty = contour_segments(ring, corners)
    orientacja = 1.0 if _signed_area(ring) >= 0 else -1.0
    suma = _signed_area([s['from'] for s in segmenty]) * orientacja
    for s in segmenty:
        if s['type'] == 'arc':
            odcinek_kola = s['radius'] ** 2 / 2.0 * (s['sweep'] - math.sin(s['sweep']))
            # Łuk skręcający zgodnie z orientacją obrysu (róg wypukły) dokłada pole
            # między cięciwą a łukiem; w rogu wklęsłym to pole odpada.
            suma += odcinek_kola if s['ccw'] == (orientacja > 0) else -odcinek_kola
    return abs(suma)


def arc_bulge(segment):
    """Wybrzuszenie (bulge) łuku dla LWPOLYLINE: tan(kąt/4), dodatnie gdy łuk skręca w lewo."""
    b = math.tan(segment['sweep'] / 4.0)
    return b if segment['ccw'] else -b


def ellipse_perimeter_cm(rx, ry):
    """Obwód elipsy (Ramanujan) z półosi w cm."""
    a, b = float(rx), float(ry)
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def ellipse_points(cutout, n=PUNKTY_ELIPSY):
    kat = math.radians(float(cutout.get('angle') or 0))
    ca, sa = math.cos(kat), math.sin(kat)
    punkty = []
    for k in range(n):
        t = 2 * math.pi * k / n
        x = cutout['rx'] * math.cos(t)
        y = cutout['ry'] * math.sin(t)
        punkty.append((cutout['cx'] + x * ca - y * sa, cutout['cy'] + x * sa + y * ca))
    return punkty


def cutout_area(cutout):
    if cutout.get('type') == 'ellipse':
        return math.pi * float(cutout['rx']) * float(cutout['ry'])
    return contour_area(cutout.get('points') or [], cutout.get('corners'))


def _wyciecie_z_surowego(c):
    """Znormalizowane wycięcie albo None. Te same warunki co ShapeCutouts.normalize w JS —
    pominięte tu wycięcie nie istnieje też w edytorze, więc numeracja H{n} się zgadza."""
    if not isinstance(c, dict):
        return None
    if c.get('type') == 'ellipse':
        try:
            cx, cy = float(c['cx']), float(c['cy'])
            rx, ry = float(c['rx']), float(c['ry'])
            kat = float(c.get('angle') or 0)
        except (KeyError, TypeError, ValueError):
            return None
        # Półosie muszą być dodatnie; NaN i nieskończoność też odpadają (w JS: !(rx > 0))
        if not all(math.isfinite(v) for v in (cx, cy, rx, ry, kat)) or rx <= 0 or ry <= 0:
            return None
        return {'type': 'ellipse', 'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'angle': kat}
    if c.get('type') == 'polygon':
        punkty = polygon_points(c.get('points'))
        if punkty is None:
            return None
        return {'type': 'polygon', 'points': punkty,
                'corners': normalize_corners(c.get('corners'), len(punkty))}
    return None


def cutouts_from_shape_data(shape_data):
    """Wycięcia z shape_data: pole `cutouts`, a dla starych danych — wielokąty z `holes`.
    Zepsute wpisy są pomijane, a nie przerywają liczenia."""
    if not isinstance(shape_data, dict):
        return []
    surowe = shape_data.get('cutouts')
    if isinstance(surowe, list):
        return [c for c in (_wyciecie_z_surowego(w) for w in surowe) if c]
    wynik = []
    holes = shape_data.get('holes')
    for h in holes if isinstance(holes, list) else []:
        punkty = polygon_points(h)
        if punkty is not None:
            wynik.append({'type': 'polygon', 'points': punkty, 'corners': [None] * len(punkty)})
    return wynik


def corners_from_edges(shape, edges_config, n_outer, cutout_sizes):
    """Narożniki ze starych wpisów krawędzi (`QuoteItemDetails.edges_config`).

    Wyceny sprzed rysunku narożników trzymają je tylko w krawędziach. Mapowanie jak
    `pullCornersFromEdges` w JS: prostokąt N1→v0, N2→v1, N4→v2, N3→v3; wielokąt P{i}→wierzchołek
    i−1; wycięcie wielokątne H{n}.P{j}→wycięcie n−1, wierzchołek j−1. Liczą się tylko
    `round`/`chamfer` z `r_value` ≥ 1 (mm); litery spoza zakresu są ignorowane.

    n_outer — liczba wierzchołków obrysu (0 = brak, np. koło); cutout_sizes — {indeks wycięcia:
    liczba wierzchołków} dla wycięć wielokątnych. Zwraca (obrys albo None, {indeks: lista}).
    """
    wpisy = edges_config
    if isinstance(wpisy, str):
        try:
            wpisy = json.loads(wpisy)
        except ValueError:
            wpisy = []
    if not isinstance(wpisy, list):
        wpisy = []
    obrys = [None] * n_outer if n_outer else None
    wyciecia = {k: [None] * n for k, n in cutout_sizes.items()}
    for e in wpisy:
        if not isinstance(e, dict) or e.get('type') not in TYPY_NAROZNIKOW:
            continue
        r = e.get('r_value')
        if isinstance(r, str):
            try:
                r = float(r)
            except ValueError:
                continue
        if not _skonczona(r) or r < 1:
            continue
        litera = str(e.get('letter') or e.get('id') or '').strip().upper()
        lista, indeks = None, None
        m = _LITERA_NAROZNIKA_WYCIECIA.match(litera)
        if m:
            numer, wierzcholek = int(m.group(1)), int(m.group(2))
            if numer >= 1 and wierzcholek >= 1:
                lista, indeks = wyciecia.get(numer - 1), wierzcholek - 1
        elif shape == 'rectangular':
            if litera in LITERY_NAROZNIKOW_PROSTOKATA:
                lista, indeks = obrys, LITERY_NAROZNIKOW_PROSTOKATA.index(litera)
        else:
            m = _LITERA_NAROZNIKA_OBRYSU.match(litera)
            if m and int(m.group(1)) >= 1:
                lista, indeks = obrys, int(m.group(1)) - 1
        if lista is not None and indeks is not None and indeks < len(lista):
            lista[indeks] = {'type': e['type'], 'r_mm': int(math.floor(r + 0.5))}
    return obrys, wyciecia


def resolve_corners(shape, ring, shape_data, edges_config):
    """Narożniki obrysu i wycięć gotowe do rysowania: (obrys albo None, lista wycięć).

    `shape_data` jest źródłem prawdy. Gdy nie ma w nim żadnego narożnika (stara wycena), bierzemy
    je z `edges_config`. Na końcu przycinamy do geometrii — dla danych z edytora to no-op,
    dla zepsutych nie pozwala narysować obrysu cofającego się po sobie.
    """
    wyciecia = cutouts_from_shape_data(shape_data)
    ring = polygon_points(ring)
    obrys = None
    if ring is not None:
        surowe = shape_data.get('corners') if isinstance(shape_data, dict) else None
        obrys = normalize_corners(surowe, len(ring))
    ma_narozniki = any(obrys or []) or any(any(w['corners']) for w in wyciecia if w['type'] == 'polygon')
    if not ma_narozniki and edges_config:
        z_krawedzi, dla_wyciec = corners_from_edges(
            shape, edges_config, len(ring) if ring else 0,
            {i: len(w['points']) for i, w in enumerate(wyciecia) if w['type'] == 'polygon'})
        if z_krawedzi is not None:
            obrys = z_krawedzi
        for i, lista in dla_wyciec.items():
            wyciecia[i]['corners'] = lista
    if ring is not None:
        obrys = clamp_corners(ring, obrys)
    for w in wyciecia:
        if w['type'] == 'polygon':
            w['corners'] = clamp_corners(w['points'], w['corners'])
    return obrys, wyciecia
