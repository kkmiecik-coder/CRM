# -*- coding: utf-8 -*-
# Stopki doklejane do wiadomosci WYCHODZACYCH na OLX/Allegro.
# Most dokleja je przy wysylce (worker) WYLACZNIE do wiadomosci agenta-czlowieka
# (sender.type == "user" w webhooku) — automatyczne powitania ich NIE dostaja.
# Mail ma wlasny natywny podpis Chatwoota i tutaj sie NIE pojawia.
#
# Placeholder {agent} podmieniany jest na imie i nazwisko agenta z webhooka (sender.name).
# Modul jest czysty (bez I/O i zaleznosci od env) — latwy do testowania.

# OLX: pelniejsza stopka z adresem firmy.
FOOTER_OLX = (
    "Pozdrawiam,\n"
    "{agent}\n"
    "Dział Obsługi Klienta\n\n"
    "Wood Power Sp. z o.o.\n"
    "Bachórz 14N,\n"
    "36-068 Bachórz\n"
    "woodpower.pl"
)

# Allegro: krotsza stopka (bez adresu) — wspolna dla wiadomosci i dyskusji/reklamacji.
FOOTER_ALLEGRO = (
    "Pozdrawiam,\n"
    "{agent}\n"
    "Dział Obsługi Klienta\n"
    "Wood Power Sp. z o.o."
)

# Kanal (z tabeli threads) -> szablon stopki.
_FOOTER_BY_CHANNEL = {
    "olx": FOOTER_OLX,
    "allegro_msg": FOOTER_ALLEGRO,
    "allegro_dispute": FOOTER_ALLEGRO,
}

# Fallback gdy webhook nie poda imienia (nie powinno sie zdarzyc dla agenta).
_DEFAULT_AGENT = "Zespół WoodPower"


def build_footer(channel, agent_name):
    """Zwraca tekst stopki dla danego kanalu z podstawionym imieniem agenta,
    albo "" gdy kanal nie ma stopki (np. mail/czat)."""
    tmpl = _FOOTER_BY_CHANNEL.get(channel)
    if not tmpl:
        return ""
    name = (agent_name or "").strip() or _DEFAULT_AGENT
    return tmpl.replace("{agent}", name)
