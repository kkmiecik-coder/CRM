# modules/clients/models.py
from extensions import db

class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    client_number = db.Column(db.String(20), unique=True, nullable=False)
    client_name = db.Column(db.String(255))
    client_delivery_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    
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
    
    # Źródło pochodzenia
    source = db.Column(db.String(100))
    
    # ✅ NOWE: Właściciel klienta (kto go utworzył)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # ✅ NOWA RELACJA: dostęp do danych użytkownika przez client.created_by
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], backref='created_clients')
    
    def __repr__(self):
        return f"<Client {self.client_name}>"