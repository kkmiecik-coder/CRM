# -*- coding: utf-8 -*-
"""
Biała lista pól odpowiedzi kierownika (spec 2.6). Serializatory budują słowniki od zera; ten moduł służy testom,
które przechodzą każdą odpowiedź każdej trasy i szukają zakazanych kluczy na dowolnym poziomie zagnieżdżenia.
"""

# Klucze, których nie ma w żadnej odpowiedzi blueprintu: dane kontaktowe, adres dostawy i pieniądze.
ZAKAZANE_KLUCZE = frozenset({
    'client_email', 'client_phone', 'email', 'phone', 'telefon', 'delivery_address', 'adres',
    'price_per_m3', 'declared_value', 'difference_value', 'settlement_notes', 'total_value_net', 'value_net',
    'wartosc', 'wartosc_netto', 'shipping_price', 'shipping_label_base64', 'cena',
})


def zakazane_w(obiekt, _sciezka=''):
    """Ścieżki zakazanych kluczy w obiekcie (rekurencyjnie po słownikach i listach), np. `a[0].client_phone`."""
    znalezione = []
    if isinstance(obiekt, dict):
        for klucz, wartosc in obiekt.items():
            sciezka = '%s.%s' % (_sciezka, klucz) if _sciezka else str(klucz)
            if klucz in ZAKAZANE_KLUCZE:
                znalezione.append(sciezka)
            znalezione.extend(zakazane_w(wartosc, sciezka))
    elif isinstance(obiekt, (list, tuple)):
        for i, element in enumerate(obiekt):
            znalezione.extend(zakazane_w(element, '%s[%d]' % (_sciezka, i)))
    return znalezione
