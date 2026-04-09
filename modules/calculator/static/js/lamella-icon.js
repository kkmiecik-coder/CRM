// lamella-icon.js
// Generuje SVG ikonki kierunku lameli (3 prostokaty tworzace kwadrat)
// Uzywane w: quotes modal, offer_pdf, edges_pdf_generator

var LamellaIcon = (function() {
    'use strict';

    /**
     * Generuje SVG string ikonki lameli obróconej o podany kąt.
     * @param {number} direction - Kat obrotu: 0, 45, 90, 135
     * @param {number} [size=30] - Rozmiar SVG w px
     * @returns {string} SVG HTML string
     */
    function generateSvg(direction, size) {
        size = size || 30;
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
            bars += '<rect x="' + x.toFixed(1) + '" y="' + startY.toFixed(1) +
                '" width="' + barW.toFixed(1) + '" height="' + barH.toFixed(1) +
                '" rx="' + r.toFixed(1) + '" fill="#e67e22"/>';
        }

        // Przy 45/135 stopniach skalujemy paski o sqrt(2) zeby wypelnialy caly kwadrat
        var isDiagonal = (direction === 45 || direction === 135);
        var s = isDiagonal ? 1.42 : 1;
        var transform = direction
            ? ' transform="translate(' + half + ' ' + half + ') rotate(' + direction + ') scale(' + s + ') translate(-' + half + ' -' + half + ')"'
            : '';

        // clipPath obcina paski do kwadratu przy obrocie
        var clipId = 'lamellaClip_' + size + '_' + direction;
        var m = size * 0.07;
        var clip = '<defs><clipPath id="' + clipId + '"><rect x="' + m + '" y="' + m +
            '" width="' + (size - m * 2) + '" height="' + (size - m * 2) + '" rx="' + r.toFixed(1) + '"/></clipPath></defs>';

        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + size + ' ' + size +
            '" width="' + size + '" height="' + size + '">' +
            clip + '<g clip-path="url(#' + clipId + ')"><g' + transform + '>' + bars + '</g></g></svg>';
    }

    return { generateSvg: generateSvg };
})();

if (typeof window !== 'undefined') window.LamellaIcon = LamellaIcon;
