// shape-tools.js
// Narzędzia edycji Canvy — jak w Illustratorze:
//   V select (całe wycięcia), A direct (punkty), + add, − remove,
//   L ellipse, M rect (wycięcia), N corner (narożniki), R rotate.
// Narzędzie to obiekt z metodami onDown/onMove/onUp/onLeave/onDblClick/onKey/
// renderOverlay/onActivate/onDeactivate/reset (wszystkie opcjonalne).
// onDown/onDblClick/onKey zwracają true, gdy zdarzenie obsłużyły — canvas
// nie zaczyna wtedy przesuwać widoku. inGesture() (opcjonalne) zwraca true, gdy trwa
// gest narzędzia (przeciąganie, obrót) — canvas nie cofa ani nie ponawia wtedy historii
// (api.gestureInProgress()). Zmiany wycięć w trakcie gestu przez _tryCutoutEdit.
// Kontekst `api` daje shape-canvas.js.

var ShapeTools = (function() {
    'use strict';

    var IDS = ['select', 'direct', 'add', 'remove', 'ellipse', 'rect', 'corner', 'rotate'];

    // Tolerancja porównań wymiaru wycięcia. Współrzędne leżą na siatce 0,1 cm, ale odejmowanie
    // floatów daje np. 1.4 − 0.4 = 0.9999999999999999 — bez tolerancji wycięcie równo 1 cm byłoby
    // odrzucane, a przesunięte małe wycięcie „zmniejszałoby się” o ułamek mikrometra.
    var EPS_WYMIARU_CM = 1e-6;

    function _isVertexHit(hit) {
        return (typeof hit === 'number' && hit >= 0) || (hit && typeof hit === 'object' && hit.kind === 'cutout');
    }

    // Szerokość i wysokość obrysu wycięcia (cm)
    function _wymiary(c) {
        var b = ShapeCutouts.bounds(c);
        return { w: b.maxX - b.minX, h: b.maxY - b.minY };
    }

    // Koło wśród elips: półosie różnią się o mniej niż krok siatki półosi, czyli 0,05 cm
    // (ShapeCutouts.roundCoords). Tolerancja 1e-9, bo np. 2.05 − 2.0 = 0.04999999999999982,
    // a taka para to już elipsa 4 × 4,1 cm, nie koło.
    function _jestKolem(c) {
        return c.type === 'ellipse' && Math.abs(c.rx - c.ry) < 0.05 - 1e-9;
    }

    // Odcisk wycięcia do porównań „czy coś się zmieniło”: postać kanoniczna (kolejność pól,
    // normalizacja), więc dwa równe wycięcia dają ten sam napis niezależnie od pochodzenia
    function _odcisk(c) {
        return JSON.stringify(ShapeCutouts.clone([c])[0] || c);
    }

    // Czy wycięcie ci po edycji nadal mieści się w obrysie i nie nachodzi na inne
    function _cutoutValid(api, ci) {
        var S = api.state, c = S.cutouts[ci];
        if (c.type === 'polygon' && ShapeGeometry.ringSelfIntersects(c.points)) return false;
        if (!ShapeCutouts.containedIn(api.outerRing(), c)) return false;
        for (var j = 0; j < S.cutouts.length; j++) {
            if (j !== ci && ShapeCutouts.overlaps(c, S.cutouts[j])) return false;
        }
        return true;
    }

    // Zmiana geometrii wycięcia ci w trakcie gestu (A: punkt; w zadaniu 6 V: przesunięcie
    // i skalowanie). `kandydat` to nowa postać wycięcia — osobna kopia, oryginału nie ruszamy.
    // Wielokąt dostaje narożniki przycięte do nowej geometrii OD STANU Z POCZĄTKU GESTU
    // (`baseCorners`, migawka z onDown): przycięcie nie jest trwałe, póki gest trwa, więc powrót
    // kursora przywraca promień. Walidujemy już z przyciętymi narożnikami — ze starymi łuk mógłby
    // wyjść poza krótszy bok i zafałszować sprawdzenie „mieści się”. Gdy wycięcie nie mieści się
    // w obrysie albo nachodzi na inne, zostaje poprzedni obiekt w całości (punkty i narożniki).
    // Odrzuca też zmniejszenie wycięcia poniżej minimalnego wymiaru (z podpowiedzią).
    // Zwraca true, gdy zmianę przyjęto.
    function _tryCutoutEdit(api, ci, kandydat, baseCorners) {
        var S = api.state, poprzednie = S.cutouts[ci];
        // Minimalny wymiar (ShapeCutouts.MIN_SIZE_CM): odrzucamy, gdy szerokość albo wysokość
        // wyniku jest poniżej minimum I mniejsza niż przed zmianą. Istniejące małe wycięcie
        // (np. ze starej wyceny) da się więc przesunąć i powiększyć, ale nic nie zejdzie
        // poniżej 1 cm. Celowo tutaj, a NIE w _cutoutValid: tamto zasila getInvalidCutouts
        // i blokadę zapisu, a stare wyceny z wycięciem poniżej 1 cm muszą dać się zapisać.
        var min = ShapeCutouts.MIN_SIZE_CM, przed = _wymiary(poprzednie), po = _wymiary(kandydat);
        if ((po.w < min - EPS_WYMIARU_CM && po.w < przed.w - EPS_WYMIARU_CM)
                || (po.h < min - EPS_WYMIARU_CM && po.h < przed.h - EPS_WYMIARU_CM)) {
            api.showHint('Wycięcie musi mieć co najmniej ' + min + ' cm.');
            return false;
        }
        if (kandydat.type === 'polygon') {
            kandydat.corners = ShapeCorners.clampCorners(kandydat.points, baseCorners);
        }
        S.cutouts[ci] = kandydat;
        if (_cutoutValid(api, ci)) return true;
        S.cutouts[ci] = poprzednie;
        return false;
    }

    // Migawka bez typu kształtu. Gest A zamienia prostokąt (trójkąt, trapez…) w wielokąt przy
    // pierwszym realnym ruchu, więc „gest wrócił do startu” porównujemy po samej geometrii.
    function _bezTypu(json) {
        var s = JSON.parse(json);
        delete s.shapeType;
        return JSON.stringify(s);
    }

    // ============================================
    // A — zaznaczanie bezpośrednie (punkty obrysu i wycięć, uchwyt średnicy koła)
    // ============================================
    function _direct(api) {
        var S = api.state;
        // {hit, startCm, downSnap, baseCorners, baseOuterCorners, snapshot, shapeType, undoPushed}
        var drag = null;

        // Wpis historii (migawka z początku gestu) dopiero przy pierwszej realnej zmianie —
        // samo kliknięcie w punkt, nawet z drgnięciem myszy, nie zostawia pustego wpisu
        function zapiszUndoRaz() {
            if (drag.undoPushed) return;
            api.pushUndoSnapshot(drag.snapshot);
            drag.undoPushed = true;
        }

        // Koniec gestu (puszczona mysz, opuszczony canvas, zmiana narzędzia). Gest, który wrócił
        // do startu, zdejmuje swój wpis historii (wzorzec V i N). Gdy po drodze zamienił kształt
        // w wielokąt, przywracamy migawkę startu razem z typem i emitujemy zmianę, żeby edytor
        // wrócił do pól wymiarów i zwykłego zapisu prostokąta.
        function zakoncz() {
            if (!drag) return false;
            var d = drag;
            drag = null;
            S.dragVertex = -1;
            api.canvas.classList.remove('dragging-vertex');
            if (d.undoPushed && _bezTypu(api.snapshot()) === _bezTypu(d.snapshot)) {
                api.popUndo();
                if (S.shapeType !== d.shapeType) {
                    api.restoreSnapshot(d.snapshot);
                    api.emitChange();
                    api.render();
                }
            }
            return true;
        }

        return {
            showsHandles: true,
            onDown: function(p) {
                if (p.button !== 0) return false;
                var hit = api.findVertexAt(p.px, p.py);
                if (!_isVertexHit(hit)) return false;
                var start, baseCorners = null, baseOuterCorners = null;
                if (typeof hit === 'object') {
                    var cw = S.cutouts[hit.ci];
                    start = cw.points[hit.pj];
                    // Narożniki wycięcia z początku gestu — od nich przycinamy w każdym ruchu
                    baseCorners = ShapeCorners.normalize(cw.corners, cw.points.length);
                } else if (S.shapeType === 'circle') {
                    start = [S.params.diameter, S.params.diameter / 2];
                } else {
                    start = S.vertices[hit];
                    // Narożniki obrysu z początku gestu — jak dla wycięć
                    baseOuterCorners = ShapeCorners.normalize(S.corners, S.vertices.length);
                }
                drag = { hit: hit, startCm: [start[0], start[1]],
                         downSnap: [api.snap(p.cm[0]), api.snap(p.cm[1])],
                         baseCorners: baseCorners, baseOuterCorners: baseOuterCorners,
                         snapshot: api.snapshot(), shapeType: S.shapeType, undoPushed: false };
                S.dragVertex = hit;
                api.canvas.classList.add('dragging-vertex');
                return true;
            },
            onMove: function(p) {
                // Bez przeciągania nic nie robimy — podświetlenie punktu pod kursorem
                // robi dyspozytor canvasu, wspólnie dla narzędzi z uchwytami (A, +, −)
                if (!drag) return false;
                var sx = api.snap(p.cm[0]), sy = api.snap(p.cm[1]);
                var stojX = (sx === drag.downSnap[0]), stojY = (sy === drag.downSnap[1]);
                // Shift: ruch tylko w dominującej osi (poniżej 1 cm bez blokady, żeby nie skakało)
                if (p.shift) {
                    var dx = sx - drag.startCm[0], dy = sy - drag.startCm[1];
                    if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) {
                        if (Math.abs(dx) >= Math.abs(dy)) stojY = true;
                        else stojX = true;
                    }
                }
                // Współrzędna, której kursor (po przyciągnięciu do siatki) nie ruszył od miejsca
                // kliknięcia, zostaje dokładnie w punkcie startu: drgnięcie myszy nie przesuwa
                // punktu na siatkę (koło Ø 80,5 nie robi się 81), a powrót kursora wraca do startu
                var x = stojX ? drag.startCm[0] : api.round(sx);
                var y = stojY ? drag.startCm[1] : api.round(sy);
                var hit = drag.hit, zmiana = false;
                if (typeof hit === 'object') {
                    var punkt = S.cutouts[hit.ci].points[hit.pj];
                    if (x !== punkt[0] || y !== punkt[1]) {
                        // Na kopii: odrzucony ruch zostawia wycięcie (punkty i narożniki) bez zmian
                        var kandydat = ShapeCutouts.clone([S.cutouts[hit.ci]])[0];
                        kandydat.points[hit.pj] = [x, y];
                        zmiana = _tryCutoutEdit(api, hit.ci, kandydat, drag.baseCorners);
                    }
                } else if (S.shapeType === 'circle') {
                    var srednica = Math.max(1, x);
                    if (srednica !== S.params.diameter) {
                        S.params.diameter = srednica;
                        zmiana = true;
                    }
                } else if (x !== S.vertices[hit][0] || y !== S.vertices[hit][1]) {
                    // Punkt i narożniki obrysu ustawiamy razem: narożniki przycinane od stanu
                    // z początku gestu, więc powrót kursora przywraca promień (samo przycinanie
                    // w _afterGeometryEdit przy emisji było trwałe). Ruchu punktu obrysu nic nie
                    // odrzuca — wycięcia, które przestały się mieścić, są tylko oznaczane.
                    S.vertices[hit] = [x, y];
                    S.corners = ShapeCorners.clampCorners(S.vertices, drag.baseOuterCorners);
                    // Zamiana na wielokąt dopiero przy realnym przesunięciu, przed emisją
                    api.convertToPolygonIfNeeded();
                    zmiana = true;
                }
                if (zmiana) {
                    zapiszUndoRaz();
                    api.emitChange();
                }
                api.render();
                return true;
            },
            onUp: function() { return zakoncz(); },
            onLeave: function() { zakoncz(); },
            // Gest w toku: canvas nie cofa/ponawia wtedy historii (patrz _gestureInProgress)
            inGesture: function() { return drag !== null; },
            // Zmiana narzędzia w trakcie przeciągania (skrót przy wciśniętej myszy): mouseup
            // trafi już do innego narzędzia, więc gest kończymy tutaj. Inaczej po powrocie
            // do A punkt jechałby za kursorem bez wciśniętego przycisku, a po zmianie kształtu
            // stary indeks mógłby wskazać punkt spoza nowej listy.
            onDeactivate: function() { zakoncz(); },
            // Nowy kształt (setShape): gest jest nieaktualny, historię czyści setShape
            reset: function() { drag = null; S.dragVertex = -1; }
        };
    }

    // ============================================
    // + — dodaj punkt (bok obrysu/wycięcia) albo rysuj wycięcie punkt po punkcie
    // ============================================
    function _add(api) {
        var S = api.state;

        function anuluj() {
            if (!S.activeHole) return;
            S.activeHole = null;
            S.hoverHoleStart = false;
            api.render();
        }

        function zatwierdz() {
            var pts = S.activeHole;
            if (!pts || pts.length < 3) { anuluj(); return; }
            if (ShapeGeometry.ringSelfIntersects(pts)) {
                api.showHint('Wycięcie nie może przecinać samo siebie.');
                return;
            }
            var nowe = ShapeCutouts.normalize({ type: 'polygon', points: pts });
            // Minimalny wymiar wycięcia: szerokość i wysokość obrysu ≥ ShapeCutouts.MIN_SIZE_CM (1 cm),
            // z tolerancją na floaty (równo 1 cm przechodzi także np. od 0,4 do 1,4)
            var wr = _wymiary(nowe);
            if (wr.w < ShapeCutouts.MIN_SIZE_CM - EPS_WYMIARU_CM || wr.h < ShapeCutouts.MIN_SIZE_CM - EPS_WYMIARU_CM) {
                api.showHint('Wycięcie musi mieć co najmniej ' + ShapeCutouts.MIN_SIZE_CM + ' cm.');
                return;
            }
            if (!ShapeCutouts.containedIn(api.outerRing(), nowe)) {
                api.showHint('Wycięcie musi mieścić się wewnątrz kształtu.');
                return;
            }
            for (var i = 0; i < S.cutouts.length; i++) {
                if (ShapeCutouts.overlaps(nowe, S.cutouts[i])) {
                    api.showHint('Wycięcia nie mogą się przecinać.');
                    return;
                }
            }
            api.pushUndo();
            S.cutouts.push(nowe);
            S.activeHole = null;
            S.hoverHoleStart = false;
            api.emitChange();
            api.render();
        }

        function wolneMiejsce(x, y) {
            if (!ShapeGeometry.pointInPolygon(x, y, api.outerRing())) return false;
            return api.findCutoutAt([x, y]) < 0;
        }

        return {
            showsHandles: true,
            onDown: function(p) {
                if (p.button === 2) {
                    if (S.activeHole) {
                        if (S.activeHole.length >= 3) zatwierdz();
                        else anuluj();
                    }
                    return true;
                }
                if (p.button !== 0) return false;

                // 1. Klik w bok obrysu = nowy punkt obrysu (koło nie ma boków)
                if (!S.activeHole && S.shapeType !== 'circle' && S.vertices) {
                    var edgeIdx = api.findEdgeAt(p.px, p.py);
                    if (edgeIdx >= 0 && S.vertices.length < 20) {
                        api.pushUndo();
                        S.vertices.splice(edgeIdx + 1, 0, [api.round(p.cm[0]), api.round(p.cm[1])]);
                        S.corners.splice(edgeIdx + 1, 0, null);
                        api.convertToPolygonIfNeeded();
                        api.emitChange();
                        api.render();
                        return true;
                    }
                }

                // 2. Klik w bok wycięcia wielokątnego = nowy punkt wycięcia
                if (!S.activeHole) {
                    var hEdge = api.findCutoutEdgeAt(p.px, p.py);
                    if (hEdge) {
                        var c = S.cutouts[hEdge.ci];
                        api.pushUndo();
                        c.points.splice(hEdge.edgeIdx + 1, 0, [api.round(p.cm[0]), api.round(p.cm[1])]);
                        c.corners.splice(hEdge.edgeIdx + 1, 0, null);
                        api.emitChange();
                        api.render();
                        return true;
                    }
                }

                // 3. Klik we wnętrzu = start/kontynuacja wycięcia rysowanego punkt po punkcie
                var x = api.round(p.cm[0]), y = api.round(p.cm[1]);
                if (S.activeHole) {
                    var first = api.cmToPixel(S.activeHole[0][0], S.activeHole[0][1]);
                    if (Math.hypot(p.px - first[0], p.py - first[1]) < 12 && S.activeHole.length >= 3) {
                        zatwierdz();
                        return true;
                    }
                    if (wolneMiejsce(x, y)) {
                        S.activeHole.push([x, y]);
                        api.render();
                    }
                    return true;
                }
                // Najpierw klik poza kształtem (albo w wycięcie) = przesuwanie widoku — także przy
                // komplecie wycięć; limit sprawdzamy dopiero przy próbie zaczęcia nowego wycięcia
                if (!wolneMiejsce(x, y)) return false;
                if (S.cutouts.length >= ShapeCutouts.MAX_CUTOUTS) {
                    api.showHint('Maksymalnie ' + ShapeCutouts.MAX_CUTOUTS + ' wycięć na produkt.');
                    return true;
                }
                S.activeHole = [[x, y]];
                api.render();
                return true;
            },
            onMove: function(p) {
                if (!S.activeHole || S.activeHole.length < 3) {
                    if (S.hoverHoleStart) { S.hoverHoleStart = false; api.render(); }
                    return false;
                }
                var first = api.cmToPixel(S.activeHole[0][0], S.activeHole[0][1]);
                var snap = Math.hypot(p.px - first[0], p.py - first[1]) < 12;
                if (snap !== S.hoverHoleStart) { S.hoverHoleStart = snap; api.render(); }
                return false;
            },
            onKey: function(e) {
                if (e.key === 'Enter' && S.activeHole && S.activeHole.length >= 3) { zatwierdz(); return true; }
                if (e.key === 'Escape' && S.activeHole) { anuluj(); return true; }
                return false;
            },
            onDeactivate: anuluj,
            reset: function() { S.activeHole = null; S.hoverHoleStart = false; }
        };
    }

    // ============================================
    // − — usuń punkt (obrys min. 3; wycięcie poniżej 3 punktów znika)
    // ============================================
    function _remove(api) {
        var S = api.state;
        return {
            showsHandles: true,
            onDown: function(p) {
                if (p.button !== 0) return false;
                var hit = api.findVertexAt(p.px, p.py);
                if (hit && typeof hit === 'object') {
                    api.pushUndo();
                    var c = S.cutouts[hit.ci];
                    c.points.splice(hit.pj, 1);
                    c.corners.splice(hit.pj, 1);
                    if (c.points.length < 3) S.cutouts.splice(hit.ci, 1);
                    S.selection = null;
                    api.emitChange();
                    api.render();
                    return true;
                }
                if (typeof hit === 'number' && hit >= 0 && S.shapeType !== 'circle'
                        && S.vertices && S.vertices.length > 3) {
                    api.pushUndo();
                    S.vertices.splice(hit, 1);
                    S.corners.splice(hit, 1);
                    api.convertToPolygonIfNeeded();
                    api.emitChange();
                    api.render();
                    return true;
                }
                return false;
            }
        };
    }

    // ============================================
    // R — obrót całego kształtu (obrys + wycięcia), Shift = co 15°
    // ============================================
    function _rotate(api) {
        var S = api.state;

        // Kończy gest: normalizuje geometrię do początku układu i dolicza kąt.
        // Gdy gest wrócił do delty 0, zdejmuje pusty wpis w historii i przywraca migawkę
        // startu: geometrię bit w bit (obrót o 0° liczony floatami nie musi jej oddać), params
        // i typ kształtu sprzed zamiany na wielokąt. Emisja odświeża edytor — wraca do pól
        // wymiarów prostokąta i jego zwykłego zapisu.
        function zakoncz() {
            var rd = S.rotateDrag;
            if (!rd) return;
            S.rotateDrag = null;
            api.canvas.classList.remove('rotating-shape');
            if (rd.deltaDeg !== 0) {
                api.normalizeAfterRotate();
                S.rotation = ((S.rotation + rd.deltaDeg) % 360 + 360) % 360;
                api.emitChange();
            } else if (rd.undoPushed) {
                api.popUndo();
                api.restoreSnapshot(rd.baseSnapshot);
                api.emitChange();
            }
            api.render();
        }

        return {
            onDown: function(p) {
                if (p.button !== 0 || S.shapeType === 'circle') return false;
                if (!S.vertices || S.vertices.length < 3) return false;
                var hit = api.findVertexAt(p.px, p.py);
                var wSrodku = ShapeGeometry.pointInPolygon(p.cm[0], p.cm[1], S.vertices);
                if (!_isVertexHit(hit) && !wSrodku) return false;   // poza kształtem: widok
                var b = api.outerBounds();
                // Środek obrotu liczony RAZ — formatka zmienia się w trakcie, co dawałoby dryf
                var pivot = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
                S.rotateDrag = {
                    pivot: pivot,
                    startAngle: Math.atan2(p.cm[1] - pivot[1], p.cm[0] - pivot[0]),
                    baseVerts: S.vertices.map(function(v) { return [v[0], v[1]]; }),
                    baseCutouts: ShapeCutouts.clone(S.cutouts),
                    baseSnapshot: api.snapshot(),
                    deltaDeg: 0,
                    undoPushed: false,
                    cursorPx: [p.px, p.py]
                };
                api.canvas.classList.add('rotating-shape');
                return true;
            },
            onMove: function(p) {
                var rd = S.rotateDrag;
                if (!rd) return false;
                var katTeraz = Math.atan2(p.cm[1] - rd.pivot[1], p.cm[0] - rd.pivot[0]);
                var delta = Math.round((katTeraz - rd.startAngle) * 180 / Math.PI);
                if (p.shift) delta = Math.round(delta / 15) * 15;
                // Undo i zamiana na wielokąt przy PIERWSZYM realnym ruchu, nie na kliknięciu.
                // Zamiana przed emisją: extractParams trapezu na obróconej geometrii wpisałby bzdury.
                if (delta !== 0 && !rd.undoPushed) {
                    api.convertToPolygonIfNeeded();
                    api.pushUndoSnapshot(rd.baseSnapshot);
                    rd.undoPushed = true;
                }
                rd.deltaDeg = delta;
                rd.cursorPx = [p.px, p.py];
                S.vertices = ShapeGeometry.rotateRing(rd.baseVerts, delta, rd.pivot);
                S.cutouts = rd.baseCutouts.map(function(c) { return ShapeCutouts.rotate(c, delta, rd.pivot); });
                api.emitChange();
                api.render();
                return true;
            },
            onUp: function() {
                if (!S.rotateDrag) return false;
                zakoncz();
                return true;
            },
            onLeave: zakoncz,
            // Gest w toku: canvas nie cofa/ponawia wtedy historii (migawka obrotu by się rozjechała)
            inGesture: function() { return !!S.rotateDrag; },
            onDeactivate: zakoncz,
            reset: function() { S.rotateDrag = null; api.canvas.classList.remove('rotating-shape'); },
            // Krzyżyk środka obrotu + dymek z ŁĄCZNYM kątem (ta wartość trafia do wyceny)
            renderOverlay: function() {
                var rd = S.rotateDrag;
                if (!rd) return;
                var ctx = api.ctx(), theme = api.theme();
                var pv = api.cmToPixel(rd.pivot[0], rd.pivot[1]);
                ctx.save();
                ctx.strokeStyle = theme.shapeStroke;
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(pv[0] - 7, pv[1]); ctx.lineTo(pv[0] + 7, pv[1]);
                ctx.moveTo(pv[0], pv[1] - 7); ctx.lineTo(pv[0], pv[1] + 7);
                ctx.stroke();
                ctx.beginPath();
                ctx.arc(pv[0], pv[1], 4, 0, Math.PI * 2);
                ctx.stroke();
                var lacznie = ((S.rotation + rd.deltaDeg) % 360 + 360) % 360;
                _dymek(api, rd.cursorPx, lacznie + '°');
                ctx.restore();
            }
        };
    }

    // ============================================
    // V — zaznaczanie całych wycięć: przesuwanie, ramka z uchwytami, odległości
    // ============================================
    function _select(api) {
        var S = api.state;
        var gest = null;     // {kind:'move'|'resize', index, base, b0, startCm, handle, snapshot, undoPushed}
        var seriaKlawisza = null;    // klawisz trzymanej strzałki, której wpis historii już zrobiono
        var etykiety = [];   // trafienia dwukliku: [{x, y, kind, value}]
        var UCHWYT_PX = 5;
        var NIEBIESKI = '#4a9eff';   // kolor zaznaczenia jak w Illustratorze
        var KOMUNIKAT_NIE_MIESCI = 'Wycięcie musi mieścić się wewnątrz kształtu i nie nachodzić na inne.';
        // 8 uchwytów: rogi (0-3) i środki boków (4-7) jako ułamki ramki [fx, fy] (oś Y w górę)
        var UCHWYTY = [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]];

        function zaznaczone() {
            var sel = S.selection;
            return (sel && sel.kind === 'cutout' && S.cutouts[sel.index]) ? S.cutouts[sel.index] : null;
        }

        // Elipsa (nie koło) obrócona razem z kształtem: bez uchwytów i bez zmiany rozmiaru,
        // tylko przesuwanie — ramka osiowa nie opisuje jej półosi. Obrót koła nic nie zmienia.
        function mozeSkalowac(c) {
            if (c.type !== 'ellipse' || _jestKolem(c)) return true;
            return (((c.angle || 0) % 360) + 360) % 360 === 0;
        }

        function pozycjeUchwytow(b) {
            return UCHWYTY.map(function(f) {
                return api.cmToPixel(b.minX + (b.maxX - b.minX) * f[0], b.minY + (b.maxY - b.minY) * f[1]);
            });
        }

        function trafionyUchwyt(p, c) {
            if (!mozeSkalowac(c)) return -1;
            var pts = pozycjeUchwytow(ShapeCutouts.bounds(c));
            for (var i = 0; i < pts.length; i++) {
                if (Math.abs(p.px - pts[i][0]) <= UCHWYT_PX + 3 && Math.abs(p.py - pts[i][1]) <= UCHWYT_PX + 3) return i;
            }
            return -1;
        }

        // Etykieta odległości/wymiaru pod kursorem (z ostatniego rysowania nakładki) albo null.
        // Najbliższa, nie pierwsza z listy: odsunięta etykieta rozmiaru leży ok. 20 px od sąsiedniej
        // etykiety odległości, a promień trafienia to 22 px — klik w środek ma trafić w tę, którą widać.
        function trafionaEtykieta(p) {
            var wynik = null, najblizej = 22;
            for (var i = 0; i < etykiety.length; i++) {
                var odl = Math.hypot(p.px - etykiety[i].x, p.py - etykiety[i].y);
                if (odl < najblizej) { najblizej = odl; wynik = etykiety[i]; }
            }
            return wynik;
        }

        // Zmiana wycięcia w trakcie gestu (przesuwanie, uchwyt). Walidacja, minimum 1 cm i narożniki
        // robi wspólne _tryCutoutEdit; narożniki wielokąta przycinane od migawki z początku
        // gestu (gest.base.corners — przycinanie jej nie modyfikuje). Bez podpowiedzi
        // przy odrzuceniu: wycięcie po prostu zatrzymuje się na ostatniej poprawnej pozycji.
        // Zwraca true tylko, gdy wycięcie REALNIE się zmieniło: przyjęty kandydat identyczny z bieżącym
        // wycięciem (drgnięcie myszy przy kliknięciu, delta po siatce = 0) nie jest zmianą, więc nie
        // ma być wpisu w historii ani emitChange (przeliczanie cen, kopia robocza).
        function sprobujWGescie(kandydat) {
            var przed = _odcisk(S.cutouts[gest.index]);
            if (!_tryCutoutEdit(api, gest.index, ShapeCutouts.roundCoords(kandydat), gest.base.corners || null)) return false;
            return _odcisk(S.cutouts[gest.index]) !== przed;
        }

        // Pojedyncza zmiana poza gestem (strzałka, wpisana wartość): migawką narożników jest
        // stan wycięcia sprzed zmiany. Odrzucenie zawsze dostaje podpowiedź — _tryCutoutEdit
        // sam pokazuje tylko komunikat o minimalnym wymiarze, więc ogólny dokładamy tu,
        // o ile tamten się nie pojawił (inaczej nadpisałby właściwy). Zwraca true tylko przy realnej
        // zmianie: wpisanie tej samej wartości w dwukliku nie jest zmianą (bez wpisu historii i emitChange).
        function sprobujKrok(index, kandydat) {
            var c = S.cutouts[index];
            var przed = _odcisk(c);
            var narozniki = c.type === 'polygon' ? ShapeCorners.normalize(c.corners, c.points.length) : null;
            var pokazano = false;
            var apiZPodpowiedzia = Object.create(api);
            apiZPodpowiedzia.showHint = function(tekst) { pokazano = true; api.showHint(tekst); };
            if (_tryCutoutEdit(apiZPodpowiedzia, index, ShapeCutouts.roundCoords(kandydat), narozniki)) {
                return _odcisk(S.cutouts[index]) !== przed;
            }
            if (!pokazano) api.showHint(KOMUNIKAT_NIE_MIESCI);
            return false;
        }

        // Nowa ramka przy przeciąganiu uchwytu h; Shift = proporcje, Alt = od środka
        function nowaRamka(b0, h, cm, shift, alt) {
            var f = UCHWYTY[h];
            var cx = (b0.minX + b0.maxX) / 2, cy = (b0.minY + b0.maxY) / 2;
            var w0 = b0.maxX - b0.minX, h0 = b0.maxY - b0.minY;
            var x = api.snap(cm[0]), y = api.snap(cm[1]);
            var w = w0, hh = h0;
            if (f[0] === 0) w = alt ? 2 * Math.abs(cx - x) : b0.maxX - x;
            else if (f[0] === 1) w = alt ? 2 * Math.abs(x - cx) : x - b0.minX;
            if (f[1] === 0) hh = alt ? 2 * Math.abs(cy - y) : b0.maxY - y;
            else if (f[1] === 1) hh = alt ? 2 * Math.abs(y - cy) : y - b0.minY;
            w = Math.max(ShapeCutouts.MIN_SIZE_CM, w);
            hh = Math.max(ShapeCutouts.MIN_SIZE_CM, hh);
            if (shift && w0 > 0 && h0 > 0) {
                // Proporcje: wiodący jest wymiar, który zmienił się bardziej (też przy zmniejszaniu
                // i na uchwycie środkowym, gdzie drugi wymiar nie zmienia się wcale), a skala
                // nie schodzi poniżej minimum żadnego z wymiarów
                var rw = w / w0, rh = hh / h0;
                var sk = Math.abs(rw - 1) >= Math.abs(rh - 1) ? rw : rh;
                sk = Math.max(sk, ShapeCutouts.MIN_SIZE_CM / w0, ShapeCutouts.MIN_SIZE_CM / h0);
                w = w0 * sk;
                hh = h0 * sk;
            }
            // Zakotwiczenie: przeciwny bok, a przy Alt albo uchwycie środkowym — środek
            var nb = {};
            if (alt || f[0] === 0.5) { nb.minX = cx - w / 2; nb.maxX = cx + w / 2; }
            else if (f[0] === 0) { nb.maxX = b0.maxX; nb.minX = b0.maxX - w; }
            else { nb.minX = b0.minX; nb.maxX = b0.minX + w; }
            if (alt || f[1] === 0.5) { nb.minY = cy - hh / 2; nb.maxY = cy + hh / 2; }
            else if (f[1] === 0) { nb.maxY = b0.maxY; nb.minY = b0.maxY - hh; }
            else { nb.minY = b0.minY; nb.maxY = b0.minY + hh; }
            return nb;
        }

        function zapiszUndoRaz() {
            if (gest && !gest.undoPushed) {
                api.pushUndoSnapshot(gest.snapshot);
                gest.undoPushed = true;
            }
        }

        // Prostokąt etykiety o środku (x, y) — ten sam, który rysuje etykieta()
        function ramkaEtykiety(ctx, tekst, x, y) {
            var szer = ctx.measureText(tekst).width + 8;
            return { x0: x - szer / 2, x1: x + szer / 2, y0: y - 9, y1: y + 9 };
        }

        function ramkiNachodza(a, b) {
            return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
        }

        function etykieta(ctx, tekst, x, y) {
            var r = ramkaEtykiety(ctx, tekst, x, y);
            ctx.fillStyle = 'rgba(26, 26, 46, 0.9)';
            ctx.fillRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
            ctx.fillStyle = NIEBIESKI;
            ctx.fillText(tekst, x, y);
        }

        // Odsuwa etykietę rozmiaru dalej na zewnątrz (pion: w górę, poziom: w prawo), dopóki
        // nachodzi na etykietę już rozłożoną. Gdy wycięcie jest blisko boku formatki, etykieta
        // odległości ląduje tuż przy etykiecie szerokości/wysokości.
        function odsunEtykiete(ctx, e, zajete, pionowo) {
            for (var licznik = 0; licznik < zajete.length + 1; licznik++) {
                var r = ramkaEtykiety(ctx, e.tekst, e.x, e.y), kolizja = null;
                for (var i = 0; i < zajete.length; i++) {
                    if (ramkiNachodza(r, zajete[i])) { kolizja = zajete[i]; break; }
                }
                if (!kolizja) return;
                if (pionowo) e.y = kolizja.y0 - 2 - 9;                 // tuż nad zajętą etykietą
                else e.x = kolizja.x1 + 2 + (r.x1 - r.x0) / 2;          // tuż na prawo od niej
            }
        }

        // Odległości ramki wycięcia od boków formatki + szerokość/wysokość (dwuklik = wpisz)
        function rysujOdleglosci(b, c) {
            var f = api.outerBounds();
            if (!f) return;
            var ctx = api.ctx();
            var cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
            var odcinki = [
                { kind: 'left', a: [f.minX, cy], z: [b.minX, cy], v: b.minX - f.minX },
                { kind: 'right', a: [b.maxX, cy], z: [f.maxX, cy], v: f.maxX - b.maxX },
                { kind: 'bottom', a: [cx, f.minY], z: [cx, b.minY], v: b.minY - f.minY },
                { kind: 'top', a: [cx, b.maxY], z: [cx, f.maxY], v: f.maxY - b.maxY }
            ];
            ctx.save();
            ctx.strokeStyle = NIEBIESKI;
            ctx.lineWidth = 1;
            ctx.font = 'bold 12px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            var napisy = [];   // etykiety do narysowania: {tekst, x, y, kind, value}
            odcinki.forEach(function(o) {
                if (o.v < 0.05) return;
                var pa = api.cmToPixel(o.a[0], o.a[1]), pz = api.cmToPixel(o.z[0], o.z[1]);
                ctx.setLineDash([3, 3]);
                ctx.beginPath();
                ctx.moveTo(pa[0], pa[1]);
                ctx.lineTo(pz[0], pz[1]);
                ctx.stroke();
                ctx.setLineDash([]);
                napisy.push({ tekst: (Math.round(o.v * 10) / 10) + ' cm',
                              x: (pa[0] + pz[0]) / 2, y: (pa[1] + pz[1]) / 2, kind: o.kind, value: o.v });
            });
            var pGora = api.cmToPixel(cx, b.maxY), pPrawo = api.cmToPixel(b.maxX, cy);
            var w = b.maxX - b.minX, h = b.maxY - b.minY;
            // Etykiety rozmiaru układamy po odległościach, żeby nie leżały jedna na drugiej
            var zajete = napisy.map(function(e) { return ramkaEtykiety(ctx, e.tekst, e.x, e.y); });
            var rozmiary = _jestKolem(c)
                ? [{ tekst: 'Ø ' + (Math.round(w * 10) / 10) + ' cm', x: pGora[0], y: pGora[1] - 16, kind: 'diameter', value: w, pionowo: true }]
                : [{ tekst: (Math.round(w * 10) / 10) + ' cm', x: pGora[0], y: pGora[1] - 16, kind: 'width', value: w, pionowo: true },
                   { tekst: (Math.round(h * 10) / 10) + ' cm', x: pPrawo[0] + 32, y: pPrawo[1], kind: 'height', value: h, pionowo: false }];
            rozmiary.forEach(function(e) {
                odsunEtykiete(ctx, e, zajete, e.pionowo);
                zajete.push(ramkaEtykiety(ctx, e.tekst, e.x, e.y));
                napisy.push(e);
            });
            // Pozycje w `etykiety` to dokładnie to, co widać (trafionaEtykieta trafia w narysowane)
            napisy.forEach(function(e) {
                etykieta(ctx, e.tekst, e.x, e.y);
                etykiety.push({ x: e.x, y: e.y, kind: e.kind, value: e.value });
            });
            ctx.restore();
        }

        // Koniec gestu (puszczona mysz, opuszczony canvas, zmiana narzędzia). Gest, który wrócił do
        // punktu startu (wycięcie przesunięte i cofnięte kursorem), zostawiłby pusty wpis historii —
        // zdejmujemy go jak _rotate przy powrocie do delty 0.
        function zakonczGest() {
            if (!gest) return false;
            if (gest.undoPushed && api.snapshot() === gest.snapshot) api.popUndo();
            gest = null;
            api.canvas.classList.remove('dragging-vertex');
            return true;
        }

        // Kursor ustawiany przy najechaniu (move, strzałki zmiany rozmiaru) nie może przeżyć V:
        // inline style wygrywa z klasą narzędzia, więc zasłoniłby celownik L/M i zostałby w A
        function wyczyscKursor() { api.canvas.style.cursor = ''; }

        return {
            // Zmiana narzędzia w trakcie przeciągania (skrót przy wciśniętej myszy) kończy gest,
            // a zaznaczenie nie przechodzi na inne narzędzie (jego ramki by nie było widać)
            onDeactivate: function() { zakonczGest(); etykiety = []; seriaKlawisza = null; S.selection = null; wyczyscKursor(); },
            // Nowy kształt (setShape): stary gest i zaznaczenie są nieaktualne (historię czyści setShape)
            reset: function() { gest = null; etykiety = []; seriaKlawisza = null; S.selection = null; wyczyscKursor(); },
            // Gest w toku: canvas nie cofa/ponawia wtedy historii (api.gestureInProgress)
            inGesture: function() { return gest !== null; },
            onDown: function(p) {
                if (p.button !== 0) return false;
                seriaKlawisza = null;
                var c = zaznaczone();
                if (c) {
                    var h = trafionyUchwyt(p, c);
                    if (h >= 0) {
                        var baza = ShapeCutouts.clone([c])[0];
                        // Koło obrócone razem z kształtem: obrót nic nie zmienia, a ramka osiowa
                        // przestałaby opisywać elipsę po zmianie proporcji — zerujemy kąt
                        if (_jestKolem(baza)) baza.angle = 0;
                        gest = { kind: 'resize', index: S.selection.index, base: baza,
                                 b0: ShapeCutouts.bounds(baza), handle: h, snapshot: api.snapshot(), undoPushed: false };
                        return true;
                    }
                }
                var ci = api.findCutoutAt(p.cm);
                if (ci >= 0) {
                    S.selection = { kind: 'cutout', index: ci };
                    gest = { kind: 'move', index: ci, base: ShapeCutouts.clone([S.cutouts[ci]])[0],
                             startCm: [p.cm[0], p.cm[1]], snapshot: api.snapshot(), undoPushed: false };
                    api.canvas.classList.add('dragging-vertex');
                    api.render();
                    return true;
                }
                // Klik w etykietę odległości (poza wycięciami) to pierwsza połowa dwukliku: zaznaczenie
                // zostaje, inaczej etykiety zniknęłyby razem z nim, zanim przyjdzie dblclick
                if (c && trafionaEtykieta(p)) return true;
                // Obrys tylko zaznaczamy (bez ruchu), tło odznacza; przeciąganie przesuwa widok
                var wObrysie = ShapeGeometry.pointInPolygon(p.cm[0], p.cm[1], api.outerRing());
                S.selection = wObrysie ? { kind: 'outer' } : null;
                api.render();
                return false;
            },
            onMove: function(p) {
                if (!gest) {
                    var c = zaznaczone();
                    var h = c ? trafionyUchwyt(p, c) : -1;
                    var kursor = '';
                    if (h >= 0 && h < 4) kursor = (h % 2 === 0) ? 'nesw-resize' : 'nwse-resize';
                    else if (h >= 4) kursor = (h % 2 === 0) ? 'ns-resize' : 'ew-resize';
                    else if (api.findCutoutAt(p.cm) >= 0) kursor = 'move';
                    api.canvas.style.cursor = kursor;
                    return false;
                }
                if (gest.kind === 'move') {
                    var dx = api.snap(p.cm[0] - gest.startCm[0]);
                    var dy = api.snap(p.cm[1] - gest.startCm[1]);
                    if (p.shift) { if (Math.abs(dx) >= Math.abs(dy)) dy = 0; else dx = 0; }
                    if (sprobujWGescie(ShapeCutouts.translate(gest.base, dx, dy))) {
                        zapiszUndoRaz();
                        api.emitChange();
                    }
                } else {
                    var nb = nowaRamka(gest.b0, gest.handle, p.cm, p.shift, p.alt);
                    if (sprobujWGescie(ShapeCutouts.scaleToBounds(gest.base, nb))) {
                        zapiszUndoRaz();
                        api.emitChange();
                    }
                }
                api.render();
                return true;
            },
            onUp: function() { return zakonczGest(); },
            onLeave: function() { this.onUp(); },
            onKey: function(e) {
                // Ctrl/Meta/Alt to skróty przeglądarki i canvasu (Alt+← i Cmd+← to „wstecz”, Ctrl+Z to cofanie)
                if (e.ctrlKey || e.metaKey || e.altKey) return false;
                // W trakcie przeciągania klawisze nie ruszają wycięcia: gest trzyma jego indeks,
                // a usunięcie czy przesunięcie spod ręki rozjechałoby migawkę i bazę gestu
                if (gest) {
                    return e.key === 'Escape' || e.key === 'Delete' || e.key === 'Backspace'
                        || e.key.indexOf('Arrow') === 0;
                }
                if (e.key === 'Escape') {
                    if (!S.selection) return false;   // nic nie zaznaczone — Esc zamknie pełny ekran
                    S.selection = null;
                    api.render();
                    return true;
                }
                var c = zaznaczone();
                if (!c) return false;   // zaznaczony obrys jest tylko podświetlony — Delete nic nie robi
                var idx = S.selection.index;
                if (e.key === 'Delete' || e.key === 'Backspace') {
                    api.pushUndo();
                    S.cutouts.splice(idx, 1);
                    S.selection = null;
                    api.emitChange();
                    api.render();
                    return true;
                }
                var krok = e.shiftKey ? 1 : 0.1;
                var d = { ArrowLeft: [-krok, 0], ArrowRight: [krok, 0], ArrowUp: [0, krok], ArrowDown: [0, -krok] }[e.key];
                if (!d) return false;
                // Trzymana strzałka (e.repeat) to jedna seria: wpis historii tylko przy pierwszym
                // naciśnięciu, kolejne powtórzenia tego samego klawisza zmieniają samą geometrię.
                // Jedno Ctrl+Z cofa całą serię.
                if (!e.repeat) seriaKlawisza = null;
                var snap = api.snapshot();
                if (sprobujKrok(idx, ShapeCutouts.translate(c, d[0], d[1]))) {
                    if (!(e.repeat && seriaKlawisza === e.key)) api.pushUndoSnapshot(snap);
                    seriaKlawisza = e.key;
                    api.emitChange();
                }
                api.render();
                return true;
            },
            onDblClick: function(p) {
                var c = zaznaczone();
                if (!c) return false;
                var hit = trafionaEtykieta(p);
                if (!hit) return false;
                var idx = S.selection.index;
                api.openInlineInput(hit.x, hit.y, Math.round(hit.value * 10) / 10, function(v) {
                    var akt = S.cutouts[idx];
                    if (!akt) return;
                    var b = ShapeCutouts.bounds(akt), f = api.outerBounds();
                    var kandydat;
                    if (hit.kind === 'left') kandydat = ShapeCutouts.translate(akt, (f.minX + v) - b.minX, 0);
                    else if (hit.kind === 'right') kandydat = ShapeCutouts.translate(akt, (f.maxX - v) - b.maxX, 0);
                    else if (hit.kind === 'bottom') kandydat = ShapeCutouts.translate(akt, 0, (f.minY + v) - b.minY);
                    else if (hit.kind === 'top') kandydat = ShapeCutouts.translate(akt, 0, (f.maxY - v) - b.maxY);
                    else {
                        if (!(v >= ShapeCutouts.MIN_SIZE_CM)) {
                            api.showHint('Wycięcie musi mieć co najmniej ' + ShapeCutouts.MIN_SIZE_CM + ' cm.');
                            return;
                        }
                        if (!mozeSkalowac(akt)) return;
                        var cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
                        var nw = hit.kind === 'height' ? (b.maxX - b.minX) : v;
                        var nh = hit.kind === 'width' ? (b.maxY - b.minY) : v;
                        kandydat = ShapeCutouts.scaleToBounds(akt, { minX: cx - nw / 2, maxX: cx + nw / 2, minY: cy - nh / 2, maxY: cy + nh / 2 });
                    }
                    var snap = api.snapshot();
                    if (sprobujKrok(idx, kandydat)) {
                        api.pushUndoSnapshot(snap);
                        api.emitChange();
                    }
                    api.render();
                }, { min: 0 });
                return true;
            },
            renderOverlay: function() {
                etykiety = [];
                var sel = S.selection;
                if (!sel) return;
                var ctx = api.ctx();
                if (sel.kind === 'outer') {
                    // Zaznaczony obrys — jasna przerywana obwódka (bez uchwytów)
                    var ring = api.outerRing();
                    if (ring.length < 3) return;
                    ctx.save();
                    ctx.strokeStyle = NIEBIESKI;
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 3]);
                    ctx.beginPath();
                    ring.forEach(function(pt, i) {
                        var q = api.cmToPixel(pt[0], pt[1]);
                        if (i === 0) ctx.moveTo(q[0], q[1]); else ctx.lineTo(q[0], q[1]);
                    });
                    ctx.closePath();
                    ctx.stroke();
                    ctx.restore();
                    return;
                }
                var c = zaznaczone();
                if (!c) return;
                var b = ShapeCutouts.bounds(c);
                var lg = api.cmToPixel(b.minX, b.maxY), pd = api.cmToPixel(b.maxX, b.minY);
                ctx.save();
                ctx.strokeStyle = NIEBIESKI;
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 3]);
                ctx.strokeRect(lg[0], lg[1], pd[0] - lg[0], pd[1] - lg[1]);
                ctx.setLineDash([]);
                if (mozeSkalowac(c)) {
                    pozycjeUchwytow(b).forEach(function(q) {
                        ctx.fillStyle = '#fff';
                        ctx.fillRect(q[0] - UCHWYT_PX, q[1] - UCHWYT_PX, UCHWYT_PX * 2, UCHWYT_PX * 2);
                        ctx.strokeRect(q[0] - UCHWYT_PX, q[1] - UCHWYT_PX, UCHWYT_PX * 2, UCHWYT_PX * 2);
                    });
                }
                ctx.restore();
                rysujOdleglosci(b, c);
            }
        };
    }

    // ============================================
    // L / M — wycięcie eliptyczne / prostokątne rysowane przeciągnięciem.
    // Shift = koło/kwadrat, Alt = od punktu kliknięcia jako środka (jak w Illustratorze).
    // `nakladkaZaznaczenia` to renderOverlay narzędzia V: po narysowaniu nowe wycięcie jest
    // zaznaczone i widać jego odległości od boków, tak jak po zaznaczeniu w V.
    // `klawiszeZaznaczenia` to onKey narzędzia V: gdy nic nie rysujemy, zaznaczone wycięcie
    // reaguje na Delete/Backspace, Esc i strzałki dokładnie jak w V.
    // ============================================
    function _shapeDraw(api, rodzaj, nakladkaZaznaczenia, klawiszeZaznaczenia) {
        var S = api.state;
        var rys = null;   // {start:[x,y], end:[x,y], shift, alt, cursorPx}

        function ramka() {
            var x0 = rys.start[0], y0 = rys.start[1];
            var dx = rys.end[0] - x0, dy = rys.end[1] - y0;
            if (rys.shift) {
                // Koło/kwadrat: bok = dłuższy wymiar, kierunek zgodny z ruchem kursora
                var m = Math.max(Math.abs(dx), Math.abs(dy));
                dx = (dx < 0 ? -1 : 1) * m;
                dy = (dy < 0 ? -1 : 1) * m;
            }
            if (rys.alt) {
                // Od środka: punkt kliknięcia jest środkiem, kursor wyznacza półosie
                return { minX: x0 - Math.abs(dx), maxX: x0 + Math.abs(dx), minY: y0 - Math.abs(dy), maxY: y0 + Math.abs(dy) };
            }
            return { minX: Math.min(x0, x0 + dx), maxX: Math.max(x0, x0 + dx),
                     minY: Math.min(y0, y0 + dy), maxY: Math.max(y0, y0 + dy) };
        }

        // Kształt wycięcia wpisany w ramkę b (cm); bez zaokrąglenia
        function kandydat(b) {
            return rodzaj === 'ellipse'
                ? ShapeCutouts.makeEllipse(b.minX, b.minY, b.maxX, b.maxY)
                : ShapeCutouts.makeRect(b.minX, b.minY, b.maxX, b.maxY);
        }

        function anuluj() {
            if (!rys) return;
            rys = null;
            api.render();
        }

        return {
            // Jak w V: zmiana narzędzia w trakcie przeciągania (skrót przy wciśniętej myszy) kończy
            // gest, a zaznaczenie nie przechodzi na inne narzędzie — jego ramki nie byłoby widać
            // (nakładkę zaznaczenia rysują tylko V, L i M), a indeks mógłby po czasie wskazać
            // inne wycięcie (np. po usunięciu któregoś w „−”).
            onDeactivate: function() { rys = null; S.selection = null; },
            // Nowy kształt (setShape): stary gest i zaznaczenie są nieaktualne
            reset: function() { rys = null; S.selection = null; },
            // Gest w toku: canvas nie cofa/ponawia wtedy historii (api.gestureInProgress)
            inGesture: function() { return rys !== null; },
            onDown: function(p) {
                if (p.button !== 0) return false;
                var x = api.snap(p.cm[0]), y = api.snap(p.cm[1]);
                // Poza kształtem albo na istniejącym wycięciu — przesuwanie widoku
                if (!ShapeGeometry.pointInPolygon(x, y, api.outerRing()) || api.findCutoutAt([x, y]) >= 0) return false;
                if (S.cutouts.length >= ShapeCutouts.MAX_CUTOUTS) {
                    api.showHint('Maksymalnie ' + ShapeCutouts.MAX_CUTOUTS + ' wycięć na produkt.');
                    return true;
                }
                rys = { start: [x, y], end: [x, y], shift: p.shift, alt: p.alt, cursorPx: [p.px, p.py] };
                return true;
            },
            onMove: function(p) {
                if (!rys) return false;
                rys.end = [api.snap(p.cm[0]), api.snap(p.cm[1])];
                rys.shift = p.shift;
                rys.alt = p.alt;
                rys.cursorPx = [p.px, p.py];
                api.render();
                return true;
            },
            onUp: function() {
                if (!rys) return false;
                var b = ramka();
                rys = null;
                // Zwykłe kliknięcie albo przeciągnięcie po linii: ramka bez szerokości lub wysokości.
                // Nic nie tworzymy, bez komunikatu. Sprawdzamy to PRZED zaokrągleniem — roundCoords
                // kopiuje wycięcie przez ShapeCutouts.clone, a ten odrzuca elipsę o półosi 0
                // (wynik undefined i wyjątek w obsłudze mouseup).
                if (!(b.maxX > b.minX) || !(b.maxY > b.minY)) {
                    api.render();
                    return true;
                }
                // Dalej liczymy na wyniku zaokrąglenia do 0,1 cm — taki obiekt trafia do stanu
                var nowe = ShapeCutouts.roundCoords(kandydat(b));
                // Za małe — nic nie tworzymy, bez komunikatu. Minimum 1 cm z tolerancją na floaty,
                // jak w „+”: np. 21.4 − 20.4 = 0.99999…, a to równo 1 cm
                var wr = _wymiary(nowe);
                if (wr.w < ShapeCutouts.MIN_SIZE_CM - EPS_WYMIARU_CM || wr.h < ShapeCutouts.MIN_SIZE_CM - EPS_WYMIARU_CM) {
                    api.render();
                    return true;
                }
                if (!ShapeCutouts.containedIn(api.outerRing(), nowe)) {
                    api.showHint('Wycięcie musi mieścić się wewnątrz kształtu.');
                    api.render();
                    return true;
                }
                for (var i = 0; i < S.cutouts.length; i++) {
                    if (ShapeCutouts.overlaps(nowe, S.cutouts[i])) {
                        api.showHint('Wycięcia nie mogą się przecinać.');
                        api.render();
                        return true;
                    }
                }
                api.pushUndo();
                S.cutouts.push(nowe);
                // Nowe wycięcie od razu zaznaczone — widać jego odległości od boków
                S.selection = { kind: 'cutout', index: S.cutouts.length - 1 };
                api.emitChange();
                api.render();
                return true;
            },
            onLeave: anuluj,
            onKey: function(e) {
                // W trakcie rysowania obsługujemy tylko Esc (anuluj); reszta bez zmian
                if (rys) {
                    if (e.key === 'Escape') { anuluj(); return true; }
                    return false;
                }
                // Po narysowaniu wycięcie jest zaznaczone (nakładka V): klawisze jak w V — Delete usuwa,
                // Esc odznacza (kolejny zamknie pełny ekran), strzałki przesuwają, z ochroną Ctrl/Alt
                // i jednym wpisem historii na trzymaną strzałkę
                return klawiszeZaznaczenia ? klawiszeZaznaczenia(e) : false;
            },
            renderOverlay: function() {
                if (!rys) {
                    // Po narysowaniu: zaznaczenie z odległościami jak w narzędziu V
                    if (nakladkaZaznaczenia) nakladkaZaznaczenia();
                    return;
                }
                var ctx = api.ctx(), theme = api.theme();
                var b = ramka();
                ctx.save();
                ctx.strokeStyle = theme.shapeStroke;
                ctx.lineWidth = 1.5;
                ctx.setLineDash([6, 4]);
                ctx.beginPath();
                api.traceSegments(ShapeCutouts.pathSegments(kandydat(b)));
                ctx.stroke();
                ctx.restore();
                var w = Math.round((b.maxX - b.minX) * 10) / 10, h = Math.round((b.maxY - b.minY) * 10) / 10;
                var tekst = (rodzaj === 'ellipse' && Math.abs(w - h) < 0.05) ? 'Ø ' + w + ' cm' : w + ' × ' + h + ' cm';
                _dymek(api, rys.cursorPx, tekst);
            }
        };
    }

    // ============================================
    // N — narożniki: frezowanie (łuk) / fazowanie (ścięcie) przeciąganiem kropki
    // ============================================
    function _corner(api) {
        var S = api.state;
        var drag = null;    // {key, index, theta, bisector, v, type, baza, m0, proj0, snapshot, undoPushed, cursorPx, wynik}
        var hover = null;   // 'klucz:indeks' kropki pod kursorem
        var MIN_DOT_PX = 20;
        var DOT_R = 5;

        // Pierścienie z narożnikami: obrys (nie koło) i wycięcia wielokątne. Narożniki w postaci
        // znormalizowanej (lista długości liczby punktów), więc krótsza lista nie psuje indeksów.
        function pierscienie() {
            var lista = [];
            if (S.vertices && S.shapeType !== 'circle') {
                lista.push({ key: 'outer', pts: S.vertices, corners: ShapeCorners.normalize(S.corners, S.vertices.length) });
            }
            S.cutouts.forEach(function(c, ci) {
                if (c.type === 'polygon') {
                    lista.push({ key: ci, pts: c.points, corners: ShapeCorners.normalize(c.corners, c.points.length) });
                }
            });
            return lista;
        }

        // Kropka leży na dwusiecznej, po stronie powstawania łuku: min. 20 px od wierzchołka,
        // przy istniejącym narożniku — tuż za środkiem łuku/ścięcia
        function odlegloscKropki(theta, corner) {
            if (!corner) return MIN_DOT_PX;
            return Math.max(MIN_DOT_PX, ShapeCorners.midpointDistance(theta, corner) * S.scale + 10);
        }

        function kropki() {
            var wynik = [];
            pierscienie().forEach(function(r) {
                var n = r.pts.length;
                for (var i = 0; i < n; i++) {
                    var ang = ShapeCorners.cornerAngle(r.pts[(i - 1 + n) % n], r.pts[i], r.pts[(i + 1) % n]);
                    if (!ang || !ShapeCorners.isAllowed(ang.theta)) continue;
                    var corner = r.corners[i];
                    var dist = odlegloscKropki(ang.theta, corner);
                    var v = api.cmToPixel(r.pts[i][0], r.pts[i][1]);
                    wynik.push({
                        key: r.key, index: i, theta: ang.theta, bisector: ang.bisector, v: r.pts[i], corner: corner,
                        px: [v[0] + ang.bisector[0] * dist, v[1] - ang.bisector[1] * dist]   // oś Y odwrócona
                    });
                }
            });
            return wynik;
        }

        function trafiona(p) {
            var lista = kropki();
            for (var i = 0; i < lista.length; i++) {
                if (Math.hypot(p.px - lista[i].px[0], p.py - lista[i].px[1]) <= DOT_R + 4) return lista[i];
            }
            return null;
        }

        // Czy pierścień o kluczu key nadal ma punkt o indeksie index (pole wymiaru mogło się
        // zatwierdzić dopiero po zmianie kształtu)
        function istnieje(key, index) {
            var pts = null;
            if (key === 'outer') {
                if (S.shapeType !== 'circle') pts = S.vertices;
            } else if (S.cutouts[key] && S.cutouts[key].type === 'polygon') {
                pts = S.cutouts[key].points;
            }
            return !!pts && index < pts.length;
        }
        function ptsOf(key) { return key === 'outer' ? S.vertices : S.cutouts[key].points; }
        function cornersOf(key) { return key === 'outer' ? S.corners : S.cutouts[key].corners; }
        function setCornersOf(key, corners) {
            if (key === 'outer') S.corners = corners;
            else S.cutouts[key].corners = corners;
        }
        // Odcisk narożników pierścienia do porównań „czy coś się zmieniło” (postać znormalizowana)
        function odcisk(key) {
            return JSON.stringify(ShapeCorners.normalize(cornersOf(key), ptsOf(key).length));
        }
        function zleWyciecia() {
            if (!S.cutouts.length) return 0;
            return ShapeCutouts.invalidIndices(api.outerRing(), S.cutouts).length;
        }
        // Stan pierścienia, od którego liczymy narożniki w trakcie gestu: kopia narożników
        // i liczba wycięć, które już teraz są złe (te nie liczą się jako nowa kolizja)
        function bazaPierscienia(key) {
            return { corners: ShapeCorners.normalize(cornersOf(key), ptsOf(key).length), zle: zleWyciecia() };
        }

        // Ustawia narożnik (albo wszystkie rogi pierścienia) na wymiar w mm: przycina do
        // limitu geometrii, a potem tak, by żadne wycięcie nie zaczęło kolidować. Narożniki
        // liczymy zawsze od `baza` (stan z początku gestu), więc powrót kursora albo puszczony
        // Shift przywracają to, co było. Zwraca {mm, limit} — limit = wymiar przycięty
        // (rysujemy na czerwono).
        function ustaw(key, index, type, wartoscMm, wszystkie, baza) {
            var pts = ptsOf(key), n = pts.length;
            var indeksy = wszystkie ? pts.map(function(_, i) { return i; }) : [index];
            function zbuduj(mm) {
                var nowe = baza.corners.slice();
                indeksy.forEach(function(i) {
                    var ang = ShapeCorners.cornerAngle(pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n]);
                    nowe[i] = (mm >= 1 && ang && ShapeCorners.isAllowed(ang.theta)) ? { type: type, r_mm: mm } : null;
                });
                return nowe;
            }
            var maks = wszystkie ? ShapeCorners.maxUniformMm(pts, type) : ShapeCorners.maxCornerMm(pts, baza.corners, index, type);
            var mm = Math.max(0, Math.round(wartoscMm));
            var limit = false;
            if (mm > maks) { mm = maks; limit = true; }
            setCornersOf(key, zbuduj(mm));
            if (zleWyciecia() > baza.zle) {
                // Łuk/ścięcie wchodzi w wycięcie — największy wymiar bez kolizji (szukanie binarne)
                var lo = 0, hi = mm;
                while (lo < hi) {
                    var mid = Math.ceil((lo + hi) / 2);
                    setCornersOf(key, zbuduj(mid));
                    if (zleWyciecia() > baza.zle) hi = mid - 1; else lo = mid;
                }
                mm = lo;
                limit = true;
                setCornersOf(key, zbuduj(mm));
            }
            return { mm: mm, limit: limit };
        }

        function rzut(p, d) {
            return (p.cm[0] - d.v[0]) * d.bisector[0] + (p.cm[1] - d.v[1]) * d.bisector[1];
        }

        // Kursor ustawiany przy najechaniu na kropkę nie może przeżyć N: inline style wygrywa
        // z klasą narzędzia, więc zasłoniłby kursor następnego narzędzia
        function wyczyscKursor() { api.canvas.style.cursor = ''; }

        // Koniec gestu (puszczona mysz, opuszczony canvas, zmiana narzędzia). Gest, który wrócił
        // do stanu z początku (kropka drgnęła i wróciła), zostawiłby pusty wpis historii — zdejmujemy
        // go jak V i R. Zwraca true, gdy gest trwał.
        function zakoncz() {
            if (!drag) return false;
            if (drag.undoPushed && api.snapshot() === drag.snapshot) api.popUndo();
            drag = null;
            S.cornerLimitHit = null;
            return true;
        }

        return {
            onActivate: function() { api.render(); },
            // Zmiana narzędzia w trakcie przeciągania (skrót przy wciśniętej myszy) kończy gest
            onDeactivate: function() { zakoncz(); hover = null; S.cornerLimitHit = null; wyczyscKursor(); },
            // Nowy kształt (setShape): stary gest jest nieaktualny, historię czyści setShape
            reset: function() { drag = null; hover = null; S.cornerLimitHit = null; wyczyscKursor(); },
            // Gest w toku: canvas nie cofa/ponawia wtedy historii (api.gestureInProgress)
            inGesture: function() { return drag !== null; },
            // Kropka narożnika (null, gdy w tym rogu jej nie ma): odległość środka od wierzchołka
            // wzdłuż dwusiecznej i największy zasięg koła (promień w hoverze + połowa obrysu 2 px).
            // Canvas stawia za nią stałą etykietę narożnika, żeby kropka jej nie zasłaniała.
            dotPlacement: function(theta, corner) {
                if (!ShapeCorners.isAllowed(theta)) return null;
                return { dist: odlegloscKropki(theta, corner), radius: DOT_R + 2 + 1 };
            },
            onDown: function(p) {
                if (p.button !== 0) return false;
                var k = trafiona(p);
                if (!k) return false;
                drag = {
                    key: k.key, index: k.index, theta: k.theta, bisector: k.bisector, v: k.v,
                    type: S.cornerType, baza: bazaPierscienia(k.key), snapshot: api.snapshot(), undoPushed: false,
                    cursorPx: [p.px, p.py], wynik: null,
                    m0: k.corner ? ShapeCorners.midpointDistance(k.theta, k.corner) : 0
                };
                // Złapanie kropki niczego nie zmienia — liczy się dopiero przesunięcie
                drag.proj0 = rzut(p, drag);
                return true;
            },
            onMove: function(p) {
                if (!drag) {
                    var k = trafiona(p);
                    var nowy = k ? (k.key + ':' + k.index) : null;
                    // Kursor ustawiamy przy każdym ruchu: canvas zeruje go po puszczeniu myszy
                    api.canvas.style.cursor = k ? 'pointer' : '';
                    if (nowy !== hover) {
                        hover = nowy;
                        api.render();
                    }
                    return false;
                }
                // Odległość środka łuku/ścięcia od wierzchołka (cm) → wymiar narożnika
                var s = drag.m0 + (rzut(p, drag) - drag.proj0);
                var wartoscCm = ShapeCorners.valueFromMidpointDistance(drag.theta, drag.type, s);
                var przed = odcisk(drag.key);
                drag.wynik = ustaw(drag.key, drag.index, drag.type, wartoscCm * 10, p.shift, drag.baza);
                drag.cursorPx = [p.px, p.py];
                S.cornerLimitHit = drag.wynik.limit ? { ring: drag.key } : null;
                // Wpis historii i emisja tylko przy realnej zmianie narożników pierścienia
                if (odcisk(drag.key) !== przed) {
                    if (!drag.undoPushed) {
                        api.pushUndoSnapshot(drag.snapshot);
                        drag.undoPushed = true;
                    }
                    api.emitChange();
                }
                api.render();
                return true;
            },
            onUp: function() {
                if (!zakoncz()) return false;
                api.render();
                return true;
            },
            onLeave: function() {
                var bylGest = zakoncz();
                if (bylGest || hover) {
                    hover = null;
                    api.render();
                }
            },
            onDblClick: function(p) {
                var k = trafiona(p);
                if (!k) return false;
                var typ = k.corner ? k.corner.type : S.cornerType;
                api.openInlineInput(k.px[0], k.px[1], k.corner ? k.corner.r_mm : 0, function(mm) {
                    if (!istnieje(k.key, k.index)) return;   // kształt zmienił się, zanim zatwierdzono pole
                    var snap = api.snapshot();
                    var przed = odcisk(k.key);
                    var wynik = ustaw(k.key, k.index, typ, mm, false, bazaPierscienia(k.key));
                    // Ta sama wartość: bez wpisu historii i bez emisji
                    if (odcisk(k.key) !== przed) {
                        api.pushUndoSnapshot(snap);
                        api.emitChange();
                    }
                    if (wynik.limit) api.showHint('W tym rogu mieści się najwyżej ' + wynik.mm + ' mm.');
                    api.render();
                }, { step: '1', min: 0 });
                return true;
            },
            renderOverlay: function() {
                var ctx = api.ctx(), theme = api.theme();
                ctx.save();
                kropki().forEach(function(k) {
                    var aktywna = hover === (k.key + ':' + k.index)
                        || (drag && drag.key === k.key && drag.index === k.index);
                    ctx.beginPath();
                    ctx.arc(k.px[0], k.px[1], aktywna ? DOT_R + 2 : DOT_R, 0, Math.PI * 2);
                    ctx.fillStyle = k.corner ? theme.shapeStroke : '#fff';
                    ctx.fill();
                    ctx.strokeStyle = theme.shapeStroke;
                    ctx.lineWidth = 2;
                    ctx.stroke();
                });
                ctx.restore();
                if (drag && drag.wynik) {
                    var opis = drag.wynik.mm === 0 ? 'Ostry róg'
                        : (drag.type === 'chamfer' ? 'Fazowanie ' + drag.wynik.mm + ' mm' : 'Frezowanie R ' + drag.wynik.mm + ' mm');
                    if (drag.wynik.limit) opis += ' (maks.)';
                    _dymek(api, drag.cursorPx, opis, drag.wynik.limit ? '#dc2626' : null);
                }
            }
        };
    }

    // Dymek przy kursorze (styl jak dymek kąta obrotu) — wspólny dla narzędzi
    function _dymek(api, cursorPx, tekst, kolor) {
        var ctx = api.ctx(), theme = api.theme(), S = api.state;
        ctx.save();
        ctx.font = 'bold 13px Poppins, sans-serif';
        var szer = ctx.measureText(tekst).width + 14;
        var x = cursorPx[0] + 16;
        var y = cursorPx[1] - 28;
        if (x + szer > S.width) x = S.width - szer - 4;
        if (y < 4) y = cursorPx[1] + 16;
        ctx.fillStyle = 'rgba(26, 26, 46, 0.92)';
        ctx.strokeStyle = kolor || theme.shapeStroke;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.rect(x, y, szer, 22);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = kolor || theme.shapeStroke;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(tekst, x + 7, y + 11);
        ctx.restore();
    }

    function create(api) {
        // V tworzymy osobno: L i M po narysowaniu wycięcia pokazują zaznaczenie przez jego nakładkę
        // i obsługują je jego klawiszami (onKey V nie używa `this`, więc można go podać jako funkcję)
        var select = _select(api);
        return {
            select: select,
            direct: _direct(api),
            add: _add(api),
            remove: _remove(api),
            ellipse: _shapeDraw(api, 'ellipse', select.renderOverlay, select.onKey),
            rect: _shapeDraw(api, 'rect', select.renderOverlay, select.onKey),
            corner: _corner(api),
            rotate: _rotate(api)
        };
    }

    return { IDS: IDS, create: create, _dymek: _dymek, _cutoutValid: _cutoutValid, _tryCutoutEdit: _tryCutoutEdit,
             _jestKolem: _jestKolem };
})();

window.ShapeTools = ShapeTools;
