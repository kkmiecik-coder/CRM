"""Ikona w zasobniku i okienko agenta druku (dla człowieka przy hubie hali).

Rozmawia wyłącznie z lokalnym API usługi (127.0.0.1, nagłówek X-Klucz). pystray, tkinter i PIL
ładowane są dopiero w `main()` — rdzeń i testy działają bez nich.

Wątki: tkinter działa tylko w wątku głównym. Zapytania HTTP idą w wątkach tła i oddają wynik
przez kolejkę, którą wątek główny opróżnia timerem `after`. Menu ikony (wątek pystray) też
tylko wkłada polecenia do tej kolejki.
"""
import json
import logging
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

from agent_druku import aktualizacja, lokalne_api, sciezki

log = logging.getLogger('agent_druku.zasobnik')

ODSWIEZANIE_MS = 3000
POMPA_MS = 150
LIMIT_CISZY_USLUGI_S = 10
LIMIT_ZAPYTANIA_S = 2
LIMIT_AKCJI_S = 40      # wydruk próbny i kalibracja mogą budzić drukarkę do 20 s

# --- kolory i pismo (jasne tło, ciemny tekst, kolory stanu jak w panelu produkcji) -----------
TLO = '#FFFFFF'
TLO_STOPKI = '#F4F5F6'
TEKST = '#1F2328'
SZARY = '#5B6168'
LINIA = '#DADDE1'
DREWNO = '#8B5A2B'
POZIOMY = {   # poziom: (tekst, tło, pasek, kolor ikony)
    'ok': ('#1B5E20', '#D8F3DC', '#2E9E44', '#2E9E44'),
    'uwaga': ('#7A5B00', '#FFF3CD', '#E5A100', '#E5A100'),
    'awaria': ('#842029', '#F8D7DA', '#C62828', '#D32F2F'),
    'neutralny': ('#495057', '#E9ECEF', '#ADB5BD', '#ADB5BD'),
}
PISMO = 'Segoe UI'

NAZWY = {'etykiety': 'Etykiety 60×40', 'wysylka': 'Paczki 100×150'}
NAZWY_KROTKIE = {'etykiety': 'Etykiety', 'wysylka': 'Paczki'}
STANY_DRUKARKI = {
    'gotowa': ('gotowa', 'ok'),
    'brak_papieru': ('brak etykiet', 'awaria'),
    'otwarta_klapa': ('otwarta klapa', 'awaria'),
    'offline': ('nie odpowiada', 'awaria'),
    'blad': ('błąd drukarki', 'awaria'),
    'pauza': ('wstrzymana', 'uwaga'),
    'nieznany': ('stan nieznany', 'uwaga'),
}
PORADY = {
    'brak_papieru': 'Włóż nową rolkę. Etykiety z kolejki wydrukują się same.',
    'otwarta_klapa': 'Zamknij klapę drukarki. Etykiety z kolejki wydrukują się same.',
    'offline': 'Sprawdź, czy drukarka jest włączona i ma podłączony kabel.',
    'blad': 'Sprawdź drukarkę, np. zaciętą etykietę. Po usunięciu problemu wydruki ruszą same.',
    'pauza': 'Drukarka jest wstrzymana. Wznów ją przyciskiem na drukarce.',
    'nieznany': 'Agent jeszcze nie odczytał stanu tej drukarki. Odczyt pojawi się przy pierwszym wydruku.',
}
STANY_WYDRUKU = {
    'wydrukowane': ('✓', 'ok'),
    'blad': ('✗ błąd', 'awaria'),
    'niewyslane': ('nie wysłano', 'uwaga'),
    'pobrane': ('czeka', 'neutralny'),
    'wysylam': ('wysyłam', 'neutralny'),
    'nieznany': ('przerwane — sprawdź etykietę', 'uwaga'),
}
USLUGA_NIE_DZIALA = 'Usługa agenta nie działa'
USLUGA_NIE_ODPOWIADA = 'Usługa agenta nie odpowiada — sprawdź, czy działa.'


# --- logika bez GUI (testowalna) --------------------------------------------------------------
def opis_glowny(stan):
    """(poziom, tytuł, szczegół) dużego komunikatu. stan=None — usługa nie odpowiada."""
    if stan is None:
        return ('awaria', USLUGA_NIE_DZIALA,
                'Ikona nie może połączyć się z usługą drukowania na tym komputerze. '
                'Uruchom komputer ponownie, a jeśli to nie pomoże, zadzwoń do biura.')
    ogolny = stan.get('ogolny')
    komunikat = stan.get('komunikat') or ''
    if not stan.get('sparowany'):
        szczegol = 'Wklej adres CRM i token agenta w zakładce Parowanie.'
        if 'nie zna' in komunikat:   # 401: token unieważniony w CRM
            szczegol = 'CRM nie zna tego agenta. Wygeneruj nowy token w CRM i wklej go w zakładce Parowanie.'
        return ('awaria', 'Agent nie jest połączony z CRM', szczegol)
    if ogolny == 'awaria':
        return ('awaria', 'Brak połączenia z CRM',
                'Sprawdź internet na tym komputerze. Etykiety czekają w CRM '
                'i wydrukują się same po powrocie połączenia.')
    if ogolny == 'uwaga':
        if stan.get('poza_godzinami'):
            return ('uwaga', 'Poza godzinami pracy', komunikat)
        for d in stan.get('drukarki') or []:
            if d.get('obsluga', 'nowy') == 'nowy' and d.get('stan') != 'gotowa':
                tekst = STANY_DRUKARKI.get(d.get('stan'), (d.get('stan') or '?', 'uwaga'))[0]
                return ('uwaga', '%s: %s' % (NAZWY_KROTKIE.get(d.get('nazwa'), d.get('nazwa')), tekst),
                        PORADY.get(d.get('stan'), d.get('opis') or ''))
        if stan.get('blad_konfiguracji'):
            return ('uwaga', 'CRM nie przyjął konfiguracji', '; '.join(stan['blad_konfiguracji']))
        return ('uwaga', 'Łączenie z CRM…', komunikat)
    return ('ok', 'Wszystko działa', 'Etykiety drukują się same.')


def opis_aktualizacji(akt):
    """(napis paska aktualizacji, czy „Aktualizuj” klikalny); None — paska nie pokazujemy."""
    if not isinstance(akt, dict) or not akt.get('wersja'):
        return None
    wersja, etap = akt['wersja'], akt.get('postep')
    if etap == 'pobieranie':
        return 'Pobieram aktualizację %s…' % wersja, False
    if etap == 'weryfikacja':
        return 'Sprawdzam pobraną aktualizację %s…' % wersja, False
    if etap == 'instalacja':
        return 'Instaluję aktualizację %s — ikona zniknie na chwilę i wróci sama' % wersja, False
    if etap == 'blad':
        return 'Aktualizacja %s nieudana: %s' % (wersja, akt.get('blad') or 'nieznany błąd'), True
    return 'Dostępna aktualizacja %s' % wersja, True


def zaczela_sie_instalacja(poprzednia, akt):
    """Czy ikona ma się teraz zamknąć na czas instalacji. `poprzednia` — informacja o aktualizacji
    z poprzedniej odpowiedzi usługi ({} gdy jej nie było), None — to pierwsza odpowiedź. Ikona
    uruchomiona po instalacji widzi „instalacja” od razu (nieudana instalacja zostawia usługę
    z tym stanem) i nie może się znów zamknąć — zamyka się tylko na samo przejście."""
    if poprzednia is None or not isinstance(akt, dict) or akt.get('postep') != 'instalacja':
        return False
    return poprzednia.get('postep') != 'instalacja'


def drukarki_tego_agenta(stan):
    """Nazwy drukarek, które obsługuje ten agent (wydruk próbny i kalibracja z okienka)."""
    return [d['nazwa'] for d in (stan or {}).get('drukarki') or []
            if d.get('obsluga', 'nowy') == 'nowy']


def poziom_ikony(stan, ostatnia_odpowiedz, teraz, start):
    """Poziom ikony: brak odpowiedzi usługi dłużej niż 10 s = awaria."""
    if stan is None:
        odniesienie = ostatnia_odpowiedz if ostatnia_odpowiedz is not None else start
        return 'awaria' if teraz - odniesienie > LIMIT_CISZY_USLUGI_S else None
    return opis_glowny(stan)[0]


class BladKluczaZasobnika(Exception):
    """Ikona nie może odczytać klucza usługi — to nie awaria usługi, restart komputera nie pomoże.
    Celowo nie OSError: okno odróżnia ten błąd od braku odpowiedzi usługi."""

    def __init__(self, tytul, szczegol):
        super().__init__(szczegol)
        self.tytul = tytul
        self.szczegol = szczegol


def opis_bledu(blad):
    """Tekst dla nieudanego zapytania do usługi."""
    if isinstance(blad, BladKluczaZasobnika):
        return blad.szczegol
    return USLUGA_NIE_ODPOWIADA


# Lokalne API zawsze bezpośrednio: urlopen czyta systemowe proxy (na Windows z rejestru), a ProxyOverride
# „<local>” nie obejmuje 127.0.0.1 — ikona przestałaby działać, a klucz usługi poszedłby do proxy.
_OTWIERACZ = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class KlientLokalny:
    """HTTP do lokalnego API; klucz czytany z pliku przy każdym zapytaniu (usługa może go
    założyć dopiero po starcie ikony)."""

    def __init__(self, port=lokalne_api.PORT, plik_klucza=None):
        self._adres = 'http://%s:%d' % (lokalne_api.HOST, port)
        self._plik_klucza = plik_klucza

    def klucz(self):
        """Klucz usługi albo BladKluczaZasobnika (brak pliku, za krótki, brak uprawnień)."""
        sciezka = self._plik_klucza or sciezki.plik_klucza_lokalnego()
        try:
            klucz = lokalne_api.wczytaj_klucz(sciezka)
        except FileNotFoundError:
            klucz = ''
        except PermissionError:
            raise BladKluczaZasobnika(
                'Ikona nie może odczytać klucza usługi',
                'Ikona nie może odczytać klucza usługi (brak uprawnień do %s) — zadzwoń do biura.'
                % sciezka) from None
        except OSError as e:
            raise BladKluczaZasobnika(
                'Ikona nie może odczytać klucza usługi',
                'Ikona nie może odczytać klucza usługi (%s: %s) — zadzwoń do biura.'
                % (sciezka, e.strerror or e)) from None
        if len(klucz) < lokalne_api.MIN_DLUGOSC_KLUCZA:
            raise BladKluczaZasobnika(
                'Brak klucza usługi',
                'Brak klucza usługi — usługa nie wystartowała albo nie jest zainstalowana. '
                'Zadzwoń do biura.')
        return klucz

    def zapytaj(self, metoda, sciezka, dane=None, limit_s=LIMIT_ZAPYTANIA_S):
        """(kod HTTP, ciało: dict albo str). OSError — usługa nie odpowiada;
        BladKluczaZasobnika — ikona nie ma klucza usługi."""
        naglowki = {'X-Klucz': self.klucz()}
        tresc = None
        if dane is not None:
            tresc = json.dumps(dane).encode('utf-8')
            naglowki['Content-Type'] = 'application/json'
        zad = urllib.request.Request(self._adres + sciezka, data=tresc, headers=naglowki,
                                     method=metoda)
        try:
            with _OTWIERACZ.open(zad, timeout=limit_s) as odp:
                kod, surowe, typ = odp.status, odp.read(), odp.headers.get('Content-Type', '')
        except urllib.error.HTTPError as e:
            kod, surowe, typ = e.code, e.read(), e.headers.get('Content-Type', '')
        except urllib.error.URLError as e:
            raise OSError(str(e.reason)) from None
        tekst = surowe.decode('utf-8', 'replace')
        if 'json' in typ:
            try:
                return kod, json.loads(tekst)
            except ValueError:
                pass
        return kod, tekst


def _opis_odpowiedzi(kod, cialo, domyslny):
    if isinstance(cialo, dict) and cialo.get('opis'):
        tekst = cialo['opis']
    elif isinstance(cialo, dict) and cialo.get('bledy'):
        tekst = '; '.join(cialo['bledy'])
    else:
        tekst = domyslny
    return tekst[:1].upper() + tekst[1:]


# --- GUI ---------------------------------------------------------------------------------------
def _obrazy_ikon():
    from PIL import Image, ImageDraw
    obrazy = {}
    for poziom, (_t, _b, _p, kolor) in POZIOMY.items():
        obraz = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        rysunek = ImageDraw.Draw(obraz)
        rysunek.ellipse((4, 4, 60, 60), fill=kolor, outline='#FFFFFF', width=4)
        obrazy[poziom] = obraz
    return obrazy


class Zasobnik:
    def __init__(self, klient):
        import tkinter as tk
        from tkinter import ttk

        import pystray

        self.tk, self.ttk = tk, ttk
        self.klient = klient
        self.kolejka = queue.Queue()
        self.stan = None
        self.poziom = None
        self.start = time.monotonic()
        self.ostatnia_odpowiedz = None
        self.pytam = False
        self.ip_drukarek = {}
        self.konfiguracja = None
        self.edytowana = False
        self.poprzednia_akt = None     # informacja o aktualizacji z poprzedniej odpowiedzi usługi
        self.zamykam_na_instalacje = False

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title('WoodPower — Agent druku')
        self.root.configure(bg=TLO)
        self.root.minsize(520, 0)   # wysokość z treści — zakładka Konfiguracja jest najwyższa
        self.root.protocol('WM_DELETE_WINDOW', self.root.withdraw)
        self._style()
        self._zbuduj()

        self.obrazy = _obrazy_ikon()
        self.ikona = pystray.Icon(
            'AgentDruku', self.obrazy['uwaga'], 'Agent druku — uruchamianie',
            menu=pystray.Menu(
                pystray.MenuItem('Pokaż okno', lambda: self.kolejka.put((self.pokaz, ())),
                                 default=True),
                pystray.MenuItem('Zamknij ikonę', lambda: self.kolejka.put((self.zamknij, ())))))

    # --- infrastruktura wątków ---
    def w_tle(self, funkcja, po):
        """funkcja() w wątku tła; po(wynik, blad) w wątku głównym."""
        def praca():
            try:
                wynik, blad = funkcja(), None
            except Exception as e:  # noqa: BLE001 — każdy błąd zapytania to brak odpowiedzi usługi
                wynik, blad = None, e
            self.kolejka.put((po, (wynik, blad)))
        threading.Thread(target=praca, daemon=True).start()

    def _pompuj(self):
        while True:
            try:
                funkcja, argumenty = self.kolejka.get_nowait()
            except queue.Empty:
                break
            funkcja(*argumenty)
        self.root.after(POMPA_MS, self._pompuj)

    def main(self):
        self.ikona.run_detached()
        self.root.after(POMPA_MS, self._pompuj)
        self.root.after(0, self._odpytaj)
        self.w_tle(lambda: self.klient.zapytaj('GET', '/konfiguracja'), self._po_konfiguracji)
        self.root.mainloop()

    def pokaz(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def zamknij(self):
        self.ikona.stop()
        self.root.destroy()

    # --- wygląd ---
    def _style(self):
        s = self.ttk.Style(self.root)
        try:
            s.theme_use('vista')
        except self.tk.TclError:
            s.theme_use('clam')
        s.configure('TNotebook', background=TLO, borderwidth=0)
        s.configure('TNotebook.Tab', font=(PISMO, 10), padding=(14, 6))
        s.configure('TFrame', background=TLO)
        s.configure('TButton', font=(PISMO, 10), padding=(10, 6))
        s.configure('TCheckbutton', background=TLO, font=(PISMO, 10))
        s.configure('TLabelframe', background=TLO)
        s.configure('TLabelframe.Label', background=TLO, foreground=DREWNO, font=(PISMO, 10, 'bold'))

    def _etykieta(self, rodzic, tekst='', rozmiar=10, waga='normal', kolor=TEKST, **kw):
        kw.setdefault('bg', TLO)
        return self.tk.Label(rodzic, text=tekst, fg=kolor, font=(PISMO, rozmiar, waga),
                             anchor='w', justify='left', **kw)

    def _pigulka(self, rodzic, tekst, poziom):
        fg, bg, _p, _i = POZIOMY[poziom]
        return self.tk.Label(rodzic, text=tekst, fg=fg, bg=bg, font=(PISMO, 9, 'bold'),
                             padx=8, pady=1)

    def _zbuduj(self):
        tk = self.tk
        # pasek aktualizacji (pokazywany tylko, gdy CRM ma nowszą wersję)
        self.pasek_akt = tk.Frame(self.root, bg='#F3E9DF')
        self.napis_akt = tk.Label(self.pasek_akt, bg='#F3E9DF', fg='#5A3A1A', font=(PISMO, 10, 'bold'))
        self.napis_akt.pack(side='left', padx=12, pady=6)
        self.przycisk_akt = self.ttk.Button(self.pasek_akt, text='Aktualizuj', command=self._aktualizuj)
        self.przycisk_akt.pack(side='right', padx=12, pady=4)

        # duży komunikat
        self.baner = tk.Frame(self.root, bg=TLO)
        self.baner.pack(fill='x')
        self.baner_pasek = tk.Frame(self.baner, width=8)
        self.baner_pasek.pack(side='left', fill='y')
        self.baner_srodek = tk.Frame(self.baner)
        self.baner_srodek.pack(side='left', fill='both', expand=True)
        self.tytul = tk.Label(self.baner_srodek, font=(PISMO, 17, 'bold'), anchor='w', justify='left')
        self.tytul.pack(fill='x', padx=14, pady=(12, 0))
        self.szczegol = tk.Label(self.baner_srodek, font=(PISMO, 11), anchor='w', justify='left',
                                 wraplength=500)
        self.szczegol.pack(fill='x', padx=14, pady=(2, 12))
        self.baner_srodek.bind('<Configure>', lambda e: self.szczegol.configure(
            wraplength=max(200, e.width - 30)))

        zakladki = self.ttk.Notebook(self.root)
        zakladki.pack(fill='both', expand=True, padx=10, pady=10)
        self.zakladka_stan = self.ttk.Frame(zakladki, padding=10)
        self.zakladka_konf = self.ttk.Frame(zakladki, padding=10)
        self.zakladka_par = self.ttk.Frame(zakladki, padding=10)
        zakladki.add(self.zakladka_stan, text='Stan')
        zakladki.add(self.zakladka_konf, text='Konfiguracja')
        zakladki.add(self.zakladka_par, text='Parowanie')
        self._zbuduj_stan()
        self._zbuduj_konfiguracje()
        self._zbuduj_parowanie()

        self.stopka = tk.Label(self.root, bg=TLO_STOPKI, fg=SZARY, font=(PISMO, 9), anchor='w')
        self.stopka.pack(fill='x', side='bottom', ipady=4, ipadx=10)
        self._pokaz_opis('uwaga', 'Łączenie z usługą agenta…', '')

    def _zbuduj_stan(self):
        tk = self.tk
        f = self.zakladka_stan
        self._etykieta(f, 'Połączenia i drukarki', 11, 'bold').pack(fill='x')
        self.tabela = tk.Frame(f, bg=TLO)
        self.tabela.pack(fill='x', pady=(4, 12))
        self._etykieta(f, 'Ostatnie wydruki', 11, 'bold').pack(fill='x')
        self.wydruki = tk.Frame(f, bg=TLO)
        self.wydruki.pack(fill='x', pady=(4, 12))

        przyciski = tk.Frame(f, bg=TLO)
        przyciski.pack(fill='x', side='bottom')
        self.wynik_akcji = self._etykieta(f, '', 10, wraplength=480)
        self.wynik_akcji.pack(fill='x', side='bottom', pady=(0, 6))
        self.przycisk_probny = self.ttk.Button(przyciski, text='Wydruk próbny',
                                               command=lambda: self._wybierz_drukarke(
                                                   self.przycisk_probny, self._wydruk_probny))
        self.przycisk_kalibruj = self.ttk.Button(przyciski, text='Kalibruj',
                                                 command=lambda: self._wybierz_drukarke(
                                                     self.przycisk_kalibruj, self._kalibruj))
        self.przycisk_probny.pack(side='left', padx=(0, 6))
        self.ttk.Button(przyciski, text='Ponów zaległe', command=self._ponow).pack(side='left', padx=(0, 6))
        self.przycisk_kalibruj.pack(side='left', padx=(0, 6))
        self.ttk.Button(przyciski, text='Otwórz log', command=self._otworz_log).pack(side='left')

    def _wiersz(self, rodzic, wiersz, kolumny):
        for kol, widget in enumerate(kolumny):
            widget.grid(row=wiersz, column=kol, sticky='w', padx=(0, 12), pady=3)
        linia = self.tk.Frame(rodzic, bg=LINIA, height=1)
        linia.grid(row=wiersz, column=0, columnspan=len(kolumny), sticky='sew')
        linia.lower()

    # --- odświeżanie stanu ---
    def _odpytaj(self):
        if not self.pytam:
            self.pytam = True
            self.w_tle(lambda: self.klient.zapytaj('GET', '/stan'), self._po_stanie)
        self.root.after(ODSWIEZANIE_MS, self._odpytaj)

    def _po_stanie(self, wynik, blad):
        self.pytam = False
        teraz = time.monotonic()
        if isinstance(blad, BladKluczaZasobnika):   # od razu czerwona, bez porady o restarcie
            self.stan = None
            self._pokaz_opis('awaria', blad.tytul, blad.szczegol)
            self._rysuj_tabele(blad)
            self._rysuj_wydruki()
            self._rysuj_aktualizacje()
            self._rysuj_parowanie()
            return
        if blad is None and wynik[0] == 200 and isinstance(wynik[1], dict):
            self.ostatnia_odpowiedz = teraz
            self.stan = wynik[1]
            akt = self.stan.get('aktualizacja') or {}
            if zaczela_sie_instalacja(self.poprzednia_akt, akt):
                self._zamknij_na_instalacje(akt.get('wersja'))
            self.poprzednia_akt = akt
        else:
            self.stan = None
        poziom = poziom_ikony(self.stan, self.ostatnia_odpowiedz, teraz, self.start)
        if poziom is None:      # chwilowy brak odpowiedzi (< 10 s) — zostawiamy ostatni obraz
            return
        if self.stan is None:
            self._pokaz_opis(*opis_glowny(None))
        else:
            self._pokaz_opis(*opis_glowny(self.stan))
        self._rysuj_tabele()
        self._rysuj_wydruki()
        self._rysuj_aktualizacje()
        self._rysuj_parowanie()

    def _pokaz_opis(self, poziom, tytul, szczegol):
        fg, bg, pasek, _i = POZIOMY[poziom]
        znak = '✓ ' if poziom == 'ok' else '⚠ '
        for w in (self.baner_srodek, self.tytul, self.szczegol):
            w.configure(bg=bg)
        self.baner.configure(bg=bg)
        self.baner_pasek.configure(bg=pasek)
        self.tytul.configure(text=znak + tytul, fg=fg)
        self.szczegol.configure(text=szczegol, fg=TEKST)
        self.szczegol.pack_configure(pady=(2, 12) if szczegol else (0, 8))
        wersja = (self.stan or {}).get('wersja')
        self.stopka.configure(text=('Agent druku %s' % wersja) if wersja else 'Agent druku')
        if hasattr(self, 'ikona'):
            self._ustaw_ikone(poziom, tytul, szczegol)

    def _ustaw_ikone(self, poziom, tytul, szczegol):
        if poziom == self.poziom:
            return
        poprzedni, self.poziom = self.poziom, poziom
        self.ikona.icon = self.obrazy[poziom]
        self.ikona.title = ('Agent druku — ' + tytul)[:120]
        if poziom in ('uwaga', 'awaria') and poprzedni is not None:
            try:
                self.ikona.notify(szczegol or tytul, tytul)
            except Exception:  # noqa: BLE001 — dymek to dodatek
                pass

    def _rysuj_tabele(self, blad_klucza=None):
        for w in self.tabela.winfo_children():
            w.destroy()
        t = self.tabela
        if self.stan is None:
            self._wiersz(t, 0, [self._etykieta(t, 'Usługa agenta', waga='bold'),
                                self._pigulka(t, 'brak klucza' if blad_klucza else 'nie odpowiada',
                                              'awaria')])
            return
        s = self.stan
        wiersze = [
            ('CRM', ('połączony', 'ok') if s.get('crm') else ('brak połączenia', 'awaria'),
             s.get('crm_url') or ''),
            ('Push', ('połączony', 'ok') if s.get('push') else ('rozłączony', 'neutralny'),
             '' if s.get('push') else 'wydruki co kilka sekund zamiast od razu'),
        ]
        for d in s.get('drukarki') or []:
            if d.get('obsluga', 'nowy') != 'nowy':  # stary agent, przełączanie albo inny agent
                pig = (d.get('komunikat') or 'obsługuje stary agent', 'neutralny')
            else:
                pig = STANY_DRUKARKI.get(d.get('stan'), (d.get('stan') or '?', 'uwaga'))
            szczegol = self.ip_drukarek.get(d.get('nazwa')) or ''
            if d.get('opis') and d.get('stan') != 'gotowa':
                szczegol = ('%s · %s' % (szczegol, d['opis'])) if szczegol else d['opis']
            wiersze.append((NAZWY.get(d.get('nazwa'), d.get('nazwa')), pig, szczegol))
        if not s.get('drukarki'):
            wiersze.append(('Drukarki', ('brak w konfiguracji', 'uwaga'), 'wpisz je w zakładce Konfiguracja'))
        for i, (nazwa, (tekst, poziom), szczegol) in enumerate(wiersze):
            self._wiersz(t, i, [self._etykieta(t, nazwa, waga='bold', width=15),
                                self._pigulka(t, tekst, poziom),
                                self._etykieta(t, szczegol, 9, kolor=SZARY)])

    def _rysuj_wydruki(self):
        for w in self.wydruki.winfo_children():
            w.destroy()
        f = self.wydruki
        ostatnie = (self.stan or {}).get('ostatnie') or []
        if not ostatnie:
            self._etykieta(f, 'Jeszcze nic nie drukowano.', kolor=SZARY).grid(row=0, column=0, sticky='w')
            return
        for i, w in enumerate(ostatnie[:8]):
            tekst, poziom = STANY_WYDRUKU.get(w.get('stan'), (w.get('stan') or '?', 'neutralny'))
            co = w.get('kod') or 'zadanie %s' % w.get('job_id')
            self._wiersz(f, i, [self._etykieta(f, str(w.get('zmieniono') or '')[11:16], kolor=SZARY),
                                self._etykieta(f, NAZWY_KROTKIE.get(w.get('drukarka'), w.get('drukarka'))),
                                self._etykieta(f, co),
                                self._pigulka(f, tekst, poziom)])

    def _zamknij_na_instalacje(self, wersja):
        """Instalator podmienia AgentDruku.exe, którego używa też ta ikona — zamykamy ją, a ukryty
        PowerShell uruchomi nową po końcu instalacji. Poza zbudowanym exe (python -m) nic nie robimy."""
        if self.zamykam_na_instalacje or not getattr(sys, 'frozen', False):
            return
        try:
            aktualizacja.uruchom_powrot_zasobnika(sys.executable, wersja)
        except (OSError, ValueError) as e:
            log.warning('Nie zaplanowano powrotu ikony po aktualizacji: %s', e)
            return
        self.zamykam_na_instalacje = True
        self.root.after(1500, self.zamknij)

    def _rysuj_aktualizacje(self):
        opis = opis_aktualizacji((self.stan or {}).get('aktualizacja'))
        if opis is not None:
            self.napis_akt.configure(text=opis[0])
            self.przycisk_akt.state(['!disabled'] if opis[1] else ['disabled'])
            if not self.pasek_akt.winfo_ismapped():
                self.pasek_akt.pack(fill='x', before=self.baner)
        elif self.pasek_akt.winfo_ismapped():
            self.pasek_akt.pack_forget()

    # --- akcje ---
    def _pokaz_wynik(self, tekst, poziom):
        kolor = POZIOMY[poziom][0] if poziom != 'neutralny' else SZARY
        self.wynik_akcji.configure(text=tekst, fg=kolor)

    def _akcja(self, metoda, sciezka, oczekiwanie, domyslny_blad, dane=None, limit_s=LIMIT_AKCJI_S,
               po=None):
        self._pokaz_wynik(oczekiwanie, 'neutralny')

        def gotowe(wynik, blad):
            if blad is not None:
                self._pokaz_wynik(opis_bledu(blad), 'awaria')
            else:
                kod, cialo = wynik
                self._pokaz_wynik(_opis_odpowiedzi(kod, cialo, domyslny_blad),
                                  'ok' if kod < 300 else 'awaria')
            if po is not None:
                po(wynik, blad)
        self.w_tle(lambda: self.klient.zapytaj(metoda, sciezka, dane if dane is not None else {},
                                               limit_s), gotowe)

    def _wybierz_drukarke(self, przycisk, akcja):
        if not (self.stan or {}).get('drukarki'):
            self._pokaz_wynik('Brak drukarek w konfiguracji — wpisz je w zakładce Konfiguracja.', 'uwaga')
            return
        nazwy = drukarki_tego_agenta(self.stan)
        if not nazwy:
            self._pokaz_wynik('Drukarki obsługuje jeszcze stary agent — wydruk próbny i kalibrację '
                              'zrób z panelu CRM.', 'uwaga')
            return
        menu = self.tk.Menu(self.root, tearoff=0, font=(PISMO, 10))
        for n in nazwy:
            menu.add_command(label=NAZWY.get(n, n), command=lambda n=n: akcja(n))
        menu.tk_popup(przycisk.winfo_rootx(), przycisk.winfo_rooty() + przycisk.winfo_height())

    def _wydruk_probny(self, nazwa):
        self._akcja('POST', '/wydruk-probny/' + nazwa,
                    'Wysyłam wydruk próbny: %s…' % NAZWY.get(nazwa, nazwa), 'wydruk próbny nieudany')

    def _kalibruj(self, nazwa):
        from tkinter import messagebox
        if not messagebox.askyesno('Kalibracja drukarki',
                                   'Drukarka %s przewinie kilka pustych etykiet i zapamięta, gdzie '
                                   'zaczyna się etykieta. Kalibrować?' % NAZWY.get(nazwa, nazwa),
                                   parent=self.root):
            return
        self._akcja('POST', '/kalibruj/' + nazwa, 'Wysyłam kalibrację…', 'kalibracja nieudana')

    def _ponow(self):
        self._akcja('POST', '/ponow-zalegle', 'Zlecam ponowienie…', 'ponowienie nieudane',
                    limit_s=LIMIT_ZAPYTANIA_S)

    def _aktualizuj(self):
        def po(wynik, blad):
            if blad is None and wynik[0] == 404:
                self._pokaz_wynik('Aktualizacja niedostępna w tej wersji.', 'uwaga')
        self._akcja('POST', '/aktualizacja', 'Pobieram aktualizację…', 'aktualizacja nieudana', po=po)

    def _otworz_log(self):
        tk = self.tk
        okno = tk.Toplevel(self.root, bg=TLO)
        okno.title('Log agenta druku')
        okno.geometry('820x520')
        gora = tk.Frame(okno, bg=TLO)
        gora.pack(fill='x', padx=10, pady=8)
        tekst = tk.Text(okno, font=('Consolas', 9), wrap='none', fg=TEKST, bg=TLO, relief='flat',
                        borderwidth=0)
        pasek = self.ttk.Scrollbar(okno, command=tekst.yview)
        tekst.configure(yscrollcommand=pasek.set)
        pasek.pack(side='right', fill='y')
        tekst.pack(fill='both', expand=True, padx=(10, 0), pady=(0, 10))

        def wczytaj():
            def gotowe(wynik, blad):
                if not okno.winfo_exists():
                    return
                if blad is not None:
                    tresc = opis_bledu(blad)
                elif wynik[0] != 200:
                    tresc = 'Nie udało się pobrać logu (HTTP %s).' % wynik[0]
                else:
                    tresc = wynik[1] if isinstance(wynik[1], str) else ''
                    tresc = tresc or 'Log jest pusty.'
                tekst.configure(state='normal')
                tekst.delete('1.0', 'end')
                tekst.insert('end', tresc)
                tekst.configure(state='disabled')
                tekst.see('end')
            self.w_tle(lambda: self.klient.zapytaj('GET', '/log', limit_s=5), gotowe)

        self._etykieta(gora, 'Ostatnie 500 linii logu usługi', 10, 'bold').pack(side='left')
        self.ttk.Button(gora, text='Odśwież', command=wczytaj).pack(side='right')
        wczytaj()

    # --- zakładka Konfiguracja ---
    def _zbuduj_konfiguracje(self):
        tk, ttk = self.tk, self.ttk
        f = self.zakladka_konf
        self.pola = {}

        def pole(rodzic, wiersz, kol, etykieta, klucz, szer=16):
            self._etykieta(rodzic, etykieta, 9, kolor=SZARY).grid(row=wiersz, column=kol, sticky='w',
                                                                  padx=(0, 6), pady=2)
            zmienna = tk.StringVar()
            e = ttk.Entry(rodzic, textvariable=zmienna, width=szer, font=(PISMO, 10))
            e.grid(row=wiersz, column=kol + 1, sticky='w', padx=(0, 14), pady=2)
            zmienna.trace_add('write', lambda *_: setattr(self, 'edytowana', True))
            self.pola[klucz] = zmienna

        for nazwa, (k1, opis1), (k2, opis2) in (
                ('etykiety', ('lt', 'Przesunięcie LT'), ('ls', 'LS')),
                ('wysylka', ('dx', 'Przesunięcie X'), ('dy', 'Y'))):
            ramka = ttk.LabelFrame(f, text=NAZWY[nazwa], padding=8)
            ramka.pack(fill='x', pady=(0, 8))
            uzywana = tk.BooleanVar()
            uzywana.trace_add('write', lambda *_: setattr(self, 'edytowana', True))
            ttk.Checkbutton(ramka, text='Drukarka podłączona do tego agenta', variable=uzywana).grid(
                row=0, column=0, columnspan=4, sticky='w', pady=(0, 4))
            self.pola[(nazwa, 'uzywana')] = uzywana
            pole(ramka, 1, 0, 'Adres IP', (nazwa, 'ip'))
            pole(ramka, 1, 2, 'Port', (nazwa, 'port'), 7)
            pole(ramka, 2, 0, 'Model', (nazwa, 'model'))
            pole(ramka, 2, 2, 'Limit wysyłki (s)', (nazwa, 'limit_wysylki_s'), 7)
            snmp = tk.BooleanVar()
            snmp.trace_add('write', lambda *_: setattr(self, 'edytowana', True))
            ttk.Checkbutton(ramka, text='Odczyt stanu przez SNMP', variable=snmp).grid(
                row=3, column=0, columnspan=2, sticky='w', pady=2)
            self.pola[(nazwa, 'snmp')] = snmp
            pole(ramka, 4, 0, opis1, ('przes', nazwa, k1), 7)
            pole(ramka, 4, 2, opis2, ('przes', nazwa, k2), 7)
            if nazwa == 'wysylka':
                self._etykieta(ramka, 'Przesunięcie w punktach drukarki: 8 punktów = 1 mm.', 9,
                               kolor=SZARY).grid(row=5, column=0, columnspan=4, sticky='w')

        ramka = ttk.LabelFrame(f, text='Godziny pracy agenta', padding=8)
        ramka.pack(fill='x', pady=(0, 8))
        pole(ramka, 0, 0, 'Pn–pt od', ('godziny', 'pn_pt', 0), 7)
        pole(ramka, 0, 2, 'do', ('godziny', 'pn_pt', 1), 7)
        pole(ramka, 1, 0, 'Sobota od', ('godziny', 'sobota', 0), 7)
        pole(ramka, 1, 2, 'do', ('godziny', 'sobota', 1), 7)
        self._etykieta(ramka, 'W niedzielę agent nie drukuje.', 9, kolor=SZARY).grid(
            row=2, column=0, columnspan=4, sticky='w')

        dol = tk.Frame(f, bg=TLO)
        dol.pack(fill='x', pady=(4, 0))
        ttk.Button(dol, text='Zapisz konfigurację', command=self._zapisz_konfiguracje).pack(side='left')
        ttk.Button(dol, text='Wczytaj z usługi', command=self._wczytaj_konfiguracje).pack(
            side='left', padx=6)
        self.wynik_konf = self._etykieta(f, '', 10, wraplength=480)
        self.wynik_konf.pack(fill='x', pady=(8, 0))

    def _wczytaj_konfiguracje(self):
        self.edytowana = False
        self.w_tle(lambda: self.klient.zapytaj('GET', '/konfiguracja'), self._po_konfiguracji)

    def _po_konfiguracji(self, wynik, blad):
        if blad is not None or wynik[0] != 200 or not isinstance(wynik[1], dict):
            self.wynik_konf.configure(text=opis_bledu(blad), fg=POZIOMY['awaria'][0])
            return
        odp = wynik[1]
        self.konfiguracja = odp.get('dane') or {}
        self.ip_drukarek = {d.get('nazwa'): d.get('ip') for d in self.konfiguracja.get('drukarki') or []
                            if isinstance(d, dict)}
        if self.edytowana:   # nie nadpisujemy tego, co ktoś właśnie wpisuje
            return
        self._wypelnij_formularz(self.konfiguracja)
        self.edytowana = False
        if odp.get('blad_konfiguracji'):
            self.wynik_konf.configure(text='CRM odrzucił ostatnią zmianę: '
                                      + '; '.join(odp['blad_konfiguracji']), fg=POZIOMY['awaria'][0])
        elif odp.get('oczekujaca'):
            self.wynik_konf.configure(text='Zmiana czeka na wysłanie do CRM.', fg=POZIOMY['uwaga'][0])
        else:
            self.wynik_konf.configure(text='Konfiguracja zgodna z CRM (wersja %s).' % odp.get('wersja'),
                                      fg=SZARY)

    def _wypelnij_formularz(self, dane):
        drukarki = {d.get('nazwa'): d for d in dane.get('drukarki') or [] if isinstance(d, dict)}
        domyslne = {'etykiety': ('XP-423B', True, 10), 'wysylka': ('XP-410B', False, 30)}
        for nazwa, (model, snmp, limit) in domyslne.items():
            d = drukarki.get(nazwa)
            self.pola[(nazwa, 'uzywana')].set(d is not None)
            d = d or {}
            self.pola[(nazwa, 'ip')].set(d.get('ip', ''))
            self.pola[(nazwa, 'port')].set(str(d.get('port', 9100)))
            self.pola[(nazwa, 'model')].set(d.get('model', model))
            self.pola[(nazwa, 'limit_wysylki_s')].set(str(d.get('limit_wysylki_s', limit)))
            self.pola[(nazwa, 'snmp')].set(d.get('odczyt_stanu', 'snmp' if snmp else 'brak') == 'snmp')
        przes = dane.get('przesuniecia') or {}
        for nazwa, klucze in lokalne_api.KLUCZE_PRZESUNIEC.items():
            for k in klucze:
                self.pola[('przes', nazwa, k)].set(str((przes.get(nazwa) or {}).get(k, 0)))
        godziny = dane.get('godziny') or {}
        for dzien in ('pn_pt', 'sobota'):
            para = godziny.get(dzien) or ['', '']
            for i in (0, 1):
                self.pola[('godziny', dzien, i)].set(para[i] if len(para) > i else '')

    def _z_formularza(self):
        """(dane, błędy) — dokument w kształcie serwera; nieznane klucze z wczytanej wersji zostają."""
        bledy = []

        def liczba(klucz, opis):
            tekst = self.pola[klucz].get().strip()
            try:
                return int(tekst)
            except ValueError:
                bledy.append('%s: wpisz liczbę całkowitą' % opis)
                return 0

        dane = json.loads(json.dumps(self.konfiguracja or {}))
        drukarki = []
        for nazwa in ('etykiety', 'wysylka'):
            if not self.pola[(nazwa, 'uzywana')].get():
                continue
            drukarki.append({
                'nazwa': nazwa,
                'ip': self.pola[(nazwa, 'ip')].get().strip(),
                'port': liczba((nazwa, 'port'), '%s: port' % NAZWY[nazwa]),
                'model': self.pola[(nazwa, 'model')].get().strip(),
                'odczyt_stanu': 'snmp' if self.pola[(nazwa, 'snmp')].get() else 'brak',
                'limit_wysylki_s': liczba((nazwa, 'limit_wysylki_s'), '%s: limit wysyłki' % NAZWY[nazwa]),
            })
        dane['drukarki'] = drukarki
        dane['przesuniecia'] = {
            nazwa: {k: liczba(('przes', nazwa, k), '%s: przesunięcie %s' % (NAZWY[nazwa], k.upper()))
                    for k in klucze}
            for nazwa, klucze in lokalne_api.KLUCZE_PRZESUNIEC.items()}
        dane['godziny'] = {dzien: [self.pola[('godziny', dzien, i)].get().strip() for i in (0, 1)]
                           for dzien in ('pn_pt', 'sobota')}
        return dane, bledy

    def _zapisz_konfiguracje(self):
        dane, bledy = self._z_formularza()
        if bledy:
            self.wynik_konf.configure(text='; '.join(bledy), fg=POZIOMY['awaria'][0])
            return
        self.wynik_konf.configure(text='Zapisuję…', fg=SZARY)

        def gotowe(wynik, blad):
            if blad is not None:
                self.wynik_konf.configure(text=opis_bledu(blad), fg=POZIOMY['awaria'][0])
                return
            kod, cialo = wynik
            if kod == 200:
                self.edytowana = False
                self.konfiguracja = dane
                self.ip_drukarek = {d['nazwa']: d['ip'] for d in dane['drukarki']}
                self.wynik_konf.configure(
                    text='Zapisano. Agent używa jej od razu, a CRM dostanie ją przy najbliższej '
                         'synchronizacji.', fg=POZIOMY['ok'][0])
            else:
                self.wynik_konf.configure(text=_opis_odpowiedzi(kod, cialo, 'zapis nieudany'),
                                          fg=POZIOMY['awaria'][0])
        self.w_tle(lambda: self.klient.zapytaj('PUT', '/konfiguracja', {'dane': dane}), gotowe)

    # --- zakładka Parowanie ---
    def _zbuduj_parowanie(self):
        tk, ttk = self.tk, self.ttk
        f = self.zakladka_par
        self.stan_parowania = self._etykieta(f, '', 11, 'bold')
        self.stan_parowania.pack(fill='x', pady=(0, 8))
        self._etykieta(f, 'W CRM otwórz Produkcja → Stanowiska → Drukarki i kliknij „Dodaj agenta”. '
                          'Skopiuj token i wklej go poniżej — CRM pokazuje go tylko raz. Adres CRM '
                          'ustawił instalator; inny serwer wymaga ponownej instalacji agenta.',
                       10, kolor=SZARY, wraplength=480).pack(fill='x', pady=(0, 10))
        siatka = tk.Frame(f, bg=TLO)
        siatka.pack(fill='x')
        self.adres_crm = tk.StringVar()
        self.token = tk.StringVar()
        self._etykieta(siatka, 'Adres CRM').grid(row=0, column=0, sticky='w', pady=4, padx=(0, 8))
        ttk.Entry(siatka, textvariable=self.adres_crm, width=42, font=(PISMO, 10),
                  state='readonly').grid(
            row=0, column=1, sticky='we', pady=4)
        self._etykieta(siatka, 'Token agenta').grid(row=1, column=0, sticky='w', pady=4, padx=(0, 8))
        ttk.Entry(siatka, textvariable=self.token, width=42, show='•', font=(PISMO, 10)).grid(
            row=1, column=1, sticky='we', pady=4)
        ttk.Button(f, text='Sparuj z CRM', command=self._sparuj).pack(anchor='w', pady=(10, 0))
        self.wynik_par = self._etykieta(f, '', 10, wraplength=480)
        self.wynik_par.pack(fill='x', pady=(8, 0))

    def _rysuj_parowanie(self):
        s = self.stan or {}
        if s.get('sparowany'):
            self.stan_parowania.configure(text='Sparowany z %s' % (s.get('crm_url') or 'CRM'),
                                          fg=POZIOMY['ok'][0])
        else:
            self.stan_parowania.configure(text='Agent nie jest połączony z CRM', fg=POZIOMY['awaria'][0])
        if s.get('crm_url') and self.adres_crm.get() != s['crm_url']:
            self.adres_crm.set(s['crm_url'])

    def _sparuj(self):
        dane = {'token': self.token.get().strip()}
        self.wynik_par.configure(text='Zapisuję…', fg=SZARY)

        def gotowe(wynik, blad):
            if blad is not None:
                self.wynik_par.configure(text=opis_bledu(blad), fg=POZIOMY['awaria'][0])
                return
            kod, cialo = wynik
            self.wynik_par.configure(text=_opis_odpowiedzi(kod, cialo, 'parowanie nieudane'),
                                     fg=POZIOMY['ok' if kod == 200 else 'awaria'][0])
            if kod == 200:
                self.token.set('')
        self.w_tle(lambda: self.klient.zapytaj('POST', '/parowanie', dane), gotowe)


def _odlacz_konsole():
    """AgentDruku.exe jest programem konsolowym (usługa dostaje Ctrl+C od WinSW). Ikona uruchomiona
    z autostartu dostaje własne okno konsoli — odłączamy je, gdy nikt inny go nie używa."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        procesy = (ctypes.c_uint32 * 4)()
        if kernel32.GetConsoleProcessList(procesy, 4) == 1:
            kernel32.FreeConsole()
    except Exception:  # noqa: BLE001 — poza Windows albo bez konsoli
        pass


def main():
    if getattr(sys, 'frozen', False):
        _odlacz_konsole()
    try:  # ostre pismo na ekranach ze skalowaniem
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 — poza Windows albo starszy system
        pass
    Zasobnik(KlientLokalny()).main()
    return 0
