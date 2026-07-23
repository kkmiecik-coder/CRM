# Ekstrakcja blog_seo do woodpower-auto_blog_seo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wydzielić `integrations/blog_seo/` z repo `woodpower-crm` do samodzielnego prywatnego repo `woodpower-auto_blog_seo` z własną historią, własnymi zależnościami, własnym auto-deployem (GitHub Actions → SSH) i własną pamięcią projektową (`CLAUDE.md` + `dev-notes/`), bez przerwy w działaniu codziennego crona na produkcji.

**Architecture:** `git subtree split` wyciąga historię commitów dot. `integrations/blog_seo/` z repo CRM do nowego lokalnego repo (flattening ścieżek). Nowe repo dostaje własny `requirements.txt` (dziś pożycza z CRM), `CLAUDE.md`, `dev-notes/`. Deploy: push do `main` → GitHub Actions SSH na VPS jako user `woodpower` → `git pull` + `pip install` w dedykowanym venv, bez restartu usługi (to cron, nie serwer). Cutover jest sekwencyjny: nowe repo wdrożone i zweryfikowane na VPS, dopiero potem `integrations/blog_seo/` znika z CRM.

**Tech Stack:** Python (venv, wersja jak na VPS — weryfikacja w Tasku 9), pytest, PyMySQL, Pillow, requests, git subtree, GitHub Actions, gh CLI.

## Global Constraints

- Komentarze w kodzie i dokumentacja po polsku (konwencja projektu, `CLAUDE.md` obu repo).
- Zero zmian logiki `blog_seo` w trakcie ekstrakcji — tylko przeniesienie. Jeśli test się wywali po przenosinach, to bug ekstrakcji do naprawienia, nie okazja do refaktoru.
- Każda operacja dotykająca VPS produkcyjnego (Task 9, 10, 11) wymaga wyraźnego potwierdzenia od Konrada przed wykonaniem — zgodnie z zasadą "backup → dry-run → potwierdzenie" z `CLAUDE.md` repo `woodpower-prestashop` (te same zasady dot. tego samego VPS).
- SSH root na VPS: `ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109`. Operacje na plikach usera `woodpower` zawsze przez `sudo -u woodpower <komenda>` (własność plików, ta sama zasada co w repo sklepu).
- Deploy key GitHub Actions musi być NOWY, dedykowany, ograniczony do konta `woodpower` (nie klucz roota `woodpower_claude`).

---

### Task 1: Wydzielenie historii commitów (git subtree split)

**Files:**
- Brak zmian w plikach — operacja czysto na historii gita, lokalnie w klonie `woodpower-crm`.

**Interfaces:**
- Produces: lokalny branch `blog_seo-history` w repo `woodpower-crm`, zawierający TYLKO commity dotyczące `integrations/blog_seo/`, ze ścieżkami spłaszczonymi (bez prefiksu `integrations/blog_seo/`). Task 2 go konsumuje.

- [ ] **Step 1: Sprawdź czysty stan repo CRM**

```bash
cd /c/Users/Grafik/Documents/woodpower-crm
git status --porcelain
```
Expected: pusty output (working tree clean) albo tylko znane niepowiązane zmiany. Jeśli są niezacommitowane zmiany dotyczące `integrations/blog_seo/` — zatrzymaj się i zapytaj Konrada, subtree split działa na zacommitowanej historii.

- [ ] **Step 2: Wykonaj subtree split**

```bash
git subtree split --prefix=integrations/blog_seo -b blog_seo-history
```
Expected: na końcu output pojedynczy SHA nowego brancha (np. `a1b2c3d...`), branch `blog_seo-history` istnieje lokalnie.

- [ ] **Step 3: Zweryfikuj spłaszczenie ścieżek**

```bash
git ls-tree -r --name-only blog_seo-history | head -20
```
Expected: ścieżki BEZ prefiksu `integrations/blog_seo/`, np. `catalog.py`, `core/log.py`, `llm/openai_provider.py`, `tests/test_catalog.py` — nie `integrations/blog_seo/catalog.py`.

- [ ] **Step 4: Zweryfikuj liczbę commitów**

```bash
git log --oneline blog_seo-history | wc -l
git log --oneline -- integrations/blog_seo | wc -l
```
Expected: liczby zbliżone (subtree split może scalić niektóre commity mieszane z innymi ścieżkami — to normalne, nie musi być 1:1).

---

### Task 2: Utworzenie nowego lokalnego repo i import historii

**Files:**
- Create: `C:\Users\Grafik\Documents\woodpower-auto_blog_seo\` (nowy katalog, nowe repo git)

**Interfaces:**
- Consumes: branch `blog_seo-history` z Task 1 (lokalna ścieżka `/c/Users/Grafik/Documents/woodpower-crm`).
- Produces: repo git w `/c/Users/Grafik/Documents/woodpower-auto_blog_seo` na branchu `main`, zawierające pełną przeniesioną historię i pliki spłaszczone do korzenia.

- [ ] **Step 1: Utwórz katalog i zainicjuj repo**

```bash
mkdir /c/Users/Grafik/Documents/woodpower-auto_blog_seo
cd /c/Users/Grafik/Documents/woodpower-auto_blog_seo
git init -b main
```
Expected: `Initialized empty Git repository in .../woodpower-auto_blog_seo/.git/`

- [ ] **Step 2: Zaciągnij historię z brancha subtree**

```bash
git pull /c/Users/Grafik/Documents/woodpower-crm blog_seo-history
```
Expected: fast-forward na `main`, pliki pojawiają się w katalogu roboczym (`catalog.py`, `core/`, `llm/`, `signals/`, `tests/`, `run_daily.py`, `run_cron.sh`, `config.py`, `config.example.env`, `README.md`, `DEPLOY-quotebot.md` — **uwaga:** `DEPLOY-quotebot.md` NIE powinien tu być, sprawdź w Step 3).

- [ ] **Step 3: Zweryfikuj zawartość — nic z chat_bridge**

```bash
ls
```
Expected: tylko pliki blog_seo (`catalog.py`, `config.py`, `content_type.py`, `images.py`, `linker.py`, `publisher.py`, `run_cron.sh`, `run_daily.py`, `shop_db.py`, `stock.py`, `store.py`, `topics.py`, `writer.py`, `core/`, `llm/`, `signals/`, `tests/`, `README.md`, `config.example.env`). Jeśli widzisz cokolwiek z `chat_bridge` — subtree split poszedł źle, zatrzymaj się.

- [ ] **Step 4: Usuń cache'e które nie powinny być trackowane (jeśli trafiły do historii)**

```bash
git rm -r --cached .pytest_cache 2>/dev/null; find . -name __pycache__ -exec git rm -r --cached {} \; 2>/dev/null
git status --porcelain
```
Expected: jeśli coś usunięto z indexu, `git status` pokaże `D` dla tych plików — to naprawimy `.gitignore`-em w Task 3 i zacommitujemy razem. Jeśli nic nie było trackowane, brak outputu — pomiń.

---

### Task 3: requirements.txt i .gitignore

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nic (statyczne pliki konfiguracyjne).
- Produces: `requirements.txt` używany w Task 4 (lokalny venv) i Task 9 (venv na VPS).

- [ ] **Step 1: Napisz requirements.txt**

Wersje skopiowane 1:1 z `requirements.txt` CRM dla parytetu zachowania (dokładnie te paczki, których realnie używa kod — zweryfikowane grepem importów: `pymysql`, `PIL`/Pillow, `requests`; nic więcej z zewnętrznych bibliotek nie jest importowane w `blog_seo`).

```
PyMySQL==1.0.2
Pillow>=9.0.0
requests==2.27.1
```

Zapisz jako `requirements.txt` w korzeniu.

- [ ] **Step 2: Napisz .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
venv/
.env
*.db
```

Zapisz jako `.gitignore` w korzeniu.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt .gitignore
git add -u
git commit -m "$(cat <<'EOF'
chore: dodaj requirements.txt i .gitignore po ekstrakcji z CRM

Wlasne zaleznosci (PyMySQL, Pillow, requests) zamiast pozyczania
venv CRM. Usunieto z trackingu cache'e (__pycache__, .pytest_cache)
jesli trafily do historii przy subtree split.
EOF
)"
```
Expected: commit utworzony, `git status` czyste.

---

### Task 4: Weryfikacja testów w nowym repo (własny venv)

**Files:**
- Modify: brak (tylko weryfikacja istniejącego kodu w nowym środowisku)

**Interfaces:**
- Consumes: `requirements.txt` z Task 3, pakiet `tests/` przeniesiony w Task 2.
- Produces: potwierdzenie że kod działa samodzielnie (bramka przed dalszymi krokami — jeśli tu coś nie przejdzie, NIE kontynuuj do Task 5+).

- [ ] **Step 1: Utwórz lokalny venv (Windows, dev)**

```bash
cd /c/Users/Grafik/Documents/woodpower-auto_blog_seo
python -m venv venv
```
Expected: katalog `venv/` utworzony.

- [ ] **Step 2: Zainstaluj zależności**

```bash
venv/Scripts/pip install -r requirements.txt pytest
```
Expected: instalacja bez błędów.

- [ ] **Step 3: Uruchom pełny pakiet testów**

```bash
venv/Scripts/python -m pytest -v
```
Expected: wszystkie testy PASS (ten sam wynik co w CRM przed ekstrakcją: `docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"`). Jeśli cokolwiek FAIL — sprawdź czy to brakująca zależność (dopisz do `requirements.txt`, wróć do Task 3) czy realny problem ze spłaszczeniem ścieżek importów.

- [ ] **Step 4: Uruchom dry-run pipeline (bez zapisu do sklepu)**

```bash
venv/Scripts/python run_daily.py --dry-run
```
Expected: kończy się bez wyjątku (może zwrócić błąd braku kluczy API w `.env` — to oczekiwane lokalnie bez sekretów; liczy się brak błędów importu/ścieżek). Jeśli błąd dotyczy `ModuleNotFoundError` albo złej ścieżki do configu — problem ze spłaszczeniem, napraw przed dalszymi taskami.

---

### Task 5: Pamięć projektowa (CLAUDE.md + dev-notes/)

**Files:**
- Create: `CLAUDE.md`
- Create: `dev-notes/STAN.md`

**Interfaces:**
- Consumes: nic.
- Produces: dokumentacja projektowa dla przyszłych sesji Claude Code na obu maszynach Konrada.

- [ ] **Step 1: Napisz CLAUDE.md**

```markdown
# CLAUDE.md

Wskazówki dla Claude Code (claude.ai/code) przy pracy z tym repozytorium.

> **Start sesji:** przeczytaj `dev-notes/STAN.md` (bieżący stan). Komentarze w kodzie po polsku.

## O projekcie

`woodpower-auto_blog_seo` — automat blogowy SEO dla sklepu **woodpower.pl** (PrestaShop / moduł ETS Simple Blog).
Raz na dobę (cron) tworzy JEDEN nieopublikowany szkic artykułu (`enabled=0`). Publikację zatwierdza
człowiek w panelu PrestaShop. Wydzielony z `woodpower-crm` (`integrations/blog_seo/`) 2026-07-23 —
zero importów z CRM, komunikacja ze sklepem tylko przez bezpośrednie połączenie do bazy PrestaShop.

Powiązane repo: `woodpower-crm` (CRM), `woodpower-prestashop` (sklep — ten sam VPS produkcyjny).

## Development lokalny

```bash
python -m venv venv
venv/Scripts/pip install -r requirements.txt pytest   # Windows; venv/bin/... na macOS/Linux
venv/Scripts/python -m pytest -v
venv/Scripts/python run_daily.py --dry-run             # przebieg bez zapisu do sklepu
```

Sekrety lokalne: skopiuj `config.example.env` → `.env` (gitignored), wypełnij kluczami dev/testowymi.

## Deployment (auto, push do main)

`git push` do `main` → GitHub Actions (`.github/workflows/deploy.yml`) łączy się po SSH na VPS jako
user `woodpower` → `git pull` w `/home/woodpower/woodpower-auto_blog_seo/` + `pip install` w
dedykowanym venv. Bez restartu usługi — to cron (raz dziennie ok. 06:15), nie długo działający proces.

## Dostęp do serwera (SSH)

VPS produkcyjny: `187.127.68.109` (Hostinger, ten sam serwer co sklep i CRM). Deploy przez GitHub
Actions używa dedykowanego klucza (deploy key, tylko user `woodpower`, NIE klucz roota). Do ręcznej
diagnostyki na VPS: `ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109`, potem
`sudo -u woodpower <komenda>` dla operacji na plikach tego repo (własność `woodpower:woodpower`).

## Dane i sekrety (poza gitem)

- `.env` — sekrety dedykowane tej integracji (osobne od CRM/mostka), na VPS w
  `/home/woodpower/woodpower-auto_blog_seo/.env` (albo w katalogu danych — patrz `dev-notes/STAN.md`
  po ostatecznym umiejscowieniu w Tasku 9 planu ekstrakcji).
- `blog_seo.db` (sqlite, dedup/historia tematów) i `blog.log` — `/home/woodpower/blog_seo/`.
- Baza PrestaShop: automat TYLKO czyta katalog i wstawia nowy szkic posta. Nie zmienia danych sklepu.

## Cron

`/etc/cron.d/woodpower-blog` na VPS, uruchamia jako `woodpower` raz dziennie. Wywołuje `run_cron.sh`,
który ładuje `.env` i odpala `run_daily.py`.
```

Zapisz jako `CLAUDE.md` w korzeniu.

- [ ] **Step 2: Napisz dev-notes/STAN.md**

```markdown
# STAN — woodpower-auto_blog_seo

**Ostatnia aktualizacja:** 2026-07-23

## Skąd to repo

Wydzielone z `woodpower-crm` (`integrations/blog_seo/`) — zobacz spec i plan w repo CRM:
`docs/superpowers/specs/2026-07-23-blog-seo-extraction-design.md` i
`docs/superpowers/plans/2026-07-23-blog-seo-extraction.md`. Historia commitów przeniesiona przez
`git subtree split` — pełen kontekst decyzji sprzed ekstrakcji jest w `git log` tego repo.

## Bieżący stan wdrożenia

- [ ] Repo GitHub utworzone (prywatne, `kkmiecik-coder/woodpower-auto_blog_seo`)
- [ ] GitHub Actions auto-deploy skonfigurowany i przetestowany
- [ ] Wdrożone na VPS w `/home/woodpower/woodpower-auto_blog_seo/`
- [ ] Cron (`/etc/cron.d/woodpower-blog`) przepięty na nową ścieżkę, zweryfikowany pełny przebieg
- [ ] Stary `integrations/blog_seo/` usunięty z repo CRM

(Odhaczaj w miarę wykonywania planu ekstrakcji — checklista lustrzana do tasków w planie.)

## Gotchas przeniesione z CRM

- Testy: `python -m pytest` z korzenia repo działa od razu (po ekstrakcji już bez specjalnego cwd
  jak w monorepo CRM, bo pakiet jest teraz w korzeniu, nie w podkatalogu).
- `BLOG_PS_DB_HOST` domyślnie `127.0.0.1` — zakłada, że baza PrestaShop jest osiągalna lokalnie z
  maszyny, na której działa automat (prawda na VPS, bo sklep i automat są na tym samym serwerze).
```

Zapisz jako `dev-notes/STAN.md`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md dev-notes/STAN.md
git commit -m "docs: dodaj CLAUDE.md i dev-notes/STAN.md (pamiec projektowa po ekstrakcji)"
```

---

### Task 6: Aktualizacja README.md pod nowe repo

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nic.
- Produces: dokumentacja zgodna z nową lokalizacją (nie odwołuje się już do ścieżek wewnątrz CRM).

- [ ] **Step 1: Zaktualizuj sekcję "Deploy na VPS" i "Cron" w README.md**

Zamień:
```markdown
## Deploy na VPS
Kod jedzie z repo (integrations/blog_seo/). Sekrety w OSOBNYM pliku .env (poza gitem):
1. Skopiuj config.example.env -> .env, wypełnij dedykowanymi kluczami, `chmod 600 .env`.
2. Uruchamiaj jako uzytkownik `woodpower` (musi miec prawo zapisu do img/ets_blog/post/).
3. Zainstaluj zaleznosci w venv (PyMySQL, Pillow, requests — sa w requirements.txt CRM).

## Cron (raz na dobe, np. 06:15)
Plik /etc/cron.d/woodpower-blog (uruchamia jako woodpower, laduje .env):
    15 6 * * * woodpower cd /sciezka/integrations/blog_seo && set -a && . ./.env && set +a && /sciezka/venv/bin/python run_daily.py >> /home/woodpower/blog_seo/blog.log 2>&1
```

Na:
```markdown
## Deploy na VPS
Push do `main` = auto-deploy (GitHub Actions SSH, patrz `CLAUDE.md`). Kod ląduje w
`/home/woodpower/woodpower-auto_blog_seo/`. Sekrety w OSOBNYM pliku .env (poza gitem):
1. Skopiuj config.example.env -> .env, wypełnij dedykowanymi kluczami, `chmod 600 .env`.
2. Działa jako uzytkownik `woodpower` (musi miec prawo zapisu do img/ets_blog/post/).
3. Własny venv w repo (`requirements.txt`), niezależny od CRM.

## Cron (raz na dobe, np. 06:15)
Plik /etc/cron.d/woodpower-blog (uruchamia jako woodpower, laduje .env):
    15 6 * * * woodpower cd /home/woodpower/woodpower-auto_blog_seo && set -a && . ./.env && set +a && ./venv/bin/python run_daily.py >> /home/woodpower/blog_seo/blog.log 2>&1
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: zaktualizuj README pod samodzielne repo (nowe sciezki deployu/crona)"
```

---

### Task 7: Utworzenie prywatnego repo GitHub i push

**Files:** brak.

**Interfaces:**
- Consumes: lokalne repo z Task 1-6 gotowe (`main`, wszystkie commity).
- Produces: `https://github.com/kkmiecik-coder/woodpower-auto_blog_seo` — konsumowane przez Task 8 (Actions) i Task 9 (git clone na VPS).

- [ ] **Step 1: Utwórz repo przez gh CLI**

```bash
cd /c/Users/Grafik/Documents/woodpower-auto_blog_seo
gh repo create kkmiecik-coder/woodpower-auto_blog_seo --private --source=. --description "Automat blogowy SEO dla woodpower.pl (wydzielony z woodpower-crm)"
```
Expected: repo utworzone, remote `origin` dodany automatycznie do lokalnego repo.

- [ ] **Step 2: Push**

```bash
git push -u origin main
```
Expected: `main` na GitHubie zawiera pełną przeniesioną historię.

- [ ] **Step 3: Zweryfikuj na GitHubie**

```bash
gh repo view kkmiecik-coder/woodpower-auto_blog_seo --web
```
Sprawdź wizualnie: pliki w korzeniu (nie w podkatalogu), historia commitów obecna, repo private.

---

### Task 8: GitHub Actions auto-deploy (SSH, dedykowany deploy key)

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: repo GitHub z Task 7.
- Produces: automatyczny deploy na push do `main`, konsumowany operacyjnie w Task 9+ (od tego momentu KAŻDY push na `main` próbuje deployować — więc ten task musi być zrobiony PO tym jak VPS ma już gdzie deployować, czyli po Task 9 Step 1-2; workflow można dodać teraz, ale pierwszy realny przebieg zadziała dopiero gdy katalog na VPS istnieje).

⚠️ **Wymaga potwierdzenia Konrada:** generowanie i instalacja nowego klucza SSH na VPS to zmiana bezpieczeństwa produkcji.

- [ ] **Step 1: Wygeneruj dedykowany klucz deploy (na maszynie lokalnej, NIE na VPS)**

```bash
ssh-keygen -t ed25519 -f /c/Users/Grafik/.ssh/woodpower_blog_seo_deploy -C "github-actions-deploy-blog-seo" -N ""
```
Expected: para kluczy `woodpower_blog_seo_deploy` (prywatny) i `woodpower_blog_seo_deploy.pub` (publiczny).

- [ ] **Step 2: Dodaj klucz publiczny do authorized_keys usera woodpower na VPS**

```bash
PUBKEY=$(cat /c/Users/Grafik/.ssh/woodpower_blog_seo_deploy.pub)
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower bash -c \"mkdir -p ~woodpower/.ssh && echo '$PUBKEY' >> ~woodpower/.ssh/authorized_keys && chmod 700 ~woodpower/.ssh && chmod 600 ~woodpower/.ssh/authorized_keys\""
```
Expected: bez błędów. Zweryfikuj: `ssh -i /c/Users/Grafik/.ssh/woodpower_blog_seo_deploy woodpower@187.127.68.109 'whoami'` → zwraca `woodpower`.

- [ ] **Step 3: Dodaj sekrety do repo GitHub**

```bash
cd /c/Users/Grafik/Documents/woodpower-auto_blog_seo
gh secret set VPS_HOST --body "187.127.68.109"
gh secret set VPS_USER --body "woodpower"
gh secret set VPS_SSH_KEY < /c/Users/Grafik/.ssh/woodpower_blog_seo_deploy
```
Expected: trzy sekrety widoczne w `gh secret list`.

- [ ] **Step 4: Napisz workflow**

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            set -e
            cd /home/woodpower/woodpower-auto_blog_seo
            git pull origin main
            venv/bin/pip install -q -r requirements.txt
            echo "Deploy OK: $(git rev-parse --short HEAD)"
```

Zapisz jako `.github/workflows/deploy.yml`.

- [ ] **Step 5: Commit i push**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: dodaj auto-deploy GitHub Actions (SSH, dedykowany deploy key)"
git push
```
Expected: workflow uruchomi się automatycznie, ale **zawiedzie** na `cd /home/woodpower/woodpower-auto_blog_seo` bo katalog jeszcze nie istnieje — to oczekiwane, naprawi się po Task 9. Nie martw się czerwonym krzyżykiem na GitHubie na tym etapie.

---

### Task 9: Wdrożenie na VPS (nowa ścieżka, dedykowany venv)

**Files:** brak lokalnie — operacje na VPS.

**Interfaces:**
- Consumes: repo GitHub z Task 7, `requirements.txt` z Task 3.
- Produces: działający checkout w `/home/woodpower/woodpower-auto_blog_seo/` z venv gotowym do użycia przez cron w Task 10.

⚠️ **Wymaga potwierdzenia Konrada przed wykonaniem — dotyka produkcyjnego VPS.**

- [ ] **Step 1: Sprawdź dostępną wersję Pythona na VPS**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "which python3 python3.12 python3.11 2>/dev/null; python3 --version"
```
Expected: lista dostępnych binarek. Wybierz najbliższą wersji użytej lokalnie w Task 4 (idealnie 3.12 — sprawdź, na tej samej zasadzie co gotcha "zawsze php8.2, nie php" w repo sklepu: dopasuj wersję świadomie, nie zakładaj `python3` domyślnego bez sprawdzenia).

- [ ] **Step 2: Sklonuj repo na VPS jako user woodpower**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower git clone https://github.com/kkmiecik-coder/woodpower-auto_blog_seo.git /home/woodpower/woodpower-auto_blog_seo"
```
Expected: klon udany. Jeśli repo private i brak dostępu przez HTTPS bez tokena — użyj zamiast tego `sudo -u woodpower git clone git@github.com:kkmiecik-coder/woodpower-auto_blog_seo.git ...` z kluczem deploy z Task 8 dodanym też jako read-only deploy key w ustawieniach repo GitHub (Settings → Deploy keys), albo skopiuj tar.gz przez scp jako fallback.

- [ ] **Step 3: Utwórz venv i zainstaluj zależności**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower bash -c 'cd /home/woodpower/woodpower-auto_blog_seo && python3 -m venv venv && venv/bin/pip install -q -r requirements.txt'"
```
Expected: bez błędów.

- [ ] **Step 4: Skopiuj istniejący .env do nowej lokalizacji**

Sekrety dziś leżą w starym miejscu (wewnątrz checkoutu CRM, `integrations/blog_seo/.env`, poza gitem). Skopiuj je 1:1, bez zmiany wartości:

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower cp /home/woodpower-crm/htdocs/crm.woodpower.pl/integrations/blog_seo/.env /home/woodpower/woodpower-auto_blog_seo/.env && sudo -u woodpower chmod 600 /home/woodpower/woodpower-auto_blog_seo/.env"
```
Expected: `.env` obecny w nowej lokalizacji, uprawnienia `600`.

- [ ] **Step 5: Smoke test — dry-run z nowego miejsca**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower bash -c 'cd /home/woodpower/woodpower-auto_blog_seo && set -a && . ./.env && set +a && venv/bin/python run_daily.py --dry-run'"
```
Expected: przebiega bez błędu, zachowanie identyczne jak dotychczasowe uruchomienie ze starej lokalizacji (porównaj z ostatnim wpisem w `/home/woodpower/blog_seo/blog.log`).

- [ ] **Step 6: Re-run deployu GitHub Actions (żeby czerwony krzyżyk z Task 8 zmienił się na zielony)**

```bash
gh run list --repo kkmiecik-coder/woodpower-auto_blog_seo --limit 1
gh run rerun --repo kkmiecik-coder/woodpower-auto_blog_seo <run-id>
```
Expected: przebieg zielony — potwierdza, że pełna pętla push→deploy działa end-to-end.

---

### Task 10: Przepięcie crona i weryfikacja pełnego przebiegu

**Files:** brak lokalnie — `/etc/cron.d/woodpower-blog` na VPS.

**Interfaces:**
- Consumes: działający checkout z Task 9.
- Produces: cron produkcyjny wskazujący na nowe repo — od tego momentu stary katalog w CRM jest martwy i bezpiecznie go usunąć (Task 11).

⚠️ **Wymaga potwierdzenia Konrada przed wykonaniem — dotyka produkcyjnego crona.**

- [ ] **Step 1: Podejrzyj obecną zawartość crona**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "cat /etc/cron.d/woodpower-blog"
```
Expected: linia wskazująca starą ścieżkę `.../integrations/blog_seo`.

- [ ] **Step 2: Podmień na nową ścieżkę**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "cat > /etc/cron.d/woodpower-blog <<'EOF'
15 6 * * * woodpower cd /home/woodpower/woodpower-auto_blog_seo && set -a && . ./.env && set +a && venv/bin/python run_daily.py >> /home/woodpower/blog_seo/blog.log 2>&1
EOF"
```
Expected: plik nadpisany nową zawartością.

- [ ] **Step 3: Ręczne uruchomienie pełnego przebiegu (nie czekaj do 06:15)**

```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "sudo -u woodpower bash -c 'cd /home/woodpower/woodpower-auto_blog_seo && set -a && . ./.env && set +a && venv/bin/python run_daily.py >> /home/woodpower/blog_seo/blog.log 2>&1'"
```
Expected: kod wyjścia 0. Sprawdź log:
```bash
ssh -i ~/.ssh/woodpower_claude -o IdentitiesOnly=yes root@187.127.68.109 "tail -30 /home/woodpower/blog_seo/blog.log"
```

- [ ] **Step 4: Potwierdź szkic w panelu PrestaShop**

Zaloguj się do panelu PrestaShop (Simple Blog) i sprawdź, czy pojawił się nowy nieopublikowany szkic (`enabled=0`) — dokładnie tak jak dotychczasowe działanie automatu. To ostateczne potwierdzenie, że ekstrakcja nie zepsuła funkcjonalności.

---

### Task 11: Usunięcie integrations/blog_seo z repo CRM

**Files:**
- Delete (w repo `woodpower-crm`): cały katalog `integrations/blog_seo/`

**Interfaces:**
- Consumes: potwierdzenie z Task 10 że nowe repo działa produkcyjnie i cron już tam wskazuje.
- Produces: jedno źródło prawdy (nowe repo). CRM auto-deploy usunie stary katalog z VPS przy najbliższym push.

⚠️ **Wymaga potwierdzenia Konrada — push do `main` CRM triggeruje auto-deploy (`git reset --hard` na VPS).**

- [ ] **Step 1: Usuń katalog w repo CRM**

```bash
cd /c/Users/Grafik/Documents/woodpower-crm
git rm -r integrations/blog_seo
```
Expected: pliki oznaczone do usunięcia.

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore(blog_seo): usun integrations/blog_seo — wydzielony do osobnego repo

Kod i historia przeniesione do woodpower-auto_blog_seo (prywatne repo,
wlasny auto-deploy). Cron na VPS juz przepiety i zweryfikowany
(docs/superpowers/plans/2026-07-23-blog-seo-extraction.md, Task 9-10).
Zero zmiany funkcjonalnosci — czyste sprzatanie po ekstrakcji.
EOF
)"
```

- [ ] **Step 3: Push (dopiero po jawnym OK od Konrada — wywoła auto-deploy CRM)**

```bash
git push
```
Expected: push udany, CRM auto-deploy usuwa stary katalog z VPS. Zweryfikuj zdrowie CRM po deployu:
```bash
curl -s -o /dev/null -w "%{http_code}" https://crm.woodpower.pl/
```
Expected: `200` (albo kod przekierowania na login, w każdym razie NIE `500`).

**Uwaga:** repo CRM miało już 5 niepowiązanych niepushowanych commitów przed tym zadaniem (docker dev setup) — ten push wypchnie też je. Potwierdź z Konradem czy to zamierzone, czy woli je wydzielić osobno przed tym pushem.

---

## Self-Review

**Pokrycie specu:** wszystkie 7 sekcji specu (`2026-07-23-blog-seo-extraction-design.md`) mają odpowiadający task — nowe repo (Task 2, 7), historia (Task 1), struktura/requirements (Task 3), topologia VPS (Task 9), auto-deploy (Task 8), sekwencja cutoveru (Task 9→10→11 w tej kolejności), testy (Task 4, powtórzone jako gate w Task 9 Step 5 i Task 10 Step 3-4).

**Placeholder scan:** brak TBD/TODO — każdy krok ma pełną, konkretną komendę lub treść pliku.

**Spójność:** ścieżka VPS `/home/woodpower/woodpower-auto_blog_seo/` spójna od Task 8 do Task 11. Nazwa crona `/etc/cron.d/woodpower-blog` spójna z istniejącą (nie tworzymy nowej). User `woodpower` konsekwentnie we wszystkich krokach VPS (zgodnie z decyzją Konrada).
