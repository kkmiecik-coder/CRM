from extensions import db
from datetime import datetime
import secrets
import string


class PublicSession(db.Model):
    __tablename__ = 'public_sessions'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    inputs = db.Column(db.Text)  # JSON jako string
    variant = db.Column(db.String(100))
    finishing = db.Column(db.String(100))
    color = db.Column(db.String(100))
    duration_ms = db.Column(db.Integer)
    user_agent = db.Column(db.Text)
    ip_address = db.Column(db.String(50))


class CalculatorInquiry(db.Model):
    __tablename__ = 'pub_calc_requests'

    id = db.Column(db.Integer, primary_key=True)
    inquiry_number = db.Column(db.String(6), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Dane klienta
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False)

    # Źródło zapytania
    source = db.Column(db.String(20), nullable=False)  # 'b2b' lub 'retail'

    # Dane wyceny (JSON)
    dimensions = db.Column(db.Text)  # JSON: {length, width, thickness, quantity}
    finishing = db.Column(db.String(100))
    finishing_variant = db.Column(db.String(100))
    finishing_color = db.Column(db.String(100))
    calculations = db.Column(db.Text)  # JSON z wynikami kalkulacji

    # Metadane
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.Text)

    @staticmethod
    def generate_inquiry_number():
        """Generuje unikalny 6-znakowy numer zapytania."""
        chars = string.ascii_uppercase + string.digits
        while True:
            number = ''.join(secrets.choice(chars) for _ in range(6))
            if not CalculatorInquiry.query.filter_by(inquiry_number=number).first():
                return number