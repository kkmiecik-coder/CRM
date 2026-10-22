"""Minimalny klient SNMP v1 (GET) — BER ręcznie, bez bibliotek.

Przeniesiony z narzędzia diagnostycznego i sprawdzony na prawdziwej drukarce XP-423B
(społeczność „public”). XP-410B w ogóle nie odpowiada na SNMP — wtedy pobierz() zwraca
pusty słownik, a wołający traktuje to jako „brak odczytu”.

Wartości w wyniku:
  int    — INTEGER, Counter32, Gauge32, TimeTicks, Counter64,
  bytes  — OCTET STRING (i nieznane typy, surowo),
  None   — noSuchObject / noSuchInstance / endOfMibView albo błąd SNMP dla tego OID.
OID, na który drukarka nie odpowiedziała w limicie czasu, nie występuje w słowniku.
"""
import socket
import time

PORT_SNMP = 161
SPOLECZNOSC = b'public'

# Znaczniki BER używane w odpowiedziach GET.
_INTEGER = 0x02
_OCTET_STRING = 0x04
_SEKWENCJA = 0x30
_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64 = 0x41, 0x42, 0x43, 0x46
_BRAK_WARTOSCI = (0x80, 0x81, 0x82)   # noSuchObject, noSuchInstance, endOfMibView
_ZAPYTANIE_GET = 0xa0


def _dl(n):
    """Długość BER: krótka (< 128) albo długa (bajt 0x8N + N bajtów)."""
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(b)]) + b


def _tlv(t, v):
    return bytes([t]) + _dl(len(v)) + v


def _int(n):
    return _tlv(_INTEGER, n.to_bytes(max(1, (n.bit_length() + 8) // 8), 'big', signed=True))


def _oid(tekst):
    """OID z zapisu kropkowego; pierwsze dwa człony w jednym bajcie, reszta base-128."""
    cz = [int(x) for x in tekst.split('.')]
    out = bytes([cz[0] * 40 + cz[1]])
    for c in cz[2:]:
        kaw = [c & 0x7f]
        c >>= 7
        while c:
            kaw.insert(0, 0x80 | (c & 0x7f))
            c >>= 7
        out += bytes(kaw)
    return _tlv(0x06, out)


def _snmp_get(oid, req_id):
    """Datagram SNMP v1 GetRequest dla jednego OID."""
    varbind = _tlv(_SEKWENCJA, _oid(oid) + b'\x05\x00')
    pdu = _tlv(_ZAPYTANIE_GET, _int(req_id) + _int(0) + _int(0) + _tlv(_SEKWENCJA, varbind))
    return _tlv(_SEKWENCJA, _int(0) + _tlv(_OCTET_STRING, SPOLECZNOSC) + pdu)


def _czytaj(dane, i):
    """Jeden element TLV od pozycji i: (znacznik, zawartość, pozycja za elementem)."""
    t = dane[i]
    n = dane[i + 1]
    i += 2
    if n & 0x80:
        ile = n & 0x7f
        n = int.from_bytes(dane[i:i + ile], 'big')
        i += ile
    if i + n > len(dane):
        raise ValueError('ucięty element BER')
    return t, dane[i:i + n], i + n


def _wartosc_snmp(odp):
    """Odpowiedź GET -> (id żądania, wartość). Rzuca ValueError przy śmieciach."""
    try:
        _, msg, _ = _czytaj(odp, 0)
        _, _, i = _czytaj(msg, 0)           # wersja
        _, _, i = _czytaj(msg, i)           # społeczność
        _, pdu, _ = _czytaj(msg, i)
        _, rid, j = _czytaj(pdu, 0)         # id żądania
        _, err, j = _czytaj(pdu, j)         # error-status
        _, _, j = _czytaj(pdu, j)           # error-index
        _, vbl, _ = _czytaj(pdu, j)
        _, vb, _ = _czytaj(vbl, 0)
        _, _, k = _czytaj(vb, 0)            # OID
        t, v, _ = _czytaj(vb, k)
    except (IndexError, ValueError) as e:
        raise ValueError('nieczytelna odpowiedź SNMP') from e
    req_id = int.from_bytes(rid, 'big', signed=True)
    if int.from_bytes(err, 'big'):
        return req_id, None
    if t == _INTEGER:
        return req_id, int.from_bytes(v, 'big', signed=True)
    if t in (_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64):
        return req_id, int.from_bytes(v, 'big')
    if t in _BRAK_WARTOSCI:
        return req_id, None
    return req_id, bytes(v)


def pobierz(ip, oidy, limit_s=2):
    """GET kilku OID-ów po kolei jednym gniazdem UDP. limit_s to łączny budżet czasu.
    Pierwszy brak odpowiedzi kończy odpytywanie (drukarka milczy — nie ma sensu czekać
    limitu na każdy OID z osobna); brakujące OID-y nie trafiają do wyniku."""
    wynik = {}
    koniec = time.monotonic() + limit_s
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for nr, oid in enumerate(oidy, 1):
            try:
                s.sendto(_snmp_get(oid, nr), (ip, PORT_SNMP))
                while True:
                    zostalo = koniec - time.monotonic()
                    if zostalo <= 0:
                        return wynik
                    s.settimeout(zostalo)
                    odp, _ = s.recvfrom(4096)
                    try:
                        rid, wartosc = _wartosc_snmp(odp)
                    except ValueError:
                        continue                    # śmieć w sieci — czekamy dalej
                    if rid == nr:
                        wynik[oid] = wartosc
                        break
                    # inne id (spóźniona odpowiedź na wcześniejsze żądanie) — czekamy dalej
            except OSError:
                return wynik                        # timeout albo błąd sieci
    finally:
        s.close()
    return wynik
