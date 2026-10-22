"""Logika zasobnika bez GUI: duży komunikat i kolor ikony (pystray/tkinter nie są importowane)."""
import sys

import pytest

from agent_druku import zasobnik


def _stan(**pola):
    stan = {'ogolny': 'ok', 'komunikat': '', 'crm': True, 'push': True, 'sparowany': True,
            'drukarki': [{'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': '', 'obsluga': 'nowy'}],
            'blad_konfiguracji': None}
    stan.update(pola)
    return stan


def test_import_bez_gui():
    assert 'pystray' not in sys.modules and 'tkinter' not in sys.modules


def test_opis_glowny_trzy_poziomy():
    assert zasobnik.opis_glowny(_stan())[:2] == ('ok', 'Wszystko działa')
    poziom, tytul, szczegol = zasobnik.opis_glowny(_stan(ogolny='uwaga', drukarki=[
        {'nazwa': 'etykiety', 'stan': 'gotowa', 'opis': '', 'obsluga': 'nowy'},
        {'nazwa': 'wysylka', 'stan': 'brak_papieru', 'opis': '', 'obsluga': 'nowy'}]))
    assert (poziom, tytul) == ('uwaga', 'Paczki: brak etykiet') and 'rolkę' in szczegol
    assert zasobnik.opis_glowny(_stan(ogolny='awaria', crm=False))[:2] == (
        'awaria', 'Brak połączenia z CRM')
    assert zasobnik.opis_glowny(_stan(ogolny='awaria', sparowany=False))[0] == 'awaria'
    assert zasobnik.opis_glowny(None)[:2] == ('awaria', zasobnik.USLUGA_NIE_DZIALA)


def test_drukarka_starego_agenta_nie_jest_problemem():
    stan = _stan(ogolny='uwaga', blad_konfiguracji=['zły adres IP'], drukarki=[
        {'nazwa': 'wysylka', 'stan': 'nieznany', 'opis': '', 'obsluga': 'stary'}])
    assert zasobnik.opis_glowny(stan)[:2] == ('uwaga', 'CRM nie przyjął konfiguracji')


def test_cisza_uslugi_dluzej_niz_10_s_daje_czerwona():
    assert zasobnik.poziom_ikony(None, ostatnia_odpowiedz=100.0, teraz=105.0, start=0.0) is None
    assert zasobnik.poziom_ikony(None, ostatnia_odpowiedz=100.0, teraz=110.5, start=0.0) == 'awaria'
    assert zasobnik.poziom_ikony(None, ostatnia_odpowiedz=None, teraz=11.0, start=0.0) == 'awaria'
    assert zasobnik.poziom_ikony(_stan(), 100.0, 200.0, 0.0) == 'ok'


def test_klient_bez_pliku_klucza(tmp_path):
    klient = zasobnik.KlientLokalny(port=9, plik_klucza=tmp_path / 'klucz_lokalny')
    with pytest.raises(zasobnik.BladKluczaZasobnika) as e:
        klient.zapytaj('GET', '/stan')
    assert not isinstance(e.value, OSError)
    assert e.value.szczegol.startswith('Brak klucza usługi — usługa nie wystartowała')
    assert 'Uruchom komputer' not in e.value.szczegol

    (tmp_path / 'klucz_lokalny').write_text('', encoding='ascii')
    with pytest.raises(zasobnik.BladKluczaZasobnika):
        klient.zapytaj('GET', '/stan')


def test_klient_bez_uprawnien_do_klucza(tmp_path, monkeypatch):
    plik = tmp_path / 'klucz_lokalny'

    def brak_uprawnien(sciezka=None):
        raise PermissionError(13, 'Odmowa dostępu', str(sciezka))

    monkeypatch.setattr(zasobnik.lokalne_api, 'wczytaj_klucz', brak_uprawnien)
    with pytest.raises(zasobnik.BladKluczaZasobnika) as e:
        zasobnik.KlientLokalny(port=9, plik_klucza=plik).zapytaj('GET', '/stan')
    assert 'brak uprawnień do %s' % plik in e.value.szczegol
    assert 'zadzwoń do biura' in e.value.szczegol
    assert zasobnik.opis_bledu(e.value) == e.value.szczegol
    assert zasobnik.opis_bledu(OSError('x')) == zasobnik.USLUGA_NIE_ODPOWIADA


def test_menu_tylko_drukarki_tego_agenta():
    stan = _stan(drukarki=[{'nazwa': 'etykiety', 'stan': 'gotowa', 'obsluga': 'nowy'},
                           {'nazwa': 'wysylka', 'stan': 'nieznany', 'obsluga': 'stary'}])
    assert zasobnik.drukarki_tego_agenta(stan) == ['etykiety']


def test_pasek_aktualizacji_pokazuje_postep():
    assert zasobnik.opis_aktualizacji(None) is None
    assert zasobnik.opis_aktualizacji({'wersja': '2.0.1'}) == ('Dostępna aktualizacja 2.0.1', True)
    assert zasobnik.opis_aktualizacji({'wersja': '2.0.1', 'postep': 'pobieranie'})[1] is False
    assert zasobnik.opis_aktualizacji({'wersja': '2.0.1', 'postep': 'instalacja'})[1] is False
    tekst, aktywny = zasobnik.opis_aktualizacji({'wersja': '2.0.1', 'postep': 'blad',
                                                 'blad': 'suma kontrolna nie zgadza się'})
    assert aktywny is True and 'suma kontrolna' in tekst


def test_ikona_zamyka_sie_tylko_na_poczatek_instalacji():
    # Ikona uruchomiona po instalacji widzi „instalacja” od razu — nie może się znów zamknąć.
    assert zasobnik.zaczela_sie_instalacja(None, {'postep': 'instalacja'}) is False
    assert zasobnik.zaczela_sie_instalacja({}, {'postep': 'instalacja'}) is True
    assert zasobnik.zaczela_sie_instalacja({'postep': 'pobieranie'}, {'postep': 'instalacja'}) is True
    assert zasobnik.zaczela_sie_instalacja({'postep': 'instalacja'}, {'postep': 'instalacja'}) is False
    assert zasobnik.zaczela_sie_instalacja({}, {'postep': 'blad'}) is False


def test_poza_godzinami_zolty_komunikat_przed_drukarkami():
    komunikat = 'Poza godzinami pracy (05:30–15:30) — etykiety czekają w kolejce'
    stan = _stan(ogolny='uwaga', poza_godzinami=True, komunikat=komunikat, drukarki=[
        {'nazwa': 'etykiety', 'stan': 'brak_papieru', 'opis': '', 'obsluga': 'nowy'}])
    assert zasobnik.opis_glowny(stan) == ('uwaga', 'Poza godzinami pracy', komunikat)
    assert zasobnik.poziom_ikony(stan, 100.0, 100.0, 0.0) == 'uwaga'


def test_klient_lokalny_omija_systemowe_proxy(tmp_path, monkeypatch):
    """Systemowe proxy (tu: zmienna środowiskowa wskazująca martwy adres) nie może przejąć zapytań do
    127.0.0.1 — ikona przestałaby działać, a klucz usługi poszedłby do proxy."""
    import http.server
    import threading

    klucz = 'a' * 64
    (tmp_path / 'klucz_lokalny').write_text(klucz, encoding='ascii')
    naglowki = []

    class Obsluga(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            naglowki.append(self.headers.get('X-Klucz'))
            tresc = b'{"ok": true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(tresc)))
            self.end_headers()
            self.wfile.write(tresc)

        def log_message(self, *a):
            pass

    serwer = http.server.HTTPServer(('127.0.0.1', 0), Obsluga)
    threading.Thread(target=serwer.serve_forever, daemon=True).start()
    for zmienna in ('http_proxy', 'HTTP_PROXY'):
        monkeypatch.setenv(zmienna, 'http://127.0.0.1:9')
    monkeypatch.delenv('no_proxy', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    import urllib.request
    monkeypatch.setattr(urllib.request, '_opener', None)   # globalny otwieracz urlopen czyta proxy na nowo
    try:
        klient = zasobnik.KlientLokalny(port=serwer.server_address[1], plik_klucza=tmp_path / 'klucz_lokalny')
        assert klient.zapytaj('GET', '/stan') == (200, {'ok': True})
        assert naglowki == [klucz]
    finally:
        serwer.shutdown()
        serwer.server_close()
