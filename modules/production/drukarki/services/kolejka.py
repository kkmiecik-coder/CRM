# -*- coding: utf-8 -*-
"""
Kolejka druku z dzierżawą (agent druku v2).

Zadanie przechodzi: pending → claimed (agent pobrał, dzierżawa) → sending (agent zaczął słać dane do drukarki)
→ printed | failed | unknown; z claimed wraca do pending po wygaśnięciu dzierżawy albo gdy agent zgłosi, że
nie wysłał ani bajtu. Sukces to dane w całości przyjęte przez drukarkę; brak połączenia (zero bajtów) nie jest
porażką — zadanie wraca do kolejki.

Zasady:
- Czas dzierżawy liczy WYŁĄCZNIE zegar serwera (datetime.utcnow()); agent żadnych czasów nie wysyła.
- Kolejka nie bierze blokad wierszy prod_orders ani prod_products. Każdy zapis zadania jest warunkowy po
  statusie (UPDATE ... WHERE id=:id AND status=:oczekiwany), a wiele wierszy idzie rosnąco po id.
- Funkcje nie commitują (wywołujący robi to razem ze swoją zmianą); wyjątek robi `wygas_z_throttlingiem`,
  które commituje po wygaszeniu.
"""
import time
from datetime import datetime, timedelta

from sqlalchemy import or_

from extensions import db
from modules.logging import get_structured_logger
from modules.production.drukarki import stale
from modules.production.models import LabelPrintJob
from modules.production.services import print_queue_service
from modules.production.services.label_print_service import rollback_label_count_for_jobs

logger = get_structured_logger('production.print_queue')

# Pending starsze niż tyle wygasa (operator ma kliknąć ponownie).
TTL_PENDING = timedelta(hours=1)

# Minimalny odstęp między przebiegami sprzątania w jednym workerze (wygas_z_throttlingiem).
ODSTEP_WYGASZANIA_S = 60
# None = ten worker jeszcze nie sprzątał. Celowo None, a nie 0.0: time.monotonic() bywa liczone od startu procesu
# (tak jest na macOS), więc zero jako „dawno temu” oznaczałoby, że świeży worker przez pierwszą minutę nie sprząta.
_ostatnie_wygaszanie = None

WYNIK_WYDRUKOWANE = 'wydrukowane'
WYNIK_BLAD = 'blad'
WYNIK_NIEWYSLANE = 'niewyslane'

_PONAWIALNE = (LabelPrintJob.STATUS_FAILED, LabelPrintJob.STATUS_EXPIRED,
               LabelPrintJob.STATUS_UNKNOWN, LabelPrintJob.STATUS_PRINTED)


def _zmien(job_id, statusy, zmiany, agent_id=None, *warunki):
    """UPDATE zadania tylko gdy ma jeszcze jeden z `statusy` (i, gdy podano, dzierżawi je ten agent).
    True, gdy wiersz się zmienił."""
    tabela = LabelPrintJob.__table__
    cond = [tabela.c.id == job_id, tabela.c.status.in_(statusy), *warunki]
    if agent_id is not None:
        cond.append(tabela.c.claimed_by_agent_id == agent_id)
    return db.session.execute(tabela.update().where(*cond).values(**zmiany)).rowcount == 1


def _wczytaj(ids):
    """Zadania o podanych id, odświeżone po zapisach Core (rosnąco po id)."""
    if not ids:
        return []
    return (LabelPrintJob.query.filter(LabelPrintJob.id.in_(list(ids)))
            .order_by(LabelPrintJob.id).populate_existing().all())


def pobierz(agent_id, drukarka, limit, teraz=None):
    """Dzierżawi agentowi do `limit` najstarszych `pending` danej drukarki (FIFO: requested_at, id).
    Zwraca faktycznie wydzierżawione zadania w kolejności FIFO.

    `pending` starszych niż TTL_PENDING nie wydajemy nigdy: po przerwie agenta (sieć, wyłączony hub) czekają na
    `wygas`, które je wygasi z cofnięciem liczników — operator i tak kliknął już druk ponownie. `teraz` tylko
    dla testów (zegar serwera)."""
    teraz = teraz or datetime.utcnow()
    kandydaci = (LabelPrintJob.query
                 .filter(LabelPrintJob.status == LabelPrintJob.STATUS_PENDING,
                         LabelPrintJob.printer == drukarka,
                         LabelPrintJob.requested_at >= teraz - TTL_PENDING)
                 .order_by(LabelPrintJob.requested_at.asc(), LabelPrintJob.id.asc())
                 .limit(max(0, int(limit)))
                 .all())
    kolejnosc = [j.id for j in kandydaci]
    do = teraz + timedelta(seconds=stale.DZIERZAWA_S)
    swieze = LabelPrintJob.__table__.c.requested_at >= teraz - TTL_PENDING
    wziete = set()
    # Zapisy rosnąco po id (bez 1213 między workerami); wygrywa ten, kto pierwszy przestawi z pending.
    for job_id in sorted(kolejnosc):
        if _zmien(job_id, (LabelPrintJob.STATUS_PENDING,),
                  {'status': LabelPrintJob.STATUS_CLAIMED, 'claimed_by_agent_id': agent_id,
                   'lease_until': do}, None, swieze):
            wziete.add(job_id)
    po_id = {j.id: j for j in _wczytaj(wziete)}
    return [po_id[i] for i in kolejnosc if i in po_id]


def wysylam(agent_id, job_id):
    """claimed → sending (agent zaczyna słać dane), z przedłużeniem dzierżawy. Powtórka dla zadania, które ten
    agent już ma w `sending`, też daje True: odnawia dzierżawę, ale NIE rusza `sending_at` (utrata odpowiedzi nie
    może kończyć się nieznanym wynikiem; przed podwójnym wydrukiem chroni dziennik agenta). False, gdy zadanie
    nie jest dzierżawą tego agenta."""
    teraz = datetime.utcnow()
    do = teraz + timedelta(seconds=stale.DZIERZAWA_S)
    if _zmien(job_id, (LabelPrintJob.STATUS_CLAIMED,),
              {'status': LabelPrintJob.STATUS_SENDING, 'sending_at': teraz, 'lease_until': do}, agent_id):
        return True
    return _zmien(job_id, (LabelPrintJob.STATUS_SENDING,), {'lease_until': do}, agent_id)


def wynik(agent_id, wyniki):
    """Wyniki z agenta: [{'id', 'wynik': 'wydrukowane'|'blad'|'niewyslane', 'blad': str?}].
    Rusza tylko zadania w claimed/sending tego agenta, więc powtórka nic nie zmienia. Powtórzone id: liczy
    się pierwszy wynik. Zwraca liczbę zmienionych zadań.

    Spóźniony wynik (dzierżawa minęła w trakcie porcji i `wygas` dał `unknown`) przyjmujemy od agenta, który
    dzierżawił zadanie: `wydrukowane` → printed, `blad` → failed z cofnięciem liczników. Inaczej fałszywe
    „wysłane, bez potwierdzenia” zachęca do „Ponów”, czyli do podwójnego wydruku. `niewyslane` dla `unknown`
    niczego nie zmienia (zadanie nie wraca do kolejki — decyzja należy do człowieka)."""
    wybrane = {}
    for w in wyniki or []:
        try:
            job_id = int(w.get('id'))
        except (TypeError, ValueError, AttributeError):
            continue
        if w.get('wynik') in (WYNIK_WYDRUKOWANE, WYNIK_BLAD, WYNIK_NIEWYSLANE):
            wybrane.setdefault(job_id, w)

    teraz = datetime.utcnow()
    w_toku = (LabelPrintJob.STATUS_CLAIMED, LabelPrintJob.STATUS_SENDING)
    z_wynikiem = w_toku + (LabelPrintJob.STATUS_UNKNOWN,)
    zmienione = 0
    nieudane = []
    for job_id in sorted(wybrane):
        w = wybrane[job_id]
        rodzaj = w['wynik']
        if rodzaj == WYNIK_WYDRUKOWANE:
            statusy = z_wynikiem
            # error_message czyści komunikat „Wysyłka przerwana…” zostawiony przez `wygas` przy unknown.
            zmiany = {'status': LabelPrintJob.STATUS_PRINTED, 'printed_at': teraz, 'lease_until': None,
                      'error_message': None}
        elif rodzaj == WYNIK_BLAD:
            statusy = z_wynikiem
            zmiany = {'status': LabelPrintJob.STATUS_FAILED, 'lease_until': None,
                      'error_message': (str(w.get('blad') or '')[:1000]) or None}
        else:
            statusy = w_toku
            zmiany = {'status': LabelPrintJob.STATUS_PENDING, 'claimed_by_agent_id': None,
                      'lease_until': None, 'sending_at': None}
        if not _zmien(job_id, statusy, zmiany, agent_id):
            continue
        zmienione += 1
        if rodzaj == WYNIK_BLAD:
            nieudane.append(job_id)
    # Etykieta, która nie wyszła, nie może zostawić pozycji oznaczonej jako wydrukowana.
    if nieudane:
        rollback_label_count_for_jobs(_wczytaj(nieudane))
    return zmienione


def wygas(teraz=None):
    """Sprząta kolejkę zegarem serwera (`teraz` tylko dla testów):
    claimed po dzierżawie → pending; sending po dzierżawie → unknown (wynik nieznany, liczników nie ruszamy:
    etykieta mogła wyjść); pending starsze niż TTL_PENDING → expired z cofnięciem liczników.
    Zwraca {'claimed_do_pending', 'sending_do_unknown', 'expired'}."""
    teraz = teraz or datetime.utcnow()
    tabela = LabelPrintJob.__table__
    po_dzierzawie = or_(LabelPrintJob.lease_until.is_(None), LabelPrintJob.lease_until < teraz)
    po_dzierzawie_core = or_(tabela.c.lease_until.is_(None), tabela.c.lease_until < teraz)

    def _ids(status):
        return [i for (i,) in db.session.query(LabelPrintJob.id)
                .filter(LabelPrintJob.status == status, po_dzierzawie)
                .order_by(LabelPrintJob.id).all()]

    raport = {'claimed_do_pending': 0, 'sending_do_unknown': 0, 'expired': 0}
    for job_id in _ids(LabelPrintJob.STATUS_CLAIMED):
        if _zmien(job_id, (LabelPrintJob.STATUS_CLAIMED,),
                  {'status': LabelPrintJob.STATUS_PENDING, 'claimed_by_agent_id': None, 'lease_until': None},
                  None, po_dzierzawie_core):
            raport['claimed_do_pending'] += 1
    for job_id in _ids(LabelPrintJob.STATUS_SENDING):
        if _zmien(job_id, (LabelPrintJob.STATUS_SENDING,),
                  {'status': LabelPrintJob.STATUS_UNKNOWN,
                   'error_message': 'Wysyłka przerwana: nie wiadomo, czy etykieta wyszła'},
                  None, po_dzierzawie_core):
            raport['sending_do_unknown'] += 1

    # Wybieramy PRZED aktualizacją, bo licznik wydrukowanych etykiet trzeba cofnąć o te zadania.
    # Zapis warunkowy: drugi worker (albo agent) mógł zmienić zadanie między odczytem a zapisem —
    # cofamy tylko za zadania, które naprawdę przestawiliśmy z `pending`.
    wygasajace = (LabelPrintJob.query
                  .filter(LabelPrintJob.status == LabelPrintJob.STATUS_PENDING,
                          LabelPrintJob.requested_at < teraz - TTL_PENDING)
                  .order_by(LabelPrintJob.id)
                  .all())
    wygasajace = [job for job in wygasajace
                  if _zmien(job.id, (LabelPrintJob.STATUS_PENDING,),
                            {'status': LabelPrintJob.STATUS_EXPIRED,
                             'error_message': f'TTL: pending starsze niż {TTL_PENDING}'})]
    if wygasajace:
        rollback_label_count_for_jobs(wygasajace)
    raport['expired'] = len(wygasajace)
    return raport


def wygas_z_throttlingiem(force=False):
    """`wygas` najwyżej raz na ODSTEP_WYGASZANIA_S w workerze (`force` omija odstęp) i commit, gdy coś się zmieniło.
    Zwraca liczbę wygaszonych `pending` (0 także wtedy, gdy przebieg pominął throttling).

    Woła je /kontakt agenta druku: agent odzywa się co kilka sekund, a TTL to godzina. Licznik jest per worker
    gunicorna — kilku workerów to kilka przebiegów na minutę zamiast jednego, a zapisy są warunkowe i idempotentne."""
    global _ostatnie_wygaszanie
    teraz = time.monotonic()
    if not force and _ostatnie_wygaszanie is not None and (teraz - _ostatnie_wygaszanie) < ODSTEP_WYGASZANIA_S:
        return 0
    _ostatnie_wygaszanie = teraz

    raport = wygas()
    if raport['expired'] or raport['claimed_do_pending'] or raport['sending_do_unknown']:
        db.session.commit()
        logger.info('Sprzątanie kolejki druku', extra=raport)
    return raport['expired']


def ponow(job_id, aktor):
    """Nowe zadanie jako kopia zakończonego (failed|expired|unknown|printed). `label_index` zostaje pusty:
    przedruk nie rusza liczników przy porażce (patrz rollback_label_count_for_jobs). Nie commituje."""
    job = db.session.get(LabelPrintJob, job_id)
    if job is None or job.status not in _PONAWIALNE:
        raise ValueError('Zadania w tym stanie nie można ponowić')
    nowe = print_queue_service.zakolejkuj_zpl(
        job.printer, job.zpl_payload, job.short_product_id, job.station_code, aktor,
        baselinker_order_id=job.baselinker_order_id, package_id=job.package_id)
    nowe.product_id = job.product_id
    nowe.label_index = None
    nowe.reprint_of_job_id = job.id
    db.session.flush()
    return nowe


def anuluj(job_id, aktor):
    """Anuluje zadanie czekające w kolejce (tylko `pending`) i cofa liczniki. False, gdy zadanie jest w innym
    stanie. Nie commituje."""
    opis = 'Anulowane przez %s:%s' % (aktor.get('type') or 'user', aktor.get('id'))
    if not _zmien(job_id, (LabelPrintJob.STATUS_PENDING,),
                  {'status': LabelPrintJob.STATUS_CANCELLED, 'error_message': opis[:1000]}):
        return False
    rollback_label_count_for_jobs(_wczytaj([job_id]))
    return True
