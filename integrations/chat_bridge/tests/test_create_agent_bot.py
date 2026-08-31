# -*- coding: utf-8 -*-
"""
setup/create_agent_bot.py — wariant konfiguracji "pro" (Task 7) i idempotentna
aktualizacja outgoing_url istniejącego bota (PATCH przy rozjeździe).

Moduł wcześniej nie miał ŻADNYCH testów jednostkowych — dopisane przy okazji
zadania 7 (Dębuś Pro), żeby zmiany (parametryzowany opis, PATCH gdy outgoing_url
się rozjechał) miały pokrycie, a nie tylko ręczną weryfikację na produkcji.
"""
import os

os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")

import importlib

cab = importlib.import_module("setup.create_agent_bot")


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._p = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._p


class TestCfgPro:
    def test_domyslny_url_bez_tokenu(self, monkeypatch):
        monkeypatch.delenv("BOT_PRO_AGENT_WEBHOOK_TOKEN", raising=False)
        monkeypatch.delenv("BOT_PRO_AGENT_WEBHOOK_URL", raising=False)
        _, _, _, url = cab._cfg_pro()
        assert url == "https://chatbridge.woodpower.pl/agent-bot-pro"

    def test_dokleja_token_do_url(self, monkeypatch):
        monkeypatch.setenv("BOT_PRO_AGENT_WEBHOOK_TOKEN", "sekret-pro")
        monkeypatch.delenv("BOT_PRO_AGENT_WEBHOOK_URL", raising=False)
        _, _, _, url = cab._cfg_pro()
        assert url == "https://chatbridge.woodpower.pl/agent-bot-pro?token=sekret-pro"

    def test_wlasny_webhook_url_nadpisuje_domyslny(self, monkeypatch):
        monkeypatch.delenv("BOT_PRO_AGENT_WEBHOOK_TOKEN", raising=False)
        monkeypatch.setenv("BOT_PRO_AGENT_WEBHOOK_URL", "https://staging.example/agent-bot-pro")
        _, _, _, url = cab._cfg_pro()
        assert url == "https://staging.example/agent-bot-pro"


class TestEnsureAgentBotOpis:
    def test_domyslny_opis_gdy_nie_podano(self, monkeypatch):
        monkeypatch.setattr(cab, "list_agent_bots", lambda: [])
        zapisany = {}

        def _post(url, headers=None, json=None, timeout=None):
            zapisany.update(json)
            return _FakeResp({"id": 1, "access_token": "T"}, 201)

        monkeypatch.setattr(cab.requests, "post", _post)
        cab.ensure_agent_bot("Test Bot", outgoing_url="https://x/y")
        assert zapisany["description"] == "Asystent AI - podpowiedzi (prywatne notatki)"

    def test_wlasny_opis_dla_debusia_pro(self, monkeypatch):
        monkeypatch.setattr(cab, "list_agent_bots", lambda: [])
        zapisany = {}

        def _post(url, headers=None, json=None, timeout=None):
            zapisany.update(json)
            return _FakeResp({"id": 1, "access_token": "T"}, 201)

        monkeypatch.setattr(cab.requests, "post", _post)
        cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://x/pro",
                              description="opis Debusia Pro")
        assert zapisany["description"] == "opis Debusia Pro"


class TestEnsureAgentBotPatchOutgoingUrl:
    def test_istniejacy_bot_z_takim_samym_url_bez_patcha(self, monkeypatch):
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "Dębuś Pro", "outgoing_url": "https://x/pro"}])
        wolania_patch = []
        monkeypatch.setattr(cab.requests, "patch",
                            lambda *a, **k: wolania_patch.append(1) or _FakeResp({}))

        bot = cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://x/pro")

        assert wolania_patch == []
        assert bot["id"] == 9

    def test_istniejacy_bot_z_innym_url_dostaje_patch(self, monkeypatch):
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "Dębuś Pro", "outgoing_url": "https://STARY"}])
        wolania_patch = []

        def _patch(url, headers=None, json=None, timeout=None):
            wolania_patch.append((url, json))
            return _FakeResp({"id": 9, "outgoing_url": json["outgoing_url"]})

        monkeypatch.setattr(cab.requests, "patch", _patch)

        bot = cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://NOWY")

        assert len(wolania_patch) == 1
        assert wolania_patch[0][1] == {"outgoing_url": "https://NOWY"}
        assert bot["outgoing_url"] == "https://NOWY"

    def test_patch_bez_access_tokenu_w_odpowiedzi_nie_gubi_starego(self, monkeypatch):
        # Code review, drobne: odpowiedz PATCH Chatwoota nie musi zawierac WSZYSTKICH
        # pol bota (typowo zwraca tylko to, co sie zmienilo) — access_token ma
        # przetrwac SCALONY ze starym obiektem, inaczej CLI wypisaloby puste
        # "BOT_PRO_CW_AGENT_TOKEN=" mimo ze bot i jego token realnie istnieja.
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "Dębuś Pro", "outgoing_url": "https://STARY",
                      "access_token": "STARY-TOKEN"}])
        monkeypatch.setattr(
            cab.requests, "patch",
            lambda url, headers=None, json=None, timeout=None:
            _FakeResp({"id": 9, "outgoing_url": json["outgoing_url"]}))   # BEZ access_token

        bot = cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://NOWY")

        assert bot["outgoing_url"] == "https://NOWY"
        assert bot["access_token"] == "STARY-TOKEN"

    def test_patch_nieudany_zwraca_stary_obiekt_bota(self, monkeypatch):
        # Blad PATCH nie ma wywalic calego skryptu — fallback na stary, ale wciaz
        # uzywalny obiekt bota (ma access_token do wypisania).
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "Dębuś Pro", "outgoing_url": "https://STARY",
                      "access_token": "STARY-TOKEN"}])
        monkeypatch.setattr(cab.requests, "patch",
                            lambda *a, **k: _FakeResp({}, status_code=500))

        bot = cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://NOWY")

        assert bot["access_token"] == "STARY-TOKEN"

    def test_patch_nie_zdejmuje_tokenu_z_url_istniejacego_bota(self, monkeypatch):
        """U12 (recenzja końcowa): `ensure_agent_bot` zaczęło PATCHować
        `outgoing_url` istniejących botów. Uruchomienie skryptu w powłoce BEZ
        `BOT_*_AGENT_WEBHOOK_TOKEN` (typowe: `docker exec` bez pliku env, ręczne
        odpalenie „żeby sprawdzić, czy bot istnieje") wylicza URL BEZ `?token=`
        i nadpisuje nim działający adres z tokenem. Efekt: webhooks.py zaczyna
        zwracać 401 i STARY bot cicho przestaje działać na produkcji."""
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "WoodPower AI", "access_token": "T",
                      "outgoing_url": "https://x/agent-bot?token=SEKRET"}])
        wolania_patch = []
        monkeypatch.setattr(cab.requests, "patch",
                            lambda *a, **k: wolania_patch.append(1) or _FakeResp({}))

        bot = cab.ensure_agent_bot("WoodPower AI", outgoing_url="https://x/agent-bot")

        assert wolania_patch == []
        assert bot["outgoing_url"] == "https://x/agent-bot?token=SEKRET"

    def test_patch_z_tokenem_na_token_dziala_normalnie(self, monkeypatch):
        # Kontrola negatywna: realny powod istnienia PATCHa — token zmieniony w
        # bridge.env — ma nadal dzialac. Blokujemy WYLACZNIE utrate tokenu.
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "WoodPower AI",
                      "outgoing_url": "https://x/agent-bot?token=STARY"}])
        wolania_patch = []

        def _patch(url, headers=None, json=None, timeout=None):
            wolania_patch.append(json)
            return _FakeResp({"id": 9, "outgoing_url": json["outgoing_url"]})

        monkeypatch.setattr(cab.requests, "patch", _patch)

        bot = cab.ensure_agent_bot("WoodPower AI",
                                   outgoing_url="https://x/agent-bot?token=NOWY")

        assert wolania_patch == [{"outgoing_url": "https://x/agent-bot?token=NOWY"}]
        assert bot["outgoing_url"] == "https://x/agent-bot?token=NOWY"

    def test_bot_bez_tokenu_w_url_nadal_da_sie_zaktualizowac(self, monkeypatch):
        # Bot zalozony kiedys bez tokenu — dopisanie tokenu to poprawa, nie utrata.
        monkeypatch.setattr(
            cab, "list_agent_bots",
            lambda: [{"id": 9, "name": "WoodPower AI", "outgoing_url": "https://x/agent-bot"}])
        wolania_patch = []
        monkeypatch.setattr(
            cab.requests, "patch",
            lambda url, headers=None, json=None, timeout=None:
            wolania_patch.append(json) or _FakeResp({"id": 9,
                                                     "outgoing_url": json["outgoing_url"]}))

        cab.ensure_agent_bot("WoodPower AI", outgoing_url="https://x/agent-bot?token=NOWY")

        assert wolania_patch == [{"outgoing_url": "https://x/agent-bot?token=NOWY"}]

    def test_nowy_bot_nie_wola_patcha(self, monkeypatch):
        monkeypatch.setattr(cab, "list_agent_bots", lambda: [])
        wolania_patch = []
        monkeypatch.setattr(cab.requests, "patch",
                            lambda *a, **k: wolania_patch.append(1) or _FakeResp({}))
        monkeypatch.setattr(cab.requests, "post",
                            lambda *a, **k: _FakeResp({"id": 1, "access_token": "T"}, 201))

        cab.ensure_agent_bot("Dębuś Pro", outgoing_url="https://x/pro")

        assert wolania_patch == []


class TestWalidacjaArgumentu:
    """W3: nieznany argument (literówka, albo naturalne `cand` przy wdrażaniu
    kandydata) spadał po cichu do gałęzi domyślnej i ruszał PRODUKCYJNEGO bota
    „WoodPower AI". A ponieważ `ensure_agent_bot` PATCHuje `outgoing_url` przy
    różnicy, pomyłka przy zakładaniu bota kandydata mogła przestawić webhook
    żywego bota na produkcji. Nieznany argument ma być twardym błędem."""

    def _bez_sieci(self, monkeypatch):
        wywolania = []
        monkeypatch.setattr(cab, "ensure_agent_bot",
                            lambda name="WoodPower AI", outgoing_url=None, description=None:
                            wywolania.append(name) or {"id": 1, "access_token": "T"})
        return wywolania

    def test_nieznany_argument_konczy_sie_kodem_2(self, monkeypatch, capsys):
        wywolania = self._bez_sieci(monkeypatch)
        assert cab.main(["cand"]) == 2
        assert wywolania == [], "nieznany argument NIE MOZE ruszyc zadnego bota"
        assert "cand" in capsys.readouterr().err

    def test_literowka_w_znanym_wariancie_tez_jest_bledem(self, monkeypatch):
        wywolania = self._bez_sieci(monkeypatch)
        for zly in ("Pro", "PRO", "quotes", "pro ", "--pro"):
            assert cab.main([zly]) == 2, zly
        assert wywolania == []

    def test_brak_argumentu_to_jedyna_droga_do_galezi_domyslnej(self, monkeypatch):
        wywolania = self._bez_sieci(monkeypatch)
        assert cab.main([]) == 0
        assert wywolania == ["WoodPower AI"]

    def test_znane_warianty_dzialaja_dalej(self, monkeypatch):
        wywolania = self._bez_sieci(monkeypatch)
        assert cab.main(["quote"]) == 0
        assert cab.main(["pro"]) == 0
        assert wywolania[0] == "Asystent AI v1"
        assert len(wywolania) == 2


class TestNazwaBotaPro:
    """W4: nazwa bota wariantu „pro" była zaszyta w kodzie, więc bota kandydata
    nie dało się założyć pod własną nazwą bez edycji pliku — a nazwa jest
    JEDYNYM kluczem idempotencji w `ensure_agent_bot`, więc zaszyta nazwa
    oznaczała, że kandydat i produkcja celowałyby w TEN SAM byt w Chatwoocie."""

    def _przechwyc(self, monkeypatch):
        wywolania = []
        monkeypatch.setattr(cab, "ensure_agent_bot",
                            lambda name="WoodPower AI", outgoing_url=None, description=None:
                            wywolania.append(name) or {"id": 1, "access_token": "T"})
        return wywolania

    def test_domyslna_nazwa_bez_zmiennej(self, monkeypatch):
        monkeypatch.delenv("BOT_PRO_NAME", raising=False)
        wywolania = self._przechwyc(monkeypatch)
        cab.main(["pro"])
        assert wywolania == ["Dębuś Pro"]

    def test_wlasna_nazwa_ze_zmiennej_srodowiskowej(self, monkeypatch):
        monkeypatch.setenv("BOT_PRO_NAME", "Debus Pro KANDYDAT (staging)")
        wywolania = self._przechwyc(monkeypatch)
        cab.main(["pro"])
        assert wywolania == ["Debus Pro KANDYDAT (staging)"]

    def test_pusta_zmienna_wraca_do_domyslnej(self, monkeypatch):
        # Pusta nazwa nie ma sensu jako klucz idempotencji — lepiej domyslna
        # niz proba zalozenia bota bez nazwy.
        monkeypatch.setenv("BOT_PRO_NAME", "   ")
        wywolania = self._przechwyc(monkeypatch)
        cab.main(["pro"])
        assert wywolania == ["Dębuś Pro"]
