# Centrifugo — broker sygnałów realtime

Broker doręcza CRM-owym klientom sygnał „coś się zmieniło, przyjdź po dane".
Etap 1 (wdrożony 12.08.2026) budzi print-agenta na hubie biura; kanały
`station:*` są przygotowane pod etap 2 (tablety hali).

**Przez brokera nie idą dane.** Sygnał tylko usuwa czekanie — stan zawsze
przyjeżdża REST-em, a źródłem prawdy pozostaje baza. Padnięty broker nie psuje
niczego: klienci mają polling jako siatkę bezpieczeństwa i pracują dalej, tylko
wolniej. Ta cicha degradacja jest celem projektu, ale też jego pułapką — dlatego
nieudana publikacja zgłasza się do Sentry (`subsystem: realtime`).

## Co gdzie leży na produkcji

| Element | Ścieżka / wartość |
|---|---|
| Binarka | `/opt/centrifugo/centrifugo` (v6.9.1, checksum zweryfikowany przy instalacji) |
| Konfiguracja | `/etc/centrifugo/config.json` — chmod 600, `woodpower-crm` |
| Nasłuch | `127.0.0.1:8091` (nigdy publicznie) |
| Supervisor | `/etc/supervisor/conf.d/centrifugo.conf`, program `centrifugo` |
| Logi | `/var/log/centrifugo/centrifugo.log` (rotacja 10 MB × 3) |
| Wejście publiczne | `https://crm.woodpower.pl/realtime/` |
| Konfiguracja CRM | `config/core.json` → sekcja `REALTIME` |

Wzorce plików leżą w tym katalogu (`config.example.json`,
`supervisor-centrifugo.conf`, `nginx-realtime.conf`). **Sekrety nie są w repo** —
generowane na serwerze przez `openssl rand -hex 32`.

Dwa klucze muszą się zgadzać po obu stronach:

| Centrifugo | CRM (`core.json` → `REALTIME`) | Do czego |
|---|---|---|
| `http_api.key` | `api_key` | CRM publikuje sygnały |
| `client.token.hmac_secret_key` | `token_hmac_secret` | CRM podpisuje tokeny połączeniowe klientów |

## Dlaczego `/realtime/` na crm.woodpower.pl, a nie subdomena

Tablety hali mają zaszyte 3 piny certyfikatu SHA-256. Osobna subdomena =
osobny certyfikat = zerwany pinning i martwy kanał auto-update aplikacji.
Naprawa oznaczałaby fizyczny obchód sześciu tabletów z kablem USB.
**Nigdy nie przenoś tego na subdomenę.**

## Trwałość konfiguracji nginx (CloudPanel)

Wyrenderowany `/etc/nginx/sites-enabled/crm.woodpower.pl.conf` jest nadpisywany
przy każdym re-renderze CloudPanel — w tym **przy odnowieniu certyfikatu Let's
Encrypt**, czyli mniej więcej co 90 dni. Źródłem prawdy jest `site.vhost_template`
w sqlite `/home/clp/htdocs/app/data/db.sq3`.

Blok `/realtime/` został dopisany do OBU miejsc. Szablon w bazie ma **CRLF** —
przy ręcznej edycji trzeba to zachować. Sprawdzenie, czy przeżył:

```bash
sqlite3 /home/clp/htdocs/app/data/db.sq3 "select count(*) from site where domain_name='crm.woodpower.pl' and vhost_template like '%realtime%';"
```

Zwraca `1` = w porządku. Zwraca `0` = ktoś nadpisał szablon, push przestanie
działać przy najbliższym re-renderze.

## Rozruch i diagnostyka

```bash
supervisorctl status centrifugo
supervisorctl restart centrifugo
tail -f /var/log/centrifugo/centrifugo.log
```

Test publikacji (z serwera):

```bash
KEY=$(python3 -c "import json;print(json.load(open('/etc/centrifugo/config.json'))['http_api']['key'])")
curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"channel":"print:agent","data":{"kind":"print"}}' http://127.0.0.1:8091/api/publish
```

Odpowiedź `{"result":{}}` = przyjęte. Bez klucza musi być HTTP 401, a publiczne
`https://crm.woodpower.pl/realtime/api/publish` musi zwracać **403** — server API
nie ma prawa być wystawione na świat.

## Włączenie i wyłączenie sygnału

Przełącznik jest po stronie CRM, nie brokera:

```json
"REALTIME": { "enabled": true }
```

w `config/core.json`, potem `supervisorctl restart crm_woodpower`.
`enabled: false` = pełny rollback: CRM przestaje publikować, agent po sygnale
503 z `/api/print-agent/realtime-token` wraca do pollingu co 10 s. Brokera nie
trzeba przy tym ruszać.

## Dodanie kanału (etap 2)

Kanał musi należeć do zdefiniowanego namespace'u (`print` albo `station`) —
prefiks przed dwukropkiem. Nowy namespace = wpis w `channel.namespaces`
w `/etc/centrifugo/config.json` + `supervisorctl restart centrifugo`.
Klient unidirectional nie subskrybuje sam: kanały przyjeżdżają w claimie
`channels` tokenu JWT wystawianego przez CRM.
