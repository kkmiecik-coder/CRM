# -*- coding: utf-8 -*-
# Resolver persony bota: inbox_id -> klucz persony ("mail", "olx", "allegro") lub None.
# Katalog inboxow pobierany z Chatwoot Application API i przechowywany w pamieci z TTL.
import time
from core.chatwoot import cw_inboxes

# Czas waznosci cache'u katalogu inboxow (sekundy)
_TTL = 300.0

# Wewnetrzny cache: str(inbox_id) -> {"name": str, "channel_type": str}
_CACHE: dict = {}
_CACHE_TS: float = 0.0


def get_catalog(force: bool = False) -> dict:
    """Zwraca slownik str(id) -> {name, channel_type}; odswiezenie po wygasnieciu TTL lub force."""
    global _CACHE, _CACHE_TS
    now = time.time()
    # Odswiezamy gdy: pusty, wygasl TTL lub wymuszone
    if force or not _CACHE or (now - _CACHE_TS) >= _TTL:
        inboxes = cw_inboxes()
        new_cache = {}
        for i in inboxes:
            iid = i.get("id")
            if iid is not None:
                new_cache[str(iid)] = {
                    "name": i.get("name") or "",
                    "channel_type": i.get("channel_type") or "",
                }
        _CACHE = new_cache
        _CACHE_TS = now
    return _CACHE


def persona_for(inbox_id) -> "str | None":
    """
    Zwraca klucz persony dla danego inbox_id lub None gdy typ kanalu nieobslugiwany.
    Tier 1 — typ kanalu:
        Channel::Email        -> "mail" (dowolna skrzynka mailowa)
        Channel::WebWidget    -> "livechat" (konwersacyjny bot na stronie)
        Channel::FacebookPage -> "livechat" (Messenger — ten sam bot konwersacyjny, np. reklamy click-to-Messenger)
        Channel::Api          -> tier 2 po nazwie inboxu
        inne typy             -> None
    Tier 2 — nazwa inboxu (tylko Channel::Api):
        zawiera "allegro" -> "allegro"  (sprawdzane PIERWSZE — restrykcyjna wygrywa)
        zawiera "olx"     -> "olx"
        inaczej           -> None
    Gdy inbox_id nie ma w katalogu: proba force-refresh raz.
    """
    cat = get_catalog()
    info = cat.get(str(inbox_id))
    if info is None:
        # Nieznany inbox — odswiezamy katalog jeden raz
        cat = get_catalog(force=True)
        info = cat.get(str(inbox_id))
    if not info:
        return None
    ctype = info.get("channel_type") or ""
    if ctype == "Channel::Email":
        return "mail"
    if ctype == "Channel::WebWidget":
        # Live chat na stronie — konwersacyjny bot (osobna sciezka, nie podpowiadacz)
        return "livechat"
    if ctype == "Channel::FacebookPage":
        # Messenger (m.in. reklamy click-to-Messenger) — ten sam konwersacyjny bot co live chat
        return "livechat"
    if ctype == "Channel::Api":
        name = (info.get("name") or "").lower()
        # "allegro" sprawdzane PRZED "olx" — restrykcyjna persona wygrywa przy niejasnosci
        if "allegro" in name:
            return "allegro"
        if "olx" in name:
            return "olx"
        return None
    return None
