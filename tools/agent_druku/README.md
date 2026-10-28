# Agent druku WoodPower (v2)

Program na komputerze hali, który drukuje etykiety z kolejki CRM na dwóch drukarkach:
**Etykiety 60×40** (`etykiety`) i **Paczki 100×150** (`wysylka`). Składa się z jednego programu
`AgentDruku.exe` w trzech rolach:

- **usługa Windows** `WoodPowerAgentDruku` — działa bez zalogowanego użytkownika, łączy się z CRM,
  pobiera zadania i wysyła je do drukarek;
- **ikona w zasobniku** — kolorowa kropka przy zegarze (zielona: wszystko działa, żółta: uwaga,
  czerwona: awaria) i okienko ze stanem drukarek, ostatnimi wydrukami, konfiguracją i parowaniem;
- **diagnostyka** — jednorazowy odczyt stanu drukarek z wiersza poleceń.

## Instalacja na komputerze hali

1. Skopiuj `AgentDruku-<wersja>-setup.exe` na komputer hali i uruchom go (potrzebne konto
   administratora — Windows zapyta o zgodę).
2. Instalator kładzie program w `C:\Program Files\WoodPower\AgentDruku\`, zakłada i uruchamia
   usługę `WoodPowerAgentDruku` (konto systemowe, start automatyczny, ponowne uruchomienie 10 s
   po awarii) i dodaje ikonę do autostartu wszystkich użytkowników.
3. Dane agenta leżą w `%ProgramData%\WoodPower\AgentDruku\`: konfiguracja z tokenem, klucz
   lokalnego API, dziennik wydruków i logi (`logi\`). Katalog jest dostępny tylko dla systemu
   i administratorów; jedynie plik klucza lokalnego może odczytać użytkownik zalogowany przy
   komputerze (bez niego ikona nie porozmawia z usługą).

Adres serwera CRM ustala instalator — parametr `/CRM=https://<adres CRM>` (domyślnie publiczny
adres CRM WoodPower). Agent łączy się tylko z tym serwerem i tylko z niego pobiera aktualizacje;
zmiana serwera wymaga ponownej instalacji z innym `/CRM=`. Aktualizacja bez parametru zostawia
dotychczasowy adres; pierwsza instalacja (także po odinstalowaniu) zawsze wpisuje adres od nowa. Dozwolone jest tylko `https://` (wyjątek: `http://127.0.0.1` i
`http://localhost` do testów).

Instalator działa też cicho: `AgentDruku-<wersja>-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
(błędy, np. usługa, która nie wystartowała, trafiają wtedy do logu instalatora — parametr `/LOG=<plik>`).

## Parowanie z CRM

1. W CRM otwórz panel produkcji, zakładkę **Drukarki**, i wygeneruj token nowego agenta
   (wymaga roli administratora). Token pokazuje się **tylko raz** — skopiuj go od razu.
2. Kliknij ikonę agenta w zasobniku → zakładka **Parowanie**. Adres CRM jest już wpisany
   (z instalatora) — wklej token i kliknij **Sparuj z CRM**.
3. Po kilku sekundach zakładka pokazuje „Sparowany z …”, ikona robi się zielona, a agent widnieje w zakładce Drukarki
   jako aktywny. Token zapisuje się wyłącznie w pliku konfiguracji na tym komputerze — nie
   wysyłaj go mailem ani nie wpisuj nigdzie indziej.

Ponowne parowanie (np. po unieważnieniu tokenu w CRM) robi się tak samo — nowy token zastępuje stary.
Po parowaniu nowym tokenem agent bierze konfigurację z CRM; gdy CRM nie ma jeszcze żadnych drukarek dla
tego agenta (świeżo dodany agent), agent wysyła do CRM drukarki i godziny pracy, które zna z tego komputera.

## Drukarki

Konfigurację drukarek (adres IP, port, odczyt stanu, limit wysyłki, przesunięcia wydruku, godziny
pracy) ustawia się w CRM w zakładce Drukarki albo w okienku agenta, zakładka **Konfiguracja**.
Obie strony synchronizują się same — zmiana z okienka trafia do CRM przy najbliższym kontakcie.

- Drukarka etykiet odpowiada na SNMP — wybierz odczyt stanu „snmp”: agent widzi brak etykiet,
  otwartą klapę i pauzę i nie wysyła wtedy zadań.
- Drukarka paczek nie odpowiada na SNMP — wybierz „brak”; jej stan to wynik ostatniego wydruku.
- Po wymianie rolki albo innego rozmiaru etykiet użyj **Kalibruj** w okienku (albo w CRM).
  **Wydruk próbny** sprawdza przesunięcia bez kolejki CRM.

Poza godzinami pracy z konfiguracji agent nie pobiera zadań (wysyła tylko zaległe wyniki i raz na
minutę melduje się w CRM). Ikona jest wtedy żółta z komunikatem „Poza godzinami pracy (…) — etykiety
czekają w kolejce”.

**Znane ograniczenie — co znaczy „wydrukowane”.** Agent oznacza etykietę jako wydrukowaną, gdy drukarka
przyjęła wszystkie dane do swojego bufora (połączenie zamknięte poprawnie). Drukarka nie potwierdza, że
etykieta fizycznie wyszła. Zacięta drukarka, która nie zrywa połączenia, przyjmie dane — w CRM etykieta
będzie „wydrukowane”, a wyjdzie dopiero po odblokowaniu drukarki (czasem w innej kolejności niż reszta).
Po usunięciu zacięcia sprawdź więc etykiety z tego okresu, zanim klikniesz „Ponów”.

## Aktualizacja

Gdy w CRM jest nowsza wersja agenta, w okienku pojawia się pasek **Dostępna aktualizacja** z
przyciskiem **Aktualizuj**. Bez kliknięcia nic się nie dzieje. Po kliknięciu usługa:

1. pobiera instalator z CRM (tylko z adresu serwera, z którym jest sparowana),
2. sprawdza rozmiar i sumę SHA-256 z CRM — przy niezgodności usuwa plik i pokazuje błąd,
3. uruchamia instalator po cichu. Ikona zamyka się na czas instalacji i wraca sama po jej końcu
   (do około minuty), usługa wstaje już w nowej wersji.

Jeśli instalacja padnie, zanim podmieni pliki (np. nie da się zatrzymać usługi), stara wersja
zostaje i działa dalej. Błąd w trakcie kopiowania plików może zostawić mieszankę starej i nowej
wersji — wtedy zainstaluj agenta ponownie z pliku setup. Pasek w okienku pokazuje błąd (i pozwala
spróbować jeszcze raz) tylko wtedy, gdy instalator nie zatrzymał usługi; pozostałe błędy są w logu
instalatora: `%ProgramData%\WoodPower\AgentDruku\aktualizacje\instalacja.log`.
Jeśli ikona nie wróci, uruchom ją z menu Start: **WoodPower → Agent druku**.

## Diagnostyka

- Okienko → **Otwórz log**: ostatnie 500 linii logu usługi.
- Logi na dysku: `%ProgramData%\WoodPower\AgentDruku\logi\` — `agent_druku.log` (program)
  i `AgentDrukuUsluga.*.log` (WinSW); każdy rotowany 5 × 1 MB.
- Stan usługi: `sc query WoodPowerAgentDruku` (powinno być `RUNNING`). Restart z wiersza poleceń
  administratora: `"C:\Program Files\WoodPower\AgentDruku\AgentDrukuUsluga.exe" restart`.
- Odczyt drukarek (wiersz poleceń administratora):
  `"C:\Program Files\WoodPower\AgentDruku\AgentDruku.exe" diagnoza` — pokazuje konfigurację,
  połączenie TCP z każdą drukarką i odpowiedź SNMP.
- Czerwona ikona z „Usługa agenta nie działa” — usługa stoi; sprawdź `sc query`, logi WinSW
  i uruchom ją ponownie.

## Odinstalowanie

Panel sterowania → Programy → **WoodPower Agent druku** → Odinstaluj. Usługa zostaje zatrzymana
i usunięta, ikona zamknięta i usunięta z autostartu. Katalog danych
`%ProgramData%\WoodPower\AgentDruku\` **zostaje** (konfiguracja, token, dziennik). Instalacja
na komputerze bez usługi agenta (także po odinstalowaniu) przenosi zastany katalog
`%ProgramData%\WoodPower` na bok (`WoodPower.przed-instalacja-<data>-<godzina>`) i zakłada go od nowa —
agenta trzeba wtedy sparować ponownie (dowiązanie w miejscu katalogu jest usuwane, jego cel zostaje
nietknięty). Przeniesiony katalog można skasować ręcznie jako administrator; unieważnij też w CRM
poprzedni token tego komputera (zakładka Drukarki → Agenci i wydania).

Uszkodzony plik konfiguracji, dziennika albo klucza lokalnego usługa przenosi na bok
(`<nazwa>.uszkodzony-<data>-<godzina>`, wpis CRITICAL w logu) i startuje z pustym stanem — po
uszkodzeniu konfiguracji agenta trzeba sparować ponownie.

## Budowanie instalatora (dla programisty)

Na Windows z Pythonem 3.12 (`py -3.12`) i Inno Setup 6:

1. Pobierz `WinSW-x64.exe` v2.12.0 z oficjalnych wydań projektu WinSW
   (https://github.com/winsw/winsw/releases/tag/v2.12.0) do `packaging\vendor\`. Plik nie jest
   w repo; skrypt sprawdza jego sumę SHA-256.
2. `powershell -ExecutionPolicy Bypass -File tools\agent_druku\packaging\zbuduj.ps1`

Skrypt zakłada `tools\agent_druku\.venv`, instaluje przypięte wersje z `requirements.txt`,
buduje `AgentDruku.exe` (PyInstaller, `packaging\agent_druku.spec`) i instalator
`packaging\wynik\AgentDruku-<wersja>-setup.exe` (`packaging\instalator.iss`). Wersja pochodzi
z `agent_druku/__init__.py` (`WERSJA`). Wyniki budowania nie trafiają do repo.

Testy (bez GUI, w kontenerze projektu): `pytest tests/agent_druku`.
