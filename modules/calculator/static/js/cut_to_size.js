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

    let nextRadioGroupId = 0;

    function bindCutToSizeToggle(form) {
        if (!form) return;
        const radios = form.querySelectorAll('.cut-to-size-radio');

        // Scope radio group per form. Bez <form>-wrappera wspolny atrybut
        // name="cutToSize" laczy radio z wszystkich .quote-form w jedna
        // grupe — wybor w jednym deselectuje pozostale. Nadajemy unikalny
        // name przy pierwszym bindzie; idempotentnie pomijamy ponowny rebind.
        if (!form.dataset.cutToSizeGroup) {
            const groupId = 'cutToSize-' + (nextRadioGroupId++);
            form.dataset.cutToSizeGroup = groupId;
            radios.forEach(function (radio) {
                radio.name = groupId;
            });
        }

        radios.forEach(function (radio) {
            radio.addEventListener('change', function (e) {
                if (e.target.checked) {
                    setCutToSize(form, e.target.value === 'yes');
                }
            });
        });
        // Init: ustaw UI zgodnie z aktualnym dataset (np. po wczytaniu drafta).
        syncToggleUI(form);
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
