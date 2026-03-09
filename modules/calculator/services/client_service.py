# modules/calculator/services/client_service.py
"""
Serwis klientów - wyszukiwanie klientów z kalkulatora.
Wyciągnięty z routers.py (linie 631-698).
"""

import logging

logger = logging.getLogger(__name__)


def search_clients_by_term(term, current_user_id):
    """
    Wyszukuje klientów po nazwie/loginie/emailu/telefonie.
    Segreguje wyniki na własnych (current_user_id) i cudzych klientów.

    Args:
        term: Fraza wyszukiwania (min 3 znaki)
        current_user_id: ID aktualnego użytkownika

    Returns:
        list: Lista klientów (własni najpierw, potem cudzi)
    """
    from modules.clients.models import Client

    base_query = Client.query.filter(
        (Client.client_number.ilike(f"%{term}%"))
        | (Client.client_name.ilike(f"%{term}%"))
        | (Client.email.ilike(f"%{term}%"))
        | (Client.phone.ilike(f"%{term}%"))
    )

    matches = base_query.all()

    own_clients = []
    other_clients = []

    for c in matches:
        # Priorytet: client_number (imię i nazwisko) nad client_name
        if c.client_number and c.client_number.strip():
            display_name = c.client_number.strip()
            if (
                c.client_name
                and c.client_name.strip()
                and c.client_name.strip() != c.client_number.strip()
            ):
                display_name = f"{c.client_number.strip()} ({c.client_name.strip()})"
        elif c.client_name and c.client_name.strip():
            display_name = c.client_name.strip()
        else:
            display_name = f"Klient ID: {c.id}"

        client_data = {
            "id": c.id,
            "name": display_name,
            "email": c.email or "",
            "phone": c.phone or "",
            "is_own_client": c.created_by_user_id == current_user_id,
        }

        if c.created_by_user_id == current_user_id:
            own_clients.append(client_data)
        else:
            other_clients.append(client_data)

    return own_clients + other_clients
