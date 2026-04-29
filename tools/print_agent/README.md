# Print Agent — WoodPower CRM

## Co to jest

Mały skrypt w Pythonie, który chodzi 24/7 na hubie biura, co 10 sekund pyta CRM o nowe zadania drukowania etykiet (ZPL) i wysyła je przez TCP do drukarki Xprinter XP-423B w sieci lokalnej. Po wydruku odsyła do CRM potwierdzenie (ACK), żeby zadanie nie było próbowane ponownie. Pollowanie tylko w godzinach pracy — w nocy i w niedzielę agent śpi.

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
   Powinieneś zobaczyć banner z konfiguracją (token zamaskowany), a potem cisza — agent czeka na zadania. Zatrzymaj `Ctrl+C`.

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

Niedziela jest na sztywno wyłączona — agent w niedzielę śpi przez cały dzień. Poza godzinami pracy agent nie polluje CRM (oszczędza ruch sieciowy), ale proces zostaje żywy i co 60s sprawdza, czy wracamy do okna pracy.

Po zmianie `config.ini` trzeba zrestartować agenta (zamknij okno i odpal `start.bat` ponownie).

## Logi

- **Konsola** (okno cmd) — pokazuje na bieżąco co się dzieje. Banner przy starcie, info o pobranych zadaniach, ✓ / ✗ dla każdego wydruku. Brak spamu, jak nie ma zadań.
- **Plik `print_agent_errors.log`** w tym samym folderze co skrypt — append-only, zapisuje tylko błędy (ERROR/CRITICAL) z pełnym tracebackiem. Brak rotacji — jak plik urośnie, skasuj go ręcznie albo przenieś do archiwum, agent stworzy nowy.

## Aktualizacje

Agent siedzi w tym samym repo co CRM, w `tools/print_agent/`. Żeby zaktualizować na hubie:

```
cd C:\WoodPower\print_agent
git pull
```

Potem zamknij okno agenta i odpal `start.bat` ponownie. `config.ini` i logi nie są w gicie, więc `git pull` ich nie ruszy.

## Diagnostyka

- **"Brak pliku konfiguracji"** — nie skopiowałeś `config.example.ini` → `config.ini`.
- **"401 Unauthorized z CRM"** — token zły albo wygasł. Sprawdź panel admin, popraw `config.ini`, zrestartuj agenta.
- **"Błąd sieci do CRM"** — hub stracił internet. Agent sam wróci do roboty następnym cyklem.
- **"Drukowanie nieudane"** — drukarka offline / odłączona od sieci / wyłączona. Sprawdź IP `192.168.100.199` (ping z huba).
- Wszystkie błędy lądują też w `print_agent_errors.log` z pełnym tracebackiem.
