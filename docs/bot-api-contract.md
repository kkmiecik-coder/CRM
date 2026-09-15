# Kontrakt API bota kalkulatora (`/api/bot/*`) — integracja ze sklepem

Dokument dla zespołu sklepu PrestaShop (woodpower.pl). Opisuje **dokładne** kształty
request/response endpointów, których sklep używa przez swój server-side proxy do budowy
konfiguratora wyceny, strony `/wycena/{token}` i funkcji „przelicz ponownie".

> Źródło prawdy: `modules/calculator/routers/bot_api.py`. Przykłady poniżej to **realne**
> odpowiedzi zrzucone z endpointów (nazwy pól 1:1 z kodem).

---

## 0. Kto ustala cenę (kontrakt cenowy)

**CRM jest jedynym źródłem prawdy o cenie. Moduł sklepu nie trzyma u siebie żadnego
mnożnika, progu ani cennika.** Sklep wysyła parametry produktu i pokazuje kwoty,
które wrócą z `/calculate`.

Modułowi **nie wolno** przechowywać ani wyliczać samodzielnie:

| Czego nie duplikować | Skąd to brać |
|---|---|
| mnożnik marży / grupa cenowa | `/calculate` → `variants[].multiplier` (już wliczony w ceny) |
| próg 1000 zł i stawki 1.5 / 1.1 | `/options` → `auto_multiplier` (tylko do wyświetlenia) |
| cena za m³, pasma wymiarów | `/calculate`; zakresy poglądowo w `/options` → `variants[]` |
| dopłaty (koło, kształt nietypowy, wycięcia) | wliczone w `variants[].unit_netto` |
| ceny wykończeń i krawędzi | `/calculate` → `finishing`, `edges` |
| VAT, zaokrąglanie do groszy | `/calculate`; nie przeliczaj brutto samodzielnie |

**Jak dobierany jest mnożnik (stan na 2026-09-15).** Domyślnie dobiera go CRM,
osobno dla **każdego wariantu drewna**, na podstawie ceny bazowej sztuki
(objętość × cena za m³, bez mnożnika i bez dopłat). Trzy zakresy:

- baza **poniżej 1000 zł netto** → mnożnik **1.5**
- baza **od 1000 zł netto** do ok. 1363,64 zł → **cena stała 1500 zł netto**
  (mnożnik efektywny schodzi płynnie z 1.5 do 1.1)
- baza **powyżej ok. 1363,64 zł** → mnożnik **1.1**

Próg liczy się na cenie bazowej, a nie końcowej, bo inaczej reguła zapętliłaby się
(baza 900 → ×1.5 = 1350, czyli powyżej progu, więc ×1.1 → 990, czyli poniżej progu…).

Środkowy zakres („plateau") istnieje po to, żeby cena **nigdy nie spadła przy
większym produkcie**. Bez niego gołe przełączenie 1.5 → 1.1 dawało uskok: na
produkcyjnym cenniku (dąb lity B/B, 90×4 cm) blat 198 cm kosztowałby 1496,88 zł
netto, a 200 cm już tylko 1108,80 zł — większy blat tańszy o 388 zł, akurat na
jednym z najpopularniejszych wymiarów. Z plateau przejście jest ciągłe:
198 cm = 1496,88 → 199 cm = 1500,00 → 200 cm = 1500,00 → 240 cm = 1568,16.

Skutki, o których musi wiedzieć sklep:

1. **Ten sam produkt ma różne mnożniki w różnych wariantach.** Blat może wyjść
   ×1.5 w buku i ×1.1 w dębie litym. Nie zakładaj jednego mnożnika na wycenę.
2. **Mnożnik bywa wartością pośrednią.** W strefie plateau `variants[].multiplier`
   to np. `1.2501`, a nie 1.5 ani 1.1. Nie waliduj go po stronie sklepu i nie
   zaokrąglaj — jest tak dobrany, żeby `base_unit_netto × multiplier` dawało
   dokładnie `unit_netto`.
3. **Grupa cenowa (`client_type`) nie wpływa na cenę** w trybie domyślnym —
   i dlatego **nie jest już wymagana** (zmiana z 2026-09-15). Sklep może jej nie
   wysyłać: `/calculate` policzy ceny, a `/quotes` zapisze wycenę z pustą grupą.
   Wymagana staje się dopiero przy `auto_multiplier: false`, gdzie to ona ustala
   mnożnik. Skutek dla modułu Presty: ustawienie „Grupa cenowa" w backoffice nie
   ma już żadnego wpływu na kwoty i może zniknąć razem z wysyłaniem pola.

**`auto_multiplier: false` NIE jest pełnym cofnięciem cen — nie używaj go jako rollbacku.**
Flagę respektuje **wyłącznie `/calculate`** (`bot_api.py:172`). `POST /quotes`
(`bot_api.py:348`) i aktualizacja wyceny (`bot_api.py:424`) ustawiają
`auto_multiplier = True` **na sztywno** i flagi z payloadu w ogóle nie czytają. Dla bota
jest to poprawne — cena podana w czacie ma się zgadzać z zapisaną wyceną — ale oznacza,
że klient korzystający z furtki pokazywałby w konfiguratorze cenę wg grupy cenowej,
a **zapisywałby wycenę policzoną automatycznie**. Rozjazd wyszedłby dopiero w mailu
z linkiem do wyceny. Pełne cofnięcie cen wymaga zmiany w CRM w **obu** miejscach,
a nie samego pola w payloadzie sklepu.

**Sklep z tej furtki nie korzysta i nie będzie.** Od 2026-09-15 moduł `wp_quotewizard`
nie wysyła `client_type` w ogóle i nie trzyma żadnego mnożnika, progu ani stawki;
pilnuje tego `modules/wp_quotewizard/tests/PricingSourceTest.php` po stronie sklepu.
Domniemanym „predefiniowanym mnożnikiem" modułu była zaszyta grupa cenowa
`WPQW_CLIENT_TYPE` — usunięta razem z polem w backoffice.

**Wyceny zapisane w trybie automatycznym** mają `Quote.quote_multiplier = NULL`,
bo jedna wartość dla całej wyceny nie istnieje; faktyczny mnożnik siedzi przy każdej
pozycji.

**Rozstrzygnięte 2026-09-15 (sesja sklepowa): `by-token` NIE zwraca użytego trybu.**
Sklep nie ma ścieżki, która przeliczałaby wycenę **ważną** — do koszyka trafiają kwoty
zapisane w CRM, bez wołania `/calculate`. Jedyne przeliczenie w sklepie to przycisk
„przelicz ponownie", widoczny **wyłącznie przy wycenie wygasłej**, gdzie podanie ceny
dzisiejszej jest celem, a nie usterką. Pole z trybem nie zmieniłoby więc żadnego
zachowania i byłoby martwym polem w kontrakcie.

Gdyby kiedyś powstała ścieżka przeliczania wyceny **ważnej**, decyzję trzeba podjąć od
nowa — i wtedy sam tryb nie wystarczy: do odtworzenia kwoty potrzebny jest również
`quote_client_type`, bo od 2026-09-15 wycena może nie mieć grupy cenowej w ogóle,
a przy `auto_multiplier: false` bez niej nie da się policzyć ceny.

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
  "custom_shape_surcharge_netto": 0.0,
  "auto_multiplier": {
    "prog_netto": 1000.0,
    "ponizej_progu": 1.5,
    "od_progu": 1.1,
    "cena_progowa_netto": 1500.0,
    "liczony_na": "cena bazowa sztuki (bez mnożnika i bez dopłat)"
  },
  "shapes": ["rectangular", "round", "circle"],
  "vat": 1.23
}
```

- `variant_code` — identyfikator wariantu drewna używany w `selected_variant` (patrz `/calculate`).
- `finishing_options[].id` — to `finishing_option_id` w `/calculate`.
- `client_types` — dozwolone wartości `client_type` (grupa cenowa).
  **Nie wpływa na cenę w trybie domyślnym** — patrz sekcja 0 (mnożnik marży).
- `round_surcharge_netto` — dopłata netto za sztukę za kształt `round`/`circle`.
- `custom_shape_surcharge_netto` — dopłata netto za sztukę za kształt inny niż
  prostokąt i koło/owal (trójkąty, trapezy, równoległoboki, wielokąty).
  `0` = dopłata wyłączona. Obie dopłaty wykluczają się — produkt ma jeden kształt.
- `auto_multiplier` — parametry automatycznego doboru mnożnika marży (sekcja 0).
  Wartości mogą się zmienić bez zapowiedzi; **nie zapisuj ich u siebie na stałe**.
- Lista `variants` zawiera tylko warianty, które mają wpis w cenniku (realnie: pełny zestaw
  gatunków/technologii dębu/jesionu/buku, tu skrócony przez dane przykładu).

---

## 3. `POST /api/bot/calculate`

Liczy wycenę **bez zapisu**. Backend jest jedynym źródłem prawdy o cenie — sklep podaje
tylko parametry.

**Request:**
```json
{
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
Na poziomie wyceny wymagane: `products` (co najmniej jeden). `client_type` jest
**opcjonalny** w trybie domyślnym — wymagany dopiero przy `auto_multiplier: false`,
bo tylko tam ustala mnożnik (patrz sekcja 0). Reszta pól opcjonalna (`finishing_type`
brak = „Surowe"; `edges` brak = brak krawędzi; `shape` brak = `rectangular`).

Opcjonalne pole `auto_multiplier` (bool) na poziomie wyceny steruje trybem mnożnika:

| wartość | zachowanie |
|---|---|
| brak pola (**domyślne**) | mnożnik dobierany automatycznie, per wariant (sekcja 0) |
| `false` | mnożnik z grupy cenowej `client_type` — zachowanie sprzed 2026-09-15; **tylko w tym trybie `client_type` jest wymagany** |
| `true` | jawnie tryb automatyczny |

**Response 200 — sukces (realny przykład, skrócone warianty niedostępne):**
```json
{
  "ok": true,
  "errors": [],
  "missing_fields": [],
  "multiplier": null,
  "multiplier_mode": "auto",
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
          "base_unit_netto": 236.16,
          "multiplier": 1.5,
          "unit_netto": 354.24,
          "unit_brutto": 435.72,
          "total_netto": 708.48,
          "total_brutto": 871.44
        },
        {"variant_code": "dab-lity-bb", "available": false},
        {"variant_code": "dab-micro-ab", "available": true, "volume_m3": 0.0288,
         "price_per_m3": 7000.0, "base_unit_netto": 201.6, "multiplier": 1.5,
         "unit_netto": 302.4, "unit_brutto": 371.95, "total_netto": 604.8,
         "total_brutto": 743.9}
      ],
      "shape_surcharge": null,
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
    "order_netto": 708.48, "order_brutto": 871.44,
    "finishing_netto": 0.0, "finishing_brutto": 0.0,
    "edges_netto": 36.0, "edges_brutto": 44.28,
    "shipping_netto": 0.0, "shipping_brutto": 0.0,
    "total_netto": 744.48, "total_brutto": 915.72
  }
}
```

- `variants[]` zawiera **wszystkie** warianty drewna; niedostępne dla podanych wymiarów mają
  `{"available": false}` (bez cen). Wybrany wariant (`selected_variant`) liczy się do `totals.order_*`.
- `unit_netto` bywa niezaokrąglone (parytet z frontendem); ceny do prezentacji bierz z
  `total_*` / `unit_brutto`.
- `totals.total_*` = order + finishing + edges + shipping.
- `base_unit_netto` — cena bazowa sztuki (mnożnik 1.0, bez dopłat). To na niej
  rozstrzyga się próg automatycznego mnożnika; pole jest **informacyjne**, do
  prezentacji nie używaj.
- `multiplier` w wariancie — mnożnik **faktycznie użyty dla tego wariantu**.
  W trybie automatycznym warianty jednego produktu mogą mieć różne mnożniki.
- `multiplier` na górnym poziomie — `null` w trybie automatycznym (nie istnieje
  jedna wartość dla całej wyceny). `multiplier_mode` mówi, który tryb zadziałał:
  `"auto"` albo `"client_type"`.
- `shape_surcharge` — rozbicie dopłaty za kształt nietypowy albo `null`, gdy jej nie ma.
  Kwota jest **już wliczona** w ceny wariantów; to pole służy tylko do pokazania
  klientowi, za co doliczono:
  ```json
  {"per_unit_netto": 120.0, "total_netto": 240.0, "total_brutto": 295.2,
   "note": "Doliczono 120.00 zł netto za sztukę za nietypowy kształt produktu."}
  ```

**Response 200 — brakujące pola (LLM/konfigurator dopytuje klienta):**
```json
{"ok": false, "missing_fields": [{"product_index": 1, "field": "width", "hint": "szerokość w cm"}], "errors": []}
```

**Response 200 — błąd walidacji wymiarów:**
```json
{
  "ok": false,
  "missing_fields": [],
  "multiplier": null,
  "multiplier_mode": "auto",
  "products": [{"index": 1, "errors": [ /* jak niżej */ ], "variants": [], "finishing": null,
                "edges": null, "shape_surcharge": null}],
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
- Grupa cenowa jest **opcjonalna**: `/quotes` zapisuje zawsze w trybie automatycznym,
  więc nie ustala tu ceny. Pominięta = wycena z pustą grupą (kolumna jest nullable,
  panel wycen pokazuje wtedy „Nie określono").
- Gdy ją podajesz, akceptowane jest `client_type` **lub** `quote_client_type`
  (to samo znaczenie) — trafia na wycenę jako etykieta.
- Przy `PUT /api/bot/quotes/<edit_uuid>` pominięcie grupy **nie kasuje** tej już
  zapisanej (inaczej niż `product_type`, patrz sekcja 7) — nadpisuje ją tylko
  wartość podana jawnie.
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

Na poziomie wyceny nie trzeba podawać niczego poza `products` — grupa cenowa
(`client_type`) jest opcjonalna, dopóki nie wysyłasz `auto_multiplier: false`.

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
