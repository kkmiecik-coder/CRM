/**
 * Modal kształtu i obróbki produktu na stanowiskach produkcji.
 * Obsługuje dwa tryby:
 * - Single product (finishing): dane w data-* atrybutach ikony
 * - Multi product (formatting/packaging): dane w script.edge-product-data
 */
(function() {
    'use strict';

    var modal = document.getElementById('edgeModal');
    if (!modal) return;

    var modalBody = document.getElementById('edgeModalBody');

    function initializeEdgeHandlers() {
        document.querySelectorAll('.edge-icon-wrapper').forEach(function(wrapper) {
            wrapper.addEventListener('click', function(e) {
                e.stopPropagation();
                openEdgeModal(this);
            });
        });
    }

    function openEdgeModal(wrapper) {
        var edgeProductIds = wrapper.dataset.edgeProducts;
        if (edgeProductIds) {
            openMultiProductModal(wrapper);
        } else {
            openSingleProductModal(wrapper);
        }
    }

    function openSingleProductModal(wrapper) {
        var productId = wrapper.dataset.productId;
        var hasEdge = wrapper.dataset.hasEdge === 'true' || wrapper.dataset.hasEdge === 'True';

        var title = document.getElementById('edgeModalTitle');
        title.textContent = 'Szczegóły produktu — #' + productId;

        var edgeLetters;
        try {
            edgeLetters = JSON.parse(wrapper.dataset.edgeLetters || '[]');
        } catch(e) {
            edgeLetters = [];
        }

        var lamellaDir = wrapper.dataset.lamellaDirection;
        var lamella = (lamellaDir !== '' && lamellaDir !== undefined) ? parseInt(lamellaDir) : null;

        modalBody.innerHTML = buildProductSection(productId, {
            edge_type: wrapper.dataset.edgeType,
            edge_radius: wrapper.dataset.edgeRadius,
            edge_angle: wrapper.dataset.edgeAngle,
            edge_letters: edgeLetters,
            edge_svg: wrapper.dataset.edgeSvg,
            shape_svg: wrapper.dataset.shapeSvg,
            lamella_direction: lamella,
            has_edge: hasEdge
        });

        resetToggle();
        modal.classList.add('show');
    }

    function openMultiProductModal(wrapper) {
        var orderNumber = wrapper.dataset.orderNumber || '';
        var productIds;
        try {
            productIds = JSON.parse(wrapper.dataset.edgeProducts || '[]');
        } catch(e) {
            productIds = [];
        }

        var title = document.getElementById('edgeModalTitle');
        title.textContent = 'Szczegóły produktów — zamówienie ' + orderNumber;

        var html = '';
        for (var i = 0; i < productIds.length; i++) {
            var scriptEl = document.querySelector('script.edge-product-data[data-product-id="' + productIds[i] + '"]');
            if (!scriptEl) continue;

            var data;
            try {
                data = JSON.parse(scriptEl.textContent);
            } catch(e) {
                continue;
            }

            var edgeLetters;
            if (Array.isArray(data.edge_letters)) {
                edgeLetters = data.edge_letters;
            } else {
                try { edgeLetters = JSON.parse(data.edge_letters || '[]'); } catch(e) { edgeLetters = []; }
            }

            if (productIds.length > 1 && i > 0) {
                html += '<div class="edge-modal-separator"></div>';
            }

            html += buildProductSection(data.id, {
                edge_type: data.edge_type,
                edge_radius: data.edge_radius,
                edge_angle: data.edge_angle,
                edge_letters: edgeLetters,
                edge_svg: data.edge_svg,
                shape_svg: data.shape_svg,
                lamella_direction: data.lamella_direction,
                has_edge: data.has_edge
            });
        }

        modalBody.innerHTML = html;
        resetToggle();
        modal.classList.add('show');
    }

    function generateLamellaSvg(direction) {
        var size = 60;
        var half = size / 2;
        var barW = size * 0.27;
        var barH = size * 0.87;
        var gap = size * 0.03;
        var startX = (size - (barW * 3 + gap * 2)) / 2;
        var startY = (size - barH) / 2;
        var r = size * 0.03;

        var bars = '';
        for (var i = 0; i < 3; i++) {
            var x = startX + i * (barW + gap);
            bars += '<rect x="' + x.toFixed(1) + '" y="' + startY.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + barH.toFixed(1) + '" rx="' + r.toFixed(1) + '" fill="#e67e22"/>';
        }

        var isDiagonal = (direction === 45 || direction === 135);
        var s = isDiagonal ? 1.42 : 1;
        var transform = direction ? ' transform="translate(' + half + ' ' + half + ') rotate(' + direction + ') scale(' + s + ') translate(-' + half + ' -' + half + ')"' : '';

        var m = size * 0.07;
        var clip = '<defs><clipPath id="lc"><rect x="' + m.toFixed(1) + '" y="' + m.toFixed(1) + '" width="' + (size - m * 2).toFixed(1) + '" height="' + (size - m * 2).toFixed(1) + '" rx="' + r.toFixed(1) + '"/></clipPath></defs>';

        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + size + ' ' + size + '" width="' + size + '" height="' + size + '">' + clip + '<g clip-path="url(#lc)"><g' + transform + '>' + bars + '</g></g></svg>';
    }

    function buildProductSection(productId, data) {
        var html = '';
        var hasEdge = data.has_edge;
        var hasShape = data.shape_svg && data.shape_svg.length > 0;
        var hasIso = data.edge_svg && data.edge_svg.length > 0;
        var hasLamella = data.lamella_direction !== null && data.lamella_direction !== undefined && !isNaN(data.lamella_direction);

        // Nagłówek produktu
        html += '<div class="edge-modal-product-header">#' + productId + '</div>';

        // Previews
        if (hasShape || hasIso || hasLamella) {
            html += '<div class="edge-modal-previews">';

            if (hasShape) {
                html += '<div class="edge-modal-preview">';
                html += '<div class="edge-modal-preview-label">Kształt</div>';
                html += '<div>' + data.shape_svg + '</div>';
                if (hasLamella) {
                    var dirLabel = data.lamella_direction + '°';
                    html += '<div class="edge-modal-lamella">';
                    html += '<span class="edge-modal-lamella-label">Lamele:</span> ';
                    html += generateLamellaSvg(data.lamella_direction);
                    html += '<span class="edge-modal-lamella-angle">' + dirLabel + '</span>';
                    html += '</div>';
                }
                html += '</div>';
            }

            if (hasIso) {
                html += '<div class="edge-modal-preview">';
                html += '<div class="edge-modal-preview-label">Izometria</div>';
                html += '<div>' + data.edge_svg + '</div>';
                html += '</div>';
            }

            html += '</div>';
        }

        // Info krawędzi — tylko gdy ma obróbkę
        if (hasEdge) {
            var typeText = data.edge_type ? (data.edge_type.charAt(0).toUpperCase() + data.edge_type.slice(1)) : '—';
            var radiusText = data.edge_radius ? ('R' + data.edge_radius) : '—';
            if (data.edge_angle) {
                radiusText += ' ' + data.edge_angle + '°';
            }
            var lettersText = (data.edge_letters && data.edge_letters.length > 0) ? data.edge_letters.join(', ') : '—';

            html += '<div class="edge-modal-info">';
            html += '<div><div class="edge-modal-info-label">Typ obróbki</div><div class="edge-modal-info-value accent">' + typeText + '</div></div>';
            html += '<div><div class="edge-modal-info-label">Promień</div><div class="edge-modal-info-value">' + radiusText + '</div></div>';
            html += '<div><div class="edge-modal-info-label">Krawędzie</div><div class="edge-modal-info-value">' + lettersText + '</div></div>';
            html += '</div>';
        }

        return html;
    }

    function resetToggle() {
        var toggleBtn = document.getElementById('edgeModalToggleLabels');
        if (toggleBtn) {
            toggleBtn.dataset.visible = 'true';
            toggleBtn.textContent = 'Ukryj oznaczenia';
        }
    }

    function toggleEdgeLabels() {
        var btn = document.getElementById('edgeModalToggleLabels');
        if (!btn || !modalBody) return;

        var visible = btn.dataset.visible !== 'false';
        var svgs = modalBody.querySelectorAll('svg');

        svgs.forEach(function(svgEl) {
            // Pomijaj SVG lameli (mają clipPath)
            if (svgEl.querySelector('clipPath')) return;
            var circles = svgEl.querySelectorAll('circle');
            var texts = svgEl.querySelectorAll('text');
            circles.forEach(function(c) { c.style.display = visible ? 'none' : ''; });
            texts.forEach(function(t) { t.style.display = visible ? 'none' : ''; });
        });

        btn.dataset.visible = visible ? 'false' : 'true';
        btn.textContent = visible ? 'Pokaż oznaczenia' : 'Ukryj oznaczenia';
    }

    function closeEdgeModal() {
        modal.classList.remove('show');
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('show')) {
            closeEdgeModal();
        }
    });

    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeEdgeModal();
        }
    });

    window.closeEdgeModal = closeEdgeModal;
    window.toggleEdgeLabels = toggleEdgeLabels;
    window.initializeEdgeHandlers = initializeEdgeHandlers;

    if (typeof window.stationRefreshHooks !== 'undefined') {
        window.stationRefreshHooks.push(initializeEdgeHandlers);
    }

    initializeEdgeHandlers();
})();
