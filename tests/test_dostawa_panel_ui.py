# -*- coding: utf-8 -*-
"""Front panelu po kroku 4.4 (spec 9.7 i 11): sekcje Załadowane i W trasie, akcje według statusu, „Cofnij załadunek”
i „Cofnij dostarczenie” zamiast „Przywróć trasę”, postęp Dostawy, etap „W trasie” na liście i blokada sposobu
dostawy po załadunku. Pilnujemy treści plików (jak tests/test_logistyka_trasy_ui.py) i renderu szablonu."""
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

KATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(KATALOG, *czesci), encoding='utf-8') as f:
        return f.read()


def test_trasy_js_zna_statusy_dostawy_i_nowe_akcje():
    js = _plik('static', 'js', 'logistics-routes.js')
    for fraza in ("zaladowana: 'Załadowana'", "w_trasie: 'W trasie'", "'/unload'", "'/undo-delivered'",
                  "'cofnij-zaladunek'", "'cofnij-dostarczenie'", 'postep', 'dostarczono', 'zostaje',
                  "const ODHACZALNE = ['robocza', 'zatwierdzona', 'zaladowana', 'w_trasie']"):
        assert fraza in js, fraza
    assert '/restore' not in js and "'przywroc'" not in js
    akcje = js[js.index('const AKCJE = {'):]
    akcje = akcje[:akcje.index('\n    };')]
    assert re.search(r"zaladowana: \[\s*\['routimo'[^\]]*\],\s*\['cofnij-zaladunek'[^\]]*\],\s*\['wykonaj'", akcje)
    assert re.search(r"w_trasie: \[\s*\['routimo'[^\]]*\],\s*\['wykonaj'", akcje)
    assert re.search(r"wykonana: \[\s*\['routimo'[^\]]*\],\s*\]", akcje)   # bez odhaczania i przywracania


def test_szablon_ma_sekcje_postep_i_opis_odhaczenia(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for nazwa in ('zaladowane', 'zaladowane-ile', 'w-trasie', 'w-trasie-ile', 'postep'):
        assert 'data-lg-trasy="%s"' % nazwa in html, nazwa
    assert html.index('data-lg-trasy="zatwierdzone"') < html.index('data-lg-trasy="zaladowane"') \
        < html.index('data-lg-trasy="w-trasie"') < html.index('data-lg-trasy="wykonane"')
    okno = html[html.index('data-lg="trasa-wykonaj-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    assert u'Base.' in okno and u'kierowc' in okno     # odhaczenie wysyła statusy; dostarczone z telefonu zostają


def test_lista_logistyki_zna_etap_w_trasie_i_blokuje_sposob_po_zaladunku():
    js = _plik('static', 'js', 'logistics.js')
    kolejnosc = re.findall(r"'(\w+)'", re.search(r"KOLEJNOSC_ETAPOW = \[([^\]]*)\]", js).group(1))
    i = kolejnosc.index('zaladowane')
    assert kolejnosc[i:i + 3] == ['zaladowane', 'w_trasie', 'dostarczone']
    for fraza in ("zaladowana: 'załadowana'", "w_trasie: 'w trasie'", 'const poZaladunku'):
        assert fraza in js, fraza
    assert 'w.spakowane && !poZaladunku(w)' in js
    assert js.count('!poZaladunku(w)') >= 3          # wiersz, hurt sposobu, hurt podpowiedzi — bez okna 8.7
    mapa = _plik('static', 'js', 'logistics-map.js')
    assert "w_trasie: 'W trasie'" in mapa and "zaladowana: 'Załadowana'" in mapa
    assert u'załadowany' in mapa[mapa.index('function powodBlokadySposobu'):][:1500]


def test_style_statusow_dostawy():
    css = _plik('static', 'css', 'logistics-trasy.css')
    for klasa in ('.lg-status--zaladowana', '.lg-status--w_trasie', '.lg-plakietka-trasy--zaladowana',
                  '.lg-plakietka-trasy--w_trasie', '.lg-edytor-postep', '.lg-trasa-pozycja-postep',
                  '.lg-przystanek-dostarczono', '.lg-przystanek-zostaje', '.lg-wykonaj-pozycja--dostarczone'):
        assert klasa in css, klasa
    assert '[data-etap="w_trasie"]' in _plik('static', 'css', 'logistics.css')
