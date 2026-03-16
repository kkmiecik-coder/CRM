# app/modules/settings/models.py
"""
Modele modułu ustawień aplikacji
================================
"""

from datetime import datetime
from extensions import db


class AppSetting(db.Model):
    """Ustawienia aplikacji (klucz-wartość)"""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_value(cls, key, default=None):
        try:
            setting = cls.query.filter_by(setting_key=key).first()
            return setting.setting_value if setting else default
        except Exception:
            return default

    @classmethod
    def set_value(cls, key, value, description=None):
        setting = cls.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = str(value)
            if description is not None:
                setting.description = description
        else:
            setting = cls(setting_key=key, setting_value=str(value), description=description)
            db.session.add(setting)
        db.session.commit()
        return setting

    def __repr__(self):
        return f'<AppSetting {self.setting_key}={self.setting_value}>'
