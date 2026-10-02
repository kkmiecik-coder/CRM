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


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def test_trasy_js_zna_statusy_dostawy_i_nowe_akcje():
    js = _plik('static', 'js', 'logistics-routes.js')
    for fraza in ("zaladowana: 'Załadowana'", "w_trasie: 'W trasie'", "'/unload'", "'/undo-delivered'",
                  "'cofnij-zaladunek'", "'cofnij-dostarczenie'", 'postepTekst(', 'lg-przystanek-dostarczono',
                  'lg-przystanek-zostaje', 'lg-przystanek-paczki',
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
    # Odhaczenie wysyła statusy do Base.; przystanki już dostarczone zostają dostarczone (kto je dostarczył — kierowca
    # albo wcześniejsze odhaczenie — okno nie rozstrzyga, Ruling 27 pkt 5).
    assert u'Base.' in okno and u'Przystanki już dostarczone zostają dostarczone.' in okno
    assert u'kierowc' not in okno


def test_lista_logistyki_zna_etap_w_trasie_i_blokuje_sposob_po_zaladunku():
    js = _plik('static', 'js', 'logistics.js')
    kolejnosc = re.findall(r"'(\w+)'", re.search(r"KOLEJNOSC_ETAPOW = \[([^\]]*)\]", js).group(1))
    i = kolejnosc.index('zaladowane')
    assert kolejnosc[i:i + 3] == ['zaladowane', 'w_trasie', 'dostarczone']
    for fraza in ("zaladowana: 'załadowana'", "w_trasie: 'w trasie'", 'const poZaladunku'):
        assert fraza in js, fraza
    assert 'w.spakowane && !poZaladunku(w)' in js
    # Okno 8.7 omija zamówienia po załadunku na czterech ścieżkach: select w wierszu (zmianaSelecta, bieżący wiersz
    # `biezacy`), dymek mapy (zmienSposobZMapy) i obie akcje hurtowe (hurtSposob, hurtPodpowiedzi).
    assert '!poZaladunku(biezacy)' in _funkcja(js, 'zmianaSelecta')
    for nazwa in ('zmienSposobZMapy', 'hurtSposob', 'hurtPodpowiedzi'):
        assert '!poZaladunku(w)' in _funkcja(js, nazwa), nazwa
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


# ── Runda 1 po przeglądzie (Ruling 27) ───────────────────────────────────────────────────────────────────

def test_okno_odhacz_przystanki_dostarczone_i_zostaje():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert js.count('ODHACZALNE.includes(') == 4        # przycisk okna, komunikat po odczycie, otwarcie, przygotowanie
    uwagi = js[js.index('const UWAGA_WYKONANIA = {'):]
    uwagi = uwagi[:uwagi.index('};')]
    assert "dostarczone: 'już dostarczone" in uwagi and 'kierowc' not in uwagi     # neutralnie, bez „przez kierowcę”
    assert 'z.dostawa.dostarczono' in _funkcja(js, 'stanPrzystankuWykonania')
    pozycja = _funkcja(js, 'pozycjaWykonaniaHtml')
    # „Zostaje” z telefonu: pokazane z etykietą i domyślnie ODZNACZONE (logistyk może zaznaczyć).
    assert 'z.dostawa.zostaje' in pozycja and ': !zostaje)' in pozycja
    assert "'Zostaje: ' + esc(zostaje.etykieta)" in pozycja and 'lg-przystanek-zostaje' in pozycja
    # Przystanek już dostarczony nie dostaje „Zostaje” (jest zawsze dostarczony i nieaktywny).
    assert "stanP !== 'dostarczone' && z.dostawa" in pozycja


def test_przystanek_pokazuje_dostawe_z_data_i_cofnieciem():
    js = _plik('static', 'js', 'logistics-routes.js')
    dostawa = _funkcja(js, 'dostawaPrzystankuHtml')
    assert 'esc(d.zostaje.etykieta)' in dostawa
    assert "status === 'w_trasie' || status === 'wykonana'" in dostawa
    assert "if (status === 'robocza') return '';" in dostawa
    assert 'czasDostarczenia(d.dostarczono)' in dostawa
    # Dostarczenie sprzed dziś ma datę („01.10 14:05”), z dzisiaj samą godzinę.
    czas = _funkcja(js, 'czasDostarczenia')
    assert 'dzisIso()' in czas and 'dataKrotka(dzien)' in czas and 'godzinaZIso(iso)' in czas
    # Fokus po przebudowie listy wraca na ten sam „Cofnij dostarczenie” (Ruling 27 pkt 6).
    fokus = _funkcja(js, 'przywrocFokusPrzystanku')
    assert "f.akcja === 'cofnij-dostarczenie'" in fokus and 'data-lg-przystanek="cofnij-dostarczenie"' in fokus


def test_postep_w_naglowku_zmienia_tekst_tylko_gdy_sie_zmienil():
    edytor = _funkcja(_plik('static', 'js', 'logistics-routes.js'), 'renderujEdytor')
    assert 'postepEl.textContent !== tekstPostepu' in edytor
    assert 'postepEl.textContent = tekstPostepu' in edytor
    assert 'postepEl.textContent = t ?' not in edytor        # bez bezwarunkowego przypisania (aria-live)


def test_cofniecie_zatwierdzenia_pyta_o_swieza_trase_i_ostrzega_o_zostaje():
    js = _plik('static', 'js', 'logistics-routes.js')
    galaz = js[js.index("case 'cofnij':"):js.index("case 'cofnij-zaladunek':")]
    assert 'zapytajOCofniecieZatwierdzenia(t)' in galaz and 'window.confirm' not in galaz
    pytanie = _funkcja(js, 'zapytajOCofniecieZatwierdzenia')
    assert "zapytanie('/routes/' + t.id" in pytanie             # świeża trasa przed liczeniem
    assert pytanie.index("zapytanie('/routes/' + t.id") < pytanie.index('opisZaladunkuTrasy(biezaca)')
    assert 'let biezaca = t;' in pytanie and 'catch (e)' in pytanie   # bez odczytu liczymy z edytora
    assert "biezaca.status !== 'zatwierdzona'" in pytanie       # kierowca skończył załadunek: bez pytania
    assert 'stan.wToku.has(klucz)' in pytanie                   # dwuklik nie pyta dwa razy (trasa „w toku”)
    opis = _funkcja(js, 'opisZaladunkuTrasy')
    assert u'wyczyści załadunek i decyzje „Zostaje” — kierowca zeskanuje paczki ponownie.' in opis
    assert 'dostawa.zostaje' in opis                            # same decyzje „Zostaje” też ostrzegają


def test_niepewne_odhaczenie_rozroznia_trase_zamknieta_przez_kierowce():
    js = _plik('static', 'js', 'logistics-routes.js')
    po = _funkcja(js, 'poOdhaczeniu')
    i = po.index('route.odhaczona_w_panelu === false')
    assert 'Odhaczenie z panelu się nie zapisało' in po[i:]
    assert po.index('odhaczenie się zapisało') > i              # „zapisało się” tylko dla odhaczonej w panelu
    assert 'zamknął ją kierowca' in po


def test_okno_przepakowania_liczy_niespakowane_osobno_od_zaladowanych():
    js = _plik('static', 'js', 'logistics.js')
    hurt = _funkcja(js, 'hurtSposob')
    assert 'inne: zmieniane.filter((w) => !w.spakowane && !poZaladunku(w)).length' in hurt
    assert 'poZaladunku: zmieniane.filter(poZaladunku).length' in hurt
    assert 'zmieniane.length - doDecyzji.length' not in hurt
    podpowiedzi = _funkcja(js, 'hurtPodpowiedzi')
    assert 'inne: doZmiany.filter((w) => !w.spakowane && !poZaladunku(w)).length' in podpowiedzi
    assert 'poZaladunku: doZmiany.filter(poZaladunku).length' in podpowiedzi
    assert 'doZmiany.length - spakowane.length' not in podpowiedzi
    # Osobne zdanie w opisie okna i przekazanie liczby przez okno.
    assert 'o.poZaladunku > 0' in _funkcja(js, 'pokazKrokPierwszy')
    assert 'poZaladunku: (opcje && opcje.poZaladunku) || 0' in js
    for forma in (u"'zamówienie jest już załadowane lub dostarczone'", u"'zamówienia są już załadowane lub dostarczone'",
                  u"'zamówień jest już załadowanych lub dostarczonych'", u"' — sposobu dostawy nie zmienimy.'"):
        assert forma in js, forma



# ── Poprawki po przeglądzie całej gałęzi (krok 4.4b, front) ──────────────────────────────────────────────

def test_cofnij_do_roboczej_czeka_na_odczyt_z_limitem_czasu():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert 'const LIMIT_ODCZYTU_MS = 10000;' in js
    assert 'cofniecieSprawdzane' not in js                      # zastąpiona wspólnym znacznikiem „w toku”
    pytanie = _funkcja(js, 'zapytajOCofniecieZatwierdzenia')
    odczyt = pytanie.index("zapytanie('/routes/' + t.id")
    # Na czas odczytu przyciski trasy czekają (jak przy zapisie), a czytnik ekranu dostaje komunikat.
    assert pytanie.index('stan.wToku.add(klucz)') < pytanie.index('odswiezAkcje()') < pytanie.index('oglos(') < odczyt
    assert 'Sprawdzamy stan trasy' in pytanie
    # Znacznik schodzi PRZED pytaniem — „tak” w oknie nie może trafić w blokadę własnej mutacji.
    assert pytanie.index('stan.wToku.delete(klucz)') < pytanie.index('window.confirm')
    # Limit czasu: odczyt idzie z sygnałem, zegar jest zdejmowany, a po przerwaniu liczymy z danych edytora.
    assert 'new AbortController()' in pytanie and 'signal: kontroler.signal' in pytanie
    assert 'setTimeout(() => kontroler.abort(), LIMIT_ODCZYTU_MS)' in pytanie and 'clearTimeout(limit)' in pytanie
    assert 'przerwane(e)' not in pytanie                        # przerwanie limitem to nie wyjście z funkcji


def test_cofnij_do_roboczej_po_zmianie_statusu_nie_pyta_serwera_drugi_raz():
    js = _plik('static', 'js', 'logistics-routes.js')
    pytanie = _funkcja(js, 'zapytajOCofniecieZatwierdzenia')
    galaz = pytanie[pytanie.index("biezaca.status !== 'zatwierdzona'"):pytanie.index('opisZaladunkuTrasy(biezaca)')]
    assert 'odswiezOtwarta' not in pytanie                      # bez drugiego GET — trasa jest już w ręku
    assert 'przyjmijSwiezyOdczyt(biezaca, start)' in galaz and 'const start = licznikZmian;' in pytanie
    # Wskazówka tylko dla trasy załadowanej: wyjście to „Cofnij załadunek”.
    assert re.search(u"biezaca\\.status === 'zaladowana' \\? ' Użyj „Cofnij załadunek”\\.'", galaz)
    # Odczyt przyjmowany tak samo jak w odswiezOtwarta: nie cofa nowszej zmiany u nas, nie rusza trasy w toku.
    przyjecie = _funkcja(js, 'przyjmijSwiezyOdczyt')
    assert 'akcjaTrwa()' in przyjecie and 'lokalna.wersja > start' in przyjecie and 'przyjmijTrase(route)' in przyjecie
    assert 'przyjmijSwiezyOdczyt(dane.route, start)' in _funkcja(js, 'odswiezOtwarta')


def test_cofnij_dostarczenie_nazywa_zamowienie_i_trase_tylko_gdy_wrocila():
    dostawa = _funkcja(_plik('static', 'js', 'logistics-routes.js'), 'cofnijDostarczenie')
    assert u"'Cofnięto dostarczenie'" in dostawa and 'zamowienie.numer' in dostawa     # komunikat podaje numer
    assert u'jest znów w drodze' not in dostawa                 # stary tekst mówił to zawsze
    # „Znów w drodze” tylko, gdy trasa była wykonana, a po cofnięciu już nie jest; inaczej zdanie neutralne.
    assert "t.status === 'wykonana' && odp.route.status !== 'wykonana'" in dostawa
    assert dostawa.index("t.status === 'wykonana'") < dostawa.index(u'znów jest w drodze')
    assert u'Zamówienie znów jest do dostarczenia.' in dostawa
    assert 'esc(' not in dostawa                                # komunikat idzie jako tekst, nie HTML


def test_komentarz_odhaczenia_nie_mowi_o_kierowcy():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert u'dostarczonych przez kierowc' not in js
    assert u'anulowanych i już dostarczonych zostają nieaktywne' in js


def test_opis_okna_odhacz_mowi_o_planowanej_trasie_dla_odznaczonych():
    html = _plik('templates', 'logistics', 'tab_content.html')
    okno = html[html.index('data-lg="trasa-wykonaj-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    opis = okno[okno.index('lg-dialog-opis'):]
    opis = opis[:opis.index('</p>')]
    assert u'odznaczone zdejmiemy z trasy' in opis
    # Odznaczone, które były już załadowane, dostają w Base. status „Planowana trasa” (Ruling 25).
    assert u'były już załadowane' in opis and u'Base. dostanie dla nich status „Planowana trasa”' in opis
    assert opis.index(u'odznaczone zdejmiemy') < opis.index(u'Planowana trasa') < opis.index(u'Dostarczone mogą być')
    assert u'BaseLinker' not in opis and u'kierowc' not in opis


def test_zablokowany_select_po_zaladunku_wskazuje_cofniecie_zaladunku():
    lista = _plik('static', 'js', 'logistics.js')
    mapa = _funkcja(_plik('static', 'js', 'logistics-map.js'), 'powodBlokadySposobu')
    ogolny = u'Towar jest już załadowany na trasę albo dostarczony. Sposobu dostawy nie można zmienić.'
    droga = u'najpierw użyj „Cofnij załadunek” w zakładce Trasy'
    # Select w wierszu listy: powód z jednego pomocnika, wyjście tylko dla etapu „załadowane” (trasa załadowana).
    pomocnik = lista[lista.index('const powodPoZaladunku ='):]
    pomocnik = pomocnik[:pomocnik.index(');\n')]
    assert "w.etap.status === 'zaladowane'" in pomocnik and droga in pomocnik and ogolny in pomocnik
    assert pomocnik.index(droga) < pomocnik.index(ogolny)
    assert 'powod = powodPoZaladunku(w);' in lista
    # Dymek mapy: ten sam podział (trasa w drodze i dostarczenie zostają przy tekście ogólnym).
    assert "z.etap.status === 'zaladowane'" in mapa and droga in mapa and ogolny in mapa
    assert mapa.index(droga) < mapa.index(ogolny)


def test_wersje_plikow_podbite_po_poprawkach_frontu_4_4b():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261001g'), ('js/logistics.js', '20261001g'),
                        ('js/logistics-map.js', '20261001f'), ('js/logistics-fleet.js', '20260928b')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m, plik
        assert m.group(1) > stara, plik


# --- Ruling 31.1: „Odhacz” pustej trasy załadowanej albo w drodze --------------------------------------------
# Doróbka albo zmiana z Base. może zdjąć jedyny przystanek trasy załadowanej (Ruling 30). „Ruszam” takiej trasy
# odmawia i odsyła logistyka do „Odhacz” w panelu, a serwer zamyka pustą trasę załadowaną albo w drodze — panel musi
# więc dopuścić „Odhacz” bez przystanków dla tych dwóch statusów (dla roboczej i zatwierdzonej zostaje jak dotąd).

def test_odhacz_pustej_trasy_zaladowanej_i_w_drodze():
    js = _plik('static', 'js', 'logistics-routes.js')
    assert "const ZAMYKANE_BEZ_PRZYSTANKOW = ['zaladowana', 'w_trasie'];" in js
    pomocnik = js[js.index('const zamykanaBezPrzystankow = (t) =>'):]
    pomocnik = pomocnik[:pomocnik.index(';\n')]
    assert 'ZAMYKANE_BEZ_PRZYSTANKOW.includes(t.status)' in pomocnik and '!(t.przystanki || []).length' in pomocnik
    # Przycisk edytora: „Trasa nie ma przystanków.” (wyłączony) tylko, gdy trasy nie da się zamknąć bez przystanków.
    akcje = _funkcja(js, 'odswiezAkcje')
    i = akcje.index("akcja === 'wykonaj'")
    galaz = akcje[i:akcje.index("tytul = 'Trasa nie ma przystanków.'", i)]
    assert '!zamykanaBezPrzystankow(' in galaz
    # Okno „Odhacz”: przycisk aktywny także dla pustej trasy do zamknięcia, z tekstem w miejscu listy.
    przyciski = _funkcja(js, 'odswiezPrzyciskiWykonania')
    assert '|| zamykanaBezPrzystankow(t)' in przyciski
    lista = _funkcja(js, 'renderujListeWykonania')
    assert 'zamykanaBezPrzystankow(w.trasa) ? PUSTA_DO_ZAMKNIECIA' in lista
    assert u"const PUSTA_DO_ZAMKNIECIA = 'Trasa nie ma przystanków — zatwierdź, żeby ją zamknąć.';" in js
    # Komunikat „nie ma czego odhaczać” — tylko dla pustej trasy, której nie da się zamknąć bez przystanków.
    wczytanie = _funkcja(js, 'wczytajDoWykonania')
    i = wczytanie.index(u'Trasa nie ma już przystanków — nie ma czego odhaczać.')
    assert '!zamykanaBezPrzystankow(trasa)' in wczytanie[wczytanie.rindex('} else if', 0, i):i]
    # Niepusta trasa jak dotąd: przycisk aktywny przy przystankach, lista z pozycjami.
    assert '(t.przystanki || []).length || zamykanaBezPrzystankow(t)' in przyciski
    assert 'przystanki.map((p) => pozycjaWykonaniaHtml(w, p))' in lista
    assert js.count('ODHACZALNE.includes(') == 4


def test_wersja_tras_podbita_po_odhaczeniu_pustej_trasy():
    html = _plik('templates', 'logistics', 'tab_content.html')
    m = re.search(r"filename='js/logistics-routes\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) > '20261002a', m and m.group(1)


# --- Oględziny 2.10 (Konrad), U4 i U6: zielona tarcza dostarczonego przystanku, legenda tarcz ----------------

def _luminancja(hex_):
    kanaly = [int(hex_[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in kanaly]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _kontrast(a, b):
    la, lb = sorted((_luminancja(a), _luminancja(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_dostarczony_przystanek_ma_zielona_tarcze_z_czarnym_numerem():
    """U4: przystanek z `zamowienie.dostawa.dostarczono` — zielona tarcza (--il-status-ok) z czarnym numerem
    (atrament panelu, ≥ 4,5:1) na osi przystanków edytora i w oknie „Odhacz”. Decyzja Konrada 2.10: pinezki też —
    na mapce edytora i na mapie tras Dashboardu (pole `dostarczone` z /routes/map), z „Dostarczono” w dymku."""
    js = _plik('static', 'js', 'logistics-routes.js')
    assert 'const dostarczony = (z) => !!(z && z.dostawa && z.dostawa.dostarczono);' in js
    assert ("if (!anul && status !== 'robocza' && dostarczony(z)) klasyStacji.push('lg-stacja--dostarczona');"
            in _funkcja(js, 'przystanekHtml'))
    assert "(stanP === 'dostarczone' ? ' lg-stacja--dostarczona' : '')" in _funkcja(js, 'pozycjaWykonaniaHtml')
    mapka = _funkcja(js, 'narysujMapke')
    assert "const dostarczonyP = !anul && t.status !== 'robocza' && dostarczony(z);" in mapka
    assert "dostarczonyP ? 'lg-stacja--dostarczona' : ''" in mapka and 'ikonaStacji(anul ? ' in mapka
    assert "'Dostarczono ' + czasDostarczenia(z.dostawa.dostarczono)" in mapka
    mapa = _plik('static', 'js', 'logistics-map.js')
    assert "(!anulowany && dostarczony ? ' lg-stacja--dostarczona' : '')" in _funkcja(mapa, 'ikonaPrzystanku')
    trasy_mapy = _funkcja(mapa, 'narysujTrasy')
    assert 'const dostarczony = !anulowany && !!p.dostarczone;' in trasy_mapy
    assert 'ikonaPrzystanku(p.pozycja, klasa, anulowany, dostarczony)' in trasy_mapy
    css = _plik('static', 'css', 'logistics-trasy.css')
    regula = css[css.index('.logistics-tab .lg-stacja--dostarczona {'):]
    regula = regula[:regula.index('}')]
    assert 'background: var(--il-status-ok, #16a34a)' in regula and 'color: var(--il-text-primary, #1a1a2e)' in regula
    assert 'border-style' not in regula          # przerywana / kropkowana obwódka (punkt mapy) zostaje
    assert css.index('.logistics-tab .lg-stacja--bez-geo {') < css.index('.logistics-tab .lg-stacja--dostarczona {')
    assert _kontrast('#1a1a2e', '#16a34a') >= 4.5
    wymuszone = css[css.index('@media (forced-colors: active) {\n    .logistics-tab .lg-stacja--dostarczona {'):]
    wymuszone = wymuszone[:wymuszone.index('\n}\n')]
    assert 'background: CanvasText' in wymuszone and 'color: Canvas;' in wymuszone


def test_legenda_tarcz_pod_osia_przystankow_i_w_oknie_odhacz(client):  # noqa: F811
    """U6: legenda tarcz (dokładny punkt, przybliżony, brak punktu, dostarczone) z jednego makra — pod osią
    przystanków w edytorze (ukryta, gdy oś nie ma przystanków) i na dole okna „Odhacz”, w kolorze trasy."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    legendy = re.findall(r'<ul class="lg-legenda-stacji" data-lg-trasy="([\w-]+)" aria-label="Oznaczenia przystanków">'
                         r'(.*?)</ul>', html, re.S)
    assert [k for k, _ in legendy] == ['legenda-stacji', 'wykonaj-legenda']
    assert legendy[0][1] == legendy[1][1]
    for klasa, opis in (('', u'dokładny punkt na mapie'),
                        (' lg-stacja--przyblizona', u'punkt przybliżony (tylko miejscowość)'),
                        (' lg-stacja--bez-geo', u'brak punktu na mapie'),
                        (' lg-stacja--dostarczona', u'dostarczone')):
        assert u'<span class="lg-stacja lg-stacja--legenda%s" aria-hidden="true">1</span>%s</li>' % (klasa, opis) \
            in legendy[0][1], opis
    sekcja = html[html.index('data-lg-trasy="przystanki-sekcja"'):]
    assert 'data-lg-trasy="legenda-stacji"' in sekcja[:sekcja.index('</section>')]
    okno = html[html.index('data-lg="trasa-wykonaj-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    assert okno.index('data-lg-trasy="wykonaj-lista"') < okno.index('data-lg-trasy="wykonaj-legenda"') \
        < okno.index('class="lg-dialog-akcje"')
    js = _plik('static', 'js', 'logistics-routes.js')
    przystanki = _funkcja(js, 'renderujPrzystanki')
    assert 'legendaStacjiEl.hidden = true;' in przystanki and 'legendaStacjiEl.hidden = !kolejne.length;' in przystanki
    assert 'ustawKolor(wykonajLegendaEl, kolor(trasa.id));' in _funkcja(js, 'przygotujWykonanie')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-stacja--legenda {' in css and '.logistics-tab .lg-legenda-stacji {' in css


def test_wersje_po_tarczy_dostarczonego_i_legendzie():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002b'), ('css/logistics-trasy.css', '20261002c')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik


# --- Oględziny 2.10 (Konrad), U5 i U7: okno „Odhacz jako dostarczoną” -------------------------------------------

def test_odhacz_jako_dostarczona_w_calym_panelu_tras(client):  # noqa: F811
    """U7: przycisk w nagłówku edytora (AKCJE, każdy status), tytuł okna i przycisk zatwierdzenia (także po zapisie) —
    „Odhacz jako dostarczoną”. Nazwę statusu trasy zmieniła osobna decyzja (test niżej: „Dostarczona”)."""
    js = _plik('static', 'js', 'logistics-routes.js')
    assert u"'Odhacz jako wykonaną'" not in js
    akcje = js[js.index('const AKCJE = {'):]
    akcje = akcje[:akcje.index('\n    };')]
    assert akcje.count(u"['wykonaj', 'Odhacz jako dostarczoną', 'fa-check-double', '']") == 4
    assert u"trwa ? 'Zapisywanie…' : 'Odhacz jako dostarczoną'" in js
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert u'Odhacz jako wykonaną' not in html
    okno = html[html.index('data-lg="trasa-wykonaj-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    assert u'id="lg-trasa-wykonaj-tytul">Odhacz jako dostarczoną <span class="lg-dialog-numer"' in okno
    assert u'data-lg-trasy="wykonaj-zapisz">Odhacz jako dostarczoną</button>' in okno
    assert u"wykonana: 'Dostarczona'" in js and u'>Dostarczone <span class="lg-trasy-sekcja-ile"' in html


def test_nazwa_trasy_w_oknach_tras_od_drugiej_linii(client):  # noqa: F811
    """U5: w oknach tras (Odhacz, Dodaj do trasy — ten sam element .lg-dialog-numer w tytule) nazwa trasy albo numer
    zamówienia stoi pod tytułem, nie w jego linii. Okno adresu na Dashboardzie (logistics.css) bez zmian."""
    css = _plik('static', 'css', 'logistics-trasy.css')
    regula = css[css.index('.logistics-tab .lg-dialog--trasy .lg-dialog-numer {'):]
    regula = regula[:regula.index('}')]
    assert 'display: block' in regula and 'overflow-wrap: anywhere' in regula
    pusty = css[css.index('.logistics-tab .lg-dialog--trasy .lg-dialog-numer:empty {'):]
    assert 'display: none' in pusty[:pusty.index('}')]
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    for okno in ('trasa-wykonaj-dialog', 'trasa-dodaj-dialog'):
        assert '<dialog class="lg-dialog lg-dialog--trasy" data-lg="%s"' % okno in html, okno
        tresc = html[html.index('data-lg="%s"' % okno):]
        tresc = tresc[:tresc.index('</dialog>')]
        assert re.search(r'<h2 class="lg-dialog-tytul"[^>]*>[^<]+ <span class="lg-dialog-numer"', tresc), okno
    ogolna = _plik('static', 'css', 'logistics.css')
    ogolna = ogolna[ogolna.index('.logistics-tab .lg-dialog-numer {'):]
    assert 'margin-left: 6px' in ogolna[:ogolna.index('}')]


def test_wersje_po_oknie_odhacz_jako_dostarczona():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002c'), ('css/logistics-trasy.css', '20261002d')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik


# --- Oględziny 2.10 (Konrad), U8: „Cofnięto dostawę …” przy przystanku -----------------------------------------

def test_przystanek_pokazuje_cofniecie_dostawy_do_ponownego_dostarczenia():
    """U8: pasek Dostawy przy przystanku pokazuje „Cofnięto dostawę <data i godzina>” (runda 1: zawsze z datą, także
    dla dzisiaj; „Dostarczono” zostaje z samą godziną dla dziś), przez esc, dopóki przystanek nie jest znów
    dostarczony; pole `cofnieto` daje serwer (trasy_api._dostawa_przystanku)."""
    js = _plik('static', 'js', 'logistics-routes.js')
    pasek = _funkcja(js, 'dostawaPrzystankuHtml')
    assert 'if (!d.dostarczono && d.cofnieto) {' in pasek
    assert u"'Cofnięto dostawę ' + esc(dataIGodzina(d.cofnieto))" in pasek
    assert u"'Dostarczono ' + esc(czasDostarczenia(d.dostarczono))" in pasek
    data_i_godzina = _funkcja(js, 'dataIGodzina')
    assert "[dataKrotka(dzien), godzinaZIso(iso)].filter(Boolean).join(' ')" in data_i_godzina
    assert 'dzisIso' not in data_i_godzina
    assert '<span class="lg-przystanek-cofnieto"><i class="fas fa-rotate-left" aria-hidden="true"></i>' in pasek
    assert pasek.index("if (status === 'robocza') return '';") < pasek.index('d.cofnieto')
    css = _plik('static', 'css', 'logistics-trasy.css')
    regula = css[css.index('.logistics-tab .lg-przystanek-cofnieto {'):]
    regula = regula[:regula.index('}')]
    assert 'color: var(--lg-kolejka-tekst, #9a4a05)' in regula
    assert _kontrast('#9a4a05', '#ffffff') >= 4.5
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002d'), ('css/logistics-trasy.css', '20261002e')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik


def test_wersje_po_zielonych_pinezkach_dostarczonych():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002e'), ('js/logistics-map.js', '20261002a'),
                        ('css/logistics-trasy.css', '20261002g')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik



# --- Decyzja Konrada 2.10, U7: status trasy „Wykonana” dla ludzi to „Dostarczona” -------------------------------

def test_status_wykonana_dla_ludzi_to_dostarczona(client):  # noqa: F811
    """U7: etykiety i plakietki statusu (panel tras, mapa, lista Dashboardu), sekcja listy „Dostarczone”, puste stany,
    podpowiedzi i komunikaty mówią „dostarczona”; wartość statusu 'wykonana' w kodzie i API zostaje. Etap pozycji
    „Dostarczone” na liście Logistyki bez zmian."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    mapa = _plik('static', 'js', 'logistics-map.js')
    lista = _plik('static', 'js', 'logistics.js')
    assert u"w_trasie: 'W trasie', wykonana: 'Dostarczona' };" in trasy
    assert u"w_trasie: 'W trasie', wykonana: 'Dostarczona' };" in mapa
    assert u"w_trasie: 'w trasie', wykonana: 'dostarczona' };" in lista
    for js in (trasy, mapa, lista):
        for stary in (u"'Wykonana'", u"wykonana: 'wykonana'", u'wykonanych tras', u'jako wykonaną', u'jest wykonana',
                      u'jest już wykonana', u'” wykonana', u'będzie wykonana'):
            assert stary not in js, stary
    for nowy in (u'Brak dostarczonych tras w tych dniach.', u'Brak dostarczonych tras w ostatnich 30 dniach.',
                 u'Nie wczytano dostarczonych tras. ', u'odhaczenie zamknie ją jako dostarczoną.',
                 u'trasa zamknie się jako dostarczona bez przystanków.', u'” dostarczona — dostarczono ',
                 u'” jest już dostarczona — zamknął ją kierowca', u'” jest dostarczona — odpowiedź serwera'):
        assert nowy in trasy, nowy
    assert "status: 'wykonana'" in trasy                      # API bez zmian
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert u'>Dostarczone <span class="lg-trasy-sekcja-ile" data-lg-trasy="wykonane-ile">' in html
    assert u'>Wykonane <' not in html
    # Etap pozycji „Dostarczone” na liście Logistyki (inna rzecz niż status trasy) bez zmian.
    assert u"'dostarczone'" in lista


def test_wersje_po_nazwie_statusu_dostarczona():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik, stara in (('js/logistics-routes.js', '20261002f'), ('js/logistics-map.js', '20261002f'),
                        ('js/logistics.js', '20261002a')):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) > stara, plik



# --- Runda 1 po oględzinach 2.10: kontrast legendy, pustych sekcji i najechania na „Dostarczone” -----------------

def test_kontrast_legendy_i_paska_dostarczonych():
    """Runda 1: legenda tarcz, puste sekcje listy i opis filtra drugorzędnym kolorem ≥ 4,5:1 na bieli; najechanie
    na pas „Dostarczone” ciemniejszą zielenią (≥ 4,5:1 na tle najechania). Panel nie ma trybu ciemnego."""
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '--lg-tekst-opis: #5b6372;' in css and _kontrast('#5b6372', '#ffffff') >= 4.5
    for selektor in ('.logistics-tab .lg-legenda-stacji {', '.logistics-tab .lg-trasy-pusto {',
                     '.logistics-tab .lg-trasy-filtr-opis {'):
        regula = css[css.index(selektor):]
        assert 'color: var(--lg-tekst-opis);' in regula[:regula.index('}')], selektor
    wykonana = css[css.index('.logistics-tab .lg-trasy-sekcja--wykonana {'):]
    wykonana = wykonana[:wykonana.index('}')]
    assert '--lg-sekcja-pasek-hover: #e1f3e7;' in wykonana and '--lg-sekcja-tekst-hover: #166534;' in wykonana
    assert _kontrast('#166534', '#e1f3e7') >= 4.5 and _kontrast('#15803d', '#eff9f2') >= 4.5
    najechanie = css[css.index('.logistics-tab .lg-trasy-wykonane > summary:hover {'):]
    assert 'color: var(--lg-sekcja-tekst-hover, var(--lg-sekcja-tekst));' in najechanie[:najechanie.index('}')]
    strzalka = css[css.index('.logistics-tab .lg-trasy-wykonane > summary::before {'):]
    assert 'color: currentColor;' in strzalka[:strzalka.index('}')]
    assert 'prefers-color-scheme' not in css
