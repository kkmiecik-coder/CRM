/**
 * Toggle "Docięcie do wymiaru" — per-produkt.
 *
 * Stan trzymany w dataset.cutToSize na elemencie .quote-form
 * ('true' | 'false'). Domyślnie 'true'.
 *
 * Markup w calculator.html: dwa radio "cutToSize" o wartościach yes/no
 * w obrębie tego samego .quote-form. Listenery scope'ujemy do formularza,
 * więc kliknięcie w produkcie nie wpływa na inne produkty mimo wspólnego
 * atrybutu name.
 */

(function () {
    'use strict';

    function getCutToSize(form) {
        if (!form) return true;
        const ds = form.dataset.cutToSize;
        if (ds === undefined || ds === null || ds === '') return true;
        return ds === 'true';
    }

    function setCutToSize(form, value) {
        if (!form) return;
        const boolValue = value === true || value === 'true' || value === 'yes';
        form.dataset.cutToSize = boolValue ? 'true' : 'false';
        syncToggleUI(form);
        applyLockState(form);
    }

    function syncToggleUI(form) {
        if (!form) return;
        const value = getCutToSize(form);
        const radioYes = form.querySelector('.cut-to-size-radio[value="yes"]');
        const radioNo = form.querySelector('.cut-to-size-radio[value="no"]');
        if (radioYes && radioNo) {
            radioYes.checked = value;
            radioNo.checked = !value;
        }
    }

    /**
     * Bez docięcia produkt jest półfabrykatem — nie robimy wykończenia ani
     * obróbki krawędzi. Lockujemy te sekcje wizualnie + blokujemy interakcje.
     * Reset wartości robi osobno listener change (tylko przy klikniętym Nie),
     * żeby nie kasować historycznych danych przy zwykłym wczytaniu.
     */
    function applyLockState(form) {
        if (!form) return;
        const locked = !getCutToSize(form);
        const targets = [
            form.querySelector('#finishing-tree-container, .finishing-tree-container'),
            form.querySelector('.finishing-options-summary'),
            form.querySelector('.edges-section'),
        ].filter(Boolean);
        targets.forEach(function (el) {
            if (locked) el.classList.add('cut-to-size-locked');
            else el.classList.remove('cut-to-size-locked');
        });
    }

    /**
     * Reset wykończenia + krawędzi przy świadomej zmianie Tak → Nie.
     * Używa istniejących przycisków reset (event delegation w edges.js).
     * Wariant/podpoziomy znikają jak przy normalnym kliknięciu "Surowe" —
     * to jest oczekiwane zachowanie (Surowe nie ma wariantów).
     */
    function resetFinishingAndEdges(form) {
        if (!form) return;
        const finishingResetBtn = form.querySelector('.finishing-reset-btn');
        if (finishingResetBtn) finishingResetBtn.click();
        const edgesResetBtn = form.querySelector('.edges-reset-btn');
        if (edgesResetBtn) edgesResetBtn.click();
    }

    let nextRadioGroupId = 0;

    function bindCutToSizeToggle(form) {
        if (!form) return;
        const radioYes = form.querySelector('.cut-to-size-radio[value="yes"]');
        const radioNo = form.querySelector('.cut-to-size-radio[value="no"]');
        const labelYes = form.querySelector('.cut-to-size-label-yes');
        const labelNo = form.querySelector('.cut-to-size-label-no');
        const labelHeader = form.querySelector('.cut-to-size-label');

        // Scope: bez <form>-wrappera wspólne name + id wyciekają między
        // .quote-form. Nadajemy unikalny suffix per formularz, łącznie z
        // przepisaniem id/for (żeby kliknięcie w label trafiało we właściwy
        // input). Idempotentne — tylko przy pierwszym bindzie.
        if (!form.dataset.cutToSizeGroup) {
            const groupId = 'cutToSize-' + (nextRadioGroupId++);
            form.dataset.cutToSizeGroup = groupId;

            const yesId = groupId + '-yes';
            const noId = groupId + '-no';

            if (radioYes) {
                radioYes.name = groupId;
                radioYes.id = yesId;
            }
            if (radioNo) {
                radioNo.name = groupId;
                radioNo.id = noId;
            }
            if (labelYes) labelYes.setAttribute('for', yesId);
            if (labelNo) labelNo.setAttribute('for', noId);
            // Nagłówek "Docięcie do wymiaru:" — usuwamy ewentualny stary for=,
            // żeby nie wskazywał na #cutToSizeYes z innego formularza.
            if (labelHeader) labelHeader.removeAttribute('for');
        }

        const radios = [radioYes, radioNo].filter(Boolean);
        radios.forEach(function (radio) {
            radio.addEventListener('change', function (e) {
                if (!e.target.checked) return;
                const newValue = e.target.value === 'yes';
                const wasValue = getCutToSize(form);
                setCutToSize(form, newValue);
                // Tak → Nie: świadoma decyzja usera, kasujemy wykończenie + krawędzie.
                if (wasValue && !newValue) {
                    resetFinishingAndEdges(form);
                }
            });
        });
        // Init: ustaw UI + lock state zgodnie z aktualnym dataset (np. po drafcie).
        syncToggleUI(form);
        applyLockState(form);
    }

    function bindAllCutToSizeToggles() {
        const forms = document.querySelectorAll('.quote-form');
        forms.forEach(bindCutToSizeToggle);
    }

    document.addEventListener('DOMContentLoaded', bindAllCutToSizeToggles);

    window.cutToSize = {
        get: getCutToSize,
        set: setCutToSize,
        sync: syncToggleUI,
        bind: bindCutToSizeToggle,
        bindAll: bindAllCutToSizeToggles,
    };
})();
