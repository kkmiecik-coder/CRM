# -*- coding: utf-8 -*-
"""
Hurtowa zmiana statusu pozycji — wspólny serwis panelu produkcji (`products_api.bulk_action`) i tabletu kierownika hali.

Ciała funkcji przeniesione z `routers/api/products_api.py` bez zmian (refaktor bez zmiany zachowania), z dwiema
świadomymi różnicami kontraktu:
- `zmien_status` NIE commituje i NIE cofa transakcji — robi to wołający (panel: `bulk_action`, tablet: handler z
  idempotencją). Kolejność blokad (blokada tras → zamówienia rosnąco → ich pozycje) i odczyty bieżące zostają
  w `zablokuj_zamowienia_i_pozycje`; wołający ma zacząć transakcję od tej funkcji (pierwszy odczyt nowej
  transakcji), bez żadnego odczytu wcześniej.
- wynik niesie dodatkowe klucze dla wołającego: `pozycje` (zablokowane obiekty ORM, do DTO), `nieznane`
  (identyfikatory, których nie ma w bazie) i `nowe_stanowisko` (stanowisko, któremu doszła praca).
  Odpowiedź webowa ich nie zawiera (`bulk_action` je obcina).
"""

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.models import ProductionItem, get_local_now
from modules.production.services import blokady_zamowien

logger = get_structured_logger('production.api')


# 'czeka_na_logistyke' zostaje w ENUM do sprzątania, ale nie jest już etapem pipeline'u — logistyka żyje równolegle
# na zamówieniu. Statusy po spakowaniu nadaje tylko logistyka (spec 8.6) — ręcznie ich nie ustawiamy.
DOZWOLONE_STATUSY = frozenset(set(ProductionItem.current_status.type.enums) - {'czeka_na_logistyke'}
                              - set(sposoby.STATUSY_LOGISTYCZNE))


def zablokuj_zamowienia_i_pozycje(product_ids):
    """
    Zaznaczone pozycje hurtowej zmiany statusu, wczytane po zablokowaniu ich zamówień. Zwraca krotkę
    (zablokowane zamówienia rosnąco po id, zaznaczone pozycje rosnąco po id).

    Kolejność blokad jak w zapisach Weryfikacji: zamówienia FOR UPDATE (rosnące id) → wszystkie pozycje każdego
    zamówienia FOR UPDATE po `order_id` (`blokady_zamowien.zablokuj_pozycje`, rosnąco po id) → dopiero zmiany
    statusów i reguła uniewaznij_etapy. Dotąd hurt najpierw zapisywał
    pozycje (flush daje blokadę pozycji), a dopiero potem reguła zapisywała zamówienie — odwrotnie niż
    Weryfikacja (zamówienie → pozycje), stąd zakleszczenie MySQL 1213. Do tego zamówienie i pozycje szły
    z migawki REPEATABLE READ: zamówienie, które Weryfikacja zdążyła zweryfikować, miało w pamięci stare
    `verified_at`, więc reguła kasowała paczki, ale nie czyściła weryfikacji.

    Identyfikatory zamówień bierzemy zwykłym odczytem `order_id` (ta kolumna pozycji się nie zmienia), a
    zamówienia i pozycje czytamy odczytem bieżącym (`populate_existing`): obiekty w sesji dostają wartości
    z bazy zamiast migawki. `p.order` każdej pozycji wskazuje te same, odświeżone obiekty. Wołać PRZED
    jakąkolwiek zmianą obiektów w sesji: `populate_existing` nadpisuje atrybuty, a autoflush zapisałby
    zmienioną pozycję przed blokadą zamówienia.

    (Krok 4.4a, runda 4) Zamówienia i pozycje blokuje `blokady_zamowien` (zablokuj_zamowienia, potem
    zablokuj_pozycje zamówienie po zamówieniu, rosnąco): blokowane są WSZYSTKIE pozycje każdego zamówienia po
    `order_id`, nie tylko zaznaczone, bo reguła unieważniania i przeliczenie zamknięcia decydują na całym składzie
    zamówienia. Wołający trzyma zwróconą listę zamówień do końca decyzji: wynik blokady, którego nikt nie trzymał,
    znikał z mapy tożsamości (trzyma czyste obiekty słabo), a `p.order` czytało wtedy zamówienie od nowa zwykłym
    SELECT-em — na MySQL z migawki sprzed blokady.

    (Fala końcowa 4.4b, decyzja Konrada A2) Przed blokadami zamówień — globalna blokada tras (`routes.zablokuj_trasy`)
    i odczyt bieżący przystanków tych zamówień na trasach załadowanych i w drodze (`_trasy_w_drodze`): kolejność
    Dostawy (blokada tras → zamówienia → paczki i pozycje). Status trasy, na którym hurt odmawia, czytamy pod blokadą,
    która go chroni. Zwraca więc trójkę: (zamówienia, zaznaczone pozycje, wynik `_trasy_w_drodze`).
    """
    from modules.production.logistics.services import routes
    wiersze = (db.session.query(ProductionItem.id, ProductionItem.order_id)
               .filter(ProductionItem.id.in_(product_ids)).all())
    zaznaczone = {product_id for product_id, _order_id in wiersze}
    id_zamowien = [order_id for _product_id, order_id in wiersze]
    routes.zablokuj_trasy()
    w_drodze = _trasy_w_drodze(id_zamowien)
    zamowienia = blokady_zamowien.zablokuj_zamowienia(id_zamowien)
    pozycje = []
    for zamowienie in zamowienia:
        pozycje.extend(p for p in blokady_zamowien.zablokuj_pozycje(zamowienie) if p.id in zaznaczone)
    return zamowienia, sorted(pozycje, key=lambda p: p.id), w_drodze


# Decyzja Konrada 2.10 (A2): opis statusu trasy w odmowie hurtu.
_OPIS_TRASY_W_DRODZE = {'zaladowana': u'załadowana', 'w_trasie': u'w drodze'}


def _trasy_w_drodze(order_ids):
    """
    {order_id: (nazwa trasy, status, stan przystanku: 'dostarczony' | 'niedostarczony' | None)} zamówień, których
    przystanek jest na trasie
    załadowanej albo w drodze
    (`dostawa.STATUSY_W_DRODZE`). Odczyt BIEŻĄCY (blokada współdzielona, LOCK IN SHARE MODE), wołany pod globalną
    blokadą tras: przystanki i trasy zapisuje tylko jej posiadacz, więc wynik obowiązuje do końca transakcji. Zwykły
    SELECT widziałby migawkę REPEATABLE READ sprzed czekania na blokadę (np. załadunek zakończony w tej chwili).
    """
    from modules.production.logistics.models import Route, RouteStop
    from modules.production.logistics.services import dostawa
    ids = sorted({i for i in order_ids if i is not None})
    if not ids:
        return {}
    wiersze = (db.session.query(RouteStop.order_id, Route.name, Route.status, RouteStop.delivered_at,
                                RouteStop.not_delivered_at)
               .join(Route, Route.id == RouteStop.route_id)
               .filter(RouteStop.order_id.in_(ids), Route.status.in_(dostawa.STATUSY_W_DRODZE))
               .with_for_update(read=True).all())
    return {order_id: (nazwa, status, 'dostarczony' if dostarczono is not None
                       else ('niedostarczony' if niedostarczono is not None else None))
            for order_id, nazwa, status, dostarczono, niedostarczono in wiersze}


def _odmowa_trasy_w_drodze(zamowienie, nazwa, status, stan):
    """Komunikat odmowy hurtu z wykonalnym krokiem: przystanek już dostarczony (trasa w drodze) cofa się przez
    „Cofnij dostarczenie” (Ruling 30.6); oznaczony jako niedostarczony (U10, Ruling 32) wisi na trasie do jej końca
    albo do „Zdejmij z trasy” w panelu tras; pozostałe — „Cofnij załadunek” (trasa załadowana) albo „Niedostarczone”
    i „Zdejmij z trasy” (trasa w drodze)."""
    numer = zamowienie.internal_order_number or u'#{}'.format(zamowienie.id)
    opis = _OPIS_TRASY_W_DRODZE.get(status, status)
    if stan == 'niedostarczony':
        return (u'Zamówienie {} jest niedostarczone na trasie „{}” ({}) — wróci do puli po zakończeniu trasy albo po '
                u'„Zdejmij z trasy” w panelu tras.'.format(numer, nazwa, opis))
    if stan == 'dostarczony':
        return (u'Zamówienie {} jest dostarczone na trasie „{}” ({}) — najpierw Cofnij dostarczenie.'
                .format(numer, nazwa, opis))
    # Runda 1 U10: „Niedostarczone” zostawia zamówienie na trasie do jej końca, więc samo nie wystarcza — z trasy
    # w drodze zdejmuje je dopiero „Zdejmij z trasy” w panelu (albo zamknięcie trasy); „Cofnij załadunek” jest tylko dla
    # trasy załadowanej.
    if status == 'zaladowana':
        return (u'Zamówienie {} jest na trasie „{}” ({}) — najpierw Cofnij załadunek.'.format(numer, nazwa, opis))
    return (u'Zamówienie {} jest na trasie „{}” ({}) — najpierw Niedostarczone, potem Zdejmij z trasy w panelu tras.'
            .format(numer, nazwa, opis))


def zmien_status(product_ids, nowy_status, *, user_id=None, worker_id=None, opis=u'zmiana statusu w panelu'):
    """
    Cały zapis hurtowej zmiany statusu w jednej transakcji: blokady (`zablokuj_zamowienia_i_pozycje`), pętla
    statusów i reguła unieważniania etapów z przeliczeniem zamknięcia. NIE commituje i NIE cofa transakcji —
    wołający commituje po sukcesie, a przy `success: False` (odmowa dla wszystkich zaznaczonych pozycji) cofa
    transakcję sam (w panelu `bulk_action` odpowiada wtedy 409). Zwraca słownik odpowiedzi (`results`) albo None,
    gdy po blokadzie nie ma żadnej z zaznaczonych pozycji (wołający odpowiada 404).

    Wynik liczy się od zera przy każdym wywołaniu, a zablokowane zamówienia trzyma lokalna lista do końca decyzji
    (silne referencje), więc funkcję wolno wywołać drugi raz po rollbacku: jedno ponowienie po zakleszczeniu 1213,
    patrz `bulk_action`. `user_id` podaje wołający, pobrany przed pierwszą próbą: po rollbacku `current_user.id`
    byłby zwykłym SELECT-em, czyli odczytem spoza blokad. Tablet kierownika podaje zamiast niego `worker_id`
    (kolumna `prod_logistics_log.worker_id`) i własny `opis` do notatek logu logistyki.

    Dodatkowe klucze wyniku dla wołającego: `pozycje` (zablokowane obiekty zaznaczonych pozycji, rosnąco po id),
    `nieznane` (przekazane identyfikatory, których nie ma w bazie), `nowe_stanowisko` (stanowisko, któremu doszła
    praca nowym statusem, albo None) i `zdjete_stanowiska` (także przy odmowie — wtedy pusta lista).

    Decyzje Konrada 2.10 (fala końcowa kroku 4.4b):
    - A2: zamówienie, którego przystanek jest na trasie załadowanej albo w drodze, hurt odmawia — bez żadnej zmiany
      jego pozycji; odmowa per zamówienie w `errors`, jego zaznaczone pozycje w `failed_count`, reszta zaznaczonych
      przechodzi. Gdy odmowa obejmuje wszystkie zaznaczone pozycje, nic się nie zapisuje (wołający cofa transakcję),
      a wynik ma `success: False` i `error` — wołający odpowiada 409. Anulowanie przechodzi: to nie powrót do
      produkcji, a Dostawa obsługuje zamówienie anulowane („Niedostarczone”, przystanek anulowanego w całości).
    - A1: zmiana na „spakowane” na zamówieniu zweryfikowanym (verified_at albo pozycja 'zweryfikowane' przed zmianą)
      unieważnia weryfikację tą samą regułą co „Cofnij weryfikację” (weryfikacja.cofnij_weryfikacje_zamowienia) —
      chyba że reguła unieważniania etapów zrobiła to już sama (zwróciła True).
    """
    # Ręczna zmiana statusu może zamknąć albo otworzyć cykl logistyczny zamówienia.
    from modules.production.logistics.services.delivery import aktywne_produkty, przelicz_zamkniecie
    from modules.production.logistics.services import weryfikacja
    from modules.production.priorytety.services import stol
    zamowienia, products, w_drodze = zablokuj_zamowienia_i_pozycje(product_ids)
    if not products:
        return None

    znalezione = {p.id for p in products}
    widziane = set()
    nieznane = []
    for product_id in product_ids:
        if product_id not in znalezione and product_id not in widziane:
            nieznane.append(product_id)
        widziane.add(product_id)

    results = {
        'success': True,
        'action': 'update_status',
        'processed_count': 0,
        'failed_count': 0,
        'errors': []
    }

    # A2 — decyzja na przystankach i trasach z odczytu bieżącego pod blokadą tras (zablokuj_zamowienia_i_pozycje).
    odmowy = {}
    if nowy_status != 'anulowane':
        odmowy = {z.id: _odmowa_trasy_w_drodze(z, *w_drodze[z.id]) for z in zamowienia if z.id in w_drodze}
    results['errors'].extend(odmowy[z.id] for z in zamowienia if z.id in odmowy)
    # A1 — stan PRZED zmianą statusów, na zablokowanych obiektach (zamówienie i wszystkie jego pozycje).
    zweryfikowane = set()
    if nowy_status == 'spakowane':
        zweryfikowane = {z.id for z in zamowienia if z.id not in odmowy and (
            z.verified_at is not None or any(p.current_status == 'zweryfikowane' for p in aktywne_produkty(z)))}

    for product in products:
        if product.order_id in odmowy:
            results['failed_count'] += 1
            continue
        try:
            if nowy_status and hasattr(ProductionItem, 'current_status'):
                product.current_status = nowy_status
                results['processed_count'] += 1
        except Exception as e:
            logger.error(f"Błąd bulk action dla produktu {product.id}", extra={'error': str(e)})
            results['errors'].append(f'Błąd produktu {product.id}: {str(e)}')
            results['failed_count'] += 1

    if odmowy and not results['processed_count']:
        # Odmowa obejmuje wszystkie zaznaczone pozycje: nic do zapisania (wołający cofa transakcję; 409 w bulk_action).
        results['success'] = False
        results['error'] = u' '.join(results['errors'])
        results['zdjete_stanowiska'] = []
        results['nowe_stanowisko'] = None
        results['nieznane'] = nieznane
        results['pozycje'] = products
        return results

    teraz = get_local_now()
    # Priorytety produkcji (spec 2026-10-04, 5.1): pozycja wstrzymana, anulowana albo przestawiona na inny status
    # schodzi ze stanowiska — jej kafel schodzi ze stołu w tej samej transakcji, pod trzymaną blokadą zamówienia.
    zdjete_ze_stolu = set()
    # Stała kolejność (rosnące id): reguła unieważniania zapisuje wiersz zamówienia i bierze
    # blokady paczek, więc dwa równoległe zapisy na nakładających się zamówieniach muszą
    # brać je w tej samej kolejności — inaczej zakleszczenie (MySQL 1213). `zamowienia` to wynik
    # blokady (rosnąco po id, ze składem z odczytu bieżącego): decyzja nie czyta zamówień od nowa.
    for zamowienie in zamowienia:
        if zamowienie.id in odmowy:
            continue
        # Pozycja cofnięta do produkcji unieważnia paczki, weryfikację i załadunek zamówienia.
        cofnieto = weryfikacja.uniewaznij_etapy(zamowienie, teraz, opis, user_id=user_id, worker_id=worker_id)
        if zamowienie.id in zweryfikowane and not cofnieto:
            _cofnij_weryfikacje_hurtem(zamowienie, teraz, user_id, worker_id, opis)
        przelicz_zamkniecie(zamowienie)
        zdjete_ze_stolu |= stol.zdejmij_nieaktualne(zamowienie, teraz=teraz)

    # Stanowiska, z których zdjęto kafel — wołający wysyła im sygnał po commicie (spec 5.4).
    results['zdjete_stanowiska'] = sorted(zdjete_ze_stolu)
    # Stanowisko, na które pozycje trafiły nowym statusem (doszła mu praca) — też sygnał po commicie.
    results['nowe_stanowisko'] = stol.STANOWISKO_STATUSU.get(nowy_status)
    results['nieznane'] = nieznane
    results['pozycje'] = products
    return results


def _cofnij_weryfikacje_hurtem(zamowienie, teraz, user_id, worker_id=None, opis=u'zmiana statusu w panelu'):
    """
    Decyzja Konrada 2.10 (A1): hurt → „spakowane” na zamówieniu zweryfikowanym = „Cofnij weryfikację”
    (weryfikacja.cofnij_weryfikacje_zamowienia: pozycje zweryfikowane → spakowane, verified_at zamówienia i znaczniki
    weryfikacji paczek czyszczone, znaczniki załadunku czyszczone, log `weryfikacja_cofnieta`, przeliczenie zamknięcia).
    Bez wysyłki do Base. — jak „Cofnij weryfikację”.

    Zamówienie i wszystkie jego pozycje hurt już blokuje; paczki blokujemy tu (paczki.zablokuj_stan: paczki, potem
    pozycje — już trzymane), w kolejności reguły unieważniania etapów. Najpierw flush: odczyt bieżący nadpisuje
    obiekty w sesji (populate_existing), więc statusy ustawione w pętli hurtu muszą być już w bazie.
    """
    from modules.production.logistics.services import delivery, paczki, weryfikacja
    db.session.flush()
    aktualne = paczki.zablokuj_stan(zamowienie)
    weryfikacja.cofnij_weryfikacje_zamowienia(zamowienie, delivery.aktywne_produkty(zamowienie), aktualne,
                                              opis, worker_id, None, teraz, user_id=user_id)
