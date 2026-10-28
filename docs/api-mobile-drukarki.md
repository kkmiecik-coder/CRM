# API mobilne — stan drukarek etykiet (baner na tabletach stanowisk)

## 0. Do kogo i na czym stoi ten dokument

Referencja dla aplikacji Android (`woodpower_prod_app` / `crm_prod_app` — ta sama appka). Opisuje jedną nową
końcówkę, `GET /api/mobile/printers/status`, i sygnał realtime, po którym appka ją odświeża. Sesja appki pracuje
wyłącznie z tego dokumentu.

Po co: nowy agent druku na hubie hali zna stan obu drukarek (brak etykiet, otwarta klapa, wstrzymanie, brak
połączenia). Tablet pokazuje to operatorowi banerem, zanim ten kliknie „Drukuj” i dowie się o problemie po fakcie.

Gdzie to stoi w kodzie CRM:

- końcówka — `modules/production/drukarki/routers/mobile_api.py` (`status`), blueprint `drukarki_mobile_bp` pod
  `/api/mobile/printers`;
- migawka stanu, teksty komunikatów, sygnał — `modules/production/drukarki/services/stan.py`;
- testy — `tests/test_drukarki_mobile.py`.

## 1. Najważniejsze w pięciu zdaniach

1. **Jedna końcówka, tylko odczyt:** `GET /api/mobile/printers/status`, autoryzacja jak każda inna końcówka API
   mobilnego (JWT urządzenia).
2. **Serwer filtruje po stanowisku urządzenia:** tablet Pakowania dostaje drukarkę paczek (`wysylka`) i — jeśli
   stanowisko jest na liście drukujących etykiety produktów — drukarkę etykiet; tablet Formatowania tylko etykiet;
   stanowisko bez drukarek dostaje `drukarki: []`.
3. **Baner pokazuj, gdy `stan` drukarki stanowiska jest inny niż `gotowa`;** tekst banera to gotowe pole `komunikat`.
4. **Odświeżanie:** odpytuj co 60 s oraz od razu po sygnale `{"kind":"printers"}` na kanale `station:<kod>`.
5. **Stary serwer (404) = brak banera,** bez błędu i bez ponawiania częściej niż co 60 s.

## 2. `GET /api/mobile/printers/status`

Nagłówki jak w pozostałych końcówkach: `Authorization: Bearer <JWT urządzenia>`, `X-App-Version`. Bez body. Odpowiedź
ma `Cache-Control: no-store` — nie cache'uj jej.

### 2.1 Odpowiedź 200 (przykład: tablet Pakowania)

```json
{
  "agent": {
    "online": true,
    "ostatni_kontakt": "2026-10-23T08:15:42.123456Z",
    "wersja": "2.0.0",
    "push": true
  },
  "drukarki": [
    {
      "nazwa": "wysylka",
      "rola": "Drukarka paczek 100×150",
      "stan": "brak_papieru",
      "komunikat": "Drukarka paczek: brak etykiet",
      "od": null,
      "obsluga": "nowy",
      "w_kolejce": 2,
      "dzis": 14
    }
  ]
}
```

| Pole | Typ | Znaczenie |
|---|---|---|
| `agent` | obiekt albo `null` | `null` = żaden agent druku nowej generacji nigdy się nie zgłosił |
| `agent.online` | bool | `false` = agent milczy dłużej niż 120 s (zegar serwera) |
| `agent.ostatni_kontakt` | tekst ISO 8601, UTC (`Z`) | ostatni kontakt agenta z serwerem |
| `agent.wersja` | tekst albo `null` | wersja agenta; tylko informacyjnie |
| `agent.push` | bool | agent ma połączenie push; tylko informacyjnie |
| `drukarki` | lista | drukarki widoczne dla stanowiska urządzenia; może być pusta |
| `drukarki[].nazwa` | tekst | `etykiety` (etykiety produktów 60×40) albo `wysylka` (etykiety paczek 100×150) |
| `drukarki[].rola` | tekst | opis do wyświetlenia w szczegółach |
| `drukarki[].stan` | tekst | jedna z wartości z sekcji 2.2 |
| `drukarki[].komunikat` | tekst | gotowy tekst banera; pusty przy `gotowa` |
| `drukarki[].od` | tekst ISO albo `null` | gdy agent milczy: czas jego ostatniego kontaktu; w pozostałych przypadkach `null` |
| `drukarki[].obsluga` | `"nowy"` | **przestarzałe** — od 28.10.2026 zawsze `"nowy"` (sekcja 5) |
| `drukarki[].w_kolejce` | liczba | zadania czekające na tę drukarkę (oczekujące, pobrane, w wysyłce) |
| `drukarki[].dzis` | liczba | etykiety wydrukowane dziś (doba lokalna, Europa/Warszawa) |

Pola, których appka nie zna, ignoruj.

### 2.2 Wartości `stan`, kolory i teksty banera

Baner pokazuj dla każdej drukarki z `drukarki`, której `stan` ≠ `gotowa`. Tekst = `komunikat` z odpowiedzi
(appka niczego nie tłumaczy ani nie składa sama).

| `stan` | Kolor banera | `komunikat` (drukarka paczek / etykiet) | Kiedy |
|---|---|---|---|
| `gotowa` | brak banera | pusty | drukarka działa |
| `brak_papieru` | żółty | `Drukarka paczek: brak etykiet` / `Drukarka etykiet: brak etykiet` | skończyły się etykiety |
| `otwarta_klapa` | żółty | `Drukarka paczek: otwarta klapa` / `Drukarka etykiet: otwarta klapa` | otwarta głowica |
| `pauza` | żółty | `Drukarka paczek: wstrzymana` / `Drukarka etykiet: wstrzymana` | drukarka wstrzymana |
| `offline` | czerwony | `Drukarka paczek: nie odpowiada` / `Drukarka etykiet: nie odpowiada` | agent nie łączy się z drukarką |
| `blad` | czerwony | `Drukarka paczek: błąd` / `Drukarka etykiet: błąd` | błąd drukarki |
| `nieznany` | czerwony | zależnie od przyczyny, patrz niżej | serwer nie zna stanu |

Dla `nieznany` pole `komunikat` ma jedną z trzech treści:

- `Agent druku nie odpowiada` — agent milczy dłużej niż 120 s (`agent.online = false`) albo żaden się nie zgłosił;
- `Drukarka paczek: agent druku jej nie obsługuje` / `Drukarka etykiet: agent druku jej nie obsługuje` — agent
  żyje, ale w ostatnim kontakcie w ogóle nie zgłosił tej drukarki (nie ma jej w swojej konfiguracji, więc nie
  pobiera jej etykiet);
- `Drukarka etykiet: stan nieznany` — agent zgłosił drukarkę, ale nie zna jej stanu.

Drukarka paczek (XP-410B) nie ma odczytu stanu: gdy żywy agent ją zgłosił, serwer uznaje ją za `gotowa`, dopóki
agent nie zgłosi `offline` (nieudane połączenie).

Gdy na stanowisku są dwie drukarki w stanie innym niż `gotowa`, pokaż oba banery (albo jeden zbiorczy z oboma
komunikatami). Kolor zbiorczego banera: czerwony, jeśli którykolwiek stan jest czerwony.

## 3. Sygnał realtime

Zmiana stanu drukarki (np. `gotowa` → `brak_papieru`, albo powrót agenta po ciszy) wysyła na kanał stanowisk
drukarki, `station:<kod>` (ten sam, na którym tablet słucha sygnałów stołu), ładunek:

```json
{"kind": "printers"}
```

Po takim sygnale appka **od razu** woła `GET /api/mobile/printers/status`. Sygnał nie niesie danych — źródłem prawdy
jest odpowiedź końcówki. Kanał `station:<kod>` dostaje też sygnały stołu (`{"kind": "station", ...}`); sygnał z
nieznanym `kind` appka może zignorować albo potraktować jak sygnał stołu — dodatkowe `GET desk` jest nieszkodliwe.
Tablety, które nie mają łączności realtime (broker wyłączony, `GET /api/mobile/realtime-token` zwraca 503), zostają
przy samym odpytywaniu.

## 4. Odpytywanie i błędy

- **Co 60 s** wołaj końcówkę na ekranach stanowiska, na których operator drukuje (lista zamówień, pakowanie), oraz
  zawsze po sygnale z sekcji 3 i po powrocie appki na pierwszy plan.
- **404** (serwer jeszcze bez tej końcówki): **bez banera**, bez komunikatu o błędzie. Spróbuj ponownie dopiero za
  60 s (albo po wznowieniu appki).
- **Brak sieci, timeout, 5xx:** zostaw ostatni znany baner (albo jego brak) i ponów za 60 s. Nie pokazuj banera
  „serwer nie odpowiada” z tej przyczyny — ten stan ma własną obsługę w appce.
- **401:** jak w każdej innej końcówce (obsługa tokenu i `reason` — `docs/api-mobile-urzadzenia.md`).
- **426 `app_version_too_old`:** jak w każdej innej końcówce.

Końcówka tylko czyta: nie zmienia stanu serwera (poza znacznikiem kontaktu urządzenia, który robi każda końcówka
API mobilnego), więc jest bezpieczna do ponawiania.

## 5. Pole `obsluga` (przestarzałe)

Okres przejściowy, w którym część drukarek obsługiwał jeszcze stary agent druku, skończył się 28.10.2026. Od tego
dnia wszystkie etykiety drukuje agent druku v2, a pole `obsluga` ma zawsze wartość `"nowy"`. Serwer wysyła je dalej
wyłącznie dla zgodności z appką napisaną według wcześniejszej wersji tego kontraktu; nowy kod appki nie powinien go
czytać.

## 6. Reguła dla appki w skrócie

```
dla d w odpowiedź.drukarki:
    jeśli d.stan == "gotowa": pomiń
    kolor = żółty dla brak_papieru | otwarta_klapa | pauza, czerwony dla offline | blad | nieznany
    pokaż baner z tekstem d.komunikat w tym kolorze
```
