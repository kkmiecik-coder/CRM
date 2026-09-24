# -*- coding: utf-8 -*-
"""Podgląd wymiaru na kafelku: pokazuje, nie zapisuje.

CZEGO TE TESTY NIE GWARANTUJĄ: że po zmianie selektora kafelek naprawdę
pokazuje inne liczby i że po odświeżeniu wraca do swojego wymiaru. Czytają
źródło jako tekst — w obrazie nie ma node'a. Dowodzi tego krok „obejrzyj
w przeglądarce" z Zadania 12, punkty o podglądzie (oraz krok 7 Zadania 9).

Fikstury i pomocnicze `zupa`, `css`, `js_bez_komentarzy` jak w
tests/test_uklad_widok.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from bs4 import BeautifulSoup
from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import reports_bp
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401,E402
from modules.users.models import User  # noqa: E402
from modules.clients.models import Client  # noqa: F401,E402
import modules.quotes.models  # noqa: F401,E402
from modules.quotes.models import QuoteStatus  # noqa: F401,E402

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATYKA_PRODUKCJI = os.path.join(KORZEN, 'modules', 'production', 'static')
SCIEZKA_CSS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'css', 'analiza.css')
SCIEZKA_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'analiza.js')


# --- fikstury: te same trzy co w tests/test_uklad_api.py --------------------
# Kopia, a nie import: pytest nie widzi fikstur spoza conftestu.

@pytest.fixture()
def app(monkeypatch):
    from modules.users.services.permission_service import PermissionService
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda user_id, module_key: True))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(reports_bp)
    produkcja = Blueprint('production', __name__, static_folder=STATYKA_PRODUKCJI,
                          static_url_path='/production/static')
    app.register_blueprint(produkcja, url_prefix='/production')
    app.jinja_loader = ChoiceLoader([
        DictLoader({'sidebar/sidebar.html': '<nav data-sidebar-zaslepka></nav>'}),
        app.jinja_loader,
    ])
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(User(email='kontroler@woodpower.pl', password='x',
                            role='admin', active=True))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    c = app.test_client()
    with c.session_transaction() as sesja:
        sesja['user_email'] = 'kontroler@woodpower.pl'
    return c


@pytest.fixture()
def uzytkownik(app):
    return User.query.filter_by(email='kontroler@woodpower.pl').first()


def zapisz(client, pozycje):
    return client.post('/reports/api/uklad', json={'uklad': pozycje})


def zupa(client, adres='/reports/analiza'):
    odpowiedz = client.get(adres)
    assert odpowiedz.status_code == 200
    return BeautifulSoup(odpowiedz.get_data(as_text=True), 'html.parser')


def css():
    with open(SCIEZKA_CSS, encoding='utf-8') as plik:
        return plik.read()


def js_bez_komentarzy():
    """Źródło JS z WYCIĘTYMI komentarzami.

    Powód: w tym repo zdarzył się już test JS, który przechodził, bo szukanego
    napisu było w KOMENTARZU. Test, który da się spełnić komentarzem, nie jest
    testem."""
    with open(SCIEZKA_JS, encoding='utf-8') as plik:
        zrodlo = plik.read()
    zrodlo = re.sub(r'/\*.*?\*/', '', zrodlo, flags=re.S)
    zrodlo = re.sub(r'(?m)^\s*//.*$', '', zrodlo)
    return zrodlo


# --- gniazdo plakietki i zapisany wymiar w szablonie ------------------------

def test_kafelek_ma_miejsce_na_plakietke_podgladu(client):
    """Plakietkę wstawia JavaScript, ale jej gniazdo renderuje serwer —
    dzięki temu da się sprawdzić, że każdy kafelek wymiarowy je ma."""
    for kafelek in zupa(client).select('[data-kafelek]'):
        if KATALOG[kafelek.get('data-typ')].wymiarowy:
            assert kafelek.select_one('[data-plakietka]') is not None, \
                kafelek.get('data-klucz')


def test_plakietka_jest_pusta_i_schowana_na_starcie(client):
    for plakietka in zupa(client).select('[data-plakietka]'):
        assert plakietka.has_attr('hidden')
        assert plakietka.get_text(strip=True) == ''


def test_css_maluje_plakietke_bursztynem_a_nie_czerwienia():
    """Podgląd to stan, nie błąd. Czerwień jest zarezerwowana dla błędów."""
    tresc = css()
    blok = tresc[tresc.index('.an-kafelek__plakietka'):][:420]
    assert '#D98A16' in blok or 'warn-line' in blok
    assert '#B33A2B' not in blok


def test_css_chowa_plakietke_z_atrybutem_hidden():
    """Dopisane ponad plan. Plakietka ustawia `display`, a reguła autora
    o tej samej szczegółowości co `[hidden] { display: none }` przeglądarki
    WYGRYWA — bez jawnej reguły pusta plakietka stałaby na każdym kafelku
    (ta sama pułapka, co `.an-chip[hidden]` i `.an-mapa__dymek[hidden]`)."""
    assert '.an-kafelek__plakietka[hidden] { display: none; }' in css()


def test_js_pobiera_kafelek_z_endpointu_fragmentu():
    zrodlo = js_bez_komentarzy()
    assert 'data-url-kafelek' in zrodlo or 'urlKafelek' in zrodlo
    assert "'/reports/api/kafelek'" not in zrodlo, 'adres sklejony na sztywno'


def test_strona_niesie_adresy_fragmentow_z_url_for(client):
    """Dopisane ponad plan: JS bierze adresy z atrybutów, więc strona musi
    je wypisać — inaczej podgląd pytałby o `null?typ=…`."""
    glowny = zupa(client).select_one('#analiza')
    assert glowny.get('data-url-kafelek') == '/reports/api/kafelek'
    assert glowny.get('data-url-siatka') == '/reports/api/siatka'


def test_js_wstawia_fragment_zamiast_budowac_karte():
    """Znaczniki kafelków generuje serwer. Budowanie ich tutaj byłoby drugim
    źródłem prawdy o wyglądzie całego pulpitu."""
    zrodlo = js_bez_komentarzy()
    assert 'function wymienKafelek(' in zrodlo
    assert 'replaceChild' in zrodlo


def test_js_rysuje_wymieniony_kafelek_ta_sama_funkcja_co_strona():
    """Bez tego powstałaby druga ścieżka rysowania: jedna dla pełnego
    ładowania, druga dla kafelka wstawionego w miejscu."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function wymienKafelek(')
    assert 'rysujKafelek(' in zrodlo[poczatek:poczatek + 900]


def test_js_nie_zapisuje_ukladu_przy_podgladzie():
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function podgladWymiaru(')
    assert 'zapiszUklad' not in zrodlo[poczatek:poczatek + 1200]


def test_js_nie_przeladowuje_strony_przy_podgladzie():
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function podgladWymiaru(')
    assert 'location.reload' not in zrodlo[poczatek:poczatek + 1200]


def test_js_mowi_uzytkownikowi_ze_to_tylko_podglad():
    """Bez tego zmiana wymiaru jest cichą pułapką: wygląda jak ustawienie,
    a znika po odświeżeniu."""
    zrodlo = js_bez_komentarzy()
    # Przegląd gałęzi, drobne 3: podgląd wraca do zapisanego wymiaru także
    # przy zmianie okresu i porównania (przywrocPodgladane) — dawne „po
    # odświeżeniu wróci" samo w sobie kłamało.
    assert "'podgląd — wróci „' + etykieta" in zrodlo
    assert "'\" po odświeżeniu lub zmianie okresu albo porównania'" in zrodlo
    assert 'po odświeżeniu wróci' not in zrodlo


def test_js_daje_droge_powrotu_do_zapisanego_wymiaru():
    assert 'data-wroc-do-zapisanego' in js_bez_komentarzy()


def test_js_pamieta_zapisany_wymiar_kafelka():
    """Zapisany wymiar trzeba znać, żeby napisać w plakietce, do czego wróci —
    i żeby „Wróć" miało dokąd wracać."""
    assert 'data-wymiar-zapisany' in js_bez_komentarzy()


def test_szablon_wypisuje_zapisany_wymiar_kafelka(client):
    """Źródłem jest SERWER, nie pierwsza wartość odczytana w JavaScripcie —
    inaczej po dwóch podglądach z rzędu »Wróć« wracałoby do poprzedniego
    podglądu, a nie do układu."""
    for kafelek in zupa(client).select('[data-kafelek]'):
        if KATALOG[kafelek.get('data-typ')].wymiarowy:
            assert kafelek.get('data-wymiar-zapisany') == kafelek.get('data-wymiar')


def test_w_trybie_edycji_plakietka_sie_nie_pojawia():
    """W trybie edycji ten sam selektor ustawia TRWAŁY wymiar (Zadanie 10),
    więc zdanie „po odświeżeniu wróci" byłoby nieprawdą."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function podgladWymiaru(')
    assert 'trybEdycji()' in zrodlo[poczatek:poczatek + 1200]


# --- dopisane ponad plan -----------------------------------------------------

def test_js_przywraca_podgladane_kafelki_przy_przeladowaniu_danych():
    """/api/analytics czyta układ Z BAZY i nie ma czym narysować kafelka
    w wymiarze podglądanym. Bez powrotu do zapisanego wymiaru kafelek po
    zmianie zakresu dat zostałby ze starymi liczbami, a plakietka kłamałaby
    dalej (Zadanie 9, krok 7, punkt 6)."""
    zrodlo = js_bez_komentarzy()
    zaladuj = zrodlo[zrodlo.index('function zaladuj('):]
    zaladuj = zaladuj[:zaladuj.index('fetch(')]
    assert 'przywrocPodgladane()' in zaladuj
    cialo = zrodlo[zrodlo.index('function przywrocPodgladane('):][:900]
    assert 'data-wymiar-zapisany' in cialo
    assert 'podgladWymiaru(' in cialo


def test_js_odrzuca_spozniona_odpowiedz_starszego_podgladu():
    """Dwa szybkie wybory w tym samym kafelku to dwa żądania. Odpowiedź na
    pierwsze, która przyjdzie PO drugim wyborze, nie może nadpisać wyniku —
    kafelek pokazałby przekrój, którego użytkownik już nie wybrał."""
    zrodlo = js_bez_komentarzy()
    cialo = zrodlo[zrodlo.index('function pobierzKafelek('):][:1600]
    assert 'numerZadania' in cialo


def test_js_wstawia_fragment_bez_innerhtml():
    """Fragment z serwera to czysty szkielet, ale i tak nie wchodzi przez
    innerHTML: DOMParser buduje go w osobnym, bezczynnym dokumencie. Dzięki
    temu zostaje w mocy niezmiennik z test_analiza_widok.py — ani jednego
    przypisania `.innerHTML =` w tym pliku."""
    zrodlo = js_bez_komentarzy()
    assert 'DOMParser' in zrodlo
    assert '.innerHTML' not in zrodlo


def test_js_niszczy_wykres_wymienianego_kafelka():
    """Chart.js trzyma wykres w swoim rejestrze także po wyjęciu kanwy ze
    strony — bez zniszczenia każda wymiana kafelka z wykresem to wyciek."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function wymienKafelek(')
    assert 'zniszczWykresyW(' in zrodlo[poczatek:poczatek + 900]


# --- poprawki z przeglądu partii C -------------------------------------------

def _cialo_funkcji(zrodlo, nazwa):
    """Ciało funkcji JS od nagłówka do klamry zamykającej na tym samym wcięciu.

    Wycinek „N znaków od nagłówka" potrafi zahaczyć o następną funkcję
    i przepuścić test, którego ciało badanej funkcji nie spełnia."""
    poczatek = zrodlo.index('function %s(' % nazwa)
    wiersz = zrodlo.rfind('\n', 0, poczatek) + 1
    wciecie = zrodlo[wiersz:poczatek]
    koniec = zrodlo.index('\n' + wciecie + '}', poczatek)
    return zrodlo[poczatek:koniec]


def test_zaladuj_uniewaznia_zadania_w_locie_przed_powrotem_podgladow():
    """Wyścig z przeglądu: podgląd B w locie z okresem P1 → zmiana okresu na
    P2 → zaladuj() pomijał kafelek (jego `data-wymiar` był jeszcze zapisany) →
    spóźniona odpowiedź P1 wymieniała kafelek → liczby z P1 pod nagłówkiem P2.

    Test sprawdza MECHANIZM, a nie samo słowo `numerZadania`: zaladuj() woła
    unieważnienie PRZED powrotem podglądów i przed pobraniem payloadu,
    a unieważnienie dla każdego kafelka z `aria-busy` podbija licznik zadań
    (spóźniona odpowiedź przestaje pasować), zdejmuje `aria-busy` i cofa
    selektor do wymiaru zapisanego."""
    zrodlo = js_bez_komentarzy()
    zaladuj = _cialo_funkcji(zrodlo, 'zaladuj')
    przed_fetch = zaladuj[:zaladuj.index('fetch(')]
    assert 'uniewaznijZadaniaKafelkow()' in przed_fetch
    assert przed_fetch.index('uniewaznijZadaniaKafelkow()') \
        < przed_fetch.index('przywrocPodgladane()')

    cialo = _cialo_funkcji(zrodlo, 'uniewaznijZadaniaKafelkow')
    assert "getAttribute('aria-busy') !== 'true'" in cialo
    assert re.search(r'wezel\.numerZadania = \(wezel\.numerZadania \|\| 0\) \+ 1', cialo)
    assert 'zakonczZadanie(wezel)' in cialo
    assert "getAttribute('data-wymiar-zapisany')" in cialo
    assert "removeAttribute('aria-busy')" in _cialo_funkcji(zrodlo, 'zakonczZadanie')


def test_pobierz_kafelek_odrzuca_odpowiedz_dla_innego_okresu():
    """Druga linia obrony: stan (okres, segment) zapamiętany w chwili żądania
    i porównany z bieżącym, zanim odpowiedź wejdzie na ekran."""
    cialo = _cialo_funkcji(js_bez_komentarzy(), 'pobierzKafelek')
    assert re.search(r'var stanZadania = parametryStanu\(\)\.toString\(\)', cialo)
    assert 'parametryStanu().toString() !== stanZadania' in cialo
    # Porównanie stoi PRZED wymianą kafelka, nie po niej.
    assert cialo.index('!== stanZadania') < cialo.index('wymienKafelek(')


def test_selektor_kafelka_nie_przywraca_wartosci_po_odswiezeniu(client):
    """Firefox po F5 przywraca wartość <select>: po podglądzie i odświeżeniu
    selektor stałby na B, a kafelek pokazywałby A."""
    for wybor in zupa(client).select('select[data-selektor]'):
        assert wybor.get('autocomplete') == 'off', wybor.get('data-selektor')


def test_js_zrownuje_selektory_z_wymiarem_kafelka_przy_starcie():
    zrodlo = js_bez_komentarzy()
    start = zrodlo[zrodlo.index("addEventListener('DOMContentLoaded'"):]
    assert 'zrownajSelektory()' in start
    assert 'przywrocSelektor' in _cialo_funkcji(zrodlo, 'zrownajSelektory')
    ustaw = _cialo_funkcji(zrodlo, 'przywrocSelektor')
    assert "getAttribute('data-wymiar')" in ustaw


def test_js_czyta_json_dopiero_po_sprawdzeniu_typu_odpowiedzi():
    """502 z nginx to strona HTML — `odp.json()` dawało na pasku angielski
    komunikat parsera. Każde żądanie modułu idzie przez `odpowiedzJson`,
    który najpierw patrzy na content-type i mówi po polsku."""
    zrodlo = js_bez_komentarzy()
    cialo = _cialo_funkcji(zrodlo, 'odpowiedzJson')
    assert cialo.index("'content-type'") < cialo.index('odp.json()')
    assert 'opisStatusu(' in cialo
    for funkcja in ('pobierzKafelek', 'zapiszUklad'):
        assert '.then(odpowiedzJson)' in _cialo_funkcji(zrodlo, funkcja), funkcja
    # Poza odpowiedzJson i zaladuj (które sprawdza odp.ok przed .json())
    # nikt nie woła .json() na surowej odpowiedzi.
    reszta = zrodlo.replace(cialo, '').replace(_cialo_funkcji(zrodlo, 'zaladuj'), '')
    assert 'odp.json()' not in reszta
    assert 'serwer odpowiedział błędem' in _cialo_funkcji(zrodlo, 'opisStatusu')


def test_plakietka_stoi_pod_naglowkiem_karty(client):
    """Anatomia karty z makiety jest wiążąca: karta zaczyna się nagłówkiem.
    Plakietka nad tytułem odrywała go od selektora, którego dotyczy."""
    for plakietka in zupa(client).select('[data-plakietka]'):
        poprzedni = plakietka.find_previous_sibling(True)
        assert poprzedni is not None and 'an-karta__glowa' in (poprzedni.get('class') or [])


def test_wyjscia_kafelkow_bez_wymiaru_biora_przekroj_z_katalogu(client):
    """Kafelki bez wymiaru (KPI, Statystyki, Lejek) prowadzą do Eksploratora
    w domyślnym przekroju kanałów — z katalogu, nie z napisu w szablonie."""
    sciezka = os.path.join(KORZEN, 'modules', 'reports', 'templates',
                           'analiza', '_kafelki.html')
    with open(sciezka, encoding='utf-8') as plik:
        assert "'order_source'" not in plik.read()
    domyslny = KATALOG['kanal'].domyslny_wymiar
    strona = zupa(client)
    for typ in ('kpi', 'wnioski', 'lejek'):
        kafelek = strona.select_one(f'[data-kafelek][data-typ="{typ}"]')
        wyjscie = kafelek.select_one('a[data-wyjscie-miara]')
        assert wyjscie.get('data-wyjscie-wymiar') == domyslny
        assert f'wymiar={domyslny}' in wyjscie.get('href')
