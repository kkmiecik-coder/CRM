# -*- coding: utf-8 -*-
"""
Ustawienia priorytetów w `prod_config` (spec 2026-10-04, sekcja 8.6): odczyt dla serwisów i panelu, walidacja
i zapis z panelu (`PUT /production/api/priorytety/ustawienia` — jedyna droga zapisu tych kluczy).

Odczyt: każda funkcja zwraca wartość poprawną — gdy wiersza nie ma, wartość jest pusta, spoza listy albo nie jest
liczbą, wraca domyślna ze `stale` (zła wartość z ostrzeżeniem w logu).

Odczyt czyta wiersz `prod_config` WPROST (jedno zapytanie po kluczu), bez pamięci podręcznej procesu
`config_service` (60 minut): zmiana trybu stanowiska, K, limitu albo progu z panelu musi dotrzeć do wszystkich
workerów gunicorna od razu, także wycofanie stanowiska na `stary` (krok K2, decyzja karty). Odczyt przez
`db.session` idzie bez autoflushu — nie wypycha niezapisanej pracy wołającego (np. importu z Base.). Z `sesja`
(`prog_blisko` dla `kolejka.utrwal`) czyta tą sesją i nie dotyka `db.session`.

Funkcje nie commitują.
"""
from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionConfig, get_local_now
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog

logger = get_structured_logger('production.priorytety.ustawienia')

# Zakresy liczb przy ZAPISIE z panelu (spec 10; plan K2, Doprecyzowania p. 8). Odczyt toleruje szerzej (tylko
# dolne granice), żeby ręcznie wpisana wartość nie wywróciła stanowiska.
ZAKRES_MIEJSC = (1, 5)
ZAKRES_LIMITU = (1, 50)
ZAKRES_BLISKO = (0, 15)
# Dni terminu nowych zamówień (plan K4b, Doprecyzowania 5; pole UI miało zawsze max 90).
ZAKRES_TERMINU = (1, 90)
# Stanowiska na stałe w trybie `stary` (spec 2026-10-04, ustalenie 15 i sekcja 10: Lakiernia pracuje na pełnej liście
# ułożonej po wykończeniu) — `PUT /ustawienia` odrzuca dla nich tryb `stol`. Wartość: nazwa do komunikatu.
STANOWISKA_BEZ_STOLU = {'painting': u'Lakiernia'}


def _sprawdz_stanowisko(stanowisko):
    if stanowisko not in stale.STANOWISKA:
        raise ValueError('Nieznane stanowisko: %r' % (stanowisko,))
    return stanowisko


def _surowa(klucz, sesja=None):
    """Tekst wiersza `prod_config` albo None (brak wiersza, wartość pusta)."""
    def odczyt(s):
        return s.query(ProductionConfig.config_value).filter(ProductionConfig.config_key == klucz).first()

    if sesja is None:
        with db.session.no_autoflush:
            wiersz = odczyt(db.session)
    else:
        wiersz = odczyt(sesja)
    if wiersz is None or wiersz[0] in (None, ''):
        return None
    return wiersz[0]


def _z_listy(klucz, wartosc, dozwolone, domyslna):
    if wartosc is None:
        return domyslna
    if wartosc in dozwolone:
        return wartosc
    logger.warning('Ustawienie priorytetów spoza listy — przyjmuję wartość domyślną',
                   extra={'klucz': klucz, 'wartosc': str(wartosc)[:64], 'domyslna': domyslna})
    return domyslna


def _liczba(klucz, wartosc, domyslna, minimum):
    if wartosc is None:
        return domyslna
    try:
        if isinstance(wartosc, bool):
            raise ValueError('wartosc logiczna')
        liczba = int(wartosc)
        if liczba < minimum:
            raise ValueError('ponizej minimum')
        return liczba
    except (TypeError, ValueError):
        logger.warning('Ustawienie priorytetów nie jest poprawną liczbą — przyjmuję wartość domyślną',
                       extra={'klucz': klucz, 'wartosc': str(wartosc)[:64], 'domyslna': domyslna})
        return domyslna


def _jednostka_domyslna(stanowisko):
    return 'zamowienie' if stanowisko in stale.STANOWISKA_ZAMOWIENIOWE else 'pozycja'


def tryb(stanowisko):
    """`stary` (pełna lista na tablecie, ZAKOŃCZ bez bramki) albo `stol`."""
    klucz = stale.klucz_tryb(_sprawdz_stanowisko(stanowisko))
    return _z_listy(klucz, _surowa(klucz), stale.TRYBY, stale.TRYBY[0])


def miejsca(stanowisko):
    """Liczba miejsc na stole stanowiska (K)."""
    klucz = stale.klucz_stol(_sprawdz_stanowisko(stanowisko))
    return _liczba(klucz, _surowa(klucz), stale.STOL_K, 1)


def jednostka(stanowisko):
    """Jednostka kafla: `pozycja`, a na Formatowaniu i Pakowaniu domyślnie `zamowienie`."""
    klucz = stale.klucz_jednostka(_sprawdz_stanowisko(stanowisko))
    return _z_listy(klucz, _surowa(klucz), stale.JEDNOSTKI, _jednostka_domyslna(stanowisko))


def limit(stanowisko):
    """Limit otwartych odłożeń stanowiska."""
    klucz = stale.klucz_limit(_sprawdz_stanowisko(stanowisko))
    return _liczba(klucz, _surowa(klucz), stale.LIMIT_ODLOZEN, 1)


def prog_blisko(sesja=None):
    """
    Próg tagu „Blisko terminu” w dniach roboczych.

    Z `sesja` czyta wiersz `prod_config` TĄ sesją — bez dotykania `db.session` (`kolejka.utrwal` pracuje na
    własnej sesji i nie może niczego czytać przez sesję wołającego).
    """
    return _liczba(stale.KLUCZ_BLISKO, _surowa(stale.KLUCZ_BLISKO, sesja), stale.BLISKO_TERMINU_DNI, 0)


def min_app_version():
    """Minimalny kod wersji appki, od którego działa tryb `stol` (0 = brak bramki)."""
    return _liczba(stale.KLUCZ_MIN_APP, _surowa(stale.KLUCZ_MIN_APP), stale.MIN_APP_VERSION_CODE, 0)


def typ_dni_terminu():
    """`robocze` albo `kalendarzowe` — jak liczyć termin NOWYCH zamówień (istniejących nie przelicza nikt)."""
    return _z_listy(stale.KLUCZ_TYP_DNI, _surowa(stale.KLUCZ_TYP_DNI), stale.TYPY_DNI,
                    stale.DEADLINE_DAY_TYPE_DOMYSLNY)


def termin_surowe_dni():
    """Dni terminu zamówień surowych (`DEADLINE_DEFAULT_DAYS`)."""
    return _liczba(stale.KLUCZ_TERMIN_SUROWE, _surowa(stale.KLUCZ_TERMIN_SUROWE), stale.TERMIN_SUROWE_DNI, 1)


def termin_wykonczone_dni():
    """Dni terminu zamówień z wykończeniem (`DEADLINE_FINISHED_DAYS`)."""
    return _liczba(stale.KLUCZ_TERMIN_WYKONCZONE, _surowa(stale.KLUCZ_TERMIN_WYKONCZONE),
                   stale.TERMIN_WYKONCZONE_DNI, 1)


def klucz_blokady(stanowisko):
    """Klucz wiersza `prod_config`, który blokuje pobieranie na stół stanowiska."""
    return stale.klucz_blokady(_sprawdz_stanowisko(stanowisko))


# ── panel: odczyt, walidacja, zapis ─────────────────────────────────────────────────────────────────────────

def odczyt_panelu():
    """Stan ustawień dla panelu: siedem stanowisk (nazwa, tryb, miejsca, jednostka, limit odłożeń), próg „Blisko
    terminu”, minimalna wersja appki, typ dni terminu i liczby dni terminu (surowe, z wykończeniem)."""
    from modules.production.services.station_catalog import station_label
    return {
        'stanowiska': {kod: {'nazwa': station_label(kod), 'tryb': tryb(kod), 'miejsca': miejsca(kod),
                             'jednostka': jednostka(kod), 'limit_odlozen': limit(kod)}
                       for kod in stale.STANOWISKA},
        'blisko_terminu_dni': prog_blisko(),
        'min_app_version_code': min_app_version(),
        'deadline_day_type': typ_dni_terminu(),
        'deadline_default_days': termin_surowe_dni(),
        'deadline_finished_days': termin_wykonczone_dni(),
    }


def _calkowita(wartosc):
    return isinstance(wartosc, int) and not isinstance(wartosc, bool)


def _z_zakresu(zakres):
    minimum, maksimum = zakres

    def sprawdz(wartosc):
        if not _calkowita(wartosc) or wartosc < minimum or (maksimum is not None and wartosc > maksimum):
            if maksimum is None:
                return u'podaj liczbę całkowitą od {}.'.format(minimum)
            return u'podaj liczbę całkowitą od {} do {}.'.format(minimum, maksimum)
        return None
    return sprawdz


def _z_wyboru(dozwolone):
    def sprawdz(wartosc):
        if wartosc not in dozwolone:
            return u'dozwolone wartości: {}.'.format(', '.join(dozwolone))
        return None
    return sprawdz


# pole panelu → (funkcja klucza albo klucz, config_type, sprawdzenie). Klucz blokady stołu NIE jest edytowalny.
POLA_STANOWISKA = {
    'tryb': (stale.klucz_tryb, 'string', _z_wyboru(stale.TRYBY)),
    'miejsca': (stale.klucz_stol, 'integer', _z_zakresu(ZAKRES_MIEJSC)),
    'jednostka': (stale.klucz_jednostka, 'string', _z_wyboru(stale.JEDNOSTKI)),
    'limit_odlozen': (stale.klucz_limit, 'integer', _z_zakresu(ZAKRES_LIMITU)),
}
POLA_GLOBALNE = {
    'blisko_terminu_dni': (stale.KLUCZ_BLISKO, 'integer', _z_zakresu(ZAKRES_BLISKO)),
    'min_app_version_code': (stale.KLUCZ_MIN_APP, 'integer', _z_zakresu((0, None))),
    'deadline_day_type': (stale.KLUCZ_TYP_DNI, 'string', _z_wyboru(stale.TYPY_DNI)),
    # Terminy (krok K4b): zmiana dotyczy tylko zamówień importowanych po niej — bez przeliczania rang.
    'deadline_default_days': (stale.KLUCZ_TERMIN_SUROWE, 'integer', _z_zakresu(ZAKRES_TERMINU)),
    'deadline_finished_days': (stale.KLUCZ_TERMIN_WYKONCZONE, 'integer', _z_zakresu(ZAKRES_TERMINU)),
}


def waliduj(dane):
    """
    Walidacja CAŁEGO ciała `PUT /ustawienia` przed zapisem (dowolny podzbiór kształtu `odczyt_panelu`, bez
    `nazwa`). Czysta, bez bazy. Zwraca `({klucz_prod_config: (wartość_tekst, config_type)}, None)` albo
    `({}, (kod, pole, komunikat))`, gdzie `kod` ∈ `dane_niepoprawne`, `stanowisko_nieznane`, `ustawienie_niepoprawne`,
    `stanowisko_bez_stolu` (tryb `stol` dla Lakierni),
    a `pole` to ścieżka w ciele (np. `stanowiska.gluing.miejsca`; None, gdy ciało nie jest obiektem).
    """
    if not isinstance(dane, dict):
        return {}, ('dane_niepoprawne', None, u'Wyślij ustawienia jako obiekt JSON.')
    zmiany = {}
    for pole in sorted(dane):
        if pole != 'stanowiska' and pole not in POLA_GLOBALNE:
            return {}, ('dane_niepoprawne', pole, u'Nieznane pole „{}”.'.format(pole))

    stanowiska = dane.get('stanowiska', {})
    if not isinstance(stanowiska, dict):
        return {}, ('dane_niepoprawne', 'stanowiska', u'Pole „stanowiska” musi być obiektem.')
    for kod in sorted(stanowiska):
        sciezka = 'stanowiska.%s' % kod
        if kod not in stale.STANOWISKA:
            return {}, ('stanowisko_nieznane', sciezka, u'Nie ma stanowiska „{}”.'.format(kod))
        pola = stanowiska[kod]
        if not isinstance(pola, dict):
            return {}, ('dane_niepoprawne', sciezka, u'Pole „{}” musi być obiektem.'.format(sciezka))
        for nazwa in sorted(pola):
            pole = '%s.%s' % (sciezka, nazwa)
            if nazwa not in POLA_STANOWISKA:
                return {}, ('dane_niepoprawne', pole, u'Pola „{}” nie można zmienić.'.format(pole))
            funkcja_klucza, typ, sprawdz = POLA_STANOWISKA[nazwa]
            blad = sprawdz(pola[nazwa])
            if blad:
                return {}, ('ustawienie_niepoprawne', pole, u'Pole „{}”: {}'.format(pole, blad))
            if nazwa == 'tryb' and pola[nazwa] == 'stol' and kod in STANOWISKA_BEZ_STOLU:
                return {}, ('stanowisko_bez_stolu', pole,
                            u'{} pracuje zawsze w trybie listy, bez stołu.'.format(STANOWISKA_BEZ_STOLU[kod]))
            zmiany[funkcja_klucza(kod)] = (str(pola[nazwa]), typ)

    for pole in sorted(POLA_GLOBALNE):
        if pole not in dane:
            continue
        klucz, typ, sprawdz = POLA_GLOBALNE[pole]
        blad = sprawdz(dane[pole])
        if blad:
            return {}, ('ustawienie_niepoprawne', pole, u'Pole „{}”: {}'.format(pole, blad))
        zmiany[klucz] = (str(dane[pole]), typ)
    return zmiany, None


KOMUNIKAT_PROGU_WERSJI = (u'Najpierw wpisz minimalną wersję appki (kod wersji nowej appki). Przy progu 0 stół '
                          u'objąłby też starą appkę: dostałaby odmowę ZAKOŃCZ na wszystkim spoza stołu.')


def sprawdz_prog_wersji(zmiany):
    """
    Reguła stanu WYNIKOWEGO `PUT /ustawienia` (K4-poprawka-1; raport K3, rozstrz. 39): tryb `stol` przy progu wersji
    appki 0 to bramka stołu także dla starej appki, więc zapis nie może takiej kombinacji WPROWADZIĆ — ani ustawić
    `stol` stanowisku, które w bazie nie jest w `stol`, gdy próg wynikowy jest 0, ani obniżyć progu do 0 z wartości
    > 0, gdy jakieś stanowisko wynikowo jest w `stol`. Zapis, który kombinacji nie wprowadza (wycofanie na `stary`,
    zmiana K przy zastanym w bazie `stol` + 0), przechodzi — wycofanie nie może czekać na próg. Lakiernia pomijana
    (zawsze `stary`, spec 5.5).

    `zmiany` — wynik `waliduj` ({klucz: (wartość_tekst, config_type)}). Czyta stan bazy tymi samymi funkcjami co
    serwisy, bez zapisu. Zwraca None albo `(kod, pole, komunikat)` jak `waliduj`.
    """
    prog_bazy = min_app_version()
    prog = int(zmiany[stale.KLUCZ_MIN_APP][0]) if stale.KLUCZ_MIN_APP in zmiany else prog_bazy
    if prog > 0:
        return None
    stoly_bazy = set()
    stoly_wynikowe = set()
    for kod in stale.STANOWISKA:
        if kod in STANOWISKA_BEZ_STOLU:
            continue
        w_bazie = tryb(kod) == 'stol'
        if w_bazie:
            stoly_bazy.add(kod)
        klucz = stale.klucz_tryb(kod)
        if (zmiany[klucz][0] == 'stol') if klucz in zmiany else w_bazie:
            stoly_wynikowe.add(kod)
    if stoly_wynikowe and (stoly_wynikowe - stoly_bazy or prog_bazy > 0):
        return 'prog_wersji_wymagany', 'min_app_version_code', KOMUNIKAT_PROGU_WERSJI
    return None


def zapisz(zmiany, user_id):
    """
    Zapis zwalidowanych `zmiany` ({klucz: (wartość_tekst, config_type)}) w `prod_config`: UPDATE istniejącego
    wiersza albo INSERT brakującego, tylko gdy wartość się zmienia; na każdą zmianę wiersz `prod_priority_log`
    (`ustawienia`, `note` = klucz). Zwraca klucze zmienione, rosnąco. Bez blokad (wiersze konfiguracji i log bez
    zamówienia) i bez commita — commituje router, jedną transakcją dla wszystkich kluczy.
    """
    teraz = get_local_now()
    zmienione = []
    for klucz in sorted(zmiany):
        wartosc, typ = zmiany[klucz]
        wiersz = ProductionConfig.query.filter(ProductionConfig.config_key == klucz).first()
        stara = wiersz.config_value if wiersz is not None else None
        if stara == wartosc:
            continue
        if wiersz is None:
            db.session.add(ProductionConfig(config_key=klucz, config_value=wartosc, config_type=typ,
                                            updated_by=user_id))
        else:
            wiersz.config_value = wartosc
            wiersz.config_type = typ
            wiersz.updated_by = user_id
        db.session.add(PriorityLog(action='ustawienia', old_value=None if stara is None else stara[:64],
                                   new_value=wartosc[:64], note=klucz, user_id=user_id, created_at=teraz))
        zmienione.append(klucz)
    db.session.flush()
    return zmienione
