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
