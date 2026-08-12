# -*- coding: utf-8 -*-
"""
Zbieżność liczb: nowe wykresy Raportów wobec widgetów, które już są na ekranie.

Każdy nowy wykres odpowiada na pytanie, na które GDZIEŚ INDZIEJ w aplikacji
już jest odpowiedź. Jeżeli te dwie odpowiedzi się różnią, użytkownik nie
dostaje dwóch punktów widzenia — dostaje powód, żeby przestać ufać obu.
Testy poniżej pilnują trzech par, które właściciel realnie zestawia obok siebie:

    wykres 1 „Dni zapasu"      ←→ kafelki kolejek na Dashboardzie
    wykres 3 „Wejście/wyjście" ←→ widget „Wykonanie stanowiska" (pakowanie)
    wykres 5 „Obsada vs przerób" ←→ widget „Wydajność dzienna"
    wykres 8 „Kto ile zrobił"  ←→ widget „Wykonanie stanowiska w dniu"

Testy porównują nowe agregaty z FUNKCJAMI, z których liczą te stare widgety
(a nie z powtórzonym w teście SQL-em) — inaczej test przyklepywałby własną,
trzecią definicję i cały sens zbieżności by wyparował.

Zmierzone na kopii produkcyjnej 2026-08-12 (te same funkcje, prawdziwe dane):
  - kolejki:   assembly 1.885 / formatting 2.008 / gluing 0.660 / cutting 0.407
               / finishing 0.696 / packaging 0.269 — raport = dashboard co do
               zaokrąglenia (raport zaokrągla do 3 miejsc, dashboard oddaje
               surowo: 1.885 vs 1.885466);
  - wyjście:   90 dni → 57.271 m³ w obu widgetach, co do trzeciego miejsca;
  - przerób:   7 dni → packaging 7.644 / formatting 5.169 / gluing 5.135 /
               assembly 3.688 / cutting 1.476 / finishing 1.133 / painting 0.368
               — identycznie w wykresie 5 i w „Wydajności dziennej".
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.routers.api.dashboard_api import _STATION_PENDING_STATUS
from modules.production.services import reports_service
from modules.production.services.station_catalog import STATION_ORDER, station_choices
from modules.production.services.station_events_service import get_station_work_per_day
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

# Ten sam poniedziałek co w test_reports_service — dzień tygodnia bywa gałęzią
# (heatmapa, agregacja tygodniowa), więc data nie może pochodzić z zegara.
PONIEDZIALEK = date(2026, 8, 10)


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def zalogowany(monkeypatch):
    """
    chart_data() loguje user_id także na ścieżce sukcesu, a testowa aplikacja
    nie ma login_managera. Podmieniamy `current_user` w przestrzeni modułu
    (endpoint importuje go po nazwie), żeby test dotykał prawdziwego ciała
    endpointu, a nie jego kopii.
    """
    from modules.production.routers.api import dashboard_api

    monkeypatch.setattr(dashboard_api, 'current_user',
                        type('UzytkownikTestowy', (), {'id': 1})())
    return dashboard_api


_licznik_zamowien = [0]


def _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10, utworzono=None):
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=quantity, volume_m3=volume, current_status=status,
        created_at=utworzono or datetime.combine(PONIEDZIALEK, time(9, 0)))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _event(produkt, station, delta, kiedy, source='mobile'):
    db.session.add(ProductionStationEvent(
        production_item_id=produkt.id, station_code=station, delta=delta,
        quantity_done_after=max(0, delta), created_at=kiedy, source=source))
    db.session.commit()


def _kolejka_dashboardu(status):
    """
    SQL kafelka kolejki 1:1 z dashboard_api.py (`pending_m3`): suma
    volume_m3 × quantity po current_status. Nie „podobny" — dokładnie ten sam
    kształt, bo test ma wychwycić rozjazd definicji, a nie potwierdzić własną.
    """
    return float(db.session.query(
        db.func.coalesce(
            db.func.sum(ProductionProduct.volume_m3 * ProductionProduct.quantity), 0)
    ).filter(ProductionProduct.current_status == status).scalar() or 0.0)


# ============================================================================
# WYKRES 1 ←→ KAFELKI KOLEJEK NA DASHBOARDZIE
# ============================================================================

def test_kolejki_wykresu_1_zgadzaja_sie_z_dashboardem(app):
    """
    Licznik dni zapasu MUSI być tą samą liczbą, którą użytkownik widzi na
    kafelku Dashboardu. Gdy dwa ekrany podają dwie kolejki tego samego
    stanowiska, każdy wniosek o wąskim gardle jest do wyrzucenia.

    Świadoma różnica jest tylko w MIANOWNIKU (tempo z eventów) — kolejka
    w liczniku ma się zgadzać co do zaokrąglenia.
    """
    with app.app_context():
        for status, sztuk in (('czeka_na_sklejanie', 10),
                              ('czeka_na_formatowanie', 4),
                              ('czeka_na_pakowanie', 7)):
            _produkt(status=status, volume=0.5, quantity=sztuk)
        # Jakikolwiek przerób, żeby okno dni roboczych w ogóle powstało.
        robiony = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        raport = {s['station_code']: s['pending_m3'] for s in
                  reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)['stations']}

        for kod, status in _STATION_PENDING_STATUS.items():
            assert raport[kod] == pytest.approx(_kolejka_dashboardu(status), abs=0.0005), kod
        assert raport['gluing'] == 5.0
        assert raport['formatting'] == 2.0
        assert raport['packaging'] == 3.5


def test_wykres_1_pokazuje_lakiernie_ktorej_dashboard_nie_ma(app):
    """
    JEDYNA uzasadniona różnica między wykresem 1 a Dashboardem: raport liczy
    siedem stanowisk, Dashboard rysuje sześć kafelków i nie zna lakierni.

    To decyzja, nie błąd — udokumentowana w dwóch miejscach naraz:
    dashboard_api._DASHBOARD_STATIONS (komentarz „ZESTAW stanowisk jest tu
    WĘŻSZY niż w katalogu") i station_catalog.STATION_PENDING_STATUS. Test
    przypina ją do liczby: gdy ktoś dołoży siódmy kafelek, ten test zapali się
    i przypomni, że wtedy trzeba porównać obie liczby, a nie tylko dorysować UI.

    Na produkcji to nie jest drobiazg: lakiernia ma dziś najdłuższy zapas
    (6.58 dnia przy kolejce 0.487 m³), a Dashboard w ogóle jej nie pokazuje.
    """
    with app.app_context():
        _produkt(status='czeka_na_lakiernie', volume=0.5, quantity=4)
        robiony = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(robiony, 'gluing', 2, datetime.combine(PONIEDZIALEK, time(9, 0)))

        raport = {s['station_code']: s['pending_m3'] for s in
                  reports_service.dni_zapasu_stanowisk(end_date=PONIEDZIALEK)['stations']}

        assert 'painting' not in _STATION_PENDING_STATUS
        assert raport['painting'] == 2.0
        assert set(raport) - set(_STATION_PENDING_STATUS) == {'painting'}


# ============================================================================
# WYKRES 3 ←→ WIDGET STANOWISKOWY (PAKOWANIE)
# ============================================================================

def test_wyjscie_wykresu_3_zgadza_sie_z_przerobem_pakowania(app):
    """
    „Wyszło z hali" na wykresie 3 to dokładnie przerób pakowania z widgetu
    stanowiskowego — ta sama definicja (SUM(volume_m3 × delta) z filtrem
    źródła), więc różnica byłaby czystym błędem, nie inną perspektywą.

    Test porównuje z get_station_work_per_day(), czyli funkcją, z której liczy
    „Wydajność dzienna" i tryb pojedynczego stanowiska Dashboardu.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100,
                           utworzono=datetime.combine(PONIEDZIALEK - timedelta(days=7),
                                                      time(8, 0)))
        wtorek = PONIEDZIALEK + timedelta(days=1)
        _event(produkt, 'packaging', 6, datetime.combine(PONIEDZIALEK, time(9, 0)))
        _event(produkt, 'packaging', -2, datetime.combine(PONIEDZIALEK, time(15, 0)))
        _event(produkt, 'packaging', 4, datetime.combine(wtorek, time(11, 0)))

        flow = reports_service.wejscie_vs_wyjscie(PONIEDZIALEK, wtorek)
        widget = get_station_work_per_day('packaging', PONIEDZIALEK, wtorek)

        assert flow['total_out_m3'] == pytest.approx(
            sum(v['m3'] for v in widget.values()), abs=0.0005)
        assert flow['total_out_m3'] == 4.0        # (6-2+4) szt. × 0.5 m³
        # Także dzień po dniu — suma może się zgadzać przy przesuniętych dobach.
        assert [d['out_m3'] for d in flow['days']] == [2.0, 2.0]


def test_obie_strony_pary_odsiewaja_automat_tak_samo(app):
    """
    Zbieżność nie może opierać się na tym, że OBA widgety liczą źle tak samo,
    ani na tym, że jeden filtruje, a drugi nie. Dosyp auto_skip/system musi
    zostawić obie liczby nietknięte — i nadal równe sobie.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        _event(produkt, 'packaging', 4, kiedy)
        _event(produkt, 'packaging', 400, kiedy, source='auto_skip')
        _event(produkt, 'packaging', 400, kiedy, source='system')

        flow = reports_service.wejscie_vs_wyjscie(PONIEDZIALEK, PONIEDZIALEK)
        widget = sum(v['m3'] for v in
                     get_station_work_per_day('packaging', PONIEDZIALEK, PONIEDZIALEK).values())

        assert flow['total_out_m3'] == 2.0
        assert widget == pytest.approx(2.0, abs=0.0005)


# ============================================================================
# WYKRES 5 ←→ „WYDAJNOŚĆ DZIENNA"
# ============================================================================

def test_przerob_wykresu_5_zgadza_sie_z_wydajnoscia_dzienna(app):
    """
    Wykres 5 dokłada do przerobu osobogodziny — ale sam PRZERÓB musi być tą
    samą liczbą, którą pod nim rysuje „Wydajność dzienna". Inaczej ten sam
    ekran pokazuje dwa różne m³ dla tego samego stanowiska i tego samego dnia,
    w odległości dwóch centymetrów.

    Sztuki sprawdzamy razem z m³: rozjazd tylko w jednej z tych dwóch liczb
    oznaczałby błąd w mnożeniu przez objętość, a nie w filtrach.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.25, quantity=1000)
        kiedy = datetime.combine(PONIEDZIALEK, time(10, 0))
        for kod, delta in (('cutting', 8), ('gluing', 12), ('formatting', 5),
                           ('painting', 3), ('packaging', 20)):
            _event(produkt, kod, delta, kiedy)
        _event(produkt, 'gluing', -2, datetime.combine(PONIEDZIALEK, time(16, 0)))

        wiersze = {w['station_code']: w for w in reports_service.obsada_vs_przerob(
            PONIEDZIALEK, PONIEDZIALEK)['rows']}

        for kod in STATION_ORDER:
            per_day = get_station_work_per_day(kod, PONIEDZIALEK, PONIEDZIALEK)
            m3 = sum(v['m3'] for v in per_day.values())
            sztuk = sum(v['pieces'] for v in per_day.values())
            wiersz = wiersze.get(kod, {'m3': 0.0, 'pieces': 0})
            assert wiersz['m3'] == pytest.approx(m3, abs=0.0005), kod
            assert wiersz['pieces'] == sztuk, kod

        assert wiersze['gluing']['pieces'] == 10          # 12 - 2 cofnięte
        assert wiersze['painting']['m3'] == 0.75


def test_wydajnosc_dzienna_zna_kazde_stanowisko_z_listy_rozwijanej(app, zalogowany):
    """
    REGRESJA (znaleziona przy tym zestawieniu): lista rozwijana „Wydajności
    dziennej" jest generowana z katalogu stanowisk (siedem pozycji), a endpoint
    /production/api/chart-data miał własną, sześciopozycyjną mapę etykiet.
    Wybranie „Lakierni" kończyło się KeyError('painting') i HTTP 500 — zmierzone
    na kopii produkcyjnej: „Obsada vs przerób" pokazywała dla lakierni
    0.368 m³ / 9 szt. (05-11.08), a widget obok nie umiał narysować niczego.

    Test woła ciało endpointu dla KAŻDEGO stanowiska z listy — nowe stanowisko
    w katalogu nie ma prawa wywrócić widgetu, który tę listę wyświetla.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=100)
        _event(produkt, 'painting', 3, datetime.combine(PONIEDZIALEK, time(9, 0)))

        for kod, nazwa in station_choices():
            with app.test_request_context(
                    f'/?start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}&station={kod}'):
                odpowiedz = zalogowany.chart_data.__wrapped__()
                # Awaria wraca jako (response, 500) — sukces jako sam response.
                assert not isinstance(odpowiedz, tuple), (kod, nazwa)
                dane = odpowiedz.get_json()
                assert dane['success'] is True, kod
                assert dane['summary']['station_label'] == nazwa, kod


def test_wydajnosc_dzienna_zbiorczo_rysuje_wszystkie_stanowiska(app, zalogowany):
    """
    REGRESJA, której poprzedni test NIE ŁAPAŁ: iterował `station={kod}`
    i ani razu nie wołał `station=all`, a to właśnie tryb zbiorczy miał
    zaszytą sześcioelementową listę krzywych przy siedmiu stanowiskach
    w katalogu. Lakiernia — dziś najdłuższa kolejka hali, 15,1 dnia zapasu —
    nie była rysowana wcale.

    Zmierzone na kopii produkcji przed poprawką: suma krzywych trybu
    zbiorczego 93.731 m³ wobec 94.895 m³ z „Obsady vs przerób" na tym samym
    oknie 30-dniowym; różnica 1.164 m³ to dokładnie painting.

    Test sprawdza OBIE rzeczy naraz: liczbę i nazwy serii (z katalogu) oraz
    zbieżność sumy z drugim widgetem, który tę samą pracę liczy niezależnie.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=1000)
        kiedy = datetime.combine(PONIEDZIALEK, time(9, 0))
        for kod, _nazwa in station_choices():
            _event(produkt, kod, 4, kiedy)

        with app.test_request_context(
                f'/?station=all&start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'):
            odpowiedz = zalogowany.chart_data.__wrapped__()

        assert not isinstance(odpowiedz, tuple)
        dane = odpowiedz.get_json()
        serie = dane['chart_data']['datasets']

        oczekiwane = [nazwa for _kod, nazwa in station_choices()]
        assert [s['label'] for s in serie] == oczekiwane

        suma_krzywych = sum(sum(s['data']) for s in serie)
        suma_obsady = reports_service.obsada_vs_przerob(
            PONIEDZIALEK, PONIEDZIALEK)['summary']['m3']
        assert suma_krzywych == pytest.approx(suma_obsady, abs=0.0005)


def test_zle_wejscie_chart_data_nie_udaje_domyslnego_okresu(app, zalogowany):
    """
    REGRESJA: `request.args.get('period', 7, type=int)` przy nieparsowalnej
    wartości oddaje wartość DOMYŚLNĄ — czyli ?period=abc stawało się cichym
    „7 dni" jeszcze przed białą listą, podczas gdy ?period=0 dostawało
    uczciwe 400. To samo złe wejście, dwa różne kody odpowiedzi.

    Ta sama reguła dla niepełnej pary dat: podanie jednej granicy zakresu to
    błąd, a nie zaproszenie do ostatniego tygodnia.
    """
    with app.app_context():
        for zapytanie in ('/?period=abc&station=all',
                          '/?period=0&station=all',
                          '/?station=all&start_date=2026-05-01',
                          '/?station=all&end_date=2026-05-01'):
            with app.test_request_context(zapytanie):
                odpowiedz = zalogowany.chart_data.__wrapped__()
            assert isinstance(odpowiedz, tuple), zapytanie
            assert odpowiedz[1] == 400, zapytanie


def test_wydajnosc_dzienna_mowi_kiedy_nie_ma_z_czego_rysowac(app, zalogowany):
    """
    REGRESJA: pusty zakres dawał sześć krzywych leżących na zerze — obraz
    nie do odróżnienia od „hala stanęła". Zakres w przyszłości, niedziela bez
    pracy i okres sprzed pierwszego produktu wyglądały identycznie, mimo że
    każdy inny widget zakładki ma jawny pusty stan.

    Serwer nie zgaduje, co pokazać — oddaje `days_with_events` i front
    decyduje o brzmieniu komunikatu.
    """
    with app.app_context():
        produkt = _produkt(status='spakowane', volume=0.5, quantity=10)
        _event(produkt, 'gluing', 4, datetime.combine(PONIEDZIALEK, time(9, 0)))

        przyszlosc = PONIEDZIALEK + timedelta(days=365)
        with app.test_request_context(
                f'/?station=all&start_date={przyszlosc}&end_date={przyszlosc}'):
            pusto = zalogowany.chart_data.__wrapped__().get_json()
        assert pusto['summary']['days_with_events'] == 0

        with app.test_request_context(
                f'/?station=all&start_date={PONIEDZIALEK}&end_date={PONIEDZIALEK}'):
            pelno = zalogowany.chart_data.__wrapped__().get_json()
        assert pelno['summary']['days_with_events'] == 1


# ============================================================================
# WYKRES 8 ←→ „WYKONANIE STANOWISKA W DNIU"
# ============================================================================

def test_wklad_osob_sumuje_sie_do_przerobu_stanowiska(app):
    """
    Wykres 8 stoi w tej samej podzakładce, dwa centymetry pod „Wykonaniem
    stanowiska w dniu", i rozbija DOKŁADNIE tę samą liczbę na ludzi. Suma
    słupków — osoby PLUS wyszarzone „Nieprzypisane" — musi więc trafić w przerób
    stanowiska co do trzeciego miejsca.

    Właśnie po to jest ten szary słupek: bez niego stanowisko, które zrobiło
    40 m³ przy 22 m³ podpisanych, miałoby wykres sugerujący, że ludzie na osi
    zrobili całość. Test sprawdza obie liczby (m³ i sztuki) na KAŻDYM
    stanowisku z katalogu, także tam, gdzie atrybucji nie ma wcale.
    """
    with app.app_context():
        adam = ProductionWorker(first_name='Adam', last_name='Nowak')
        borys = ProductionWorker(first_name='Borys', last_name='Nowak')
        db.session.add_all([adam, borys])
        db.session.commit()

        produkt = _produkt(status='spakowane', volume=0.25, quantity=1000)
        kiedy = datetime.combine(PONIEDZIALEK, time(10, 0))

        def _z_podpisem(station, delta, pracownicy, source='mobile', godzina=kiedy):
            ev = ProductionStationEvent(
                production_item_id=produkt.id, station_code=station, delta=delta,
                quantity_done_after=max(0, delta), created_at=godzina, source=source)
            db.session.add(ev)
            db.session.flush()
            for pracownik in pracownicy:
                db.session.add(ProductionStationEventWorker(
                    event_id=ev.id, worker_id=pracownik.id,
                    share=1.0 / len(pracownicy)))
            db.session.commit()

        # Pełny przekrój sytuacji, w których suma potrafi się rozjechać:
        _z_podpisem('gluing', 12, [adam])                    # jedna osoba
        _z_podpisem('assembly', 9, [adam, borys])            # brygada, share 1/2
        _z_podpisem('formatting', 5, [adam])
        _event(produkt, 'formatting', 7, kiedy)              # ta sama doba bez podpisu
        _event(produkt, 'packaging', 20, kiedy)              # wyłącznie bez podpisu
        _z_podpisem('gluing', -2, [borys], source='admin',   # cofnięcie na minus
                    godzina=datetime.combine(PONIEDZIALEK, time(16, 0)))
        _event(produkt, 'cutting', 400, kiedy, source='auto_skip')
        _event(produkt, 'finishing', 400, kiedy, source='system')

        for kod in STATION_ORDER:
            per_day = get_station_work_per_day(kod, PONIEDZIALEK, PONIEDZIALEK)
            m3_widgetu = sum(v['m3'] for v in per_day.values())
            sztuk_widgetu = sum(v['pieces'] for v in per_day.values())

            wynik = reports_service.wklad_pracownikow_na_stanowisku(
                kod, PONIEDZIALEK, PONIEDZIALEK)
            suma_m3 = (sum(o['m3'] for o in wynik['workers'])
                       + wynik['unassigned']['m3'])
            suma_sztuk = (sum(o['pieces'] for o in wynik['workers'])
                          + wynik['unassigned']['pieces'])

            assert suma_m3 == pytest.approx(m3_widgetu, abs=0.0005), kod
            assert suma_sztuk == pytest.approx(sztuk_widgetu, abs=0.005), kod
            assert wynik['summary']['sums_match'] is True, kod
            # Ta sama liczba jedzie w kafelku widgetu — gdyby liczył ją inaczej
            # niż słupki, kafelek kłóciłby się z wykresem pod sobą.
            assert wynik['summary']['station_m3'] == pytest.approx(
                m3_widgetu, abs=0.0005), kod

        # Kontrola, że powyższe nie jest porównaniem zer: automat na wycinaniu
        # i wykańczaniu ma zniknąć po OBU stronach, a nie zostać po żadnej.
        assert reports_service.wklad_pracownikow_na_stanowisku(
            'cutting', PONIEDZIALEK, PONIEDZIALEK)['summary']['station_events'] == 0
        assert reports_service.wklad_pracownikow_na_stanowisku(
            'packaging', PONIEDZIALEK, PONIEDZIALEK)['summary']['station_m3'] == 5.0


def test_porownania_wyzej_nie_sa_tautologia(app):
    """
    Zabezpieczenie samych testów zbieżności: obie porównywane strony muszą być
    od siebie NIEZALEŻNE. Gdyby reports_service liczył przerób przez
    get_station_work_per_day (albo odwrotnie), testy wyżej porównywałyby jedną
    liczbę samą ze sobą i świeciłyby na zielono nawet po zepsuciu obu widgetów.

    Serwis raportów pisze własne zapytania (patrz `_filtry_eventow_pracy`)
    i to jest w porządku dopóty, dopóki filtr źródła jest wspólny — sam filtr
    jedzie z jednego miejsca (station_events_service.ZRODLA_AUTOMATU),
    i to jest jedyna rzecz, którą te dwie ścieżki mają dzielić.
    """
    import modules.production.services.reports_service as rs
    from modules.production.services import station_events_service

    assert not hasattr(rs, 'get_station_work_per_day')
    assert rs.ZRODLA_AUTOMATU is station_events_service.ZRODLA_AUTOMATU
    assert set(rs.ZRODLA_AUTOMATU) == {'auto_skip', 'system'}
