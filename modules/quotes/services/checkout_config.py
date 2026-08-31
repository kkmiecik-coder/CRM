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


# Nazwa metody dostawy dla odbioru osobistego — ta sama, którą wstawia panel
# handlowca (baselinker.js:1004), żeby BaseLinker widział jedną wartość
# niezależnie od tego, kto złożył zamówienie.
ODBIOR_OSOBISTY = "Odbiór osobisty"

# Znacznik zapisywany na kliencie przy odbiorze osobistym
# (client_accept_quote_with_data: delivery_address = 'ODBIÓR OSOBISTY').
_ZNACZNIKI_ODBIORU = ("odbiór osobisty", "odbior osobisty")


def _na_float(wartosc):
    """Decimal/None/str -> float. Brak wartości = 0.0 (a nie wyjątek)."""
    if wartosc is None:
        return 0.0
    return float(wartosc)


def _adres_wskazuje_odbior_osobisty(quote):
    """Czy adres dostawy zapisany na kliencie to znacznik odbioru osobistego.

    Drugie źródło prawdy obok pola z formularza — i potrzebne, bo wycena
    zaakceptowana WCZEŚNIEJ nie przechodzi już przez zapis danych dostawy:
    wtedy pole z bieżącego żądania nie ma jak trafić na klienta, a jedynym
    śladem wyboru zostaje ten adres. Bez tego sprawdzenia zamówienie jechałoby
    kurierem pod adres „ODBIÓR OSOBISTY".
    """
    client = getattr(quote, 'client', None)
    adres = (getattr(client, 'delivery_address', None) or '').strip().lower()
    return adres in _ZNACZNIKI_ODBIORU


def build_checkout_order_config(quote, order_source_id, is_self_pickup=False):
    """Konfiguracja dla BaselinkerService.create_order_from_quote.

    quote            — obiekt Quote (albo dowolny z polami quote_type,
                       courier_name, shipping_cost_netto/brutto)
    order_source_id  — baselinker_id źródła „Dębuś VPS" (ID_ZRODLA_DEBUS)
    is_self_pickup   — wybór klienta z formularza zamówienia
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

    # Odbiór osobisty ma pierwszeństwo nad kurierem z wyceny: kurier w wycenie
    # jest propozycją handlowca, a to klient płaci i to on wybiera.
    odbior_osobisty = bool(is_self_pickup) or _adres_wskazuje_odbior_osobisty(quote)
    if odbior_osobisty:
        dostawa = ODBIOR_OSOBISTY
        wysylka = 0.0
    else:
        dostawa = quote.courier_name or ODBIOR_OSOBISTY

    return {
        "order_source_id": order_source_id,
        "payment_method": "Przelew bankowy",
        "delivery_method": dostawa,
        "delivery_country": "PL",
        "shipping_cost_override": wysylka,
        "include_attachment": True,
    }
