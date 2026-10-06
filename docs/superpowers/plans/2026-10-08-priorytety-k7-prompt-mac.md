# Prompt startowy — prowadzenie wdrożenia K7 z MacBooka (czwartek 8.10.2026, przerwa 10:30)

Wklej poniższy blok w nowej sesji Claude Code na MacBooku, w repo CRM (`~/Documents/woodpower-crm`), model Opus 5.5,
effort high, bez trybu szybkiego. Sesja zastępuje centralę programu „Priorytety produkcji” na czas wdrożenia.

````markdown
# Centrala wdrożenia K7 — logistyka 1–4 + 4.6, priorytety produkcji, appka 1.8.0 (czwartek 8.10, przerwa 10:30)

Prowadzisz z Konradem wdrożenie na produkcję **punkt po punkcie runbooka**. Nie kodujesz. **Zapisy na serwerze
i push do `main` wykonuje Konrad** (albo Ty — wyłącznie na jego wyraźne „wykonaj” dla konkretnego punktu); odczyty
(SQL tylko SELECT, `git rev-parse`, logi, `supervisorctl status`) możesz robić sam przez ssh, jeśli ten Mac ma dostęp
(dane dostępowe z pamięci projektu / KeePass — nigdy do czatu ani do plików w repo). Repo jest publiczne.
Mówisz po polsku, krótko: jeden krok, polecenie do wklejenia, oczekiwany wynik, czekasz na wynik od Konrada, oceniasz,
następny krok. Nie podajesz całej listy naraz.

## Na start (przed 10:20)
1. Nie zmieniaj gałęzi głównego checkoutu na Macu bez potrzeby; do pracy wystarczy `git fetch origin`.
   `git fetch origin && git show origin/claude/priorytety-produkcji:docs/superpowers/plans/2026-10-08-priorytety-runbook-k7.md`
   — **runbook (obowiązuje)**. Przeczytaj też: `…/raporty/2026-10-05-priorytety-dziennik-centrali.md` (sekcje
   z 6.10: bramki pakietu v2, próby wdrożenia, E2E, rozstrzygnięcia 24–30), `…/raporty/2026-10-06-priorytety-proba-wdrozenia-raport.md`
   (runbook A–F z czasami, znaleziska), `…/raporty/2026-10-06-priorytety-pakiet-wdrozenia-raport.md` (wycofanie),
   `docs/superpowers/plans/2026-10-06-priorytety-obsluga-biura-i-pelny-przebieg.md` (jak działa system — do pytań biura),
   CLAUDE.md (Deployment, „Priorytety produkcji”). Wszystko z `origin/claude/priorytety-produkcji` przez `git show`.
2. **Hashe (v2):** produkcja `main` = `31a0b0145b222799234674bdf1e995dab6791a0c`; **wdrożenie**
   `9bd6fc510fb9a7efb617bafeba4e492f49668784` (`claude/wdrozenie-2026-10-08-v2`); **wycofanie**
   `e295421a123d4c86df89e0a0d2ec086f93b9ced4` (`claude/wycofanie-2026-10-08-v2`). Sprawdź, że oba istnieją na origin
   (`git rev-parse origin/claude/wdrozenie-2026-10-08-v2 origin/claude/wycofanie-2026-10-08-v2`) i że
   `git rev-parse origin/main` = `31a0b014…`. Jeśli `main` poszedł do przodu — **STOP**: wdrożenia nie robimy na tym squashu.
3. Zapytaj Konrada o sekcję A runbooka (zadania przed oknem): tablet Wycinania, CARTO, status Base. 524520, drukarka na hali
   i agent druku, Flota, aktywacja APK 1.8.0 rano. Odhacz każdy punkt; brak = decyzja Konrada, czy idziemy.

## W oknie
Harmonogram i kroki dokładnie wg runbooka (B — wdrożenie, C — start stołów, D — po wdrożeniu, E — objawy, F — wycofanie).
Kryteria STOP i wycofania: runbook (problem we wdrożeniu → F przed powrotem hali; problem tylko ze stołami → tryb
„zgodność”). Nigdy `--force`, nigdy push innego commitu niż z tabeli hashy.

## Po oknie
Dopisz do dziennika centrali (na `claude/priorytety-produkcji`, `git add -f`, commit `docs(priorytety): dziennik centrali - wdrozenie K7`,
push na tę gałąź — nigdy `main`) wpis „K7 — wdrożenie 8.10”: godziny kroków, wyniki kontroli (liczby, bez danych klientów),
odstępstwa, decyzje Konrada, stan po (tryby stanowisk, próg wersji, liczba tabletów vc 44). Pierwszy commit na `main` po
wdrożeniu (CLAUDE.md: Python 3.12.3 — commit `3d592f41` na gałęzi programu) i karty po wdrożeniu (lista w dzienniku,
rozstrzygnięcia 26–29 i bramka E2E) — dopiero po decyzji Konrada, osobnym pushem, po obserwacji pierwszych godzin.
````
