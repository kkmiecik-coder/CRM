"""Pętla usługi agenta druku v2: konfiguracja lokalna + dziennik + klient CRM + transport drukarek.

Wątki: kanał push (push.Kanal) tylko ustawia zdarzenie; cykl biegnie w jednym wątku roboczym
(`petla()`); `stan_dla_okienka()` czytają inne wątki, więc wspólny stan chroni blokada.
"""
import logging
import threading
import time
from datetime import datetime

from agent_druku import WERSJA, drukarki as drukarki_mod, dziennik, konfiguracja, push
from agent_druku.crm import BladCrm, NieznanyAgent

log = logging.getLogger('agent_druku.petla')

KOLEJNOSC_DRUKAREK = ('etykiety', 'wysylka')
STANY_BEZ_POBIERANIA = ('brak_papieru', 'otwarta_klapa', 'pauza', 'blad')
LIMIT_PORCJI = 10
MAKS_PORCJI = 20
POLLING_Z_PUSHEM_S = 60
POLLING_BEZ_PUSHU_S = 10
KONTAKT_POZA_GODZINAMI_S = 60
CISZA_CRM_S = 120   # jak drukarki.stale.AGENT_CISZA_S po stronie serwera
# Cykl „po (ponownym) połączeniu push” najwyżej raz na tyle sekund — kanał, który łączy się i zrywa,
# nie może zasypywać CRM pełnymi cyklami.
CYKL_PO_POLACZENIU_CO_S = 10

BLAD_PRZERWANEJ_WYSYLKI = 'agent przerwał wysyłanie — sprawdź, czy etykieta wyszła'
AGENT_NIEAKTYWNY = 'agent nie jest aktywny w CRM'
# Komunikat okienka dla drukarki, którą /zadania/pobierz zgłasza jako „nie twoja teraz”.
KOMUNIKATY_OBSLUGI = {
    'stary': 'Drukarkę obsługuje stary agent',
    'przelaczanie': 'Przełączanie na nowego agenta — chwila',
}
OBSLUGA_INNA = 'Drukarka obsługiwana gdzie indziej'


class Zegar:
    """Zegar produkcyjny; w testach podmieniany (teraz, monotonic, czekaj)."""

    def teraz(self):
        return datetime.now()  # czas lokalny huba — tylko do godzin pracy

    def monotonic(self):
        return time.monotonic()

    def czekaj(self, zdarzenie, sekundy):
        return zdarzenie.wait(sekundy)


def _okno_dzis(godziny, teraz):
    """(od, do) okna pracy na dziś albo None (niedziela albo brak wpisu)."""
    if not isinstance(godziny, dict):
        return None
    dzien = teraz.weekday()
    para = godziny.get('pn_pt') if dzien <= 4 else godziny.get('sobota') if dzien == 5 else None
    if not isinstance(para, (list, tuple)) or len(para) != 2:
        return None
    return tuple(para)


def _w_godzinach(godziny, teraz):
    """Okno pracy z konfiguracji: pn–pt `pn_pt`, sobota `sobota`, niedziela wolna.
    Bez godzin w konfiguracji (jeszcze nie pobrana) pracujemy — inaczej agent nigdy by jej nie pobrał."""
    if not isinstance(godziny, dict) or not godziny:
        return True
    para = _okno_dzis(godziny, teraz)
    return para is not None and para[0] <= teraz.strftime('%H:%M') <= para[1]


def komunikat_poza_godzinami(okno):
    """Tekst okienka poza godzinami pracy; `okno` = (od, do) na dziś albo None."""
    opis = '%s–%s' % okno if okno else 'dziś bez pracy'
    return 'Poza godzinami pracy (%s) — etykiety czekają w kolejce' % opis


class Agent:
    def __init__(self, sciezki, klient, zegar=None, drukarki=drukarki_mod):
        self.lokalna = konfiguracja.Lokalna(sciezki.plik_konfiguracji())
        self.dziennik = dziennik.Dziennik(sciezki.plik_dziennika())
        self.klient = klient
        self.zegar = zegar or Zegar()
        self.drukarki = drukarki
        self._blokada = threading.Lock()
        self._obudz = threading.Event()
        self._stop = threading.Event()
        self._powod = None
        self._start = self.zegar.monotonic()
        self._ostatni_kontakt = None       # monotonic ostatniego udanego /kontakt
        self._ostatnia_proba_kontaktu = None
        self._push = False
        self._cykl_po_polaczeniu = None    # monotonic ostatniego cyklu „push-polaczony”
        self._nieznany = False             # 401 z CRM
        self._stany = {}                   # nazwa -> {nazwa, stan, opis, obsluga, komunikat}
        self._aktualizacja = None
        self._blad_konfiguracji = None     # lista komunikatów albo None
        self._blad_konfiguracji_rodzaj = None
        self._komunikat = ''
        self._porcja_odrzucona = False     # któraś drukarka nie przyjęła porcji w ostatnim cyklu
        self._poza_godzinami = False
        self._okno_pracy = None            # (od, do) na dziś, do komunikatu poza godzinami
        self._opisy_bledow = {}            # job_id -> opis błędu dla wyniku „blad”
        self._bledy_cyklu = []             # komunikaty błędów bieżącego cyklu (publikowane na końcu)
        # Wysyłka przerwana awarią procesu: nie wiadomo, czy etykieta wyszła. Wyniku do CRM nie
        # wysyłamy (dzierżawa serwera kończy się stanem „unknown”), a zadania nie wysyłamy drugi raz.
        self.dziennik.oznacz_przerwane()
        self._kanal = None                 # push.Kanal po uruchom() / sparuj()
        self._uruchomiony = False          # uruchom() wołane — parowanie startuje wtedy kanał push

    # --- push i wątek roboczy -------------------------------------------
    def _zbudz(self, powod):
        with self._blokada:
            if self._powod is None:
                self._powod = powod
            self._obudz.set()

    def ustaw_push(self, polaczony):
        with self._blokada:
            self._push = bool(polaczony)

    def przy_polaczeniu_push(self):
        # Kanał nie ma historii: po (ponownym) połączeniu od razu cykl nadrabia zgubione sygnały — najwyżej
        # raz na CYKL_PO_POLACZENIU_CO_S (częstsze połączenia i tak niosą najwyżej sekundy zaległości).
        self.ustaw_push(True)
        teraz = self.zegar.monotonic()
        with self._blokada:
            ostatni = self._cykl_po_polaczeniu
            if ostatni is not None and teraz - ostatni < CYKL_PO_POLACZENIU_CO_S:
                return
            self._cykl_po_polaczeniu = teraz
        self._zbudz('push-polaczony')

    def przy_rozlaczeniu_push(self):
        self.ustaw_push(False)

    def przy_sygnale_push(self, rodzaj):
        self._zbudz('push-%s' % (rodzaj or 'sygnal'))

    def odstep_pollingu(self):
        with self._blokada:
            if self._poza_godzinami:
                return KONTAKT_POZA_GODZINAMI_S
            if self._porcja_odrzucona or not self._push:
                return POLLING_BEZ_PUSHU_S
            return POLLING_Z_PUSHEM_S

    def krok(self):
        """Czeka na sygnał albo odstęp pollingu, potem jeden cykl."""
        self.zegar.czekaj(self._obudz, self.odstep_pollingu())
        if self._stop.is_set():  # zatrzymaj() budzi czekanie — bez dodatkowego cyklu
            return
        with self._blokada:
            self._obudz.clear()
            powod, self._powod = self._powod or 'polling', None
        self.cykl(powod)

    def petla(self):
        """Wątek roboczy: cykl od razu po starcie, potem krok za krokiem do zatrzymania."""
        self._bezpieczny_cykl('start')
        while not self._stop.is_set():
            try:
                self.krok()
            except Exception:
                log.exception('Nieoczekiwany błąd cyklu agenta druku')

    def _bezpieczny_cykl(self, powod):
        try:
            self.cykl(powod)
        except Exception:
            log.exception('Nieoczekiwany błąd cyklu agenta druku')

    def obudz(self, powod):
        """Natychmiastowy cykl w wątku roboczym (okienko: „Ponów zaległe”, parowanie, zmiana konfiguracji)."""
        self._zbudz(powod)

    def _uruchom_kanal(self):
        with self._blokada:
            stary, self._kanal = self._kanal, None
            klient = self.klient
        if stary is not None:
            stary.zatrzymaj()
        if klient is None or self._stop.is_set():
            return
        kanal = push.Kanal(klient, self.przy_polaczeniu_push, self.przy_sygnale_push,
                           self.przy_rozlaczeniu_push, adres_crm=self.lokalna.crm_url)
        with self._blokada:
            self._kanal = kanal
        kanal.uruchom()

    def uruchom(self):
        """Startuje kanał push i wątek roboczy (oba jako wątki tła). Zwraca wątek roboczy."""
        self._uruchomiony = True
        self._uruchom_kanal()
        watek = threading.Thread(target=self.petla, name='agent-druku-petla', daemon=True)
        watek.start()
        return watek

    def sparuj(self, crm_url, token, fabryka_klienta):
        """Nowy adres CRM i token z okienka: zapis do pliku, nowy klient, nowy kanał push
        (gdy usługa już działa) i natychmiastowy cykl. Tokenu nie logujemy."""
        self.lokalna.ustaw_polaczenie(crm_url, token)
        klient = fabryka_klienta(crm_url, token)
        with self._blokada:
            self.klient = klient
            self._nieznany = False
            self._komunikat = ''
            self._ostatni_kontakt = None
            self._start = self.zegar.monotonic()   # cisza CRM liczona od parowania
        self.ustaw_push(False)
        if self._uruchomiony:
            self._uruchom_kanal()
        log.info('Agent sparowany z CRM %s', crm_url)
        self.obudz('parowanie')

    def zatrzymaj(self):
        self._stop.set()
        self._obudz.set()
        with self._blokada:
            kanal = self._kanal
        if kanal is not None:
            kanal.zatrzymaj()

    # --- cykl -----------------------------------------------------------
    def cykl(self, powod):
        log.debug('Cykl agenta druku: %s', powod)
        if self.klient is None or not self.lokalna.token:
            with self._blokada:
                self._komunikat = 'agent nie jest sparowany z CRM'
            return
        dane = self.lokalna.dane or {}
        self._bledy_cyklu = []
        teraz = self.zegar.teraz()
        if not _w_godzinach(dane.get('godziny'), teraz):
            with self._blokada:
                self._poza_godzinami = True
                self._okno_pracy = _okno_dzis(dane.get('godziny'), teraz)
                self._porcja_odrzucona = False
                ostatnia = self._ostatnia_proba_kontaktu
            # Poza godzinami bez nowych zadań, ale zaległe wyniki idą od razu.
            zalegle = bool(self.dziennik.niepotwierdzone())
            kontakt = ostatnia is None or self.zegar.monotonic() - ostatnia >= KONTAKT_POZA_GODZINAMI_S
            if not (zalegle or kontakt):
                return
            try:
                if zalegle:
                    self._wyslij_zalegle()
                if kontakt:
                    self._kontakt()
            except NieznanyAgent:
                self._oznacz_nieznany()
            self._opublikuj_bledy()
            return
        with self._blokada:
            self._poza_godzinami = False
        try:
            self._wyslij_zalegle()
            self._synchronizuj()
            self._obsluz_drukarki()
            odp = self._kontakt()
            if odp is not None:
                self._wykonaj_polecenia(odp.get('polecenia') or [])
        except NieznanyAgent:
            self._oznacz_nieznany()
        self._opublikuj_bledy()

    def _opublikuj_bledy(self):
        """Komunikat okienka = błędy tego cyklu; udany /kontakt nie kasuje wcześniejszego błędu cyklu."""
        with self._blokada:
            self._komunikat = '; '.join(self._bledy_cyklu)

    def _oznacz_nieznany(self):
        with self._blokada:
            self._nieznany = True
        self._bledy_cyklu.append('CRM nie zna tego agenta — sparuj go ponownie')

    def _blad_crm(self, e, co):
        if isinstance(e, NieznanyAgent):
            raise e
        log.warning('%s: %s', co, e)
        self._bledy_cyklu.append('%s: %s' % (co, e.opis))

    # (2) zaległe wyniki z dziennika
    def _wyslij_zalegle(self):
        wiersze = self.dziennik.niepotwierdzone()
        if not wiersze:
            return True
        wyniki = []
        for w in wiersze:
            wynik = {'id': w['job_id'], 'wynik': w['stan']}
            if w['stan'] == 'blad':
                wynik['blad'] = self._opisy_bledow.get(w['job_id']) or 'błąd wysyłki do drukarki'
            wyniki.append(wynik)
        try:
            self.klient.wyniki(wyniki)
        except BladCrm as e:
            self._blad_crm(e, 'Nie udało się wysłać wyników do CRM')
            return False
        self.dziennik.oznacz_wyslane([(w['job_id'], w['rewizja']) for w in wiersze])
        for w in wiersze:
            self._opisy_bledow.pop(w['job_id'], None)
        return True

    # (3) synchronizacja konfiguracji
    def _synchronizuj(self):
        miala_oczekujaca = self.lokalna.oczekujaca is not None
        try:
            self.lokalna.synchronizuj(self.klient)
        except BladCrm as e:
            kod = (e.cialo or {}).get('error') if isinstance(e.cialo, dict) else None
            odrzucona = getattr(e, 'odrzucona', None)
            if kod == 'bledna_konfiguracja' and odrzucona is not None:
                with self._blokada:
                    self._blad_konfiguracji = list(e.cialo.get('bledy') or [e.opis])
                    self._blad_konfiguracji_rodzaj = 'bledna'
                try:
                    self.lokalna.porzuc_oczekujaca(self.klient, odrzucona)
                except BladCrm as e2:
                    self._blad_crm(e2, 'Nie udało się pobrać konfiguracji z CRM')
            elif kod == 'agent_nieaktywny':
                with self._blokada:
                    self._blad_konfiguracji = [AGENT_NIEAKTYWNY]
                    self._blad_konfiguracji_rodzaj = 'nieaktywny'
            else:
                self._blad_crm(e, 'Nie udało się zsynchronizować konfiguracji')
            return
        with self._blokada:
            # Błąd „bledna” zostaje do kolejnej przyjętej zmiany; „nieaktywny” znika po pierwszej udanej.
            if miala_oczekujaca or self._blad_konfiguracji_rodzaj == 'nieaktywny':
                self._blad_konfiguracji = None
                self._blad_konfiguracji_rodzaj = None

    # (4) drukarki
    def _konfiguracje_drukarek(self):
        lista = (self.lokalna.dane or {}).get('drukarki') or []
        po_nazwie = {d.get('nazwa'): d for d in lista if isinstance(d, dict)}
        return [po_nazwie[n] for n in KOLEJNOSC_DRUKAREK if n in po_nazwie]

    def _ustaw_stan(self, nazwa, **pola):
        with self._blokada:
            wpis = self._stany.setdefault(nazwa, {'nazwa': nazwa, 'stan': 'nieznany', 'opis': '',
                                                  'obsluga': 'nowy', 'komunikat': ''})
            wpis.update(pola)

    def _obsluz_drukarki(self):
        odrzucona = False
        konfiguracje = self._konfiguracje_drukarek()
        with self._blokada:  # drukarka usunięta z konfiguracji znika z okienka
            for nazwa in list(self._stany):
                if nazwa not in {d['nazwa'] for d in konfiguracje}:
                    del self._stany[nazwa]
        for drukarka in konfiguracje:
            if self._stop.is_set():   # zatrzymanie usługi: bieżąca porcja skończona, kolejnej nie bierzemy
                break
            if self._obsluz_drukarke(drukarka):
                odrzucona = True
        with self._blokada:
            self._porcja_odrzucona = odrzucona

    def _odczytaj_stan(self, drukarka):
        try:
            stan, opis = self.drukarki.stan(drukarka)
        except Exception as e:  # odczyt stanu nie może zatrzymać druku
            stan, opis = 'nieznany', 'błąd odczytu stanu: %s' % e
        self._ustaw_stan(drukarka['nazwa'], stan=stan, opis=opis or '')
        return stan

    def _obsluz_drukarke(self, drukarka):
        """Zwraca True, gdy drukarka nie przyjęła porcji (krótszy polling)."""
        nazwa = drukarka['nazwa']
        stan = self._odczytaj_stan(drukarka)
        if stan in STANY_BEZ_POBIERANIA:
            self._ustaw_stan(nazwa, komunikat='nie pobieram zadań: %s' % stan)
            return False
        for _ in range(MAKS_PORCJI):
            if self._stop.is_set():
                return False
            try:
                odp = self.klient.pobierz(nazwa, LIMIT_PORCJI)
            except BladCrm as e:
                self._blad_crm(e, 'Nie udało się pobrać zadań (%s)' % nazwa)
                return False
            obsluga = odp.get('obsluga') or 'nowy'
            if obsluga != 'nowy':  # drukarka teraz nie nasza — pomijamy bez błędu
                self._ustaw_stan(nazwa, obsluga=obsluga,
                                 komunikat=KOMUNIKATY_OBSLUGI.get(obsluga, OBSLUGA_INNA))
                return False
            self._ustaw_stan(nazwa, obsluga='nowy', komunikat='')
            zadania = odp.get('zadania') or []
            if not zadania:
                return False
            wyniki = self._wydrukuj(drukarka, zadania)
            if drukarka.get('odczyt_stanu') != 'snmp':
                # bez SNMP stan to wynik ostatniego połączenia — odświeżamy po wysyłce
                self._odczytaj_stan(drukarka)
            if any(w['wynik'] != 'wydrukowane' for w in wyniki):
                return True
            if len(zadania) < LIMIT_PORCJI:
                return False
        return False

    def _wydrukuj(self, drukarka, zadania):
        nazwa = drukarka['nazwa']
        przerwane = set()
        for z in zadania:
            if self.dziennik.czy_wysylane(z['id']):
                przerwane.add(z['id'])   # wysyłane w poprzednim przebiegu — nie drugi raz
            else:
                self.dziennik.zapisz(z['id'], nazwa, z.get('kod'), 'pobrane')

        def przed_wyslaniem(job_id):
            if job_id in przerwane:
                return False
            kod = next((z.get('kod') for z in zadania if z['id'] == job_id), None)
            self.dziennik.zapisz(job_id, nazwa, kod, 'wysylam')
            try:
                self.klient.wysylam(job_id)
            except NieznanyAgent:
                return False
            except BladCrm as e:
                log.warning('CRM nie przyjął „wysyłam” dla zadania %s: %s', job_id, e)
                return False
            return True

        wyniki = self.drukarki.wyslij_porcje(
            drukarka, [{'id': z['id'], 'zpl': z['zpl']} for z in zadania], przed_wyslaniem)
        kody = {z['id']: z.get('kod') for z in zadania}
        for w in wyniki:
            if w['id'] in przerwane:
                w['wynik'], w['blad'] = 'blad', BLAD_PRZERWANEJ_WYSYLKI
            if w['wynik'] == 'blad':
                self._opisy_bledow[w['id']] = w.get('blad') or 'błąd wysyłki do drukarki'
            self.dziennik.zapisz(w['id'], nazwa, kody.get(w['id']), w['wynik'])
        self._wyslij_zalegle()
        return wyniki

    # (5) kontakt
    def _kontakt(self):
        with self._blokada:
            self._ostatnia_proba_kontaktu = self.zegar.monotonic()
            stany = [{'nazwa': s['nazwa'], 'stan': s['stan'], 'opis': s['opis']}
                     for s in (self._stany.get(n) for n in KOLEJNOSC_DRUKAREK) if s]
            push_wl = self._push
        if not stany:  # przed pierwszym odczytem — sama lista skonfigurowanych drukarek
            stany = [{'nazwa': d['nazwa'], 'stan': 'nieznany', 'opis': ''}
                     for d in self._konfiguracje_drukarek()]
        try:
            odp = self.klient.kontakt(WERSJA, stany, push_wl, self.lokalna.wersja)
        except NieznanyAgent:
            self._oznacz_nieznany()
            return None
        except BladCrm as e:
            self._blad_crm(e, 'Brak kontaktu z CRM')
            return None
        with self._blokada:
            self._ostatni_kontakt = self.zegar.monotonic()
            self._nieznany = False
            self._aktualizacja = odp.get('aktualizacja')
        return odp

    # (6) polecenia
    def _wykonaj_polecenia(self, polecenia):
        po_nazwie = {d['nazwa']: d for d in self._konfiguracje_drukarek()}
        for p in polecenia:
            if p.get('rodzaj') != 'kalibracja':
                ok, opis = False, 'nieznane polecenie: %s' % p.get('rodzaj')
            elif p.get('drukarka') not in po_nazwie:
                ok, opis = False, 'brak drukarki %s w konfiguracji agenta' % p.get('drukarka')
            else:
                try:
                    self.drukarki.kalibruj(po_nazwie[p['drukarka']])
                    ok, opis = True, 'kalibracja wysłana do drukarki'
                except Exception as e:
                    ok, opis = False, 'kalibracja nieudana: %s' % e
            try:
                self.klient.wynik_polecenia(p['id'], ok, opis)
            except BladCrm as e:  # polecenie zostaje pending — CRM poda je przy kolejnym kontakcie
                self._blad_crm(e, 'Nie udało się zgłosić wyniku polecenia')

    # --- okienko --------------------------------------------------------
    def stan_dla_okienka(self):
        teraz = self.zegar.monotonic()
        with self._blokada:
            sparowany = bool(self.klient is not None and self.lokalna.token and not self._nieznany)
            crm = self._ostatni_kontakt is not None and teraz - self._ostatni_kontakt <= CISZA_CRM_S
            cisza = teraz - (self._ostatni_kontakt if self._ostatni_kontakt is not None else self._start)
            drukarki = [dict(self._stany[n]) for n in KOLEJNOSC_DRUKAREK if n in self._stany]
            komunikat = self._komunikat
            blad_konf = list(self._blad_konfiguracji) if self._blad_konfiguracji else None
            wynik = {'push': self._push, 'aktualizacja': self._aktualizacja}
            poza_godzinami, okno = self._poza_godzinami, self._okno_pracy
        if not sparowany:
            ogolny, komunikat = 'awaria', komunikat or 'agent nie jest sparowany z CRM'
        elif cisza > CISZA_CRM_S:
            ogolny, komunikat = 'awaria', komunikat or 'brak kontaktu z CRM'
        elif poza_godzinami:
            # Agent celowo nie drukuje — ikona nie może pokazywać „wszystko działa”.
            ogolny = 'uwaga'
            komunikat = '; '.join(x for x in (komunikat_poza_godzinami(okno), komunikat) if x)
        else:
            problemy = [d for d in drukarki if d['obsluga'] == 'nowy' and d['stan'] != 'gotowa']
            if problemy:
                ogolny = 'uwaga'
                komunikat = komunikat or ', '.join('%s: %s' % (d['nazwa'], d['stan']) for d in problemy)
            elif blad_konf or not crm:
                ogolny = 'uwaga'
                komunikat = komunikat or ('; '.join(blad_konf) if blad_konf else 'łączenie z CRM…')
            else:
                ogolny = 'ok'
        wynik.update({
            'ogolny': ogolny, 'komunikat': komunikat, 'crm': crm, 'drukarki': drukarki,
            'ostatnie': self.dziennik.ostatnie(20), 'wersja': WERSJA, 'sparowany': sparowany,
            'blad_konfiguracji': blad_konf, 'poza_godzinami': poza_godzinami,
        })
        return wynik
