# -*- coding: utf-8 -*-
"""
Serializery trakowni.

Serializer mobilny jest zbudowany na BIAŁEJ LIŚCIE, nie na wykluczeniach.
Gdyby działał odwrotnie, dodanie nowej kolumny do modelu w przyszłości
po cichu poszerzyłoby odpowiedź wysyłaną na tablet — i cała kontrola
nad tym, czego pracownik nie widzi, przestałaby obowiązywać.
"""

# Pola, których obecność w odpowiedzi mobilnej jest błędem. Lista istnieje
# wyłącznie po to, żeby dało się to zaasertować w teście.
DEVICE_FORBIDDEN_FIELDS = frozenset({
    'declared_volume_m3', 'declared_logs_count', 'price_per_m3',
    'declared_value', 'agreed_volume_m3', 'notes', 'settlement_notes',
    'deviation_threshold_pct',
})


def _float(value):
    return float(value) if value is not None else None


def _isoformat(value):
    return value.isoformat() if value is not None else None


def _date(value):
    return value.isoformat() if value is not None else None


# ── Tablet ──────────────────────────────────────────────────────────────────

def serialize_order_for_device(order, logs_count, measured_volume_m3):
    """
    Zlecenie widziane przez pracownika: identyfikacja i to, co sam zmierzył.
    Ani deklaracji, ani niczego finansowego.
    """
    delivery = order.delivery
    return {
        'id': order.id,
        'order_number': order.order_number,
        'species': order.species.name if order.species else None,
        'supplier_name': delivery.supplier.name if delivery and delivery.supplier else None,
        'invoice_number': delivery.invoice_number if delivery else None,
        'delivery_date': _date(delivery.delivery_date) if delivery else None,
        'status': order.status,
        'logs_count': logs_count,
        'measured_volume_m3': _float(measured_volume_m3),
        'started_at': _isoformat(order.started_at),
    }


def serialize_log_for_device(log):
    return {
        'id': log.id,
        'sequence_no': log.sequence_no,
        'mid_circumference_cm': _float(log.mid_circumference_cm),
        'length_cm': _float(log.length_cm),
        'volume_m3': _float(log.volume_m3),
        'measured_at': _isoformat(log.measured_at),
    }


# ── Panel ───────────────────────────────────────────────────────────────────

def serialize_order_for_panel(order, logs_count, measured_volume_m3, differences):
    delivery = order.delivery
    out = {
        'id': order.id,
        'order_number': order.order_number,
        'status': order.status,
        'species': order.species.name if order.species else None,
        'species_id': order.species_id,
        'delivery_id': order.delivery_id,
        'supplier_name': delivery.supplier.name if delivery and delivery.supplier else None,
        'invoice_number': delivery.invoice_number if delivery else None,
        'invoice_date': _date(delivery.invoice_date) if delivery else None,
        'delivery_date': _date(delivery.delivery_date) if delivery else None,
        'declared_volume_m3': _float(order.declared_volume_m3),
        'declared_logs_count': order.declared_logs_count,
        'price_per_m3': _float(order.price_per_m3),
        'declared_value': _float(order.declared_value),
        'agreed_volume_m3': _float(order.agreed_volume_m3),
        'measured_volume_m3': _float(measured_volume_m3),
        'logs_count': logs_count,
        'notes': order.notes,
        'settlement_notes': order.settlement_notes,
        'started_at': _isoformat(order.started_at),
        'completed_at': _isoformat(order.completed_at),
    }
    out.update({
        'difference_m3': _float(differences.get('difference_m3')),
        'difference_pct': _float(differences.get('difference_pct')),
        'difference_value': _float(differences.get('difference_value')),
        'is_deviation': differences.get('is_deviation', False),
    })
    return out


def serialize_log_for_panel(log):
    out = serialize_log_for_device(log)
    out.update({
        'device_id': log.device_id,
        'created_at': _isoformat(log.created_at),
        'is_deleted': bool(log.is_deleted),
    })
    return out
