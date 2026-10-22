"""Kodowanie GET i dekodowanie odpowiedzi SNMP v1 (agent druku v2)."""
import socket
import types

import pytest

from agent_druku import snmp


def _odpowiedz(req_id, tag, wartosc, oid='1.3.6.1.2.1.25.3.5.1.1.1', blad=0):
    """Odpowiedź GetResponse jak od drukarki."""
    varbind = snmp._tlv(0x30, snmp._oid(oid) + snmp._tlv(tag, wartosc))
    pdu = snmp._tlv(0xa2, snmp._int(req_id) + snmp._int(blad) + snmp._int(0)
                    + snmp._tlv(0x30, varbind))
    return snmp._tlv(0x30, snmp._int(0) + snmp._tlv(0x04, b'public') + pdu)


def test_kodowanie_get_dokladnie():
    # Wzorzec policzony ręcznie: sysDescr.0, id żądania 1.
    oczekiwane = bytes.fromhex(
        '30260201000406' + '7075626c6963'     # SEQUENCE, wersja 0, społeczność „public”
        + 'a019020101020100020100'
        + '300e300c06082b060102010101000500')
    assert snmp._snmp_get('1.3.6.1.2.1.1.1.0', 1) == oczekiwane


def test_oid_z_dlugim_czlonem():
    # 311 = 0x137 -> 0x82 0x37 (base-128)
    assert snmp._oid('1.3.311') == bytes.fromhex('06032b8237')


def test_dekodowanie_counter32():
    assert snmp._wartosc_snmp(_odpowiedz(7, 0x41, b'\x01\x00')) == (7, 256)


def test_dekodowanie_integer_ze_znakiem():
    assert snmp._wartosc_snmp(_odpowiedz(1, 0x02, b'\xff')) == (1, -1)


def test_dekodowanie_octet_string():
    assert snmp._wartosc_snmp(_odpowiedz(2, 0x04, b'Online')) == (2, b'Online')


def test_dekodowanie_no_such_object():
    assert snmp._wartosc_snmp(_odpowiedz(3, 0x80, b'')) == (3, None)
    assert snmp._wartosc_snmp(_odpowiedz(3, 0x81, b'')) == (3, None)
    assert snmp._wartosc_snmp(_odpowiedz(3, 0x82, b'')) == (3, None)


def test_dekodowanie_bledu_snmp_to_none():
    assert snmp._wartosc_snmp(_odpowiedz(4, 0x05, b'', blad=2)) == (4, None)


def test_dekodowanie_smieci_rzuca_value_error():
    with pytest.raises(ValueError):
        snmp._wartosc_snmp(b'\x30\x05\x02')


class _GniazdoUdp:
    """Atrapa UDP: na każde sendto odpowiada kolejnym elementem skryptu
    (bytes = odpowiedź, None = cisza -> timeout)."""
    def __init__(self, skrypt, poczatkowa_kolejka=()):
        self.skrypt = list(skrypt)
        self.wyslane = []
        self.zamkniete = False
        self._kolejka = list(poczatkowa_kolejka)

    def settimeout(self, t):
        pass

    def sendto(self, dane, adres):
        self.wyslane.append((dane, adres))
        if self.skrypt:
            odp = self.skrypt.pop(0)
            if odp is not None:
                self._kolejka.append(odp)

    def recvfrom(self, n):
        if not self._kolejka:
            raise socket.timeout('timed out')
        return self._kolejka.pop(0), ('10.0.0.1', 161)

    def close(self):
        self.zamkniete = True


def _podstaw(monkeypatch, gniazdo):
    monkeypatch.setattr(snmp, 'socket', types.SimpleNamespace(
        socket=lambda *a: gniazdo, AF_INET=socket.AF_INET, SOCK_DGRAM=socket.SOCK_DGRAM))


def test_pobierz_zwraca_typowane_wartosci(monkeypatch):
    g = _GniazdoUdp([_odpowiedz(1, 0x02, b'\x03'), _odpowiedz(2, 0x04, b'\x00'),
                     _odpowiedz(3, 0x80, b'')])
    _podstaw(monkeypatch, g)
    wynik = snmp.pobierz('10.0.0.1', ['1.3.6.1.2.1.1.1', '1.3.6.1.2.1.1.2', '1.3.6.1.2.1.1.3'])
    assert wynik == {'1.3.6.1.2.1.1.1': 3, '1.3.6.1.2.1.1.2': b'\x00', '1.3.6.1.2.1.1.3': None}
    assert g.wyslane[0][1] == ('10.0.0.1', 161)
    assert g.zamkniete


def test_pobierz_cisza_to_pusty_slownik_i_jedno_zapytanie(monkeypatch):
    g = _GniazdoUdp([None, None, None])
    _podstaw(monkeypatch, g)
    assert snmp.pobierz('10.0.0.1', ['1.3.6.1.2.1.1.1', '1.3.6.1.2.1.1.2']) == {}
    assert len(g.wyslane) == 1          # po pierwszej ciszy nie czekamy na kolejne OID-y
    assert g.zamkniete


def test_pobierz_pomija_smieci_i_cudze_id(monkeypatch):
    # W kolejce: spóźniona odpowiedź z innego żądania i śmieć; potem prawdziwa odpowiedź.
    g = _GniazdoUdp([_odpowiedz(1, 0x02, b'\x05')],
                    poczatkowa_kolejka=[_odpowiedz(99, 0x02, b'\x09'), b'\x30\x02\x02\x00'])
    _podstaw(monkeypatch, g)
    assert snmp.pobierz('10.0.0.1', ['1.3.6.1.2.1.1.1']) == {'1.3.6.1.2.1.1.1': 5}
