# modules/calculator/services/shipping_service.py
"""
Serwis wysyłki - integracja z GlobKurier API.
Wyciągnięty z routers.py (linie 84-313).
"""

import time
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Konfiguracja timeout i retry
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_DELAY = 2
RETRYABLE_STATUS_CODES = [502, 503, 504]


def make_request_with_retry(request_func, request_name, *args, **kwargs):
    """
    Wykonuje request HTTP z mechanizmem retry dla błędów tymczasowych.

    Args:
        request_func: Funkcja requests (get/post)
        request_name: Nazwa requestu do logowania
        *args, **kwargs: Argumenty przekazywane do request_func

    Returns:
        Response lub None jeśli wszystkie próby się nie powiodły
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            if 'timeout' not in kwargs:
                kwargs['timeout'] = REQUEST_TIMEOUT

            current_app.logger.info(
                f">>> shipping: {request_name} - próba {attempt + 1}/{MAX_RETRIES + 1}"
            )
            response = request_func(*args, **kwargs)

            if response.status_code == 200 or response.status_code not in RETRYABLE_STATUS_CODES:
                return response

            if attempt < MAX_RETRIES:
                current_app.logger.warning(
                    f">>> shipping: {request_name} - błąd {response.status_code}, "
                    f"retry za {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
                continue

            return response

        except requests.exceptions.Timeout:
            current_app.logger.error(
                f">>> shipping: {request_name} - timeout po {REQUEST_TIMEOUT}s"
            )
            if attempt < MAX_RETRIES:
                current_app.logger.warning(
                    f">>> shipping: {request_name} - retry za {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
                continue
            else:
                raise

        except requests.exceptions.RequestException as e:
            current_app.logger.error(
                f">>> shipping: {request_name} - wyjątek: {e}"
            )
            if attempt < MAX_RETRIES:
                current_app.logger.warning(
                    f">>> shipping: {request_name} - retry za {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
                continue
            else:
                raise

    return None


def _cena_liczbowa(wartosc):
    """Czy cena z GlobKuriera nadaje się do liczenia.

    Jedyna definicja „poprawnej ceny" w tym module — korzystają z niej i
    serializuj_oferty (filtr u źródła), i cheapest_with_packing (ścieżka bota).
    Dwie osobne kopie tego warunku już raz się rozjechały: filtr bota nie
    wykluczał boola, więc True przechodziło i liczyło się jako 1 zł, czyli
    oferta najtańsza. bool jest w Pythonie podklasą int, stąd jawne wykluczenie.
    """
    return not isinstance(wartosc, bool) and isinstance(wartosc, (int, float))


def serializuj_oferty(products):
    """Surowa lista produktów z GlobKuriera -> lista ofert do dalszego przeliczenia.

    Oferty bez liczbowej ceny (pusty string, None) są tu ODRZUCANE, a nie
    przepuszczane z pustą/zerową ceną: dalej w łańcuchu _liczba() w
    apply_shipping_markup zamienia taki brak na 0.00 zł, a oferta za 0 zł
    wygrywa sortowanie jako „najtańsza" i daje się zapisać do wyceny klienta.
    Filtrujemy u źródła, żeby KAŻDY konsument (panel, bot) dostawał już czystą
    listę; cheapest_with_packing broni się dodatkowo tym samym predykatem
    (_cena_liczbowa), bo bierze listę podaną przez wywołującego.

    Czysta funkcja (bez requests/current_app) — dzięki temu testowalna bez
    mockowania wywołania HTTP do GlobKuriera.
    """
    oferty = []
    for product in products or []:
        cena = product.get("grossPrice")
        if not _cena_liczbowa(cena):
            continue
        oferty.append({
            "carrierName": product.get("carrierName", "Nieznany"),
            "grossPrice": cena,
            "netPrice": round(cena / 1.23, 2),
            "carrierLogoLink": product.get("carrierLogoLink", ""),
        })
    return oferty


def get_shipping_quotes(shipping_params, glob_config):
    """
    Pobiera wyceny wysyłki z GlobKurier API.

    Args:
        shipping_params: Słownik z parametrami paczki (length, width, height, weight, kody pocztowe)
        glob_config: Konfiguracja GlobKurier (endpoint, login, password)

    Returns:
        tuple: (lista wyników, kod HTTP) lub (słownik błędu, kod HTTP)
    """
    # Walidacja wymiarów
    try:
        original_length = float(shipping_params.get("length", 0))
        original_width = float(shipping_params.get("width", 0))
        original_height = float(shipping_params.get("height", 0))
        weight = float(shipping_params.get("weight", 0))
    except ValueError:
        return {"success": False, "error": "Bledne dane wejsciowe"}, 400

    if original_length <= 0 or original_width <= 0 or original_height <= 0 or weight <= 0:
        return {"success": False, "error": "Nieprawidlowe wymiary lub waga"}, 400

    # Dodajemy 5 cm do każdego wymiaru i konwertujemy na liczbę całkowitą
    length_int = int(round(original_length + 5))
    width_int = int(round(original_width + 5))
    height_int = int(round(original_height + 5))

    weight_2dec = round(weight, 2)
    weight_str = f"{weight_2dec:.2f}"

    query_params = {
        "width": width_int,
        "height": height_int,
        "length": length_int,
        "weight": weight_str,
        "quantity": 1,
        "senderCountryId": shipping_params.get("senderCountryId", "1"),
        "receiverCountryId": shipping_params.get("receiverCountryId", "1"),
        "senderPostCode": shipping_params.get("senderPostCode", "01-001"),
        "receiverPostCode": shipping_params.get("receiverPostCode", "41-100"),
    }

    # === Logowanie do GlobKurier ===
    auth_url = glob_config["endpoint"] + "/auth/login"
    login_payload = {
        "email": glob_config["login"],
        "password": glob_config["password"],
    }
    headers = {
        "Content-Type": "application/json",
        "accept-language": "en",
    }

    try:
        auth_response = make_request_with_retry(
            requests.post, "auth/login", auth_url, headers=headers, json=login_payload
        )

        if not auth_response:
            return {
                "success": False,
                "error": "Serwis kurierski chwilowo niedostepny. Sprobuj ponownie za chwile."
            }, 503

        if auth_response.status_code != 200:
            return {
                "success": False,
                "error": "Blad logowania do serwisu kurierskiego",
            }, 401

        auth_data = auth_response.json()
        token = auth_data.get("token")
        if not token:
            return {"success": False, "error": "Nie otrzymano tokena autoryzacyjnego"}, 401

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Serwis kurierski nie odpowiada. Sprobuj ponownie za chwile."
        }, 504
    except Exception as e:
        current_app.logger.error(f">>> shipping: Wyjątek podczas logowania: {e}")
        return {"success": False, "error": "Blad polaczenia z serwisem kurierskim"}, 500

    # === Pobieranie wycen wysyłki ===
    products_url = glob_config["endpoint"] + "/products"
    headers_quote = {
        "accept-language": "en",
        "x-auth-token": token,
    }

    try:
        quote_response = make_request_with_retry(
            requests.get, "products", products_url, headers=headers_quote, params=query_params
        )

        if not quote_response:
            return {
                "success": False,
                "error": "Serwis kurierski chwilowo niedostepny. Sprobuj ponownie za chwile."
            }, 503

        if quote_response.status_code != 200:
            current_app.logger.error(
                ">>> shipping: Błąd pobierania wyceny, status: %s, treść: %s",
                quote_response.status_code,
                quote_response.text[:500],
            )
            return {
                "success": False,
                "error": "Nie udalo sie pobrac wyceny wysylki",
            }, quote_response.status_code

        quote_data = quote_response.json()

        # Łączymy wszystkie kategorie produktów
        all_products = []
        for category in quote_data:
            items = quote_data[category]
            if isinstance(items, list):
                all_products.extend(items)
            else:
                all_products.append(items)

        if not all_products:
            return [], 200

        result = serializuj_oferty(all_products)

        current_app.logger.info(f">>> shipping: Zwrócono {len(result)} opcji wysyłki")
        return result, 200

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Serwis kurierski nie odpowiada. Sprobuj ponownie za chwile."
        }, 504
    except Exception as e:
        current_app.logger.error(f">>> shipping: Wyjątek podczas pobierania wyceny: {e}")
        return {"success": False, "error": "Blad podczas pobierania wyceny wysylki"}, 500


def aggregate_package(products):
    """Wymiary i waga paczki dla listy produktow — odwzorowuje computeAggregatedData
    (calculator-core.js): length=max(dl)+5, width=max(szer)+5, height=suma(grubosc x szt)+5,
    weight=suma(dl*szer*gr*szt / 1e6 * 800 kg/m3). Produkty bez poprawnych wymiarow pomijane.
    get_shipping_quotes dokłada kolejne +5 do kazdego wymiaru (parytet z UI: JS+5, backend+5)."""
    max_l = max_w = 0.0
    sum_h = 0.0
    weight = 0.0
    for p in products or []:
        try:
            length = float(p.get("length") or 0)
            width = float(p.get("width") or 0)
            thickness = float(p.get("thickness") or 0)
            quantity = int(p.get("quantity") or 1)
        except (TypeError, ValueError):
            continue
        if length <= 0 or width <= 0 or thickness <= 0:
            continue
        if length > max_l:
            max_l = length
        if width > max_w:
            max_w = width
        sum_h += thickness * quantity
        weight += (length * width * thickness / 1_000_000.0) * 800 * quantity
    return {
        "length": max_l + 5,
        "width": max_w + 5,
        "height": sum_h + 5,
        "weight": round(weight, 2),
        "quantity": 1,
        "senderCountryId": "1",
        "receiverCountryId": "1",
    }


def cheapest_with_packing(quotes, config=None):
    """Z listy wycen kurierskich (z get_shipping_quotes) wybiera NAJTANSZA PO
    CENIE KONCOWEJ i dokłada narzut wg ustawień z panelu.

    Wybór po cenie końcowej, a nie surowej: przy progu kolejności potrafią się
    różnić, bo tańszy surowo kurier może złapać dopłatę, a droższy nie. Klient
    płaci cenę końcową, więc to ona decyduje.

    Parametr `config` służy testom (czysta funkcja bez bazy). Produkcja woła bez
    niego i konfiguracja doczytuje się z calculator_settings.

    Zwraca dict z carrier_name i cenami albo None gdy brak liczbowych cen."""
    from modules.calculator.services.shipping_pricing import (
        apply_shipping_markup, load_shipping_config,
    )

    valid = [q for q in (quotes or []) if _cena_liczbowa(q.get("grossPrice"))]
    if not valid:
        return None

    config = config if config is not None else load_shipping_config()
    wyliczone = [(q, apply_shipping_markup(q["grossPrice"], config)) for q in valid]
    cheapest, markup = min(wyliczone, key=lambda para: para[1]["final_brutto"])

    return {
        "carrier_name": cheapest.get("carrierName") or "Kurier",
        "shipping_brutto": markup["final_brutto"],
        "shipping_netto": markup["final_netto"],
        "raw_brutto": markup["raw_brutto"],
        "raw_netto": markup["raw_netto"],
    }
