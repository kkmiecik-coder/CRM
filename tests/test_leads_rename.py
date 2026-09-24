# -*- coding: utf-8 -*-
"""Rejestr wycenianych nazywa sie `leads`, nie `clients`.

To nie kosmetyka. `clients` jest zasilane wylacznie z procesu wyceny —
tylko 23,2% e-maili kupujacych ma tam odpowiednik. Lead to ktos wyceniony,
klient sprzedazowy to ktos, kto kupil. Dwie nazwy dla dwoch roznych bytow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.clients.models import Client


def test_tabela_nazywa_sie_leads():
    assert Client.__tablename__ == 'leads'


def test_lead_ma_date_zalozenia():
    """Bez created_at nie da sie powiedziec, kiedy lead sie pojawil,
    wiec nie da sie policzyc konwersji lead -> klient w czasie."""
    assert 'created_at' in Client.__table__.columns


def test_wycena_wskazuje_na_leads():
    from modules.calculator.models import Quote
    klucze = list(Quote.__table__.c.client_id.foreign_keys)
    assert len(klucze) == 1
    assert klucze[0].column.table.name == 'leads'
