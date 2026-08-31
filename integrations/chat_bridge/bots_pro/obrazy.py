# -*- coding: utf-8 -*-
"""
Zdjęcia klienta -> wejście multimodalne Agents SDK (U2).

Klienci WoodPower rutynowo przysyłają zdjęcia: pomieszczenie, szkic, wymiary
zapisane na kartce. Webhook `/agent-bot-pro` ŚWIADOMIE przyjmuje wiadomość BEZ
tekstu, gdy niesie obraz (`webhooks._process_pro`), a `prompty.ROLA` obiecuje
wprost „Obrazy od klienta to treść wyceny". Do tej poprawki `tura.uruchom`
przyjmowała `zalaczniki` wyłącznie w sygnaturze — model dostawał `''`, a obrazy
lądowały w koszu (regres wobec starego silnika, `bots/quotebot.py` ->
`bots.vision.attach_images`).

DWA zapożyczenia i jedna różnica wobec starego silnika:
  - pobieranie obrazu (token Chatwoota, limit rozmiaru, filtr po prawdziwym
    Content-Type, „nigdy nie rzuca") zostaje w `bots.vision.to_data_uri` —
    używamy go, NIE kopiujemy: to sprawdzony w produkcji kod, a duplikat
    rozjechałby się przy pierwszej zmianie limitu;
  - profil kanału decyduje o dozwolonych formatach (`image_formats` z
    `bots.channel_caps`) — OLX i Allegro czytają wyłącznie jpg/png, livechat
    bez ograniczenia;
  - RÓŻNICA: stary silnik składał wiadomość w formacie Chat Completions
    (`{"type": "image_url", "image_url": {"url": ...}}`), tutaj składamy
    KANONICZNY kształt wejścia Agents SDK (`input_text`/`input_image` z gołym
    stringiem w `image_url`). Adapter LiteLLM tłumaczy go z powrotem na format
    Chat Completions (`agents.models.chatcmpl_converter.Converter.
    extract_all_content`), więc inwariant przenośności OpenAI <-> Anthropic
    zostaje zachowany — to NIE jest funkcja wyłączna dla Responses API.

Ten moduł CELOWO nie importuje `agents` — buduje zwykłe słowniki, więc
`quote_worker` (i testy w wariancie „bez SDK") mogą go zaimportować bez
zainstalowanego SDK, tak jak `bots_pro.stan` i `bots_pro.wysylka`.
"""
import json

from bots.channel_caps import caps_for
from bots.vision import to_data_uri
from core.log import log

# Tyle samo, ile bierze stary silnik (`bots.vision.attach_images(limit=2)`):
# każdy obraz to kilkaset kB base64 w prompcie, a klienci potrafią wkleić serię.
LIMIT_OBRAZOW = 2

# Załącznika graficznego NIE dało się pobrać/odczytać. Model NIE MOŻE wtedy
# dostać pustego promptu (pusty prompt to cisza w rozmowie, czyli dokładnie ta
# awaria, którą U2 naprawia) ani udawać, że załącznika nie było — dostaje
# jednoznaczny opis sytuacji i może poprosić o ponowne przesłanie.
#
# N4 (rerecenzja gałęzi): ten opis idzie rolą "system", NIGDY "user". To
# wewnętrzna instrukcja, nie wypowiedź klienta, a trafia na stałe do
# `SQLiteSession` — w roli "user" model mógłby wziąć ją za prawdziwe pytanie i
# sparafrazować klientowi. Dokładnie ta sama klasa problemu i ta sama naprawa
# co przy komunikacie korekty guardraila (`tura._KOMUNIKAT_KOREKTY`, W2).
ZASTEPNIK_NIEODCZYTANEGO_OBRAZU = (
    "[Klient przysłał załącznik graficzny, którego nie udało się odczytać. "
    "Poproś o ponowne przesłanie zdjęcia albo o opisanie go słowami.]")

# C3 (runda D): wiadomość niosąca SAMO nieodczytane zdjęcie nie zostawiała
# ŻADNEJ pozycji roli "user" — wejście składało się wyłącznie z noty systemowej,
# a tor LiteLLM/Anthropic odrzuca takie żądanie twardym błędem („Anthropic
# requires at least one non-system message"), czyli wywala CAŁĄ turę. Na OpenAI
# błąd nie występował, więc awaria była widoczna tylko na jednym torze —
# a przenośność dostawcy jest wymogiem projektu (`bots_pro/models.py`).
#
# Marker jest rzeczowym OPISEM tego, co przyszło (wiadomość klienta bez tekstu),
# nie instrukcją i nie zmyśloną wypowiedzią — intencja N4 zostaje: instrukcja
# („poproś o ponowne przesłanie") idzie dalej rolą "system", więc model nie
# sparafrazuje jej klientowi jako jego własnego pytania.
MARKER_WIADOMOSCI_BEZ_TEKSTU = "[Wiadomość klienta bez tekstu — sam załącznik graficzny.]"


def _lista_url(zalaczniki):
    """Adresy załączników z kolumny kolejki. `quote_worker` podaje SUROWĄ
    wartość kolumny `attachments` — tekst JSON, nie listę — więc obie postacie
    muszą działać. Nieparsowalna zawartość to pusta lista, nigdy wyjątek:
    uszkodzony wiersz kolejki nie ma prawa wywalić tury."""
    if isinstance(zalaczniki, str):
        try:
            zalaczniki = json.loads(zalaczniki)
        except Exception:
            log("obrazy: nieparsowalna kolumna attachments — pomijam zalaczniki")
            return []
    if not isinstance(zalaczniki, (list, tuple)):
        return []
    return [u.strip() for u in zalaczniki if isinstance(u, str) and u.strip()]


def data_uri_obrazow(zalaczniki, persona, limit=LIMIT_OBRAZOW):
    """Lista `data:` URI obrazów gotowych do wysłania modelowi. Nieudane
    pobranie (błąd sieci, za duży plik, format spoza profilu kanału) po prostu
    wypada z listy — `to_data_uri` nigdy nie rzuca."""
    formaty = caps_for(persona).get("image_formats")
    uri = []
    for url in _lista_url(zalaczniki)[:limit]:
        pobrany = to_data_uri(url, formats=formaty)
        if pobrany:
            uri.append(pobrany)
    return uri


def wejscie(tresc, zalaczniki=None, persona="pro"):
    """Wejście dla `Runner.run_sync`: goły string albo lista pozycji wejściowych.

    Rozmowa BEZ zdjęć dostaje DOKŁADNIE to co dotąd — string — żeby zmiana nie
    dotykała ścieżki, którą chodzi większość ruchu (i żeby historia sesji SDK
    miała ten sam kształt co przed poprawką).

    N5 (rerecenzja gałęzi): KAŻDY nieodczytany załącznik zostawia ślad —
    zastępnik dla modelu i wpis w logu. Wcześniej ginął bez śladu, gdy
    wiadomość miała też tekst (gałąź `if not uri: if tekst: return tekst`):
    model odpowiadał tak, jakby zdjęcia nie było, na wiadomość, która się do
    niego odwołuje („tak jak na zdjęciu, ile taki kosztuje?"). Dotyczy to też
    niepowodzenia CZĘŚCIOWEGO (jedno zdjęcie z dwóch) — model ma wiedzieć, że
    czegoś nie widzi, zamiast odpowiadać z niepełnego materiału.

    C3 (runda D): zwrócona lista ZAWSZE ma pozycję roli "user" — wejście
    złożone wyłącznie z noty systemowej wywalało turę na torze Anthropica
    (patrz MARKER_WIADOMOSCI_BEZ_TEKSTU).
    """
    tekst = (tresc or "").strip()
    adresy = _lista_url(zalaczniki)[:LIMIT_OBRAZOW]
    if not adresy:
        return tekst

    uri = data_uri_obrazow(zalaczniki, persona)
    czesci = []
    if tekst:
        czesci.append({"type": "input_text", "text": tekst})
    czesci.extend({"type": "input_image", "image_url": u} for u in uri)

    if not czesci:
        # C3: wejście NIGDY nie może być puste ani złożone wyłącznie z roli
        # "system" — patrz komentarz przy MARKER_WIADOMOSCI_BEZ_TEKSTU.
        czesci.append({"type": "input_text", "text": MARKER_WIADOMOSCI_BEZ_TEKSTU})

    pozycje = [{"role": "user", "content": czesci}]
    if len(uri) < len(adresy):
        # Ślad dla człowieka czytającego logi ORAZ dla modelu (rola "system",
        # patrz ZASTEPNIK_NIEODCZYTANEGO_OBRAZU) — nie dla klienta.
        log("obrazy: %s z %s zalacznikow nie zostalo odczytanych — zastepnik dla modelu"
            % (len(adresy) - len(uri), len(adresy)))
        pozycje.append({"role": "system", "content": ZASTEPNIK_NIEODCZYTANEGO_OBRAZU})
    return pozycje
