# -*- coding: utf-8 -*-
"""Tryb edycji układu: struktura źródła i kontrakt z JavaScriptem.

W repozytorium NIE MA testu uruchamiającego JavaScript — obraz nie ma node'a.
Sprawdzamy więc strukturę HTML-a (która jest prawdziwa: renderuje ją serwer)
oraz obecność mechanizmów w źródle JS, Z WYCIĘTYMI KOMENTARZAMI.

CZEGO TE TESTY NIE GWARANTUJĄ — i to jest ważniejsze niż to, co gwarantują:
- że przeciąganie działa. Nie da się tego sprawdzić bez przeglądarki.
- że przycisk „Przenieś wcześniej" naprawdę przenosi. Test widzi, że przycisk
  ISTNIEJE i że w JS jest jego obsługa. Obecność elementu to nie używalność —
  zakładka była już raz całkowicie martwa przy zielonym pakiecie 3000 testów.
- że fokus wraca na przeniesiony kafelek.
Dowodzi tego WYŁĄCZNIE krok „obejrzyj w przeglądarce" z Zadania 12.

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
from modules.reports.uklad import KATALOG, UKLAD_DOMYSLNY  # noqa: F401

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


# --- fikstury: te same co w tests/test_uklad_widok.py -----------------------
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


def cialo_funkcji(zrodlo, nazwa):
    """Ciało funkcji JS od nagłówka do klamry zamykającej na tym samym wcięciu.

    Wycinek „N znaków od nagłówka" potrafi zahaczyć o następną funkcję
    i przepuścić test, którego ciało badanej funkcji nie spełnia."""
    poczatek = zrodlo.index('function %s(' % nazwa)
    wiersz = zrodlo.rfind('\n', 0, poczatek) + 1
    wciecie = zrodlo[wiersz:poczatek]
    koniec = zrodlo.index('\n' + wciecie + '}', poczatek)
    return zrodlo[poczatek:koniec]


# --- wejście w tryb edycji --------------------------------------------------

def test_przycisk_edytuj_widok_stoi_na_samym_dole_strony(client):
    """Rozstrzygnięcie 5: »Na samym dole dać przycisk Edytuj widok«."""
    strona = zupa(client)
    przycisk = strona.select_one('#an-edytuj')
    assert przycisk is not None
    assert przycisk.get_text(strip=True) == 'Edytuj widok'
    siatka = strona.select_one('#an-siatka')
    # Pasek edycji stoi PO siatce w kolejności dokumentu.
    assert siatka in przycisk.find_parent('main').find_all('div', recursive=True)
    assert list(siatka.next_elements).count(przycisk) == 1


def test_pasek_edycji_jest_schowany_w_trybie_podgladu(client):
    assert zupa(client).select_one('#an-edycja-pasek').has_attr('hidden')


def test_pasek_edycji_ma_trzy_wyjscia(client):
    pasek = zupa(client).select_one('#an-edycja-pasek')
    etykiety = [b.get_text(strip=True) for b in pasek.select('button')]
    assert etykiety == ['Przywróć domyślny', 'Anuluj', 'Zapisz układ']


def test_licznik_zmian_oglasza_sie_czytnikom_ekranu(client):
    """Dopisane ponad plan. Bursztyn widzi oko; czytnik ekranu musi usłyszeć
    „Niezapisane zmiany w układzie" — inaczej użytkownik klawiatury nie wie,
    że przeniesienie się udało."""
    assert zupa(client).select_one('#an-edycja-licznik').get('role') == 'status'


# --- narzędzia kafelka ------------------------------------------------------

def test_kazdy_kafelek_ma_narzedzia_przeniesienia_i_usuniecia(client):
    for kafelek in zupa(client).select('[data-kafelek]'):
        narzedzia = kafelek.select_one('.an-kafelek__narzedzia')
        assert narzedzia is not None, kafelek.get('data-klucz')
        assert narzedzia.select_one('[data-ruch="wczesniej"]') is not None
        assert narzedzia.select_one('[data-ruch="pozniej"]') is not None
        assert narzedzia.select_one('.an-kafelek__usun') is not None


def test_narzedzia_sa_schowane_w_trybie_podgladu(client):
    for narzedzia in zupa(client).select('.an-kafelek__narzedzia'):
        assert narzedzia.has_attr('hidden')


def test_narzedzia_to_zwykle_przyciski_a_nie_divy(client):
    """Zwykły <button> działa z klawiatury i z czytnikiem ekranu bez ani jednej
    linii kodu obsługi klawiszy. To jest DROGA PODSTAWOWA, nie awaryjna —
    natywne przeciąganie HTML5 nie działa dotykiem, a pulpit bywa otwierany
    na tablecie."""
    for narzedzia in zupa(client).select('.an-kafelek__narzedzia'):
        for sterowanie in narzedzia.find_all(True, recursive=False):
            assert sterowanie.name == 'button', sterowanie
            assert sterowanie.get('type') == 'button'


def _nazwa_widoczna(kafelek):
    """Tytuł karty i etykieta wybranego wymiaru — to, co widzi oko."""
    tytul = kafelek.select_one('.an-karta__tytul')
    # Etykieta selektora WYMIARU — nie podziału lejka, który ma własny.
    wybor = kafelek.select_one('select[data-selektor]')
    wymiar = (wybor.find_parent(class_='an-sel-opak').select_one('.an-sel-etykieta')
              if wybor is not None else None)
    czesci = [tytul.get_text(strip=True) if tytul else None,
              wymiar.get_text(strip=True) if wymiar else None]
    return [c for c in czesci if c]


def test_kazde_narzedzie_mowi_ktorego_kafelka_dotyczy(client):
    """Przegląd gałęzi, W4. Do przeglądu każdy z jedenastu kafelków miał trzy
    przyciski o IDENTYCZNYCH nazwach („Usuń kafelek"), a selektor zawsze
    „Wymiar kafelka" — użytkownik czytnika ekranu nie wiedział, co usuwa ani
    co przestawia. Nazwa ma zawierać to, co widać na karcie: tytuł i etykietę
    wymiaru (KPI nie ma tytułu — tam nazwa z katalogu)."""
    strona = zupa(client)
    wszystkie = []
    for kafelek in strona.select('[data-kafelek]'):
        przyciski = kafelek.select('.an-kafelek__narzedzia button')
        etykiety = [b.get('aria-label') for b in przyciski]
        assert etykiety[0].startswith('Przenieś wcześniej kafelek »'), etykiety
        assert etykiety[1].startswith('Przenieś później kafelek »'), etykiety
        assert etykiety[2].startswith('Usuń kafelek »'), etykiety
        nazwa = etykiety[2][len('Usuń kafelek »'):-1]
        for czesc in _nazwa_widoczna(kafelek):
            assert czesc in nazwa, (kafelek.get('data-klucz'), czesc, nazwa)
        if kafelek.get('data-typ') == 'kpi':
            assert nazwa == KATALOG['kpi'].nazwa
        wybor = kafelek.select_one('select[data-selektor]')
        if wybor is not None:
            assert wybor.get('aria-label') == f'Wymiar kafelka »{nazwa}«'
        wszystkie.append(nazwa)
    # Układ domyślny: tyle RÓŻNYCH nazw, ile kafelków (od partii E dziesięć).
    assert len(set(wszystkie)) == len(wszystkie) == len(UKLAD_DOMYSLNY), wszystkie


def test_nazwa_kafelka_idzie_za_wymiarem(client):
    """Po zmianie wymiaru kafelek przychodzi z serwera od nowa (/api/kafelek),
    więc nazwa narzędzi mówi o NOWYM wymiarze, a nie o starym."""
    html = client.get('/reports/api/kafelek?typ=kanal&wymiar=caretaker').get_json()['html']
    kafelek = BeautifulSoup(html, 'html.parser').select_one('[data-kafelek]')
    usun = kafelek.select_one('.an-kafelek__usun').get('aria-label')
    assert usun == 'Usuń kafelek »Sprzedaż netto według: Opiekun«'


def test_js_po_usunieciu_nie_stawia_fokusu_na_usun_sasiada():
    """Przegląd gałęzi, W4: po Enter na „Usuń" fokus przechodził na „Usuń"
    następnego kafelka i drugi Enter z rozpędu kasował kolejny. Teraz fokus
    idzie na pierwszy przycisk przenoszenia sąsiada (jego nazwa mówi, gdzie
    użytkownik jest), a bez sąsiadów — na „+"."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'usunKafelek')
    fokus = cialo[cialo.index('var sasiad'):]
    assert "sasiad.querySelector('[data-ruch=\"wczesniej\"]')" in fokus
    assert '.an-kafelek__usun' not in fokus


def test_narzedzia_stoja_przed_naglowkiem_karty(client):
    """Dopisane ponad plan. Pasek narzędzi stoi W PRZEPŁYWIE karty, nad
    nagłówkiem — nakładka w rogu zakrywałaby koniec dłuższych tytułów."""
    for kafelek in zupa(client).select('[data-kafelek]'):
        pierwszy = kafelek.find(True, recursive=False)
        assert 'an-kafelek__narzedzia' in (pierwszy.get('class') or []), kafelek.get('data-klucz')


def test_css_daje_narzedziom_pole_dotyku_44px():
    """WCAG 2.5.5. Reguła »min 48 px« z feedback_station_design dotyczy ekranów
    stanowiskowych w hali — to nimi nie jest — ale 44 px to i tak dwa razy
    więcej niż ikonki w stopkach kart."""
    tresc = css()
    blok = tresc[tresc.index('.an-kafelek__narzedzia'):]
    assert 'min-width: 44px' in blok and 'min-height: 44px' in blok


def test_css_chowa_elementy_edycji_z_atrybutem_hidden():
    """Dopisane ponad plan. Reguła autora z `display` wygrywa z `[hidden]`
    przeglądarki — bez jawnych reguł schowany pasek, schowane narzędzia,
    schowana podpowiedź i schowany „Edytuj widok" stałyby na ekranie."""
    tresc = css()
    for regula in ('.an-kafelek__narzedzia[hidden] { display: none; }',
                   '.an-kafelek__podpowiedz[hidden] { display: none; }',
                   '.an-edycja__pasek[hidden]', '.an-edycja__potwierdzenie[hidden]',
                   '.analiza .an-btn[hidden]'):
        assert regula in tresc, regula


# --- JS: przenoszenie, usuwanie, przeciąganie -------------------------------

def test_js_obsluguje_przyciski_przeniesienia():
    zrodlo = js_bez_komentarzy()
    assert "data-ruch" in zrodlo
    assert 'przeniesKafelek' in zrodlo


def test_js_przenosi_kafelek_w_domie_a_nie_w_osobnej_liscie():
    """DOM jest jedynym źródłem prawdy o układzie — druga kopia w zmiennej
    rozjechałaby się przy pierwszym błędzie, a użytkownik widzi DOM."""
    zrodlo = js_bez_komentarzy()
    assert 'insertBefore' in zrodlo


def test_js_przywraca_fokus_po_przeniesieniu():
    """insertBefore na podpiętym węźle usuwa go i wstawia od nowa, więc fokus
    ucieka na <body> i DRUGA strzałka z rzędu nie działa. Bez tego kroku
    przenoszenie z klawiatury jest bezużyteczne."""
    zrodlo = js_bez_komentarzy()
    assert '.focus()' in zrodlo
    obsluga = cialo_funkcji(zrodlo, 'podepnijEdycje')
    assert "querySelector('[data-ruch=\"' + kierunek + '\"]').focus()" in obsluga


def test_js_nie_wylacza_strzalki_atrybutem_disabled():
    """Dopisane ponad plan. Granice (pierwszy kafelek „wcześniej", ostatni
    „później") są oznaczone `aria-disabled`, nie `disabled` — przycisk
    z `disabled` gubi fokus dokładnie wtedy, gdy kafelek dojedzie do brzegu."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'odswiezGraniceRuchu')
    assert "setAttribute('aria-disabled'" in cialo
    assert '.disabled' not in cialo


def test_js_wlacza_przeciaganie_tylko_w_trybie_edycji():
    zrodlo = js_bez_komentarzy()
    assert 'draggable' in zrodlo
    assert 'dragstart' in zrodlo and 'dragover' in zrodlo and 'drop' in zrodlo
    obsluga = cialo_funkcji(zrodlo, 'podepnijEdycje')
    poczatek = obsluga.index("'dragstart'")
    assert 'trybEdycji()' in obsluga[poczatek:poczatek + 200]


def test_js_podpina_edycje_na_korzeniu_a_nie_na_siatce():
    """Dopisane ponad plan. „Anuluj" i „Przywróć domyślny" podmieniają CAŁY
    węzeł siatki na przyniesiony z /api/siatka (patrz docstring api_siatka).
    Słuchacz przypięty do starej siatki zniknąłby razem z nią i po pierwszym
    anulowaniu strzałki przestałyby działać."""
    obsluga = cialo_funkcji(js_bez_komentarzy(), 'podepnijEdycje')
    for zdarzenie in ('click', 'dragstart', 'dragover', 'drop', 'dragend'):
        assert f"korzen.addEventListener('{zdarzenie}'" in obsluga, zdarzenie
    assert "getElementById('an-siatka').addEventListener" not in obsluga


def test_js_nie_siega_po_zadna_biblioteke_przeciagania():
    """Safari ITP blokuje CDN-y, a wciąganie SortableJS do vendora dla jednej
    funkcji to nowa zależność do utrzymania."""
    zrodlo = js_bez_komentarzy()
    for biblioteka in ('Sortable', 'dragula', 'interact.js', 'jquery'):
        assert biblioteka not in zrodlo


def test_strona_nie_laduje_zadnego_nowego_zasobu_zewnetrznego(client):
    hosty = set(re.findall(r'https?://([^/"\']+)',
                           client.get('/reports/analiza').get_data(as_text=True)))
    assert hosty <= {'fonts.googleapis.com', 'fonts.gstatic.com'}


def test_js_usuniety_kafelek_zwalnia_wykres_i_zadanie_w_locie():
    """Dopisane ponad plan. Chart.js trzyma wykres w rejestrze także po wyjęciu
    kanwy ze strony, a odpowiedź w locie usuniętego kafelka nie ma czego
    wymieniać."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'usunKafelek')
    assert 'zniszczWykresyW(wezel)' in cialo
    assert 'numerZadania' in cialo


# --- konwencja niezapisanych zmian ------------------------------------------

def test_css_uzywa_bursztynu_na_niezapisane_zmiany():
    """Ta sama konwencja, co narzędziownik arkusza. Czerwień jest ZAREZERWOWANA
    dla błędów."""
    tresc = css()
    blok = tresc[tresc.index('.an-edycja__pasek--zmiany'):][:400]
    assert '#FDEDCF' in blok or 'warn-bg' in blok
    assert '#B33A2B' not in blok and 'bad' not in blok


def test_w_trybie_edycji_selektor_ustawia_trwaly_wymiar():
    """Rozstrzygnięcie planu (R5): ten sam selektor zmienia znaczenie razem
    z trybem. Poza edycją to podgląd, w edycji — trwały wymiar, który dołącza
    do paczki. Alternatywa „usuń i dodaj z powrotem" kosztowałaby utratę
    miejsca kafelka w siatce przy poprawianiu jednej literówki."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function podgladWymiaru(')
    cialo = zrodlo[poczatek:poczatek + 1200]
    assert 'trybEdycji()' in cialo and 'oznaczZmiane()' in cialo


def test_kafelek_mowi_w_trybie_edycji_ze_wymiar_sie_zapisze(client):
    """Ta sama kontrolka, dwa znaczenia, to realne ryzyko — dlatego jest
    nazwane wprost na ekranie, a nie zostawione domysłowi."""
    strona = zupa(client)
    for kafelek in strona.select('[data-kafelek]'):
        if KATALOG[kafelek.get('data-typ')].wymiarowy:
            podpowiedz = kafelek.select_one('[data-podpowiedz-edycji]')
            assert podpowiedz is not None, kafelek.get('data-klucz')
            assert 'zapisze się razem z układem' in podpowiedz.get_text()


def test_podpowiedz_edycji_jest_schowana_w_trybie_podgladu(client):
    for podpowiedz in zupa(client).select('[data-podpowiedz-edycji]'):
        assert podpowiedz.has_attr('hidden')


def test_js_oznacza_niezapisane_zmiany_porownaniem_ze_stanem_wejsciowym():
    """Licznik operacji kłamałby: przeniesienie kafelka w lewo i z powrotem
    to zero zmian, a nie dwie. Porównujemy stan z migawką zrobioną przy
    wejściu w tryb edycji."""
    zrodlo = js_bez_komentarzy()
    assert 'migawka' in zrodlo


def test_js_liczy_zmiane_wymiaru_juz_w_chwili_wyboru():
    """Dopisane ponad plan. Uklad ze strony bierze wymiar W LOCIE (ten, o który
    kafelek właśnie poprosił), a nie ten, który jeszcze widać — inaczej przez
    ułamek sekundy pasek mówiłby „Bez zmian", a zapis wysłałby stary wymiar."""
    zrodlo = js_bez_komentarzy()
    assert 'wymiarKafelka(wezel)' in cialo_funkcji(zrodlo, 'ukladZeStrony')
    cialo = cialo_funkcji(zrodlo, 'wymiarKafelka')
    assert 'wymiarWLocie' in cialo and "'aria-busy'" in cialo
    podglad = cialo_funkcji(zrodlo, 'podgladWymiaru')
    # oznaczZmiane() stoi takze PRZED .then — w chwili wysłania żądania.
    assert podglad.index('oznaczZmiane()') < podglad.index('.then(')


# --- kolizja kluczy `typ:wymiar` w trybie edycji (rozstrzygnięcie 3) ---------

def test_wejscie_w_edycje_najpierw_cofa_podglady_do_ukladu_zapisanego():
    """Tryb edycji zaczyna się od UKŁADU ZAPISANEGO. Podgląd, który wszedłby
    w edycję, byłby drugim punktem startu — a podglądany wymiar mógł już
    należeć do innego kafelka tego samego typu."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'wlaczEdycje')
    cofniecie = cialo.index('podgladWymiaru(wezel, zapisany)')
    assert "getAttribute('data-wymiar-zapisany')" in cialo[:cofniecie]
    assert cofniecie < cialo.index("classList.add('analiza--edycja')")
    assert cofniecie < cialo.index('migawka =')
    # Migawka to uklad ZAPISANY — potwierdzony przez serwer, nie odczytany
    # z ekranu (przegląd gałęzi, W1; patrz testy „punktu odniesienia" niżej).
    assert 'migawka = odciskUkladu(ukladZapisany)' in cialo


def test_selektor_w_trybie_edycji_wylacza_wymiary_zajete_przez_inny_kafelek():
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'odswiezZajeteWymiary')
    assert 'opcja.disabled = cudzy' in cialo
    assert 'już na pulpicie' in cialo
    # Własny wymiar kafelka NIE jest dla niego zajęty.
    assert 'j !== i' in cialo
    # Poza trybem edycji wszystkie opcje wracają — tam selektor jest podglądem.
    assert 'trybEdycji()' in cialo
    assert 'odswiezZajeteWymiary()' in cialo_funkcji(zrodlo, 'oznaczZmiane')
    assert 'odswiezZajeteWymiary()' in cialo_funkcji(zrodlo, 'wylaczEdycje')


def test_selektor_w_trybie_edycji_nie_buduje_duplikatu():
    """Straż w obsłudze selektora: wymiar zajęty przez INNY kafelek tego typu
    cofa selektor, zamiast wysłać żądanie i zbudować duplikat."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'podepnijSelektory')
    straz = cialo.index('inny !== wezel')
    assert straz < cialo.index('podgladWymiaru(wezel, wybor.value)')
    assert 'trybEdycji()' in cialo[:straz]


# --- kafelki, których payload nie niesie --------------------------------------

def test_wypelnij_dociaga_kafelki_ktorych_payload_nie_niosl():
    """Dopisane ponad plan. /api/analytics liczy układ Z BAZY, a w trybie
    edycji na ekranie bywają kafelki dodane albo przestawione, których w bazie
    jeszcze nie ma. Po zmianie okresu zostałyby z liczbami starego okresu."""
    zrodlo = js_bez_komentarzy()
    wypelnij = cialo_funkcji(zrodlo, 'wypelnij')
    assert '!rysujKafelek(wezel, dane)' in wypelnij
    assert 'dociagnijBrakujace(' in wypelnij
    assert 'pobierzKafelek(' in cialo_funkcji(zrodlo, 'dociagnijBrakujace')
    rysuj = cialo_funkcji(zrodlo, 'rysujKafelek')
    assert 'return false' in rysuj and 'return true' in rysuj


# --- kafelek dodawania ------------------------------------------------------

def test_kafelek_dodawania_stoi_na_koncu_siatki(client):
    """Cytat użytkownika: »Jak mamy kafle to na końcu robimy taki szary kwadrat
    z dużym + i napisem dodaj statystykę«."""
    siatka = zupa(client).select_one('#an-siatka')
    dzieci = siatka.find_all(True, recursive=False)
    assert 'an-kafelek--dodaj' in (dzieci[-1].get('class') or [])


def test_kafelek_dodawania_ma_plus_i_napis(client):
    kafelek = zupa(client).select_one('.an-kafelek--dodaj')
    assert 'Dodaj statystykę' in kafelek.get_text()
    assert kafelek.select_one('.an-kafelek--dodaj__plus').get_text(strip=True) == '+'


def test_kafelek_dodawania_jest_schowany_w_trybie_podgladu(client):
    """Poza trybem edycji pulpit nie ma nosić stałego zaproszenia do edycji —
    wejście jest jedno i jest nim »Edytuj widok« na dole (rozstrzygnięcie 5)."""
    assert zupa(client).select_one('.an-kafelek--dodaj').has_attr('hidden')


def test_kafelek_dodawania_jest_widoczny_gdy_uklad_jest_pusty(client):
    """Jedyny wyjątek: pusty pulpit bez kafelka »+« byłby białą stroną bez
    żadnego wyjścia poza przyciskiem na samym dole."""
    zapisz(client, [])
    assert not zupa(client).select_one('.an-kafelek--dodaj').has_attr('hidden')


def test_kafelek_dodawania_to_przycisk(client):
    assert zupa(client).select_one('.an-kafelek--dodaj').name == 'button'


def test_kafelek_dodawania_nie_jest_kafelkiem_ukladu(client):
    """Dopisane ponad plan. „+" nie jedzie do zapisu (brak `data-kafelek`)
    i nie dostaje stylów kafelka układu (brak `.an-kafelek`)."""
    plus = zupa(client).select_one('#an-dodaj-kafelek')
    assert not plus.has_attr('data-kafelek')
    assert 'an-kafelek' not in (plus.get('class') or [])


def test_na_stronie_jest_dokladnie_jeden_kafelek_dodawania(client):
    """Rozstrzygnięcie dyspozytora: strona renderuje siatkę Z kafelkiem „+",
    `/api/siatka` BEZ niego — jeden węzeł na stronie, nigdy dwa."""
    assert len(zupa(client).select('#an-dodaj-kafelek')) == 1
    assert 'an-dodaj-kafelek' not in client.get('/reports/api/siatka').get_json()['html']


def test_css_chowa_kafelek_dodawania_i_modal_z_atrybutem_hidden():
    """Dopisane ponad plan. `.an-modal` ma position:fixed, inset:0 i display:
    flex — bez jawnej reguły `[hidden]` schowany modal przykrywałby CAŁE okno
    przyciemnieniem i łykał wszystkie kliknięcia (ta sama klasa błędu, co
    rozlany `.an-sel` z 23.09.2026)."""
    tresc = css()
    assert '.an-modal[hidden] { display: none; }' in tresc
    assert '.an-kafelek--dodaj[hidden] { display: none; }' in tresc


# --- modal ------------------------------------------------------------------

def test_modal_jest_w_zrodle_i_schowany(client):
    modal = zupa(client).select_one('#an-modal-dodaj')
    assert modal is not None and modal.has_attr('hidden')
    assert modal.get('role') == 'dialog'
    assert modal.get('aria-modal') == 'true'


def test_modal_ma_tytul_po_polsku(client):
    modal = zupa(client).select_one('#an-modal-dodaj')
    assert 'Dodaj statystykę' in modal.get_text()


def test_modal_ma_dwa_wyjscia(client):
    stopka = zupa(client).select_one('#an-modal-dodaj .an-modal__stopka')
    assert [b.get_text(strip=True) for b in stopka.select('button')] == ['Anuluj', 'Dodaj']


def test_selektor_wymiaru_w_modalu_nie_uzywa_klasy_an_sel(client):
    """`.an-sel` jest PRZEZROCZYSTY i ma inset:0 — poza kartą, bez opakowania
    `.an-sel-opak`, rozlałby się na całe okno i zabił stronę. Dokładnie to się
    stało 23.09.2026. W modalu używamy zwykłego, WIDOCZNEGO selecta."""
    modal = zupa(client).select_one('#an-modal-dodaj')
    for wybor in modal.select('select'):
        assert 'an-sel' not in (wybor.get('class') or [])
        assert 'an-modal__pole' in (wybor.get('class') or [])


def test_strona_niesie_liste_wymiarow_dla_modalu(client):
    """Lista wymiarów pochodzi z REJESTRU PÓL po stronie serwera, nie z napisów
    wpisanych w JavaScripcie."""
    assert 'data-wymiary=' in client.get('/reports/analiza').get_data(as_text=True)


def test_lista_wymiarow_modalu_jest_per_typ_i_z_etykietami(client):
    """Dopisane ponad plan. Karty kubełkowe mają własną, węższą listę
    z pseudo-wymiarem spoza rejestru — modal z pełną listą 19 wymiarów
    pozwoliłby dodać „Należności według: Gatunek", które serwer odrzuci
    (saldo żyje na zamówieniu)."""
    import json
    from modules.reports.uklad import wymiary_typu
    atrybut = zupa(client).select_one('#analiza').get('data-wymiary')
    wymiary = json.loads(atrybut)
    for klucz, typ in KATALOG.items():
        if typ.wymiarowy:
            assert [w['nazwa'] for w in wymiary[klucz]] == wymiary_typu(klucz), klucz
            assert all(w['etykieta'] for w in wymiary[klucz])
        else:
            assert klucz not in wymiary


# --- JS ---------------------------------------------------------------------

def test_js_buduje_liste_statystyk_z_katalogu_z_atrybutu():
    zrodlo = js_bez_komentarzy()
    assert "czytajJson('data-katalog'" in zrodlo
    assert "korzen.getAttribute(atrybut)" in cialo_funkcji(zrodlo, 'czytajJson')
    # Zero nazw statystyk wpisanych w JS — jedyne źródło to katalog z serwera.
    assert 'Lejek wycena' not in zrodlo


def test_js_wyszarza_typ_ktory_juz_jest_na_pulpicie():
    zrodlo = js_bez_komentarzy()
    assert 'już na pulpicie' in zrodlo
    cialo = cialo_funkcji(zrodlo, 'rysujListeModalu')
    assert '!typ.wielokrotny && typy.indexOf(typ.klucz) !== -1' in cialo
    assert 'pozycja.disabled = true' in cialo


def test_js_wylacza_w_modalu_pary_typ_wymiar_juz_obecne():
    """Rozstrzygnięcie 3 dyspozytora: modal wyłącza opcje, których
    `typ:wymiar` już jest na siatce — liczone z wymiarem W LOCIE, żeby
    zmiana wymiaru w trakcie pobierania też zajmowała miejsce."""
    zrodlo = js_bez_komentarzy()
    wymiary = cialo_funkcji(zrodlo, 'rysujWymiaryModalu')
    assert "zajete.indexOf(wybranyTyp.klucz + ':' + w.nazwa) !== -1" in wymiary
    assert 'opcja.disabled = true' in wymiary
    assert 'wymiarKafelka(w)' in cialo_funkcji(zrodlo, 'kluczeNaPulpicie')


def test_js_pilnuje_limitu_kafelkow_z_atrybutu_a_nie_z_liczby_w_kodzie():
    zrodlo = js_bez_komentarzy()
    assert 'data-maks-kafelkow' in zrodlo or 'maksKafelkow' in zrodlo
    assert ' 20' not in zrodlo.replace('  ', ' '), 'limit wpisany w JS na sztywno'


def test_limit_kafelkow_to_granica_a_nie_blad():
    """Dopisane ponad plan. Czerwień jest zarezerwowana dla błędów — pełny
    pulpit mówi o sobie bursztynem w modalu, nie czerwonym paskiem strony."""
    zrodlo = js_bez_komentarzy()
    for nazwa in ('otworzModalDodawania', 'rysujListeModalu'):
        assert 'pokazBlad(' not in cialo_funkcji(zrodlo, nazwa), nazwa
    assert "getElementById('an-modal-limit')" in cialo_funkcji(zrodlo, 'rysujListeModalu')


def test_js_wstawia_nowy_kafelek_przed_kafelkiem_dodawania():
    zrodlo = js_bez_komentarzy()
    assert 'an-kafelek--dodaj' in zrodlo
    cialo = cialo_funkcji(zrodlo, 'dodajKafelek')
    assert 'insertBefore(miejsce, plus)' in cialo


def test_nowy_kafelek_dostaje_dane_od_razu():
    """Kafelek dodany w trybie edycji przychodzi z `/api/kafelek` (Zadanie 8)
    gotowy i Z DANYMI — nie czeka na zapis układu. Pierwsza wersja planu miała
    tu szkielet z napisem „dane po zapisaniu"; rozstrzygnięcie użytkownika
    („Bez przeładowania, płynnie") ten kompromis usunęło."""
    zrodlo = js_bez_komentarzy()
    assert 'Dane pojawią się po zapisaniu układu' not in zrodlo
    assert 'pobierzKafelek(' in cialo_funkcji(zrodlo, 'dodajKafelek')


def test_nowy_kafelek_ma_miejsce_w_siatce_zanim_przyjda_dane():
    """Bez tego reszta kafelków podskakuje w chwili wstawienia i użytkownik
    traci z oczu to, co czytał."""
    zrodlo = js_bez_komentarzy()
    assert 'an-kafelek--wczytywanie' in zrodlo


def test_nieudane_dodanie_nie_zostawia_pustego_pudelka():
    """Dopisane ponad plan. Miejsce na kafelek, którego serwer nie oddał,
    znika z siatki — inaczej zostałoby na zawsze „Wczytywanie…"."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'pobierzKafelek')
    blad = cialo[cialo.index('.catch('):]
    assert "classList.contains('an-kafelek--wczytywanie')" in blad
    assert 'removeChild(wezel)' in blad


def test_modal_zamyka_escape_i_trzyma_fokus_w_oknie():
    """Dopisane ponad plan. aria-modal mówi czytnikowi, że reszta strony jest
    nieaktywna — Tab nie może na nią uciekać."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'naKlawiszModalu')
    assert "'Escape'" in cialo and "'Tab'" in cialo
    assert "addEventListener('keydown', naKlawiszModalu, true)" in \
        cialo_funkcji(zrodlo, 'otworzModalDodawania')


# --- stan pusty -------------------------------------------------------------

def test_pusty_uklad_pokazuje_blok_stanu_pustego(client):
    zapisz(client, [])
    strona = zupa(client)
    pusty = strona.select_one('#an-stan-pusty')
    assert pusty is not None and not pusty.has_attr('hidden')
    assert 'Pulpit jest pusty' in pusty.get_text()


def test_stan_pusty_ma_przycisk_przywrocenia_domyslnego(client):
    zapisz(client, [])
    pusty = zupa(client).select_one('#an-stan-pusty')
    assert 'Przywróć domyślny' in pusty.get_text()


def test_stan_pusty_jest_schowany_przy_niepustym_ukladzie(client):
    assert zupa(client).select_one('#an-stan-pusty').has_attr('hidden')


def test_stan_pusty_nie_jest_bledem(client):
    """Czerwień jest zarezerwowana dla błędów. Pusty pulpit to decyzja
    użytkownika, a nie awaria."""
    zapisz(client, [])
    pusty = zupa(client).select_one('#an-stan-pusty')
    assert pusty.get('role') != 'alert'
    assert 'an-blad' not in (pusty.get('class') or [])


def test_stan_pusty_ma_wyjscie_takze_przez_kafelek_dodawania(client):
    """Dopisane ponad plan. Pusty pulpit ma DWA wyjścia widoczne od razu:
    „Przywróć domyślny" w bloku i kafelek „+" w siatce."""
    zapisz(client, [])
    strona = zupa(client)
    assert not strona.select_one('#an-stan-pusty').has_attr('hidden')
    plus = strona.select_one('#an-siatka > #an-dodaj-kafelek')
    assert plus is not None and not plus.has_attr('hidden')


def test_plus_poza_trybem_edycji_najpierw_wchodzi_w_tryb_edycji():
    """Przegląd gałęzi, W1. „+" poza trybem edycji (stan pusty) otwierał okno
    BEZ wejścia w tryb: dodany kafelek nie trafiał do paczki, pasek nie
    bursztyniał, „Zapisz układ" nic nie wysyłał, a po F5 kafelka nie było.
    Kliknięcie ma NAJPIERW włączyć tryb edycji, dopiero potem otworzyć okno.

    Test czyta źródło — samo zachowanie potwierdza skrypt przeglądarki
    (s2/s2b: pusty → „+" → dodaj → „Zapisz" → F5 daje kafelek)."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'podepnijModal')
    obsluga = cialo[cialo.index("closest('#an-dodaj-kafelek')"):]
    assert 'if (!trybEdycji()) { wlaczEdycje(); }' in obsluga
    assert obsluga.index('wlaczEdycje()') < obsluga.index('otworzModalDodawania()')


def test_nowy_kafelek_nie_udaje_zapisanego():
    """W1: miejsce na dodawany kafelek nie dostaje `data-wymiar-zapisany` —
    zapisany jest dopiero po odpowiedzi serwera na „Zapisz układ"."""
    zrodlo = js_bez_komentarzy()
    assert 'data-wymiar-zapisany' not in cialo_funkcji(zrodlo, 'dodajKafelek')
    assert "nowy.removeAttribute('data-wymiar-zapisany')" in cialo_funkcji(zrodlo, 'wymienKafelek')


def test_brak_wiersza_to_nie_stan_pusty(client):
    """Brak wiersza ≠ pusty układ: kto nigdy nie zapisywał, dostaje układ
    domyślny, a nie pusty pulpit."""
    strona = zupa(client)
    assert len(strona.select('[data-kafelek]')) == len(UKLAD_DOMYSLNY)
    assert strona.select_one('#an-stan-pusty').has_attr('hidden')


# --- pominięte kafelki ------------------------------------------------------

def test_pominiete_kafelki_maja_swoj_komunikat(client, uzytkownik):
    from modules.reports.models_uklad import UkladDashboardu
    db.session.add(UkladDashboardu(
        user_id=uzytkownik.id,
        uklad=[{'typ': 'kpi', 'wymiar': None},
               {'typ': 'karta-ktorej-nie-ma', 'wymiar': None}]))
    db.session.commit()
    strona = zupa(client)
    pasek = strona.select_one('#an-pominiete')
    assert pasek is not None and not pasek.has_attr('hidden')
    assert '1' in pasek.get_text()
    assert pasek.select_one('#an-pominiete-liczba').get_text(strip=True) == '1'


def test_bez_pominietych_komunikat_jest_schowany(client):
    assert zupa(client).select_one('#an-pominiete').has_attr('hidden')


def test_komunikat_o_pominietych_nie_jest_bledem(client, uzytkownik):
    """Bursztyn, nie czerwień: to granica wiarygodności układu, nie awaria —
    ta sama zasada, co przy nadpłatach i uwadze lejka."""
    pasek = zupa(client).select_one('#an-pominiete')
    assert 'an-blad' not in (pasek.get('class') or [])
    assert 'an-info' in (pasek.get('class') or [])
    assert pasek.get('role') != 'alert'


# --- JS: zapis, anulowanie, przywrócenie ------------------------------------

def test_js_zapisuje_paczke_z_przycisku_zapisz_uklad():
    zrodlo = js_bez_komentarzy()
    assert 'an-uklad-zapisz' in zrodlo
    assert 'zapiszUklad(' in zrodlo
    assert "getElementById('an-uklad-zapisz').addEventListener('click', zapiszPaczke)" in zrodlo
    assert 'zapiszUklad(uklad' in cialo_funkcji(zrodlo, 'zapiszPaczke')


def test_js_nigdzie_nie_przeladowuje_strony():
    """Rozstrzygniecie uzytkownika: „Bez przeladowania, plynnie". Ani zapis,
    ani anulowanie, ani przywrocenie domyslnego nie maja prawa skoczyc strona
    ani zabrac pozycji przewijania."""
    zrodlo = js_bez_komentarzy()
    assert 'location.reload' not in zrodlo
    assert 'location.href =' not in zrodlo


def test_js_po_zapisie_nie_pobiera_siatki_od_nowa():
    """Po „Zapisz uklad" DOM jest juz dokladnie tym, co poszlo na serwer —
    kazdy kafelek przyszedl z /api/kafelek gotowy i z danymi. Ponowne pobieranie
    siatki byloby zadaniem, ktore niczego nie zmienia, i mrugnieciem ekranu."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index("getElementById('an-uklad-zapisz')")
    assert 'urlSiatka' not in zrodlo[poczatek:poczatek + 600]
    assert 'data-url-siatka' not in zrodlo[poczatek:poczatek + 600]
    # I mocniej: w całym ciele obsługi zapisu nie ma ani siatki, ani zaladuj().
    cialo = cialo_funkcji(zrodlo, 'zapiszPaczke')
    for zakazane in ('wymienSiatke(', 'data-url-siatka', 'zaladuj('):
        assert zakazane not in cialo, zakazane


def test_js_przywraca_zapisana_siatke_z_serwera_przy_anulowaniu():
    """„Anuluj" musi cofnac przestawienia, usuniecia i dodania. Odtwarzanie
    ich z kopii DOM-u byloby trzecia sciezka budowania tego samego widoku —
    siatke oddaje serwer, tym samym szablonem co strona."""
    zrodlo = js_bez_komentarzy()
    assert 'data-url-siatka' in zrodlo or 'urlSiatka' in zrodlo
    assert "'/reports/api/siatka'" not in zrodlo, 'adres sklejony na sztywno'
    assert 'wymienSiatke' in cialo_funkcji(zrodlo, 'anulujEdycje')


def test_js_po_wymianie_siatki_rysuje_ja_od_nowa():
    """Selektory i wykresy naleza do WYMIENIONYCH wezlow. Bez ponownego
    narysowania siatka po anulowaniu bylaby martwa — a to jest dokladnie ta
    klasa bledu, ktora raz juz zabila te zakladke przy zielonym pakiecie."""
    zrodlo = js_bez_komentarzy()
    poczatek = zrodlo.index('function wymienSiatke(')
    assert 'zaladuj()' in zrodlo[poczatek:poczatek + 1400]


def test_js_po_podmianie_siatki_przenosi_istniejacy_kafelek_dodawania():
    """Rozstrzygnięcie 2 dyspozytora: `/api/siatka` nie niesie kafelka „+",
    więc przeglądarka PRZENOSI istniejący węzeł na koniec nowej siatki — jeden
    węzeł, zero znaczników budowanych w JS. Test sprawdza kolejność: „+"
    trafia do nowej siatki (appendChild — zawsze na koniec) ZANIM stara
    zniknie z dokumentu."""
    zrodlo = js_bez_komentarzy()
    przenies = cialo_funkcji(zrodlo, 'przeniesDoSiatki')
    assert "stara.querySelector('.an-kafelek--dodaj')" in przenies
    assert 'nowa.appendChild(plus)' in przenies
    podmien = cialo_funkcji(zrodlo, 'podmienSiatke')
    assert podmien.index('przeniesDoSiatki(nowa, stara)') < podmien.index('replaceChild(nowa, stara)')
    # Nowa siatka wchodzi przez DOMParser + importNode, nie przez innerHTML.
    assert 'DOMParser' in podmien and 'importNode' in podmien
    # W całym pliku nikt nie buduje kafelka „+" od zera.
    assert "el('button', 'an-kafelek--dodaj" not in zrodlo
    assert "createElement('button')" not in zrodlo


def test_podmiana_siatki_zwalnia_stare_kafelki():
    """Dopisane ponad plan. Stare kafelki odchodzą razem z zadaniami w locie
    (spóźniona odpowiedź wymieniałaby węzeł w odpiętej siatce) i wykresami
    (rejestr Chart.js)."""
    podmien = cialo_funkcji(js_bez_komentarzy(), 'podmienSiatke')
    assert 'numerZadania' in podmien
    assert 'zniszczWykresyW(wezel)' in podmien
    assert 'schowajDymek()' in podmien


def test_js_pyta_o_potwierdzenie_przed_porzuceniem_zmian():
    zrodlo = js_bez_komentarzy()
    assert 'an-edycja-potwierdzenie' in zrodlo
    assert 'saZmiany()' in zrodlo
    anuluj = cialo_funkcji(zrodlo, 'anulujEdycje')
    assert anuluj.index('saZmiany()') < anuluj.index('pokazPotwierdzenie(')


def test_js_nie_uzywa_okien_przegladarki():
    """Ta strona ma już popover filtra i dymek mapy; trzeci rodzaj okna,
    narzucony przez przeglądarkę, byłby obcy i nie da się go ostylować."""
    zrodlo = js_bez_komentarzy()
    assert 'window.confirm' not in zrodlo and 'confirm(' not in zrodlo
    assert 'alert(' not in zrodlo


def test_js_przywraca_domyslny_pod_adresem_z_atrybutu():
    zrodlo = js_bez_komentarzy()
    assert 'data-url-uklad-domyslny' in zrodlo or 'urlUkladDomyslny' in zrodlo
    assert "'/reports/api/uklad/domyslny'" not in zrodlo


def test_js_przywraca_domyslny_zadaniem_json():
    """Przegląd gałęzi, D4: serwer odrzuca przywrócenie, które nie jest
    JSON-em (400). Bez nagłówka i ciała przycisk przestałby działać."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'przywrocDomyslny')
    assert "'Content-Type': 'application/json'" in cialo
    assert "body: '{}'" in cialo


def test_przywrocenie_domyslnego_z_paska_pyta_a_ze_stanu_pustego_tylko_poza_edycja():
    """„Przywróć domyślny" KASUJE zapisany układ. Z paska pyta tym samym
    wierszem, co porzucenie zmian.

    Przegląd gałęzi, W2: przycisk w bloku stanu pustego działał bez pytania
    TAKŻE w trybie edycji — a pusty pulpit w edycji to zwykle usunięte, ale
    niezapisane kafelki, więc kasował zapisany układ bez ostrzeżenia. Teraz
    w trybie edycji jest schowany (pasek ma własny, z pytaniem), a poza
    trybem edycji — gdzie pusty jest ZAPISANY układ i nie ma czego stracić —
    działa od razu. Dawna wersja tego testu wymuszała brak pytania także
    w trybie edycji."""
    zrodlo = js_bez_komentarzy()
    podpiecie = cialo_funkcji(zrodlo, 'podepnijZapisUkladu')
    z_paska = podpiecie[podpiecie.index("getElementById('an-uklad-domyslny')"):]
    z_paska = z_paska[:z_paska.index('});\n')]
    assert 'pokazPotwierdzenie(' in z_paska and 'przywrocDomyslny' in z_paska
    z_pustego = podpiecie[podpiecie.index("getElementById('an-stan-pusty-domyslny')"):]
    z_pustego = z_pustego[:z_pustego.index('    });')]
    assert 'pokazPotwierdzenie(' not in z_pustego
    assert 'if (trybEdycji()) { return; }' in z_pustego
    assert z_pustego.index('trybEdycji()') < z_pustego.index('przywrocDomyslny')
    # Schowanie w trybie edycji — przy każdym odświeżeniu stanu pustego,
    # także przy wejściu w tryb.
    stan = cialo_funkcji(zrodlo, 'odswiezStanPusty')
    assert "getElementById('an-stan-pusty-domyslny')" in stan
    assert 'przywroc.hidden = trybEdycji()' in stan
    assert 'odswiezStanPusty()' in cialo_funkcji(zrodlo, 'wlaczEdycje')


def test_punkt_odniesienia_zmian_pochodzi_z_serwera(client):
    """Przegląd gałęzi, W1. Stan „zapisany" = ostatni układ POTWIERDZONY przez
    serwer: z renderu strony, a potem z odpowiedzi udanego zapisu albo
    wymiany siatki — nigdy odczytany z ekranu przy wejściu w edycję."""
    import json
    zapisz(client, [{'typ': 'lejek', 'wymiar': None},
                    {'typ': 'kanal', 'wymiar': 'caretaker'}])
    atrybut = zupa(client).select_one('#analiza').get('data-uklad-zapisany')
    assert json.loads(atrybut) == [{'typ': 'lejek', 'wymiar': None},
                                   {'typ': 'kanal', 'wymiar': 'caretaker'}]
    zrodlo = js_bez_komentarzy()
    assert "var ukladZapisany = czytajJson('data-uklad-zapisany', [])" in zrodlo
    assert 'ukladZapisanyZeStrony' not in zrodlo
    # Po udanym zapisie i po wymianie siatki — z odpowiedzi serwera.
    po_zapisie = cialo_funkcji(zrodlo, 'zapiszPaczke')
    assert 'ukladZapisany = (tresc && Array.isArray(tresc.uklad)) ? tresc.uklad : uklad' \
        in po_zapisie[po_zapisie.index('zapiszUklad('):]
    assert 'ukladZapisany = tresc.uklad' in cialo_funkcji(zrodlo, 'wymienSiatke')


def test_odpowiedzi_serwera_niosa_zapisany_uklad(client):
    """Źródło punktu odniesienia po zapisie i po „Odrzuć"/„Przywróć"."""
    odp = zapisz(client, [{'typ': 'kpi', 'wymiar': None}])
    assert odp.get_json()['uklad'] == [{'typ': 'kpi', 'wymiar': None}]
    assert client.get('/reports/api/siatka').get_json()['uklad'] == \
        [{'typ': 'kpi', 'wymiar': None}]
    client.post('/reports/api/uklad/domyslny', json={})
    domyslny = client.get('/reports/api/siatka').get_json()['uklad']
    assert [p['typ'] for p in domyslny] == [i.typ for i in UKLAD_DOMYSLNY]


def test_przywrocenie_domyslnego_oddaje_uklad_ktory_serwer_teraz_podaje(client):
    """Weryfikacja poprawek, znalezisko 2. Przeglądarka ustawia punkt
    odniesienia licznika zmian z odpowiedzi SAMEGO przywrócenia — nie czeka
    na siatkę, która może nie przyjść (502 w trakcie restartu). Odpowiedź
    niesie więc układ, który serwer od teraz podaje: ten sam, co /api/siatka."""
    zapisz(client, [{'typ': 'lejek', 'wymiar': None},
                    {'typ': 'kanal', 'wymiar': 'caretaker'}])
    odp = client.post('/reports/api/uklad/domyslny', json={})
    assert odp.status_code == 200
    tresc = odp.get_json()
    assert tresc['przywrocono'] is True
    assert tresc['uklad'] == client.get('/reports/api/siatka').get_json()['uklad']
    assert [p['typ'] for p in tresc['uklad']] == [i.typ for i in UKLAD_DOMYSLNY]
    # Drugie przywrócenie (nic już nie ma do skasowania) — ta sama postać.
    ponownie = client.post('/reports/api/uklad/domyslny', json={}).get_json()
    assert ponownie['przywrocono'] is False
    assert ponownie['uklad'] == tresc['uklad']


def test_przywrocenie_od_razu_przestawia_punkt_odniesienia():
    """Weryfikacja poprawek, znalezisko 2. Do tej poprawki `ukladZapisany`
    zmieniał się dopiero po udanym /api/siatka. Gdy POST przywrócenia
    przeszedł (wiersz skasowany), a siatka odpowiedziała 502, ekran pokazywał
    dalej własny układ z licznikiem „Bez zmian", „Zapisz układ" nie wysyłał
    nic, a po F5 użytkownik tracił układ, który na ekranie „zapisał".
    Punkt odniesienia przestawia teraz SAMA odpowiedź przywrócenia — przed
    wymianą siatki — a w trybie edycji licznik liczy się od niego od nowa."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'przywrocDomyslny')
    sukces = cialo[cialo.index('.then(odpowiedzJson).then(function (tresc)'):]
    assert sukces.index('ustawUkladZapisany(tresc && tresc.uklad') < sukces.index('wymienSiatke(')
    ustaw = cialo_funkcji(zrodlo, 'ustawUkladZapisany')
    assert 'Array.isArray(uklad) ? uklad : null' in ustaw
    assert 'migawka = odciskUkladu(ukladZapisany)' in ustaw
    assert 'oznaczZmiane()' in ustaw
    # Nieznany punkt odniesienia (odpowiedź bez układu) nigdy nie pasuje do
    # ekranu — „Zapisz" wyśle wtedy POST, zamiast udawać, że nie ma czego.
    odcisk = cialo_funkcji(zrodlo, 'odciskUkladu')
    assert odcisk.index('!Array.isArray(uklad)') < odcisk.index('uklad.map(')
    # Komunikat po nieudanej siatce mówi prawdę: przywrócenie SIĘ UDAŁO.
    assert 'Układ domyślny został przywrócony, ale nie udało się go wczytać' in cialo
    assert 'odśwież stronę' in cialo
    siatka = cialo_funkcji(zrodlo, 'wymienSiatke')
    assert 'pokazBladPaska(zdanieBledu(prefiksBledu ||' in siatka


def test_blad_kafelka_w_trakcie_oczekiwania_zapisu_przerywa_zapis():
    """Weryfikacja poprawek, znalezisko 5 (W3 niedomknięte). Zapis czeka na
    kafelki w locie. Gdy w tym czasie dodanie albo zmiana wymiaru padła,
    komunikat trafiał do paska, a zaraz potem `wylaczEdycje` go kasował:
    kafelek „migał i znikał", a zmiana wymiaru wracała po cichu. Teraz zapis
    liczy błędy kafelków z chwili kliknięcia i po czekaniu — jeśli przybyło
    choć jeden — przerywa się PRZED zamknięciem trybu i PRZED POST-em,
    a komunikat zostaje w pasku."""
    zrodlo = js_bez_komentarzy()
    assert 'var bledyKafelkow = 0;' in zrodlo
    pobierz = cialo_funkcji(zrodlo, 'pobierzKafelek')
    blad = pobierz[pobierz.index('.catch('):]
    assert blad.index('if (wezel.numerZadania !== numer) { return null; }') \
        < blad.index('bledyKafelkow += 1;')
    # Licznik rośnie przy KAŻDEJ porażce, przed rozgałęzieniem na dodanie
    # i zmianę wymiaru.
    assert blad.index('bledyKafelkow += 1;') < blad.index("classList.contains('an-kafelek--wczytywanie')")
    paczka = cialo_funkcji(zrodlo, 'zapiszPaczke')
    przed = paczka.index('var bledyPrzed = bledyKafelkow;')
    assert przed < paczka.index('akcjaPaska(') < paczka.index('poWczytaniuKafelkow()')
    po = paczka[paczka.index('poWczytaniuKafelkow()'):]
    straz = po.index('if (bledyKafelkow !== bledyPrzed) {')
    koniec = po.index('return false;', straz)
    assert straz < po.index('wylaczEdycje()') and straz < po.index('zapiszUklad(')
    blok = po[straz:koniec]
    assert 'wylaczEdycje' not in blok
    assert "pokazBladPaska('Układu nie zapisano. '" in blok


def test_zapis_bez_zmian_nie_zamraza_ukladu_domyslnego():
    """Dopisane ponad plan. Brak wiersza w bazie znaczy „idź za układem
    domyślnym, także przyszłym" (R2 planu). „Zapisz układ" bez żadnej zmiany
    zapisałby dzisiejszy domyślny jako prywatny i odciął użytkownika od jego
    przyszłych zmian — więc bez zmian (i bez pominiętych do usunięcia) tylko
    zamyka tryb edycji."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'zapiszPaczke')
    straz = cialo.index("!saZmiany() && document.getElementById('an-pominiete').hidden")
    assert straz < cialo.index('zapiszUklad(')
    assert 'wylaczEdycje()' in cialo[straz:cialo.index('zapiszUklad(')]


def test_zapis_czeka_na_kafelki_w_locie_i_nie_wysyla_duplikatu():
    """Rozstrzygnięcie 3 dyspozytora: zapis nigdy nie wysyła duplikatu. Plus:
    kafelek w trakcie zmiany wymiaru pokazuje jeszcze stary stan, więc zapis
    czeka, aż wszystkie żądania kafelków się skończą."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'zapiszPaczke')
    assert cialo.index('poWczytaniuKafelkow()') < cialo.index('zapiszUklad(')
    assert cialo.index('zdublowanyKlucz(uklad)') < cialo.index('zapiszUklad(')
    assert 'sledzZadanie(fetch(' in cialo_funkcji(zrodlo, 'pobierzKafelek')


def test_po_zapisie_wymiar_zapisany_to_ten_ktory_widac():
    """Bez tego plakietka podglądu pokazałaby się po wyjściu z trybu edycji
    na kafelku, któremu właśnie zmieniono wymiar NA STAŁE."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'zapiszPaczke')
    po_zapisie = cialo[cialo.index('zapiszUklad('):]
    assert "setAttribute('data-wymiar-zapisany', wymiar)" in po_zapisie
    assert 'pokazPominiete(0)' in po_zapisie
    assert 'wylaczEdycje()' in po_zapisie


def test_js_ostrzega_przed_opuszczeniem_strony_z_niezapisanym_ukladem():
    """Dopisane ponad plan. Stopki kafelków prowadzą do Eksploratora — jedno
    kliknięcie w trybie edycji gubiło cały przestawiony układ. Ta sama ochrona,
    co w arkuszu."""
    podpiecie = cialo_funkcji(js_bez_komentarzy(), 'podepnijZapisUkladu')
    blok = podpiecie[podpiecie.index("'beforeunload'"):]
    assert 'saZmiany()' in blok[:200]


def test_escape_w_trybie_edycji_ustepuje_oknu_i_menu():
    """Escape zamyka najpierw okno dodawania i menu zakresu dat — dopiero
    potem dotyczy trybu edycji (przez to samo potwierdzenie, co „Anuluj")."""
    zrodlo = js_bez_komentarzy()
    podpiecie = cialo_funkcji(zrodlo, 'podepnijZapisUkladu')
    blok = podpiecie[podpiecie.index("document.addEventListener('keydown'"):]
    assert 'modalOtwarty()' in blok and "'an-zakres-menu'" in blok
    assert 'anulujEdycje()' in blok
    assert 'stopPropagation()' in cialo_funkcji(zrodlo, 'naKlawiszModalu')
    start = zrodlo[zrodlo.index("addEventListener('DOMContentLoaded'"):]
    assert start.index('podepnijZapisUkladu()') < start.index('podepnijZakres()')


# --- bez skoku strony (znaleziska z oględzin) -------------------------------

def test_podmiana_siatki_trzyma_wysokosc_i_kotwice_przewiniecia():
    """Dopisane po oględzinach. Nowa siatka przychodzi jako szkielet — przez
    ułamek sekundy dużo niższa od starej, więc przeglądarka przycinała
    przewinięcie do krótszej strony. A jej własne zakotwiczenie przewijania
    trzyma się WĘZŁA, którego po podmianie już nie ma. Stąd: dawna wysokość
    siatki do czasu narysowania danych i jawna kotwica po kluczu kafelka."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'wymienSiatke')
    assert cialo.index('kotwicaPrzewiniecia()') < cialo.index('podmienSiatke(')
    assert 'style.minHeight = wysokosc' in cialo
    po_danych = cialo[cialo.index('zaladuj().then('):]
    assert "style.minHeight = ''" in po_danych and 'przywrocKotwice(kotwica)' in po_danych
    kotwica = cialo_funkcji(zrodlo, 'przywrocKotwice')
    assert "getAttribute('data-klucz') === kotwica.klucz" in kotwica


# --- fokus (przegląd gałęzi, W5) ---------------------------------------------
# ZASTĄPIONE: dawne `test_fokus_w_przyklejonym_pasku_nie_przewija_strony`
# i `test_przyklejony_pasek_nie_zaslania_fokusu` przechodziły bez dowodu —
# pierwszy sprawdzał obecność linii `an-edytuj.focus(…)`, która w praktyce
# nigdy się nie wykonywała (fokus był już na <body>, zanim ją sprawdzono),
# drugi — napis `scroll-padding-bottom`, który przy elemencie W oknie nic nie
# robi. Poniższe testy czytają źródło i pilnują MECHANIZMU; DOWODEM
# ZACHOWANIA jest skrypt przeglądarki s8_dostepnosc.mjs i s8b_fokus_zasloniety.mjs
# (Enter na „Zapisz"/„Odrzuć"/„Przywróć" → fokus na „Edytuj widok"; Tab po
# narzędziach → zero elementów z fokusem pod paskiem). Obraz testów nie ma
# node'a, więc zachowania fokusu nie da się tu wykonać.

def test_wyjscie_z_edycji_oddaje_fokus_takze_gdy_zgubil_sie_na_body():
    """Kliknięty przycisk paska bywa w chwili wyjścia z trybu już wyłączony
    (zapis) albo schowany (wiersz potwierdzenia) — przeglądarka przenosi
    wtedy fokus na <body>. Decyzja „oddaj fokus na »Edytuj widok«" zapada
    PRZED jakąkolwiek zmianą i obejmuje <body> oraz narzędzia kafelka."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'wylaczEdycje')
    decyzja = cialo.index('var oddajFokus')
    assert decyzja < cialo.index("classList.remove('analiza--edycja')")
    warunek = cialo[decyzja:cialo.index(';', decyzja)]
    assert 'aktywny === document.body' in warunek
    assert "getElementById('an-edycja').contains(aktywny)" in warunek
    assert "closest('.an-kafelek__narzedzia')" in warunek
    assert "if (oddajFokus) { document.getElementById('an-edytuj').focus({ preventScroll: true }); }" \
        in cialo


def test_po_bledzie_akcji_fokus_wraca_na_przycisk_do_ponowienia():
    zrodlo = js_bez_komentarzy()
    akcja = cialo_funkcji(zrodlo, 'akcjaPaska')
    assert 'udana === false && trybEdycji()' in akcja
    assert 'getElementById(idPrzyciskuPrzyBledzie)' in akcja
    assert "'an-uklad-zapisz'" in cialo_funkcji(zrodlo, 'zapiszPaczke')
    assert "akcjaPaska(wymienSiatke, 'an-uklad-anuluj')" in cialo_funkcji(zrodlo, 'anulujEdycje')
    assert "akcjaPaska(przywrocDomyslny, 'an-uklad-domyslny')" in \
        cialo_funkcji(zrodlo, 'podepnijZapisUkladu')


def test_fokus_pod_przyklejonym_paskiem_dosuwa_strone():
    """WCAG 2.4.11. Element W OKNIE, ale pod paskiem: przeglądarka nie
    przewija sama, więc słuchacz `focusin` dosuwa stronę o nachodzenie."""
    zrodlo = js_bez_komentarzy()
    assert "korzen.addEventListener('focusin', odslonFokus)" in \
        cialo_funkcji(zrodlo, 'podepnijEdycje')
    odslon = cialo_funkcji(zrodlo, 'odslonFokus')
    assert 'if (!trybEdycji()) { return; }' in odslon
    assert 'pasek.getBoundingClientRect().top' in odslon
    assert 'korzen.scrollTop = przed + nachodzi' in odslon
    assert "closest('#an-modal-dodaj')" in odslon


def test_fokus_z_myszy_nie_przewija_strony():
    """Weryfikacja poprawek, znalezisko 1 (regresja z W5). Chrome daje fokus
    przyciskowi już przy `mousedown`. Słuchacz `focusin` przewijał wtedy
    stronę o nachodzenie + zapas, `mouseup` trafiał w inne miejsce, a klik
    w przycisk wystający spod paska ginął (lejek zostawał na pozycji 8).
    Stronę dosuwamy WYŁĄCZNIE przy fokusie z klawiatury (`:focus-visible`),
    a sprawdzenie stoi PRZED przewinięciem. Dowód zachowania:
    wf_klik_przy_pasku.mjs (klik działa, zero przewinięcia) i s8b (Tab
    dalej odsłania fokus)."""
    zrodlo = js_bez_komentarzy()
    odslon = cialo_funkcji(zrodlo, 'odslonFokus')
    straz = odslon.index('if (!fokusZKlawiatury(cel)) { return; }')
    assert straz < odslon.index('korzen.scrollTop = przed + nachodzi')
    klawiatura = cialo_funkcji(zrodlo, 'fokusZKlawiatury')
    assert "cel.matches(':focus-visible')" in klawiatura
    # Przeglądarka bez `:focus-visible` rzuca SyntaxError z `matches` —
    # słuchacz nie może się na tym wywrócić.
    assert 'try {' in klawiatura and 'catch (' in klawiatura


def test_przyklejony_pasek_domyka_sie_do_dolu_okna():
    """Przegląd gałęzi, drobne 9: przy `bottom: 0` pasek wisiał 28 px nad
    krawędzią okna (przyklejenie szanuje dolny padding #analiza), a kafelki
    przewijały się pod nim w tej szczelinie. Pasek jest przesunięty o dolny
    odstęp strony — ta sama zmienna, z której bierze się padding."""
    tresc = css()
    assert 'padding: 0 22px var(--odstep-dolny) 22px' in tresc
    blok = tresc[tresc.index('.analiza--edycja .an-edycja {'):]
    blok = blok[:blok.index('}')]
    assert 'position: sticky' in blok
    assert 'bottom: calc(-1 * var(--odstep-dolny))' in blok
    assert 'background: var(--paper)' in blok


# --- błędy akcji paska (przegląd gałęzi, W3) ----------------------------------

def test_pasek_edycji_ma_miejsce_na_blad(client):
    blad = zupa(client).select_one('#an-edycja-pasek #an-edycja-blad')
    assert blad is not None and blad.has_attr('hidden')
    assert blad.get('role') == 'alert'


def test_bledy_zapisu_odrzucenia_przywrocenia_i_dodania_ida_do_paska():
    """Do przeglądu wszystkie szły do #an-blad pod tytułem strony — 1500 px
    nad oknem, kiedy użytkownik patrzy na przyklejony pasek u dołu."""
    zrodlo = js_bez_komentarzy()
    for funkcja in ('zapiszUklad', 'wymienSiatke', 'przywrocDomyslny'):
        cialo = cialo_funkcji(zrodlo, funkcja)
        assert 'pokazBladPaska(' in cialo, funkcja
        assert 'pokazBlad(' not in cialo, funkcja
    pobierz = cialo_funkcji(zrodlo, 'pobierzKafelek')
    blad = pobierz[pobierz.index('.catch('):]
    assert "var poczatek = 'Nie udało się dodać kafelka „' + nazwaTypu(typ)" in blad
    assert 'pokazBladPaska(blad.status === 401' in blad
    assert 'pokazBlad(' not in blad
    # Duplikat przed zapisem: błąd w pasku, nie podmiana licznika.
    paczka = cialo_funkcji(zrodlo, 'zapiszPaczke')
    assert "pokazBladPaska('Dwa kafelki pokazują to samo" in paczka
    assert "getElementById('an-edycja-licznik')" not in paczka


def test_blad_paska_poza_trybem_edycji_idzie_pod_tytul_strony():
    """Poza trybem edycji paska nie ma na ekranie — przywrócenie ze stanu
    pustego stoi tuż pod #an-blad, więc tam trafia komunikat."""
    cialo = cialo_funkcji(js_bez_komentarzy(), 'pokazBladPaska')
    assert "if (!blad || !trybEdycji()) { pokazBlad(komunikat); return; }" in cialo
    assert 'tekstZCyframi(blad, komunikat)' in cialo


def test_css_bledu_paska_to_czerwien_bledu():
    tresc = css()
    blok = tresc[tresc.index('.an-edycja__blad {'):]
    blok = blok[:blok.index('}')]
    assert 'var(--bad' in blok
    assert '.an-edycja__blad[hidden] { display: none; }' in tresc


# --- blokada w trakcie akcji (przegląd gałęzi, drobne 1) ---------------------

def test_w_trakcie_zapisu_siatka_jest_zablokowana():
    """Usunięcie kafelka albo „Odrzuć" w trakcie POST-u rozjeżdżało ekran
    i bazę. Na czas akcji siatka jest `inert`, Escape, „+" i okno dodawania
    nic nie robią, a przyciski paska są wyłączone."""
    zrodlo = js_bez_komentarzy()
    ustaw = cialo_funkcji(zrodlo, 'ustawAkcjeWToku')
    assert 'siatka.inert = tak' in ustaw and 'przyciskiPaska(!tak)' in ustaw
    assert 'if (akcjaWToku) { return Promise.resolve(null); }' in cialo_funkcji(zrodlo, 'akcjaPaska')
    podpiecie = cialo_funkcji(zrodlo, 'podepnijZapisUkladu')
    escape = podpiecie[podpiecie.index("document.addEventListener('keydown'"):]
    assert escape.index('if (akcjaWToku) { return; }') < escape.index('anulujEdycje()')
    assert 'if (akcjaWToku) { return; }' in cialo_funkcji(zrodlo, 'anulujEdycje')
    assert 'akcjaWToku' in cialo_funkcji(zrodlo, 'dodajKafelek')
    modal = cialo_funkcji(zrodlo, 'podepnijModal')
    plus = modal[modal.index("closest('#an-dodaj-kafelek')"):]
    assert plus.index('if (akcjaWToku) { return; }') < plus.index('otworzModalDodawania()')


# --- drobne frontu -------------------------------------------------------------

def test_awaria_danych_nie_zostawia_kafelka_we_wczytywaniu():
    """Przegląd gałęzi, drobne 4: dodany kafelek w locie + zmiana okresu +
    awaria /api/analytics zostawiały „Wczytywanie…" na zawsze."""
    zrodlo = js_bez_komentarzy()
    zaladuj = cialo_funkcji(zrodlo, 'zaladuj')
    blad = zaladuj[zaladuj.index('.catch('):]
    assert "classList.contains('an-kafelek--wczytywanie')" in blad
    assert 'pokazBladMiejsca(wezel)' in blad
    miejsce = cialo_funkcji(zrodlo, 'pokazBladMiejsca')
    assert "'an-kafelek__blad'" in miejsce and 'data-ponow-kafelek' in miejsce
    assert "closest('[data-ponow-kafelek]')" in cialo_funkcji(zrodlo, 'podepnijModal')
    assert 'pokazWczytywanieMiejsca(wezel)' in cialo_funkcji(zrodlo, 'pobierzKafelek')


def test_css_miejsca_na_kafelek_jest_flexem():
    """`align-items` i `justify-content` bez `display: flex` nic nie robiły."""
    tresc = css()
    blok = tresc[tresc.index('.an-kafelek--wczytywanie {'):]
    blok = blok[:blok.index('}')]
    assert 'display: flex' in blok


def test_okno_dodawania_stoi_nad_gornym_paskiem_mobilnym():
    """Przegląd gałęzi, drobne 5: na 390 px `.mobile-topbar` (z-index 10000)
    stał nad oknem i jego hamburger był klikalny."""
    import re
    tresc = css()
    blok = tresc[tresc.index('.an-modal { position: fixed;'):]
    blok = blok[:blok.index('}')]
    z_modalu = int(re.search(r'z-index: (\d+)', blok).group(1))
    with open(os.path.join(KORZEN, 'static', 'css', 'style.css'), encoding='utf-8') as plik:
        styl = plik.read()
    najwyzszy_paska = max(int(z) for z in re.findall(
        r'\.mobile-topbar\s*\{[^}]*?z-index:\s*(\d+)', styl))
    assert z_modalu > najwyzszy_paska


def test_lista_w_oknie_nie_obiecuje_wzorca_radio():
    """Przegląd gałęzi, drobne 6: `role="radio"` bez obsługi strzałek.
    Zwykłe przyciski z `aria-pressed`, grupa bez roli radiogroup."""
    zrodlo = js_bez_komentarzy()
    lista = cialo_funkcji(zrodlo, 'rysujListeModalu')
    assert "'radio'" not in lista and 'aria-checked' not in lista
    assert "setAttribute('aria-pressed', 'false')" in lista
    # Styl listy w oknie nie ma haka pod wzorzec radia. Od 24.09.2026 arkusz
    # MA regułę z `aria-checked` — przełącznik miary na kafelkach jest
    # prawdziwą grupą radiową ze strzałkami (tests/test_analiza_przelacznik.py)
    # — więc sprawdzamy reguły OKNA, a nie cały plik.
    regula_okna = re.findall(r'[^{}]*\.an-modal[^{}]*\{', css())
    assert regula_okna and not any('aria-checked' in r for r in regula_okna)


def test_lista_w_oknie_nie_ma_roli_radiogroup(client):
    lista = zupa(client).select_one('#an-modal-lista')
    assert lista.get('role') == 'group'


def test_liczby_w_uwagach_okna_sa_w_mono():
    """Każda cyfra w IBM Plex Mono — także „20" w uwadze o limicie i „90"
    w opisie karty należności."""
    zrodlo = js_bez_komentarzy()
    lista = cialo_funkcji(zrodlo, 'rysujListeModalu')
    assert 'tekstZCyframi(limit,' in lista
    assert "tekstZCyframi(el('span', 'an-modal__opis'), typ.opis)" in lista
    cyfry = cialo_funkcji(zrodlo, 'tekstZCyframi')
    assert "split(/(\\d+)/)" in cyfry and "el('span', 'an-mono', kawalek)" in cyfry
    assert 'tekstZCyframi(blok, komunikat)' in cialo_funkcji(zrodlo, 'pokazBlad')


def test_teksty_katalogu_mowia_to_co_karta_pokazuje():
    """Przegląd gałęzi, drobne 7. KPI nie ma strzałek, tylko zmianę
    procentową; „pierścień" jest na karcie „Sprzedaż netto według:"
    z legendą w złotych; „przed zwinięciem ogona" to żargon kodu."""
    wszystko = ' '.join(t.nazwa + ' ' + t.opis for t in KATALOG.values())
    assert 'strzałk' not in wszystko
    assert 'zwinięciem ogona' not in wszystko
    assert KATALOG['wykonczenie'].nazwa.startswith('Sprzedaż netto')
    assert 'Udział procentowy' not in wszystko
    assert 'zmianą procentową wobec poprzedniego okresu' in KATALOG['kpi'].opis


def test_opis_pierscienia_mowi_ze_cena_za_m3_jest_tylko_na_wymiarze_wykonczenia():
    """Kontrola końcowa, DROBNE 6. Od porządków końcowych (punkt 2) podsekcja
    „Cena za m³ z wykończeniem … wobec surowego" stoi tylko na wymiarze
    wykończenia, a opis w modalu obiecywał ją na każdym: karta dodana
    z wymiarem Status jej nie miała. Nazwa wymiaru z rejestru, nie z pamięci."""
    from modules.reports.analiza_service import WYMIAR_WYKONCZENIA
    from modules.reports.fields import POLA
    opis = KATALOG['wykonczenie'].opis
    assert 'wobec surowego' in opis
    assert f'tylko na wymiarze {POLA[WYMIAR_WYKONCZENIA].etykieta}' in opis


# --- partia E, punkt E7: domknięcia trybu edycji -----------------------------

def test_udane_przywrocenie_nie_miga_bursztynem():
    """Przy udanym „Przywróć domyślny" pasek na chwilę mówił bursztynem
    „Niezapisane zmiany w układzie": punkt odniesienia był już domyślny, a na
    ekranie stał jeszcze stary układ. Licznik przelicza się dopiero wtedy,
    gdy siatka NIE przyjdzie (wtedy zmiana jest prawdziwa, znalezisko 2)."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'przywrocDomyslny')
    assert 'ustawUkladZapisany(tresc && tresc.uklad, true)' in cialo
    assert 'if (!udana) { oznaczZmiane(); }' in cialo
    ustaw = cialo_funkcji(zrodlo, 'ustawUkladZapisany')
    assert 'if (!bezOdswiezenia) { oznaczZmiane(); }' in ustaw


def test_escape_z_fokusem_na_plusie_oddaje_fokus_na_edytuj_widok():
    """Kafelek „+" znika razem z trybem edycji — fokus na nim zostawał
    na <body>. Ma trafić na „Edytuj widok", jak po innych wyjściach."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'wylaczEdycje')
    assert "aktywny.closest('#an-dodaj-kafelek')" in cialo


def test_komunikaty_bledow_nie_maja_podwojnej_kropki_a_401_kaze_sie_zalogowac():
    zrodlo = js_bez_komentarzy()
    kropka = cialo_funkcji(zrodlo, 'bezKropki')
    assert '.replace(' in kropka
    # Od partii E8 (punkt 4e) opis błędu skleja z radą `zdanieBledu`, a ono
    # zdejmuje kropkę opisu przez `bezKropki`.
    assert 'bezKropki(blad.message)' in cialo_funkcji(zrodlo, 'zdanieBledu')
    zapis = cialo_funkcji(zrodlo, 'zapiszUklad')
    assert 'zdanieBledu(' in zapis
    assert 'blad.status === 401' in zapis and 'zaloguj się ponownie' in zapis.lower()
    dodanie = cialo_funkcji(zrodlo, 'pobierzKafelek')
    assert 'zdanieBledu(' in dodanie
    assert 'blad.status === 401' in dodanie
    # Status odpowiedzi jedzie z błędem — inaczej 401 nie dało się rozpoznać.
    odpowiedz = cialo_funkcji(zrodlo, 'odpowiedzJson')
    assert 'bladOdpowiedzi(odp' in odpowiedz


def test_stan_pusty_w_edycji_odsyla_do_paska_edycji(client):
    """W trybie edycji przycisk „Przywróć domyślny" bloku stanu pustego jest
    schowany — tekst nie może go obiecywać, ma odsyłać do paska edycji."""
    strona = client.get('/reports/analiza').get_data(as_text=True)
    blok = strona.split('id="an-stan-pusty"')[1].split('id="an-stan-pusty-domyslny"')[0]
    assert 'data-stan-pusty-podglad' in blok and 'data-stan-pusty-edycja' in blok
    edycja = blok.split('data-stan-pusty-edycja')[1].split('</span>')[0]
    assert 'na pasku edycji' in edycja
    zrodlo = js_bez_komentarzy()
    stan = cialo_funkcji(zrodlo, 'odswiezStanPusty')
    assert '[data-stan-pusty-edycja]' in stan and '[data-stan-pusty-podglad]' in stan


def test_mysz_nie_podrywa_strony_takze_na_selekcie():
    """Naprawa F1 objęła tylko przyciski: Chrome daje <select> klikniętemu
    myszą `:focus-visible`, więc `focusin` przewijał stronę przy `mousedown`.
    Fokus, który przyszedł ze wskaźnika, nie przewija niczego."""
    zrodlo = js_bez_komentarzy()
    odslon = cialo_funkcji(zrodlo, 'odslonFokus')
    assert 'if (wskaznikWcisniety) { return; }' in odslon
    assert odslon.index('if (wskaznikWcisniety) { return; }') < \
        odslon.index('korzen.scrollTop = przed + nachodzi')
    edycja = cialo_funkcji(zrodlo, 'podepnijEdycje')
    assert "addEventListener('pointerdown'" in edycja
    assert "addEventListener('pointerup'" in edycja


def test_przeniesienie_kafelka_odslania_jego_przycisk():
    """„Przenieś później" Enterem przy ostatnim rzędzie: kafelek zjeżdżał
    niżej, a fokus zostawał poza oknem."""
    zrodlo = js_bez_komentarzy()
    edycja = cialo_funkcji(zrodlo, 'podepnijEdycje')
    ruch = edycja[edycja.index("closest('[data-ruch]')"):edycja.index("closest('.an-kafelek__usun')")]
    assert "scrollIntoView({ block: 'nearest' })" in ruch


# --- partia E8, punkt 4c: dymek po przeniesieniu kafelka ----------------------

def test_przeniesienie_kafelka_chowa_dymki():
    """Weryfikacja partii E (D1): kursor na pierścieniu, Enter na „Przenieś
    wcześniej" — kafelek jedzie gdzie indziej, a dymek zostawał nad obcą
    kartą. Chrome zeruje najechanie przy przestawieniu węzła, więc Chart.js
    nie dostaje `mouseout` i sam dymka nie schowa. Przeniesienie chowa oba
    dymki (wykresów i mapy), tak jak usunięcie kafelka."""
    zrodlo = js_bez_komentarzy()
    cialo = cialo_funkcji(zrodlo, 'przeniesKafelek')
    assert 'schowajDymekWykresu();' in cialo
    assert 'schowajDymek();' in cialo
    # Dopiero gdy przeniesienie się udało — przy skrajnym kafelku nic się
    # nie rusza i dymek może zostać.
    assert cialo.index('insertBefore') < cialo.index('schowajDymekWykresu();')


# --- partia E8, punkt 4e: jedna rada w komunikacie błędu ----------------------

def test_komunikat_bledu_ma_jedna_rade():
    """Weryfikacja partii E (D6): 502 przy zapisie dawało „…serwer odpowiedział
    błędem 502, spróbuj ponownie za chwilę. Zmiany zostały na ekranie —
    spróbuj zapisać ponownie." — dwie rady, bo opis statusu niósł własną,
    a zdanie paska dokładało swoją. Opis statusu mówi teraz tylko, CO się
    stało; radę dokłada wołający, raz. Przy 401 rady nie dokłada wcale —
    opis („zaloguj się ponownie") jest wtedy sam radą."""
    zrodlo = js_bez_komentarzy()
    opis = cialo_funkcji(zrodlo, 'opisStatusu').lower()
    assert 'spróbuj' not in opis and 'odśwież' not in opis
    zdanie = cialo_funkcji(zrodlo, 'zdanieBledu')
    assert 'bezKropki(blad.message)' in zdanie
    assert 'blad.status === 401' in zdanie
    for funkcja in ('zapiszUklad', 'pobierzKafelek', 'wymienSiatke', 'przywrocDomyslny'):
        cialo = cialo_funkcji(zrodlo, funkcja)
        assert 'zdanieBledu(' in cialo, funkcja
        # Żadne zdanie paska nie skleja już opisu błędu samo.
        assert "+ bezKropki(blad.message)" not in cialo, funkcja
