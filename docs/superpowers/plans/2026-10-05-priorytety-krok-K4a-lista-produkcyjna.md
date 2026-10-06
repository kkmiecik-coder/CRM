# Priorytety produkcji, krok K4a — „Lista produkcyjna”: modal priorytetu, drabina, gwiazdki 0–5 w Liście i Logistyce — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biuro ustawia priorytety tam, gdzie pracuje. Zakładka „Lista produktów” nazywa się teraz „Lista produkcyjna”.
Karty zamówień idą w kolejności rangi zamówienia i mają plakietki: gwiazdki, trasa, tag, „Odłożone na …”. Gwiazdki 0–5
ustawia się z modalu priorytetu, hurtowo z paska akcji i z kolumny „★” w Logistyce. Drabinę układa się w modalu
„Drabina priorytetów”. Stara gwiazdka true/false, przeciąganie wierszy, progi rangi i końcówka `POST /set-priority`
znikają.

**Architecture:** Całe UI priorytetów to jeden wspólny plik `modules/production/priorytety/static/js/priorytety.js`
(statyka blueprintu `priorytety_panel` z K2) ze stylem `priorytety.css`, ładowany raz na stronę w
`templates/panel/dashboard.html`. Wystawia `window.Priorytety`: klienta API `/production/api/priorytety/*`, znaczek
i wybierak gwiazdek, modal priorytetu zamówienia i modal drabiny. Oba modale to `<dialog>` budowane w JS. Z
`window.Priorytety` korzystają `products-module.js` (karty, hurt, sortowanie) i `logistics.js` / `logistics-routes.js`
(kolumna ★, przystanki). Backend K4a jest tylko do odczytu, z jednym wyjątkiem. Lista produktów dostaje
`order_id` i `order_priority_stars`, a lista Logistyki (i przystanki tras) dostaje `gwiazdki`. Wyjątkiem jest usunięcie
`POST /production/api/set-priority`. Wszystkie zapisy idą przez końcówki K2, a kolejność blokad trzymają one.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, Jinja2, czysty JS (ES2020 jak reszta panelu — `products-module.js` już używa
`?.`; bez bundlera, bez nowych bibliotek), Bootstrap 5 już
na stronie, `<dialog>`, pytest na SQLite in-memory (testy strukturalne źródeł JS/HTML, bo w obrazie nie ma node'a).

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`: 2 (ustalenie 10), 3.1 (drabina, ostrzeżenie
o datach), 3.2 (kolejność zamówień), 4.1 (ranga zamówienia), 5.3 (odłożenia widziane przez biuro), **7.1** (zakładka
„Lista produkcyjna”), **7.2** (Logistyka: kolumna ★, przystanki), 7.3 (uprawnienia), 9.1 (pakiet, `static/{js,css}/priorytety.*`),
9.4 (współbieżność), 9.5 (wiersze `products-module.js`, `products-dragdrop.js`, `products-tab-content.html`,
`products-tab.css`, `dashboard.html`, `logistics.js`, `logistics-routes.js`, końcówka `set-priority`), 10 (błędy), 13 (UI:
Lista produkcyjna, modale, brak `products-dragdrop.js`), 15. Symulacja: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`,
„Analiza wyniku” i „E. Decyzje Konrada”. Plany zależności: `…-krok-K2-panel-api.md` (Task 2–4: kształty JSON),
`…-krok-K3-stol-odloz-sygnaly.md` (Task 5: `GET /odlozenia`). Podręcznik centrali: `…-priorytety-produkcji-centrala.md`
(sekcje 2, 4a, 8.0, 8.4).

**Sesja:** lokalna (Docker: `docker compose exec app pytest`, podgląd aplikacji w przeglądarce). JS nie da się
uruchomić w testach, więc krok kończy się oględzinami na podglądzie i zrzutami (karta 8.4). Model wg podręcznika 4a:
Opus 5.5, effort high, tryb szybki dozwolony. Krok nie dodaje pisarzy ani blokad, więc wyścigów MySQL nie robi.

**Zależności:** K2 i K3 zakończone i zaliczone na bramce. Od K2: blueprint `priorytety_panel_bp` ze statyką
(`static_url_path='/static/priorytety'`), końcówki `GET /drabina`, `PUT /drabina/kolejnosc`, `PUT /zamowienia/gwiazdki`,
`GET /kolejka`, `GET /zamowienia/<id>/priorytet`. Od K3: `GET /odlozenia` i dane stołu w `prod_station_desk`. K4b może
iść równolegle. Wspólny plik obu kroków to `dashboard.html` (wersje skryptów).

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji && git pull
--ff-only origin claude/priorytety-produkcji`. Nigdy `main`. **Numery linii w tym planie dotyczą stanu
`claude/logistyka-etap-4` @ `b4b4a54d`, czyli sprzed K1–K3.** K2 usuwa fragmenty `products_api.py`, więc linie się
przesuną. Szukaj po nazwie (`grep -n`), nazwy są podane przy każdym miejscu.

## Global Constraints

- **Python 3.9:** `X | Y` w adnotacjach tylko w plikach z `from __future__ import annotations`, bez `match`. Zmiany Pythona
  w tym kroku są małe (dwa serializery, usunięcie końcówki).
- Komentarze i docstringi **po polsku**. W tekstach UI pisz „Base.”, nie „BaseLinker”. Etykiety stanowisk bierz
  z `station_catalog.STATION_LABELS`, czyli z odpowiedzi API, a nie z własnej kopii. Wyjątek: miejscownik do plakietki
  „Odłożone na Sklejaniu” (Doprecyzowania p. 6).
- **Dane z API do HTML tylko przez escapowanie.** Dotyczy klienta, nazwy trasy, notatki odłożenia, pracownika,
  `message` z błędu i etykiety szczebla. `ToastSystem.show` (`shared-services.js:497`) składa treść przez `innerHTML`
  (`:542`), więc komunikat też przechodzi przez `esc`. Wzór: `tests/test_produkty_js_hurt_pominiete.py`.
  **W `products-module.js` treść węzła idzie przez `this.escapeHtml`, a wartość atrybutu (`title`, `aria-label`) przez
  `this.escapeAttr`** (`products-module.js:4246-4262`): `escapeHtml` nie zamienia cudzysłowu, więc nazwa trasy z `"` w
  `title="…"` wyszłaby z atrybutu. `Priorytety.esc` i `esc` z `logistics*.js` zamieniają `& < > " '` i służą do obu.
- **Jedna droga zapisu gwiazdek:** `PUT /production/api/priorytety/zamowienia/gwiazdki` wołane wyłącznie z
  `Priorytety.ustawGwiazdki`. **Jedna droga zapisu drabiny:** `PUT /drabina/kolejnosc` wyłącznie z modalu drabiny.
  `products-module.js` i `logistics.js` nie robią `fetch` do `/priorytety/` same. Komentarze w tych plikach nie
  wypisują ścieżek `/priorytety/…` (testy szukają tekstu ścieżki, nie tylko wywołań). W `priorytety.js` komentarz
  nagłówkowy wypisuje końcówki bez apostrofów, a w kodzie ścieżka zapisu stoi raz jako literał w apostrofach.
- **Współbieżność** (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek”, akapit o pisarzach pozycji
  bez blokady zamówienia; spec 9.4). K4a **nie dodaje** żadnego zapisu w bazie ani żadnej blokady. Zapisy robią
  końcówki K2 w swojej kolejności (sekcja „Współbieżność” niżej). UI ma nie mnożyć transakcji: jedno żądanie na akcję,
  hurt w jednym żądaniu (≤ 500), bez automatycznego ponawiania 500, bo serwer sam ponowił raz po 1213. Jeden zapis
  naraz w modalu.
- **Serializery tylko czytają.** Nowe pola biorą wartości z obiektów już dociągniętych (`joinedload(ProductionItem.order)`
  w `products_tab_content`, zamówienia z pozycjami w `lista.pobierz`). Zero nowych zapytań na wiersz.
- **Szablon zakładki Logistyki nie odwołuje się do statyki priorytetów.** `url_for('priorytety_panel.static')`
  w `logistics/templates/logistics/tab_content.html` wywróciłoby `test_zakladka_renderuje_sie_z_trasami_i_flota`, bo
  `tests/logistyka_fixtures.py` nie rejestruje blueprintu priorytetów. `priorytety.js` ładuje wyłącznie `dashboard.html`.
- Zakres: Lista produkcyjna, modale, gwiazdki w Logistyce, usunięcie martwego kodu z 7.1 i `set-priority`. **Nie**
  ruszaj: zakładki Stanowiska, dashboardu, Konfiguracji ani monitorów (K4b), końcówek K2/K3 (poza testem K2 z Task 5),
  `priority_service.py` (K8), filtra `priority_range` w `GET /products/filters-data` (Poza zakresem), `tools/print_agent`.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`. TDD: najpierw test, który pada. Testy
  strukturalne źródeł robimy wg `tests/krawedzie_fixtures.py` (`zrodlo`, `JS_PRODUKTY`, `SZABLON_PRODUKTOW`) i
  `tests/test_logistyka_*_ui.py`. Testy API idą na fiksturach `krawedzie_fixtures` / `logistyka_fixtures`.
- Wersje plików statycznych (`?v=`) podbijaj w każdym zmienionym pliku do daty wykonania z literą. Każda nowa wersja
  ma być większa od obecnej, bo testy porównują napisy.
- Commity: Conventional Commits po polsku, **temat bez polskich znaków**, jeden na Task, stopka atrybucji własnej sesji.
  `docs/superpowers/` dodawaj przez `git add -f`. Push na gałąź roboczą wg karty (S-2).
- Repo publiczne. Zrzuty ekranu z podglądu **nie trafiają do repo**, chyba że baza podglądu ma wyłącznie dane testowe.
  Domyślnie zostają w katalogu podglądu wskazanym przez centralę, a raport podaje ich ścieżki i opis.
- Jeśli K4b pracuje równolegle: `git pull --ff-only` (albo `--rebase` przy rozjeździe) **przed każdym commitem**.
  Konflikty powinny być tylko w `dashboard.html`. Rozwiąż je ręcznie (obie wersje skryptów), niczego nie nadpisuj
  (karta 8.4).

## Review Focus

1. **XSS: dane z API (klient, trasa, notatka, pracownik, komunikat) trafiają do HTML wyłącznie przez `esc`
   (w `products-module.js`: treść przez `escapeHtml`, atrybuty przez `escapeAttr`).** Testy:
   `test_priorytety_js_dane_z_api_tylko_przez_esc`, `test_plakietki_karty_przez_esc` (Task 2, 4).
2. **Martwy kod naprawdę zniknął, a `set-priority` nie ma ani w JS, ani w API.** Testy: `test_brak_przeciagania_na_liscie`,
   `test_brak_starej_gwiazdki_i_progow_rangi`, `test_set_priority_usuniete`, zmieniony K2
   `test_martwe_koncowki_priorytetow_usuniete` (Task 4, 5).
3. **Kolejność kart = ranga z `GET /kolejka`, a lista działa także wtedy, gdy priorytety się nie wczytają (po terminie,
   z ostrzeżeniem).** Testy: `test_sortowanie_kart_po_randze_z_kolejki`, `test_blad_priorytetow_nie_psuje_listy` (Task 4).
4. **Drabina: strzałki tylko przy szczeblach ruchomych, zapis zawsze z `oczekiwane`, 409 `drabina_zmieniona` daje
   odczyt od nowa, jeden zapis naraz.** Testy: `test_drabina_strzalki_tylko_dla_ruchomych`,
   `test_drabina_wysyla_oczekiwane_i_obsluguje_409`, `test_jeden_zapis_naraz` (Task 3).
5. **Gwiazdki: jedna droga zapisu (modal, hurt, Logistyka), hurt po unikalnych zamówieniach i ≤ 500 przed wysłaniem,
   `przeliczenie: "nieudane"` daje ostrzeżenie, a nie błąd.** Testy: `test_gwiazdki_jedna_droga_zapisu`,
   `test_hurt_gwiazdek_unikalne_zamowienia_i_limit`, `test_przeliczenie_nieudane_ostrzega` (Task 2, 4, 6).
6. **Nowe pola serializerów są poprawne i nie dokładają zapytań.** Testy: `test_lista_produkcyjna_ma_order_id_i_gwiazdki`,
   `test_lista_produkcyjna_bez_dodatkowych_zapytan`, `test_lista_logistyki_i_przystanki_maja_gwiazdki` (Task 1).
7. **Tabela Logistyki ma spójne 11 kolumn** (nagłówek, `colspan` wiersza ładowania w szablonie, stanów i rozwinięcia
   w JS, sortowanie, fokus).
   Test: `test_tabela_logistyki_kolumna_gwiazdek_i_colspan` (Task 6).
8. **Nazwa zakładki i teksty.** Test: `test_zakladka_nazywa_sie_lista_produkcyjna` (Task 1).

## Decyzje przyjęte (ze specu i symulacji)

1. Priorytetami zarządza biuro z backoffice produkcji: gwiazdki 0–5 na **zamówieniu**, trasy i tagi na drabinie
   (Konrad 4.10, spec 2 p. 1–3, 10).
2. Miejsce ustawiania: modal priorytetu na karcie zamówienia w zakładce „Lista produkcyjna” (dotąd „Lista produktów”)
   i przycisk „Drabina priorytetów” w tej zakładce (Konrad 4.10, spec 2 p. 10, 7.1).
3. Gwiazdka pozycji i stan „częściowo” znikają. Gwiazdki są tylko na zamówieniu (spec 7.1).
4. Kolejność kart = ranga zamówienia. Termin zostaje kolumną i kolorem (spec 7.1).
5. Szczeble gwiazdek są stałe. Tagi i trasy są ruchome, a trasę można dać nawet pod „bez gwiazdek” (Konrad 4.10, spec 3.1).
6. Domyślna drabina: ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez gwiazdek. Próg „Blisko
   terminu” to 3 dni robocze (Konrad 5.10, symulacja E). K4a tylko to wyświetla.
7. Ostrzeżenie o datach tras przy drabinie, bez automatycznego przesuwania (spec 3.1).
8. Brak „Przywróć” dla odłożeń. Biuro reaguje gwiazdkami, wstrzymaniem albo materiałem (spec 5.3).
9. Uprawnienia: gwiazdki i drabina przez `guard` (login + moduł `production`), czyli biuro, a nie tylko admin
   (spec 7.3). Dzisiejsze `set-priority` było `@admin_required`.
10. `POST /set-priority` zostało w K2 tylko dla JS (karta centrali 8.2). Usuwa je K4a razem z wywołaniem
    `products-module.js:2383`.

## Doprecyzowania (do specu — K5 przeniesie)

1. **Modale są budowane w JS jako `<dialog>`** (`priorytety.js`), bez `templates/priorytety/` ze spec 9.1. Gdyby
   `products-tab-content.html` robił `{% include %}` szablonu innego blueprintu, render zakładki zależałby od rejestracji
   `priorytety_panel_bp`. Wtedy `GET /production/api/products-tab-content` w fiksturze `krawedzie_fixtures` (tylko `api_bp`)
   zwracałby 500.
2. **Źródło kolejności kart to `GET /kolejka`.** Ranga liczy się tam na żywo, tak samo jak w modalu i w licznikach drabiny.
   Kolumna `prod_orders.priority_rank` jest tylko pamięcią podręczną. Zamówienia spoza kolejki (spakowane, ale otwarte
   w Logistyce, wstrzymane) idą na koniec, posortowane po terminie, potem po numerze. Gdy `/kolejka` nie odpowie, lista
   sortuje po terminie (zachowanie sprzed K4a) i pokazuje w pasku ostrzeżenie „Kolejność wg terminu: nie udało się
   wczytać priorytetów”.
3. **Nowe pola listy produktów:** `order_id` (`prod_orders.id`) i `order_priority_stars` (`prod_orders.priority_stars`,
   0–5) w `_serialize_product` i `_serialize_production_item`. `is_priority`, `priority_rank` i `priority_manual_override`
   zostają w odpowiedzi (archiwum, inni czytelnicy, K8), ale JS listy ich nie czyta.
4. **`lista.serializuj` (Logistyka) dostaje `gwiazdki`** (int 0–5). Z tego pola biorą dane kolumna ★ i gwiazdki
   przystanków, bo `trasy_api` (`:322`) serializuje przystanki tą samą funkcją. Telefon kierowcy
   (`dostawa_widok.serializuj`) zostaje bez zmian.
5. **Modal priorytetu czyta tylko `GET /zamowienia/<id>/priorytet`.** Pole `stanowiska` z K2 (Task 4) daje dla każdego
   stanowiska stół, odłożone i miejsce w kolejce. `GET /stoly` czyta K4b (zakładka Stanowiska), K4a go nie potrzebuje.
   Sekcja „Historia gwiazdek” pokazuje wpisy `historia[]` z `akcja == "gwiazdki"`.
6. **Plakietka „Odłożone na …”** pochodzi z `GET /odlozenia` (K3). Na karcie jest jedna plakietka na stanowisko.
   Jedno odłożenie daje „Odłożone na Sklejaniu: brak materiału, 9:40, Adam”, kilka daje „Odłożone na Sklejaniu: 2”,
   a szczegóły są w `title` i w modalu. Miejscownik nazw stanowisk jest w `priorytety.js` (`cutting` → Wycinaniu,
   `assembly` → Składaniu, `gluing` → Sklejaniu, `formatting` → Formatowaniu, `edges` → Krawędziach, `painting` →
   Lakierni, `packaging` → Pakowaniu). Nieznany kod daje „na <nazwa z API>”. Etykiety powodów: `brak_materialu` →
   „brak materiału”, `awaria_maszyny` → „awaria maszyny”, `brak_miejsca` → „brak miejsca”, `czeka_na_biuro` →
   „czeka na biuro”, `inne` → treść notatki.
7. **Hurt „Ustaw gwiazdki”** działa na zamówieniach zaznaczonych pozycji (unikalne `order_id` z widocznej selekcji,
   `_getVisibleSelectedKeys`). Powyżej 500 zamówień (`Priorytety.LIMIT_HURTU`, lustro `stale.LIMIT_HURTU` z K2) UI
   odmawia bez wysyłki. Nie dzielimy na partie, bo każda partia to osobna transakcja i osobne `utrwal()`.
8. **Drabina:** strzałka ↑/↓ wysyła `pozycja` = indeks sąsiada w widocznej drabinie (±1), także gdy sąsiad to szczebel
   gwiazdek, zawsze razem z `oczekiwane` = lista id widocznych szczebli z ostatniego odczytu. Po 409
   `drabina_zmieniona` modal czyta drabinę od nowa i pokazuje „Drabina zmieniła się w międzyczasie. Sprawdź i spróbuj
   jeszcze raz.”. Do czasu odpowiedzi strzałki mają `aria-disabled="true"`, a kliknięcia są ignorowane. Drag&drop jest
   opcjonalny i nie wchodzi do DoD (Task 3, Step 6).
9. **Pierwsza kolumna karty** to miejsce w kolejce (`#17`, ranga z `/kolejka`, dla zamówień spoza kolejki „—”). Zastępuje
   uchwyt przeciągania. Liczba dzieci siatki nagłówka zostaje (11), więc reguły `nth-child` w `products-tab.css` dalej
   trafiają w te same kolumny. Jedyna zmiana: przy `max-width: 900px` ukrywana jest kolumna 1 (ranga) zamiast 3
   (dawna gwiazdka, teraz przycisk gwiazdek).
10. **Modal szczegółów pozycji:** wskaźnik `priority-indicator` z progami rangi znika bez następcy
    (`products-tab-content.html:375`, `updateHeaderStatus`).
11. **Logistyka:** gwiazdek nie da się edytować na zamówieniach zamkniętych, anulowanych i wydanych. Tam są tylko
    wyświetlane. Kolumna ★ jest sortowalna (`gwiazdki` w `KOLUMNY_SORTOWANIA`).
12. **Zdarzenie po zmianie:** `ProductionShared.eventBus.emit('priorytety:zmiana', {rodzaj: 'gwiazdki'|'drabina', order_ids})`.
    Lista produkcyjna nasłuchuje i ponownie czyta `/kolejka` i `/odlozenia`, a potem sortuje. Logistyka aktualizuje
    `gwiazdki` wiersza lokalnie, bez przeładowania listy. Słuchacza zdejmuje się funkcją wyrejestrowania, którą zwraca
    `eventBus.on` (`shared-services.js:26-48`). `eventBus.off('priorytety:zmiana')` bez handlera usuwa **wszystkich**
    słuchaczy zdarzenia (`:71-75`), więc jest zakazane.
13. **Filtr `priority_range` w `GET /products/filters-data` zostaje bez zmian** (odstępstwo od spec 9.5 „filtr
    `priority_range` → gwiazdki”). Nikt go nie czyta (`products-module.js:982`, TODO), a filtrowanie listy idzie po
    stronie klienta. Usunięcie należy do K8 razem z `priority_service`.
14. **Klawiatura listy nie działa pod oknami priorytetów.** `ProductsModule.handleKeydown` (`products-module.js:2734-2756`,
    nasłuch na `document`) czyści selekcję na Esc i zaznacza wszystko na Ctrl+A. Bez zabezpieczenia Esc w dymku
    „Ustaw gwiazdki” albo w modalu skasowałby zaznaczenie (wbrew „Selekcja zostaje”, Task 4 Step 6). `handleKeydown`
    kończy się więc od razu, gdy otwarty jest `dialog[open]` albo dymek `.pr-wybierak`.

## Współbieżność (gdzie plan dotyka blokad)

K4a nie bierze blokad i nie pisze do bazy sam. Ścieżki zapisu, które UI uruchamia, mają kolejność ustaloną w K2 (spec 9.4,
CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek” — hurt blokuje zamówienia rosnąco po id):

```
Gwiazdki (modal / hurt / Logistyka) → PUT /zamowienia/gwiazdki (K2 Task 3):
  walidacja → user_id → db.session.commit()            # koniec migawki; nic nie czytamy do blokady
  → gwiazdki.ustaw: FOR UPDATE prod_orders WHERE id IN (…) ORDER BY id   # blokady_zamowien.zablokuj_zamowienia
  → UPDATE prod_orders (tylko zmienione) → INSERT prod_priority_log (FK do już zablokowanego zamówienia)
  → db.session.commit() → kolejka.utrwal() na własnej sesji (zamówienia FOR UPDATE rosnąco → pozycje rosnąco)
  BEZ blokady tras. 1213 → jedno ponowienie całego zapisu w routerze; drugie → 500.

Drabina (strzałka w modalu) → PUT /drabina/kolejnosc (K2 Task 2):
  walidacja → user_id → db.session.commit()
  → routes.zablokuj_trasy()  (FOR UPDATE prod_config 'logistyka_trasy_blokada')
  → odczyt widocznej drabiny (migawka spod blokady) → oczekiwane? → drabina.przesun → commit
  → kolejka.utrwal() po commicie, poza blokadą tras.

Odczyty (GET /kolejka, /zamowienia/<id>/priorytet, /odlozenia, /drabina) — bez blokad; wyjątek: samonaprawa w GET /drabina
  (commit → blokada tras → drabina.uzupelnij → commit) tylko gdy brakuje szczebla trasy (okno wdrożenia).
```

Co K4a zmienia w tym obrazie:
- **Usuwa jednego pisarza pozycji bez blokady zamówienia.** `POST /set-priority` (`products_api.py:3679-3797`) robił
  UPDATE `prod_products.is_priority` dla pozycji zamówienia wybranych po `internal_order_number`, bez blokady zamówienia
  i bez gwarancji kolejności po PK (CLAUDE.md: „hurtowa i ręczna zmiana priorytetu” na liście pisarzy). Po K4a ten
  pisarz nie istnieje. Poprawka tekstu CLAUDE.md należy do K5 (raport K2 to zgłasza).
- **UI nie mnoży transakcji.** Hurt idzie jednym żądaniem, a UI nie wysyła równoległych zapisów z jednego modalu. Kliknięć
  w trakcie zapisu nie kolejkuje się, tylko ignoruje. Po 500 UI pokazuje komunikat i nie ponawia, bo router K2 już raz
  ponowił po 1213.
- **Testy pilnujące kolejności zapisów** to testy K2, które ten krok uruchamia jako regresję (Task 7):
  `test_gwiazdki_commit_blokada_zamowien_rosnaco_potem_zapis`, `test_gwiazdki_bez_blokady_tras`,
  `test_gwiazdki_utrwal_po_commicie`, `test_przesun_szczebla_commit_i_blokada_tras_bez_odczytu_pomiedzy`,
  `test_odczyty_nie_biora_blokad` (`tests/test_priorytety_panel_api.py`) oraz K3
  `test_stoly_i_odlozenia_bez_blokad_i_zapisow`. Własne testy K4a pilnują strony UI (`test_gwiazdki_jedna_droga_zapisu`,
  `test_jeden_zapis_naraz`) i braku nowych zapytań w serializerach (`test_lista_produkcyjna_bez_dodatkowych_zapytan`).

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/templates/panel/dashboard.html` | 1, 2, 4 | nazwa zakładki (`:52`), komunikat błędu (`:183`), `<link>`/`<script>` `priorytety.*`, usunięcie `products-dragdrop.js` (`:361`), wersje |
| `modules/production/templates/components/products-tab-content.html` | 1, 4 | pasek tytułu z przyciskiem „Drabina priorytetów”, nagłówki kolumn, szablon karty i wiersza, hurt „Ustaw gwiazdki”, usunięcie formularza priorytetu i wskaźnika |
| `modules/production/static/js/modules/archive-module.js` | 1 | tekst `:592` „Lista produktów” → „Lista produkcyjna” |
| `modules/production/routers/api/products_api.py` | 1, 5 | `order_id`, `order_priority_stars` w `_serialize_product` (`:108`) i `_serialize_production_item` (`:2601`); usunięcie `set_product_priority` (`:3679-3797`) |
| `modules/production/logistics/services/lista.py` | 1 | `gwiazdki` w `serializuj` (`:240-294`) |
| `modules/production/priorytety/static/js/priorytety.js` (nowy) | 2, 3 | `window.Priorytety`: klient API, gwiazdki, wybierak, modal priorytetu, modal drabiny |
| `modules/production/priorytety/static/css/priorytety.css` (nowy) | 2, 3 | style modali, gwiazdek, plakietek (prefiks `pr-`) |
| `modules/production/static/js/modules/products-module.js` | 4 | karty: ranga, przycisk gwiazdek, plakietki, sortowanie, hurt; usunięcia martwego kodu |
| `modules/production/static/css/products-tab.css` | 4 | siatka nagłówka, plakietki, usunięcie stylów uchwytu i starej gwiazdki |
| `modules/production/static/js/modules/products-dragdrop.js` | 4 | **usunięty** |
| `modules/production/logistics/templates/logistics/tab_content.html` | 6 | kolumna `th.lg-k-gwiazdki`, `colspan="11"` wiersza ładowania (`:292`), wersje skryptów |
| `modules/production/logistics/static/js/logistics.js` | 6 | kolumna ★: komórka, sortowanie, wybierak, `colspan` 11 |
| `modules/production/logistics/static/js/logistics-routes.js` | 6 | gwiazdki przy przystanku (odczyt) |
| `modules/production/logistics/static/css/logistics.css`, `logistics-trasy.css` | 6 | style kolumny i znaczka |
| `tests/test_priorytety_lista_produkcyjna_ui.py` (nowy) | 1–5 | testy strukturalne i API Listy produkcyjnej |
| `tests/test_priorytety_logistyka_ui.py` (nowy) | 1, 6 | testy Logistyki |
| `tests/test_priorytety_kolejnosc_zapisow.py` (K2) | 5 | `test_martwe_koncowki_priorytetow_usuniete`: `set-priority` teraz **nie** istnieje |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4a-raport.md` (nowy) | 7 | raport kroku |

Usunięte pliki: `products-dragdrop.js`. Nie powstaje `modules/production/priorytety/templates/priorytety/`
(Doprecyzowania p. 1).

---

### Task 1: Punkt wyjścia, nazwa zakładki, pola gwiazdek w serializerach

**Files:**
- Modify: `modules/production/templates/panel/dashboard.html:44-53` (przycisk zakładki), `:183` (komunikat błędu)
- Modify: `modules/production/templates/components/products-tab-content.html` (pasek tytułu nad `il-stats-bar`, `:4`)
- Modify: `modules/production/static/js/modules/archive-module.js:592`
- Modify: `modules/production/routers/api/products_api.py` (`_serialize_product` `:108-283`, `_serialize_production_item` `:2601`)
- Modify: `modules/production/logistics/services/lista.py:240-294` (`serializuj`)
- Create: `tests/test_priorytety_lista_produkcyjna_ui.py`, `tests/test_priorytety_logistyka_ui.py`

**Stan obecny (ugruntowanie):**
- Zakładka: `dashboard.html:44-53`, przycisk `id="products-tab"` z tekstem `<i class="fas fa-list me-2"></i>Lista produktów`
  (`:52`). Panel `#products-tab-content` `:153-189`, komunikat `:183` „Błąd ładowania produktów!”.
- `grep -rn "Lista produktów" modules/production` → `dashboard.html:52`, `archive-module.js:592` (toast „Otwórz najpierw
  zakładkę "Lista produktów"…”). Trafienia w `products_api.py:2101/2173` (arkusz eksportu Excel) i `:2347` (PDF) to nazwy
  arkuszy eksportu, a nie zakładki. **Zostają.** Testów z tym tekstem nie ma.
- `products-tab-content.html` nie ma tytułu. Zaczyna się paskiem statystyk `:5-26` i filtrami `:29-100`.
- `_serialize_product` (`products_api.py:108`) zwraca `priority_rank` (`:177`), `priority_manual_override` (`:178`),
  `is_priority` (`:275`), dane zamówienia (`internal_order_number`, `baselinker_order_id`), ale **nie zwraca
  `order_id`**. `order = product.order` (`:168`) jest już doczytane przez `joinedload` (`products_tab_content`
  `:714-717`). Ten sam serializer woła archiwum (`_archive_tab_content`, `:635`), więc nowe pola dostaje też ono. `_serialize_production_item` (`:2601`, `GET /products-filtered` i `/products/<id>/details`) też nie ma
  `order_id`.
- `lista.serializuj` (`logistics/services/lista.py:240`) zwraca słownik z `id` = `order.id`, bez gwiazdek. Woła go
  `GET /orders` (`panel_api.py:242`), zapisy panelu (`:282`, `:322`, `:377`, `:393`) i przystanki trasy
  (`trasy_api.py:322`, `GET /routes/<id>`, `:590`).
- `ProductionOrder.priority_stars`: kolumna z K1 (spec 8.1, `TINYINT NOT NULL DEFAULT 0`).

**Interfaces:**
- Produces (JSON listy produktów, `GET /production/api/products-tab-content`, `/products-filtered`, `/products/<id>/details`):
  `"order_id": int|null`, `"order_priority_stars": int` (0–5; brak zamówienia → 0).
- Produces (JSON Logistyki, `GET /production/api/logistics/orders`, odpowiedzi zapisów panelu, `GET /routes/<id>` →
  `przystanki[].zamowienie`): `"gwiazdki": int` (0–5).

- [x] **Step 0: Punkt wyjścia**
  1. `git log -1 --oneline` → hash z karty centrali. Inny hash → STOP, pytanie do centrali.
  2. Przeczytaj raporty K2 i K3 (`docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K2-raport.md`, `…-K3-raport.md`),
     sekcje „Co następny krok musi wiedzieć” i „Odstępstwa”. Potwierdź kształty JSON (tabela „Consumes” w Task 2)
     z testami K2/K3: `grep -n "def kolejka\|def drabina\|def priorytet_zamowienia\|def odlozenia\|route(" modules/production/priorytety/routers/panel_api.py`.
     Wpisz do notatki raportu ścieżka:linia każdej końcówki. Inna nazwa pola przy tej samej semantyce → użyj nazwy
     z kodu (adapter w jednym miejscu `priorytety.js`) i wpisz to w „Odstępstwa”. **Brak końcówki → STOP** przed
     Taskiem, który jej potrzebuje, i meldunek do centrali.
  3. `ls modules/production/priorytety/static` → katalog może nie istnieć (K2 zostawił go K4a). Sprawdź
     `grep -n "static_folder\|static_url_path" modules/production/priorytety/__init__.py` → `static_folder='static'`,
     `static_url_path='/static/priorytety'`. Inaczej STOP.
  4. Pełny pakiet `docker compose exec app pytest tests/ -q -p no:cacheprovider`. Zapisz `passed/skipped/failed`.
     `failed` > 0 → STOP.
  5. **Zrzuty „przed”** (karta 8.4): na podglądzie wskazanym przez centralę otwórz zakładkę „Lista produktów”
     (szerokość 1440 i 390 px), karta zamówienia zwinięta i rozwinięta, pasek hurtu. Zapisz poza repo i podaj ścieżki
     w raporcie.

- [x] **Step 1: Testy, które padną**

`tests/test_priorytety_lista_produkcyjna_ui.py` (nagłówek modułu w stylu `tests/test_produkty_js_hurt_pominiete.py`:
po co, czemu strukturalnie; importy `from tests.krawedzie_fixtures import BASE, JS_PRODUKTY, KORZEN, SZABLON_PRODUKTOW,
app, client, produkt, zrodlo  # noqa: F401`):
- `test_zakladka_nazywa_sie_lista_produkcyjna`: przycisk `id="products-tab"` w `dashboard.html` zawiera „Lista produkcyjna”.
  „Lista produktów” nie występuje w `dashboard.html`, `products-tab-content.html` ani `archive-module.js`. W szablonie
  zakładki jest pasek `class="il-lista-naglowek"` z tekstem „Lista produkcyjna”.
- `test_lista_produkcyjna_ma_order_id_i_gwiazdki`: `produkt(app, status='czeka_na_sklejanie')`, potem zamówieniu
  `priority_stars = 3` i commit. `GET BASE + '/products-tab-content'` → produkt ma `order_id == zamówienie.id`,
  `order_priority_stars == 3`, a `is_priority` i `priority_rank` dalej są w słowniku. To samo dla
  `GET BASE + '/products/<id>/details'` (`product.order_id`, `product.order_priority_stars`).
- `test_lista_produkcyjna_bez_dodatkowych_zapytan`: `tests/blokady_pomocnicze.Zapytania` wokół
  `GET /products-tab-content` z 1 zamówieniem i z 3 zamówieniami (po 2 pozycje). **Łączna** liczba zapytań
  (`len(z.lista)`) jest w obu przypadkach taka sama (wynik `joinedload`, bez zapytań na wiersz). Samo liczenie
  `FROM prod_orders` nie wystarcza: główne zapytanie to `FROM prod_products JOIN prod_orders …`, więc test przeszedłby
  także przy jednym leniwym `SELECT` na zamówienie, jeśli jego tekst wygląda inaczej.

`tests/test_priorytety_logistyka_ui.py` (importy z `tests/logistyka_fixtures.py`: `BASE, app, client, zamowienie, produkt`):
- `test_lista_logistyki_i_przystanki_maja_gwiazdki`: zamówienie z `priority_stars = 2` daje w `GET BASE + '/orders'`
  pole `gwiazdki == 2`, a zamówienie bez gwiazdek daje `0`. Trasa robocza z przystankiem tego zamówienia (wzór
  zakładania trasy z `tests/test_logistyka_trasy*.py`) daje w `GET BASE + '/routes/<id>'` pole
  `route.przystanki[0].zamowienie.gwiazdki == 2` (odpowiedź to `{"success": true, "route": {...}}`, `trasy_api.py:605`).

- [x] **Step 2: Testy padają.**

- [x] **Step 3: Implementacja**
  - `dashboard.html:52`: „Lista produkcyjna”. `:183`: „Błąd ładowania listy produkcyjnej!”. Komentarz `:177`:
    „Zawartość Listy produkcyjnej…”.
  - `products-tab-content.html`: przed `{# ─── STATS BAR ─── #}` dodaj
    `<div class="il-lista-naglowek"><span class="il-lista-tytul">Lista produkcyjna</span>` i miejsce na przycisk
    drabiny (sam przycisk dochodzi w Task 3). Styl w Task 4.
  - `archive-module.js:592`: „Otwórz najpierw zakładkę "Lista produkcyjna"…”.
  - `_serialize_product`: za `'internal_order_number'` dodaj `'order_id': product.order_id` i
    `'order_priority_stars': int(order.priority_stars or 0) if order else 0` z komentarzem „gwiazdki zamówienia
    (priorytety produkcji, K4a); `is_priority` zostaje dla innych czytelników”. Analogicznie w
    `_serialize_production_item` (`item.order_id`, `item.order.priority_stars`).
  - `lista.serializuj`: `'gwiazdki': int(order.priority_stars or 0),` obok `'termin'`, z komentarzem o kolumnie ★
    i przystankach.

- [x] **Step 4: Testy przechodzą:** oba nowe pliki oraz regresja `tests/test_produkty_lista_krawedzie.py tests/test_archive_tab.py
  tests/test_logistyka_poprawki_panelu.py tests/test_paczki_panel.py tests/test_weryfikacja_panel.py
  tests/test_zrodlo_zamowienia.py tests/test_produkty_js_cache_szczegolow.py` (dwa ostatnie wołają oba serializery listy
  produktów wprost).

- [x] **Step 5: Commit** `feat(priorytety): Lista produkcyjna - nazwa zakladki i gwiazdki zamowienia w listach`

---

### Task 2: Wspólny komponent `priorytety.js` — klient API, gwiazdki, modal priorytetu

**Files:**
- Create: `modules/production/priorytety/static/js/priorytety.js`, `modules/production/priorytety/static/css/priorytety.css`
- Modify: `modules/production/templates/panel/dashboard.html` (`<head>`: `<link>` po `products-tab.css` `:11`; skrypty:
  `priorytety.js` **przed** `products-module.js` `:363`)
- Modify: `tests/test_priorytety_lista_produkcyjna_ui.py`

**Stan obecny (ugruntowanie):**
- Wzór klienta API i escapowania: `logistics.js:286-318` (`komunikatBledu`, `zapytanie`: `credentials: 'same-origin'`,
  nagłówki `X-Requested-With`, `Accept`; błąd → wyjątek z `status` i `dane`). Wzór `<dialog>` i `showModal`: modale
  logistyki w `tab_content.html` (np. `:562`, `:594`, `:617`). Skróty klawiaturowe panelu sprawdzają `dialog:modal`
  (`tests/test_logistyka_runda_poprawek_4_10.py`, C-1), więc otwarty `<dialog>` blokuje je poprawnie.
- Globalne serwisy: `window.ProductionShared` (`shared-services.js:838`): `eventBus.on/emit/off` (`:26`, `:50`, `:71`),
  `toastSystem.show(message, type, options)` (`:497`, treść przez `innerHTML` `:542`).
- Statyka blueprintu K2: `url_for('priorytety_panel.static', filename='js/priorytety.js')` →
  `/production/api/priorytety/static/priorytety/js/priorytety.js`.
- Dziś gwiazdki zamówienia nie ma. Jest tylko flaga pozycji przez `set-priority` (`products-module.js:2355-2469`, usuwa Task 4).

**Interfaces:**
- Consumes (K2, `docs/…-krok-K2-panel-api.md`, Task 2–4. Sprawdzone w Task 1, Step 0):

  | Końcówka | Pola, z których korzysta K4a |
  |---|---|
  | `GET /production/api/priorytety/zamowienia/<id>/priorytet` | `zamowienie{order_id,numer,klient}`, `gwiazdki`, `gwiazdki_ustawione{kiedy,kto}\|null`, `aktywne`, `ranga\|null`, `szczebel{id,rodzaj,etykieta,pozycja,z}\|null`, `tagi[]`, `termin`, `trasa{id,nazwa,date_from}\|null`, `stanowiska[{stanowisko,nazwa,pozycji,na_stole[],odlozone[{short_id,powod,notatka,kiedy,pracownik}],w_kolejce{miejsce,z}\|null,niekompletne}]`, `historia[{akcja,stare,nowe,powod,notatka,stanowisko,kiedy,kto}]`; 404 `zamowienie_nieznane` |
  | `PUT /production/api/priorytety/zamowienia/gwiazdki` | ciało `{"order_ids":[int], "gwiazdki":int}` → `{zmienione[], bez_zmian[], nieznane[], przeliczenie: "ok"\|"nieudane"\|"niepotrzebne"}`; 400 `dane_niepoprawne`/`gwiazdki_niepoprawne`/`za_duzo_zamowien`, 404 `zamowienie_nieznane` |
  | `GET /production/api/priorytety/kolejka` | `zamowienia[{order_id, ranga, gwiazdki, szczebel{id,rodzaj,etykieta,pozycja}, tagi[], termin, trasa{id,nazwa,date_from}\|null}]` |
  | `GET /production/api/priorytety/odlozenia` (K3 Task 5) | `odlozenia[{stanowisko, nazwa, order_id, numer, product_id\|null, short_id\|null, powod, notatka, odlozono, pracownik}]` (najdłużej leżące pierwsze) |

  Każdy błąd routera ma postać `{"success": false, "error": "<kod>", "message": "<po polsku>"}`. `guard` zwraca 401
  `{"error": "unauthorized"}` albo 403.
- Produces (`window.Priorytety`, korzystają z niego Task 3, 4, 6 i K4b, jeśli zechce):
  ```
  Priorytety.API = '/production/api/priorytety'
  Priorytety.LIMIT_HURTU = 500
  Priorytety.zapytanie(sciezka, {metoda?, dane?}) -> Promise<object>     // rzuca Priorytety.Blad {status, kod, message}
  Priorytety.esc(tekst) -> string
  Priorytety.gwiazdkiHtml(n, {male?: bool}) -> string                   // 5 znaków ★/☆, aria-label „3 z 5 gwiazdek”, „bez gwiazdek” dla 0
  Priorytety.wybierzGwiazdki(kotwica: Element, aktualne: int) -> Promise<int|null>   // dymek 0–5; Esc/klik obok → null
  Priorytety.ustawGwiazdki(orderIds: int[], gwiazdki: int) -> Promise<object>        // jedyny PUT gwiazdek; emituje 'priorytety:zmiana'
  Priorytety.pobierzKolejke() -> Promise<Map<int, object>>              // order_id → wpis z /kolejka
  Priorytety.pobierzOdlozenia() -> Promise<Map<int, object[]>>          // order_id → odłożenia z /odlozenia
  Priorytety.etykietaOdlozenia(odlozenia: object[]) -> string           // Doprecyzowania p. 6
  Priorytety.etykietaTagu(tag) -> string                                // po_terminie → „Po terminie” itd.
  Priorytety.otworzModalPriorytetu(orderId: int) -> void
  Priorytety.otworzDrabine() -> void                                    // Task 3
  zdarzenie: ProductionShared.eventBus.emit('priorytety:zmiana', {rodzaj: 'gwiazdki'|'drabina', order_ids: int[]})
  ```

- [x] **Step 1: Testy, które padną** (w `tests/test_priorytety_lista_produkcyjna_ui.py`; stała
  `JS_PRIORYTETY = os.path.join(KORZEN, 'modules', 'production', 'priorytety', 'static', 'js', 'priorytety.js')`):
  - `test_priorytety_js_ladowany_w_dashboardzie`: `dashboard.html` ma
    `url_for('priorytety_panel.static', filename='js/priorytety.js') }}?v=` **przed** `js/modules/products-module.js`
    i `<link>` do `css/priorytety.css` z `?v=`. `logistics/templates/logistics/tab_content.html` **nie** zawiera
    `priorytety_panel` (Global Constraints).
  - `test_statyka_priorytetow_serwowana`: minimalna apka (`Flask`, `app.register_blueprint(priorytety_panel_bp,
    url_prefix='/production/api/priorytety')`, bez bazy) → `GET …/static/priorytety/js/priorytety.js` i `…/css/priorytety.css`
    → 200.
  - `test_priorytety_js_koncowki_i_api`: źródło zawiera `window.Priorytety`, `'/production/api/priorytety'`,
    `'/zamowienia/gwiazdki'`, `'/kolejka'`, `'/odlozenia'`, `'/priorytet'`, `LIMIT_HURTU: 500`, `'priorytety:zmiana'`,
    `credentials: 'same-origin'`. Nie zawiera `BaseLinker`, `unpkg.com`, `cdn.`.
  - `test_gwiazdki_jedna_droga_zapisu`: w `priorytety.js` literał `'/zamowienia/gwiazdki'` (razem z apostrofami)
    występuje dokładnie raz, wewnątrz `ustawGwiazdki`. Komentarz nagłówkowy wypisuje ścieżki bez apostrofów, więc się
    nie liczy. W `products-module.js`, `logistics.js` i `logistics-routes.js` nie ma `/priorytety/` ani
    `/zamowienia/gwiazdki`, także w komentarzach (zapis tylko przez `Priorytety.ustawGwiazdki`; Task 6 Step 4).
  - `test_modal_priorytetu_sekcje`: wycinek funkcji `otworzModalPriorytetu`… (do następnej funkcji najwyższego
    poziomu) zawiera `showModal`, nagłówki sekcji „Gwiazdki”, „Szczebel”, „Termin”, „Gdzie leży”, „Odłożenia”,
    „Historia gwiazdek”, tekst `szczebel ' +` … `' z '` (format „szczebel 1 z 11”), obsługę `aktywne === false`
    („poza kolejką produkcji”), filtr `akcja === 'gwiazdki'` i przycisk „Bez gwiazdek”.
  - `test_przeliczenie_nieudane_ostrzega`: w `ustawGwiazdki` (albo jego wołającym w module) jest gałąź
    `przeliczenie === 'nieudane'` z `toastSystem.show(…, 'warning'…)` i tekstem „przeliczy się”.
  - `test_priorytety_js_dane_z_api_tylko_przez_esc`: dla każdego wystąpienia
    `\.(klient|nazwa|etykieta|notatka|pracownik|message|numer|kto|short_id)\b` w liniach `priorytety.js`, które
    składają HTML (zawierają `'<'` albo `innerHTML`/`insertAdjacentHTML`), wystąpienie jest objęte `esc(`. Wzór
    regexu i wyjątków (np. `textContent =`) opisz w docstringu testu. Funkcja `esc` zamienia `& < > " '`.

- [x] **Step 2: Testy padają.**

- [x] **Step 3: `priorytety.js` — szkielet i klient** (IIFE, `'use strict'`, idempotentny: jeśli `window.Priorytety`
  już jest, nie definiuj drugi raz). Komentarz nagłówkowy po polsku z listą końcówek (wzór `logistics.js:1-30`).
  Pseudokod:
  ```js
  const API = '/production/api/priorytety';
  class Blad extends Error { constructor(message, status, kod) { … } }
  async function zapytanie(sciezka, o = {}) {
      // jak logistics.js:295-318; komunikat: dane.message || (status 401 → „Sesja wygasła. Zaloguj się ponownie.”,
      // 403 → „Brak uprawnień do priorytetów.”, 0 → „Brak połączenia z serwerem.”, inaczej „Błąd serwera (status).”)
  }
  function powiadom(tresc, typ) { const t = window.ProductionShared && ProductionShared.toastSystem;
      if (t) t.show(esc(tresc), typ, { duration: typ === 'warning' ? 8000 : 4000 }); }
  async function ustawGwiazdki(orderIds, gwiazdki) {
      const ids = Array.from(new Set(orderIds.filter(Number.isInteger)));
      if (!ids.length) throw new Blad('Nie wybrano zamówień.', 400, 'dane_niepoprawne');
      if (ids.length > LIMIT_HURTU) throw new Blad('Najwyżej ' + LIMIT_HURTU + ' zamówień naraz.', 400, 'za_duzo_zamowien');
      const odp = await zapytanie('/zamowienia/gwiazdki', { metoda: 'PUT', dane: { order_ids: ids, gwiazdki } });
      if (odp.przeliczenie === 'nieudane') powiadom('Gwiazdki zapisane. Kolejka przeliczy się przy najbliższym przebiegu (do godziny).', 'warning');
      emituj('gwiazdki', ids);
      return odp;
  }
  ```

- [x] **Step 4: Gwiazdki i wybierak.** `gwiazdkiHtml(n)`: `<span class="pr-gwiazdki pr-gwiazdki--n" role="img"
  aria-label="3 z 5 gwiazdek">★★★☆☆</span>`. Dla 0: `☆☆☆☆☆` i „bez gwiazdek”. `wybierzGwiazdki(kotwica, aktualne)`:
  jeden dymek na stronę (`div.pr-wybierak[role=dialog]`), sześć przycisków „0” (Bez gwiazdek), „1”…„5” z
  `aria-pressed` dla aktualnej wartości, strzałki ←/→ przenoszą fokus, Enter wybiera, Esc i klik obok dają `null`.
  Pozycja pod kotwicą, w obrębie okna (`getBoundingClientRect`). Dymek to `div` z klasą `pr-wybierak`, a nie
  `<dialog>`, więc `dialog:modal` w skrótach panelu go nie widzi. Klawisze listy wyłącza `handleKeydown` (Doprecyzowania
  p. 14, Task 4).

- [x] **Step 5: Modal priorytetu** (`otworzModalPriorytetu(orderId)`). Jeden `<dialog class="pr-modal" id="pr-modal-priorytetu">`
  na stronę, tworzony leniwie i dołączany do `document.body`. Zawartość z `GET /zamowienia/<id>/priorytet`:
  1. Nagłówek: „Priorytet zamówienia {numer}” + klient. Przycisk „Zamknij”.
  2. **Gwiazdki:** pięć przycisków-gwiazdek (klik n-tej ustawia n) i „Bez gwiazdek” (0). Pod spodem „Ustawił: {kto},
     {kiedy}” albo „Nikt jeszcze nie ustawiał”. Klik idzie przez `ustawGwiazdki([orderId], n)`. W trakcie zapisu
     `zapisTrwa = true`, przyciski mają `aria-disabled`, a kolejne kliknięcia są ignorowane. Po sukcesie modal czyta
     dane od nowa. Błąd daje komunikat w modalu (`role="alert"`) i stan bez zmian.
  3. **Szczebel:** „{etykieta}, szczebel {pozycja} z {z}”, „Miejsce w kolejce: {ranga}”. Gdy `aktywne === false`:
     „Zamówienie jest poza kolejką produkcji (spakowane, wstrzymane albo anulowane).”
  4. **Termin i tagi:** data `dd.mm.rrrr` i plakietki tagów (`etykietaTagu`). Bez terminu: „brak terminu”.
  5. **Trasa:** nazwa i „od {date_from}”, albo „bez trasy”.
  6. **Gdzie leży:** tabela po `stanowiska[]` z kolumnami: Stanowisko, Pozycji, Na stole (lista `short_id`/numer albo „—”),
     Odłożone (liczba), W kolejce („{miejsce} z {z}” albo „—”), oraz znacznik „niekompletne” na stanowiskach
     zamówieniowych. Pusta lista daje „Żadna pozycja nie czeka na stanowisku.”
  7. **Odłożenia:** lista z `stanowiska[].odlozone` w formacie „{Stanowisko}: {powód}, {notatka}, {kiedy hh:mm dd.mm}, {pracownik}”.
     Gdy ich nie ma, sekcja jest ukryta.
  8. **Historia gwiazdek:** `historia.filter(h => h.akcja === 'gwiazdki')`, wiersze „{stare} → {nowe} · {kto} · {kiedy}”,
     najwyżej 20. Gdy brak: „Brak zmian gwiazdek”.
  Escapowanie: wszystkie pola z API przez `esc`. Fokus po otwarciu na przycisku aktualnej liczby gwiazdek, po zamknięciu
  wraca na element, który otworzył modal. 404 daje „Nie ma takiego zamówienia.”

- [x] **Step 6: `priorytety.css`** (prefiks `pr-`, kolory jak `products-tab.css`: `--il-status-warn` dla gwiazdek;
  modal max-width 720 px, na ≤ 600 px pełna szerokość; tabela „Gdzie leży” z przewijaniem w poziomie).
  `dashboard.html`: `<link rel="stylesheet" href="{{ url_for('priorytety_panel.static', filename='css/priorytety.css') }}?v=…">`
  po `products-tab.css` i `<script src="{{ url_for('priorytety_panel.static', filename='js/priorytety.js') }}?v=…"></script>`
  bezpośrednio przed `products-module.js`.

- [x] **Step 7: Testy przechodzą** (plik). **Step 8: Commit**
`feat(priorytety): wspolny komponent priorytetow i modal priorytetu zamowienia`

---

### Task 3: Modal „Drabina priorytetów”

**Files:**
- Modify: `modules/production/priorytety/static/js/priorytety.js`, `.../css/priorytety.css`
- Modify: `modules/production/templates/components/products-tab-content.html` (przycisk w pasku `il-lista-naglowek` z Task 1)
- Modify: `tests/test_priorytety_lista_produkcyjna_ui.py`

**Stan obecny (ugruntowanie):**
- Drabina w UI nie istnieje. Odpowiedź K2 (`GET /drabina`, K2 Task 2): `{"uzupelniono": n, "szczeble": [{"id", "rodzaj":
  "gwiazdki"|"tag"|"trasa", "gwiazdki", "tag", "trasa": {id,nazwa,status,date_from,date_to}|null, "pozycja", "etykieta",
  "ruchomy", "w_produkcji"}], "ostrzezenia": [{"kod": "daty_tras"|"samonaprawa_nieudana", "route_ids"?, "message"}]}`.
  `PUT /drabina/kolejnosc` przyjmuje `{"szczebel_id", "pozycja", "oczekiwane"?}` i zwraca to samo plus
  `"przeliczenie"`. Błędy: 400 `szczebel_staly`/`pozycja_niepoprawna`/`dane_niepoprawne`, 404 `szczebel_nieznany`,
  409 `trasa_nieaktywna`/`drabina_zmieniona`.
- Wzór przycisków ↑/↓ z `aria-label` i fokusem po przerysowaniu: przystanki w `logistics-routes.js:2204-2209`
  (`data-lg-przystanek="gora"|"dol"`, `disabled` na krańcach) i `fokusPrzystanku` (`:2219`).

**Interfaces:**
- Consumes: `GET /drabina`, `PUT /drabina/kolejnosc` (wyżej).
- Produces: `Priorytety.otworzDrabine()`. Przycisk `<button type="button" class="il-btn-secondary il-drabina-btn"
  data-priorytety="drabina">Drabina priorytetów</button>`. Kliknięcie obsługuje `products-module.js` (Task 4) przez
  `Priorytety.otworzDrabine()`.

- [x] **Step 1: Testy, które padną**
  - `test_przycisk_drabiny_w_naglowku_zakladki`: szablon zakładki ma `data-priorytety="drabina"` z tekstem
    „Drabina priorytetów” w `il-lista-naglowek`.
  - `test_drabina_strzalki_tylko_dla_ruchomych`: w wycinku funkcji renderującej wiersz drabiny (`wierszDrabiny(…)`)
    strzałki `data-pr-drabina="gora"` i `"dol"` są w gałęzi `s.ruchomy`, a w gałęzi stałej jest znacznik „stały”
    (ikona kłódki, `title="Szczebel gwiazdek jest stały"`). Strzałka „gora” dostaje `disabled` przy indeksie 0, a „dol”
    przy ostatnim. Każda strzałka ma `aria-label` z etykietą szczebla (przez `esc`).
  - `test_drabina_wysyla_oczekiwane_i_obsluguje_409`: funkcja zapisu (`przesunSzczebel`) wysyła `'/drabina/kolejnosc'`
    metodą `PUT` z kluczami `szczebel_id`, `pozycja`, `oczekiwane`. `oczekiwane` pochodzi z mapy id ostatniego odczytu.
    Jest gałąź `kod === 'drabina_zmieniona'`, która ponownie czyta `'/drabina'` i pokazuje komunikat z Doprecyzowań
    p. 8. Jest gałąź `przeliczenie === 'nieudane'` z ostrzeżeniem. Po sukcesie emituje `'priorytety:zmiana'`
    z `rodzaj: 'drabina'`.
  - `test_jeden_zapis_naraz`: `przesunSzczebel` zaczyna się od `if (zapisTrwa) return;`, ustawia `zapisTrwa = true`
    i zdejmuje flagę w `finally`. Ten sam wzór ma zapis gwiazdek w modalu priorytetu (Task 2).
  - `test_drabina_liczniki_ostrzezenia_i_trasy`: renderowanie pokazuje `w_produkcji` („{n} w produkcji”), klasę
    `pr-szczebel--pusty` dla `w_produkcji === 0`, daty trasy `date_from`–`date_to`, listę `ostrzezenia[].message`
    (przez `esc`) w `role="status"`, informację przy `uzupelniono > 0` i plakietkę statusu trasy.

- [x] **Step 2: Testy padają.**

- [x] **Step 3: Implementacja `otworzDrabine()`.** Jeden `<dialog class="pr-modal pr-modal--drabina">`. Lista `<ol>`
  z `szczeble` w kolejności `pozycja`. Wiersz: numer pozycji, ikona rodzaju (gwiazdki / tag / ciężarówka dla trasy),
  etykieta (dla gwiazdek `gwiazdkiHtml(n)`, dla trasy nazwa i daty), licznik `w_produkcji`, strzałki albo „stały”.
  Nad listą ostrzeżenia i opis jednym zdaniem: „Zamówienie z trasy bierze szczebel trasy. Zamówienie bez trasy bierze
  najwyższy ze swoich szczebli (gwiazdki, tagi).”
- [x] **Step 4: Przesuwanie.**
  ```js
  async function przesunSzczebel(id, kierunek) {           // kierunek: -1 (w górę) | +1 (w dół)
      if (zapisTrwa) return;
      const i = stanDrabiny.szczeble.findIndex(s => s.id === id);
      const cel = i + 1 + kierunek;                         // pozycja 1-based w widocznej drabinie
      if (i < 0 || cel < 1 || cel > stanDrabiny.szczeble.length) return;
      zapisTrwa = true; oznaczCzekanie(true);
      try {
          const odp = await zapytanie('/drabina/kolejnosc', { metoda: 'PUT',
              dane: { szczebel_id: id, pozycja: cel, oczekiwane: stanDrabiny.szczeble.map(s => s.id) } });
          stanDrabiny = odp; renderujDrabine(); przywrocFokus(id, kierunek);
          if (odp.przeliczenie === 'nieudane') powiadom('Kolejność zapisana. Kolejka przeliczy się przy najbliższym przebiegu (do godziny).', 'warning');
          emituj('drabina', []);
      } catch (e) {
          if (e.kod === 'drabina_zmieniona') { await wczytajDrabine(); komunikatDrabiny(…p. 8…); }
          else komunikatDrabiny(e.message);                 // 409 trasa_nieaktywna, 400 szczebel_staly itd.
      } finally { zapisTrwa = false; oznaczCzekanie(false); }
  }
  ```
  Fokus po przerysowaniu wraca na tę samą strzałkę tego samego szczebla. Na krańcu, gdzie strzałka jest `disabled`,
  przechodzi na drugą strzałkę.
- [x] **Step 5: Testy przechodzą.**
- [ ] **Step 6 (opcjonalny, poza DoD): drag&drop** — POMINIĘTY (raport K4a, Rozstrzygnięcie 6).
  Treść kroku: wierszy ruchomych (natywne HTML5 DnD, `draggable` tylko na
  ruchomych). Upuszczenie woła tę samą ścieżkę zapisu (`przesunSzczebelNa(id, pozycja)`, wspólne ciało z Step 4).
  Klawiatura zostaje przy strzałkach. Jeśli pominięty, napisz to w raporcie („Odstępstwa: brak”, „Rozstrzygnięcia”).
- [x] **Step 7: Commit** `feat(priorytety): modal drabiny priorytetow ze strzalkami i ostrzezeniem o datach`

---

### Task 3a (dopisany z karty K4a, spec 5.7, 7.1): „Wyślij na stanowisko” i „Zdejmij ze stołu” w modalu priorytetu

**Źródło:** karta K4a, Start 3 (decyzje Konrada/centrali): w modalu priorytetu przy każdym stanowisku, na którym
zamówienie ma pozycje, przycisk „Wyślij na stanowisko” (`POST /production/api/priorytety/stoly/<kod>/wyslij`), a przy
kaflu leżącym na stole albo odłożonym „Zdejmij ze stołu” (`POST …/stoly/<kod>/zdejmij`); komunikaty dla wszystkich
kodów błędów z raportu K3; przy „Zdejmij” na doróbce albo kaflu, który jest pierwszy w kolejce, opis „Kafel wróci przy
następnym dopełnieniu stołu” (pytanie 9 raportu K3, bez zmiany zachowania serwera). Historia w modalu pokazuje też
`wyslanie`, `zdjecie`, `odlozenie`, `odlozenie_zamkniete`, `start_stolow`. Pracownik odłożenia w panelu — pełne imię
i nazwisko (Konrad 5.10). Spec 7.1 i 5.7 wygrywają nad Task 2 Step 5 p. 8 („Historia gwiazdek” z samym filtrem
`akcja === 'gwiazdki'`): sekcja nazywa się „Historia”.

**Files:**
- Modify: `modules/production/priorytety/static/js/priorytety.js`, `.../css/priorytety.css`
- Modify: `tests/test_priorytety_lista_produkcyjna_ui.py`

**Stan obecny (ugruntowanie, kod K2/K3 na `2634c5b8`):**
- Modal (`widok.priorytet_zamowienia`): `stanowiska[]` tylko dla zamówienia aktywnego, `na_stole` = lista NAPISÓW
  (`short_id` albo numer zamówienia), `odlozone[]` bez `unit_key`. Klucza kafla, źródła i doróbki modal nie podaje.
- `GET /stoly` (`widok.stoly_panelu`, K3): 6 stanowisk ze stołem (bez Lakierni), kafle `stol[]`/`odlozone[]` z `unit_key`,
  `order_id`, `short_id`/`numer`, `zrodlo` (`kolejka|dorobka|biuro|start`), `dorobka` (kafel pozycji), `wyslal`,
  odłożone także `powod`, `notatka`, `odlozono`, `pracownik` (pełne imię i nazwisko). Same zwykłe odczyty.
- `POST /stoly/<kod>/wyslij` `{order_id}` → 200 `{wynik: "wyslano"|"juz_na_stole", wyslane[], przywrocone[], juz_na_stole[]}`;
  błędy 400 `dane_niepoprawne`/`stanowisko_nieznane`, 404 `zamowienie_nieznane`, 409 `brak_na_stanowisku`/
  `stanowisko_bez_stolu`/`delivery_method_not_set`, 500 `blad_serwera`.
- `POST /stoly/<kod>/zdejmij` `{unit_key}` → 200 `{unit_key, order_id, product_id, odlozony}`; 404 `brak_kafla`,
  400 `dane_niepoprawne`/`stanowisko_nieznane`, 500 `blad_serwera`.
- `GET /kolejka?stanowisko=S&limit=1` → `kafle[0]` = pierwszy kafel kolejki (`product_id` albo `order_id` wg jednostki).

**Rozstrzygnięcie (bez zmian K2/K3):** klucz kafla dla „Zdejmij” bierzemy z `GET /stoly`, czytanego przy otwarciu modalu
**tylko wtedy**, gdy któreś stanowisko zamówienia ma coś na stole albo odłożone (`na_stole.length || odlozone.length`).
Błąd `/stoly` → kolumna „Na stole” z napisów modalu, bez przycisków „Zdejmij” i z uwagą. Lakiernia (`painting`,
lustro `ustawienia.STANOWISKA_BEZ_STOLU`) nie dostaje „Wyślij” — opis „pracuje z listy, bez stołu”.

**Interfaces:**
- Consumes: wyżej.
- Produces: `Priorytety.wyslijNaStanowisko(kod, orderId) -> Promise<object>`, `Priorytety.zdejmijZeStolu(kod, unitKey)
  -> Promise<{odp, wroci: bool}>` (jedyne miejsca POST `/wyslij` i `/zdejmij` we froncie; emitują `priorytety:zmiana`
  z `rodzaj: 'stol'`), `Priorytety.komunikatStolu(blad, kod) -> string`.

- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_lista_produkcyjna_ui.py`):
  - `test_modal_wyslij_przy_kazdym_stanowisku`: wiersz „Gdzie leży” ma przycisk `data-pr-akcja="wyslij"` z
    `data-stanowisko` i tekstem „Wyślij na stanowisko”; dla stanowiska z `STANOWISKA_BEZ_STOLU` (`'painting'`) zamiast
    przycisku opis „bez stołu”.
  - `test_wyslij_i_zdejmij_jedna_droga`: w `priorytety.js` literały `'/wyslij'` i `'/zdejmij'` stoją po jednym razie,
    odpowiednio w `wyslijNaStanowisko` (metoda `POST`, `order_id`) i `zdejmijZeStolu` (`POST`, `unit_key`);
    w `products-module.js`, `logistics.js`, `logistics-routes.js` nie ma `/stoly/`.
  - `test_zdejmij_z_kluczem_z_stolow`: modal czyta `'/stoly'` tylko w gałęzi `na_stole.length || … odlozone.length`,
    filtruje kafle po `order_id`, przycisk `data-pr-akcja="zdejmij"` niesie `data-unit-key` (przez `esc`) i
    `data-stanowisko`; kafle na stole i odłożone mają ten przycisk.
  - `test_komunikaty_wszystkich_kodow_stolu`: słownik komunikatów ma klucze `dane_niepoprawne`, `stanowisko_nieznane`,
    `zamowienie_nieznane`, `brak_na_stanowisku`, `stanowisko_bez_stolu`, `delivery_method_not_set`, `brak_kafla`,
    `blad_serwera`; komunikat idzie do modalu przez `esc`.
  - `test_zdejmij_opis_powrotu`: tekst „Kafel wróci przy następnym dopełnieniu stołu” przy kaflu doróbki
    (`dorobka` / `zrodlo === 'dorobka'`) przed kliknięciem oraz po udanym „Zdejmij”, gdy `'/kolejka?stanowisko='` z
    `limit=1` oddaje ten sam kafel jako pierwszy.
  - `test_historia_akcje_stolu`: historia filtruje akcje `gwiazdki`, `wyslanie`, `zdjecie`, `odlozenie`,
    `odlozenie_zamkniete`, `start_stolow` (każda z etykietą), nagłówek „Historia”; pracownik i `kto` wyświetlane bez
    skracania (brak `split(` na tych polach).
  - `test_akcje_stolu_jeden_zapis_naraz`: obsługa `wyslij`/`zdejmij` w modalu zaczyna się od `if (zapisTrwa) return;`
    i zdejmuje flagę w `finally`; po sukcesie modal czyta dane od nowa.
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Implementacja** w `priorytety.js` (sekcja „Gdzie leży” z kolumną akcji, „Odłożenia” z „Zdejmij”,
  komunikat w `role="alert"`/`role="status"` modalu, historia z etykietami akcji) i `priorytety.css`.
- [x] **Step 4: Testy przechodzą** (plik).
- [x] **Step 5: Commit** `feat(priorytety): Wyslij na stanowisko i Zdejmij ze stolu w modalu priorytetu`

---

### Task 4: Lista produkcyjna — karty po randze, przycisk gwiazdek, plakietki, hurt; usunięcie martwego kodu

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js`
- Modify: `modules/production/templates/components/products-tab-content.html` (`:107-120` nagłówki, `:147-152` pasek hurtu,
  `:190-216` szablon karty, `:218-232` szablon wiersza, `:268-274` i `:316-330` w szablonie modalu akcji grupowych, `:375`)
- Modify: `modules/production/static/css/products-tab.css` (`:350-365`, `:416-430`, `:714-763`, `:1118-1165`, `:1243-1264`)
- Modify: `modules/production/templates/panel/dashboard.html` (`:11` wersja CSS, `:361` usunięty skrypt, `:363` wersja JS)
- Delete: `modules/production/static/js/modules/products-dragdrop.js`
- Modify: `tests/test_priorytety_lista_produkcyjna_ui.py`

**Stan obecny (ugruntowanie, `products-module.js` @ `b4b4a54d`):**

| Miejsce | Stan | Zmiana |
|---|---|---|
| `:16` | komentarz „ProductsDragDrop will be loaded dynamically” | usuń |
| `:103` | `dragDrop: null` w `this.components` | usuń |
| `:184` (`this.onKeydown`), `:2734-2756` (`handleKeydown`) | Esc czyści selekcję, Ctrl+A zaznacza wszystko — nasłuch na `document` | na początku `handleKeydown`: `if (document.querySelector('dialog[open], .pr-wybierak')) return;` (Doprecyzowania p. 14) |
| `:245-248` (`unload`), `:278-281` (`destroy`), `:361` (`initializeComponents`), `:690-713` (`initializeDragDrop`), `:5600-5626` (`enableDragDrop`, `disableDragDrop`, `isDragDropEnabled`, `isDragging`) | obsługa `ProductsDragDrop` | usuń (grep `dragDrop` → pusto) |
| `:832-833` | NOTE o `#bulk-set-priority` | usuń |
| `:874-896` (`showLoadingAndLoadProducts`), `:257-272` (`refresh`) | ładują produkty i filtry | po `loadProductsData()` dodaj `await this.wczytajPriorytety()` (nie rzuca) |
| `:1372-1437` (`groupProductsIntoOrders`) | `isPriority` (`:1393`, `:1405`) z `is_priority` pozycji | zamiast `isPriority`: `orderId` (`product.order_id`), `gwiazdki` (`product.order_priority_stars`) |
| `:1471-1511` (`createOrderCard`) | `data-order-key` | dodaj `data-order-id` |
| `:1513-1543` (`populateCardMeta`, układ mobilny) | status, metryki, termin | dodaj gwiazdki i plakietki (te same funkcje co w nagłówku) |
| `:1545-1601` (`populateOrderHeader`) | gwiazdka all/partial (`:1550-1559`) | ranga `#n` w pierwszej kolumnie, przycisk gwiazdek, plakietki w `.il-order-ids` |
| `:1603-1736` (`attachOrderEventListeners`) | wyjątki kliknięcia `.il-star-btn`, `.il-drag-handle` (`:1609-1612`), gwiazdka → `toggleOrderPriority` (`:1672-1677`), przeciąganie karty (`:1724-1735`) | wyjątek `.il-priorytet-btn` i `.il-prio-tag`; przycisk otwiera `Priorytety.otworzModalPriorytetu(order.orderId)`; przeciąganie usunięte |
| `:1825-1853` (`sortOrders`) | domyślnie po terminie (`:1829-1836`) | domyślnie po randze z `this.state.priorytety` (pseudokod niżej) |
| `:1888-1899` (`_createILProductRow`) | gwiazdka pozycji → `toggleProductPriority` | usuń |
| `:1960`, `:1963` (`_createOldProductRow`, ścieżka nieużywana) | `data-priority` z `priority_rank`, `data-is-priority` z `is_priority` | usuń obie linie (reszta funkcji zostaje, Poza zakresem) |
| `:1993-2008` (`populateProductRow`, ścieżka nieużywana) | gwiazdka i `priority_rank` | usuń oba bloki |
| `:2323-2339` (`attachRowEventListeners`, ścieżka nieużywana) | `this.handleStarClick(…)` (`:2328`), `this.showEditPriorityModal(…)` (`:2337`). **Obie metody nie są nigdzie zdefiniowane** (`grep -rn "handleStarClick\|showEditPriorityModal" modules` → tylko te wywołania) | usuń oba bloki |
| `:2355-2469` (`toggleProductPriority`, `toggleOrderPriority`, `_sendPriorityUpdate` z `fetch('/production/api/set-priority')` `:2383`, `refreshStarUI`) | stara gwiazdka | usuń całą sekcję |
| `:2758-2782` (`handleBulkAction`) | `change-status`, `export-selected`, `delete` | dodaj `case 'stars'` |
| `:3284-3350` (`toggleBulkActionsVisibility`, obsługa `il-bulk-bar` `:3322-3343`) | `status`, `export`, `delete` | dodaj `stars` |
| `:3605-3614` (`updatePriorityColor`, bez wołających) | progi 180/140/80 | usuń |
| `:3778-3797` (`updateHeaderStatus`) | `priority-indicator` + `getPriorityClass` (`:3781`, `:3793-3796`) | usuń blok wskaźnika |
| `:5593-5598` (`getPriorityClass`) | progi 180/140/80 | usuń |

Szablon i CSS:
- `products-tab-content.html:190-216`: karta ma `il-drag-handle` (`:193`) i `il-star-btn` (`:195`). `:218-232`: wiersz
  pozycji z `il-star-btn il-product-star` (`:221`). Nagłówki kolumn `:108-120` to 11 `<span>` (puste 1, 3, 4).
  Pasek hurtu `:148-152`. Szablon `bulk-actions-modal-template` (`:243-347`) nie ma użytkownika w JS
  (`grep -rn "bulk-actions-modal\|bulk-action-btn" modules/production/static/js` → pusto). Usuwamy z niego tylko przycisk
  `data-action="set-priority"` (`:268-274`) i `bulk-priority-form` (`:316-330`), a resztę zostawiamy (poza zakresem).
- `products-tab.css`: siatka 11 kolumn `:353`, `:419` (`20px 24px 24px 20px 2fr …`), media `1200px` `:1121-1137`
  (ukrywa `nth-child(8)`), `900px` `:1140-1163` (ukrywa `nth-child(3)`, `(7)`, `(8)`), mobilne `:1243-1264`
  (`.il-drag-handle`, `.il-order-header .il-star-btn`). Style `.il-drag-handle` `:714-733`, `.il-star-btn` z `.partial`
  `:735-763`.
- `products-dragdrop.js` (785 linii) woła `/production/api/update-priority` (`:535`), które usunął K2. Ładuje go tylko
  `dashboard.html:361`.

**Interfaces:**
- Consumes: `window.Priorytety` (Task 2–3), pola listy `order_id`, `order_priority_stars` (Task 1).
- Produces (`ProductsModule`): `async wczytajPriorytety()` (wypełnia `this.state.priorytety: Map`,
  `this.state.odlozenia: Map`, `this.state.priorytetyBlad: bool`; nie rzuca), `plakietkiPriorytetuHtml(order) -> string`,
  `showBulkStarsPicker(selectedIds)`. Nasłuch `ProductionShared.eventBus.on('priorytety:zmiana', …)` rejestrowany
  w `setupEventListeners`; funkcję wyrejestrowania, którą zwraca `on`, moduł trzyma (np. `this._odpinijPriorytety`)
  i woła w `unload` (Doprecyzowania p. 12).

- [x] **Step 1: Testy, które padną**
  - `test_brak_przeciagania_na_liscie`: plik `products-dragdrop.js` nie istnieje. `dashboard.html` nie zawiera
    `products-dragdrop`. `products-module.js` nie zawiera `ProductsDragDrop`, `dragDrop`, `il-drag-handle`, `draggable`,
    `dragstart`. Szablon zakładki nie zawiera `il-drag-handle`.
  - `test_brak_starej_gwiazdki_i_progow_rangi`: `products-module.js` nie zawiera `showEditPriorityModal`,
    `handleStarClick`, `getPriorityClass`, `updatePriorityColor`, `toggleProductPriority`, `toggleOrderPriority`,
    `_sendPriorityUpdate`, `refreshStarUI`, `set-priority`, `is_priority`, `priority-critical`, `'partial'` (kod dodaje
    klasę napisem `classList.add('partial')`, więc szukamy napisu z apostrofami, nie selektora `.partial`). Szablon nie
    zawiera `il-product-star`, `il-star-btn`, `bulk-priority-form`, `data-action="set-priority"`, `priority-indicator`.
    `products-tab.css` nie zawiera `.il-star-btn` ani `.il-drag-handle`.
  - `test_sortowanie_kart_po_randze_z_kolejki`: metoda `sortOrders()` w gałęzi `if (!col)` czyta
    `this.state.priorytety`, porównuje `ranga`, zamówienia bez rangi idą po zamówieniach z rangą i między sobą są
    sortowane po `deadline`. Gałąź `this.state.priorytetyBlad` sortuje po `deadline` (dzisiejsze zachowanie).
  - `test_blad_priorytetow_nie_psuje_listy`: `wczytajPriorytety()` ma `try/catch`, w `catch` ustawia
    `this.state.priorytetyBlad = true` i nie rzuca dalej. W szablonie jest element `id="il-priorytety-ostrzezenie"`
    (`hidden`) z tekstem z Doprecyzowań p. 2. `showLoadingAndLoadProducts` i `refresh` wołają `wczytajPriorytety`
    **po** `loadProductsData`.
  - `test_karta_ma_range_przycisk_gwiazdek_i_plakietki`: szablon karty ma `il-order-ranga` jako pierwsze dziecko
    `.il-order-header` i `button.il-priorytet-btn` jako trzecie (z `aria-haspopup="dialog"`). `populateOrderHeader`
    woła `Priorytety.gwiazdkiHtml` i `this.plakietkiPriorytetuHtml(order)`. `attachOrderEventListeners` woła
    `Priorytety.otworzModalPriorytetu(order.orderId)`. Nagłówki kolumn mają `#` w pierwszym `<span>` i `★` w trzecim,
    razem 11 `<span>` jak dotąd.
  - `test_plakietki_karty_przez_esc`: `plakietkiPriorytetuHtml` składa plakietki `il-prio-tag--trasa`,
    `il-prio-tag--po_terminie`, `il-prio-tag--blisko_terminu`, `il-prio-tag--rozpoczete`, `il-prio-tag--odlozone`.
    Nazwa trasy i etykiety w treści idą przez `this.escapeHtml(`, a każde `title="` i `aria-label="` w
    `plakietkiPriorytetuHtml` i w przycisku gwiazdek (`populateOrderHeader`) przez `this.escapeAttr(` (Global
    Constraints). Tekst plakietki odłożeń pochodzi z `Priorytety.etykietaOdlozenia`.
  - `test_klawisze_listy_pomijaja_okna_priorytetow`: `handleKeydown` zaczyna się od sprawdzenia
    `dialog[open]` i `.pr-wybierak` z `return` przed obsługą Esc i Ctrl+A (Doprecyzowania p. 14).
  - `test_hurt_gwiazdek_unikalne_zamowienia_i_limit`: pasek `#il-bulk-bar` ma `data-action="stars"` z tekstem
    „Ustaw gwiazdki”. `handleBulkAction` ma `case 'stars'`. `showBulkStarsPicker` zbiera `order_id` przez `new Set(`,
    sprawdza `Priorytety.LIMIT_HURTU` przed wywołaniem i woła wyłącznie `Priorytety.ustawGwiazdki`.
  - `test_nasluch_zmiany_priorytetow`: `eventBus.on('priorytety:zmiana'` w `setupEventListeners`, a jego wynik
    przypisany do pola modułu, które `unload` woła. W pliku nie ma `off('priorytety:zmiana')` (zdjęłoby cudzych
    słuchaczy). Handler woła `wczytajPriorytety()` i `applyAllFilters()`.
  - `test_podbite_wersje_listy`: w `dashboard.html` wersja `products-module.js` jest większa od `'20261002a'`,
    a `products-tab.css` od `'20260805'` (porównanie napisów jak w `test_produkty_js_hurt_pominiete.py:75-79`; regex
    tam to `\?v=(\d+[a-z]?)`, więc nowa wersja ma jedną literę, np. `20261006a`).
- [x] **Step 2: Testy padają.**

- [x] **Step 3: Szablon.** Karta: `<span class="il-order-ranga" title="Miejsce w kolejce produkcji"></span>` zamiast
  uchwytu. `<button type="button" class="il-priorytet-btn" aria-haspopup="dialog" title="Priorytet zamówienia"></button>`
  zamiast gwiazdki. Wiersz pozycji bez gwiazdki. Nagłówki: `<span>#</span>`, checkbox, `<span>★</span>`. Pasek hurtu:
  `<button class="il-bulk-btn" data-action="stars"><i class="fas fa-star"></i> Ustaw gwiazdki</button>` przed „Eksport”.
  Ostrzeżenie `<div id="il-priorytety-ostrzezenie" class="il-priorytety-ostrzezenie" role="status" hidden>`.
  Usunięcia z „Stan obecny”.
- [x] **Step 4: Dane i sortowanie.**
  ```js
  async wczytajPriorytety() {
      // Oba odczyty równolegle; błąd /odlozenia nie psuje kolejności kart (tylko brak plakietek odłożeń).
      const odlozeniaP = Priorytety.pobierzOdlozenia().catch((e) => {
          console.warn('[ProductsModule] Odłożenia niedostępne:', e); return new Map(); });
      try {
          const [kolejka, odlozenia] = await Promise.all([Priorytety.pobierzKolejke(), odlozeniaP]);
          this.state.priorytety = kolejka; this.state.odlozenia = odlozenia; this.state.priorytetyBlad = false;
      } catch (e) {
          console.warn('[ProductsModule] Priorytety niedostępne:', e);
          this.state.priorytety = new Map(); this.state.odlozenia = new Map(); this.state.priorytetyBlad = true;
      }
      // pokaż/ukryj #il-priorytety-ostrzezenie
  }
  sortOrders() — gałąź domyślna (!col):
      if (this.state.priorytetyBlad) → dzisiejsze sortowanie po deadline
      else klucz(o) = [ranga ?? Infinity, deadline ?? '9999', internalOrderNumber]; ranga = this.state.priorytety.get(o.orderId)?.ranga
  ```
  Brak `window.Priorytety` (plik się nie wczytał) liczy się jak błąd. Wtedy `wczytajPriorytety` ustawia
  `priorytetyBlad` i lista działa po terminie.
- [x] **Step 5: Nagłówek karty i plakietki.** `il-order-ranga`: `#{ranga}` albo „—”. Przycisk:
  `Priorytety.gwiazdkiHtml(order.gwiazdki, {male: true})`, a w `title` „{etykieta szczebla}, miejsce {ranga}”
  (przez `this.escapeAttr`, albo `setAttribute('title', …)`).
  `plakietkiPriorytetuHtml(order)`:
  trasa (ikona FA `fa-truck` + nazwa + `dd.mm` z `date_from`), wszystkie tagi z `wpis.tagi` (także ten, który
  wyznacza szczebel; spec 7.1 wymienia tag jako plakietkę), „Odłożone na …” po stanowiskach. Wstaw do
  `.il-order-ids` za numerami (desktop) i do `populateCardMeta` (mobilnie). Kolor terminu (`deadline-overdue/urgent/normal`)
  zostaje bez zmian.
- [x] **Step 6: Hurt.** `showBulkStarsPicker(selectedIds)`: z `selectedIds` (klucze pozycji) przez `this.state.products`
  zbierz `new Set(order_id)` (pomiń `null`). Pusty zbiór daje „Zaznaczone pozycje nie mają zamówienia”, a ponad
  `LIMIT_HURTU` daje komunikat bez wysyłki. `const n = await Priorytety.wybierzGwiazdki(przyciskStars, 0)`,
  `null` → koniec. `await Priorytety.ustawGwiazdki(ids, n)`. Toast: „Gwiazdki {★…}: zmieniono {zmienione.length},
  bez zmian {bez_zmian.length}” i, jeśli `nieznane.length`, „pominięto {n} (brak zamówienia)”. Selekcja zostaje.
  Tekst pod przyciskiem w dymku: „Gwiazdki dotyczą całych zamówień”.
- [x] **Step 7: Usunięcia** wg tabeli „Stan obecny”, plik `products-dragdrop.js` (`git rm`), `<script>` `dashboard.html:361`.
  Po usunięciach: `grep -n "dragDrop\|is_priority\|priority_rank\|getPriorityClass\|set-priority" modules/production/static/js/modules/products-module.js`
  → pusto, z jednym możliwym wyjątkiem: `sort_by: 'priority_rank'` w `loadProductsData` (`:918`, `:942`) **zostaje**.
  To kolejność pozycji wewnątrz karty (ranga×100+sekwencja, spec 9.5 „sort po `priority_rank` bez zmian”). W teście
  `test_brak_starej_gwiazdki_i_progow_rangi` wyklucz go jawnie i uzasadnij w komentarzu.
- [x] **Step 8: CSS.** Siatka `:353`, `:419` i media `1200px`: pierwsza kolumna `36px` (ranga), trzecia `76px` (gwiazdki).
  Media `900px`: ukryj `nth-child(1)` zamiast `nth-child(3)`, siatka bez rangi. Uwaga: dziś ta siatka ma 7 ścieżek
  (`20px 24px 20px 2fr 120px 120px 100px`, `:1144`, `:1148`) na 8 widocznych dzieci (11 minus 3 ukryte), więc ostatnia
  komórka zawija się do nowego wiersza. Po zmianie widoczne są: checkbox, gwiazdki, rozwiń, klient, pozycje, status,
  termin, akcje — siatka dostaje 8 ścieżek (np. `24px 76px 20px 2fr 55px 120px 120px 100px`). Mobilnie (`:1243-1264`): selektory
  `.il-order-ranga` (ukryta) i `.il-order-header .il-priorytet-btn`. Nowe: `.il-lista-naglowek` (flex, tytuł po lewej,
  przycisk drabiny po prawej), `.il-order-ranga`, `.il-priorytet-btn` (focus-visible!), `.il-prio-tag` z wariantami
  (trasa niebieska, po terminie czerwona `--il-status-danger`, blisko terminu `--il-status-warn`, rozpoczęte szara,
  odłożone fioletowa/obramowana), `.il-priorytety-ostrzezenie`. Usuń style `.il-drag-handle`, `.product-drag-handle`,
  `.il-star-btn`, `.product-star`, `.partial` (sprawdź grepem, że `product-star`/`product-drag-handle` nie ma w szablonach).
  `il-product-row` `padding-left` popraw tak, żeby nazwa pozycji dalej stała pod nazwą klienta (sprawdź na podglądzie).
- [x] **Step 9: Wersje** w `dashboard.html`: `products-module.js`, `products-tab.css`, `priorytety.js`, `priorytety.css`.
- [x] **Step 10: Testy przechodzą:** plik oraz `tests/test_produkty_js_*.py tests/test_produkty_formularz_statusu.py
  tests/test_produkty_lista_krawedzie.py tests/test_produkty_masowa_zmiana_statusu.py tests/test_archive_tab.py
  tests/test_weryfikacja_front_produkcji.py tests/test_logistyka_przeglad_koncowy_ui.py tests/test_dashboard_logistyka_pasek.py
  tests/test_logistyka_sprzatanie.py tests/test_katalog_stanowisk_krawedzie.py tests/test_druk_panel_ui.py
  tests/test_logistyka_zakladka.py tests/test_logistyka_runda_poprawek_4_10.py` (wszystkie czytają `products-module.js`,
  szablon zakładki albo `dashboard.html`).
- [x] **Step 11: Commit** `feat(priorytety): Lista produkcyjna po randze z gwiazdkami, plakietkami i hurtem; bez przeciagania`

---

### Task 5: Usunięcie `POST /production/api/set-priority`

**Files:**
- Modify: `modules/production/routers/api/products_api.py` (`set_product_priority` `:3679-3797`, import `:19`)
- Modify: `tests/test_priorytety_kolejnosc_zapisow.py` (test K2 `test_martwe_koncowki_priorytetow_usuniete`)
- Modify: `tests/test_priorytety_lista_produkcyjna_ui.py`

**Stan obecny (ugruntowanie):**
- `@api_bp.route('/set-priority', methods=['POST'])` + `@admin_required` → `set_product_priority()`
  (`products_api.py:3679-3797`, w trybie `order` po `internal_order_number` ustawia `is_priority` wszystkim pozycjom
  zamówienia, w trybie `product` jednej pozycji, commit w routerze). Po Task 4 nie woła jej nic
  (`grep -rn "set-priority" modules --include=*.js --include=*.html` → pusto).
- `admin_required` w `products_api.py` jest użyte tylko tu (`grep -n "admin_required" products_api.py` → `:19` import,
  `:3680`). Sprawdź po K2, bo K2 usuwał inne końcówki.
- K2 dopisał `test_martwe_koncowki_priorytetow_usuniete` z asercją, że `/production/api/set-priority` **jest**
  (plan K2, Task 6, Step 1). K4a odwraca tę asercję.
- `modules/production/routers/__init__.py` `URL_PATTERNS` (`:172` i okolice) nie zawiera `set-priority` (sprawdzone).

**Interfaces:** Removes `POST /production/api/set-priority`. Nic nie produkuje.

- [x] **Step 1: Testy, które padną.**
  - `test_set_priority_usuniete` (w `test_priorytety_lista_produkcyjna_ui.py`, fikstura `krawedzie_fixtures.app`):
    w `app.url_map` nie ma reguły `/production/api/set-priority`. `POST` na nią daje 404 (albo 405, jeśli inna reguła
    łapie ścieżkę; zapisz, co wyszło). `products_api.py` nie zawiera `set_product_priority`.
  - `tests/test_priorytety_kolejnosc_zapisow.py::test_martwe_koncowki_priorytetow_usuniete`: `/production/api/set-priority`
    dopisane do listy reguł nieobecnych, asercja „jest” usunięta, docstring „(set-priority usunięte w K4a)”.
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Usuń** funkcję z dekoratorami i komentarzem sekcji, jeśli został sam. `admin_required` usuń z importu
  `:19` tylko wtedy, gdy grep nie pokazuje innego użycia w pliku.
- [x] **Step 4: Grep kontrolny** (wynik do raportu):
  `grep -rn --include=*.py --include=*.js --include=*.html -E "set-priority|set_product_priority|products-dragdrop|ProductsDragDrop|showEditPriorityModal|handleStarClick|getPriorityClass|updatePriorityColor|il-drag-handle|il-product-star|bulk-priority-form" modules app.py tests`
  → trafienia wyłącznie w testach nieobecności (`tests/test_priorytety_*`).
- [x] **Step 5: Testy przechodzą:** `tests/test_priorytety_kolejnosc_zapisow.py tests/test_priorytety_lista_produkcyjna_ui.py
  tests/test_produkty_masowa_zmiana_statusu.py tests/test_priorytety_panel_api.py`.
- [x] **Step 6: Commit** `refactor(priorytety): usuniecie koncowki set-priority starej gwiazdki`

---

### Task 6: Logistyka — kolumna „★” w liście i gwiazdki przy przystankach

**Files:**
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (`:271-288` nagłówek tabeli, `:292`
  `<td colspan="10">` wiersza „Ładowanie zamówień…”, `:236` wersja
  `logistics-routes.js`, `:799` wersja `logistics.js`, `:17`/`:19` wersje CSS)
- Modify: `modules/production/logistics/static/js/logistics.js` (`:16-30` komentarz końcówek, `:424-447`
  `KOLUMNY_SORTOWANIA`, `:662` i `:962` `colspan="10"`, `:966-1061` `wierszHtml`, `:1101-1102` `KLASY_FOKUSU`, obsługa
  kliknięć `:2671` i okolice)
- Modify: `modules/production/logistics/static/js/logistics-routes.js` (`:2170-2217` `przystanekHtml`)
- Modify: `modules/production/logistics/static/css/logistics.css` (`:602-603` sąsiednie kolumny), `logistics-trasy.css`
- Modify: `tests/test_priorytety_logistyka_ui.py`

**Stan obecny (ugruntowanie):**
- Nagłówek tabeli: `tab_content.html:271-288`, 10 kolumn: `lg-k-zaznacz`, `lg-k-numer`, `lg-k-klient`, `lg-k-adres`,
  `lg-k-metoda`, `lg-k-sposob`, `lg-k-etap`, `lg-k-termin`, `lg-k-m3`, `lg-k-stan`. Sortowalne mają
  `data-lg-sort-kolumna` i `button.lg-sort[data-lg-sort]`.
- `logistics.js`: `wierszHtml(w)` `:966-1061` (komórki w tej samej kolejności), `komorkaStanu` z `colspan="10"` (`:662`),
  rozwinięcie pozycji `colspan="10"` (`:962`). Trzeci `colspan="10"` stoi w szablonie: wiersz ładowania
  `tab_content.html:292` (widoczny do pierwszej odpowiedzi `/orders`). Wiersz po id: `znajdz(id)`, przerysowanie jednego
  wiersza: `odswiezWiersz(id)` (`:1156`). `KOLUMNY_SORTOWANIA` `:424-447`, `posortuj` `:450-463` (puste na końcu
  w obu kierunkach). `KLASY_FOKUSU` `:1101-1102`. Klik w tabeli `:2671` i dalej (`data-lg-akcja`). Komunikaty:
  `pokazKomunikat(typ, tresc, opcje)` `:1237`. Kolumny ukrywa CSS po klasie, a nie po `nth-child` (`logistics.css:1322-1357`).
  Jedyny test reguł CSS tabeli dotyczy `lg-k-stan` (`tests/test_logistyka_dymek_ui.py:77-83`).
- `logistics-routes.js`: `przystanekHtml(z, indeks, ile, numer, edyt, status)` `:2170-2217`. Górna linia
  `lg-przystanek-gora` (`:2191-2196`): numer, klient, etap albo „Anulowane”. Dane `z` = `lista.serializuj` (Task 1 dodał
  `gwiazdki`).
- Szablon zakładki Logistyki renderuje się w `tests/logistyka_fixtures.py` bez blueprintu priorytetów
  (`test_zakladka_renderuje_sie_z_trasami_i_flota`), dlatego żadnego `url_for('priorytety_panel…')` w `tab_content.html`.

**Interfaces:**
- Consumes: `w.gwiazdki` (Task 1), `window.Priorytety.gwiazdkiHtml`, `.wybierzGwiazdki`, `.ustawGwiazdki` (Task 2).
- Produces: kolumna `th.lg-k-gwiazdki[data-lg-sort-kolumna="gwiazdki"]` z `button.lg-sort[data-lg-sort="gwiazdki"][data-nazwa="Gwiazdki"]`
  i treścią „★”, komórka `td.lg-k-gwiazdki` z `button.lg-gwiazdki[data-lg-akcja="gwiazdki"]` (edytowalna) albo `span`
  (zamknięte, anulowane, wydane), znaczek przystanku `span.lg-przystanek-gwiazdki`.

- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_logistyka_ui.py`):
  - `test_tabela_logistyki_kolumna_gwiazdek_i_colspan`: nagłówek ma 11 `<th scope="col"`, `lg-k-gwiazdki` stoi
    między `lg-k-numer` a `lg-k-klient`, a `wierszHtml` ma `td.lg-k-gwiazdki` w tym samym miejscu. W `logistics.js`
    nie ma `colspan="10"`, są dwa `colspan="11"`. Szablon `tab_content.html` też nie ma `colspan="10"` (wiersz ładowania
    ma `colspan="11"`; `colspan="5"` floty zostaje). `KOLUMNY_SORTOWANIA` ma `gwiazdki`, a `KLASY_FOKUSU` ma `'lg-gwiazdki'`.
  - `test_logistyka_gwiazdki_przez_wspolny_komponent`: `logistics.js` ma `data-lg-akcja="gwiazdki"`, obsługę akcji
    `'gwiazdki'` wołającą `Priorytety.wybierzGwiazdki` i `Priorytety.ustawGwiazdki`, sprawdzenie
    `window.Priorytety` (bez niego komórka pokazuje tylko liczbę), brak edycji przy `w.zamkniete`, `anulowane`,
    `w.wydane`, błąd przez `pokazKomunikat('blad'`. Nie ma `fetch` do `/priorytety/`.
  - `test_przystanek_pokazuje_gwiazdki`: `przystanekHtml` zawiera `lg-przystanek-gwiazdki` w gałęzi `z.gwiazdki > 0`
    z `aria-label` „Gwiazdki zamówienia: n” i bez przycisku (tylko odczyt).
  - `test_wersje_skryptow_logistyki_podbite`: `logistics.js?v=` > `'20261004a'`, `logistics-routes.js?v=` > `'20261004b1'`.
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Nagłówek i wiersz.** `<th scope="col" class="lg-k-gwiazdki" data-lg-sort-kolumna="gwiazdki" aria-sort="none"><button
  type="button" class="lg-sort" data-lg-sort="gwiazdki" data-nazwa="Gwiazdki"><span aria-hidden="true">★</span><span
  class="visually-hidden">Gwiazdki</span><span class="lg-sort-znak" aria-hidden="true"></span></button></th>`.
  Komórka:
  ```js
  function komorkaGwiazdek(w, anulowane) {
      const n = Number(w.gwiazdki) || 0;
      const P = window.Priorytety;
      const znak = P ? P.gwiazdkiHtml(n, { male: true }) : (n ? esc(n) + '★' : '–');
      if (!P || w.zamkniete || anulowane || w.wydane) return '<span class="lg-gwiazdki is-tylko-odczyt">' + znak + '</span>';
      // W trakcie zapisu przycisk zostaje (aria-disabled), żeby fokus klawiatury nie zginął przy przerysowaniu —
      // wzór „bez disabled na czas innej zmiany” z logistics-routes.js:2209-2210. Taki klik ignoruje obsługa akcji (Step 4).
      const czeka = stan.wysylane.has(w.id);
      return '<button type="button" class="lg-gwiazdki" data-lg-akcja="gwiazdki" aria-haspopup="dialog"' +
             (czeka ? ' aria-disabled="true"' : '') +
             ' aria-label="' + esc('Gwiazdki zamówienia ' + w.numer + ': ' + n + '. Zmień') + '">' + znak + '</button>';
  }
  ```
  `colspan="11"` w obu miejscach JS i w wierszu ładowania szablonu. Sortowanie `gwiazdki: { wartosc: (w) => Number(w.gwiazdki) || 0, porownaj: porownajLiczby }`.
- [x] **Step 4: Akcja.** W obsłudze `data-lg-akcja` (`switch (akcja)` `:2700`): `'gwiazdki'` → `w = znajdz(id)`;
  `przycisk.getAttribute('aria-disabled') === 'true'` albo `stan.wysylane.has(w.id)` → koniec.
  `const n = await Priorytety.wybierzGwiazdki(przycisk, w.gwiazdki)`. `null` lub ta sama wartość → koniec. Inaczej
  `stan.wysylane.add(w.id)`, `odswiezWiersz(w.id)`, `await Priorytety.ustawGwiazdki([w.id], n)`,
  potem `const biezacy = znajdz(w.id); if (biezacy) biezacy.gwiazdki = n;` (lista mogła się w tym czasie odświeżyć
  i podmienić obiekt), `pokazKomunikat('ok', 'Gwiazdki zamówienia ' + w.numer + ': ' + n + '.', {klucz: 'wynik'})`.
  Błąd → `pokazKomunikat('blad', e.message)`. `finally` → `stan.wysylane.delete(w.id)` i `odswiezWiersz(w.id)`.
  `stan.wysylane` blokuje też select sposobu dostawy w tym wierszu (`:987`, „Zapisywanie…”), więc obie zmiany jednego
  wiersza nie idą naraz. Komentarz nagłówkowy `logistics.js:16-30`: dopisz „gwiazdki zamówienia zapisuje
  window.Priorytety.ustawGwiazdki (priorytety produkcji, K4a)” — **bez ścieżki końcówki**, bo
  `test_gwiazdki_jedna_droga_zapisu` szuka w tym pliku tekstu `/priorytety/` i `/zamowienia/gwiazdki`.
- [x] **Step 5: Przystanek.** W `lg-przystanek-gora` za numerem:
  `(!anul && z.gwiazdki > 0 ? '<span class="lg-przystanek-gwiazdki" role="img" aria-label="' + esc('Gwiazdki zamówienia: ' + z.gwiazdki) + '" title="Gwiazdki zamówienia">' + '★'.repeat(Math.min(5, z.gwiazdki)) + '</span>' : '')`.
  Bez zależności od `window.Priorytety` (plik tras ładuje się osobno i ma działać sam).
- [x] **Step 6: CSS** (`logistics.css`: `.logistics-tab .lg-k-gwiazdki { width: 1%; white-space: nowrap; text-align: center; }`,
  `.lg-gwiazdki` jako przycisk bez tła z `focus-visible`; `logistics-trasy.css`: `.lg-przystanek-gwiazdki` w kolorze
  ostrzeżenia, `font-size` jak numer). Sprawdź na podglądzie szerokości 1440, 1100, 860, 760 px, żeby kolumna
  „Stan” nie była ucinana (próg z komentarza `logistics.css:1318-1321`).
- [x] **Step 7: Wersje** w `tab_content.html`.
- [x] **Step 8: Testy przechodzą:** plik oraz `tests/test_logistyka_*_ui.py tests/test_dostawa_*_ui.py tests/test_logistyka_trasy*.py
  tests/test_logistyka_poprawki_panelu.py tests/test_weryfikacja_panel.py tests/test_logistyka_zakladka.py
  tests/test_logistyka_daleko_od_drogi.py` (`KLASY_FOKUSU` w `test_weryfikacja_panel.py:213`, teksty i „Base.” w
  `test_logistyka_zakladka.py`, wersja `logistics-routes.js` w `test_logistyka_daleko_od_drogi.py:292`).
- [x] **Step 9: Commit** `feat(priorytety): gwiazdki zamowien w Logistyce - kolumna i przystanki tras`

---

### Task 7: Oględziny na podglądzie, pełny pakiet, Python 3.9, raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4a-raport.md`

- [x] **Step 1: Oględziny w przeglądarce** (podgląd wskazany przez centralę, baza podglądu; **nigdy** produkcja).
  Przygotowanie danych na bazie podglądu: gwiazdki ustawione z UI na 3–4 zamówieniach, jedna trasa robocza w Logistyce
  z 2 przystankami, jedno odłożenie. Odłożenie zrób przez `POST /api/mobile/orders/<id>/postpone` urządzeniem podglądu
  (K3) albo wpisem SQL do `prod_station_desk` tylko na podglądzie. Sprawdź i zrób zrzuty (1440 px i 390 px):
  1. Lista produkcyjna: karty po randze (`#1`, `#2`…), plakietki trasy, tagu i „Odłożone na …”, termin z kolorem.
  2. Modal priorytetu: zmiana gwiazdek 0→3→0, historia rośnie, „Gdzie leży” zgadza się z `GET /kolejka?stanowisko=`.
  3. Modal drabiny: przesunięcie „Rozpoczęte” ↑ i trasy pod „bez gwiazdek”, kolejność kart po zamknięciu modalu się
     zmienia. Drugi klient (inna karta przeglądarki) przesuwa szczebel, a pierwszy dostaje komunikat
     `drabina_zmieniona` i odświeżoną drabinę. Ostrzeżenie o datach przy dwóch trasach w odwrotnej kolejności.
  4. Hurt „Ustaw gwiazdki” na 2 zamówieniach (pozycje z jednego zamówienia liczone raz).
  5. Logistyka: kolumna ★, zmiana z listy, sortowanie, gwiazdki przy przystankach w edytorze trasy.
  6. Konsola DevTools: **zero błędów JS** przy otwarciu zakładki, obu modali, Logistyki i edytora trasy. Wynik do
     raportu.
  7. Klawiatura: Tab dochodzi do przycisku gwiazdek na karcie, Enter otwiera modal, Esc zamyka i fokus wraca. Strzałki
     drabiny działają z klawiatury.
  8. Czas `GET /production/api/priorytety/kolejka` i modalu (DevTools → Network) na bazie podglądu. Ponad 1 s →
     meldunek (ryzyko z planu K2), bez optymalizacji.
- [x] **Step 2: Pełny pakiet:** `docker compose exec app pytest tests/ -q -p no:cacheprovider` → 0 failed. `passed` =
  punkt wyjścia + nowe testy (liczby w raporcie). Osobno, jako regresja kolejności zapisów:
  `docker compose exec app pytest tests/test_priorytety_panel_api.py tests/test_priorytety_kolejnosc_zapisow.py -q -p no:cacheprovider`.
- [x] **Step 3: Składnia 3.9** dla `.py` zmienionych w K4a (`git diff --name-only <hash startu>..HEAD -- '*.py'`):
  `docker compose exec app python -c "import ast,sys; [ast.parse(open(p,encoding='utf-8').read(), p, feature_version=(3,9)) for p in sys.argv[1:]]; print('OK')" <pliki>`.
- [x] **Step 4: Grep końcowy** (wyniki do raportu): grep z Task 5, Step 4. `grep -rn "Lista produktów" modules/production/templates
  modules/production/static/js` → pusto. `grep -rn "priorytety_panel" modules/production/logistics/templates` → pusto.
- [x] **Step 5: Raport** z sekcjami karty: Zrobione (po Taskach, z hashami), Testy (polecenia i wyniki: Step 0 Task 1,
  pliki z Tasków, pełny pakiet, składnia), Odstępstwa od planu (nazwy pól K2/K3 inne niż w planie, drag&drop pominięty
  albo zrobiony), Rozstrzygnięcia podjęte w trakcie (numerowane, z kosztem pomyłki), Pytania do Konrada, Stan gałęzi
  (hash, czy wypchnięte), Co następny krok musi wiedzieć. Ta sekcja ma co najmniej:
  - **K4b:** `window.Priorytety` (sygnatury z Task 2) do ponownego użycia (`gwiazdkiHtml`, `etykietaOdlozenia`,
    miejscownik stanowisk). Zdarzenie `priorytety:zmiana`. `priorytety.js/.css` ładuje `dashboard.html`. Przy
    scaleniu konflikt możliwy tylko w wersjach skryptów.
  - **K5:** CLAUDE.md, akapit pisarzy pozycji bez blokady zamówienia: znika „hurtowa i ręczna zmiana priorytetu”
    (`set-priority` usunięte w K4a, `bulk-action update_priority` w K2). Doprecyzowania 1–12 tego planu do specu
    (zwłaszcza 9.1 bez `templates/priorytety/` i 7.1 „kolejność kart z `/kolejka`”). Spec 7.3: gwiazdki już nie tylko
    dla admina, co warto odnotować w notatce wdrożeniowej K7.
  - **K7:** po wdrożeniu użytkownicy z otwartą starą kartą przeglądarki dostaną 404 na kliknięcie starej gwiazdki,
    aż odświeżą stronę (wersje `?v=` podbite). Notatka dla biura: zmiana nazwy zakładki i nowy przycisk „Drabina
    priorytetów”.
  - **K8:** `priority_range` w `GET /products/filters-data` (`products_api.py:2479-2490`) nikt nie czyta
    (`products-module.js:982` TODO). Do usunięcia razem z `priority_service`. `is_priority`/`priority_manual_override`
    w serializerze listy zostają do P4.
  - Zrzuty: ścieżki (poza repo) i opis każdego.
- [x] **Step 6: Commit raportu i push** wg karty: `git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4a-raport.md`,
  `docs(priorytety): raport kroku K4a lista produkcyjna`.

---

## Kryteria zakończenia (DoD)

1. `tests/test_priorytety_lista_produkcyjna_ui.py` i `tests/test_priorytety_logistyka_ui.py` zielone. Każdy test
   z Review Focus istnieje pod podaną nazwą i przechodzi.
2. Pełny pakiet: 0 failed. Liczby w raporcie, różnica wobec Task 1 Step 0 wyjaśniona (nowe testy, zmieniony test K2).
3. Grep z Task 5, Step 4: brak trafień w `modules/` i `app.py`. Plik `products-dragdrop.js` nie istnieje.
   `app.url_map` nie ma `/production/api/set-priority`.
4. `grep -rn "Lista produktów" modules/production/templates modules/production/static/js` → pusto. Zakładka nazywa się
   „Lista produkcyjna”.
5. Zapis gwiazdek występuje w kodzie frontu dokładnie raz (`Priorytety.ustawGwiazdki`), a zapis drabiny raz
   (`przesunSzczebel`). Grep `'/zamowienia/gwiazdki'` i `'/drabina/kolejnosc'` w `modules/production/**/*.js` →
   po jednym trafieniu w `priorytety.js`.
6. Oględziny z Task 7, Step 1, punkty 1–7 wykonane, konsola bez błędów JS. Zrzuty „przed” (Task 1) i „po” (Lista,
   modal priorytetu, modal drabiny, Logistyka z kolumną ★, przystanki) wymienione w raporcie.
7. Składnia 3.9 OK dla zmienionych `.py`. Żadnej migracji w kroku.
8. Raport kroku zacommitowany z sekcją „Co następny krok musi wiedzieć” (K4b, K5, K7, K8). `main` nietknięty.
   Commity tylko na `claude/priorytety-produkcji`: 7, po jednym na Task.

## Poza zakresem

- Zakładka Stanowiska, dashboard (`high_priority_count`), Konfiguracja (Terminy, Stół stanowisk), monitory hali — K4b.
- Końcówki API priorytetów i ich logika (K2, K3), algorytm rangi (K1). Jedyna zmiana w testach K2 to odwrócenie
  asercji `set-priority` (Task 5).
- Filtr `priority_range` w `GET /products/filters-data` (`products_api.py:2479-2507`) zgodnie ze spec 9.5 miał przejść
  na gwiazdki, ale nikt go nie czyta (`products-module.js:982`, TODO). Zostawiamy go i zgłaszamy do K8.
- Reszta martwego szablonu `bulk-actions-modal-template` (`products-tab-content.html:243-347`, bez użytkownika w JS)
  i martwa ścieżka `_createOldProductRow`/`populateProductRow`/`attachRowEventListeners` poza fragmentami o priorytecie.
  Zgłaszamy w raporcie, nie usuwamy.
- Arkusz „Lista produktów” w eksportach Excel/PDF (`products_api.py:2101`, `:2173`, `:2347`): to nazwa arkusza,
  nie zakładki.
- Telefon kierowcy (`dostawa_widok.serializuj`), gwiazdki w puli zamówień edytora tras, na mapie i w dymku mapy.
- Wyścigi MySQL (K5). CLAUDE.md (K5).

## Ryzyka i co robić przy blokadzie

| Ryzyko | Skutek | Co robić |
|---|---|---|
| Kształt JSON K2/K3 inny niż w tabeli „Consumes” (nazwy pól, brak `stanowiska` w modalu, brak `/odlozenia`) | modal albo plakietki nie działają | Task 1 Step 0: drobne różnice nazw → adapter w jednym miejscu `priorytety.js`, „Odstępstwa”. Brak końcówki albo pola bez zamiennika → **STOP** przed Taskiem, meldunek do centrali (karta naprawcza K2/K3). Bez własnych końcówek w K4a |
| K4b równolegle zmienia `dashboard.html` | konflikt przy commicie | `git pull` przed każdym commitem; rozwiązać ręcznie, obie zmiany zostają (karta 8.4) |
| Reguły `nth-child` w `products-tab.css` po zmianie kolumn ukrywają nie to, co trzeba | na tablecie albo wąskim ekranie znika przycisk gwiazdek | liczba dzieci siatki bez zmian (Doprecyzowania p. 9); zrzuty na 1440 / 1100 / 850 / 390 px w Task 7 |
| `GET /kolejka` wolne (policz na żywo, ~250 zamówień) | lista ładuje się dłużej | równolegle z resztą (`Promise.all`), lista renderuje się po terminie, jeśli priorytety padną; pomiar w Task 7 Step 1 p. 8; > 1 s → meldunek, bez optymalizacji |
| XSS przez nazwę trasy, klienta albo notatkę odłożenia (toast i plakietki składane przez `innerHTML`) | wykonanie skryptu w panelu biura | `esc` wszędzie, testy Review Focus 1; przy wątpliwości `textContent` |
| `priorytety.js` nie wczyta się (błąd składni, 404 statyki) | brak gwiazdek i modali | lista i Logistyka mają ścieżki bez `window.Priorytety` (testy Task 4, 6); konsola w Task 7 |
| Użytkownicy bez roli admina mogą teraz zmieniać gwiazdki (spec 7.3) | zmiana praktyki biura | zgodnie ze spec; odnotować w raporcie dla K7 (komunikat do biura) |
| Stara karta przeglądarki po wdrożeniu woła usunięte `set-priority` | 404 i toast błędu do odświeżenia | akceptowalne; wersje `?v=` podbite; notatka K7 |
| Brak node'a w obrazie — logika JS nietestowana wykonaniem | błąd wychodzi dopiero w przeglądarce | testy strukturalne + oględziny Task 7 z konsolą; nie dodawać node'a ani nowych zależności |
| Padający test spoza zakresu, spór spec ↔ kod, brak czegoś, co plan zakłada | — | **STOP**: opis w raporcie, meldunek do centrali, bez obejść i bez wyłączania testów (podręcznik, sekcja 6) |

## Pytania do Konrada

Brak pytań blokujących start. Do potwierdzenia przy bramce (plan przyjmuje wartości domyślne):
1. Gwiazdki i drabinę może zmieniać każdy użytkownik z dostępem do modułu produkcji (spec 7.3), nie tylko admin (jak
   dotąd `set-priority`). Rekomendacja: tak, zgodnie ze spec. Biuro ustawia priorytety.
2. Drag&drop w modalu drabiny jest opcjonalny, obowiązkowe są strzałki ↑↓. Rekomendacja: wystarczą strzałki,
   szczebli ruchomych jest kilka (3 tagi + trasy).
3. Plakietka odłożeń na karcie zbiera odłożenia jednego stanowiska („Odłożone na Sklejaniu: 2”), a szczegóły są
   w modalu. Rekomendacja: tak, karta zostaje czytelna.

---

## K4-poprawka-1 (karta naprawcza po bramkach K4a/K4b; rozstrzygnięcie 18 dziennika centrali)

Zakres z karty (decyzje Konrada 5.10 i centrali), nic poza tym. Usterka `config_service.update_multiple_configs` —
nie ruszamy (K5). Worktree `.claude/worktrees/priorytety-k4p`, gałąź `claude/priorytety-k4p`, push wyłącznie
`HEAD:claude/priorytety-produkcji` po każdym commicie (rebase przed pushem). Jeden commit na punkt zakresu.

### Task P1: Logistyka — kolumna „★” chowana w wąskim widoku

**Files:** `modules/production/logistics/static/css/logistics.css`, `modules/production/templates/panel/dashboard.html`
albo szablon ładujący `logistics.css` (podbicie `?v=`), test `tests/test_priorytety_logistyka_ui.py`.

- [x] Step 1: Pomiar na podglądzie 5006 (dane `priorytety_podglad`): szerokość ramki tabeli (`.lg-tabela-ramka`,
  kontener `lg-tabela`) i szerokość treści tabeli z kolumną ★ i bez niej przy 1100, 1280, 1440, 1600, 1920 px
  (lista obok mapy i mapa nad listą). Próg = szerokość kontenera, poniżej której tabela z ★ przewija się w bok.
- [x] Step 2: Test (RED): w `logistics.css` reguła `@container lg-tabela (max-width: <próg>px)` chowa
  `th.lg-k-gwiazdki` i `td.lg-k-gwiazdki` (`display: none`); poza tą regułą kolumna nie jest chowana (szeroki widok bez
  zmian); wiersze szczegółów i stanu dalej `colspan="11"` (kolumna ukryta jak `lg-k-adres`); przystanki trasy dalej
  z gwiazdkami; podbita wersja `logistics.css`.
- [x] Step 3: Implementacja (GREEN) — sam CSS, bez JS (próg wspólny z kontenerem tabeli; pastylka zmienia szerokość
  listy i reguła reaguje sama). Komentarz po polsku z wynikiem pomiaru.
- [x] Step 4: Oględziny 1100 / 1440 / 1920 px — zrzuty, konsola czysta. Commit `fix(logistyka): ...`, push.

### Task P2: Hurt „Ustaw gwiazdki” — okno potwierdzenia

**Files:** `modules/production/priorytety/static/js/priorytety.js` (nowe `potwierdz(opcje)` — natywny `<dialog>`),
`priorytety.css`, `modules/production/static/js/modules/products-module.js` (`showBulkStarsPicker`), `dashboard.html`
(wersje), test `tests/test_priorytety_lista_produkcyjna_ui.py`. Logistyka nie ma hurtu gwiazdek (sprawdzone na kodzie:
jedyny wybór w Logistyce to pojedyncza komórka ★) — bez zmian.

- [x] Step 1: Test (RED): `showBulkStarsPicker` po wyborze gwiazdek, a przed `P.ustawGwiazdki(` woła
  `P.potwierdz(` przy `n === 0` albo `ids.size > PROG_POTWIERDZENIA_HURTU` (10); treść z liczbą zamówień i docelową
  liczbą gwiazdek („Bez gwiazdek” przy 0); odmowa → brak zapisu. `potwierdz` w `priorytety.js`: `<dialog>`
  z przyciskami „Anuluj” i zatwierdzającym, fokus startowy na „Anuluj” (Enter z wybieraka nie zatwierdza),
  przycisk zatwierdzający bez `autofocus`, Esc (`cancel`) = odmowa i oddanie fokusu, treść przez `textContent`/`esc`,
  eksport w `window.Priorytety`; `handleKeydown` listy dalej pomija `dialog[open]`.
- [x] Step 2: Implementacja (GREEN), wersje `priorytety.js`, `priorytety.css`, `products-module.js` podbite.
- [x] Step 3: Oględziny na 5006: 0 gwiazdek przy 1 zamówieniu → okno; 3 gwiazdki przy 2 zamówieniach → bez okna;
  Enter od razu po wyborze → okno zostaje, nic nie zapisane (bez zapisu trwałego na bazie podglądu — odmowa).
  Commit `feat(produkcja): ...`, push.

### Task P3: Serwer odmawia stołu przy progu wersji 0

**Files:** `modules/production/priorytety/services/ustawienia.py` (`sprawdz_prog_wersji(zmiany)`),
`modules/production/priorytety/routers/panel_api.py` (`ustawienia_put`), `modules/production/static/js/modules/config-module.js`
(`wlaczStoly`), testy `tests/test_priorytety_panel_api.py`, `tests/test_priorytety_czytelnicy.py`.

Reguła: stan WYNIKOWY (zmiany z żądania nałożone na stan bazy; Lakiernia pomijana — jest zawsze `stary`) ma
stanowisko w `stol` przy `priorytety_min_app_version_code` = 0 **i** żądanie tę kombinację wprowadza (ustawia `stol`
stanowisku, które w bazie nie jest w `stol`, albo obniża próg do 0 z wartości > 0) → 400 `prog_wersji_wymagany`,
`pole` = `min_app_version_code`, komunikat po polsku, nic nie zapisane. Żądanie, które kombinacji nie wprowadza (np.
wycofanie stanowiska na `stary` albo zmiana K przy zastanym w bazie `stol` + 0) przechodzi — wycofanie nigdy nie jest
blokowane.

- [x] Step 1: Testy (RED) w `test_priorytety_panel_api.py`: (a) `stol` w jednym żądaniu z progiem 0 → 400;
  (b) `stol` przy zapisanym progu 0 (brak wiersza = 0) → 400; (c) obniżenie progu do 0 przy stanowisku już w `stol` →
  400; (d) `stol` z progiem > 0 w jednym żądaniu → 200; (e) `stol` przy zapisanym progu > 0 → 200; (f) zastany
  `stol` + 0: wycofanie stanowiska na `stary` i zmiana K → 200; (g) Lakiernia w `stol` w bazie + obniżenie progu do
  0 → 200 (Lakiernia nie ma stołu); (h) odmowa: brak zmian w `prod_config` i w logu, `pole` = `min_app_version_code`.
  Dwa istniejące testy, które włączają `stol` bez progu, dostają próg > 0. Test strukturalny `wlaczStoly`: przy
  progu 0 bez starego ostrzeżenia „UWAGA” w pytaniu, komunikat z serwera (`result.message`) w toaście.
- [x] Step 2: Implementacja (GREEN): `ustawienia.sprawdz_prog_wersji(zmiany)` (odczyt stanu bazy tymi samymi
  funkcjami co serwisy) wołane w routerze po `waliduj`, przed zapisem; `wlaczStoly` przy progu 0 nie pyta
  (serwer i tak odmówi, toast z komunikatem serwera, pole progu podświetlone).
- [x] Step 3: Commit `fix(priorytety): ...`, push.

### Task P4: Pełny pakiet, raport

- [x] Step 1: `docker ps` (brak innego `priorytety-app-run-*`), pełny pakiet 0 failed (punkt wyjścia 6765 passed,
  3 skipped); kontener podglądu usunięty, pusty `config/core.json` z worktree usunięty przed pakietem.
- [x] Step 2: Raport `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4-poprawka-1-raport.md`, commit, push.
