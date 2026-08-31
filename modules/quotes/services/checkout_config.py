# -*- coding: utf-8 -*-
"""
Konfiguracja zamówienia dla checkoutu klienckiego.

Panel BaseLinkera składa `config` w JavaScripcie (baselinker.js:1568-1601)
i wysyła go w żądaniu. Checkout klienta nie ma skąd go wziąć, więc buduje
go tutaj — serwerowo, bez sesji zalogowanego użytkownika.

Świadomie NIE ustawiamy client_data: podanie go zastępuje dane z bazy
w całości, a checkout zapisuje dane klienta na obiekcie Client zanim
utworzy zamówienie.

JEDNO ŹRÓDŁO PRAWDY O SPOSOBIE DOSTAWY
======================================
Adres, pod który zamówienie faktycznie pojedzie, bierze się WYŁĄCZNIE
z danych zapisanych na kliencie (service.py — delivery_address, delivery_city
itd.). Pole `is_self_pickup` z formularza nie ma jak tam trafić: dane dostawy
zapisuje tylko akceptacja wyceny, a dla wyceny zaakceptowanej wcześniej
akceptacja się już nie wykonuje. Dlatego dane klienta są jedynym źródłem
adresu, a formularz nie jest ich drugą, równoległą wersją: może co najwyżej
adres ZDJĄĆ (odbiór osobisty), nigdy go wymyślić.

Stąd dwa kierunki sprzeczności rozstrzygnięte niesymetrycznie:

* formularz „odbiór osobisty" + realny adres na kliencie — składamy jako
  odbiór osobisty i JEDNOCZEŚNIE zdejmujemy adres z zamówienia
  (`delivery_override`). Dawniej zamówienie szło z metodą „Odbiór osobisty",
  zerowym kosztem dostawy I pełnym adresem kurierskim: magazyn dostawał
  sprzeczne zlecenie, a przesyłka mogła pojechać za darmo. Wybór klienta
  honorujemy, bo to jego pieniądze i jego świeża decyzja — ale musi być
  spójny w całym zamówieniu. Danych na kliencie NIE ruszamy: adres należy
  też do innych jego wycen;

* formularz „kurier" + adres „ODBIÓR OSOBISTY" na kliencie — zamówienia NIE
  SKŁADAMY (KonfliktDostawy). Dawniej po cichu wygrywał odbiór osobisty, więc
  klient czekał na przesyłkę, która nigdy nie wyjechała. Honorowanie wyboru
  wymagałoby tu WYMYŚLENIA adresu — czyli wzięcia go z pól formularza, których
  nikt nie zweryfikował i których ta ścieżka celowo nie zapisuje. Wolimy
  odmowę z prośbą o kontakt niż przesyłkę pod adres z niesprawdzonego pola.

Sytuacja jest przy tym rzadka: przy wycenie akceptowanej TERAZ akceptacja
zapisuje dane dostawy prosto z tego samego formularza, więc oba źródła
zgadzają się z definicji, a modal zaznacza „odbiór osobisty" z góry, gdy na
kliencie siedzi znacznik odbioru (client_accept_modal.js).
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


class KonfliktDostawy(Exception):
    """Formularz mówi co innego o dostawie niż dane zapisane na kliencie.

    Świadomie wyjątek, a nie „wybierz jedno i jedź dalej": to jedyny sposób,
    żeby ta sprzeczność nie zamieniła się w milczącą decyzję o cudzych
    pieniądzach. Łapie go checkout_service i zamienia na odmowę z prośbą
    o kontakt.
    """


def _na_float(wartosc):
    """Decimal/None/str -> float. Brak wartości = 0.0 (a nie wyjątek)."""
    if wartosc is None:
        return 0.0
    return float(wartosc)


def _adres_dostawy(quote):
    """Adres dostawy zapisany na kliencie wyceny (przycięty, może być pusty)."""
    client = getattr(quote, 'client', None)
    return (getattr(client, 'delivery_address', None) or '').strip()


def _adres_wskazuje_odbior_osobisty(quote):
    """Czy adres dostawy zapisany na kliencie to znacznik odbioru osobistego."""
    return _adres_dostawy(quote).lower() in _ZNACZNIKI_ODBIORU


def rozstrzygnij_odbior_osobisty(quote, is_self_pickup):
    """(czy odbiór osobisty, czy zdjąć adres z zamówienia). Rzuca KonfliktDostawy.

    Drugi element mówi, czy do konfiguracji trzeba dołożyć `delivery_override`:
    jest True tylko wtedy, gdy klient wybrał odbiór osobisty, a na kliencie
    siedzi realny adres — patrz docstring modułu.

    Brak adresu na kliencie NIE jest sprzecznością z niczym: nie ma dwóch
    źródeł, które mówiłyby co innego, więc decyduje formularz. Ten przypadek
    zdarza się przy wycenach zaakceptowanych wewnętrznie, bez danych dostawy.
    """
    zapisany_odbior = _adres_wskazuje_odbior_osobisty(quote)
    ma_realny_adres = bool(_adres_dostawy(quote)) and not zapisany_odbior
    z_formularza = bool(is_self_pickup)

    if not z_formularza and zapisany_odbior:
        raise KonfliktDostawy(
            "formularz wskazuje dostawę kurierem, a na kliencie zapisany jest "
            "odbiór osobisty")

    return (z_formularza or zapisany_odbior), (z_formularza and ma_realny_adres)


def build_checkout_order_config(quote, order_source_id, is_self_pickup=False):
    """Konfiguracja dla BaselinkerService.create_order_from_quote.

    quote            — obiekt Quote (albo dowolny z polami quote_type,
                       courier_name, shipping_cost_netto/brutto)
    order_source_id  — baselinker_id źródła „Dębuś VPS" (ID_ZRODLA_DEBUS)
    is_self_pickup   — wybór klienta z formularza zamówienia

    Rzuca KonfliktDostawy, gdy formularz przeczy danym dostawy zapisanym
    na kliencie.
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

    odbior_osobisty, zdejmij_adres = rozstrzygnij_odbior_osobisty(
        quote, is_self_pickup)
    if odbior_osobisty:
        dostawa = ODBIOR_OSOBISTY
        wysylka = 0.0
    else:
        dostawa = quote.courier_name or ODBIOR_OSOBISTY

    config = {
        "order_source_id": order_source_id,
        "payment_method": "Przelew bankowy",
        "delivery_method": dostawa,
        "delivery_country": "PL",
        "shipping_cost_override": wysylka,
        "include_attachment": True,
    }

    if zdejmij_adres:
        # Zamówienie z metodą „Odbiór osobisty" nie może nieść adresu
        # kurierskiego — ten sam znacznik, który przy odbiorze zapisuje
        # akceptacja wyceny (client_accept_quote_with_data).
        config["delivery_override"] = {
            "delivery_address": ODBIOR_OSOBISTY.upper(),
            "delivery_city": ODBIOR_OSOBISTY.upper(),
            "delivery_postcode": "",
            "delivery_region": "",
            "delivery_company": "",
        }

    return config
