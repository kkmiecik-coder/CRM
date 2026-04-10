/**
 * Modal obróbki krawędzi na stanowiskach produkcji.
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
        // Sprawdź tryb: multi (data-edge-products) vs single (data-product-id)
        var edgeProductIds = wrapper.dataset.edgeProducts;

        if (edgeProductIds) {
            openMultiProductModal(wrapper);
        } else {
            openSingleProductModal(wrapper);
        }
    }

    function openSingleProductModal(wrapper) {
        var productId = wrapper.dataset.productId;
        var edgeType = wrapper.dataset.edgeType;
        var edgeRadius = wrapper.dataset.edgeRadius;
        var edgeAngle = wrapper.dataset.edgeAngle;
        var edgeSvg = wrapper.dataset.edgeSvg;
        var shapeSvg = wrapper.dataset.shapeSvg;

        var edgeLetters;
        try {
            edgeLetters = JSON.parse(wrapper.dataset.edgeLetters || '[]');
        } catch(e) {
            edgeLetters = [];
        }

        var title = document.getElementById('edgeModalTitle');
        title.textContent = 'Obróbka krawędzi — #' + productId;

        modalBody.innerHTML = buildProductSection(productId, {
            edge_type: edgeType,
            edge_radius: edgeRadius,
            edge_angle: edgeAngle,
            edge_letters: edgeLetters,
            edge_svg: edgeSvg,
            shape_svg: shapeSvg
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
        title.textContent = 'Obróbka krawędzi — zamówienie ' + orderNumber;

        // Zbierz dane z script.edge-product-data
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
                shape_svg: data.shape_svg
            });
        }

        modalBody.innerHTML = html;
        resetToggle();
        modal.classList.add('show');
    }

    function buildProductSection(productId, data) {
        var html = '';

        // Nagłówek produktu
        html += '<div class="edge-modal-product-header">#' + productId + '</div>';

        // Previews (kształt + izometria)
        var hasShape = data.shape_svg && data.shape_svg.length > 0;
        var hasIso = data.edge_svg && data.edge_svg.length > 0;

        if (hasShape || hasIso) {
            html += '<div class="edge-modal-previews">';
            if (hasShape) {
                html += '<div class="edge-modal-preview">';
                html += '<div class="edge-modal-preview-label">Kształt</div>';
                html += '<div>' + data.shape_svg + '</div>';
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

        // Info
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

    // Zamknięcie na ESC
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('show')) {
            closeEdgeModal();
        }
    });

    // Zamknięcie na kliknięcie tła
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeEdgeModal();
        }
    });

    // Globalne funkcje
    window.closeEdgeModal = closeEdgeModal;
    window.toggleEdgeLabels = toggleEdgeLabels;
    window.initializeEdgeHandlers = initializeEdgeHandlers;

    // Hook do refresha
    if (typeof window.stationRefreshHooks !== 'undefined') {
        window.stationRefreshHooks.push(initializeEdgeHandlers);
    }

    // Init
    initializeEdgeHandlers();
})();
