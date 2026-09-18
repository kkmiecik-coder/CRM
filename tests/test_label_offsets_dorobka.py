# -*- coding: utf-8 -*-
"""
Numeracja etykiet w zamówieniu, w którym istnieje doróbka.

Doróbka dziedziczy short_product_id po oryginale (rework_service), więc mapa
offsetów kluczowana po tym polu gubiła jeden z dwóch wierszy — drugi nadpisywał
pierwszy i pozycja dostawała offset sąsiada.

Skutek na produkcji (zamówienie 223, wrzesień 2026): pozycja 223_4 o czterech
sztukach numerowała etykiety 9..12 w zamówieniu liczącym 11 sztuk. Trzy numery
kolidowały z sąsiednimi pozycjami, czwarty wychodził poza zakres. Nikt tego nie
zgłosił, bo dopóki nikt nie czyta tych liczb z powrotem, wyglądają jak liczby.

Układ odtworzony 1:1 z produkcji:

    seq  qty  rola
     1    1   zwykła
     2    2   zwykła
     3    1   zwykła
     4    4   ORYGINAŁ  ← dzieli short_product_id z doróbką
     4    1   doróbka
     5    1   zwykła
     6    1   zwykła
                razem 11 sztuk
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
)
from modules.production.services.label_print_service import _compute_unit_offsets

from tests.krawedzie_fixtures import app  # noqa: F401


def _zamowienie_z_dorobka():
    """Buduje układ z docstringu. Zwraca dict {etykieta: ProductionProduct}."""
    order = ProductionOrder(
        baselinker_order_id=223223,
        internal_order_number='223',
        client_name='Jan Kowalski',
    )
    db.session.add(order)
    db.session.flush()
    cfg = ProductionConfiguration.find_or_create('dąb', 'lity', 'A/B')
    db.session.flush()

    def poz(seq, qty, short, oryginal_id=None):
        p = ProductionProduct(
            order_id=order.id,
            configuration_id=cfg.id,
            short_product_id=short,
            product_sequence_in_order=seq,
            original_product_name='Blat dębowy',
            current_status='czeka_na_krawedzie',
            quantity=qty,
            original_product_id=oryginal_id,
        )
        db.session.add(p)
        db.session.flush()
        return p

    pozycje = {
        'p1': poz(1, 1, '223_1'),
        'p2': poz(2, 2, '223_2'),
        'p3': poz(3, 1, '223_3'),
    }
    oryginal = poz(4, 4, '223_4')
    pozycje['oryginal'] = oryginal
    pozycje['dorobka'] = poz(4, 1, '223_4', oryginal_id=oryginal.id)
    pozycje['p5'] = poz(5, 1, '223_5')
    pozycje['p6'] = poz(6, 1, '223_6')
    db.session.commit()
    return pozycje


def test_dorobka_nie_zabiera_offsetu_oryginalowi(app):
    with app.app_context():
        p = _zamowienie_z_dorobka()
        offsety = _compute_unit_offsets({x.id: x for x in p.values()})

        # Oryginał stoi po 1+2+1 = 4 sztukach poprzedników.
        assert offsety[p['oryginal'].id][0] == 4
        # Doróbka wchodzi zaraz za nim, po jego czterech sztukach.
        assert offsety[p['dorobka'].id][0] == 8
        # Gdyby klucz był po short_product_id, oba wiersze miałyby tę samą
        # wartość — to jest ten regres, którego pilnuje ten test.
        assert offsety[p['oryginal'].id][0] != offsety[p['dorobka'].id][0]


def test_numery_etykiet_nie_wychodza_poza_zamowienie(app):
    with app.app_context():
        p = _zamowienie_z_dorobka()
        offsety = _compute_unit_offsets({x.id: x for x in p.values()})

        uzyte = []
        for pozycja in p.values():
            offset, razem = offsety[pozycja.id]
            assert razem == 11
            uzyte.extend(range(offset + 1, offset + pozycja.quantity + 1))

        # Każda sztuka zamówienia dostaje własny numer, bez dziur i kolizji.
        assert sorted(uzyte) == list(range(1, 12))


def test_dorobka_nie_przesuwa_numeracji_pozniejszym_pozycjom(app):
    """
    Odrzucenie sztuk przenosi je z oryginału na doróbkę, a suma zostaje —
    dlatego numery pozycji stojących DALEJ w zamówieniu się nie zmieniają.
    To jest przesłanka, na której opiera się numeracja globalna na kafelkach
    w aplikacji stanowiskowej: numer wydrukowany wczoraj znaczy to samo dziś.
    """
    with app.app_context():
        p = _zamowienie_z_dorobka()
        offsety = _compute_unit_offsets({x.id: x for x in p.values()})
        offset_p5_po_dorobce = offsety[p['p5'].id][0]

        # Stan sprzed odrzucenia: oryginał miał 5 sztuk, doróbki nie było.
        db.session.delete(p['dorobka'])
        p['oryginal'].quantity = 5
        db.session.commit()

        przed = _compute_unit_offsets(
            {x.id: x for k, x in p.items() if k != 'dorobka'}
        )
        assert przed[p['p5'].id][0] == offset_p5_po_dorobce
        assert przed[p['p5'].id][1] == 11


def test_pozycja_anulowana_nie_zajmuje_slotu_w_numeracji(app):
    """
    Anulowana pozycja ma quantity = 0. Podłoga `max(1, n)` w liczeniu KOPII
    istnieje po to, żeby pozycja bez znanej ilości dostała mimo wszystko
    etykietę — ale przeniesiona do numeracji sprawiała, że anulowana zajmowała
    slot: przesuwała wszystkich za sobą i podbijała mianownik.

    Zamówienie 1400 na produkcji raportowało „5" przy trzech fizycznych
    sztukach. Operator widziałby sumę, której nie ma w rękach.
    """
    with app.app_context():
        order = ProductionOrder(baselinker_order_id=1400400,
                                internal_order_number='1400',
                                client_name='Jan Kowalski')
        db.session.add(order)
        db.session.flush()
        cfg = ProductionConfiguration.find_or_create('dąb', 'lity', 'A/B')
        db.session.flush()

        def poz(seq, qty, short, status='czeka_na_pakowanie'):
            p = ProductionProduct(
                order_id=order.id, configuration_id=cfg.id,
                short_product_id=short, product_sequence_in_order=seq,
                original_product_name='Blat', current_status=status,
                quantity=qty,
            )
            db.session.add(p)
            db.session.flush()
            return p

        anulowana = poz(1, 0, '1400_1', status='anulowane')
        pierwsza = poz(2, 1, '1400_2')
        druga = poz(3, 1, '1400_3')
        db.session.commit()

        offsety = _compute_unit_offsets(
            {x.id: x for x in (anulowana, pierwsza, druga)})

        # Suma to dwie sztuki, nie trzy — anulowana nie liczy się do mianownika.
        assert offsety[pierwsza.id] == (0, 2)
        assert offsety[druga.id] == (1, 2)
        # Anulowana nie przesuwa nikogo: stoi tam, gdzie następna pozycja.
        assert offsety[anulowana.id][0] == 0
