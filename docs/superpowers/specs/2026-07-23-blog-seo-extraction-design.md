# Ekstrakcja blog_seo do samodzielnego repozytorium — Design Spec

**Data:** 2026-07-23
**Zakres:** Wydzielenie `integrations/blog_seo/` z repo `woodpower-crm` do osobnego prywatnego repo GitHub z własnym auto-deployem i własną pamięcią projektową.
**Kontekst szerszy:** To pierwszy z dwóch niezależnych bytów do wyizolowania z `integrations/`. Drugi — `chat_bridge` (most Allegro/OLX/Chatwoot + boty AI) — ma osobny spec później; jest już bardziej samodzielny (własny Dockerfile, zero importów z CRM) niż `blog_seo`, więc świadomie robimy go w drugiej kolejności. `blog_seo` idzie pierwszy, bo działa tylko raz dziennie (cron), a `chat_bridge` działa 24/7 w żywym czacie — niższe ryzyko na start.

## Stan obecny (przed ekstrakcją)

- Kod: `integrations/blog_seo/` w repo `woodpower-crm`, płaski styl importów (`import catalog` itp.), zero importów z `app.py`/`extensions.py`/`modules/` CRM — logicznie już odizolowany.
- Zależności: **brak własnego `requirements.txt`** — korzysta ze wspólnego venv CRM (PyMySQL, Pillow, requests, SDK-i LLM).
- Uruchomienie: cron (`/etc/cron.d/woodpower-blog`, user `woodpower`, raz dziennie ok. 06:15) woła `run_cron.sh`, który relatywną ścieżką `../../venv/bin/python run_daily.py` zakłada, że siedzi wewnątrz checkoutu CRM.
- Dane: `.env` (sekrety, poza gitem), `blog_seo.db` (sqlite, dedup/historia), `blog.log` — wszystkie w `/home/woodpower/blog_seo/` na VPS, **już dziś fizycznie osobno** od checkoutu CRM.
- Sklep: łączy się bezpośrednio z bazą PrestaShop (czyta katalog, wstawia szkic posta) i zapisuje obrazy do `img/ets_blog/post/` sklepu — nie przez API CRM.
- Testy: własny pakiet `tests/` (pytest), uruchamiany z osobnym cwd (`docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"`).

## Docelowa architektura

### 1. Nowe repozytorium
`woodpower-auto_blog_seo` (prywatne, GitHub, konto `kkmiecik-coder`). Lokalny klon na obu maszynach Konrada: `~/Documents/woodpower-auto_blog_seo` (obok `woodpower-crm` i `woodpower-prestashop`).

### 2. Historia commitów
Przeniesiona przez `git subtree split --prefix=integrations/blog_seo -b blog_seo-history` w repo CRM, następnie zaimportowana jako historia nowego repo (`git push` z lokalnego remote wskazującego na branch `blog_seo-history`). Stare repo CRM zachowuje swój `git log` bez zmian — subtree split nie usuwa niczego wstecznie.

### 3. Struktura nowego repo
Zawartość dzisiejszego `integrations/blog_seo/` trafia do korzenia nowego repo (spłaszczenie jednego poziomu). Dodatki:
- **`requirements.txt`** — nowy, wydzielony z `requirements.txt` CRM (tylko realnie używane paczki: PyMySQL, Pillow, requests, SDK LLM openai/anthropic).
- **`CLAUDE.md`** — po polsku, wzorowany na konwencji `woodpower-crm`/`woodpower-prestashop` (opis projektu, dev workflow, deploy, gotchas).
- **`dev-notes/`** — śledzony w git, dla ciągłości pamięci między dwiema maszynami Konrada (ten sam wzorzec co w `woodpower-prestashop`).
- Reszta (`core/`, `llm/`, `signals/`, `tests/`, `run_daily.py`, `run_cron.sh`, `config.py`, `config.example.env`) — bez zmian logiki, tylko przeniesienie.

### 4. Topologia VPS
- **Kod:** nowy checkout `git clone` w `/home/woodpower/woodpower-auto_blog_seo/`, właściciel `woodpower`.
- **Dane:** zostają tam gdzie są dziś — `/home/woodpower/blog_seo/` (`.env`, `blog_seo.db`, `blog.log`). Zero zmian uprawnień: `woodpower` już ma prawo zapisu do `img/ets_blog/post/` sklepu i dostęp do bazy PrestaShop.
- **Venv:** dedykowany, np. `/home/woodpower/woodpower-auto_blog_seo/venv/` (dziś pożycza venv CRM — po ekstrakcji musi mieć własny, bo CRM nie będzie już dostępny w tej samej ścieżce względnej).

### 5. Auto-deploy
GitHub Actions w nowym repo (`.github/workflows/deploy.yml`):
- Trigger: push do `main`.
- Krok: SSH na VPS (`187.127.68.109`) jako `woodpower` (klucz w GitHub Secrets — deploy key ograniczony do tego repo, nie klucz roota).
- Komendy: `git pull origin main` w checkout + `pip install -r requirements.txt` w dedykowanym venv.
- **Bez restartu usługi** — to nie jest długo działający proces, tylko cron odpalający się raz dziennie i tak sięgnie po świeży kod przy najbliższym uruchomieniu.

Odrzucone alternatywy:
- *Webhook przez istniejący Flask/nginx (CRM lub sklep)* — działałoby, ale ponownie splata `blog_seo` z infrastrukturą innego repo, sprzecznie z celem izolacji.
- *Cron pollingowy (git pull co N minut)* — nie jest to "push=auto-deploy", tylko opóźniony polling.

### 6. Sekwencja cutoveru (bezpieczeństwo — chroni przed zepsuciem crona na produkcji)

1. Lokalnie: utworzenie repo + `git subtree split` + `requirements.txt` + `CLAUDE.md` + `dev-notes/`. Zero ruchu na VPS.
2. Deploy na VPS do **nowej** ścieżki (`/home/woodpower/woodpower-auto_blog_seo/`), osobny venv, smoke test: `python run_daily.py --dry-run` z nowego miejsca, porównanie zachowania ze starym.
3. Przepięcie `/etc/cron.d/woodpower-blog` na nową ścieżkę/venv. Weryfikacja **jednego pełnego przebiegu** (poczekać do 06:15 albo odpalić ręcznie jako `woodpower`) — potwierdzić szkic w PrestaShop tak jak dotychczas.
4. **Dopiero teraz**: usunięcie `integrations/blog_seo/` z repo `woodpower-crm`, commit + push. CRM auto-deploy zrobi `git reset --hard origin/main` na VPS, co usunie stary folder z checkoutu CRM — bezpieczne, bo cron już nie tam wskazuje.
5. Ustawienie GitHub Actions w nowym repo na przyszłe zmiany (jeśli jeszcze nie skonfigurowane w kroku 1).

### 7. Testy
Istniejący pakiet `tests/` jedzie 1:1 do nowego repo (ta sama konwencja: uruchamiany z własnego katalogu jako cwd). Pełny przebieg `pytest` — zielony — to bramka przed krokiem 3 (przepięcie crona).

## Poza zakresem

- Ekstrakcja `chat_bridge` — osobny spec, po zakończeniu tego.
- Zmiana logiki generowania treści blogowej — czysto przeniesienie, bez zmian funkcjonalnych.
- Nowy system użytkownika na VPS — świadomie reużywamy `woodpower`.
