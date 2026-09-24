# modules/clients/models.py
from datetime import datetime

from extensions import db

class Client(db.Model):
    # Rejestr WYCENIANYCH, nie kupujących. Zasilany z procesu wyceny —
    # kupujący ze sklepu i Allegro nigdy tu nie trafiali (tylko 23,2%
    # e-maili z raportu sprzedażowego ma tu odpowiednik). Klienci
    # sprzedażowi mieszkają w sales_clients.
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    # UWAGA: pole trzyma "Nazwę klienta" (wolny tekst / nazwa firmy), nie krótki numer
    # — dlatego musi być szerokie jak pozostałe pola nazw (255), inaczej MySQL rzuca 1406.
    client_number = db.Column(db.String(255), unique=True, nullable=False)
    client_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120), nullable=True)  # Email opcjonalny, ale unikalny jeśli podany
    phone = db.Column(db.String(20), nullable=True)

    # Adres dostawy
    delivery_name = db.Column(db.String(255))
    delivery_company = db.Column(db.String(255))
    delivery_address = db.Column(db.String(255))
    delivery_zip = db.Column(db.String(10))
    delivery_city = db.Column(db.String(100))
    delivery_region = db.Column(db.String(100))
    delivery_country = db.Column(db.String(100))

    # Dane do faktury
    invoice_name = db.Column(db.String(255))
    invoice_company = db.Column(db.String(255))
    invoice_address = db.Column(db.String(255))
    invoice_zip = db.Column(db.String(10))
    invoice_city = db.Column(db.String(100))
    invoice_region = db.Column(db.String(100))
    invoice_nip = db.Column(db.String(20))

    # Źródło pochodzenia (wyceny)
    source = db.Column(db.String(100))

    # Domyślne źródło zamówień Baselinker (baselinker_id)
    order_source_id = db.Column(db.Integer, nullable=True)

    # Data założenia leada. Tabela nie miała jej wcale, więc nie dało się
    # policzyć, kiedy lead się pojawił ani jaka jest konwersja w czasie.
    # nullable, bo dla istniejących wierszy NULL jest uczciwszy niż zmyślona data.
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    # Notatka o kliencie
    notes = db.Column(db.Text, nullable=True)

    # Właściciel klienta (kto go utworzył)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relacja: dostęp do danych użytkownika przez client.created_by
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_clients')

    def __repr__(self):
        return f"<Client {self.client_name}>"