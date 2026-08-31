# -*- coding: utf-8 -*-
"""
Obrazy wysyłane KLIENTOWI (P2, runda napraw 4).

Odwrotny kierunek niż `bots_pro/obrazy.py` (tamten bierze ZDJĘCIA OD KLIENTA
i robi z nich wejście multimodalne). Tutaj wychodzą nasze stałe materiały
poglądowe: próbka gatunków, schemat wymiarów, schemat krawędzi, wzornik kolorów.

REGRES, KTÓRY TO ZAMYKA: stary silnik wysyła je od dawna — `bots/livechat.py`
(obraz semantyczny wybrany przez model, `images.resolve`) i `bots/quotebot.py`
(`_obrazy_kontekstowe`, dobierane deterministycznie). Dębuś Pro nie miał tej
ścieżki wcale, choć oba potrzebne kawałki już istniały: transport
(`core.chatwoot.cw_agent_reply` przyjmuje `image_path`/`image_name`/`image_mime`)
i biała lista plików (`bots/images.py`). Brakowało wyłącznie wyjścia po stronie
Pro — i ono jest w tym module.

CO JEST TU ŚWIADOMIE INACZEJ NIŻ W STARYM SILNIKU:

  - ZAMKNIĘTA LISTA CZTERECH IDENTYFIKATORÓW. Stary silnik ma dwa mechanizmy:
    whitelistę semantyczną (`IMAGES`, model podaje tag) i próbki dobierane
    z konwencji nazwy pliku `{gatunek}_{technologia}_{klasa}_{wykończenie}.jpg`
    (`images.resolve_sample`). Te drugie wymagają KOMPLETNEJ konfiguracji
    pozycji, więc dla klienta niezdecydowanego — czyli dla przypadku, dla
    którego ta runda powstała — i tak nie zadziałałyby. Zostawiamy je poza
    zakresem; gdyby kiedyś weszły, mają wejść jako osobna ścieżka
    DETERMINISTYCZNA (jak w quotebocie), nie jako kolejny identyfikator do
    wyboru przez model.

  - PODPIS SKŁADA KOD, NIE MODEL. To nie jest kosmetyka: treść wysłana
    z wnętrza narzędzia NIE przechodzi przez guardrail cenowy G1 — `tura.py`
    ogląda wyłącznie `final_output` modelu. Gdyby podpis pisał model, miałby
    kanał wyjścia omijający jedyny mechanizm chroniący przed zmyśloną ceną.
    Ten sam powód, dla którego treść podsumowania składa `podsumowanie.wyslij`.

  - PROFIL KANAŁU JEST SPRAWDZANY TUTAJ. Docstring `bots_pro/wysylka.py`
    zapowiadał to wprost: „Gdy taka ścieżka powstanie, ma sprawdzać te flagi
    SAMA". Sprawdzamy `images` (czy kanał w ogóle przyjmuje obrazy) i
    `image_formats` (jakie rozszerzenia). Sam PODPIS idzie przez
    `wysylka.przygotuj`, żeby profil tekstowy (emoji, markdown, limit długości)
    egzekwowało dalej jedno miejsce — podpisy z `bots/images.py` niosą emoji 👇,
    a OLX i Allegro emoji nie renderują.

CZEGO TU NIE MA: dedupu „raz na rozmowę". Stary silnik księguje wysłane obrazy
w kolumnie `sent_images`, której `stan.init_pro()` świadomie NIE ma (przebieg
rozmowy odtwarza sesja Agents SDK — model widzi własne wcześniejsze wywołania
narzędzi i nie ma powodu powtarzać obrazka). Liczba wywołań w jednej turze jest
ograniczona przez `BOT_PRO_MAX_RUNNER_STEPS`, więc najgorszy przypadek to ten
sam obrazek dwa razy pod rząd, nie pętla.

NIGDY NIE RZUCA: obraz nie może wywrócić tury (zasada mostka, ta sama co
w `bots/images.py`). Każde niepowodzenie wraca do modelu jako `{"ok": False,
"error": ...}` ze wskazówką, co zrobić zamiast tego.
"""
import os

from bots import images
from bots.channel_caps import caps_for
from config import BOT_PRO_CW_AGENT_TOKEN
from core.chatwoot import cw_agent_reply
from core.log import log

from bots_pro import wysylka

# Zamknięta biała lista. Kolejność = kolejność w opisie narzędzia. Klucze są
# kluczami z `bots/images.py` (`IMAGES` + `CONTEXT_IMAGES`) — modułu, którego
# w tej rundzie NIE WOLNO zmieniać, więc to on jest źródłem prawdy dla nazw
# plików, MIME i podpisów. Sonda spójności:
# test_pro_obrazy_do_klienta.py::test_kazdy_identyfikator_wskazuje_wpis_w_bots_images.
OBRAZY_DLA_KLIENTA = ("gatunki_porownanie", "wymiary", "krawedzie", "kolory")

# `CONTEXT_IMAGES` mają w `bots/images.py` gotowe `podpis`. `IMAGES` mają tylko
# `opis` — napisany dla whitelisty w PROMPCIE starego silnika ("dąb, buk i jesion
# (lite, surowe) obok siebie — różnice w usłojeniu i kolorze"), czyli tekst dla
# modelu, nie dla klienta. Podpis dla klienta piszemy więc tutaj; `bots/images.py`
# zostaje nietknięty.
_PODPISY_WLASNE = {
    "gatunki_porownanie": ("Dąb, buk i jesion obok siebie — lite, surowe. "
                           "Widać różnice w usłojeniu i kolorze 👇"),
}


def _meta(identyfikator):
    """(ścieżka, nazwa pliku, MIME, podpis) albo None.

    None znaczy „nie ma czego wysłać" i obejmuje OBA powody: identyfikator spoza
    białej listy oraz brakujący plik na dysku. Rozróżnia je `wyslij()` — modelowi
    mówią co innego."""
    if identyfikator not in OBRAZY_DLA_KLIENTA:
        return None
    if identyfikator in images.CONTEXT_IMAGES:
        wpis = images.CONTEXT_IMAGES[identyfikator]
        sciezka = images.resolve_context(identyfikator)
        podpis = wpis.get("podpis")
    else:
        wpis = images.IMAGES[identyfikator]
        sciezka = images.resolve(identyfikator)
        podpis = _PODPISY_WLASNE.get(identyfikator)
    if not sciezka or not podpis:
        return None
    return (sciezka, wpis["nazwa"], wpis["mime"], podpis)


def _format_dozwolony(sciezka, caps):
    """Czy rozszerzenie pliku mieści się w `image_formats` profilu kanału.

    None/pusta lista = bez ograniczenia (DEFAULT_CAPS, livechat). Porównujemy
    ROZSZERZENIE pliku, nie MIME — `image_formats` w `bots/channel_caps.py` jest
    zdefiniowane właśnie jako rozszerzenia ('jpg', 'jpeg', 'png')."""
    dozwolone = caps.get("image_formats")
    if not dozwolone:
        return True
    rozszerzenie = os.path.splitext(sciezka)[1].lstrip(".").lower()
    return rozszerzenie in tuple(str(f).lower() for f in dozwolone)


def wyslij(identyfikator):
    """Wysyła jeden obraz z białej listy razem z jego podpisem.

    Kolejność sprawdzeń jest istotna: NAJPIERW biała lista i profil kanału
    (rzeczy, o których wiemy bez dotykania dysku i sieci), POTEM plik. Dzięki
    temu nieznany identyfikator na kanale bez obrazów dostaje komunikat o tym,
    co model naprawdę zrobił źle."""
    from bots_pro import stan

    if identyfikator not in OBRAZY_DLA_KLIENTA:
        log("obrazy_do_klienta: nieznany identyfikator %r (conv %s)"
            % (identyfikator, stan.conv_id()))
        return {"ok": False, "error": "NIEZNANY_OBRAZ",
                "wskazowka": "Takiego obrazu nie mamy — wolno wysłać wyłącznie: "
                             + ", ".join(OBRAZY_DLA_KLIENTA)
                             + ". Opisz rzecz słowami albo wybierz z tej listy."}

    caps = caps_for(stan.persona())
    if not caps.get("images", True):
        return {"ok": False, "error": "KANAL_BEZ_OBRAZOW",
                "wskazowka": "Ten kanał nie przyjmuje obrazów — opisz rzecz słowami "
                             "i nie zapowiadaj klientowi żadnego zdjęcia."}

    meta = _meta(identyfikator)
    if not meta:
        # Plik zniknął z `assets/bot_images` (albo BOT_IMAGES_DIR wskazuje gdzie
        # indziej). Samego PODPISU nie wysyłamy: „proszę wskazać odcień 👇" bez
        # wzornika jest gorsze niż milczenie — klient szuka obrazka, którego nie
        # ma. To jest ta sama decyzja co w `cw_agent_reply`, ale przeciwna:
        # tamten przy nieczytelnym pliku ROBI fallback do samego tekstu, więc
        # bez tej bramki cichy brak pliku wyglądałby dla klienta jak awaria
        # wyświetlania, a dla modelu jak sukces.
        log("obrazy_do_klienta: brak pliku dla %r (conv %s)"
            % (identyfikator, stan.conv_id()))
        return {"ok": False, "error": "BRAK_PLIKU",
                "wskazowka": "Tego obrazu chwilowo nie ma — opisz rzecz słowami "
                             "i nie zapowiadaj klientowi zdjęcia."}

    sciezka, nazwa, mime, podpis = meta
    if not _format_dozwolony(sciezka, caps):
        return {"ok": False, "error": "FORMAT_NIEDOZWOLONY",
                "wskazowka": "Ten kanał nie przyjmuje tego formatu pliku — opisz "
                             "rzecz słowami i nie zapowiadaj klientowi zdjęcia."}

    # Podpis przez `wysylka.przygotuj`: profil TEKSTOWY kanału (emoji, markdown,
    # limit długości) ma być egzekwowany w jednym miejscu. Podpisy są krótkie,
    # więc lista jest w praktyce jednoelementowa — ale gdyby kanał miał bardzo
    # niski `max_len`, obraz jedzie z PIERWSZĄ częścią, a reszta osobno.
    czesci = wysylka.przygotuj(podpis, stan.persona()) or [""]
    if not cw_agent_reply(stan.conv_id(), czesci[0], image_path=sciezka,
                          image_name=nazwa, image_mime=mime,
                          token=BOT_PRO_CW_AGENT_TOKEN):
        # `cw_agent_reply` NIGDY nie rzuca — przy 429/5xx/timeoucie zwraca False.
        # Meldowanie sukcesu na podstawie „nie wywaliło się" było już raz błędem
        # (U1 w `podsumowanie.wyslij`), więc wynik jest sprawdzany.
        return {"ok": False, "error": "WYSYLKA_NIEUDANA",
                "wskazowka": "Obraz nie dotarł do klienta. Nie pisz, że go wysłałeś "
                             "— opisz rzecz słowami albo spróbuj w kolejnej turze."}
    for czesc in czesci[1:]:
        cw_agent_reply(stan.conv_id(), czesc, token=BOT_PRO_CW_AGENT_TOKEN)

    return {"ok": True, "wyslano": identyfikator,
            "wskazowka": "Obraz poszedł do klienta razem z podpisem — nie opisuj go "
                         "jeszcze raz i nie powtarzaj podpisu własnymi słowami."}
