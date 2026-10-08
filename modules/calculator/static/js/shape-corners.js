// shape-corners.js
// Geometria narożników: frezowanie (łuk, type 'round') i fazowanie (ścięcie, type 'chamfer').
// Port 1:1 z modules/calculator/services/shape_geometry.py — zgodność pilnują
// przypadki z tests/fixtures/narozniki_przypadki.json.
// Współrzędne w cm, wymiar narożnika w mm (r_mm). Bez DOM i canvasu.

var ShapeCorners = (function() {
    'use strict';

    var KROK_LUKU_STOPNIE = 5;
    var MAX_ANGLE_DEG = 175;      // powyżej (prawie prosto) narożnika nie da się nadać
    var TYPY = { round: true, chamfer: true };

    function _sub(a, b) { return [a[0] - b[0], a[1] - b[1]]; }
    function _len(v) { return Math.hypot(v[0], v[1]); }
    function _unit(v) {
        var d = _len(v);
        return d < 1e-12 ? null : [v[0] / d, v[1] / d];
    }
    function _cross(a, b) { return a[0] * b[1] - a[1] * b[0]; }
    function _at(ring, i) { var n = ring.length; return ring[((i % n) + n) % n]; }

    function _signedArea(pts) {
        var s = 0, n = pts.length;
        for (var i = 0; i < n; i++) {
            var p = pts[i], q = pts[(i + 1) % n];
            // Kolejność dodawania i odejmowania jak w dawnym _shoelaceArea
            // (shape-geometry.js): dzięki temu zwykły kształt daje po zaokrągleniu
            // dokładnie to samo pole co dotąd.
            s += p[0] * q[1];
            s -= q[0] * p[1];
        }
        return s / 2;
    }

    // Lista długości n: poprawne narożniki albo null (ostry róg)
    function normalize(corners, n) {
        var wynik = [];
        for (var i = 0; i < n; i++) {
            var c = (corners && i < corners.length) ? corners[i] : null;
            if (c && TYPY[c.type] && typeof c.r_mm === 'number' && c.r_mm >= 1) {
                wynik.push({ type: c.type, r_mm: Math.floor(c.r_mm + 0.5) });
            } else {
                wynik.push(null);
            }
        }
        return wynik;
    }

    function hasAny(corners) {
        if (!corners) return false;
        for (var i = 0; i < corners.length; i++) {
            if (corners[i]) return true;
        }
        return false;
    }

    // Kąt θ między promieniami V→P i V→N oraz dwusieczna. Łuk/ścięcie zawsze leży
    // w klinie o kącie θ < 180° (róg wypukły: wnętrze blatu, wklęsły: wcięcie).
    function cornerAngle(prev, v, next) {
        var u1 = _unit(_sub(prev, v));
        var u2 = _unit(_sub(next, v));
        if (!u1 || !u2) return null;
        var cos = Math.max(-1, Math.min(1, u1[0] * u2[0] + u1[1] * u2[1]));
        var b = _unit([u1[0] + u2[0], u1[1] + u2[1]]);
        if (!b) return null;
        return { theta: Math.acos(cos), u1: u1, u2: u2, bisector: b };
    }

    // Ile cm boku zużywa narożnik o wymiarze 1 cm: łuk 1/tan(θ/2), ścięcie 1
    function factor(theta, type) {
        return type === 'chamfer' ? 1 : 1 / Math.tan(theta / 2);
    }

    function isAllowed(theta) {
        return theta * 180 / Math.PI <= MAX_ANGLE_DEG + 1e-9;
    }

    function geometry(prev, v, next, corner) {
        if (!corner) return null;
        var ang = cornerAngle(prev, v, next);
        if (!ang || !isAllowed(ang.theta)) return null;
        var wartosc = corner.r_mm / 10;
        var t = wartosc * factor(ang.theta, corner.type);
        var g = {
            type: corner.type,
            t1: [v[0] + ang.u1[0] * t, v[1] + ang.u1[1] * t],
            t2: [v[0] + ang.u2[0] * t, v[1] + ang.u2[1] * t],
            theta: ang.theta,
            // Kierunek skrętu obrysu w wierzchołku (lewo = CCW) — z niego kierunek łuku
            ccw: _cross(_sub(v, prev), _sub(next, v)) > 0,
            extent: t
        };
        if (corner.type === 'round') {
            var d = wartosc / Math.sin(ang.theta / 2);
            g.center = [v[0] + ang.bisector[0] * d, v[1] + ang.bisector[1] * d];
            g.radius = wartosc;
            g.sweep = Math.PI - ang.theta;
        }
        return g;
    }

    function _extent(ring, corners, i) {
        var g = geometry(_at(ring, i - 1), ring[i], _at(ring, i + 1), corners[i]);
        return g ? g.extent : 0;
    }

    // Największy wymiar (mm) narożnika `index`, który mieści się między sąsiadami
    function maxCornerMm(ring, corners, index, type) {
        var n = ring ? ring.length : 0;
        if (n < 3) return 0;
        var norm = normalize(corners, n);
        var prevI = (index - 1 + n) % n, nextI = (index + 1) % n;
        var ang = cornerAngle(ring[prevI], ring[index], ring[nextI]);
        if (!ang || !isAllowed(ang.theta)) return 0;
        var k = factor(ang.theta, type);
        var limit = Infinity;
        [prevI, nextI].forEach(function(s) {
            var bok = _len(_sub(ring[s], ring[index]));
            limit = Math.min(limit, (bok - _extent(ring, norm, s)) / k);
        });
        return Math.max(0, Math.floor(limit * 10 + 1e-9));
    }

    // Największy wspólny wymiar (mm), gdy wszystkie rogi dostają ten sam typ i wymiar
    function maxUniformMm(ring, type) {
        var n = ring ? ring.length : 0;
        if (n < 3) return 0;
        var wsp = [];
        for (var i = 0; i < n; i++) {
            var ang = cornerAngle(_at(ring, i - 1), ring[i], _at(ring, i + 1));
            wsp.push(ang && isAllowed(ang.theta) ? factor(ang.theta, type) : 0);
        }
        var limit = Infinity;
        for (var j = 0; j < n; j++) {
            var k = wsp[j] + wsp[(j + 1) % n];
            if (k > 0) limit = Math.min(limit, _len(_sub(ring[(j + 1) % n], ring[j])) / k);
        }
        if (limit === Infinity) return 0;
        return Math.max(0, Math.floor(limit * 10 + 1e-9));
    }

    // Przycina każdy narożnik do limitu (jedno przejście — przycinanie tylko zmniejsza)
    function clampCorners(ring, corners) {
        var n = ring ? ring.length : 0;
        var wynik = normalize(corners, n);
        if (n < 3) return wynik;
        for (var i = 0; i < n; i++) {
            var c = wynik[i];
            if (!c) continue;
            var maks = maxCornerMm(ring, wynik, i, c.type);
            if (maks < 1) wynik[i] = null;
            else if (c.r_mm > maks) wynik[i] = { type: c.type, r_mm: maks };
        }
        return wynik;
    }

    // Obrys jako lista odcinków i łuków (zamknięta, od wyjścia z wierzchołka 0)
    function contourSegments(ring, corners) {
        var n = ring ? ring.length : 0;
        if (n < 3) return [];
        var norm = normalize(corners, n);
        var geoms = [], wejscie = [], wyjscie = [];
        for (var i = 0; i < n; i++) {
            var g = geometry(_at(ring, i - 1), ring[i], _at(ring, i + 1), norm[i]);
            geoms.push(g);
            wejscie.push(g ? g.t1 : [ring[i][0], ring[i][1]]);
            wyjscie.push(g ? g.t2 : [ring[i][0], ring[i][1]]);
        }
        var segmenty = [];
        for (var a = 0; a < n; a++) {
            var b = (a + 1) % n;
            if (_len(_sub(wejscie[b], wyjscie[a])) > 1e-9) {
                segmenty.push({ type: 'line', from: wyjscie[a], to: wejscie[b] });
            }
            var gb = geoms[b];
            if (gb && gb.type === 'round') {
                segmenty.push({ type: 'arc', from: gb.t1, to: gb.t2, center: gb.center,
                                radius: gb.radius, sweep: gb.sweep, ccw: gb.ccw });
            } else if (gb) {
                segmenty.push({ type: 'line', from: gb.t1, to: gb.t2 });
            }
        }
        return segmenty;
    }

    // Łuki → odcinki (krok ≤ stepDeg); pierścień bez powtórzonego punktu końcowego
    function flatten(segments, stepDeg) {
        var krok = stepDeg || KROK_LUKU_STOPNIE;
        var punkty = [];
        (segments || []).forEach(function(s) {
            if (s.type !== 'arc') {
                punkty.push([s.from[0], s.from[1]]);
                return;
            }
            var c = s.center;
            var a0 = Math.atan2(s.from[1] - c[1], s.from[0] - c[0]);
            var sweep = s.ccw ? s.sweep : -s.sweep;
            var kroki = Math.max(1, Math.ceil(Math.abs(sweep) * 180 / Math.PI / krok - 1e-9));
            for (var k = 0; k < kroki; k++) {
                var ang = a0 + sweep * k / kroki;
                punkty.push([c[0] + s.radius * Math.cos(ang), c[1] + s.radius * Math.sin(ang)]);
            }
        });
        return punkty;
    }

    // Dokładne pole obrysu z narożnikami: wielokąt cięciw + odcinki koła łuków
    function contourArea(ring, corners) {
        if (!ring || ring.length < 3) return 0;
        var segmenty = contourSegments(ring, corners);
        var orientacja = _signedArea(ring) >= 0 ? 1 : -1;
        var suma = _signedArea(segmenty.map(function(s) { return s.from; })) * orientacja;
        segmenty.forEach(function(s) {
            if (s.type !== 'arc') return;
            var odcinekKola = s.radius * s.radius / 2 * (s.sweep - Math.sin(s.sweep));
            // Róg wypukły (skręt zgodny z orientacją) dokłada pole między cięciwą a łukiem
            suma += (s.ccw === (orientacja > 0)) ? odcinekKola : -odcinekKola;
        });
        return Math.abs(suma);
    }

    // Odległość (cm) od wierzchołka do środka łuku/ścięcia wzdłuż dwusiecznej
    function midpointDistance(theta, corner) {
        var w = corner.r_mm / 10;
        if (corner.type === 'chamfer') return w * Math.cos(theta / 2);
        return w / Math.sin(theta / 2) - w;
    }

    // Odwrotność midpointDistance: wymiar narożnika (cm) dla zadanej odległości środka
    function valueFromMidpointDistance(theta, type, dist) {
        if (!(dist > 0)) return 0;
        if (type === 'chamfer') return dist / Math.cos(theta / 2);
        return dist / (1 / Math.sin(theta / 2) - 1);
    }

    // Etykieta na rysunku dla produkcji. Fazowanie ma równe ramiona (r_mm na każdym boku):
    // „{r}×45°” mówi prawdę tylko w rogu prostym (±0,5°), w innym kącie — „{r}×{r}”.
    // theta (rad) — kąt wewnętrzny rogu; bez niego zakładamy róg prosty.
    function label(corner, theta) {
        if (corner.type !== 'chamfer') return 'R' + corner.r_mm;
        var prosty = theta == null || Math.abs(theta * 180 / Math.PI - 90) <= 0.5;
        return prosty ? corner.r_mm + '×45°' : corner.r_mm + '×' + corner.r_mm;
    }

    return {
        MAX_ANGLE_DEG: MAX_ANGLE_DEG,
        normalize: normalize,
        hasAny: hasAny,
        cornerAngle: cornerAngle,
        factor: factor,
        isAllowed: isAllowed,
        geometry: geometry,
        maxCornerMm: maxCornerMm,
        maxUniformMm: maxUniformMm,
        clampCorners: clampCorners,
        contourSegments: contourSegments,
        flatten: flatten,
        contourArea: contourArea,
        midpointDistance: midpointDistance,
        valueFromMidpointDistance: valueFromMidpointDistance,
        label: label
    };
})();

window.ShapeCorners = ShapeCorners;
