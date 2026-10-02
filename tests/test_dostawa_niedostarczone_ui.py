# -*- coding: utf-8 -*-
"""Front panelu tras po U10 (decyzja Konrada 2.10, Ruling 32): przystanek niedostarczony zostaje na trasie w drodze —
szara tarcza i wiersz, „Niedostarczono <data godz> — powód”, „Cofnij niedostarczenie” i „Zdejmij z trasy”, sekcja
historii niedostarczonych zdjętych z trasy, postęp „dostarczono X/Y · niedostarczono Z”, okno „Odhacz” z
niedostarczonymi domyślnie odznaczonymi, confirm „Cofnij dostarczenie” na trasie z historią. Pilnujemy treści plików
(jak tests/test_dostawa_panel_ui.py) i renderu szablonu."""
import os
import re

from tests.logistyka_fixtures import app, client  # noqa: F401

KATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(KATALOG, *czesci), encoding='utf-8') as f:
        return f.read()


def _funkcja(js, nazwa):
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _luminancja(hex_):
    kanaly = [int(hex_[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in kanaly]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _kontrast(a, b):
    la, lb = sorted((_luminancja(a), _luminancja(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_przystanek_niedostarczony_na_osi_edytora():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert 'const niedostarczony = (z) => !!(z && z.dostawa && z.dostawa.niedostarczono);' in js
    wiersz = _funkcja(js, 'przystanekHtml')
    assert "klasyStacji.push('lg-stacja--niedostarczona')" in wiersz
    assert "' lg-przystanek--niedostarczony'" in wiersz
    pasek = _funkcja(js, 'dostawaPrzystankuHtml')
    assert '} else if (d.niedostarczono) {' in pasek
    assert u"'Niedostarczono ' + esc(dataIGodzina(d.niedostarczono.kiedy))" in pasek
    assert 'opisNiedostarczenia(d.niedostarczono)' in pasek
    assert '<span class="lg-przystanek-niedostarczono">' in pasek
    assert 'data-lg-przystanek="cofnij-niedostarczenie"' in pasek
    assert 'data-lg-przystanek="zdejmij-niedostarczone"' in pasek
    assert pasek.index("status === 'w_trasie'", pasek.index('d.niedostarczono')) < pasek.index(
        'cofnij-niedostarczenie')
    opis = _funkcja(js, 'opisNiedostarczenia')
    assert "n.etykieta + (n.notatka ? ': ' + n.notatka : '')" in opis


def test_akcje_cofnij_i_zdejmij_niedostarczone():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert "'/undo-not-delivered'" in _funkcja(js, 'cofnijNiedostarczenie')
    assert "'/remove-not-delivered'" in _funkcja(js, 'zdejmijNiedostarczone')
    klik = _funkcja(js, 'naKlikPanelu')
    assert "akcja === 'cofnij-niedostarczenie'" in klik and 'mutacja((ctx) => cofnijNiedostarczenie(ctx, id))' in klik
    assert "akcja === 'zdejmij-niedostarczone'" in klik and 'mutacja((ctx) => zdejmijNiedostarczone(ctx, id))' in klik
    assert u'wróci do puli bez trasy, a Base. dostanie status „Planowana trasa”' in klik
    fokus = _funkcja(js, 'przywrocFokusPrzystanku')
    assert "['cofnij-dostarczenie', 'cofnij-niedostarczenie', 'zdejmij-niedostarczone'].includes(f.akcja)" in fokus


def test_confirm_cofnij_dostarczenie_mowi_o_niedostarczonych_w_puli():
    """Koordynator 2.10: „Cofnij dostarczenie” na zamkniętej trasie z niedostarczonymi w historii — confirm mówi
    wprost, że te zamówienia zostają w puli (R32.4)."""
    js = _plik('static', 'js', 'logistics-routes.js')
    klik = _funkcja(js, 'naKlikPanelu')
    assert "stan.otwarta.status === 'wykonana'" in klik
    assert '(stan.otwarta.niedostarczone_zdjete || []).filter(doPuli).length' in klik   # bez doróbek (runda 1)
    assert u'zostają w puli bez trasy' in klik and u'nie wrócą na tę trasę' in klik


def test_historia_niedostarczonych_zdjetych_pod_osia(client):
    js = _plik('static', 'js', 'logistics-routes.js')
    assert "const zdjeteEl = el('zdjete');" in js
    historia = _funkcja(js, 'renderujZdjete')
    assert '(t && t.niedostarczone_zdjete) || []' in historia
    assert u"'Niedostarczone — wróciły do puli'" in historia and u"'Niedostarczone — zdjęte z trasy'" in historia
    # Runda 1 U10: zdjęte przez powrót do produkcji — „Zdjęto”, separator „·” (bez podwójnego myślnika).
    assert "(doPuli(h) ? 'Niedostarczono ' : 'Zdjęto ') + esc(dataIGodzina(h.kiedy)) + ' · '" in historia
    assert 'opisNiedostarczenia(h)' in historia
    assert "const POWODY_POWROTU = ['dorobka', 'zmiana_base'];" in js
    assert 'renderujZdjete(' in _funkcja(js, 'renderujPrzystanki')
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert '<div class="lg-zdjete" data-lg-trasy="zdjete" hidden></div>' in html
    assert u'lg-stacja--niedostarczona" aria-hidden="true">1</span>niedostarczone' in html


def test_postep_z_niedostarczonymi():
    js = _plik('static', 'js', 'logistics-routes.js')
    postep = _funkcja(js, 'postepTekst')
    assert '(Number(p.zdjete) || 0)' in postep
    assert "' · niedostarczono ' + p.niedostarczone" in postep


def test_okno_odhacz_niedostarczone_domyslnie_odznaczone():
    js = _plik('static', 'js', 'logistics-routes.js')
    pozycja = _funkcja(js, 'pozycjaWykonaniaHtml')
    assert "const niedostarczono = stanP !== 'dostarczone' && z.dostawa && z.dostawa.niedostarczono" in pozycja
    assert '!zostaje && !niedostarczono' in pozycja
    assert u"'Niedostarczono ' + esc(dataIGodzina(niedostarczono.kiedy))" in pozycja


def test_mapki_szara_pinezka_niedostarczonego():
    js = _plik('static', 'js', 'logistics-routes.js')
    mapka = _funkcja(js, 'narysujMapke')
    assert "const niedostarczonyP = !anul && !dostarczonyP && t.status !== 'robocza' && niedostarczony(z);" in mapka
    assert "niedostarczonyP ? 'lg-stacja--niedostarczona' : ''" in mapka
    assert u"'Niedostarczono ' + dataIGodzina(z.dostawa.niedostarczono.kiedy)" in mapka
    mapa = _plik('static', 'js', 'logistics-map.js')
    ikona = _funkcja(mapa, 'ikonaPrzystanku')
    assert "(!anulowany && !dostarczony && niedostarczony ? ' lg-stacja--niedostarczona' : '')" in ikona
    trasy = _funkcja(mapa, 'narysujTrasy')
    assert 'const niedostarczony = !anulowany && !!p.niedostarczone;' in trasy
    assert 'ikonaPrzystanku(p.pozycja, klasa, anulowany, dostarczony, niedostarczony)' in trasy


def test_css_niedostarczonego_i_kontrast():
    css = _plik('static', 'css', 'logistics-trasy.css')
    regula = css[css.index('.logistics-tab .lg-stacja--niedostarczona {'):]
    regula = regula[:regula.index('}')]
    assert 'background: #6b7280' in regula and 'color: #fff' in regula
    assert _kontrast('#ffffff', '#6b7280') >= 4.5
    assert css.index('.logistics-tab .lg-stacja--bez-geo {') < css.index('.logistics-tab .lg-stacja--niedostarczona {')
    wymuszone = css[css.index('@media (forced-colors: active) {\n    .logistics-tab .lg-stacja--niedostarczona {'):]
    assert 'background: GrayText' in wymuszone[:wymuszone.index('\n}\n')]
    tekst = css[css.index('.logistics-tab .lg-przystanek-niedostarczono {'):]
    tekst = tekst[:tekst.index('}')]
    assert 'color: #4b5563' in tekst and _kontrast('#4b5563', '#ffffff') >= 4.5
    assert '.logistics-tab .lg-zdjete {' in css


def test_wersje_podbite_po_u10():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002u10'), ('css/logistics-trasy.css', '20261002k')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik
    m = re.search(r"filename='js/logistics-map\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) > '20261002i'


def test_szablon_ma_sekcje_historii_pod_osia():
    html = _plik('templates', 'logistics', 'tab_content.html')
    sekcja = html[html.index('data-lg-trasy="przystanki-sekcja"'):]
    sekcja = sekcja[:sekcja.index('</section>')]
    assert sekcja.index('data-lg-trasy="linia"') < sekcja.index('data-lg-trasy="zdjete"')
