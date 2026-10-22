"""`python -m agent_druku service|tray|diagnoza|klucz`.

service  — rdzeń (pętla, push) + lokalne API; uruchamiany przez WinSW jako usługa Windows,
tray     — ikona w zasobniku i okienko (pystray + tkinter, ładowane dopiero tutaj),
diagnoza — jednorazowy odczyt stanu obu drukarek (także SNMP) na standardowe wyjście,
klucz    — zakłada klucz lokalnego API, jeśli go brak (instalator, przed nadaniem uprawnień).
"""
import logging
import logging.handlers
import os
import sys

UZYCIE = 'Użycie: AgentDruku.exe service | tray | diagnoza | klucz'
# Tyle czekamy przy zatrzymaniu usługi, aż wątek roboczy dokończy bieżącą porcję (wysłane etykiety
# trafią do dziennika i nie skończą jako „przerwane”). WinSW daje 15 s (stoptimeout w AgentDrukuUsluga.xml).
CZEKANIE_NA_PORCJE_S = 12


def _ustaw_logi():
    from agent_druku import sciezki
    plik = sciezki.plik_logu()
    os.makedirs(plik.parent, exist_ok=True)
    format_ = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    do_pliku = logging.handlers.RotatingFileHandler(plik, maxBytes=1024 * 1024, backupCount=5,
                                                    encoding='utf-8')
    do_pliku.setFormatter(format_)
    na_ekran = logging.StreamHandler()
    na_ekran.setFormatter(format_)
    korzen = logging.getLogger()
    korzen.setLevel(logging.INFO)
    korzen.addHandler(do_pliku)
    korzen.addHandler(na_ekran)


def usluga():
    from agent_druku import WERSJA, crm, konfiguracja, lokalne_api, sciezki
    from agent_druku.petla import Agent

    _ustaw_logi()
    log = logging.getLogger('agent_druku')
    log.info('Start usługi agenta druku %s', WERSJA)
    agent = Agent(sciezki, None)
    adres_crm = konfiguracja.wczytaj_przypiety_adres()
    if not adres_crm:
        log.critical('Brak adresu CRM z instalatora (%s) — agent nie połączy się z CRM; '
                     'zainstaluj go ponownie.', sciezki.plik_adresu_crm())
    elif agent.lokalna.crm_url and agent.lokalna.token:
        if konfiguracja.ten_sam_serwer(agent.lokalna.crm_url, adres_crm):
            agent.klient = crm.Klient(agent.lokalna.crm_url, agent.lokalna.token)
        else:   # token wydany przez inny serwer niż ten z instalatora — nie używamy go
            log.error('Konfiguracja wskazuje inny serwer CRM niż instalator — sparuj agenta ponownie.')
    try:
        serwer = lokalne_api.uruchom(agent, klucz=lokalne_api.zapewnij_klucz(), adres_crm=adres_crm)
    except (lokalne_api.BladKlucza, OSError) as e:
        log.critical('Lokalne API nie wystartowało: %s', e)
        return 1
    watek = agent.uruchom()
    try:
        while watek.is_alive():
            watek.join(1)
    except KeyboardInterrupt:   # WinSW zatrzymuje usługę sygnałem Ctrl+C
        pass
    finally:
        log.info('Zatrzymanie usługi agenta druku')
        agent.zatrzymaj()
        watek.join(CZEKANIE_NA_PORCJE_S)
        if watek.is_alive():
            log.warning('Wątek roboczy nie skończył porcji w %d s — zatrzymanie mimo to', CZEKANIE_NA_PORCJE_S)
        serwer.shutdown()
        serwer.server_close()
    return 0


def diagnoza():
    import socket

    from agent_druku import drukarki, konfiguracja, sciezki, snmp

    lokalna = konfiguracja.Lokalna()
    print('Konfiguracja: %s (wersja %s)' % (sciezki.plik_konfiguracji(), lokalna.wersja))
    print('CRM: %s, sparowany: %s\n' % (lokalna.crm_url or '(brak)', 'tak' if lokalna.token else 'nie'))
    lista = (lokalna.dane or {}).get('drukarki') or []
    if not lista:
        print('Brak drukarek w konfiguracji — wpisz je w okienku agenta albo w CRM.')
        return 1
    for d in lista:
        print('Drukarka %s: %s:%s, model %s, odczyt stanu: %s' % (
            d.get('nazwa'), d.get('ip'), d.get('port'), d.get('model'), d.get('odczyt_stanu')))
        try:
            with socket.create_connection((d['ip'], d['port']), timeout=3):
                print('  połączenie TCP: OK')
        except (OSError, KeyError) as e:
            print('  połączenie TCP: brak (%s)' % e)
        if d.get('odczyt_stanu') == 'snmp':
            odp = snmp.pobierz(d['ip'], [drukarki.OID_STATUS, drukarki.OID_BLEDY, drukarki.OID_KONSOLA])
            if not odp:
                print('  SNMP: brak odpowiedzi')
            for oid, wartosc in odp.items():
                print('  SNMP %s = %r' % (oid, wartosc))
            stan, opis = drukarki.stan(d)
            print('  stan: %s%s' % (stan, ' (%s)' % opis if opis else ''))
        else:
            print('  stan: bez odczytu (drukarka nie odpowiada na SNMP)')
        print()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    tryb = argv[0] if argv else ''
    if tryb == 'service':
        return usluga()
    if tryb == 'tray':
        from agent_druku import zasobnik
        return zasobnik.main()
    if tryb == 'diagnoza':
        return diagnoza()
    if tryb == 'klucz':
        from agent_druku import lokalne_api
        lokalne_api.zapewnij_klucz()
        return 0
    print(UZYCIE)
    return 2


if __name__ == '__main__':
    sys.exit(main())
