// shape-edges-sync.js
// Spójność danych krawędzi produktu z rysunkiem z Canvy:
//  - po zmianie topologii (liczba punktów, wycięcia) usuwa nieaktualne litery
//    i przenumerowuje wycięcia (np. H3.* → H2.* po usunięciu drugiego),
//  - odświeża długości krawędzi, które zostały (przesunięty punkt, nowy rozmiar wycięcia),
//  - narożniki działają w obie strony: z krawędzi na rysunek (pullCornersFromEdges, po „Zastosuj”
//    w modalu i po wczytaniu) oraz z rysunku do krawędzi (cornerEntries w syncForm: rysunek
//    jest źródłem prawdy, tryb przechodzi na zaawansowany).
// Dane krawędzi siedzą w form.dataset.edgesData; zapisuje je EdgesModule.setFormEdges.
// Zależności (w chwili wywołania): ShapeCutouts, ShapeCorners, EdgesModule.

var ShapeEdgesSync = (function() {
    'use strict';

    // Litery prostokąta → wymiar, z którego bierze się długość
    var LITERY_PROSTOKATA = { A: 'length', B: 'length', E: 'length', F: 'length',
                              C: 'width', D: 'width', G: 'width', H: 'width' };
    var NAROZNIK_RE = /^(N\d+|P\d+|H\d+\.P\d+)$/;
    var WYCIECIE_RE = /^H(\d+)\.([GDP])(\d+)$/;

    function _parse(json, fallback) {
        try { return json ? JSON.parse(json) : fallback; } catch (e) { return fallback; }
    }

    function _dims(form) {
        function v(sel) {
            var el = form.querySelector('input[data-field="' + sel + '"]');
            return el ? (parseFloat(el.value) || 0) : 0;
        }
        return { length: v('length'), width: v('width'), thickness: v('thickness') };
    }

    // Obwód elipsy z wymiarów opisanego prostokąta — jak calculateEllipsePerimeterCm w edges.js
    function _obwodElipsy(dl, sz) {
        var a = dl / 2, b = sz / 2;
        return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
    }

    function isCornerLetter(letter) {
        return NAROZNIK_RE.test(String(letter || ''));
    }

    // Sygnatura topologii: typ kształtu, liczba wierzchołków obrysu, wycięcia (id, typ, liczba punktów)
    function topologySignature(shape, sd) {
        return {
            shape: shape,
            outer: (sd && sd.vertices) ? sd.vertices.length : 0,
            cutouts: ShapeCutouts.fromShapeData(sd).map(function(c) {
                return { id: c.id, type: c.type, n: c.type === 'polygon' ? c.points.length : 0 };
            })
        };
    }

    // Rodzina liter obrysu: prostokąt (A–H, N1–N4), koło (KG/KD) albo wielokąt (G/D/P).
    // Trójkąt, trapez czy równoległobok po pierwszym przeciągnięciu punktu stają się „polygon”,
    // ale litery G/D/P zostają te same — porównujemy więc rodziny, nie surowy typ kształtu.
    function _rodzina(shape) {
        if (shape === 'rectangular') return 'rect';
        if (shape === 'circle' || shape === 'round') return 'circle';
        return 'polygon';
    }

    // Usuwa wpisy, które po zmianie topologii wskazywałyby inny bok, i przenumerowuje wycięcia
    function invalidateEntries(entries, prev, next) {
        var obrysBezZmian = _rodzina(prev.shape) === _rodzina(next.shape) && prev.outer === next.outer;
        var poId = {};
        next.cutouts.forEach(function(c, i) { poId[c.id] = { num: i + 1, type: c.type, n: c.n }; });
        var wynik = [];
        (entries || []).forEach(function(e) {
            var m = WYCIECIE_RE.exec(String(e.letter || ''));
            if (!m) {
                if (obrysBezZmian) wynik.push(e);
                return;
            }
            var stare = prev.cutouts[Number(m[1]) - 1];
            var nowe = stare ? poId[stare.id] : null;
            if (!nowe || nowe.type !== stare.type || nowe.n !== stare.n) return;
            wynik.push(Object.assign({}, e, { letter: 'H' + nowe.num + '.' + m[2] + m[3] }));
        });
        return wynik;
    }

    // Definicje krawędzi z długościami (cm): obrys nietypowy (G/D/P) + wycięcia.
    // Prostokąt i koło mają własne litery obrysu (A–H/N, KG/KD) — tu tylko ich wycięcia.
    function edgeDefinitions(shape, sd, thicknessCm) {
        var defs = [];
        var verts = sd && sd.vertices;
        var prosty = (shape === 'rectangular' || shape === 'circle' || shape === 'round');
        if (!prosty && verts && verts.length >= 3) {
            var n = verts.length, i;
            for (i = 0; i < n; i++) {
                defs.push({ id: 'G' + (i + 1), group: 'top', name: 'Góra ' + (i + 1),
                            length_cm: Math.hypot(verts[(i + 1) % n][0] - verts[i][0], verts[(i + 1) % n][1] - verts[i][1]) });
            }
            for (i = 0; i < n; i++) {
                defs.push({ id: 'D' + (i + 1), group: 'bottom', name: 'Dół ' + (i + 1),
                            length_cm: Math.hypot(verts[(i + 1) % n][0] - verts[i][0], verts[(i + 1) % n][1] - verts[i][1]) });
            }
            for (i = 0; i < n; i++) {
                defs.push({ id: 'P' + (i + 1), group: 'vertical', name: 'Pion ' + (i + 1), length_cm: thicknessCm });
            }
        }
        ShapeCutouts.fromShapeData(sd).forEach(function(c, ci) {
            var h = 'H' + (ci + 1) + '.', nazwa = 'Wycięcie ' + (ci + 1) + ', ';
            if (c.type === 'ellipse') {
                var obw = ShapeCutouts.perimeterCm(c);
                defs.push({ id: h + 'G1', group: 'hole_top', name: nazwa + 'obwód góra', length_cm: obw, cutout: ci + 1 });
                defs.push({ id: h + 'D1', group: 'hole_bottom', name: nazwa + 'obwód dół', length_cm: obw, cutout: ci + 1 });
                return;
            }
            var p = c.points, m = p.length, j;
            for (j = 0; j < m; j++) {
                defs.push({ id: h + 'G' + (j + 1), group: 'hole_top', name: nazwa + 'góra ' + (j + 1),
                            length_cm: Math.hypot(p[(j + 1) % m][0] - p[j][0], p[(j + 1) % m][1] - p[j][1]), cutout: ci + 1 });
            }
            for (j = 0; j < m; j++) {
                defs.push({ id: h + 'D' + (j + 1), group: 'hole_bottom', name: nazwa + 'dół ' + (j + 1),
                            length_cm: Math.hypot(p[(j + 1) % m][0] - p[j][0], p[(j + 1) % m][1] - p[j][1]), cutout: ci + 1 });
            }
            for (j = 0; j < m; j++) {
                defs.push({ id: h + 'P' + (j + 1), group: 'hole_vertical', name: nazwa + 'pion ' + (j + 1),
                            length_cm: thicknessCm, cutout: ci + 1 });
            }
        });
        return defs;
    }

    // Tolerancja porównań długości (cm). Długości w zapisanych wpisach mają pełną dokładność,
    // a ta sama krawędź liczona drugi raz (np. bok przesuniętego wycięcia: 30.1 − 20.1) różni się
    // o szum floatów — bez tolerancji każdy ruch przepisywałby krawędzie i przeliczał cenę.
    var EPS_DLUGOSCI_CM = 1e-6;

    function _taSamaDlugosc(a, b) {
        return Math.abs(Number(a) - Number(b)) < EPS_DLUGOSCI_CM;
    }

    // Długości zachowanych wpisów z bieżącej geometrii, z pełną dokładnością (cm i mm). Cenę
    // na żywo liczy backend z tych długości, a zapis z dokładnej geometrii — zaokrąglenie do
    // 0,01 cm dawało różnicę groszy między ekranem a zapisem. Zaokrąglamy tylko do wyświetlania.
    // Długość różna o mniej niż EPS_DLUGOSCI_CM zostaje stara (wpis bez zmian).
    function refreshLengths(entries, shape, sd, dims) {
        var mapa = {};
        edgeDefinitions(shape, sd, dims.thickness).forEach(function(d) { mapa[d.id] = d.length_cm; });
        return (entries || []).map(function(e) {
            var litera = String(e.letter || '');
            var dl = null;
            if (isCornerLetter(litera)) dl = dims.thickness;
            else if (shape === 'rectangular' && LITERY_PROSTOKATA[litera]) dl = dims[LITERY_PROSTOKATA[litera]];
            else if (litera === 'KG' || litera === 'KD') dl = _obwodElipsy(dims.length, dims.width);
            else if (mapa[litera] != null) dl = mapa[litera];
            if (dl == null) return e;
            if (_taSamaDlugosc(e.length_cm, dl) && _taSamaDlugosc(e.length_mm, dl * 10)) return e;
            return Object.assign({}, e, { length_cm: dl, length_mm: dl * 10 });
        });
    }

    // Narożniki prostokąta: v0 lewy dolny, v1 prawy dolny, v2 prawy górny, v3 lewy górny
    // (przód = dolny bok rysunku, jak na izometrii modalu)
    var PROSTOKAT_NAROZNIKI = ['N1', 'N2', 'N4', 'N3'];

    // Litera narożnika w danych krawędzi: prostokąt N1–N4, wielokąt P{i+1},
    // wycięcie n → H{n}.P{j+1} (ringKey wycięcia = jego indeks, od 0)
    function cornerLetter(shape, ringKey, index) {
        if (ringKey === 'outer') return shape === 'rectangular' ? PROSTOKAT_NAROZNIKI[index] : 'P' + (index + 1);
        return 'H' + (ringKey + 1) + '.P' + (index + 1);
    }

    // Odwrotność cornerLetter: {ringKey, index} albo null (to nie litera narożnika tego kształtu).
    // Numeracja liter zaczyna się od 1: `P0` i `H0.P1` nie wskazują żadnego narożnika.
    function parseCornerLetter(shape, letter) {
        var s = String(letter || '');
        var m = /^H(\d+)\.P(\d+)$/.exec(s);
        if (m) {
            return (Number(m[1]) >= 1 && Number(m[2]) >= 1)
                ? { ringKey: Number(m[1]) - 1, index: Number(m[2]) - 1 } : null;
        }
        if (shape === 'rectangular') {
            var i = PROSTOKAT_NAROZNIKI.indexOf(s);
            return i >= 0 ? { ringKey: 'outer', index: i } : null;
        }
        m = /^P(\d+)$/.exec(s);
        return (m && Number(m[1]) >= 1) ? { ringKey: 'outer', index: Number(m[1]) - 1 } : null;
    }

    // Narożniki z danych krawędzi → rysunek (po „Zastosuj” w modalu i po wczytaniu wyceny).
    // Zwraca {changed, clamped}; clamped = wymiar przycięty do geometrii.
    // opcje.onlyIfAny: przenosi tylko wtedy, gdy w krawędziach jest choć jeden narożnik, który
    // da się położyć na rysunku (round/chamfer, r_value ≥ 1, litera pasuje do kształtu).
    // Bez tego pusty zestaw wyzerowałby narożniki zapisane w `shape_data.corners` (nowe
    // wyceny, szkice, kopie bez narożników w krawędziach). „Zastosuj” w modalu woła bez opcji:
    // użytkownik edytował narożniki jawnie, więc ostry róg w modalu ma zdjąć narożnik z rysunku.
    function pullCornersFromEdges(form, opcje) {
        opcje = opcje || {};
        var editor = form && form._shapeEditor;
        var nic = { changed: false, clamped: false };
        if (!editor || typeof editor.applyCorners !== 'function') return nic;
        var shape = editor.getShapeType();
        var sd = editor.getShapeData();
        var nObrysu = (_rodzina(shape) !== 'circle' && sd && sd.vertices) ? sd.vertices.length : 0;
        var spec = { outer: nObrysu ? new Array(nObrysu).fill(null) : null, cutouts: {} };
        ShapeCutouts.fromShapeData(sd).forEach(function(c, ci) {
            if (c.type === 'polygon') spec.cutouts[ci] = new Array(c.points.length).fill(null);
        });
        var jakikolwiek = false;
        _parse(form.dataset.edgesData, []).forEach(function(e) {
            if (!isCornerLetter(e.letter) || (e.type !== 'round' && e.type !== 'chamfer') || !(e.r_value >= 1)) return;
            var gdzie = parseCornerLetter(shape, e.letter);
            if (!gdzie) return;
            var naroznik = { type: e.type, r_mm: Math.round(e.r_value) };
            var lista = gdzie.ringKey === 'outer' ? spec.outer : spec.cutouts[gdzie.ringKey];
            if (lista && gdzie.index < lista.length) {
                lista[gdzie.index] = naroznik;
                jakikolwiek = true;
            }
        });
        if (opcje.onlyIfAny && !jakikolwiek) return nic;
        // Zwykły prostokąt bez rysunku i bez narożników — nie ma czego przenosić
        if (!editor.getCanvas() && !jakikolwiek) return nic;
        return editor.applyCorners(spec);
    }

    // Górny limit pola R w modalu dla narożnika (z geometrii); null = nie narożnik
    function maxForLetter(form, letter, type) {
        var editor = form && form._shapeEditor;
        if (!editor) return null;
        var gdzie = parseCornerLetter(editor.getShapeType(), letter);
        if (!gdzie) return null;
        var canvas = editor.getCanvas();
        if (canvas) return canvas.maxCornerMm(gdzie.ringKey, gdzie.index, type);
        // Zwykły prostokąt bez rysunku: limit z pól wymiarów, sąsiednie rogi ostre
        var sd = editor.getShapeData();
        if (gdzie.ringKey !== 'outer' || !sd || !sd.vertices) return null;
        return ShapeCorners.maxCornerMm(sd.vertices, [], gdzie.index, type);
    }

    // Wpisy krawędzi dla narożników z rysunku (łuk → round, ścięcie → chamfer 45°).
    // Narożnik liczy się za sztukę, więc długość to grubość (jak w modalu dla N/P).
    function cornerEntries(shape, sd, thicknessCm) {
        var wpisy = [];
        function dodaj(letter, c) {
            wpisy.push({
                letter: letter,
                type: c.type,
                r_value: c.r_mm,
                angle_value: c.type === 'chamfer' ? 45 : null,
                // Pełna dokładność jak w refreshLengths (zaokrąglamy tylko do wyświetlania)
                length_cm: thicknessCm,
                length_mm: thicknessCm * 10,
                is_corner: true
            });
        }
        if (_rodzina(shape) !== 'circle' && sd && sd.vertices) {
            ShapeCorners.normalize(sd.corners, sd.vertices.length).forEach(function(c, i) {
                if (c) dodaj(cornerLetter(shape, 'outer', i), c);
            });
        }
        ShapeCutouts.fromShapeData(sd).forEach(function(cut, ci) {
            if (cut.type !== 'polygon') return;
            cut.corners.forEach(function(c, j) { if (c) dodaj(cornerLetter(shape, ci, j), c); });
        });
        return wpisy;
    }

    // Czy dwa wpisy to ta sama krawędź pod względem znaczenia (bez pól cenowych i kolejności kluczy);
    // długości z tolerancją (pełna dokładność, szum floatów)
    function _taSamaKrawedz(a, b) {
        return a.letter === b.letter && a.type === b.type
            && Number(a.r_value) === Number(b.r_value)
            && (a.angle_value || null) === (b.angle_value || null)
            && _taSamaDlugosc(a.length_cm, b.length_cm)
            && _taSamaDlugosc(a.length_mm, b.length_mm)
            && !!a.is_corner === !!b.is_corner;
    }

    // Kanoniczny zapis listy wpisów do porównań „czy coś się zmieniło” — niezależny od kolejności
    function _kanon(lista) {
        return (lista || []).map(function(e) { return JSON.stringify(e); }).sort().join('|');
    }

    // Wołane po każdej zmianie rysunku i po resecie krawędzi (strażnik wymiarów w edges.js).
    // Rysunek jest źródłem prawdy o narożnikach: wpisy N/P/H.P zawsze odtwarzamy z niego.
    // Bez docięcia do wymiaru produkt jest półfabrykatem bez obróbki krawędzi (cut_to_size.js):
    // syncForm nie zapisuje wtedy żadnych wpisów, rysunek zostaje bez zmian. Po powrocie na „Tak”
    // cut_to_size.js woła syncForm i narożniki z rysunku wracają do krawędzi.
    function _bezDociecia(form) {
        return form.dataset.cutToSize === 'false';
    }

    function syncForm(form) {
        var editor = form && form._shapeEditor;
        if (!editor || !window.EdgesModule || typeof window.EdgesModule.setFormEdges !== 'function') return;
        if (_bezDociecia(form)) return;
        var shape = editor.getShapeType();
        var sd = editor.getShapeData();
        var dims = _dims(form);
        var sig = topologySignature(shape, sd);
        var prev = _parse(form.dataset.edgesTopology, null);
        form.dataset.edgesTopology = JSON.stringify(sig);

        var entries = _parse(form.dataset.edgesData, []);
        var mode = form.dataset.edgesMode || 'basic';
        var next = prev ? invalidateEntries(entries, prev, sig) : entries.slice();
        // Identyczny wpis narożnika zostaje (z cenami), żeby brak zmian nie wyglądał na zmianę
        var istniejace = {};
        entries.forEach(function(e) { if (isCornerLetter(e.letter)) istniejace[e.letter] = e; });
        var narozniki = cornerEntries(shape, sd, dims.thickness).map(function(w) {
            var stary = istniejace[w.letter];
            return (stary && _taSamaKrawedz(stary, w)) ? stary : w;
        });
        next = next.filter(function(e) { return !isCornerLetter(e.letter); }).concat(narozniki);
        next = refreshLengths(next, shape, sd, dims);
        // Narożniki o różnych wymiarach to z natury konfiguracja mieszana — tryb zaawansowany
        if (next.some(function(e) { return isCornerLetter(e.letter); })) mode = 'advanced';
        if (_kanon(next) === _kanon(entries) && mode === (form.dataset.edgesMode || 'basic')) return;
        window.EdgesModule.setFormEdges(form, next, mode);
    }

    // Zapamiętuje topologię bez zmiany danych krawędzi (po „Zastosuj” w modalu, po wczytaniu)
    function rememberTopology(form) {
        var editor = form && form._shapeEditor;
        if (!editor) return;
        form.dataset.edgesTopology = JSON.stringify(topologySignature(editor.getShapeType(), editor.getShapeData()));
    }

    // Czy rysunek ma jakikolwiek narożnik — na obrysie albo na wycięciu wielokątnym
    function _rysunekMaNarozniki(sd) {
        if (!sd) return false;
        if (ShapeCorners.hasAny(sd.corners)) return true;
        return ShapeCutouts.fromShapeData(sd).some(function(c) {
            return c.type === 'polygon' && ShapeCorners.hasAny(c.corners);
        });
    }

    // Po wczytaniu wyceny, szkicu albo kopii: uzgodnienie krawędzi z rysunkiem.
    // Narożniki z krawędzi przenosimy na rysunek TYLKO dla danych starego formatu: przywrócony
    // shape_data nie ma żadnego narożnika (ani obrysu, ani wycięć), a krawędzie niosą choć jeden
    // narożnik, który da się położyć (onlyIfAny). Cena krawędzi się nie zmienia (wpisów nie ruszamy,
    // narożniki liczą się za sztukę). Gdy rysunek ma jakikolwiek narożnik, to on jest źródłem
    // prawdy: nic nie przenosimy (inaczej niespójne krawędzie, np. zapisane przed dodaniem narożnika
    // wycięcia, skasowałyby narożniki z rysunku), wpisy dociągnie najbliższa synchronizacja.
    function reconcileAfterRestore(form) {
        var editor = form && form._shapeEditor;
        if (editor && !_rysunekMaNarozniki(editor.getShapeData())) {
            pullCornersFromEdges(form, { onlyIfAny: true });
        }
        rememberTopology(form);
    }

    return {
        isCornerLetter: isCornerLetter,
        cornerLetter: cornerLetter,
        parseCornerLetter: parseCornerLetter,
        pullCornersFromEdges: pullCornersFromEdges,
        maxForLetter: maxForLetter,
        cornerEntries: cornerEntries,
        topologySignature: topologySignature,
        invalidateEntries: invalidateEntries,
        edgeDefinitions: edgeDefinitions,
        refreshLengths: refreshLengths,
        syncForm: syncForm,
        rememberTopology: rememberTopology,
        reconcileAfterRestore: reconcileAfterRestore
    };
})();

window.ShapeEdgesSync = ShapeEdgesSync;
