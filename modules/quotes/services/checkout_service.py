# -*- coding: utf-8 -*-
"""
Składanie zamówienia w BaseLinkerze — wspólny, zabezpieczony tor.

BaselinkerService.create_order_from_quote nie ma żadnej idempotencji. Druga
próba tworzy DRUGIE realne zamówienie i nadpisuje base_linker_order_id,
osierocając pierwsze (zamówienia w BaseLinkerze nie da się cofnąć jednym
ruchem). Przez ten moduł przechodzą OBIE ścieżki — publiczny checkout klienta
i panel handlowca — żeby na jedno zamówienie była jedna reguła. Panel miał
wcześniej własną, słabszą kopię guardu: czytał numer zamówienia bez blokady
i PRZED addOrder, więc przegrywał wyścig z checkoutem klienta i dawał dwa
realne zamówienia (sondy W3/W3b recenzji).

KOLEJNOŚĆ, KTÓRA JEST TU CAŁĄ OBRONĄ
====================================
1. SELECT ... FOR UPDATE na wierszu wyceny (zablokuj_wycene) — odczyt bieżący,
   nie ze snapshotu transakcji.
2. Guardy pod blokadą: numer zamówienia, znacznik próby, kwalifikacja.
3. ZAPIS I COMMIT ZNACZNIKA `order_attempt_started_at` — dopiero teraz.
4. Wywołanie BaseLinkera (poza blokadą).
5. Rozstrzygnięcie: znacznik zdejmujemy WYŁĄCZNIE wtedy, gdy wiemy, że
   zamówienia nie ma, albo gdy mamy jego numer.

Krok 3 kończy transakcję, więc blokada wiersza zwalnia się PRZED wywołaniem
BaseLinkera — i to jest zamierzone. Od tej chwili wzajemne wykluczanie robi
znacznik, a nie blokada: każde kolejne żądanie bierze tę samą blokadę,
czyta świeży wiersz i widzi znacznik. Zysk jest podwójny:

* znacznik jest TRWAŁY już w chwili strzału do BaseLinkera, więc przeżywa
  awarię wszystkiego, co dzieje się później (padnięty commit wyceny, padnięty
  zapis awaryjny numeru, padnięty wpis w logu, ubity worker). Poprzednia
  wersja zapisywała ślad dopiero w obsłudze wyjątku — czyli dokładnie wtedy,
  gdy niesprawna bywała właśnie baza;
* nasza WŁASNA blokada `FOR UPDATE` nie trzyma się przez całe wywołanie HTTP,
  więc żaden guard nie czeka na nią do lock wait timeoutu i nie wysycamy puli
  połączeń (pool_size=2, max_overflow=2 na workera).

CO NAPRAWDĘ DZIEJE SIĘ Z BLOKADĄ WIERSZA (zmierzone, nie wydedukowane).
Zwolnienie blokady w kroku 3 NIE znaczy, że wiersz wyceny jest wolny przez
całe wywołanie BaseLinkera. `create_order_from_quote` zaczyna od INSERT-a do
`baselinker_order_logs` (klucz obcy na `quotes.id`) i commituje dopiero po
powrocie z `addOrder`, więc InnoDB trzyma na wierszu wyceny współdzieloną
blokadę FK przez cały ten czas. Drugie żądanie, które w tym oknie bierze
`SELECT ... FOR UPDATE`, po prostu CZEKA — w sondzie W1 recenzji 3,2 s przy
`addOrder` trwającym 4 s — i dopiero potem widzi zapisany numer zamówienia
albo znacznik. Wiersz jest naprawdę wolny wyłącznie przez czas
`_prepare_order_data` (milisekundy), między commitem znacznika a tym INSERT-em.
Kto pisze do wyceny w tym oknie, ten omija całą tę mechanikę — dlatego
`odepnij_zamowienie` też wchodzi pod blokadę i odmawia, gdy próba trwa.

CENA. Drugie żądanie, które wejdzie zanim blokada FK się założy, nie czeka
i dostaje od razu PROBA_W_TOKU („przetwarzamy, nie składaj ponownie").
Dawniej doczekałoby się i zobaczyło duplikat z numerem zamówienia. Ten sam
komunikat, mniej czekania, zero ryzyka drugiego zamówienia — a klasyczne
podwójne kliknięcie (dwa żądania jedno po drugim) dalej kończy się duplikatem
z numerem.

Znacznika NIE dałoby się zapisać z osobnego połączenia przy trzymanej
blokadzie: baselinker_order_logs ma klucz obcy na quotes.id, więc INSERT
z drugiej sesji czeka na współdzieloną blokadę wiersza rodzica — czyli na
transakcję, która sama czeka na nas. Stąd znacznik na samym wierszu wyceny.
"""
from datetime import datetime

from flask import current_app

from extensions import db
from modules.baselinker.models import BaselinkerOrderLog, STATUS_PROBA_NIEPEWNA
from modules.baselinker.service import BaselinkerService
from modules.calculator.models import Quote
from modules.logging import get_structured_logger
from modules.quotes.services.checkout_config import (
    KonfliktDostawy, build_checkout_order_config,
)

__all__ = ['STATUS_PROBA_NIEPEWNA', 'PROBA_W_TOKU', 'PROBA_NIEPEWNA',
           'PROG_PROBY_W_TOKU_S', 'ODMOWA_ODPIECIA_PROBA_W_TOKU',
           'zablokuj_wycene', 'stan_proby',
           'istnieje_nierozstrzygnieta_proba', 'wisi_nierozstrzygnieta_proba',
           'zloz_zamowienie', 'zloz_zamowienie_klienta', 'odepnij_zamowienie']

logger = get_structured_logger('quotes.checkout')

# Stany znacznika próby. Blokują tak samo — różnią się tym, co mówimy człowiekowi.
PROBA_W_TOKU = 'w_toku'
PROBA_NIEPEWNA = 'niepewna'

# Komunikat odmowy odpięcia w trakcie trwającej próby. Stała, a nie luźny
# napis: router panelu rozpoznaje po niej ten jeden przypadek i oddaje 409
# („spróbuj za chwilę") zamiast 500 („coś się zepsuło") — bo nic się nie
# zepsuło, po prostu sprawa jeszcze się nie rozstrzygnęła.
ODMOWA_ODPIECIA_PROBA_W_TOKU = (
    'Trwa właśnie próba złożenia zamówienia dla tej wyceny. Odpięcie teraz '
    'mogłoby doprowadzić do DRUGIEGO zamówienia w BaseLinkerze. Odśwież panel '
    'za chwilę — gdy próba się zakończy, odpięcie znów będzie możliwe.')

# Do ilu sekund od startu próba jest jeszcze „w toku". Jedno wywołanie
# create_order_from_quote to addOrder (timeout 30 s) plus getOrders z jednym
# ponowieniem (2 x 30 s), więc uczciwa górna granica to około 90 s; 120 s daje
# zapas na powolną bazę. Powyżej tego progu żądanie na pewno już nie żyje,
# a jego losu i tak nie znamy — czyli „nie wiemy", nie „przetwarzamy".
PROG_PROBY_W_TOKU_S = 120


def istnieje_nierozstrzygnieta_proba(quote_id):
    """Czy w logu BaseLinkera wisi wpis o próbie, której losu nie znamy.

    Zgodność wstecz i druga linia obrony: zanim pojawił się znacznik na
    wycenie, ten wpis był JEDYNYM trwałym śladem — i nadal blokuje. Sam
    w sobie nie wystarcza, bo powstaje w obsłudze wyjątku (a więc bywa, że
    nie powstaje wcale) i bo w MySQL-owym REPEATABLE READ czyta ze snapshotu
    transakcji, a nie stanu bieżącego. Rozstrzyga znacznik na wierszu wyceny,
    czytany pod blokadą; ten wpis może blokadę tylko DOŁOŻYĆ, nigdy zdjąć.
    """
    return db.session.query(BaselinkerOrderLog.id).filter_by(
        quote_id=quote_id,
        action='create_order',
        status=STATUS_PROBA_NIEPEWNA,
    ).first() is not None


def stan_proby(quote):
    """PROBA_W_TOKU / PROBA_NIEPEWNA / None dla podanej (świeżo wczytanej) wyceny.

    Wiek znacznika rozstrzyga wyłącznie o TREŚCI komunikatu — każdy stan
    niepusty blokuje kolejną próbę tak samo.

    Kolejność sprawdzeń niesie znaczenie. Wpis `uncertain` w logu znaczy
    „próba SIĘ SKOŃCZYŁA i skończyła się nierozstrzygnięciem" — jest więc
    mocniejszy od samego znacznika, który mówi tylko „próba wystartowała".
    Znacznik bez takiego wpisu czytamy przez wiek: świeży = ktoś wciąż wisi
    na BaseLinkerze, stary = żądanie już nie żyje, a jego losu nie znamy.
    """
    if istnieje_nierozstrzygnieta_proba(quote.id):
        return PROBA_NIEPEWNA
    znacznik = getattr(quote, 'order_attempt_started_at', None)
    if znacznik is not None:
        wiek = (datetime.utcnow() - znacznik).total_seconds()
        return PROBA_W_TOKU if wiek < PROG_PROBY_W_TOKU_S else PROBA_NIEPEWNA
    return None


def wisi_nierozstrzygnieta_proba(quote):
    """Czy na wycenie wisi próba, po której nie wolno pokazać przycisku „Zamów".

    KIERUNEK NA PRZYSZŁOŚĆ (świadomie poza zakresem tej rundy). Dziś stan
    „nie wiemy" zamyka klientowi drogę, dopóki człowiek nie sprawdzi
    w BaseLinkerze, czy zamówienie powstało. Tę samą robotę da się wykonać
    automatycznie: numer wyceny jedzie do BaseLinkera w custom_extra_fields,
    więc `getOrders` filtrowane po źródle „Dębuś VPS" i dacie pozwala
    sprawdzić, czy zamówienie z tym numerem wyceny istnieje — i albo dopisać
    jego numer na wycenie, albo zdjąć znacznik. Kolejna próba mogłaby wtedy
    NAJPIERW zapytać, zamiast odmawiać na ślepo. Wymaga to własnego zadania:
    ustalenia okna czasowego, zachowania przy wielu trafieniach i limitów API.
    """
    return stan_proby(quote) is not None


def zablokuj_wycene(quote):
    """Blokuje wiersz wyceny do końca transakcji i zwraca ŚWIEŻY stan.

    Wzorzec blokady jak w modules/calculator/services/quote_service.py:481,
    ale z populate_existing(). Bez niego blokada byłaby dekoracją: SQLAlchemy
    zwraca dla wczytanego już wiersza ten sam obiekt z identity map i NIE
    nadpisuje jego atrybutów danymi z nowego SELECT-a. Drugie żądanie
    doczekałoby swojej kolei na blokadzie, po czym przeczytałoby własną,
    nieaktualną kopię wiersza (base_linker_order_id = NULL, znacznik = NULL)
    i złożyło drugie zamówienie — czyli dokładnie to, przed czym blokada
    miała chronić.

    SELECT ... FOR UPDATE to w InnoDB odczyt BIEŻĄCY, a nie ze snapshotu
    transakcji — i tylko dlatego guard widzi znacznik zapisany przed chwilą
    przez równoległe żądanie. Zwykły SELECT w REPEATABLE READ pokazałby stan
    sprzed pierwszego odczytu w tej transakcji (a router czytał już wycenę
    po tokenie), czyli świeżego znacznika by NIE zobaczył.

    Zwraca None, gdy wiersz zniknął (wycena usunięta w międzyczasie).
    """
    return (Quote.query
            .populate_existing()
            .filter_by(id=quote.id)
            .with_for_update()
            .first())


def _numer_zamowienia(wartosc):
    """base_linker_order_id -> int, a gdy w kolumnie tekstowej siedzi coś innego,
    oddajemy wartość bez zmian. Powtórka nie ma prawa wywalić się wyjątkiem —
    zamówienie już istnieje i klient ma je zobaczyć."""
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return wartosc


def _odpowiedz(ok, order_id=None, order_page_url=None, duplikat=False, error=None,
               niepewne=False, zamowienie_utworzone=False, w_toku=False):
    """Cztery różne prawdy o nieudanej próbie — mylenie ich kosztuje pieniądze.

    `niepewne` = nie wiemy, czy zamówienie w BaseLinkerze powstało. Ustawia je
    ścieżka błędu transportowego (patrz create_order_from_quote). Przy takim
    wyniku nie wolno ani twierdzić, że zamówienie jest, ani że go nie ma, ani
    zapraszać klienta do ponowienia.

    `zamowienie_utworzone` = zamówienie NA PEWNO istnieje (addOrder potwierdził),
    a nie udało się zapisać jego numeru na wycenie. Wiedza mocniejsza niż
    `niepewne`: klientowi mówimy wprost, że zamówienie zostało złożone.

    `w_toku` = inne żądanie właśnie składa to zamówienie. Też odbiera prawo do
    powtórki, ale nie jest awarią: wynik pojawi się na stronie sam.

    Wszystkie trzy na False = zamówienia NA PEWNO nie ma i powtórka jest
    bezpieczna.
    """
    return {
        "ok": ok,
        "order_id": order_id,
        "order_page_url": order_page_url,
        "duplikat": duplikat,
        "error": error,
        "niepewne": niepewne,
        "zamowienie_utworzone": zamowienie_utworzone,
        "w_toku": w_toku,
    }


def _zaznacz_probe(quote):
    """Zapisuje i COMMITUJE znacznik próby. Wyjątek leci do wywołującego.

    Commit jest tu istotą rzeczy, a nie szczegółem: dopiero on czyni znacznik
    trwałym i dopiero on zwalnia blokadę wiersza. Gdyby padł, do BaseLinkera
    NIE WOLNO strzelać — bo nie mielibyśmy czym zablokować drugiej próby.
    """
    quote.order_attempt_started_at = datetime.utcnow()
    db.session.commit()


def _zdejmij_znacznik(quote):
    """Zdejmuje znacznik, gdy wiemy, że zamówienia nie ma. Best-effort.

    Gdy ten zapis padnie, znacznik zostaje i klient nie zamówi do czasu
    interwencji człowieka. To zła strona po bezpiecznej stronie: jeśli baza
    nie przyjmuje zapisów, kolejna próba i tak nie ma jak się udać.
    """
    try:
        quote.order_attempt_started_at = None
        db.session.commit()
        return True
    except Exception as blad:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("Nie udało się zdjąć znacznika próby zamówienia",
                     quote_id=getattr(quote, 'id', None), error=str(blad))
        return False


def _dane_do_alarmu(quote):
    """(numer wyceny, mail opiekuna) — odczyt osłonięty, bo sesja bywa zerwana."""
    numer, opiekun = None, None
    try:
        numer = quote.quote_number
        opiekun = getattr(getattr(quote, 'user', None), 'email', None)
    except Exception:
        pass
    return numer, opiekun


def _zglos_zablokowana_wycene(quote, wynik):
    """Alarm, gdy PEWNA odmowa BaseLinkera zostawiła na wycenie znacznik.

    Sytuacja jest gorsza, niż wygląda z odpowiedzi, którą dostaje klient.
    BaseLinker odmówił, więc zamówienia NA PEWNO nie ma i klient słyszy prawdę
    („spróbuj ponownie za kilka minut") — ale zdjęcie znacznika padło, więc
    każda kolejna próba to `409 przetwarzane`, a po PROG_PROBY_W_TOKU_S
    „nie wiemy". Zwykła, odwracalna odmowa zamienia się w wycenę zablokowaną
    na głucho. Alarm o nierozstrzygniętej próbie tej ścieżki NIE obejmuje
    (nic tu nie jest nierozstrzygnięte), a sam wpis w logu czyta wyłącznie kod
    — więc bez tego maila nikt by się o blokadzie nie dowiedział.
    """
    numer, opiekun = _dane_do_alarmu(quote)

    logger.error(
        "Wycena została ZABLOKOWANA zawieszonym znacznikiem próby — "
        "BaseLinker odmówił (zamówienia nie ma), a znacznika nie udało się "
        "zdjąć; wymaga odpięcia zamówienia w panelu",
        quote_id=getattr(quote, 'id', None),
        quote_number=numer,
        blad=str(wynik.get('error'))[:500],
        opiekun=opiekun)

    _wyslij_alert_do_czlowieka(numer, opiekun, wynik, znacznik_zawieszony=True)


def _zglos_nierozstrzygnieta_probe(quote, wynik):
    """Ślad widoczny dla CZŁOWIEKA po próbie, której losu nie znamy.

    Bez tego „człowiek zamknie sprawę" znaczyło „klient zadzwoni": wpis
    w baselinker_order_logs czyta wyłącznie kod, endpoint /order-logs nie jest
    wołany przez żaden front-end, a klient czyta „skontaktuj się z nami".

    Dwie drogi, obie best-effort i obie odporne na zerwaną sesję bazy:
    log na poziomie ERROR (zawsze) oraz mail do opiekuna wyceny (gdy poczta
    jest skonfigurowana — w testach nie jest, więc nic nie wychodzi).
    """
    numer, opiekun = _dane_do_alarmu(quote)

    _dopisz_wpis_o_nierozstrzygnietej_probie(quote, wynik)

    logger.error(
        "NIEROZSTRZYGNIĘTA próba zamówienia — wymaga ręcznego sprawdzenia "
        "w BaseLinkerze",
        quote_id=getattr(quote, 'id', None),
        quote_number=numer,
        baselinker_order_id=wynik.get('order_id'),
        zamowienie_utworzone=bool(wynik.get('zamowienie_utworzone')),
        niepewne=bool(wynik.get('niepewne')),
        blad=str(wynik.get('error'))[:500],
        opiekun=opiekun)

    _wyslij_alert_do_czlowieka(numer, opiekun, wynik)


def _dopisz_wpis_o_nierozstrzygnietej_probie(quote, wynik):
    """Druga próba dopisania wpisu `uncertain` do logu. Nigdy nie rzuca.

    Serwis robi to sam w obsłudze wyjątku, ale właśnie tam sesja bazy bywa
    zerwana i wpis przepada (sonda D3b recenzji). Ponawiamy z czystej sesji,
    bo ten wpis niesie wiedzę, której sam znacznik na wycenie nie ma: że
    próba SIĘ SKOŃCZYŁA. Bez niego klient przez dwie minuty czytałby
    „przetwarzamy", zamiast od razu „nie wiemy, skontaktuj się z nami".

    Gdy i to padnie, nic złego się nie dzieje: znacznik na wycenie blokuje
    dalej, a po PROG_PROBY_W_TOKU_S sam zaczyna znaczyć „nie wiemy".
    """
    try:
        if istnieje_nierozstrzygnieta_proba(quote.id):
            return
        numer = wynik.get('order_id')
        db.session.add(BaselinkerOrderLog(
            quote_id=quote.id,
            action='create_order',
            status=STATUS_PROBA_NIEPEWNA,
            # Kolumna jest liczbowa — cokolwiek innego wpuszczone tu wprost
            # wywaliłoby zapis, który ma być ostatnią deską ratunku.
            baselinker_order_id=numer if isinstance(numer, int) else None,
            error_message=str(wynik.get('error'))[:1000]))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _wyslij_alert_do_czlowieka(numer_wyceny, email_opiekuna, wynik,
                               znacznik_zawieszony=False):
    """Mail alarmowy o zablokowanej wycenie. Nigdy nie rzuca.

    znacznik_zawieszony=True — wiemy WIĘCEJ, nie mniej: BaseLinker odmówił,
    zamówienia na pewno nie ma, a wycena została zablokowana wyłącznie przez
    znacznik, którego nie udało się zdjąć. Ten sam mail, inna treść: nie ma
    czego sprawdzać w BaseLinkerze, wystarczy odpiąć zamówienie.
    """
    try:
        nadawca = current_app.config.get('MAIL_USERNAME')
        if not nadawca:
            return  # poczta nieskonfigurowana (np. testy) — zostaje log ERROR
        odbiorcy = [adres for adres in (email_opiekuna, 'biuro@woodpower.pl')
                    if adres]
        if not odbiorcy:
            return

        from flask_mail import Message

        from extensions import mail

        if znacznik_zawieszony:
            tresc = (
                "Wycena {numer} została ZABLOKOWANA po nieudanej próbie "
                "zamówienia.\n\n"
                "BaseLinker odmówił, więc zamówienia NA PEWNO nie ma — ale nie "
                "udało się zdjąć z wyceny znacznika trwającej próby (awaria "
                'bazy w tym samym momencie). Klient usłyszał „spróbuj ponownie '
                'za kilka minut", a każda kolejna próba odbije się o ten '
                'znacznik: najpierw jako „zamówienie jest przetwarzane", potem '
                'jako „nie wiemy, czy powstało".\n\n'
                'Co zrobić: odblokuj wycenę akcją „Odepnij zamówienie" '
                "w panelu (uprawnienie administratora). W BaseLinkerze nie ma "
                "czego szukać — zamówienie nie powstało.\n\n"
                "Szczegóły techniczne: {blad}\n"
            ).format(numer=numer_wyceny or '-',
                     blad=str(wynik.get('error'))[:500])

            mail.send(Message(
                subject="⚠️ Wycena zablokowana po nieudanym zamówieniu — {}".format(
                    numer_wyceny or '-'),
                sender=nadawca,
                recipients=odbiorcy,
                body=tresc))
            return

        if wynik.get('zamowienie_utworzone'):
            czego_nie_wiemy = (
                "Zamówienie ZOSTAŁO utworzone w BaseLinkerze (nr {nr}), ale nie "
                "udało się zapisać jego numeru na wycenie."
            ).format(nr=wynik.get('order_id'))
        else:
            czego_nie_wiemy = (
                "Nie wiemy, czy zamówienie powstało po stronie BaseLinkera — "
                "łączność padła w trakcie żądania."
            )

        tresc = (
            "Próba złożenia zamówienia dla wyceny {numer} nie została "
            "rozstrzygnięta.\n\n"
            "{co}\n\n"
            'Klient widzi komunikat „nie składaj zamówienia ponownie" i nie '
            "może zamówić tej wyceny, dopóki ktoś nie zamknie sprawy.\n\n"
            "Co zrobić: sprawdź w BaseLinkerze, czy zamówienie dla tej wyceny "
            "istnieje.\n"
            "— jeśli TAK: dopisz jego numer na wycenie;\n"
            '— jeśli NIE: odblokuj wycenę akcją „Odepnij zamówienie" w panelu '
            "(uprawnienie administratora), a klient złoży zamówienie sam.\n\n"
            "Szczegóły techniczne: {blad}\n"
        ).format(numer=numer_wyceny or '-', co=czego_nie_wiemy,
                 blad=str(wynik.get('error'))[:500])

        mail.send(Message(
            subject="⚠️ Nierozstrzygnięta próba zamówienia — wycena {}".format(
                numer_wyceny or '-'),
            sender=nadawca,
            recipients=odbiorcy,
            body=tresc))
    except Exception as blad:
        logger.error("Nie udało się wysłać alertu o zablokowanej wycenie",
                     quote_number=numer_wyceny, error=str(blad))


def zloz_zamowienie(quote, user_id, buduj_config, sprawdz_kwalifikacje=True):
    """Wspólny tor obu ścieżek: blokada, guardy, znacznik, BaseLinker, rozstrzygnięcie.

    quote                — obiekt Quote (używany tylko po id; stan czytamy z bazy)
    user_id              — kto składa (created_by w logu BaseLinkera; może być None)
    buduj_config         — funkcja (zablokowana_wycena) -> dict konfiguracji
                           zamówienia. Wołana POD blokadą, na świeżym stanie;
                           może rzucić KonfliktDostawy.
    sprawdz_kwalifikacje — True dla checkoutu klienta (wymaga statusu
                           „Zaakceptowane"). Panel handlowca składa zamówienia
                           także z wycen w innych statusach i tego warunku
                           nie miał — dokładanie go tutaj zablokowałoby
                           normalną pracę panelu.

    Nie rzuca wyjątków. Zwraca słownik z _odpowiedz().
    """
    try:
        zablokowana = zablokuj_wycene(quote)
        if zablokowana is None:
            # Wiersz zniknął spod blokady — nie ma czego zamawiać i nie ma na
            # czym oprzeć guardu, więc odmawiamy zamiast strzelać do BaseLinkera.
            return _odpowiedz(False, error="NIEKWALIFIKOWANA")

        # Sprawdzenia POD blokadą, na stanie wczytanym świeżo z bazy.
        if zablokowana.base_linker_order_id:
            return _odpowiedz(
                True,
                order_id=_numer_zamowienia(zablokowana.base_linker_order_id),
                order_page_url=zablokowana.baselinker_order_page,
                duplikat=True,
            )

        stan = stan_proby(zablokowana)
        if stan == PROBA_W_TOKU:
            # Inne żądanie jest właśnie w BaseLinkerze. Nie wiemy jeszcze,
            # jak skończy, ale wiemy, że drugi strzał to drugie zamówienie.
            return _odpowiedz(False, error="PROBA_W_TOKU", w_toku=True)
        if stan == PROBA_NIEPEWNA:
            # Po nierozstrzygniętej próbie NIE wolno strzelać drugi raz:
            # tamto zamówienie mogło powstać, a my nie mamy jak tego sprawdzić.
            return _odpowiedz(False, error="NIEPEWNA_PROBA", niepewne=True)

        if sprawdz_kwalifikacje and not zablokowana.is_eligible_for_order():
            return _odpowiedz(False, error="NIEKWALIFIKOWANA")

        # Konfiguracja PRZED znacznikiem: odmowa nie ma zostawiać śladu, który
        # trzeba potem sprzątać.
        config = buduj_config(zablokowana)

        # Punkt, od którego kolejna próba jest odbijana. Musi być trwały ZANIM
        # cokolwiek poleci do BaseLinkera — patrz docstring modułu.
        _zaznacz_probe(zablokowana)
    except KonfliktDostawy as konflikt:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("Konflikt sposobu dostawy — zamówienia nie składamy",
                       quote_id=getattr(quote, 'id', None), powod=str(konflikt))
        return _odpowiedz(False, error="KONFLIKT_DOSTAWY")
    except Exception as blad:
        # Wszystko powyżej dzieje się PRZED wywołaniem BaseLinkera, więc
        # zamówienia NA PEWNO nie ma i wolno powiedzieć „spróbuj za chwilę".
        # Bez tego lock wait timeout wychodził z endpointu jako 500 bez JSON-a,
        # a klient czytał „nie wiemy, czy zamówienie zostało złożone" — komunikat
        # fałszywy i najbardziej niepokojący w całej ścieżce (sonda W2 recenzji).
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("Błąd bazy przed wywołaniem BaseLinkera — zamówienie "
                     "NIE zostało złożone",
                     quote_id=getattr(quote, 'id', None), error=str(blad),
                     error_type=type(blad).__name__)
        return _odpowiedz(False, error="BLAD_BAZY")

    wynik = BaselinkerService().create_order_from_quote(zablokowana, user_id, config)

    if not wynik.get("success"):
        utworzone = bool(wynik.get("zamowienie_utworzone"))
        niepewne = bool(wynik.get("niepewne"))
        if not utworzone:
            # base_linker_order_id nie został zapisany — zostawiamy sesję czystą.
            # Gdy zamówienie JEDNAK powstało, serwis zdążył już zrobić własny
            # rollback i zapis ratunkowy: kolejny rollback tutaj mógłby wywalić
            # ten zapis, a to on broni przed drugim realnym zamówieniem.
            try:
                db.session.rollback()
            except Exception:
                pass

        if utworzone or niepewne:
            # Znacznika NIE ZDEJMUJEMY. To jedyny stan, w którym kolejna próba
            # mogłaby utworzyć drugie realne zamówienie — i jedyny, o którym
            # musi się dowiedzieć człowiek.
            _zglos_nierozstrzygnieta_probe(zablokowana, wynik)
        else:
            # BaseLinker odpowiedział i odmówił albo żądanie w ogóle nie wyszło:
            # zamówienia NA PEWNO nie ma, więc powtórka musi być możliwa.
            # Gdy zdjęcie znacznika padnie, powtórka możliwa NIE JEST i wycena
            # zostaje zablokowana — o czym musi się dowiedzieć człowiek.
            if not _zdejmij_znacznik(zablokowana):
                _zglos_zablokowana_wycene(zablokowana, wynik)

        return _odpowiedz(False, error=wynik.get("error") or "BLAD_BASELINKER",
                          order_id=wynik.get("order_id"),
                          niepewne=niepewne,
                          zamowienie_utworzone=utworzone)

    # Sukces: znacznik zdjął serwis w tym samym commicie, w którym zapisał numer
    # zamówienia. Gdyby jednak został (np. atrapa, stara ścieżka), sprzątamy —
    # zostawiony znacznik nikogo nie blokuje, bo guard duplikatu rozstrzyga
    # wcześniej, ale zaśmiecałby widok.
    if getattr(zablokowana, 'order_attempt_started_at', None) is not None:
        _zdejmij_znacznik(zablokowana)

    # Odczyt linku osłonięty, bo to JEDYNE miejsce po sukcesie, które jeszcze
    # sięga do bazy. Wyjątek stąd wyleciałby z całej funkcji i wywołujący
    # dostałby 500 zamiast potwierdzenia zamówienia, które NA PEWNO powstało —
    # a przeglądarka zamieniłaby to na „nie wiemy". Brak linku kosztuje jedno
    # zdanie („szczegóły prześlemy w osobnej wiadomości"), nie pieniądze.
    try:
        link = zablokowana.baselinker_order_page
    except Exception as blad:
        logger.error("Nie udało się odczytać linku do strony zamówienia",
                     quote_id=getattr(quote, 'id', None), error=str(blad))
        link = None

    return _odpowiedz(True, order_id=wynik.get("order_id"), order_page_url=link)


def zloz_zamowienie_klienta(quote, order_source_id, bot_user_id,
                            is_self_pickup=False,
                            dane_dostawy_z_formularza=None):
    """Checkout publiczny: klient składa zamówienie ze strony wyceny.

    is_self_pickup — wybór klienta z bieżącego formularza. Musi tu dojechać,
    bo dla wyceny zaakceptowanej wcześniej nie ma go już skąd odczytać: dane
    dostawy zapisuje wyłącznie akceptacja, a ta się wtedy nie wykonuje.
    Rozstrzygnięcie konfliktu z danymi zapisanymi na kliencie siedzi
    w build_checkout_order_config.

    dane_dostawy_z_formularza — pola adresu z tego samego formularza. Też nie
    ma innej drogi: dla wyceny zaakceptowanej wcześniej nikt ich nie zapisuje,
    a bez nich wycena kurierska klienta ze starym znacznikiem odbioru kończy
    się odmową (patrz checkout_config.rozstrzygnij_odbior_osobisty).

    Zwraca słownik z _odpowiedz(). Nie rzuca wyjątków.
    """
    def buduj(zablokowana):
        return build_checkout_order_config(
            zablokowana, order_source_id, is_self_pickup=is_self_pickup,
            dane_dostawy_z_formularza=dane_dostawy_z_formularza)

    return zloz_zamowienie(quote, bot_user_id, buduj, sprawdz_kwalifikacje=True)


def odepnij_zamowienie(quote, powod_uzytkownik_id=None):
    """Odpina zamówienie od wyceny i zdejmuje znacznik próby.

    Droga wyjścia dla UPRAWNIONEGO CZŁOWIEKA (nie dla klienta) z dwóch stanów,
    z których dotąd nie było wyjścia inaczej niż ręcznym UPDATE w bazie:

    * zamówienie anulowane w BaseLinkerze albo złożone pomyłkowo — wycena
      zostawała zamknięta na zawsze, bo w całym modules/ nic nie kasowało
      base_linker_order_id;
    * nierozstrzygnięta próba, po której człowiek sprawdził w BaseLinkerze,
      że zamówienia NIE MA — bez tego klient nie mógł zamówić już nigdy.

    Zwraca (True, None) albo (False, komunikat). Wpis w logu jest świadomie
    zapisywany z action='detach_order': guard nierozstrzygniętej próby patrzy
    wyłącznie na 'create_order', więc ten ślad niczego nie blokuje.

    ODMOWA W TRAKCIE TRWAJĄCEJ PRÓBY. Odpięcie było jedynym miejscem w kodzie,
    które pisało znacznik POZA blokadą wiersza i bez spojrzenia, czy próba
    trwa. Trafione w okno tuż po zapisie znacznika (a przed założeniem blokady
    FK przez wywołanie BaseLinkera) kasowało jedyną rzecz, która blokowała
    drugie żądanie — i powstawały DWA REALNE zamówienia, z których wycena
    znała tylko drugie (sonda B recenzji). Dlatego czytamy stan pod tą samą
    blokadą co reszta i odmawiamy, dopóki próba jest świeża. Po
    PROG_PROBY_W_TOKU_S — i po każdej próbie zakończonej nierozstrzygnięciem —
    odpięcie działa jak dotąd, bo po to właśnie istnieje.
    """
    zablokowana = zablokuj_wycene(quote)
    if zablokowana is None:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False, 'Nie znaleziono wyceny do odpięcia.'

    if stan_proby(zablokowana) == PROBA_W_TOKU:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("Odmowa odpięcia — próba zamówienia właśnie trwa",
                       quote_id=getattr(quote, 'id', None),
                       user_id=powod_uzytkownik_id)
        return False, ODMOWA_ODPIECIA_PROBA_W_TOKU

    quote = zablokowana
    poprzedni_numer = quote.base_linker_order_id
    try:
        quote.base_linker_order_id = None
        quote.baselinker_order_page = None
        quote.order_attempt_started_at = None
        db.session.add(BaselinkerOrderLog(
            quote_id=quote.id,
            action='detach_order',
            status='success',
            baselinker_order_id=_numer_zamowienia(poprzedni_numer)
            if str(poprzedni_numer or '').isdigit() else None,
            error_message='Odpięto zamówienie {} od wyceny'.format(
                poprzedni_numer or '(brak numeru)'),
            created_by=powod_uzytkownik_id))
        db.session.commit()
    except Exception as blad:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("Nie udało się odpiąć zamówienia od wyceny",
                     quote_id=getattr(quote, 'id', None), error=str(blad))
        return False, 'Nie udało się odpiąć zamówienia: {}'.format(blad)

    # Wpisy `uncertain` z poprzednich prób też muszą przestać blokować —
    # inaczej odpięcie numeru zamówienia nie odblokowałoby wyceny.
    try:
        (BaselinkerOrderLog.query
         .filter_by(quote_id=quote.id, action='create_order',
                    status=STATUS_PROBA_NIEPEWNA)
         .update({'status': 'error'}, synchronize_session=False))
        db.session.commit()
    except Exception as blad:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("Odpięto zamówienie, ale nie udało się zamknąć wpisów "
                     "o nierozstrzygniętych próbach",
                     quote_id=getattr(quote, 'id', None), error=str(blad))

    logger.warning("Odpięto zamówienie od wyceny",
                   quote_id=getattr(quote, 'id', None),
                   poprzedni_numer=poprzedni_numer,
                   user_id=powod_uzytkownik_id)
    return True, None
