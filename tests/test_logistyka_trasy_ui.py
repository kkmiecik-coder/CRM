# -*- coding: utf-8 -*-
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(open(os.path.join(katalog, f), encoding='utf-8').read()
                   for f in os.listdir(katalog) if f.endswith('.js'))


def test_podzakladki_i_widoki():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for widok in ('dashboard', 'routes', 'fleet'):
        assert 'data-logistics-view="{}"'.format(widok) in html
        assert 'data-lg-widok="{}"'.format(widok) in html
    assert 'data-skrypt-trasy=' in html
    assert 'js/logistics-fleet.js' in html and 'css/logistics-trasy.css' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_mapa_ma_widok_tras_i_fabryke_podkladu():
    mapa = _plik('static', 'js', 'logistics-map.js')
    for fraza in ('ustawWidok', 'renderTrasy', 'onWyborTrasy', 'nowaWarstwaPodkladu'):
        assert fraza in mapa, fraza


def test_js_uzywa_api_tras_i_floty():
    js = _js()
    for fraza in ('/routes/map', '/availability', '/stops/order', '/approve', '/revert',
                  '/complete', '/restore', '/routimo', '/vehicles', '/drivers',
                  'bez_trasy', 'hurt-trasa', 'usunieto_z_trasy', 'dragstart', '(zajęty',
                  'window.LogisticsRoutes', 'window.LogisticsFleet', 'komunikat:', 'pokazWidok'):
        assert fraza in js, fraza
    assert 'BaseLinker' not in js and 'unpkg.com' not in js


# ─── Poza briefem: szablon renderuje się z nowymi adresami i pliki istnieją ───

def test_zakladka_renderuje_sie_z_trasami_i_flota(client):  # noqa: F811
    """Błąd Jinja albo literówka w url_for nowego pliku wyszłaby dopiero na produkcji."""
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for plik in ('js/logistics-routes.js', 'js/logistics-fleet.js', 'css/logistics-trasy.css'):
        m = re.search(r'="([^"?]+' + re.escape(plik) + r')\?v=\w+"', html)
        assert m, plik
        statyka = client.get(m.group(1))
        assert statyka.status_code == 200, plik
        statyka.close()
    # Obecna treść Dashboardu w całości w panelu „dashboard”, przed panelem tras.
    assert html.index('data-logistics-view="dashboard"') < html.index('class="lg-liczniki"') \
        < html.index('class="lg-uklad"') < html.index('data-logistics-view="routes"')
    # Przełącznik widoków mapy stoi w dotychczas pustym miejscu nagłówka mapy.
    widoki = html[html.index('data-lg-mapa="widoki"'):]
    widoki = widoki[:widoki.index('</div>')]
    assert 'data-lg-mapa-widok="zamowienia"' in widoki and 'data-lg-mapa-widok="trasy"' in widoki


def test_zakladki_maja_role_i_klawiature():
    html = _plik('templates', 'logistics', 'tab_content.html')
    naglowek = html[html.index('class="lg-podzakladki"'):]
    naglowek = naglowek[:naglowek.index('</div>')]
    assert naglowek.count('role="tab"') == 3 and naglowek.count('aria-selected=') == 3
    for widok in ('dashboard', 'routes', 'fleet'):
        assert 'aria-controls="lg-widok-{}"'.format(widok) in naglowek
        assert 'id="lg-widok-{}"'.format(widok) in html
    lista = _plik('static', 'js', 'logistics.js')
    assert "'logistyka.widok'" in lista          # ostatnia podzakładka w localStorage
    assert 'ArrowRight' in lista and 'ArrowLeft' in lista


def test_okna_tras_i_floty_to_natywne_dialogi():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for okno in ('trasa-dodaj-dialog', 'trasa-wykonaj-dialog', 'pojazd-dialog'):
        start = html.index('data-lg="{}"'.format(okno))
        znacznik = html[html.rindex('<dialog', 0, start):html.index('>', start)]
        assert 'class="lg-dialog' in znacznik and 'aria-labelledby=' in znacznik, okno
    # Poza panelami podzakładek — „Dodaj do trasy…” otwiera się ze schowanymi Trasami.
    assert html.index('data-lg="trasa-dodaj-dialog"') > html.index('data-logistics-view="fleet"')


def test_wykonanie_trasy_zawsze_wysyla_liste_dostarczonych():
    """Addendum do Task 3: bez klucza API uznałby za dostarczone wszystkie bieżące przystanki."""
    js = _plik('static', 'js', 'logistics-routes.js')
    assert 'delivered_order_ids:' in js


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


# ─── Poprawki po przeglądzie i oględzinach Task 8 (runda 1) ───

def test_odpowiedz_mutacji_nie_przejmuje_edytora_innej_trasy():
    """A1: spóźniona odpowiedź trasy A nie wraca do edytora, w którym jest już trasa B."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    assert 'akcjaTrwa:' not in trasy and 'stan.akcjaTrwa' not in trasy   # zajętość per trasa (stan.wToku)
    assert 'stan.sesja += 1' in _funkcja(trasy, 'resetEdytora')
    for nazwa in ('zapisz', 'zatwierdz', 'cofnij', 'przywroc', 'usunPrzystanek', 'dodajKandydatow'):
        tresc = _funkcja(trasy, nazwa)
        assert 'przyjmijOdpowiedz(ctx, odp.route' in tresc and 'przyjmijTrase(' not in tresc, nazwa
    assert 'przyjmijOdpowiedz(w, odp.route' in _funkcja(trasy, 'zatwierdzWykonanie')
    assert 'stan.otwarta.id !== w.id' not in _funkcja(trasy, 'zatwierdzWykonanie')
    assert 'stan.sesja !== sesja' in _funkcja(trasy, 'przygotujWykonanie')


def test_odmowa_zapisu_punktu_spoza_trybu_trafia_do_komunikatu():
    """A2: 409 z PUT /orders/<id>/geo, gdy pasek należy już do następnego zamówienia."""
    mapa = _plik('static', 'js', 'logistics-map.js')
    for nazwa in ('zapiszKorekte', 'ustawPunkt'):
        tresc = _funkcja(mapa, nazwa)
        catch = tresc[tresc.index('} catch (e) {'):]
        galaz = catch[catch.index('if (tryb !== biezacy) {'):]
        assert galaz.index('zglosBlad(') < galaz.index('return;'), nazwa
    assert 'onBlad: onBlad' in mapa
    assert 'm.onBlad(naBladMapy)' in _plik('static', 'js', 'logistics.js')


def test_css_etapu_3_nie_zmienia_wygladu_etapu_2():
    """m1: ogólne reguły (nieaktywny przycisk, [hidden], pola dotykowe) tylko w nowych kontenerach."""
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab [hidden]' not in css
    assert '\n.logistics-tab .lg-przycisk:disabled' not in css
    assert '\n.logistics-tab .lg-przycisk--glowny:disabled' not in css
    assert '    .logistics-tab .lg-pole input { min-height' not in css
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert 'class="lg-dialog lg-dialog--pojazd"' in html


def test_paleta_tras_ma_12_barw():
    """m5 + M7: 12 wyraźnie różnych barw, kolor z id trasy."""
    css = _plik('static', 'css', 'logistics-trasy.css')
    for n in range(12):
        assert '--lg-trasa-%d:' % n in css and '.lg-trasa-kolor-%d {' % n in css, n
    assert '--lg-trasa-12:' not in css
    assert 'const LICZBA_KOLOROW_TRAS = 12;' in _plik('static', 'js', 'logistics-map.js')


def test_mapy_po_polsku_i_bez_nasluchu_okna_leafleta():
    """M13 + I2: polskie podpisy zoomu; rozmiar map pilnuje ResizeObserver, nie trackResize."""
    for plik in ('logistics-map.js', 'logistics-routes.js'):
        js = _plik('static', 'js', plik)
        assert "zoomInTitle: 'Przybliż', zoomOutTitle: 'Oddal'" in js, plik
        assert 'trackResize: false' in js and 'zoomControl: false' in js, plik
    assert 'Pokaż całą trasę' in _plik('static', 'js', 'logistics-routes.js')


def test_daty_i_bledy_pol_w_szablonie():
    """M5 + M15: zakres lat w polach dat, błędy powiązane z polami (aria-describedby).
    (Fala poprawek, M8) min/max dat trasy (edytor, „Dodaj do trasy…”) liczy JS przy otwarciu
    formularza — stały zakres lat w szablonie został tylko w filtrze „Wykonane”."""
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert html.count('type="date"') == 6
    filtr = html[html.index('data-lg-trasy="wykonane-filtr"'):]
    filtr = filtr[:filtr.index('</form>')]
    assert filtr.count('min="2000-01-01" max="2099-12-31"') == 2
    assert html.count('min="2000-01-01" max="2099-12-31"') == 2
    for id_ in ('lg-edytor-blad', 'lg-trasa-dodaj-blad', 'lg-pojazd-blad', 'lg-trasy-wykonane-opis'):
        assert 'id="%s"' % id_ in html, id_
    assert "'lg-pojazd-blad'" in _plik('static', 'js', 'logistics-fleet.js')


def test_plik_tras_nie_wczytal_sie_to_blad_a_nie_czekanie():
    """m6: loader stawia data-lg-trasy-blad, „Dodaj do trasy…” mówi o błędzie."""
    assert "setAttribute('data-lg-trasy-blad', '1')" in _plik('templates', 'logistics', 'tab_content.html')
    assert "hasAttribute('data-lg-trasy-blad')" in _funkcja(_plik('static', 'js', 'logistics.js'), 'dodajDoTrasy')


# ─── Runda 2 poprawek (oględziny N1–N9, przegląd kodu 1–6) ───

def test_fokus_listy_tras_i_wczytywanie_trasy():
    """N1, N6: przerysowana lista oddaje fokus tej samej trasie; otwarcie z listy → tytuł;
    w trakcie wczytywania formularz poprzedniej trasy jest inert, a sesja rośnie od razu."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    lista = _funkcja(trasy, 'renderujListe')
    assert "a.closest('[data-lg-trasa-id]')" in lista and 'nowa.focus(' in lista
    assert "{ fokus: true }" in _funkcja(trasy, 'naKlikPanelu')
    otworz = _funkcja(trasy, 'otworz')
    assert 'ustawWczytywanie(true)' in otworz
    assert otworz.index('stan.sesja += 1') < otworz.index("zapytanie('/routes/' + id")
    assert 'ustawWczytywanie(false)' in _funkcja(trasy, 'koniecWczytywania')


def test_runda_3_wczytywanie_i_nakladka():
    """Runda 3: inert tylko formularz, akcje, przystanki i „Do dodania” (× i „Wszystkie trasy”
    czynne); sesja wraca po nieudanym wczytaniu; po 404 fokus na sąsiedniej pozycji listy;
    komunikaty nakładki nieprzezroczyste, pusty kontener nie traci zapasu."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    wczytywanie = _funkcja(trasy, 'ustawWczytywanie')
    assert '[form, akcjeEl, podsumowanieEl, ukladEdytoraEl, kandydaciSekcja]' in wczytywanie
    assert 'trescEl' not in wczytywanie
    otworz = _funkcja(trasy, 'otworz')
    assert 'if (stan.sesja === sesjaProby) stan.sesja = sesjaWidocznej;' in otworz
    assert otworz.index('sasiadNaLiscie(id)') < otworz.index('usunZListy(id)') < otworz.index('fokusNaSasiada(sasiad)')
    assert 'if (zmieniony() && !zmianyPorzucone)' in _funkcja(trasy, 'pozwolOpuscic')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-komunikaty.lg-komunikaty--nakladka:empty {\n    display: flex;' in css
    nakladka = css[css.index('.logistics-tab .lg-komunikaty--nakladka > .lg-komunikat {'):]
    assert 'background-color: var(--il-bg-card, #fff);' in nakladka[:nakladka.index('}')]
    for odmiana in ('uwaga', 'blad'):
        assert '.logistics-tab .lg-komunikaty--nakladka > .lg-komunikat--%s {\n    background-image: linear-gradient(' % odmiana in css
    ladowanie = css[css.index('.logistics-tab .lg-edytor.is-laduje'):]
    ladowanie = ladowanie[:ladowanie.index('}')]
    assert 'pointer-events' not in ladowanie and 'lg-edytor-wstecz' not in ladowanie and 'lg-edytor-zamknij' not in ladowanie


def test_komunikaty_tras_i_floty_nie_przesuwaja_ukladu():
    """N3: kontenery komunikatów Tras i Floty na końcu paneli, jako nakładka sticky."""
    html = _plik('templates', 'logistics', 'tab_content.html')
    for widok, nastepny in (('routes', '{# ═══ PODZAKŁADKA FLOTA'), ('fleet', '{# ─── POPRAWKA ADRESU')):
        znacznik = 'class="lg-komunikaty lg-komunikaty--nakladka" data-lg-komunikaty="%s"' % widok
        assert html.count(znacznik) == 1, widok
        panel = html[html.index('data-logistics-view="%s"' % widok):html.index(nastepny)]
        assert panel.rstrip().endswith('</div>') and panel.index(znacznik) > panel.index('</section>'), widok
    regula = _plik('static', 'css', 'logistics-trasy.css')
    regula = regula[regula.index('.logistics-tab .lg-komunikaty--nakladka {'):]
    regula = regula[:regula.index('}')]
    assert 'position: sticky' in regula and 'height: 0' in regula


def test_przyciski_przystankow_czekaja_i_odmowy_z_kluczem_trasy():
    """N4, przegląd pkt 1 i 3: aria-disabled przystanków w trakcie zmiany, klucz błędu per trasa,
    dostępność nie kasuje walidacji pola."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    assert 'odswiezPrzyciskiPrzystankow();' in _funkcja(trasy, 'odswiezAkcje')
    assert "klucz: kluczBleduTrasy(ctx.klucz)" in _funkcja(trasy, 'mutacja')
    assert "rodzajBledu === 'konflikt' || rodzajBledu === 'dostepnosc'" in _funkcja(trasy, 'wczytajDostepnosc')
    assert "pokazBlad(blad.tekst, 'pole')" in _funkcja(trasy, 'fokusNaBledneZPola')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.lg-ikona-przycisk[aria-disabled="true"]' in css


def test_mapy_trzymaja_srodek_i_legenda_ma_limit():
    """N9 + N8: widoczna zmiana rozmiaru trzyma środek (poza pastylką), legenda tras przewijana."""
    mapa = _plik('static', 'js', 'logistics-map.js')
    zmiana = _funkcja(mapa, 'poZmianieRozmiaru')
    assert zmiana.count('invalidateSize({ pan: true, animate: false })') == 2
    assert 'pastylkaZmienia' in zmiana and 'invalidateSize({ pan: false })' not in zmiana
    assert 'invalidateSize({ pan: true, animate: false })' in _funkcja(_plik('static', 'js', 'logistics-routes.js'), 'naRozmiarMapki')
    css = _plik('static', 'css', 'logistics-trasy.css')
    legenda = css[css.index('.logistics-tab .lg-mapa-legenda--trasy {'):]
    legenda = legenda[:legenda.index('}')]
    assert 'max-height' in legenda and 'overflow-y: auto' in legenda


def test_komunikaty_geokodera_i_okno_adresu():
    """N5 + N7: komunikaty geokodera tylko na Dashboardzie; po odmowie zapisu adresu fokus w oknie."""
    lista = _plik('static', 'js', 'logistics.js')
    teraz = _funkcja(lista, 'zlokalizujTeraz')
    assert teraz.count("widok: 'dashboard'") == 2
    assert "el('adres-zapisz').focus();" in _funkcja(lista, 'zapiszAdres')


# ─── Fala poprawek po przeglądzie końcowym ───

def test_okno_odhaczenia_ze_swiezej_trasy():
    """Important: okno pobiera trasę przy otwarciu (odhaczenie czeka na listę), po odmowie
    409/422 albo niepewnej odpowiedzi pobiera ją od nowa z zachowaniem wyborów i mówi, co
    doszło i zniknęło; zamówienia z `niespakowane` odznaczone, tekst odmowy zostaje w oknie."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    przygotuj = _funkcja(trasy, 'przygotujWykonanie')
    assert 'await wczytajDoWykonania(w);' in przygotuj and 'Wczytywanie przystanków…' in przygotuj
    assert '(trasa.przystanki || []).map' not in przygotuj        # lista nie z kopii w edytorze
    wczytaj = _funkcja(trasy, 'wczytajDoWykonania')
    assert "zapytanie('/routes/' + w.id" in wczytaj and 'opisZmianPrzystankow(poprzednia, trasa)' in wczytaj
    assert 'w.wybory.set(Number(id), false)' in wczytaj and 'o.tekst' in wczytaj
    zatwierdz = _funkcja(trasy, 'zatwierdzWykonanie')
    assert 'e.dane.niespakowane' in zatwierdz and 'wczytajDoWykonania(w, {' in zatwierdz
    assert "c.checked && c.getAttribute('data-lg-mozna') === '1'" in zatwierdz
    przyciski = _funkcja(trasy, 'odswiezPrzyciskiWykonania')
    assert 'trwa || wczytuje || !aktywna' in przyciski and "c.getAttribute('data-lg-mozna') !== '1'" in przyciski
    assert 'wybory.set(Number(c.value), c.checked)' in trasy


def test_stan_pakowania_i_anulowane_przystanki():
    """I1/I5 (UI): stan pakowania w oknie, niespakowane i anulowane nieaktywne z wyjaśnieniem,
    numer z `pozycja` („—” dla anulowanego), plakietka „Anulowane” i szara stacja w edytorze
    i na mapach, liczba anulowanych w podsumowaniu, liczba pominiętych po eksporcie."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    for tekst in ("'niespakowane — '", 'wróci do puli bez trasy; spakuj na tablecie, żeby oznaczyć jako dostarczone',
                  "anulowane: 'zdejmiemy z trasy'", 'lg-plakietka-anulowane', 'lg-stacja--anulowana',
                  "X-Routimo-Pominiete", "' Pominięto '"):
        assert tekst in trasy, tekst
    assert "p.pozycja === null || p.pozycja === undefined ? '—'" in _funkcja(trasy, 'pozycjaWykonaniaHtml')
    assert "(mozna ? ' data-lg-mozna=\"1\"' : ' disabled')" in _funkcja(trasy, 'pozycjaWykonaniaHtml')
    assert 'Number(p.anulowane)' in _funkcja(trasy, 'renderujPodsumowanie')
    assert 'anulowane(z) ? null : (numer += 1)' in _funkcja(trasy, 'renderujPrzystanki')
    assert 'ikonaPrzystanku(p.pozycja, klasa, anulowany)' in _funkcja(_plik('static', 'js', 'logistics-map.js'),
                                                                     'narysujTrasy')
    css = _plik('static', 'css', 'logistics-trasy.css')
    for klasa in ('.lg-stacja--anulowana {', '.lg-przystanek--anulowany', '.lg-plakietka-anulowane {',
                  '.lg-wykonaj-pozycja--niespakowane {', '.lg-wykonaj-pozycja--anulowane', '.lg-przystanek-etap {'):
        assert klasa in css, klasa
    assert 'Dostarczone mogą być tylko zamówienia spakowane w całości.' in _plik('templates', 'logistics',
                                                                                'tab_content.html')


def test_granice_dat_trasy_w_formularzach():
    """M8 (UI): granice jak na serwerze (dziś − 1 rok … dziś + 2 lata, „do” najwyżej 31 dni po
    „od”), min/max pól liczone przy otwarciu formularza; filtr „Wykonane” bez tych granic."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    for stala in ('const LATA_WSTECZ = 1;', 'const LATA_NAPRZOD = 2;', 'const MAKS_ROZPIETOSC_DNI = 31;'):
        assert stala in trasy, stala
    assert 'ustawGraniceDat(form)' in _funkcja(trasy, 'wypelnijFormularz')
    assert 'ustawGraniceDat(formDodaj)' in _funkcja(trasy, 'otworzOknoDodawania')
    blad = _funkcja(trasy, 'bladFormularza')
    assert 'graniceDat()' in blad and 'roznicaDni(dane.date_from, dane.date_to) > MAKS_ROZPIETOSC_DNI' in blad
    assert "bladDaty(od, 'od', false)" in _funkcja(trasy, 'naWyslaniePanelu')     # filtr: bez granic trasy
    assert 'doDnia.max = ' in _funkcja(trasy, 'ustawGraniceDat')


def test_drobiazgi_przegladu_koncowego_interfejsu():
    """Minory 1–6 i 8 z przeglądu końcowego interfejsu, podpowiedź I3 i resztka Task 8."""
    trasy = _plik('static', 'js', 'logistics-routes.js')
    flota = _plik('static', 'js', 'logistics-fleet.js')
    # 1: klik w trasę na ekranie przerywa wczytywanie innej i przywraca jej sesję.
    otworz = _funkcja(trasy, 'otworz')
    wczesny = otworz[:otworz.index('if (!(await pozwolOpuscic())) return;')]
    assert 'przerwijWczytywanie();' in wczesny and 'stan.sesja = sesjaWidocznej;' in wczesny
    # 2: brak odpowiedzi / 5xx = dane od nowa, ostrzeżenie przed duplikatem.
    assert 'niepewnaOdpowiedz(e)' in _funkcja(trasy, 'mutacja') and 'Trasa mogła już powstać' in trasy
    assert 'niepewnaOdpowiedz(e)' in _funkcja(trasy, 'zapiszDodawanie')
    zapisz_pojazd = _funkcja(flota, 'zapisz')
    assert 'niepewnaOdpowiedz(err)' in zapisz_pojazd and 'wczytaj();' in zapisz_pojazd
    # 3: okno zamknięte w trakcie zapisu — zapis kończy się w tle i mówi o wyniku.
    assert "dialogDodaj.addEventListener('close', poZamknieciuOknaDodawania" in trasy
    assert 'dodawaniaWTle.add(d);' in _funkcja(trasy, 'poZamknieciuOknaDodawania')
    assert 'zakonczDodawanieWTle(d)' in _funkcja(trasy, 'zapiszDodawanie')
    assert "komunikat('blad', 'Nie zapisano pojazdu" in zapisz_pojazd
    # 4: Routimo — tylko prawdziwy arkusz.
    assert "typ.indexOf('spreadsheetml') === -1" in _funkcja(trasy, 'eksportujRoutimo')
    # 5: ładowność z wartością nieczytelną dla przeglądarki.
    assert 'poleLadownosci.validity.badInput' in _funkcja(flota, 'daneFormularza')
    # 6: podsumowanie bez aria-live.
    html = _plik('templates', 'logistics', 'tab_content.html')
    znacznik = html[html.index('<div class="lg-podsumowanie"'):]
    assert 'aria-live' not in znacznik[:znacznik.index('>')]
    # 8: odmowy dodawania z kluczem, filtr „Wykonane” przy odhaczonej trasie.
    assert "klucz: 'trasa-bledy-dodawania'" in _funkcja(trasy, 'pokazBledyDodawania')
    assert 'pasujeDoFiltraWykonanych(s, stan.filtrWykonanych)' in _funkcja(trasy, 'aktualizujNaLiscie')
    # I3: niezmieniony wyłączony pojazd/kierowca zostaje na trasie.
    assert 'Wybierz inny, żeby zapisać trasę.' not in trasy
    assert trasy.count('Zostaje na tej trasie; po zmianie nie wybierzesz go ponownie.') == 2
    # Resztka Task 8: błąd edytora przygasa razem z trasą, która ustępuje miejsca następnej.
    css = _plik('static', 'css', 'logistics-trasy.css')
    ladowanie = css[css.index('.logistics-tab .lg-edytor.is-laduje'):]
    assert '.lg-edytor-blad' in ladowanie[:ladowanie.index('}')]


def test_nowe_pliki_sprzataja_po_sobie():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    flota = _plik('static', 'js', 'logistics-fleet.js')
    for js, nazwa in ((trasy, 'LogisticsRoutes'), (flota, 'LogisticsFleet')):
        assert 'window.{0} && typeof window.{0}.zniszcz'.format(nazwa) in js, nazwa
        assert 'delete window.{}'.format(nazwa) in js, nazwa
    assert 'mapka.remove()' in trasy            # mapka edytora niszczona razem z edytorem
    assert "credentials: 'same-origin'" in trasy and "credentials: 'same-origin'" in flota
