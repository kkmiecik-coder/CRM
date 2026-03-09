# modules/calculator/services/draft_service.py
"""
Serwis do obslugi draftow kalkulatora (server-side backup).
"""

from extensions import db
from modules.calculator.models import CalculatorDraft
import logging

logger = logging.getLogger(__name__)


def save_draft(user_id, draft_data):
    """Zapisz lub zaktualizuj draft dla uzytkownika (upsert)."""
    try:
        draft = CalculatorDraft.query.filter_by(user_id=user_id).first()

        if draft:
            draft.draft_data = draft_data
        else:
            draft = CalculatorDraft(user_id=user_id, draft_data=draft_data)
            db.session.add(draft)

        db.session.commit()
        return {'success': True, 'draft': draft.to_dict()}, 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Blad zapisu draftu dla user_id={user_id}: {e}")
        return {'success': False, 'error': 'Blad zapisu draftu'}, 500


def load_draft(user_id):
    """Zaladuj draft dla uzytkownika."""
    try:
        draft = CalculatorDraft.query.filter_by(user_id=user_id).first()

        if draft:
            return {'success': True, **draft.to_dict()}, 200
        else:
            return {'success': True, 'draft_data': None}, 200

    except Exception as e:
        logger.error(f"Blad ladowania draftu dla user_id={user_id}: {e}")
        return {'success': False, 'error': 'Blad ladowania draftu'}, 500


def delete_draft(user_id):
    """Usun draft dla uzytkownika."""
    try:
        draft = CalculatorDraft.query.filter_by(user_id=user_id).first()

        if draft:
            db.session.delete(draft)
            db.session.commit()
            return {'success': True, 'message': 'Draft usuniety'}, 200
        else:
            return {'success': True, 'message': 'Brak draftu do usuniecia'}, 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Blad usuwania draftu dla user_id={user_id}: {e}")
        return {'success': False, 'error': 'Blad usuwania draftu'}, 500
