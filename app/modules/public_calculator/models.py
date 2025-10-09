from extensions import db
from datetime import datetime

class PublicSession(db.Model):
    __tablename__ = 'public_sessions'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    inputs = db.Column(db.Text)  # JSON jako string
    variant = db.Column(db.String(100))
    finishing = db.Column(db.String(100))  # 🧨 TO DODAJ
    color = db.Column(db.String(100))      # 🧨 TO DODAJ
    duration_ms = db.Column(db.Integer)
    user_agent = db.Column(db.Text)
    ip_address = db.Column(db.String(50))