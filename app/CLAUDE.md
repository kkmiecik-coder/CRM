# Notatki projektowe - CRM

## Zasady dla Claude

- **Proaktywnie aktualizuj ten plik** gdy dowiesz się czegoś istotnego o projekcie
- Zapisuj: ustalenia z użytkownikiem, odkryte wzorce w kodzie, ważne decyzje architektoniczne

---

## Workflow wdrażania

**WAŻNE:** Pracujemy na lokalnej kopii plików z serwera produkcyjnego.
- Claude modyfikuje pliki lokalne w `/Users/konradkmiecik/Documents/GitHub/CRM/app/`
- Użytkownik (Konrad) przesyła zmiany przez FTP na serwer
- Testowanie odbywa się na serwerze produkcyjnym po wgraniu plików

## Baza danych

- Nie używamy Alembic/Flask-Migrate
- Migracje bazy: surowe SQL do ręcznego wykonania na serwerze
- SQL migracji należy dostarczyć na końcu zmian (nie jako osobny plik migracji)

## Moduł Production

### Struktura stanowisk (stations)
6 stanowisk w kolejności workflow:
1. cutting (wycinanie)
2. assembly (składanie)
3. gluing (sklejanie)
4. formatting (formatowanie)
5. finishing (wykańczanie)
6. packaging (pakowanie)

### Format ID produktu
`YY_NNNNN_S` np. `25_05248_1` = rok 2025, zamówienie 5248, pozycja 1

**UWAGA (2025-11):** ID oznacza teraz "pozycję w zamówieniu", nie "pojedynczą sztukę".
Ilość sztuk przechowywana w kolumnie `quantity`.

### Statusy produktów
- `czeka_na_wyciecie` → `czeka_na_skladanie` → `czeka_na_sklejanie` → `czeka_na_formatowanie` → `czeka_na_wykanczanie` → `czeka_na_pakowanie` → `spakowane`
- Dodatkowe: `anulowane`, `wstrzymane`, `w_realizacji`

### Model ProductionItem - kluczowe kolumny (2025-11)

**Ilość produktów:**
- `quantity` - ilość sztuk z zamówienia (domyślnie 1)
- `quantity_done_{station}` - ile sztuk wykonano na danym stanowisku (0 do quantity)

**Śledzenie czasu (per stanowisko):**
- `{station}_completed_at` - timestamp gdy quantity_done == quantity

**Usunięte kolumny:**
- `{station}_started_at` - usunięte
- `{station}_duration_minutes` - usunięte
- `{station}_assigned_worker_id` - usunięte (brak systemu pracowników)
- `{station}_marked_done` - zastąpione przez quantity_done

### Decyzje architektoniczne (2025-11)

1. **Jeden rekord = jedna pozycja zamówienia** (nie pojedyncza sztuka)
2. **Przyciski +/- zamiast checkboxów** - łatwiejsze przy dużych ilościach
3. **Scalanie produktów** - produkty o tym samym `baselinker_product_id` w ramach zamówienia są zawsze identyczne

---

## Baselinker API

### Struktura odpowiedzi getOrders

```
{
  "status": "SUCCESS",
  "orders": [
    {
      "order_id": int,              // ID zamówienia Baselinker (np. 25208907)
      "order_status_id": int,       // ID statusu w Baselinker
      "date_add": int,              // Unix timestamp utworzenia
      "date_confirmed": int,        // Unix timestamp potwierdzenia
      "user_login": string,         // Nazwa klienta
      "phone": string,
      "email": string,
      "user_comments": string,      // Uwagi klienta (przy składaniu)
      "admin_comments": string,     // Uwagi admina/sprzedawcy ← UŻYWAMY TEGO
      "currency": string,
      "payment_method": string,
      "payment_done": float,
      "delivery_method": string,
      "delivery_price": float,
      "delivery_fullname": string,
      "delivery_company": string,
      "delivery_address": string,
      "delivery_city": string,
      "delivery_postcode": string,
      "delivery_country_code": string,
      "extra_field_1": string,      // Wewnętrzny numer zamówienia (np. "1617/2025") ← UŻYWAMY
      "extra_field_2": string,
      "products": [
        {
          "order_product_id": int,   // ID produktu w zamówieniu
          "product_id": string,
          "name": string,            // Pełna nazwa produktu do parsowania
          "sku": string,
          "price_brutto": float,
          "tax_rate": int,
          "quantity": int,           // Ilość sztuk ← WAŻNE
          "weight": float
        }
      ],
      "custom_extra_fields": {}     // Dodatkowe pola customowe (słownik)
    }
  ]
}
```

### Pola używane w module Production
- `order_id` → `baselinker_order_id`
- `extra_field_1` → `client_order_number` (wewnętrzny numer klienta, np. "1617/2025")
- `admin_comments` → `order_notes` (uwagi do zamówienia)
- `products[].name` → parsowane na gatunek, wymiary, klasę drewna, technologię
- `products[].quantity` → `quantity` w ProductionItem
