# -*- coding: utf-8 -*-
"""
Pomocnik testów zapisów Weryfikacji: symulacja migawki transakcji MySQL (REPEATABLE READ).

SQLite nie ma migawki — każdy SELECT widzi bieżący stan, więc błąd „zapis decyduje na pozycjach
sprzed czekania na blokady” nie dałby się na nim odtworzyć. Zamiast tego podmieniamy funkcję serwisu
przelotką, która tuż przed jej wywołaniem wpycha do pamięci ORM pozycje w STARYM stanie, a w bazie
zostawia stan NOWY. To dokładnie ta sytuacja, którą na MySQL robi migawka: obiekty w sesji są nieświeże,
baza ma już cudzy zapis.
"""
from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct

_POZYCJE = ProductionProduct.__table__


def migawka_pozycji(monkeypatch, cel, nazwa, w_pamieci, w_bazie=None):
    """
    Podmienia `cel.nazwa` (funkcję serwisu, w której `order` jest argumentem pozycyjnym) przelotką:
      1. zapamiętuje statusy pozycji zamówienia z bazy (chwila „teraz”),
      2. surowym UPDATE-em ustawia w bazie `w_pamieci` i wczytuje pozycje do sesji ORM,
      3. surowym UPDATE-em przywraca w bazie `w_bazie` (brak = statusy z punktu 1),
      4. wywołuje prawdziwą funkcję.
    Nie wołamy `expire_all()` ani `refresh()` — obiekty zostają nieświeże, więc zmianę w bazie
    zobaczy wyłącznie odczyt bieżący w kodzie (`populate_existing`). Surowy UPDATE jest w transakcji
    żądania: przy 409 (rollback) znika razem z nią — dlatego testy sprawdzają odpowiedź, a nie
    stan bazy po odmowie.
    """
    oryginal = getattr(cel, nazwa)

    def przelotka(*args, **kwargs):
        order = next(a for a in args if isinstance(a, ProductionOrder))
        warunek = _POZYCJE.c.order_id == order.id
        teraz = dict(db.session.query(_POZYCJE.c.id, _POZYCJE.c.current_status).filter(warunek).all())
        db.session.execute(_POZYCJE.update().where(warunek).values(current_status=w_pamieci))
        for p in order.products:
            assert p.current_status == w_pamieci      # wczytane do pamięci w starym stanie
        for pid, status in teraz.items():
            db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pid)
                               .values(current_status=w_bazie or status))
        return oryginal(*args, **kwargs)

    monkeypatch.setattr(cel, nazwa, przelotka)
