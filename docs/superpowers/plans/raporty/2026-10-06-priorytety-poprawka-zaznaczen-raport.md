# Raport — poprawka zaznaczeń w hurcie gwiazdek + przebudowa pakietu (6.10.2026), program „Priorytety produkcji”

- **Data:** 2026-10-06
- **Sesja:** lokalna (Windows). Model: Opus 5.5, effort high.
- **Karta:** „poprawka zaznaczeń w hurcie gwiazdek + przebudowa pakietu (6.10)”, znalezisko 1 pełnego przebiegu E2E
- **Stan wejściowy (sprawdzony):** `origin/main` = `31a0b0145b222799234674bdf1e995dab6791a0c`;
  `origin/claude/priorytety-produkcji` = `e255841b`; stare gałęzie `claude/wdrozenie-2026-10-08` = `5e944a55`,
  `claude/wycofanie-2026-10-08` = `8e14937e` (nietknięte)

## Zrobione

| Krok | Co | Wynik |
|---|---|---|
| 1–2 | poprawka (TDD) w `products-module.js` + testy strukturalne | `9dd08077` na `claude/priorytety-produkcji` (fast-forward z `e255841b`) |
| 3 | oględziny w wbudowanej przeglądarce, podgląd 127.0.0.1:5009 na `priorytety_podglad` | scenariusz zaliczony, dane przywrócone |
| 4 | pełny pakiet na gałęzi poprawki | 6834 passed, 3 skipped; blog_seo 89 passed |
| 5b | `claude/wdrozenie-2026-10-08-v2` = squash na `main` | `9bd6fc51`, wszystkie kontrole zaliczone |
| 5c | `claude/wycofanie-2026-10-08-v2` = revert + migracja cofająca | `e295421a`, wszystkie kontrole zaliczone |

`main` nietknięty, bez `--force`, nic na produkcji.

### Przyczyna i poprawka

Karta zamówienia rysuje się z szablonu z pustym polem wyboru. `syncAllCheckboxes()` (woła je każde rysowanie listy)
przeliczało tylko pola pozycji, a pola zamówienia nie. Po hurcie gwiazdek `priorytety:zmiana` → `applyAllFilters()`
→ `renderOrdersList()` rysuje karty od nowa w nowej kolejności, a selekcja (`state.selectedProducts`) zostaje.
Efekt: pole zamówienia puste, pozycje w zwiniętym wierszu zaznaczone, pasek „2 zaznaczone”. Ta sama luka
dotyczyła Esc (selekcja czyszczona, pole zamówienia zostawało zaznaczone) i każdej zmiany filtra/sortowania.

1. `syncAllCheckboxes()` przelicza pole każdej `.il-order-card` przez istniejące `_updateOrderCheckboxState()`
   (zaznaczone / częściowe / puste, liczone z widocznych pozycji) — żadna droga rysowania nie zostawia
   niewidocznego zaznaczenia.
2. `showBulkStarsPicker()` po udanym zapisie czyści selekcję w całości (`clear` → `syncAllCheckboxes` →
   `toggleBulkActionsVisibility`, licznik 0, pasek schowany). Błąd zapisu, anulowany wybierak, odmowa w oknie
   potwierdzenia i przekroczony limit zostawiają selekcję.
3. Pozostałe akcje paska: „Zmień status” i „Usuń” już czyściły selekcję przed `refresh()` (test to teraz pilnuje);
   „Eksport” niczego na liście nie zmienia i zostawia zaznaczenie — bez zmian.

Zmiana decyzji K4a: test `test_hurt_gwiazdek_unikalne_zamowienia_i_limit` pilnował „Selekcja zostaje po zapisie”;
zgodnie z rekomendacją centrali z karty ta asercja zastąpiona testem czyszczenia (komentarz JSDoc też poprawiony).

## Testy (liczby)

- TDD: 2 nowe testy czerwone przed poprawką (`test_przerysowanie_przelicza_pola_zamowien`,
  `test_hurt_gwiazdek_czysci_zaznaczenie_po_zapisie` — brak kotwic w `syncAllCheckboxes` i w bloku `try`), zielone po
  niej; trzeci (`test_pozostale_hurty_czyszcza_zaznaczenie_po_zapisie`) pilnuje istniejącego zachowania.
- `node --check products-module.js` — OK.
- Trzy pliki z karty (`test_priorytety_lista_produkcyjna_ui.py`, `test_priorytety_logistyka_ui.py`,
  `test_priorytety_panel_api.py`): **242 passed**.
- Pełny pakiet na `9dd08077`: **6834 passed, 3 skipped**; blog_seo **89 passed**.
- Pełny pakiet na `claude/wdrozenie-2026-10-08-v2`: **6858 passed, 3 skipped** (v1 miał 6855 — różnica = 3 nowe
  testy); blog_seo **89 passed**.
- `tests/test_migracja_wycofanie_logistyki.py` na `claude/wycofanie-2026-10-08-v2`: **10 passed**.

Wszystko przez `docker compose -p priorytety run --rm --no-deps app …` z worktree; przed każdym uruchomieniem żaden
inny `priorytety-app-run-*` nie działał.

## Oględziny

Podgląd: kontener `logistyka3-app` z kodem `9dd08077`, port 127.0.0.1:5009, baza `priorytety_podglad`, konfiguracja
`woodpower-podglady/priorytety/core.json`; logowanie ciasteczkiem sesji z `login_user` (skrypt K4a), bez haseł.
Przeglądarka wczytała `products-module.js` z poprawką (sprawdzone na treści pliku). Zrzuty:
`woodpower-podglady/priorytety/zaznaczenia/zrzuty/` (1–4).

1. Zaznaczona 1 pozycja w zamówieniu 1551 (#28) i 1 w 1615 (#44): pola zamówień częściowe, pasek „2 zaznaczone”
   (zrzut 1).
2. Karty zwinięte, wymuszone przerysowanie listy (`poZmianiePriorytetow({})` — odczyt kolejki i rysowanie, bez zmian
   danych): karty narysowane od nowa, pola zamówień dalej **częściowe** (przed poprawką byłyby puste), pasek
   „2 zaznaczone” (zrzut 2).
3. Hurt „Ustaw gwiazdki” → ★★★ (kliknięciem): toast „zmieniono 2, bez zmian 0”, karty przeskoczyły na #8 i #9,
   **0 zaznaczonych pól w całej liście, selekcja 0, pasek schowany** (zrzut 3).
4. Druga akcja hurtowa: zaznaczone tylko te 2 widoczne zamówienia (pola zamówień) → „Bez gwiazdek” → okno „Zdjąć
   gwiazdki? Zaznaczone zamówienia: 2” (zrzut 4) → zatwierdzone: „zmieniono 2”, karty wróciły na #28 i #44, selekcja 0.
5. Esc przy zaznaczonym zamówieniu: pole zamówienia czyści się razem z selekcją (przed poprawką zostawało zaznaczone).

Dane podglądu: gwiazdki obu zamówień przywrócone do 0 (punkt 4), rangi wróciły na #28/#44. Zostały 4 wpisy historii
priorytetu tych dwóch zamówień (2 × ★★★, 2 × zdjęcie) — historia jest dziennikiem i nie kasowałem jej. Kontener
podglądu usunięty, pusty `config/core.json` w worktree usunięty. Inne kontenery, bazy i worktree nietknięte.

## Hashe v2 (pełne)

| Co | Hash |
|---|---|
| `main` / produkcja (stan wejściowy) | `31a0b0145b222799234674bdf1e995dab6791a0c` |
| poprawka na `claude/priorytety-produkcji` — podstawa squasha v2 | `9dd08077b90d9488c2e44a3da6f96fc7a232065f` |
| **squash — `claude/wdrozenie-2026-10-08-v2`** (rodzic `31a0b014`) | **`9bd6fc510fb9a7efb617bafeba4e492f49668784`** |
| revert squasha v2 | `160aac4e6346b62c7623445260afaac32c821440` |
| **wycofanie — `claude/wycofanie-2026-10-08-v2`** (revert + cherry-pick `8e14937e`) | **`e295421a123d4c86df89e0a0d2ec086f93b9ced4`** |

## Kontrole z kroku 5

| Kontrola | Wynik |
|---|---|
| a) `git rev-parse origin/main` = `31a0b014…` | ✅ (sprawdzone przed squashem i ponownie przed pushem) |
| b) `git diff --stat v2 origin/claude/priorytety-produkcji` | ✅ **24 pliki**; lista identyczna z `git diff --name-only origin/main~5 origin/main` (5 commitów `main`: `c2b312f0`, `b910b07b`, `a71af794`, `0310b6a7`, `31a0b014`) |
| b) `git diff --stat origin/claude/wdrozenie-2026-10-08 v2` | ✅ **6 plików**: `products-module.js`, `tests/test_priorytety_lista_produkcyjna_ui.py`, `CLAUDE.md` (wersja Pythona, `3d592f41`), 3 dokumenty w `docs/superpowers/plans/raporty/` (dziennik centrali, raport pakietu, raport próby). **Żadnych innych plików kodu ani migracji** |
| b) zamówienie 1450 (`prod_orders.id = 1450` z kopii produkcji `priorytety_prod_kopia`) | ✅ identyfikator Base. i pola osobowe (numer klienta, imię i nazwisko, e-mail, telefon, adres, odbiorca, miasto, kod — całe wartości i słowa ≥ 5 znaków): **0 trafień** w drzewie v2. Trafienia mają tylko pola ogólne `delivery_method` i `order_source_name` (nazwy sposobu dostawy i źródła, występujące w kodzie) — nie są danymi zamówienia. Historia v2 = jeden commit na `main` |
| b) pełny pakiet + blog_seo na v2 | ✅ 6858 passed, 3 skipped; 89 passed |
| c) `git diff --stat origin/main wycofanie-v2` | ✅ wyłącznie `migrations/2026-10-08-wycofanie-logistyki.sql` i `tests/test_migracja_wycofanie_logistyki.py` |
| c) `git diff 8e14937e wycofanie-v2 -- migrations tests/test_migracja_wycofanie_logistyki.py` | ✅ puste; dodatkowo **całe drzewo** `e295421a` = drzewo `8e14937e` (`0a5b7e77`), a drzewo revertu `160aac4e` = drzewo `main` (`46d148ff`) |
| c) test migracji cofającej | ✅ 10 passed |
| pushe | ✅ `claude/priorytety-produkcji` (`e255841b..9dd08077`, fast-forward), nowe `claude/wdrozenie-2026-10-08-v2`, `claude/wycofanie-2026-10-08-v2`; stare gałęzie bez zmian (`5e944a55`, `8e14937e`) |

Uwaga do kontroli b): treść różnicy w 5 z 24 plików (`admin_routers.py`, `reports_api.py`, `mobile_api_service.py`,
`reports_service.py`, `reports/mix.html`) nie jest bajt w bajt równa różnicy `main~5..main`, bo te pliki zmieniała też
gałąź programu (scalenie, inne linie kontekstu). To samo było w v1; v1 → v2 tych plików nie dotyka.

## Odstępstwa

1. **Wersja pliku w `dashboard.html` nie podbita** (`products-module.js?v=20261005c`). Podbicie dołożyłoby siódmy plik
   do różnicy v1 → v2, a karta dopuszcza tylko JS, test, `CLAUDE.md` i dokumenty. Produkcja nigdy nie widziała
   `20261005c` (ma starszą wersję z `main`), więc przeglądarki biura pobiorą nowy plik po wdrożeniu. Pamięć
   podręczną z `20261005c` mają tylko przeglądarki podglądów — tam twarde odświeżenie.
2. Przerysowanie w oględzinach (punkt 2) wywołane z konsoli (`poZmianiePriorytetow({})`, ten sam słuchacz co po
   zmianie priorytetów), żeby pokazać pole częściowe bez zmiany danych; hurt w punktach 3–4 klikany normalnie.
3. „Zrzut przed/po” = przed hurtem i po nim na kodzie z poprawką; stanu sprzed poprawki nie odtwarzałem w
   przeglądarce (opisany w znalezisku E2E, a test strukturalny był czerwony na starym kodzie).
4. Kontrola „1450” — pierwsze uruchomienie skryptu zawisło na pytaniu `mysql -p` o hasło (pusty użytkownik root w
   kopii); przerwane i powtórzone bez `-p`. Bez wpływu na wynik.

## Pytania do Konrada

1. Czy biuro ma wiedzieć, że po hurcie gwiazdek zaznaczenie znika (to zmiana względem K4a „selekcja zostaje”)?
   Instrukcja „odświeżyć stronę po hurcie” z listy znalezisk przestaje być potrzebna.
2. Wdrożenie 8.10 — z gałęzi v2 (`9bd6fc51`), wycofanie z `e295421a`. Runbook K7 trzeba przepisać na nowe hashe
   (stare `5e944a55` / `8e14937e` zostają w repo, ale nie mają poprawki).
