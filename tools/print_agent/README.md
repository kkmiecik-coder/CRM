# Print Agent — WoodPower CRM

## Co to jest

Mały skrypt w Pythonie, który chodzi 24/7 na hubie biura, odbiera z CRM zadania drukowania etykiet (ZPL) i wysyła je przez TCP do drukarki Xprinter XP-423B w sieci lokalnej. Po wydruku odsyła do CRM potwierdzenie (ACK), żeby zadanie nie było próbowane ponownie. Pracuje tylko w godzinach pracy — w nocy i w niedzielę agent śpi.

## Jak agent dowiaduje się o zadaniach

Dwie drogi, jedna uzupełnia drugą:

1. **Sygnał push (SSE).** Agent trzyma otwarte połączenie do brokera Centrifugo (`https://crm.woodpower.pl/realtime/`, kanał `print:agent`). Gdy operator kliknie „Drukuj etykietę", CRM wysyła krótki sygnał i agent natychmiast idzie po zadania. Etykieta wyjeżdża w ułamku sekundy od kliknięcia.
2. **Polling.** Zapasowe pytanie o zadania co jakiś czas — na wypadek zgubionego sygnału albo padniętego brokera. Co 60 s gdy push działa, co 10 s gdy nie działa.

**Przez brokera nie idą żadne dane — sam budzik.** ZPL zawsze przyjeżdża zwykłym zapytaniem do `/api/print-agent/jobs`, a stan zadania trzyma baza CRM. Dzięki temu restart agenta w trakcie pracy nie gubi etykiety: zadanie zostaje w kolejce jako `pending` i zostanie wydrukowane po powrocie.

**Awaria brokera nie zatrzymuje drukowania.** Agent po prostu wraca do pytania co 10 s, czyli do zachowania sprzed wdrożenia pusha. Jedyny objaw: etykieta wyjeżdża wolniej.

Do połączenia z brokerem agent potrzebuje krótkotrwałego tokena, który pobiera sam z CRM (`GET /api/print-agent/realtime-token`), autoryzując się tym samym tokenem co resztę zapytań. **Na hubie nie ma żadnego dodatkowego hasła do skonfigurowania.**

## Wymagania

- Python 3.8+ (Windows)
- Dostęp do sieci LAN z drukarką (`192.168.100.199:9100`)
- Dostęp do internetu (HTTPS do `crm.woodpower.pl`)
- Pakiety opcjonalne: `pip install colorama` (kolorowe logi na starszym CMD; nieobowiązkowe)

Skrypt nie używa żadnych zewnętrznych pakietów Pythona — działa na czystej standardowej bibliotece.

## Instalacja

1. Skopiuj cały folder `tools/print_agent/` w stałe miejsce na hubie, np. `C:\WoodPower\print_agent\`.
2. Skopiuj plik konfiguracyjny:
   ```
   copy config.example.ini config.ini
   ```
3. Otwórz `config.ini` w notatniku i ustaw `token` — bierzesz go z panelu admin CRM (zakładka Ustawienia → `?tab=config` → pole "Token print-agenta").
4. (Opcjonalnie) Zainstaluj `colorama` dla kolorowych logów:
   ```
   pip install colorama
   ```
5. Test uruchomienia:
   ```
   python print_agent.py
   ```
   Powinieneś zobaczyć banner z konfiguracją (token zamaskowany), potem `Otwarto kanał push` i `Kanał push aktywny (print:agent)`, a dalej cisza — agent czeka na zadania. Zatrzymaj `Ctrl+C`.

   Jeśli zamiast tego pojawi się `Brak kanału push — jadę na pollingu`, agent działa poprawnie, tylko wolniej. Patrz sekcja Diagnostyka.

## Autostart na Windowsie (Win 10/11)

Najprostszy sposób — folder Autostart:

1. Naciśnij `Win+R`, wpisz `shell:startup`, Enter — otworzy się folder.
2. Skopiuj do niego skrót do pliku `start.bat` (PPM na `start.bat` → "Wyślij do" → "Pulpit (utwórz skrót)", potem przenieś skrót do otwartego folderu).
3. Po następnym restarcie systemu agent wystartuje automatycznie po zalogowaniu.

Alternatywnie można użyć Harmonogramu zadań (`Task Scheduler`) z wyzwalaczem "Przy uruchomieniu" — jeśli chcesz, żeby agent ruszał bez logowania użytkownika.

## Godziny pracy

Konfigurujesz w `config.ini`, sekcja `[schedule]`:

```ini
workdays_start = 05:30   ; pn-pt początek
workdays_end = 15:30     ; pn-pt koniec
saturday_start = 05:30   ; sobota początek
saturday_end = 15:30     ; sobota koniec
```

Niedziela jest na sztywno wyłączona — agent w niedzielę śpi przez cały dzień. Poza godzinami pracy agent zamyka kanał push i nie pyta CRM o zadania (oszczędza ruch sieciowy), ale proces zostaje żywy i co 60s sprawdza, czy wracamy do okna pracy.

Po zmianie `config.ini` trzeba zrestartować agenta (zamknij okno i odpal `start.bat` ponownie).

## Wyłączenie pusha

W `config.ini`:

```ini
[realtime]
enabled = false
```

Agent wróci do samego pollingu co `interval_seconds`. To samo da się zrobić centralnie po stronie CRM (`REALTIME.enabled` w `config/core.json`) — wtedy agent sam wykryje, że push jest wyłączony, i nie będzie próbował się łączyć.

Jeśli hub ma `config.ini` sprzed wdrożenia pusha, **nie trzeba go ruszać** — brakujące klucze mają domyślne wartości (push włączony, adres brokera brany z CRM).

## Logi

- **Konsola** (okno cmd) — pokazuje na bieżąco co się dzieje. Banner przy starcie, info o pobranych zadaniach, ✓ / ✗ dla każdego wydruku. Brak spamu, jak nie ma zadań.
- **Plik `print_agent_errors.log`** w tym samym folderze co skrypt — append-only, zapisuje tylko błędy (ERROR/CRITICAL) z pełnym tracebackiem. Brak rotacji — jak plik urośnie, skasuj go ręcznie albo przenieś do archiwum, agent stworzy nowy.

## Aktualizacje

Agent siedzi w tym samym repo co CRM, w `tools/print_agent/`. Sposób aktualizacji zależy od tego, jak agent trafił na huba — sprawdź, czy w `C:\WoodPower\print_agent\` jest ukryty folder `.git`:

**Jeśli hub ma klon repozytorium** (`.git` istnieje):

```
cd C:\WoodPower\print_agent
git pull
```

**Jeśli folder został po prostu skopiowany** (`.git` nie istnieje — tak wygląda instalacja opisana wyżej): skopiuj z repo na huba **sam plik `print_agent.py`**, nadpisując stary. To jedyny plik, od którego zależy działanie agenta. `config.example.ini` i ten README są tylko wzorcem i dokumentacją — nie trzeba ich kopiować, choć nie zaszkodzi.

Agent nie używa żadnych zewnętrznych pakietów, więc aktualizacja nigdy nie wymaga `pip install`.

Potem zamknij okno agenta i odpal `start.bat` ponownie. `config.ini` i logi nie są w gicie, więc `git pull` ich nie ruszy.

## Diagnostyka

- **"Brak pliku konfiguracji"** — nie skopiowałeś `config.example.ini` → `config.ini`.
- **"401 Unauthorized z CRM"** — token zły albo wygasł. Sprawdź panel admin, popraw `config.ini`, zrestartuj agenta.
- **"Błąd sieci do CRM"** — hub stracił internet. Agent sam wróci do roboty następnym cyklem.
- **"Drukowanie nieudane"** — drukarka offline / odłączona od sieci / wyłączona / bez etykiet. Agent sam wypyta ją wtedy o stan i wypisze odpowiedzi. Możesz to też sprawdzić na żądanie, w drugim oknie, **bez zatrzymywania agenta**:
  ```
  python print_agent.py --drukarka
  ```
  Wysyła komendy ZPL `~HQES` (błędy i ostrzeżenia), `~HS` (status) i `~HI` (model), i pokazuje surowe odpowiedzi. Uwaga: XP-423B ma emulację ZPL, nie oryginalny firmware Zebry, więc nie na wszystkie musi odpowiadać. Ale jeśli nie udaje się nawet **połączyć**, drukarka jest odcięta i to jest odpowiedź sama w sobie.
- **"Brak kanału push — jadę na pollingu"** — etykiety nadal się drukują, tylko z opóźnieniem do 10 s. Przyczyny w kolejności prawdopodobieństwa: broker Centrifugo nie działa na serwerze, `REALTIME.enabled=false` w CRM, hub nie ma dostępu do `crm.woodpower.pl`. Sprawdzenie z huba:
  ```
  curl -i -H "Authorization: Bearer TWOJ_TOKEN" https://crm.woodpower.pl/api/print-agent/realtime-token
  ```
  HTTP 503 = push wyłączony albo nieskonfigurowany po stronie CRM (robota na serwerze). HTTP 200 z tokenem = problem jest w połączeniu do `/realtime/`.
- **"Brak pinga z brokera"** — połączenie push zamarło (typowo: zerwany internet albo restart serwera). Agent sam się przełączy i wróci — nic nie trzeba robić.
- Wszystkie błędy lądują też w `print_agent_errors.log` z pełnym tracebackiem.
