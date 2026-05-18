(function () {
    'use strict';

    var modal, canvasSlot;
    var movedEditor = null;
    var originalParent = null;
    var originalNextSibling = null;
    var isOpen = false;

    function open(triggerBtn) {
        if (isOpen) return;
        // Znajdź edytor związany z klikniętym przyciskiem (nie pierwszy na stronie!)
        var canvasEditor = triggerBtn && triggerBtn.closest('[data-shape-editor]');
        if (!canvasEditor) return;

        modal.hidden = false;
        modal.classList.add('is-open');
        document.body.classList.add('fs-canvas-open');

        originalParent = canvasEditor.parentNode;
        originalNextSibling = canvasEditor.nextSibling;
        canvasSlot.appendChild(canvasEditor);
        movedEditor = canvasEditor;

        var fitBtn = canvasEditor.querySelector('[data-shape-fit]');
        if (fitBtn) {
            requestAnimationFrame(function () { fitBtn.click(); });
        }
        isOpen = true;
    }

    function close() {
        if (!isOpen) return;
        modal.classList.remove('is-open');
        modal.hidden = true;
        document.body.classList.remove('fs-canvas-open');

        if (movedEditor && originalParent) {
            if (originalNextSibling && originalNextSibling.parentNode === originalParent) {
                originalParent.insertBefore(movedEditor, originalNextSibling);
            } else {
                originalParent.appendChild(movedEditor);
            }
        }
        movedEditor = null;
        originalParent = null;
        originalNextSibling = null;
        isOpen = false;
    }

    function onKeydown(e) {
        if (isOpen && e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    }

    function init() {
        modal = document.querySelector('[data-fs-modal]');
        if (!modal) return;

        canvasSlot = modal.querySelector('[data-fs-slot="canvas"]');

        // Delegacja — działa dla wszystkich produktów (także skopiowanych/dodanych po init)
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-fullscreen-toggle]');
            if (!btn) return;
            e.preventDefault();
            open(btn);
        });

        modal.querySelectorAll('[data-fs-close]').forEach(function (el) {
            el.addEventListener('click', close);
        });
        document.addEventListener('keydown', onKeydown);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
