# modules/clients/models.py
from extensions import db

class Client(db.Model):
    __tablename__ = 'clients'
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

    # Notatka o kliencie
    notes = db.Column(db.Text, nullable=True)

    # Właściciel klienta (kto go utworzył)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relacja: dostęp do danych użytkownika przez client.created_by
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_clients')

    def __repr__(self):
        return f"<Client {self.client_name}>"