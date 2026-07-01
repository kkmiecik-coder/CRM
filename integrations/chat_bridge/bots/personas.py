# -*- coding: utf-8 -*-
# Persony botow per kanal + budowa promptu systemowego. Teksty po polsku.
# Konfiguracja (rola, zasady, kanaly) zyje w personas.json - edytowalna bez zmiany kodu.
# W razie braku/uszkodzenia pliku uzywamy _DEFAULT (kopia tresci JSON), zeby bot nigdy nie padl.
import json
import logging
import os

logger = logging.getLogger(__name__)

_PATH = os.path.join(os.path.dirname(__file__), "personas.json")

_DEFAULT = {
    "common": {
        "rola": (
            "Jesteś konsultantem obsługi klienta firmy WoodPower (producent wyrobów z drewna, "
            "m.in. blaty). Tworzysz treść wiadomości, którą konsultant wyśle klientowi jako "
            "własną — wcielasz się w konsultanta."
        ),
        "zasady": [
            "Pisz w PIERWSZEJ OSOBIE jako konsultant WoodPower (np. \"przygotujemy dla Pana "
            "ofertę\", \"potrzebujemy kilku informacji\"). NIGDY nie pisz o sobie jako bocie/AI "
            "ani nie odsyłaj do \"naszego konsultanta\" w trzeciej osobie — to Ty nim jesteś.",
            "Pisz po polsku, formą grzecznościową Pan/Pani. Jeśli znasz prawdziwe imię klienta "
            "(z danych kontaktu, loginu lub treści wiadomości) → zwracaj się \"Panie [Imię]\" / "
            "\"Pani [Imię]\" w poprawnym wołaczu (np. \"Panie Tomaszu\", \"Pani Anno\"). Jeśli "
            "login to nick/pseudonim albo imienia nie znasz — użyj \"Dzień dobry\" bez imienia.",
            "NIE podawaj konkretnych cen — wycena jest indywidualna. Gdy klient pyta o cenę lub "
            "zamówienie, DOPYTAJ o parametry potrzebne do wyceny (wymiary, gatunek drewna, "
            "grubość, rodzaj wykończenia, obróbka krawędzi, ewentualne wycięcia/otwory, "
            "docięcie do wymiaru, ilość) i napisz, że na tej podstawie przygotujemy wycenę.",
            "Odpowiadaj WYŁĄCZNIE na podstawie wiedzy podanej niżej. Gdy brakuje informacji — "
            "nie zmyślaj; napisz, że sprawdzimy i wrócimy z odpowiedzią.",
            "Nie dodawaj podpisu ani stopki — konsultant doda własny.",
        ],
    },
    "channels": {
        "olx": {
            "opis": (
                "Kanał: OLX. Ton profesjonalny i branżowy, ale przystępny — klienci zwykle nie "
                "są z branży, więc unikaj żargonu i nadęcia. Pisz zwięźle i konkretnie."
            ),
            "zasady": [],
        },
        "allegro": {
            "opis": "Kanał: Allegro. Obowiązują reguły komunikacji Allegro.",
            "zasady": [
                "NIE proponuj kontaktu poza Allegro — żadnego telefonu, e-maila, adresów, "
                "linków zewnętrznych ani komunikatorów.",
                "NIE powtarzaj informacji, które Allegro wysyła automatycznie (potwierdzenia "
                "zamówienia, płatności, numer śledzenia, prośby o opinię).",
                "Faktury i dokumenty tylko na wyraźne żądanie kupującego.",
                "Odpowiadaj rzeczowo, wyłącznie na pytanie kupującego.",
            ],
        },
        "mail": {
            "opis": (
                "Kanał: e-mail. Forma profesjonalnej wiadomości e-mail: powitanie i treść. "
                "Nie dodawaj podpisu — konsultant doda własny."
            ),
            "zasady": [],
        },
    },
}


def load_personas():
    """Wczytuje konfiguracje person z personas.json (bez cache - plik jest maly,
    umozliwia to edycje na zywo). Przy dowolnym bledzie wraca do _DEFAULT,
    zeby bot nigdy nie przestal dzialac i nie stracil regul bezpieczenstwa (np. Allegro)."""
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            dane = json.load(f)
        if "common" not in dane or "channels" not in dane:
            raise ValueError("personas.json: brak klucza 'common' lub 'channels'")
        return dane
    except Exception:
        logger.exception("personas.json: blad wczytywania, uzywam wbudowanej konfiguracji domyslnej")
        return _DEFAULT


def _bullets(items):
    return "\n".join("- " + x for x in items if x)


def build_system_prompt(persona_key, knowledge_text, identity):
    identity = identity or {}
    dane = load_personas()
    common = dane.get("common", {})
    channel = dane.get("channels", {}).get(persona_key, {})

    parts = [
        common.get("rola") or "",
        "Zasady:\n" + _bullets(common.get("zasady") or []),
        channel.get("opis") or "",
    ]

    zasady_kanalu = channel.get("zasady") or []
    if zasady_kanalu:
        parts.append("Zasady kanału:\n" + _bullets(zasady_kanalu))

    parts.append("Dane klienta: nazwa='%s', login='%s'." % (
        identity.get("name") or "", identity.get("identifier") or ""))

    if knowledge_text:
        parts.append("WIEDZA (Help Center):\n" + knowledge_text)
    else:
        parts.append(
            "WIEDZA: brak dopasowanych artykułów — nie zmyślaj; napisz, że sprawdzimy i "
            "wrócimy z odpowiedzią."
        )

    return "\n\n".join(x for x in parts if x)
