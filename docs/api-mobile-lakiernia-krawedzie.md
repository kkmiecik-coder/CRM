# Lakiernia obrabia krawędzie — kontrakt dla aplikacji Android

Kontrakt dla sesji aplikacji tabletowej (`crm_prod_app`) po zmianie trasy z 13.10.2026.
Sprawdzaj w kodzie: odnośniki prowadzą do plików i linii z dnia zmiany.

---

## Najważniejsze w trzech zdaniach

1. **Pozycja olejowana albo lakierowana z obróbką krawędzi omija stanowisko Krawędzie.**
   Z Formatowania idzie prosto na Lakiernię, a Lakiernia sama obrabia krawędzie, potem olejuje
   albo lakieruje.
2. **API się nie zmienia.** Żadna trasa, pole ani kod błędu nie powstał ani nie zniknął.
   Lakiernia już dziś dostaje pełne dane krawędzi.
3. **Zmienia się tylko appka.** Ekran Lakierni ma wyglądać jak ekran Krawędzi (rysunek,
   tabela krawędzi, program obróbki) i mieć dodatkowo komponent wykończenia. Pozycja bez
   krawędzi pokazuje samo wykończenie.

---

## 1. Trasa pozycji: przed i po

| pozycja | przed | po |
|---|---|---|
| surowa, bez krawędzi | Formatowanie → Pakowanie | bez zmian |
| surowa, z krawędziami | Formatowanie → Krawędzie → Pakowanie | bez zmian |
| olej/lakier, bez krawędzi | Formatowanie → Lakiernia → Pakowanie | bez zmian |
| **olej/lakier, z krawędziami** | Formatowanie → **Krawędzie → Lakiernia** → Pakowanie | Formatowanie → **Lakiernia** → Pakowanie |
| bez docięcia (`cut_to_size = false`) | Sklejanie → Pakowanie | bez zmian |

Źródło: `ProductionProduct.should_skip_edges` i `complete_task` w `modules/production/models.py`.
Licznik Krawędzi takiej pozycji zamyka system (`quantity_done_edges = quantity`, zdarzenie
`source = 'system'`), więc Krawędzie nigdy jej nie dostaną.

**Okres przejściowy.** Pozycje, które w chwili wdrożenia stały już w `czeka_na_krawedzie`,
kończą starą trasą: Krawędzie → Lakiernia. Przez kilka dni Lakiernia dostaje więc mieszankę:

- **nowe** pozycje z `has_edge = true`: krawędzie do obróbki na Lakierni,
- **stare** pozycje z `has_edge = true`: krawędzie już obrobione na Krawędziach.

API ich nie rozróżnia (decyzja: YAGNI, stan wygasa sam). Na hali dotyczy to garstki pozycji.
Jeśli appka potrzebuje rozróżnienia, zgłoś to przed implementacją, bo wymaga nowego pola.

---

## 2. Co Lakiernia dostaje dziś z API (bez zmian)

`GET /api/mobile/stations/painting/orders` → każda pozycja z `serialize_order`
(`modules/production/services/mobile_api_service.py:1130`). Pola krawędzi i wykończenia
**nie zależą od stanowiska**, więc Lakiernia dostaje dokładnie to samo co Krawędzie:

| pole | kiedy nie-null | treść |
|---|---|---|
| `finish` | wykończenie ≠ `surowe` (:1166) | `type`, `color_type`, `color`, `gloss` |
| `edge` | `parsed_edge_processing` (:1175) | `type`, `radius`, `angle`, `letters`, `letters_labeled`, `groups[]` (każda z `letters_labeled`) |
| `has_edge` | zawsze (:1305) | `bool` |
| `edge_svg`, `shape_svg`, `shape`, `shape_rotation` | gdy są w bazie (:1301-1306) | jak na Krawędziach |
| `grupa_wykonczenia` | **tylko Lakiernia** (:1240) | separator grup wykończenia, bez zmian |

Na Lakierni każda pozycja ma `finish` ≠ null (trafiają tam tylko olej/lakier).
`edge` ≠ null ma tylko część z nich.

---

## 3. Czego oczekujemy od appki

1. **Ekran Lakierni = ekran Krawędzi + komponent wykończenia.** Ten sam układ co `EdgesScreen`
   (lista + panel szczegółów z rysunkiem i tabelą krawędzi, sortowanie po programie obróbki),
   a w panelu dodatkowo wykończenie z próbką koloru i połyskiem (dzisiejszy `FinishHeroBlock`).
2. **Pozycja bez krawędzi** (`has_edge = false`): panel pokazuje **tylko wykończenie**,
   bez pustego miejsca na rysunek i bez komunikatu „brak rysunku” w roli błędu.
3. **`FinishDisplay.showsEdgeSummary`** (`ui/components/finish/FinishDisplay.kt:33`) zakłada dziś,
   że na Lakierni krawędzie są już obrobione. Po zmianie to nieprawda: zaktualizuj KDoc i logikę.
4. **Lakiernia nie ma stołu, nigdy.** `GET …/painting/desk` i `postpone` odpowiadają
   409 `stanowisko_bez_stolu` (`ustawienia.STANOWISKA_BEZ_STOLU`). `EdgesScreen` ma gałąź trybu
   stołu (`StationView.Desk`, Odłóż). Na Lakierni musi zostać tryb listy, bez wołania `desk`
   i bez przycisku Odłóż.
5. **Kolejność listy** zostaje serwerowa, ułożona grupami wykończenia
   (`lista.porzadek_listy`), z separatorem z `grupa_wykonczenia` (dziś `PaintingRows.kt`).
   Jeśli ekran Krawędzi sortuje lokalnie (np. po programie obróbki), na Lakierni domyślną
   kolejnością ma być ta z serwera.
6. **ZAKOŃCZ, licznik sztuk, doróbka:** bez zmian (`/api/mobile/orders/<id>/complete`,
   `PATCH …/quantity`, reject — jak dziś na Lakierni). Etykieta przycisku zostaje „ZAKOŃCZ”.

Alias tabletów się nie zmienia: `STATION_GROUPS = [{'edges', 'painting'}]`
(`mobile_api_service.py:118`), więc tablet Krawędzi nadal może zamknąć pozycję Lakierni i odwrotnie.

---

## 4. Kolejność wdrożenia

**Backend wszedł pierwszy (13.10.2026), appka uzupełnia widok.** Do czasu nowej appki tablet
Lakierni pokazuje pozycje do obróbki krawędzi bez podsumowania krawędzi. Zostaje tylko ikona
rysunku (`EdgeDialog`), więc lakierników trzeba uprzedzić, żeby przy każdej pozycji z ikoną
krawędzi otwierali rysunek. Nowa appka usuwa tę lukę, więc warto ją wydać możliwie szybko.

---

## 5. Skutek uboczny po stronie raportów

Obróbka krawędzi zrobiona na Lakierni liczy się w statystykach jako praca **Lakierni**
(zdarzenia `painting`). Nie trafia do statystyk Krawędzi, bo automatyczne zamknięcie licznika
Krawędzi ma `source = 'system'` i raporty pracy je pomijają. Tak ma być.
