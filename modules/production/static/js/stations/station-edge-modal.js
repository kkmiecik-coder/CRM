/**
 * Modal obróbki krawędzi na stanowiskach produkcji.
 * Obsługuje kliknięcie ikony prostopadłościanu → otwiera modal z SVG i danymi.
 */
(function() {
    'use strict';

    var modal = document.getElementById('edgeModal');
    if (!modal) return;

    function initializeEdgeHandlers() {
        document.querySelectorAll('.edge-icon-wrapper').forEach(function(wrapper) {
            wrapper.addEventListener('click', function(e) {
                e.stopPropagation();
                openEdgeModal(this);
            });
        });
    }

    function openEdgeModal(wrapper) {
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

        // Tytuł
        document.getElementById('edgeModalTitle').textContent =
            'Obróbka krawędzi — #' + productId;

        // Typ obróbki
        var typeText = edgeType ? (edgeType.charAt(0).toUpperCase() + edgeType.slice(1)) : '—';
        document.getElementById('edgeModalType').textContent = typeText;

        // Promień
        var radiusText = edgeRadius ? ('R' + edgeRadius) : '—';
        if (edgeAngle) {
            radiusText += ' ' + edgeAngle + '°';
        }
        document.getElementById('edgeModalRadius').textContent = radiusText;

        // Krawędzie
        document.getElementById('edgeModalLetters').textContent =
            edgeLetters.length > 0 ? edgeLetters.join(', ') : '—';

        // SVG kształtu
        var shapeContainer = document.getElementById('edgeModalShapeContent');
        var shapePreview = document.getElementById('edgeModalShape');
        if (shapeSvg) {
            shapeContainer.innerHTML = shapeSvg;
            shapePreview.style.display = '';
        } else {
            shapePreview.style.display = 'none';
        }

        // SVG izometrii
        var isoContainer = document.getElementById('edgeModalIsometricContent');
        var isoPreview = document.getElementById('edgeModalIsometric');
        if (edgeSvg) {
            isoContainer.innerHTML = edgeSvg;
            isoPreview.style.display = '';
        } else {
            isoPreview.style.display = 'none';
        }

        modal.classList.add('show');
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
    window.initializeEdgeHandlers = initializeEdgeHandlers;

    // Hook do refresha
    if (typeof window.stationRefreshHooks !== 'undefined') {
        window.stationRefreshHooks.push(initializeEdgeHandlers);
    }

    // Init
    initializeEdgeHandlers();
})();
