# -*- coding: utf-8 -*-
"""
Konfiguracja zamówienia dla checkoutu klienckiego.

Panel BaseLinkera składa `config` w JavaScripcie (baselinker.js:1568-1601)
i wysyła go w żądaniu. Checkout klienta nie ma skąd go wziąć, więc buduje
go tutaj — serwerowo, bez sesji zalogowanego użytkownika.

Świadomie NIE ustawiamy client_data: podanie go zastępuje dane z bazy
w całości, a checkout zapisuje dane klienta na obiekcie Client zanim
utworzy zamówienie.
"""


# Realne id źródła „Dębuś VPS" w panelu BaseLinkera (Ustawienia -> Źródła
# zamówień). Ta sama wartość, którą wstawia migracja
# migrations/2026-08-30-zrodlo-zamowien-debus.sql — i po NIEJ, a nie po nazwie,
# szuka się źródła w bazie. Nazwa jest polem redagowalnym w panelu: dopóki
# wiązała nas nazwa, samo przemianowanie źródła kładło cały checkout.
ID_ZRODLA_DEBUS = 85727


def _na_float(wartosc):
    """Decimal/None/str -> float. Brak wartości = 0.0 (a nie wyjątek)."""
    if wartosc is None:
        return 0.0
    return float(wartosc)


def build_checkout_order_config(quote, order_source_id):
    """Konfiguracja dla BaselinkerService.create_order_from_quote.

    quote            — obiekt Quote (albo dowolny z polami quote_type,
                       courier_name, shipping_cost_netto/brutto)
    order_source_id  — baselinker_id źródła „Dębuś VPS" (ID_ZRODLA_DEBUS)
    """
    # Tryb cen czytamy tak samo jak serwis (service.py:527): getattr z domyślnym
    # 'brutto', bo pusta wartość w kolumnie też ma znaczyć brutto.
    tryb_cen = getattr(quote, 'quote_type', 'brutto') or 'brutto'

    # Wycena netto ma pozycje netto — koszt dostawy musi jechać tą samą stroną,
    # inaczej suma w BaseLinkerze rozjedzie się z zaakceptowaną wyceną.
    if tryb_cen == 'netto':
        wysylka = _na_float(quote.shipping_cost_netto)
    else:
        wysylka = _na_float(quote.shipping_cost_brutto)

    return {
        "order_source_id": order_source_id,
        "payment_method": "Przelew bankowy",
        "delivery_method": quote.courier_name or "Odbiór osobisty",
        "delivery_country": "PL",
        "shipping_cost_override": wysylka,
        "include_attachment": True,
    }
