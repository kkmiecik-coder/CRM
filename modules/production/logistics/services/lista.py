# -*- coding: utf-8 -*-
"""Lista zamówień zakładki Logistyka (spec, sekcja 6.7)."""
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby, wojewodztwa
from modules.production.logistics.models import RouteStop, STATUSY_TRASY_AKTYWNE
from modules.production.logistics.services import geocoding, paczki, paczki_druk, routes, weryfikacja
from modules.production.logistics.services.delivery import aktywne_produkty, wszystkie_spakowane, wszystkie_w
from modules.production.models import ProductionOrder, ProductionProduct, get_local_now
from modules.production.services.station_catalog import STATION_LABELS, STATION_PENDING_STATUS

# Najwcześniejszy etap zamówienia = etap jego najbardziej zaległej pozycji.
KOLEJNOSC_ETAPOW = ('wstrzymane', 'czeka_na_wyciecie', 'czeka_na_skladanie',
                    'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie',
                    'czeka_na_lakiernie', 'czeka_na_pakowanie', 'spakowane',
                    'zweryfikowane', 'zaladowane', 'dostarczone')
LIMIT_ZAMKNIETYCH = 50
# Filtr `stan` listy (krok 4.3, spec 11): zakres własny, niezależny od podziału otwarte/zamknięte.
STANY_WERYFIKACJI = ('do_weryfikacji', 'problem', 'bez_paczek')

# Etap w kolumnie listy = STANOWISKO, na którym pozycja czeka („Lakiernia”, nie
# „Czeka na lakiernię”) — nazwy z jednego źródła (station_catalog), tymi samymi
# mówią monitory na hali. Statusy po spakowaniu nazywa weryfikacja.NAZWY_ETAPOW
# („Spakowane — czeka na weryfikację”). Pozostałe (wstrzymane) — jak w bazie.
NAZWA_STANOWISKA = {status: STATION_LABELS[kod] for kod, status in STATION_PENDING_STATUS.items()}
# Etap zamówienia załadowanego na trasę, która już ruszyła (krok 4.4, spec 11) — wynika z pozycji I trasy.
NAZWA_W_TRASIE = u'W trasie'


def _ranga(status):
    """
    Status spoza KOLEJNOSC_ETAPOW (np. `czeka_na_logistyke` zapisany przez stary kod
    w oknie wdrożenia) dostaje rangę -1, czyli wychodzi jako NAJWCZEŚNIEJSZY etap —
    anomalia ma być widoczna, a nie chować się za „Spakowane”.
    """
    return KOLEJNOSC_ETAPOW.index(status) if status in KOLEJNOSC_ETAPOW else -1


def warunek_bez_sposobu():
    """
    „Nie ustawiono” w SQL — ta sama definicja co sposoby.normalizuj() w Pythonie
    (licznik zakładki, 409 tabletu): NULL albo wartość spoza SPOSOBY (np. pusty tekst).
    Używają jej filtr `sposob=brak` i bramka dashboardu produkcji.
    """
    kolumna = ProductionOrder.override_delivery_method
    return or_(kolumna.is_(None), kolumna.notin_(sposoby.SPOSOBY))


def liczba_bez_sposobu():
    """Bramka dashboardu produkcji: otwarte zamówienia z aktywną pozycją i bez sposobu."""
    return db.session.query(func.count(ProductionOrder.id)).filter(
        ProductionOrder.logistics_closed_at.is_(None),
        warunek_bez_sposobu(),
        ProductionOrder.products.any(ProductionProduct.current_status != 'anulowane'),
    ).scalar() or 0


def _wzor_like(fraza):
    """`%`, `_` i sam znak ucieczki `\\` dosłownie (ESCAPE '\\'), nie jako wieloznaczniki."""
    bezpieczna = fraza.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return u'%{}%'.format(bezpieczna)


# Pola wyszukiwarki: numer, klient, ulica z numerem, kod pocztowy, miejscowość.
_POLA_FRAZY = (ProductionOrder.internal_order_number, ProductionOrder.client_name,
               ProductionOrder.delivery_address, ProductionOrder.delivery_postcode,
               ProductionOrder.delivery_city)
MAKS_SLOW_FRAZY = 6


def _warunki_frazy(fraza):
    """
    Każde słowo frazy musi pasować do któregoś pola (niekoniecznie tego samego):
    „Kowalski Rzeszów”, „Zagłoby 10 Józefów”. Pięć cyfr to też kod z kreską
    („35310” znajduje „35-310”).
    """
    warunki = []
    for slowo in fraza.split()[:MAKS_SLOW_FRAZY]:
        wzory = [_wzor_like(slowo)]
        if re.fullmatch(r'\d{5}', slowo):
            wzory.append(_wzor_like(slowo[:2] + '-' + slowo[2:]))
        warunki.append(or_(*[pole.ilike(wzor, escape='\\')
                             for pole in _POLA_FRAZY for wzor in wzory]))
    return warunki


def _nazwa_etapu(produkt):
    """Napis etapu pozycji: po spakowaniu z weryfikacja.NAZWY_ETAPOW, dalej stanowisko, na końcu status."""
    return (weryfikacja.NAZWY_ETAPOW.get(produkt.current_status)
            or NAZWA_STANOWISKA.get(produkt.current_status) or produkt.status_display_name)


def _etap(aktywne, trasa=None):
    if not aktywne:
        return {'status': 'anulowane', 'nazwa': 'Anulowane'}
    najwczesniejszy = min(aktywne, key=lambda p: _ranga(p.current_status))
    status = najwczesniejszy.current_status
    if status == 'zaladowane' and trasa is not None and trasa.status == 'w_trasie':
        return {'status': 'w_trasie', 'nazwa': NAZWA_W_TRASIE}
    return {'status': status, 'nazwa': _nazwa_etapu(najwczesniejszy)}


def _geo(punkt):
    if punkt is None or punkt.lat is None:
        return None
    return {'lat': float(punkt.lat), 'lng': float(punkt.lng), 'quality': punkt.quality,
            'source': punkt.source, 'adres_zmieniony': bool(punkt.address_changed_after_manual)}


def _liczba(wartosc):
    """Decimal z bazy → '4' albo '4.5' (bez zbędnych zer), None → None."""
    if wartosc is None:
        return None
    return format(float(wartosc), 'g')


def _pozycja(p):
    """
    Pozycja zamówienia do rozwijanego wiersza listy — to samo, co pokazuje lista
    produktów (nazwa, ID, gatunek / technologia / klasa / grubość, ilość, m³),
    plus etap jako stanowisko (jak kolumna „Etap produkcji”).
    """
    konfiguracja = p.configuration

    def cecha(nazwa):
        # find_or_create zapisuje „unknown” dla usług i nieparsowalnych nazw — lista
        # produktów go nie pokazuje, więc i tu nie (przegląd D18).
        wartosc = getattr(konfiguracja, nazwa, None) if konfiguracja else None
        return None if wartosc in (None, '', 'unknown') else wartosc

    return {
        'id': p.short_product_id,
        'nazwa': p.original_product_name,
        'gatunek': cecha('species'),
        'technologia': cecha('technology'),
        'klasa': cecha('wood_class'),
        'grubosc_cm': _liczba(p.parsed_thickness_cm),
        'bez_dociecia': p.cut_to_size is False,
        'dorobka': p.original_product_id is not None,
        'ilosc': p.quantity or 1,
        'm3': round(float(p.volume_m3 or 0) * (p.quantity or 1), 4),
        'etap': {'status': p.current_status, 'nazwa': _nazwa_etapu(p)},
        'anulowana': p.current_status == 'anulowane',
    }


def _etykiety_paczek_sprzed_zmiany(order, trasa, paczki_zamowienia):
    """
    Spec 6.3: etykiety paczki nie przedrukowujemy sami po zmianie sposobu dostawy albo
    trasy — panel pokazuje ikonę, gdy napis z pasa na wydrukowanej etykiecie (zapamiętany
    na paczce) różni się od dzisiejszego.

    Zamówienie OTWARTE: dzisiejszy napis liczymy tylko z trasy aktywnej — wykonana nie
    trafia na etykietę (jak w paczki_druk.drukuj_etykiety → routes.trasa_dla_tabletu).

    Zamówienie ZAMKNIĘTE w Logistyce (decyzja Konrada 30.09): ikona też się pokazuje, ale
    napis liczymy z trasy zamówienia także wtedy, gdy jest wykonana — etykieta była
    drukowana, gdy trasa była aktywna („TRASA: …”), a po wykonaniu trasy dzisiejszy napis
    bez niej to „TRANSPORT WOODPOWER”, więc samo porównanie z napisem „bez trasy” świeciłoby
    na każdym zamówieniu dowiezionym trasą. Prawdziwa zmiana po zamknięciu (sposób dostawy
    zmieniony na odbiór albo kuriera, inna trasa) nadal zapala ikonę.

    Przypadek graniczny, świadomie zostawiony: etykieta wydrukowana, zanim zamówienie trafiło
    na trasę („TRANSPORT WOODPOWER”), a potem zamówienie dowiezione trasą — napis na etykiecie
    naprawdę różni się od dzisiejszego („TRASA: …”), więc ikona zostaje.

    `trasa` ma tu pochodzić z routes.trasy_zamowien() (trasa zamówienia w dowolnym statusie,
    jedno zapytanie na listę), nie z mapy tras aktywnych — inaczej wykonana by nie dotarła.
    """
    wydrukowane = [p for p in paczki_zamowienia if p.label_printed_at is not None]
    if not wydrukowane:
        return False
    if order.logistics_closed_at is not None:
        trasa_napisu = trasa
    else:
        trasa_napisu = trasa if trasa is not None and trasa.status in STATUSY_TRASY_AKTYWNE else None
    napis = paczki_druk.napis_sposobu(order, trasa_napisu)
    return any(p.label_delivery_text != napis for p in wydrukowane)


def _problem(order):
    """Otwarty problem z Weryfikacji (powód, notatka, kiedy) albo None."""
    if order.problem_at is None:
        return None
    return {'powod': order.problem_reason,
            'etykieta': weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
            'notatka': order.problem_note, 'kiedy': order.problem_at.isoformat()}


def okno_weryfikacji(teraz=None):
    """
    Funkcja bez argumentów zwracająca początek okna listy Weryfikacji (weryfikacja.poczatek_okna).
    Liczy go dopiero przy pierwszym wywołaniu i pamięta — lista woła ją raz na całą listę i tylko
    wtedy, gdy któryś wiersz naprawdę jej potrzebuje (zamknięte, spakowane, bez paczek), więc zwykła
    lista nie dokłada żadnego zapytania, a przy wielu takich wierszach nadal jest jedno.
    """
    teraz = teraz or get_local_now()
    pamiec = []

    def okno():
        if not pamiec:
            pamiec.append(weryfikacja.poczatek_okna(teraz))
        return pamiec[0]
    return okno


def _bez_paczek(order, aktywne, paczki_zamowienia, okno):
    """
    Plakietka „BEZ PACZEK” (spec 11) w TYM SAMYM zakresie co filtr i licznik „Bez paczek”
    (weryfikacja.warunek_bez_paczek): zamówienie bez aktualnych paczek, którego wszystkie
    niezanulowane pozycje są dokładnie 'spakowane', i które jest w zakresie listy Weryfikacji —
    otwarte w Logistyce albo spakowane nie wcześniej niż początek okna. Bez tego historyczne
    zamówienia kurierskie (zamknięte, dawno spakowane) dostawałyby plakietkę przy wyszukiwaniu
    zamkniętych, choć filtr ich nie pokazuje.
    """
    if paczki_zamowienia or not wszystkie_w(order, ('spakowane',)):
        return False
    if order.logistics_closed_at is None:
        return True
    spakowano = max((p.packaging_completed_at for p in aktywne if p.packaging_completed_at), default=None)
    return spakowano is not None and spakowano >= okno()


def serializuj(order, geo=None, trasa=None, paczki_zamowienia=None, okno_weryfikacji_zamowien=None):
    if paczki_zamowienia is None:
        # Pojedynczy wiersz (odświeżenie po akcji) — listy podają mapę jednym zapytaniem.
        paczki_zamowienia = paczki.aktualne_paczki(order.id)
    # Początek okna Weryfikacji: lista podaje jeden wspólny (okno_weryfikacji()), pojedynczy wiersz
    # liczy sam — i tylko jeśli go potrzebuje.
    okno = okno_weryfikacji_zamowien or okno_weryfikacji()
    aktywne = aktywne_produkty(order)
    sposob = sposoby.normalizuj(order.override_delivery_method)
    terminy = [p.deadline_date for p in aktywne if p.deadline_date]
    ustawiono = order.delivery_method_set_at
    return {
        'id': order.id,
        'numer': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'klient': order.client_name,
        'miasto': order.delivery_city,
        'kod': order.delivery_postcode,
        'adres': order.delivery_address,
        'metoda_z_base': order.delivery_method,
        'podpowiedz': sposoby.podpowiedz(order),
        'sposob': sposob,
        'sposob_etykieta': sposoby.etykieta(sposob),
        'etap': _etap(aktywne, trasa),
        'termin': min(terminy).isoformat() if terminy else None,
        'm3': round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4),
        'spakowane': wszystkie_spakowane(order),
        'wydane': order.handed_over_at.isoformat() if order.handed_over_at else None,
        'zamkniete': order.logistics_closed_at is not None,
        'base_czeka': bool(order.bl_delivery_method_pending or order.bl_status_pending_id
                           or order.bl_address_pending),
        'etykiety_sprzed_zmiany': bool(ustawiono) and any(
            p.label_printed_at is not None and p.label_printed_at < ustawiono for p in aktywne),
        'etykiety_paczek_sprzed_zmiany': _etykiety_paczek_sprzed_zmiany(order, trasa, paczki_zamowienia),
        # Krok 4.3 (spec 11): paczki pod kolumną Etap, plakietka „BEZ PACZEK”, ikona problemu.
        'paczki': ({'opis': paczki.opis_paczek(paczki_zamowienia), 'liczba': len(paczki_zamowienia),
                    'zweryfikowane': sum(1 for p in paczki_zamowienia if p.verified_at is not None),
                    # Krok 4.4: panel tras pokazuje „załadowano 1/2” przy przystanku.
                    'zaladowane': sum(1 for p in paczki_zamowienia if p.loaded_at is not None)}
                   if paczki_zamowienia else None),
        'bez_paczek': _bez_paczek(order, aktywne, paczki_zamowienia, okno),
        'problem': _problem(order),
        'zweryfikowano': order.verified_at.isoformat() if order.verified_at else None,
        'przepakowanie': bool(order.repack_required),
        # Rozwijany wiersz listy: wszystkie pozycje (anulowane też — wyszarzone).
        'pozycje': [_pozycja(p) for p in sorted(
            order.products, key=lambda p: (p.product_sequence_in_order or 0, p.id or 0))],
        'geo': _geo(geo),
        'trasa': {'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status}
                 if trasa is not None else None,
    }


def _klucz(wiersz):
    return (wiersz['sposob'] is not None, wiersz['termin'] is None,
            wiersz['termin'] or '', wiersz['numer'] or '')


def pobierz(sposob=None, etap=None, q=None, zamkniete=False, woj=None, stan=None):
    """
    UWAGA (R3, poprawka względem briefu): wszystkie filtry (q, otwarte/zamknięte,
    sposob) muszą trafić do zapytania PRZED order_by/limit. W SQLAlchemy < 2.0
    Query.filter() wołane PO limit() rzuca InvalidRequestError — pierwotna wersja
    (limit dla zamkniętych, potem filter dla sposob) wywalałaby się na
    GET /orders?zamkniete=1&q=...&sposob=... kodem 500. Z tego samego powodu
    `sposob=bez_trasy` (etap 3: transport własny bez przystanku na żadnej trasie)
    jest filtrem SQL w tym samym bloku, nie post-filtrem Pythonowym po wczytaniu —
    inaczej `zamkniete=1&q=...&sposob=bez_trasy` obcięłoby wynik do LIMIT_ZAMKNIETYCH
    PRZED odsianiem zamówień na trasie, gubiąc trafienia spoza limitu.

    Runda 2 (spec 2.5): `woj` — lista identyfikatorów z wojewodztwa.opcje(); filtr SQL
    z kodu pocztowego i kraju w tym samym bloku (R3), przed order_by/limit zamkniętych.

    Krok 4.3 (spec 11): `stan` ∈ STANY_WERYFIKACJI — filtr SQL z weryfikacja.py w tym samym
    bloku (R3). Ma własny zakres i zastępuje podział otwarte/zamknięte oraz limit zamkniętych.
    """
    # Konfiguracje pozycji (gatunek, technologia, klasa) jednym zapytaniem na listę —
    # bez tego każda pozycja dociągałaby swoją osobno (setki zapytań co odświeżenie).
    zapytanie = ProductionOrder.query.options(
        selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration))
    if q:
        zapytanie = zapytanie.filter(*_warunki_frazy(q))
    # Krok 4.3 (spec 11): filtry Weryfikacji mają własny zakres (zamówienia kurierskie zamykają się
    # przy spakowaniu, a nadal czekają na weryfikację) — zastępują podział otwarte/zamknięte.
    teraz = get_local_now()
    if stan == 'do_weryfikacji':
        zapytanie = zapytanie.filter(weryfikacja.warunek_do_weryfikacji(teraz))
    elif stan == 'problem':
        zapytanie = zapytanie.filter(weryfikacja.warunek_problemu())
    elif stan == 'bez_paczek':
        zapytanie = zapytanie.filter(weryfikacja.warunek_bez_paczek(teraz))
    elif not zamkniete:
        zapytanie = zapytanie.filter(ProductionOrder.logistics_closed_at.is_(None))
    if sposob == 'brak':
        zapytanie = zapytanie.filter(warunek_bez_sposobu())
    elif sposob == 'bez_trasy':
        # Transport własny bez przystanku na ŻADNEJ trasie (dowolnego statusu) —
        # w SQL, nie jako post-filtr, patrz uwaga w docstringu.
        zapytanie = zapytanie.filter(
            ProductionOrder.override_delivery_method == sposoby.TRANSPORT,
            ~ProductionOrder.id.in_(db.session.query(RouteStop.order_id)))
    elif sposoby.normalizuj(sposob):
        zapytanie = zapytanie.filter(ProductionOrder.override_delivery_method == sposob)
    if woj:
        zapytanie = zapytanie.filter(wojewodztwa.warunek(woj))
    if zamkniete and not stan:
        zapytanie = zapytanie.order_by(ProductionOrder.id.desc()).limit(LIMIT_ZAMKNIETYCH)
    zamowienia = zapytanie.all()
    ids = [o.id for o in zamowienia]
    punkty = geocoding.geo_zamowien(ids)
    trasy = routes.trasy_zamowien(ids)
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    okno = okno_weryfikacji(teraz)   # jedno na listę, liczone dopiero gdy wiersz go potrzebuje
    wiersze = [serializuj(o, punkty.get(o.id), trasy.get(o.id), pakunki.get(o.id, []), okno)
               for o in zamowienia]
    if etap:
        wiersze = [w for w in wiersze if w['etap']['status'] == etap]
    return sorted(wiersze, key=_klucz)


def liczniki():
    wynik = {'brak': 0, sposoby.KURIER: 0, sposoby.TRANSPORT: 0, sposoby.ODBIOR: 0}
    for (wartosc,) in (ProductionOrder.query.with_entities(ProductionOrder.override_delivery_method)
                       .filter(ProductionOrder.logistics_closed_at.is_(None)).all()):
        klucz = sposoby.normalizuj(wartosc) or 'brak'
        wynik[klucz] += 1
    return wynik


def liczniki_weryfikacji():
    """Liczby przy filtrach Weryfikacji (spec 11) — trzy zapytania COUNT, niezależne od listy."""
    teraz = get_local_now()
    return {'do_weryfikacji': weryfikacja.liczba_do_weryfikacji(teraz),
            'problem': weryfikacja.liczba_problemow(),
            'bez_paczek': db.session.query(func.count(ProductionOrder.id)).filter(
                weryfikacja.warunek_bez_paczek(teraz)).scalar() or 0}
