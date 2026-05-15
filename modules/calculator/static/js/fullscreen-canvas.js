(function () {
    'use strict';

    var modal, canvasSlot, toggleBtn;
    var movedEditor = null;
    var originalParent = null;
    var originalNextSibling = null;
    var isOpen = false;

    function open() {
        if (isOpen) return;
        var canvasEditor = document.querySelector('[data-shape-editor]');
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
        toggleBtn = document.querySelector('[data-fullscreen-toggle]');
        if (!modal || !toggleBtn) return;

        canvasSlot = modal.querySelector('[data-fs-slot="canvas"]');

        toggleBtn.addEventListener('click', open);
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
