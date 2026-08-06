# -*- coding: utf-8 -*-
"""Cykl życia zlecenia trakowania, audyt i liczenie różnic."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.sawmill.models import (
    STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NEW, STATUS_SETTLED,
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog,
    SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.sawmill.services import orders
from modules.production.sawmill.services.orders import (
    SawmillStateError, add_log, complete_order, compute_differences, delete_log,
    next_sequence_no, order_totals, reopen_order, settle_order, unsettle_order,
    update_log,
)
from modules.users.models import User
# Sam import User nie wystarcza — to samo uzasadnienie co w test_sawmill_models.py
# i test_sawmill_numbering.py: User.multiplier_id ma ForeignKey('multipliers.id')
# i relationship('Multiplier'), a Multiplier siedzi razem z Quote, które ma
# relationship('Client') i relationship('QuoteStatus'). configure_mappers()
# przy pierwszym flush/query próbuje skonfigurować CAŁY rejestr mapperów, więc
# te klasy też muszą być zaimportowane, mimo że sawmill ich w ogóle nie dotyka.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, SawmillSupplier, SawmillSpecies, SawmillCounter,
    SawmillDelivery, SawmillOrder, SawmillLog, SawmillAudit,
)]

POMIAR = {
    'mid_circumference_cm': Decimal('125.6'),
    'length_cm': Decimal('410.0'),
}
CZAS = datetime(2026, 8, 5, 9, 31, 12)


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _zlecenie(deklaracja='80.000', cena=None):
    supplier = SawmillSupplier(name='Tartak Testowy')
    species = SawmillSpecies(name='Dąb')
    db.session.add_all([supplier, species])
    db.session.flush()
    delivery = SawmillDelivery(supplier_id=supplier.id, delivery_date=date(2026, 8, 5))
    db.session.add(delivery)
    db.session.flush()
    order = SawmillOrder(
        order_number='TRK/2026/001', delivery_id=delivery.id, species_id=species.id,
        declared_volume_m3=Decimal(deklaracja),
        price_per_m3=Decimal(cena) if cena else None,
        status=STATUS_NEW,
    )
    db.session.add(order)
    db.session.flush()
    return order


def test_pierwszy_pomiar_przelacza_status(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='TRAK-1')
        db.session.commit()
        assert order.status == STATUS_IN_PROGRESS
        assert order.started_at == CZAS


def test_objetosc_jest_wyliczana_i_zapisywana(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='TRAK-1')
        db.session.commit()
        assert log.volume_m3 == Decimal('0.514699')


def test_numery_klod_rosna_i_nie_sa_reuzywane(app):
    with app.app_context():
        order = _zlecenie()
        a = add_log(order, POMIAR, CZAS, device_id='T')
        b = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        assert (a.sequence_no, b.sequence_no) == (1, 2)

        delete_log(b, device_id='T')
        db.session.commit()
        c = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        assert c.sequence_no == 3


def test_sumy_pomijaja_usuniete(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        drugi = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        assert order_totals(order.id) == (2, Decimal('1.029398'))

        delete_log(drugi, device_id='T')
        db.session.commit()
        assert order_totals(order.id) == (1, Decimal('0.514699'))


def test_usuniecie_ostatniego_pomiaru_nie_cofa_statusu(app):
    """Status ma odzwierciedlać fakt rozpoczęcia pracy, nie stan licznika."""
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        delete_log(log, device_id='T')
        db.session.commit()
        assert order.status == STATUS_IN_PROGRESS
        assert order.started_at is not None


def test_zakonczenie_wymaga_pomiaru(app):
    with app.app_context():
        order = _zlecenie()
        with pytest.raises(SawmillStateError):
            complete_order(order, device_id='T')


def test_pelna_sciezka_statusow(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        assert order.status == STATUS_COMPLETED
        assert order.completed_by_device == 'T'

        settle_order(order, Decimal('76.500'), 'przyjęto z uwagą', user_id=1)
        db.session.commit()
        assert order.status == STATUS_SETTLED
        assert order.agreed_volume_m3 == Decimal('76.500')

        unsettle_order(order, user_id=1)
        db.session.commit()
        assert order.status == STATUS_COMPLETED
        assert order.settled_at is None
        # Uzgodniona objętość i notatka ZOSTAJĄ — admin zwykle koryguje szczegół.
        assert order.agreed_volume_m3 == Decimal('76.500')
        assert order.settlement_notes == 'przyjęto z uwagą'


def test_rozliczenie_tylko_z_completed(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        with pytest.raises(SawmillStateError):
            settle_order(order, Decimal('1.0'), None, user_id=1)


def test_reopen_wraca_do_in_progress(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        reopen_order(order, user_id=1)
        db.session.commit()
        assert order.status == STATUS_IN_PROGRESS
        assert order.completed_at is None
        assert order.completed_by_device is None


def test_kazda_operacja_zapisuje_audyt(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        update_log(log, dict(POMIAR, length_cm=Decimal('420.0')), device_id='T')
        delete_log(log, device_id='T')
        db.session.commit()
        akcje = [a.action for a in SawmillAudit.query.order_by(SawmillAudit.id).all()]
        assert akcje == ['log_create', 'log_update', 'log_delete']


def test_recznie_dodany_pomiar_ma_inna_akcje(app):
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, user_id=1, manual=True)
        db.session.commit()
        assert SawmillAudit.query.first().action == 'log_create_manual'


def test_audyt_zapisuje_wartosci_przed_i_po(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        update_log(log, dict(POMIAR, length_cm=Decimal('420.0')), device_id='T')
        db.session.commit()
        wpis = SawmillAudit.query.filter_by(action='log_update').first()
        assert '410.0' in wpis.before_json
        assert '420.0' in wpis.after_json


# ── Różnice ─────────────────────────────────────────────────────────────────

def test_roznica_ujemna_gdy_zmierzono_mniej(app):
    with app.app_context():
        order = _zlecenie(deklaracja='80.000', cena='1200.00')
        out = compute_differences(order, Decimal('76.340'), threshold_pct=5.0)
        assert out['difference_m3'] == Decimal('-3.660')
        assert out['difference_pct'] == Decimal('-4.58')
        assert out['difference_value'] == Decimal('-4392.00')
        assert out['is_deviation'] is False


def test_flaga_odchylenia_powyzej_progu(app):
    with app.app_context():
        order = _zlecenie(deklaracja='80.000', cena='1200.00')
        out = compute_differences(order, Decimal('74.000'), threshold_pct=5.0)
        assert out['is_deviation'] is True


def test_brak_ceny_zeruje_tylko_roznice_zlotowa(app):
    with app.app_context():
        order = _zlecenie(deklaracja='80.000', cena=None)
        out = compute_differences(order, Decimal('76.340'), threshold_pct=5.0)
        assert out['difference_m3'] == Decimal('-3.660')
        assert out['difference_value'] is None


def test_zerowa_deklaracja_nie_dzieli_przez_zero(app):
    """
    Regresja na recenzję finalną: zero w declared_volume_m3 (order_update
    i delivery_create od dawna odrzucają taką wartość kodem 422, ale wiersz
    mógł powstać inną drogą, np. wprost w bazie) NIE MOŻE lecieć do
    dzielenia — compute_differences() liczy się przy KAŻDYM odczycie listy
    zleceń, więc DivisionUndefined na jednym wierszu wywalałoby GET /orders
    dla wszystkich zleceń naraz. difference_pct zostaje puste (brak punktu
    odniesienia przy zerowej deklaracji), a is_deviation mimo to True —
    sama zerowa deklaracja to zawsze anomalia wymagająca uwagi biura, więc
    wiersz ma zostać widoczny nawet pod filtrem "tylko odchylenia".
    """
    with app.app_context():
        order = _zlecenie(deklaracja='0.000', cena='1200.00')
        out = compute_differences(order, Decimal('5.000'), threshold_pct=5.0)
        assert out['difference_m3'] == Decimal('5.000')
        assert out['difference_pct'] is None
        assert out['is_deviation'] is True
        # Różnica złotowa nie zależy od dzielenia — liczy się normalnie.
        assert out['difference_value'] == Decimal('6000.00')


# ── Rozróżnienie panel/tablet w update_log i delete_log ──────────────────────
#
# Brief nie testował tej gałęzi, a to właśnie ona jest najbardziej narażona
# na regresję: update_log/delete_log wnioskują pochodzenie żądania z tego,
# który argument (device_id czy user_id) jest różny od None — nie mają
# osobnego parametru "panel", bo kontrakt funkcji jest zamrożony. Te testy
# potwierdzają, że wniosek jest poprawny w obie strony i dla obu granic
# statusów (completed dla panelu, settled dla obu).

def test_panel_moze_edytowac_pomiar_po_zakonczeniu(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        update_log(log, dict(POMIAR, length_cm=Decimal('415.0')), user_id=1)
        db.session.commit()
        assert log.length_cm == Decimal('415.0')


def test_tablet_nie_moze_edytowac_pomiaru_po_zakonczeniu(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        with pytest.raises(SawmillStateError):
            update_log(log, dict(POMIAR, length_cm=Decimal('415.0')), device_id='T')


def test_panel_nie_moze_edytowac_pomiaru_po_rozliczeniu(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        settle_order(order, Decimal('76.500'), None, user_id=1)
        db.session.commit()
        with pytest.raises(SawmillStateError):
            update_log(log, dict(POMIAR, length_cm=Decimal('415.0')), user_id=1)


def test_panel_moze_usunac_pomiar_po_zakonczeniu(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        delete_log(log, user_id=1)
        db.session.commit()
        assert log.is_deleted is True


def test_tablet_nie_moze_usunac_pomiaru_po_zakonczeniu(app):
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        with pytest.raises(SawmillStateError):
            delete_log(log, device_id='T')


# ── Brakujące przejścia i warunki brzegowe ─────────────────────────────────

def test_panel_nie_moze_usunac_pomiaru_po_rozliczeniu(app):
    """Symetryczne do testu edycji — panel też nie może usunąć po rozliczeniu."""
    with app.app_context():
        order = _zlecenie()
        log = add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        settle_order(order, Decimal('76.500'), None, user_id=1)
        db.session.commit()
        with pytest.raises(SawmillStateError):
            delete_log(log, user_id=1)


def test_rozliczenie_wymaga_uzgodnionej_objetosci(app):
    """settle_order musi odrzucić None jako agreed_volume_m3."""
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        # Zlecenie jest w statusie COMPLETED, teraz próbujemy rozliczyć bez objętości
        with pytest.raises(SawmillStateError) as exc_info:
            settle_order(order, None, 'jakaś notatka', user_id=1)
        assert 'uzgodniona objętość' in str(exc_info.value)


def test_zakonczenie_z_niewlasciwego_statusu(app):
    """complete_order na już completed zleceniu powinien rzucić SawmillStateError."""
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        status_przed = order.status
        # Próba podwójnego zakończenia
        with pytest.raises(SawmillStateError):
            complete_order(order, device_id='T')
        # Stan nie powinien się zmienić
        db.session.refresh(order)
        assert order.status == status_przed


def test_wznowienie_z_niewlasciwego_statusu(app):
    """reopen_order na zleceniu które nie jest completed powinien rzucić SawmillStateError."""
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()
        # Zlecenie jest w statusie IN_PROGRESS
        assert order.status == STATUS_IN_PROGRESS
        status_przed = order.status
        with pytest.raises(SawmillStateError):
            reopen_order(order, user_id=1)
        # Stan nie powinien się zmienić
        db.session.refresh(order)
        assert order.status == status_przed


def test_cofniecie_rozliczenia_z_niewlasciwego_statusu(app):
    """unsettle_order na zleceniu które nie jest settled powinien rzucić SawmillStateError."""
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')
        complete_order(order, device_id='T')
        db.session.commit()
        # Zlecenie jest w statusie COMPLETED, a nie SETTLED
        assert order.status == STATUS_COMPLETED
        status_przed = order.status
        with pytest.raises(SawmillStateError):
            unsettle_order(order, user_id=1)
        # Stan nie powinien się zmienić
        db.session.refresh(order)
        assert order.status == status_przed


# ── SAVEPOINT i kolizja sequence_no ───────────────────────────────────────────

def test_kolizja_numeru_jest_ponawiana_raz(app):
    """
    Symulacja rzadkiego wyścigu o sequence_no: pierwsza próba insertu trafia
    w numer już zajęty (prawdziwy IntegrityError na UniqueConstraint
    (order_id, sequence_no) — nie mockujemy wyjątku, tylko next_sequence_no
    tak, by naprawdę zderzyć się z istniejącym wierszem). SAVEPOINT łapie
    ten wyjątek i insert jest ponawiany ze świeżym numerem, bez psucia sesji.
    """
    with app.app_context():
        order = _zlecenie()
        add_log(order, POMIAR, CZAS, device_id='T')  # zajmuje sequence_no=1
        db.session.commit()

        real_next = orders.next_sequence_no
        wywolania = {'n': 0}

        def fake_next(order_id):
            wywolania['n'] += 1
            if wywolania['n'] == 1:
                return 1  # kolizja — numer już zajęty przez pierwszą kłodę
            return real_next(order_id)

        with patch.object(orders, 'next_sequence_no', side_effect=fake_next):
            log = add_log(order, POMIAR, CZAS, device_id='T')
        db.session.commit()

        assert log.sequence_no == 2
        assert wywolania['n'] == 2


def test_inny_blad_zapisu_nie_jest_polykany_jako_kolizja(app):
    """
    except musi łapać wyłącznie IntegrityError. Inny wyjątek podczas zapisu
    (np. zerwane połączenie, błąd sterownika) ma się propagować, a NIE
    zostać po cichu zinterpretowany jako kolizja numeru i ponowiony —
    inaczej prawdziwy błąd ginie, a operacja kończy się fałszywym sukcesem.
    """
    with app.app_context():
        order = _zlecenie()
        real_add = db.session.add
        wywolania = {'n': 0}

        def fake_add(instance):
            wywolania['n'] += 1
            if wywolania['n'] == 1:
                raise RuntimeError('zerwane polaczenie')
            return real_add(instance)

        with patch.object(db.session, 'add', side_effect=fake_add):
            with pytest.raises(RuntimeError):
                add_log(order, POMIAR, CZAS, device_id='T')

        # Brak ponowienia dla wyjątku innego niż IntegrityError.
        assert wywolania['n'] == 1
