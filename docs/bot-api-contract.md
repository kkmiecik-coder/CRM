# Kontrakt API bota kalkulatora (`/api/bot/*`) — integracja ze sklepem

Dokument dla zespołu sklepu PrestaShop (woodpower.pl). Opisuje **dokładne** kształty
request/response endpointów, których sklep używa przez swój server-side proxy do budowy
konfiguratora wyceny, strony `/wycena/{token}` i funkcji „przelicz ponownie".

> Źródło prawdy: `modules/calculator/routers/bot_api.py`. Przykłady poniżej to **realne**
> odpowiedzi zrzucone z endpointów (nazwy pól 1:1 z kodem).

---

## 1. Zasady wspólne

- **Bazowy URL (produkcja):** `https://crm.woodpower.pl/api/bot`
- **Autoryzacja:** nagłówek `X-Bot-Api-Key: <BOT_API_KEY>` w **każdym** żądaniu.
  Porównanie stałoczasowe; brak skonfigurowanego klucza = dostęp zamknięty.
- **Format odpowiedzi:** zawsze JSON z polem `ok` (bool).
  - Sukces: `{"ok": true, ...}`.
  - Błąd biznesowy / walidacja: `{"ok": false, "errors": [...]}` albo
    `{"ok": false, "missing_fields": [...], "errors": []}` — **ze statusem HTTP 200**.
    Kontrakt używa `ok`/`errors`, **nie** kodów HTTP.
  - **Jedyny wyjątek HTTP:** zły/brakujący klucz API → **HTTP 401**:
    ```json
    {"ok": false, "errors": [{"field": null, "code": "UNAUTHORIZED", "message": "Nieprawidłowy klucz API."}]}
    ```
- **Obiekt błędu:** `{"field": <str|null>, "code": <str>, "message": <PL, str>}`
  (walidacja wymiarów dokłada `product_index`, a czasem `limit` i `given`).
- **VAT:** 1.23 (23%). Ceny `*_netto` i `*_brutto` podawane osobno. Waluta: PLN.
- **Jednostki:** wymiary w **cm**, ceny w **PLN**.

---

## 2. `GET /api/bot/options`

Słowniki dla konfiguratora: dostępne warianty drewna (z zakresami wymiarów), globalne
limity, opcje wykończeń, typy krawędzi, grupy cenowe.

**Request:** brak ciała. Tylko nagłówek autoryzacji.

**Response 200 (realny przykład):**
```json
{
  "ok": true,
  "variants": [
    {
      "variant_code": "dab-lity-ab",
      "species": "Dąb",
      "technology": "Lity",
      "wood_class": "A/B",
      "length_min": 20.0, "length_max": 450.0,
      "width_min": 10.0, "width_max": 200.0,
      "thickness_min": 2.0, "thickness_max": 6.0
    },
    {
      "variant_code": "dab-micro-ab",
      "species": "Dąb", "technology": "Mikrowczep", "wood_class": "A/B",
      "length_min": 20.0, "length_max": 450.0,
      "width_min": 10.0, "width_max": 200.0,
      "thickness_min": 2.0, "thickness_max": 6.0
    }
  ],
  "global_limits": {
    "length_min": 20.0, "length_max": 450.0,
    "width_min": 10.0, "width_max": 200.0,
    "thickness_min": 2.0, "thickness_max": 6.0
  },
  "finishing_options": [
    {"id": 1, "full_path": "Surowe", "price_netto": 0.0, "level": 0},
    {"id": 2, "full_path": "Lakierowane", "price_netto": 200.0, "level": 0},
    {"id": 3, "full_path": "Lakierowane > Bezbarwne", "price_netto": 200.0, "level": 1}
  ],
  "edge_types": [
    {"type": "round", "per_mb": 15.0, "per_corner": 5.0}
  ],
  "client_types": ["Detal+"],
  "cutout_price_netto": 0.0,
  "round_surcharge_netto": 50.0,
  "shapes": ["rectangular", "round", "circle"],
  "vat": 1.23
}
```

- `variant_code` — identyfikator wariantu drewna używany w `selected_variant` (patrz `/calculate`).
- `finishing_options[].id` — to `finishing_option_id` w `/calculate`.
- `client_types` — dozwolone wartości `client_type` (grupa cenowa).
- Lista `variants` zawiera tylko warianty, które mają wpis w cenniku (realnie: pełny zestaw
  gatunków/technologii dębu/jesionu/buku, tu skrócony przez dane przykładu).

---

## 3. `POST /api/bot/calculate`

Liczy wycenę **bez zapisu**. Backend jest jedynym źródłem prawdy o cenie — sklep podaje
tylko parametry.

**Request:**
```json
{
  "client_type": "Detal+",
  "products": [
    {
      "index": 1,
      "length": 120, "width": 60, "thickness": 4,
      "quantity": 2,
      "shape": "rectangular",
      "selected_variant": "dab-lity-ab",
      "finishing_type": "Surowe",
      "finishing_variant": null,
      "finishing_gloss_level": null,
      "finishing_option_id": null,
      "finishing_full_path": null,
      "holes_count": 0,
      "shape_data": null,
      "edges": [{"letter": "A", "type": "round", "r_value": 5}],
      "edges_mode": "basic"
    }
  ],
  "shipping": {"netto": 0, "brutto": 0}
}
```

Pola **wymagane** per produkt: `length`, `width`, `thickness`, `quantity`, `selected_variant`.
Na poziomie wyceny wymagane: `client_type`. Reszta pól opcjonalna (`finishing_type` brak =
„Surowe"; `edges` brak = brak krawędzi; `shape` brak = `rectangular`).

**Response 200 — sukces (realny przykład, skrócone warianty niedostępne):**
```json
{
  "ok": true,
  "errors": [],
  "missing_fields": [],
  "multiplier": 1.3,
  "products": [
    {
      "index": 1,
      "errors": [],
      "variants": [
        {
          "variant_code": "dab-lity-ab",
          "available": true,
          "volume_m3": 0.0288,
          "price_per_m3": 8200.0,
          "multiplier": 1.3,
          "unit_netto": 307.008,
          "unit_brutto": 377.62,
          "total_netto": 614.02,
          "total_brutto": 755.24
        },
        {"variant_code": "dab-lity-bb", "available": false},
        {"variant_code": "dab-micro-ab", "available": true, "volume_m3": 0.0288,
         "price_per_m3": 7000.0, "multiplier": 1.3, "unit_netto": 262.08,
         "unit_brutto": 322.36, "total_netto": 524.16, "total_brutto": 644.72}
      ],
      "finishing": {"netto": 0.0, "brutto": 0.0, "price_per_m2": 0.0, "surface_m2": 0.0},
      "edges": {
        "netto": 36.0, "brutto": 44.28,
        "details": [
          {"letter": "A", "type": "round", "length_cm": 120.0,
           "price_netto": 18.0, "price_brutto": 22.14, "is_corner": false}
        ]
      }
    }
  ],
  "totals": {
    "order_netto": 614.02, "order_brutto": 755.24,
    "finishing_netto": 0.0, "finishing_brutto": 0.0,
    "edges_netto": 36.0, "edges_brutto": 44.28,
    "shipping_netto": 0.0, "shipping_brutto": 0.0,
    "total_netto": 650.02, "total_brutto": 799.52
  }
}
```

- `variants[]` zawiera **wszystkie** warianty drewna; niedostępne dla podanych wymiarów mają
  `{"available": false}` (bez cen). Wybrany wariant (`selected_variant`) liczy się do `totals.order_*`.
- `unit_netto` bywa niezaokrąglone (parytet z frontendem); ceny do prezentacji bierz z
  `total_*` / `unit_brutto`.
- `totals.total_*` = order + finishing + edges + shipping.

**Response 200 — brakujące pola (LLM/konfigurator dopytuje klienta):**
```json
{"ok": false, "missing_fields": [{"product_index": 1, "field": "width", "hint": "szerokość w cm"}], "errors": []}
```

**Response 200 — błąd walidacji wymiarów:**
```json
{
  "ok": false,
  "missing_fields": [],
  "multiplier": 1.3,
  "products": [{"index": 1, "errors": [ /* jak niżej */ ], "variants": [], "finishing": null, "edges": null}],
  "totals": null,
  "errors": [
    {"field": "length", "code": "MAX_EXCEEDED",
     "message": "Maksymalna długość to 450 cm (podano 700 cm).",
     "product_index": 1, "limit": 450, "given": 700}
  ]
}
```
Kody błędów walidacji: `MISSING`, `INVALID_TYPE`, `MIN_NOT_MET`, `MAX_EXCEEDED`,
`UNKNOWN_CLIENT_TYPE`, `VARIANT_UNAVAILABLE`, `NO_PRICELIST`.

---

## 4. `POST /api/bot/clients/find-or-create`

Dopasowuje klienta po e-mailu → telefonie → `client_number`, a jeśli żaden nie pasuje —
**zakłada nowego**. Zwraca `id` klienta do użycia w `POST /api/bot/quotes`.

**Request** (wymagane: przynajmniej jedno z `email` / `phone` / `client_number`):
```json
{"email": "jan@example.pl", "phone": "500600700", "name": "Jan Kowalski"}
```

**Response 200 (realny przykład — nowy klient):**
```json
{
  "ok": true,
  "matched": false,
  "created": true,
  "client": {"id": 1, "client_name": "Jan Kowalski", "email": "jan@example.pl", "phone": "500600700"}
}
```

> **ID klienta jest w polu `client.id`** — to wartość do przekazania jako `client_id`
> w `POST /api/bot/quotes`.

- `matched: true` — dopasowano **istniejącego, powracającego** klienta po e-mailu/telefonie.
- `created: true` — założono nowego klienta.
- Brak wszystkich trzech pól → `{"ok": false, "errors": [{"field": "email", "code": "MISSING", "message": "Podaj e-mail, telefon lub client_number, żeby dopasować lub założyć klienta."}]}`.

---

## 5. `POST /api/bot/quotes`

Tworzy pełnoprawną wycenę w CRM (widoczną dla klienta pod publicznym linkiem). Body jak
`/calculate` **plus** `client_id`; opcjonalnie `notes`. **Sklep dodaje per produkt pole
`product_type`** (`"blat" | "schody" | "parapet"`) — koncept sklepu, CRM go nie interpretuje,
ale utrwala i zwraca w `by-token`.

**Request:**
```json
{
  "client_id": 1,
  "client_type": "Detal+",
  "notes": "zapytanie ze sklepu",
  "products": [
    {
      "index": 1,
      "length": 120, "width": 60, "thickness": 4,
      "quantity": 2,
      "shape": "rectangular",
      "selected_variant": "dab-lity-ab",
      "finishing_type": "Surowe",
      "edges": [{"letter": "A", "type": "round", "r_value": 5}],
      "edges_mode": "basic",
      "product_type": "blat"
    }
  ]
}
```
- Akceptowane jest `client_type` **lub** `quote_client_type` (to samo znaczenie).
- Ceny liczy backend od zera — ewentualne ceny w payloadzie są ignorowane.

**Response 200 (realny przykład):**
```json
{
  "ok": true,
  "quote_number": "01/07/26/W",
  "quote_id": 1,
  "edit_uuid": "43d5ed3b-0c79-4fd2-b4fc-acee1d08b526",
  "public_url": "https://crm.woodpower.pl/quotes/c/7NMQ3V7IIINGNRFICRORBC9INBESJ0ZZ"
}
```

> **Skąd wziąć token do `by-token`?** Endpoint `POST /quotes` **nie** zwraca osobnego pola
> `public_token` — token to **ostatni segment `public_url`** (po `/quotes/c/`).
> Wyodrębnienie: `public_token = public_url.rsplit('/', 1)[-1]`
> (dla przykładu wyżej: `7NMQ3V7IIINGNRFICRORBC9INBESJ0ZZ`).
> `edit_uuid` służy do późniejszej aktualizacji wyceny (`PUT /api/bot/quotes/<edit_uuid>`),
> gdzie sklep również przesyła `product_type` (przetrwa edycję).

Błędy: `{"field": "client_id", "code": "MISSING"}` (brak `client_id`),
`{"field": "client_id", "code": "CLIENT_NOT_FOUND"}` (nieznany klient) — oba z `ok: false`, HTTP 200.

---

## 6. `GET /api/bot/quotes/by-token/<public_token>`

Odczyt wyceny po publicznym tokenie — do renderu strony `/wycena/{token}` i „przelicz ponownie".
Pola konfiguracyjne pozycji są w **tym samym formacie**, który przyjmuje `POST /api/bot/calculate`,
więc sklep może je podać 1:1 do ponownego przeliczenia.

**Request:** brak ciała. `public_token` w ścieżce. Nagłówek autoryzacji.

**Response 200 — sukces (realny przykład):**
```json
{
  "ok": true,
  "quote": {
    "quote_number": "01/07/26/W",
    "created_at": "2026-07-17T13:13:08.106533",
    "items": [
      {
        "product_type": "blat",
        "length": 120.0, "width": 60.0, "thickness": 4.0,
        "quantity": 2,
        "selected_variant": "dab-lity-ab",
        "species": "Dąb", "technology": "Lity", "wood_class": "A/B",
        "shape": "rectangular",
        "holes_count": 0,
        "finishing_type": "Surowe",
        "finishing_variant": null,
        "finishing_option_id": null,
        "finishing_gloss_level": null,
        "edges": [{"letter": "A", "type": "round", "r_value": 5, "angle_value": null}],
        "unit_netto": 307.01, "unit_brutto": 377.62,
        "finishing_netto": 0.0, "finishing_brutto": 0.0,
        "edges_netto": 36.0, "edges_brutto": 44.28,
        "total_netto": 650.02, "total_brutto": 799.52
      }
    ],
    "totals": {"total_netto": 650.02, "total_brutto": 799.52}
  }
}
```

- `items[]` zawiera **tylko wybrane warianty** pozycji (po jednym na pozycję).
- `created_at` — ISO 8601. **Ważność wyceny (14 dni) liczy sklep** — CRM nie zwraca daty wygaśnięcia.

**Ceny pozycji (ważne — jak liczy się `total`):** cena materiału (`QuoteItem`) jest per **wybrany
wariant drewna**, a wykończenie i krawędzie są liczone per **pozycja** (za całą ilość) i trzymane
osobno. Dlatego:

| pole | znaczenie |
|------|-----------|
| `unit_netto` / `unit_brutto` | cena **samego materiału** (wybrany wariant) za **1 szt.** — tożsama z `unit_netto` wariantu z `/calculate` |
| `finishing_netto` / `finishing_brutto` | koszt wykończenia za **całą pozycję** |
| `edges_netto` / `edges_brutto` | koszt krawędzi za **całą pozycję** |
| `total_netto` / `total_brutto` | **pełna cena pozycji** = `unit × quantity + finishing + edges` |

- `totals` = suma `total_*` wszystkich pozycji (materiał + wykończenie + krawędzie), **BEZ wysyłki**
  (wysyłkę dolicza sklep po swojej stronie). Wartości `total_*` odpowiadają cenie, którą klient
  widzi na stronie CRM `/quotes/c/<token>` (dla tej samej wyceny bez wysyłki).

**Response 200 — nieznany token (kontrakt bota, NIE 404 HTTP):**
```json
{"ok": false, "errors": [{"field": "public_token", "code": "NOT_FOUND", "message": "Nie znaleziono wyceny dla tokenu <token>."}]}
```

### 6.1. Wariant drewna: `selected_variant` vs `species/technology/wood_class`

`by-token` zwraca **oba**:
- `selected_variant` (np. `"dab-lity-ab"`) — **pole kanoniczne do re-kalkulacji**; to jego
  wymaga `POST /calculate` (`selected_variant`). **Do „przelicz ponownie" używaj tego pola.**
- `species` / `technology` / `wood_class` — czytelny rozkład (do renderu strony), wyprowadzony
  z tego samego kodu wariantu. Pola tylko-do-odczytu; nie odsyłaj ich do `/calculate`.

### 6.2. Wykończenie: dlaczego `finishing_option_id` jest zawsze `null`

CRM **nie przechowuje** `finishing_option_id` ani `finishing_full_path` na pozycji wyceny
(tak samo jak edycja wyceny w kalkulatorze CRM). `by-token` zwraca więc `finishing_option_id: null`,
a re-kalkulację wykończenia oprzyj na `finishing_type` + `finishing_variant` + `finishing_gloss_level`
(`calculate_finishing` ma dla nich fallback). Jeśli sklep zapisze wycenę z `finishing_type: "Surowe"`,
re-kalkulacja też da wykończenie 0 zł.

### 6.3. Mapowanie `by-token` → `POST /calculate` (przelicz ponownie)

Weź pozycję z `items[]` i zbuduj produkt do `/calculate` (dostosuj wymiary z formularza klienta):

| pole w `/calculate` (produkt) | źródło w `by-token` (`items[i]`)            |
|-------------------------------|---------------------------------------------|
| `length` / `width` / `thickness` | `length` / `width` / `thickness`         |
| `quantity`                    | `quantity`                                  |
| `selected_variant`            | `selected_variant`                          |
| `shape`                       | `shape`                                     |
| `holes_count`                 | `holes_count`                               |
| `finishing_type`              | `finishing_type`                            |
| `finishing_variant`           | `finishing_variant`                         |
| `finishing_gloss_level`       | `finishing_gloss_level`                     |
| `edges`                       | `edges` (`[{letter, type, r_value, angle_value}]`) |

Na poziomie wyceny podaj `client_type` (z listy `client_types` z `/options`).

> **Granice zakresu (świadome):** `by-token` obsługuje produkty prostokątne z prostymi
> krawędziami (typowe blaty/schody/parapety). Zaawansowany tryb krawędzi (`edges_mode`) oraz
> kształty nieregularne (`shape_data`) nie są round-tripowane w tym endpoincie.

---

## 7. Semantyka `product_type`

- Wartości: `"blat" | "schody" | "parapet"` (koncept sklepu; CRM go **nie interpretuje**).
- Utrwalany przy `POST /api/bot/quotes` i przy `PUT /api/bot/quotes/<edit_uuid>`; zwracany
  verbatim w `by-token`.
- Wyceny **spoza sklepu** (kalkulator CRM, inne boty) nie mają `product_type` → `by-token`
  zwraca `product_type: null`.
- Przy `PUT` wartość jest nadpisywana w całości — aby ją zachować, sklep musi ją ponownie
  wysłać (echo z `by-token`).
