# -*- coding: utf-8 -*-
"""Model prywatnego układu pulpitu Analizy sprzedażowej.

Osobny plik, a nie dopisek do `models_sales.py`: tamten opisuje DANE
SPRZEDAŻOWE (klient → zamówienie → pozycja), a to jest preferencja interfejsu.
Wspólny plik kusiłby, żeby kiedyś dołożyć tu relację do `sales_*`, której
nie ma i nie ma być.

WSZYSTKIE OGRANICZENIA Z MIGRACJI SĄ POWTÓRZONE TUTAJ — nie dla ozdoby. Cały
pakiet testów buduje SQLite Z TYCH METADANYCH, więc ograniczenie, którego
model nie zna, jest dla 3000 testów niewidzialne. Rozjazd model–baza wyszedł
w tym projekcie 21.09.2026 (fk_so_client SET NULL w migracji kontra
sales_orders_ibfk_1 NO ACTION w bazie zbudowanej z metadanych) i kosztował
osobne śledztwo.
"""

from datetime import datetime

from extensions import db


class UkladDashboardu(db.Model):
    """Układ kafelków pulpitu jednego użytkownika.

    Jeden wiersz na użytkownika. BRAK wiersza znaczy „nigdy nie dotykał trybu
    edycji" i daje układ domyślny; wiersz z pustą listą znaczy „usunął
    wszystkie kafelki" i daje stan pusty. Te dwa stany MUSZĄ być rozróżnialne
    — inaczej „Przywróć domyślny" i „usuń ostatni kafelek" dawałyby to samo.
    """

    __tablename__ = 'reports_dashboard_layouts'

    # Nazwy ograniczeń JAWNE i ZGODNE Z MIGRACJĄ (uq_rdl_user, fk_rdl_user).
    # `db.create_all()` bez jawnej nazwy nadałby własną (np.
    # `reports_dashboard_layouts_user_id_key`), różną od tej z pliku SQL —
    # dokładnie ten rozjazd model–baza wyszedł 21.09.2026 przy `sales_orders`
    # (fk_so_client SET NULL w migracji kontra ibfk_1 NO ACTION z metadanych).
    __table_args__ = (
        db.UniqueConstraint('user_id', name='uq_rdl_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Unikalność user_id siedzi w `__table_args__` (ograniczenie NAZWANE),
    # nie w `unique=True` na kolumnie — kolumnowy skrót nadaje nazwę
    # niejawnie i po cichu rozjeżdża się z migracją.
    user_id = db.Column(db.Integer,
                        db.ForeignKey('users.id', ondelete='CASCADE',
                                     name='fk_rdl_user'),
                        nullable=False)
    # Lista instancji kafelków: [{"typ": "kanal", "wymiar": "order_source"}, ...].
    # KOLEJNOŚĆ LISTY JEST KOLEJNOŚCIĄ W SIATCE — nie ma osobnego pola pozycji,
    # bo byłoby drugim źródłem prawdy o tym samym.
    uklad = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)
