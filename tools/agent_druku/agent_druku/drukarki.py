"""Drukarki: transport surowych bajtów (port 9100) z budzeniem oraz odczyt stanu.

Stan z SNMP ma tylko XP-423B (`odczyt_stanu="snmp"`). XP-410B nie odpowiada na SNMP
(`"brak"`) — jej stan to wynik ostatniej próby połączenia.

Drukarka to słownik z dokumentu konfiguracji serwera:
  {"nazwa": "etykiety"|"wysylka", "ip": str, "port": int, "model": str,
   "odczyt_stanu": "snmp"|"brak", "limit_wysylki_s": int}
"""
import socket
import threading
import time

from agent_druku import snmp

# Budzenie drukarki. XP-410B usypia moduł sieciowy po bezczynności: pierwsze połączenie
# po przerwie kończy się timeoutem, następne przechodzą od razu (diagnoza 22.10.2026).
# Łączymy się więc kilka razy krótkimi próbami, zanim uznamy drukarkę za niedostępną.
BUDZENIE_PROBA_S = 3
BUDZENIE_ODSTEP_S = 1
BUDZENIE_LIMIT_S = 20

# Po ostatnim bajcie czekamy na zamknięcie połączenia przez drukarkę — to znak, że
# przyjęła wszystko (zamknięcie od razu po sendall potrafiło ucinać końcówkę etykiety).
CZEKANIE_NA_ZAMKNIECIE_S = 3

BLAD_ZAMKNIECIA = 'drukarka zerwała połączenie po wysłaniu — sprawdź, czy etykiety wyszły'

KOMENDA_KALIBRACJI = b'GAPDETECT\r\n'

# Stany zwracane przez stan().
GOTOWA = 'gotowa'
OFFLINE = 'offline'
BRAK_PAPIERU = 'brak_papieru'
OTWARTA_KLAPA = 'otwarta_klapa'
BLAD = 'blad'
NIEZNANY = 'nieznany'

OID_STATUS = '1.3.6.1.2.1.25.3.5.1.1.1'          # hrPrinterStatus
OID_BLEDY = '1.3.6.1.2.1.25.3.5.1.2.1'           # hrPrinterDetectedErrorState
OID_KONSOLA = '1.3.6.1.2.1.43.16.5.1.2.1.1'      # prtConsoleDisplayBufferText

# hrPrinterDetectedErrorState, bajt 0 (maski wartości bitów wg RFC 2790).
_BIT_MALO_PAPIERU = 0x80
_BIT_BRAK_PAPIERU = 0x40
_BIT_KLAPA = 0x08
_BIT_ZACIECIE = 0x04
_BIT_OFFLINE = 0x02

# Ostatni wynik połączenia na nazwę drukarki: True (połączono) / False (nie).
_ostatnie_polaczenie = {}

# Jedna wysyłka naraz na drukarkę: wydruk próbny i kalibracja z okienka czekają na trwającą
# porcję (inaczej bajty dwóch połączeń przeplatałyby się na tej samej drukarce).
_blokady_drukarek = {}
_blokada_slownika = threading.Lock()


def blokada_drukarki(nazwa):
    with _blokada_slownika:
        return _blokady_drukarek.setdefault(nazwa, threading.Lock())


class DrukarkaNiedostepna(OSError):
    """Nie udało się nawiązać połączenia z drukarką — nie wysłano ANI BAJTU.
    To nie porażka zadania: wraca ono do kolejki zamiast przepaść jako błąd."""


def _polacz_z_budzeniem(drukarka):
    nazwa = drukarka.get('nazwa', '?')
    koniec = time.monotonic() + BUDZENIE_LIMIT_S
    proba = 0
    while True:
        proba += 1
        try:
            sock = socket.create_connection((drukarka['ip'], drukarka['port']),
                                            timeout=BUDZENIE_PROBA_S)
        except OSError as e:
            if time.monotonic() + BUDZENIE_ODSTEP_S >= koniec:
                _ostatnie_polaczenie[nazwa] = False
                raise DrukarkaNiedostepna(
                    f'drukarka nie odpowiada na połączenie ({proba} prób w {BUDZENIE_LIMIT_S} s): {e}') from e
            time.sleep(BUDZENIE_ODSTEP_S)
            continue
        _ostatnie_polaczenie[nazwa] = True
        return sock


def _zamknij_po_wyslaniu(sock):
    """shutdown(SHUT_WR) i czekanie (do 3 s) aż drukarka zamknie połączenie.
    Zwraca True, gdy zamknięcie było czyste: drukarka zamknęła połączenie (EOF) albo
    przez 3 s milczała bez błędu. Reset połączenia albo inny błąd gniazda w tej fazie
    to False — sendall samo nie dowodzi, że drukarka odebrała dane."""
    try:
        sock.shutdown(socket.SHUT_WR)
        koniec = time.monotonic() + CZEKANIE_NA_ZAMKNIECIE_S
        while True:
            zostalo = koniec - time.monotonic()
            if zostalo <= 0:
                return True
            sock.settimeout(zostalo)
            if not sock.recv(4096):
                return True
    except TimeoutError:
        return True
    except OSError:
        return False


def wyslij_porcje(drukarka, zadania, przed_wyslaniem):
    """Wysyła zadania jednym połączeniem. Zwraca listę {"id", "wynik"[, "blad"]},
    po jednym wpisie na zadanie, w kolejności wejścia.

    wynik: "wydrukowane" (dane w całości przyjęte), "blad" (połączenie padło w trakcie
    wysyłki tego zadania) albo "niewyslane" (nic nie poszło: brak połączenia, wcześniejszy
    błąd w porcji albo przed_wyslaniem odmówiło).
    przed_wyslaniem(id) zgłasza serwerowi „wysylam”; False = pomiń to zadanie.
    Trzyma blokadę drukarki przez całą porcję."""
    with blokada_drukarki(drukarka.get('nazwa', '?')):
        return _wyslij_porcje(drukarka, zadania, przed_wyslaniem)


def _wyslij_porcje(drukarka, zadania, przed_wyslaniem):
    wyniki = []
    try:
        sock = _polacz_z_budzeniem(drukarka)
    except DrukarkaNiedostepna:
        return [{'id': z['id'], 'wynik': 'niewyslane'} for z in zadania]
    with sock:
        sock.settimeout(drukarka['limit_wysylki_s'])
        przerwane = False
        for z in zadania:
            if przerwane:
                wyniki.append({'id': z['id'], 'wynik': 'niewyslane'})
                continue
            try:
                zgoda = przed_wyslaniem(z['id'])
            except Exception:
                # Nie wiadomo, czy serwer przyjął zgłoszenie — nie drukujemy ani tego,
                # ani reszty (serwer i tak zwróci je do kolejki).
                przerwane = True
                wyniki.append({'id': z['id'], 'wynik': 'niewyslane'})
                continue
            if not zgoda:
                wyniki.append({'id': z['id'], 'wynik': 'niewyslane'})
                continue
            try:
                sock.sendall(z['zpl'].encode('utf-8'))
            except OSError as e:
                przerwane = True
                _ostatnie_polaczenie[drukarka.get('nazwa', '?')] = False
                wyniki.append({'id': z['id'], 'wynik': 'blad', 'blad': str(e) or e.__class__.__name__})
                continue
            wyniki.append({'id': z['id'], 'wynik': 'wydrukowane'})
        if not przerwane and not _zamknij_po_wyslaniu(sock):
            _ostatnie_polaczenie[drukarka.get('nazwa', '?')] = False
            for w in wyniki:
                if w['wynik'] == 'wydrukowane':
                    w['wynik'] = 'blad'
                    w['blad'] = BLAD_ZAMKNIECIA
    return wyniki


def kalibruj(drukarka):
    """Kalibracja czujnika przerwy (TSPL GAPDETECT) — drukarka przewija kilka pustych
    etykiet i zapamiętuje, gdzie zaczyna się etykieta. Błędy (OSError, w tym
    DrukarkaNiedostepna) idą do wołającego. Czeka na trwającą wysyłkę do tej drukarki."""
    with blokada_drukarki(drukarka.get('nazwa', '?')), _polacz_z_budzeniem(drukarka) as sock:
        sock.settimeout(drukarka['limit_wysylki_s'])
        sock.sendall(KOMENDA_KALIBRACJI)
        _zamknij_po_wyslaniu(sock)


def _tekst(wartosc):
    if isinstance(wartosc, (bytes, bytearray)):
        return bytes(wartosc).decode('utf-8', 'replace').strip('\x00 \r\n\t')
    return ''


def stan(drukarka):
    """(stan, opis). Stany: gotowa, offline, brak_papieru, otwarta_klapa, blad, nieznany."""
    if drukarka.get('odczyt_stanu') != 'snmp':
        wynik = _ostatnie_polaczenie.get(drukarka.get('nazwa'))
        if wynik is None:
            return NIEZNANY, 'brak próby połączenia'
        if wynik:
            return GOTOWA, 'ostatnie połączenie udane'
        return OFFLINE, 'ostatnie połączenie nieudane'

    odp = snmp.pobierz(drukarka['ip'], [OID_STATUS, OID_BLEDY, OID_KONSOLA])
    status, bledy, konsola = odp.get(OID_STATUS), odp.get(OID_BLEDY), odp.get(OID_KONSOLA)
    if status is None and not bledy and not konsola:
        return NIEZNANY, 'brak odpowiedzi SNMP'
    opis = _tekst(konsola)

    bajt = bledy[0] if isinstance(bledy, (bytes, bytearray)) and len(bledy) else 0
    if bajt & _BIT_BRAK_PAPIERU:
        return BRAK_PAPIERU, opis or 'brak papieru'
    if bajt & _BIT_KLAPA:
        return OTWARTA_KLAPA, opis or 'otwarta klapa'
    if bajt & _BIT_ZACIECIE:
        return BLAD, opis or 'zacięcie'
    if bajt & _BIT_OFFLINE:
        return OFFLINE, opis or 'drukarka offline'
    # Mało papieru nie zmienia stanu — wpada tylko do opisu.
    if bajt & _BIT_MALO_PAPIERU:
        opis = f'{opis}; mało papieru' if opis else 'mało papieru'

    if status == 1:
        return BLAD, opis or 'drukarka zgłasza stan „inny”'
    if status == 2:
        return NIEZNANY, opis or 'stan nieznany'
    return GOTOWA, opis   # 3 (idle), 4 (printing), 5 (warmup) i brak statusu


# --- Etykieta próbna ---
# Te same wzory co modules/production/services/print_queue_service.zpl_probny (etykiety 60x40)
# i package_label.generate_test_label_zpl (paczki 100x150); zgodność pilnuje test.
_PACZKA_SZEROKOSC = 800
_PACZKA_WYSOKOSC = 1200
_PACZKA_MARGINES = 24
_PACZKA_PREDKOSC = 3


def _zpl_probny_etykiet(offset_lt, offset_ls):
    x = offset_ls
    return (
        '^XA\n^PW480\n^LL320\n^LT%d\n^LS0\n^CI0\n' % offset_lt
        + '^FO%d,0^GB480,320,4^FS\n' % x
        + '^FO%d,40^A0N,40,40^FDWYDRUK PROBNY^FS\n' % (x + 20)
        + '^FO%d,100^A0N,26,26^FDDrukarka etykiet 60x40^FS\n' % (x + 20)
        + '^FO%d,140^A0N,22,22^FDLT=%d LS=%d^FS\n' % (x + 20, offset_lt, offset_ls)
        + '^FO%d,190^BQN,2,4^FDLA,TEST^FS\n' % (x + 20)
        + '^XZ\n'
    )


def _zpl_probny_paczek(dx, dy):
    linie = ['^XA', '^PR%d' % _PACZKA_PREDKOSC, '^CI0',
             '^PW%d' % _PACZKA_SZEROKOSC, '^LL%d' % _PACZKA_WYSOKOSC, '^LH0,0']

    def pole(x, y, tresc):
        linie.append('^FO%d,%d%s' % (max(0, x + dx), max(0, y + dy), tresc))

    pole(_PACZKA_MARGINES, _PACZKA_MARGINES,
         '^GB%d,%d,4^FS' % (_PACZKA_SZEROKOSC - 2 * _PACZKA_MARGINES,
                            _PACZKA_WYSOKOSC - 2 * _PACZKA_MARGINES))
    pole(60, 80, '^A0N,64,60^FDWYDRUK PROBNY^FS')
    pole(60, 160, '^A0N,36,34^FDDrukarka paczek 100x150^FS')
    pole(60, 230, '^A0N,30,28^FDRamka: 3 mm od kazdej krawedzi.^FS')
    pole(60, 270, '^A0N,30,28^FDNierowno? Popraw przesuniecie w panelu^FS')
    pole(60, 310, '^A0N,30,28^FD(8 punktow = 1 mm) i drukuj ponownie.^FS')
    pole(60, 370, '^A0N,30,28^FDPrzesuniecie teraz: X=%d, Y=%d^FS' % (dx, dy))
    pole(60, 440, '^BQN,2,11^FDLA,P-TEST^FS')
    pole(60, 1100, '^A0N,28,28^FDDol tresci (y=1100)^FS')
    return '\n'.join(linie + ['^XZ']) + '\n'


def _liczba(przesuniecia, klucz):
    try:
        return int(przesuniecia[klucz])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f'brak przesunięcia „{klucz}” w konfiguracji drukarki') from None


def zpl_probny(nazwa, przesuniecia):
    """ZPL etykiety próbnej z lokalnymi przesunięciami w kształcie z dokumentu konfiguracji
    serwera: etykiety {"lt": int, "ls": int}, wysylka {"dx": int, "dy": int}.
    Brakujący klucz to ValueError (nie drukujemy po cichu z zerami)."""
    if nazwa == 'etykiety':
        return _zpl_probny_etykiet(_liczba(przesuniecia, 'lt'), _liczba(przesuniecia, 'ls'))
    if nazwa == 'wysylka':
        return _zpl_probny_paczek(_liczba(przesuniecia, 'dx'), _liczba(przesuniecia, 'dy'))
    raise ValueError(f'nieznana drukarka: {nazwa!r}')
