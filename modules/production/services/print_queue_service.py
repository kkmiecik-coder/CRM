# -*- coding: utf-8 -*-
"""
Kolejka wydruku dla obu drukarek (logistyka etap 4, spec 6.1).

`zakolejkuj_zpl` wkłada gotowy ZPL do prod_print_queue z nazwą drukarki — krok 4.2
użyje go do etykiet paczek. `wydruk_probny` służy do ustawienia drukarki z panelu
(Konfiguracja → Drukarka etykiet). Druk robi agent na komputerze hali; CRM tylko
kolejkuje i budzi agenta sygnałem.
"""
from flask import g

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob
from modules.production.services import package_label, realtime_service
from modules.production.services.label_print_service import _load_config

logger = get_structured_logger('production.print_queue')

NAZWY_DRUKAREK = {
    LabelPrintJob.DRUKARKA_ETYKIETY: 'drukarka etykiet (60x40)',
    LabelPrintJob.DRUKARKA_WYSYLKA: 'drukarka paczek (100x150)',
}


class NieznanaDrukarka(ValueError):
    """Nazwa drukarki spoza LabelPrintJob.DRUKARKI."""


def _sprawdz_drukarke(drukarka):
    if not isinstance(drukarka, str) or drukarka not in LabelPrintJob.DRUKARKI:
        raise NieznanaDrukarka('Nieznana drukarka: %r' % (drukarka,))


def zakolejkuj_zpl(drukarka, zpl, kod, stanowisko, aktor,
                   baselinker_order_id=None, package_id=None):
    """Jedno zadanie ZPL w kolejce agenta. Flush (żeby było id), bez commita —
    commituje wywołujący razem ze swoją zmianą, a po commicie woła
    realtime_service.publish_print_signal (inaczej agent obudzi się przed
    zakończeniem transakcji i wróci z pustymi rękami)."""
    _sprawdz_drukarke(drukarka)
    job = LabelPrintJob(
        printer=drukarka,
        short_product_id=str(kod)[:20],
        package_id=package_id,
        baselinker_order_id=baselinker_order_id,
        zpl_payload=zpl,
        station_code=str(stanowisko)[:50],
        requested_by_type=str(aktor.get('type') or 'user')[:20],
        requested_by_id=str(aktor.get('id') if aktor.get('id') is not None else '0')[:100],
        status=LabelPrintJob.STATUS_PENDING,
    )
    db.session.add(job)
    db.session.flush()
    return job


def _zpl_probny_etykiet(offset_lt, offset_ls):
    """Etykieta próbna 60x40 z tymi samymi przesunięciami co etykieta produktu
    (label_print_service.generate_label_zpl): ^LT w pionie, offset_ls dodawany do x."""
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


def zpl_probny(drukarka):
    _sprawdz_drukarke(drukarka)
    if drukarka == LabelPrintJob.DRUKARKA_WYSYLKA:
        return package_label.generate_test_label_zpl(package_label.wczytaj_przesuniecie())
    cfg = _load_config()
    return _zpl_probny_etykiet(cfg['offset_lt'], cfg['offset_ls'])


def wydruk_probny(drukarka, aktor):
    """Etykieta próbna w kolejce wskazanej drukarki. Bierze ZAPISANE przesunięcia —
    niezapisane zmiany w panelu nie mają wpływu (panel o tym ostrzega)."""
    zpl = zpl_probny(drukarka)
    job = zakolejkuj_zpl(drukarka, zpl, 'TEST-' + drukarka, 'panel', aktor)
    db.session.commit()
    # Sygnał dopiero po commicie — patrz komentarz w label_print_service._enqueue_labels.
    realtime_service.publish_print_signal(1)
    logger.info('Wydruk próbny w kolejce', extra={'printer': drukarka, 'job_id': job.id})
    return job


def zaplanuj_sygnal_po_commicie(liczba):
    """
    Sygnał dla agenta druku PO commicie transakcji żądania (etykiety paczek z API
    mobilnego, krok 4.2). W API mobilnym commit robi @with_idempotency, więc handler nie
    może wysłać sygnału sam — agent obudzony przed commitem wróciłby z pustymi rękami.
    Wysyła go wyslij_zaplanowany_sygnal() wołane przez dekorator po udanym commicie;
    odmowa i błąd kończą się rollbackiem bez sygnału (g żyje tylko do końca żądania).
    """
    g.sygnal_druku_po_commicie = getattr(g, 'sygnal_druku_po_commicie', 0) + int(liczba)


def wyslij_zaplanowany_sygnal():
    """Wysyła zaplanowany sygnał (jeden na żądanie, z sumą zadań). Zwraca liczbę zadań."""
    liczba = getattr(g, 'sygnal_druku_po_commicie', 0)
    g.sygnal_druku_po_commicie = 0
    if liczba:
        realtime_service.publish_print_signal(liczba)
    return liczba
