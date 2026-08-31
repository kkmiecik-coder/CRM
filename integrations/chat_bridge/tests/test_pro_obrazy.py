# -*- coding: utf-8 -*-
"""
U2: zdjęcia klienta jako wejście multimodalne Dębusia Pro.

Klienci WoodPower rutynowo przysyłają zdjęcia (pomieszczenie, szkic, wymiary na
kartce), a webhook `/agent-bot-pro` ŚWIADOMIE przyjmuje wiadomość BEZ tekstu, gdy
ma obraz (`webhooks._process_pro`). Przed tą poprawką `tura.uruchom` miała
`zalaczniki` wyłącznie w sygnaturze — model dostawał pusty string, a obrazy szły
do kosza (regres wobec `bots/vision.py` w starym silniku).

Ten plik NIE wymaga SDK — `bots_pro.obrazy` buduje zwykłe słowniki (kanoniczny
kształt wejścia Agents SDK: `input_text`/`input_image`), więc da się go
przetestować także w wariancie „bez SDK".
"""
import json

import pytest

from bots_pro import obrazy


class _Pobieracz:
    """Atrapa `bots.vision.to_data_uri` — zapamiętuje, o co pytano, i zwraca
    ustalone wyniki (None = nieudane pobranie/odrzucony format)."""

    def __init__(self, wyniki=None):
        self._wyniki = dict(wyniki or {})
        self.wywolania = []

    def __call__(self, url, formats=None):
        self.wywolania.append((url, formats))
        return self._wyniki.get(url, "data:image/jpeg;base64,AAA")


class TestParsowanieZalacznikow:
    def test_lista_json_ze_stringa_kolejki(self, monkeypatch):
        # quote_worker podaje SUROWĄ kolumnę `attachments` (tekst JSON), nie listę.
        pobieracz = _Pobieracz()
        monkeypatch.setattr(obrazy, "to_data_uri", pobieracz)

        wynik = obrazy.wejscie("", json.dumps(["https://x/foto.jpg"]), persona="olx")

        assert [u for u, _ in pobieracz.wywolania] == ["https://x/foto.jpg"]
        assert wynik == [{"role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/jpeg;base64,AAA"}]}]

    def test_zwykla_lista_tez_dziala(self, monkeypatch):
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())
        wynik = obrazy.wejscie("cześć", ["https://x/a.jpg"], persona="pro")
        assert isinstance(wynik, list)

    def test_smieci_w_kolumnie_nie_wywalaja_tury(self, monkeypatch):
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())
        assert obrazy.wejscie("tekst", "to nie jest json", persona="pro") == "tekst"

    def test_brak_zalacznikow_daje_goly_tekst(self, monkeypatch):
        # Regresja: rozmowa bez zdjęć ma iść do modelu DOKŁADNIE jak dotąd (string).
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())
        assert obrazy.wejscie("blat 180x60x4", None, persona="pro") == "blat 180x60x4"
        assert obrazy.wejscie("blat", [], persona="pro") == "blat"


class TestWejscieMultimodalne:
    def test_sam_obraz_bez_tekstu_nie_daje_pustego_promptu(self, monkeypatch):
        # SEDNO U2: wiadomość samym zdjęciem dawała modelowi ''.
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())

        wynik = obrazy.wejscie("", ["https://x/foto.jpg"], persona="olx")

        assert wynik != ""
        czesci = wynik[0]["content"]
        assert [c["type"] for c in czesci] == ["input_image"]

    def test_tekst_i_obraz_ida_razem_tekst_pierwszy(self, monkeypatch):
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())

        wynik = obrazy.wejscie("taki blat jak na zdjęciu", ["https://x/a.jpg"], persona="pro")

        czesci = wynik[0]["content"]
        assert [c["type"] for c in czesci] == ["input_text", "input_image"]
        assert czesci[0]["text"] == "taki blat jak na zdjęciu"

    def test_ksztalt_jest_kanoniczny_dla_sdk(self, monkeypatch):
        """`input_image` z gołym stringiem w `image_url` — postać, którą Agents SDK
        rozumie NATYWNIE i którą adapter LiteLLM tłumaczy na format Chat Completions
        (inwariant przenośności: nic wyłącznego dla Responses API)."""
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/a.jpg": "data:image/png;base64,ZZZ"}))

        czesci = obrazy.wejscie("", ["https://x/a.jpg"], persona="pro")[0]["content"]

        assert czesci == [{"type": "input_image", "image_url": "data:image/png;base64,ZZZ"}]

    def test_limit_liczby_obrazow(self, monkeypatch):
        pobieracz = _Pobieracz()
        monkeypatch.setattr(obrazy, "to_data_uri", pobieracz)

        obrazy.wejscie("", ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"],
                       persona="pro")

        assert len(pobieracz.wywolania) == obrazy.LIMIT_OBRAZOW == 2


class TestProfilKanalu:
    """Nie każdy kanał dostarcza obrazy tak samo — OLX/Allegro czytają wyłącznie
    jpg/png (`bots.channel_caps.OLX_CAPS['image_formats']`), livechat bez ograniczeń."""

    def test_olx_ogranicza_formaty(self, monkeypatch):
        pobieracz = _Pobieracz()
        monkeypatch.setattr(obrazy, "to_data_uri", pobieracz)

        obrazy.wejscie("", ["https://x/a.jpg"], persona="olx")

        assert pobieracz.wywolania == [("https://x/a.jpg", ("jpg", "jpeg", "png"))]

    def test_allegro_ogranicza_formaty(self, monkeypatch):
        pobieracz = _Pobieracz()
        monkeypatch.setattr(obrazy, "to_data_uri", pobieracz)

        obrazy.wejscie("", ["https://x/a.jpg"], persona="allegro")

        assert pobieracz.wywolania == [("https://x/a.jpg", ("jpg", "jpeg", "png"))]

    def test_livechat_bez_ograniczenia_formatu(self, monkeypatch):
        pobieracz = _Pobieracz()
        monkeypatch.setattr(obrazy, "to_data_uri", pobieracz)

        obrazy.wejscie("", ["https://x/a.webp"], persona="pro")

        assert pobieracz.wywolania == [("https://x/a.webp", None)]


class TestNieudanePobranie:
    def test_nieodczytany_obraz_zostawia_slad_mimo_tekstu(self, monkeypatch):
        """N5 (rerecenzja gałęzi): nieodczytane zdjęcie GINĘŁO BEZ ŚLADU, gdy
        wiadomość miała też tekst — model dostawał sam tekst i nie wiedział, że
        załącznik w ogóle był. „Tak jak na zdjęciu, ile taki kosztuje?" +
        niepobrane zdjęcie = odpowiedź udająca, że zdjęcia nie było, na
        wiadomość, która się do niego odwołuje."""
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/zly.jpg": None}))

        wynik = obrazy.wejscie("tak jak na zdjęciu, ile taki kosztuje?",
                               ["https://x/zly.jpg"], persona="olx")

        assert wynik == [
            {"role": "user", "content": [
                {"type": "input_text", "text": "tak jak na zdjęciu, ile taki kosztuje?"}]},
            {"role": "system", "content": obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU},
        ]

    def test_sam_nieudany_obraz_bez_tekstu_daje_zastepnik_nie_pustke(self, monkeypatch):
        """Wiadomość była SAMYM zdjęciem, a zdjęcia nie dało się pobrać —
        model NIE MOŻE dostać pustego promptu (cisza w rozmowie). Dostaje
        jednoznaczny opis sytuacji i może poprosić o ponowne przesłanie.

        N4: opis idzie rolą "system", NIE "user" — to wewnętrzna instrukcja,
        nie wypowiedź klienta (ta sama poprawka co przy komunikacie korekty
        guardraila, `tura._KOMUNIKAT_KOREKTY`).

        C3: obok noty systemowej stoi rzeczowy marker roli "user" — wejście
        złożone WYŁĄCZNIE z roli "system" wywalało turę na torze Anthropica
        (patrz TestWejscieNigdyNieJestSamymSystemem)."""
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/zly.jpg": None}))

        wynik = obrazy.wejscie("", ["https://x/zly.jpg"], persona="olx")

        assert wynik == [
            {"role": "user", "content": [
                {"type": "input_text", "text": obrazy.MARKER_WIADOMOSCI_BEZ_TEKSTU}]},
            {"role": "system", "content": obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU},
        ]

    def test_zastepnik_nigdy_nie_idzie_rola_user(self, monkeypatch):
        """N4: zastępnik trafia na stałe do `SQLiteSession`. W roli "user"
        model mógłby wziąć go za prawdziwe pytanie klienta i sparafrazować mu
        go w odpowiedzi — dokładnie ta klasa problemu, dla której komunikat
        korekty przeniesiono na rolę "system"."""
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/zly.jpg": None}))

        for tresc in ("", "mam pytanie"):
            for pozycja in obrazy.wejscie(tresc, ["https://x/zly.jpg"], persona="olx"):
                if obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU in json.dumps(
                        pozycja, ensure_ascii=False):
                    assert pozycja["role"] == "system"

    def test_czesciowe_niepowodzenie_tez_zostawia_slad(self, monkeypatch):
        # Jedno zdjęcie się pobrało, drugie nie — model ma wiedzieć, że czegoś
        # nie widzi, zamiast odpowiadać z niepełnego materiału.
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/zly.jpg": None}))

        wynik = obrazy.wejscie("dwa blaty", ["https://x/ok.jpg", "https://x/zly.jpg"],
                               persona="olx")

        assert wynik[0]["role"] == "user"
        assert {"type": "input_image", "image_url": "data:image/jpeg;base64,AAA"} \
            in wynik[0]["content"]
        assert wynik[-1] == {"role": "system",
                             "content": obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU}

    def test_wszystkie_obrazy_odczytane_nie_dokladaja_zastepnika(self, monkeypatch):
        # Kontrola negatywna: udana ścieżka multimodalna bez zmian.
        monkeypatch.setattr(obrazy, "to_data_uri", _Pobieracz())

        wynik = obrazy.wejscie("blat", ["https://x/ok.jpg"], persona="olx")

        assert wynik == [{"role": "user", "content": [
            {"type": "input_text", "text": "blat"},
            {"type": "input_image", "image_url": "data:image/jpeg;base64,AAA"}]}]

class TestWejscieNigdyNieJestSamymSystemem:
    """C3 (runda D): po poprawce N4 wiadomość niosąca SAMO nieodczytane zdjęcie
    dawała wejście złożone WYŁĄCZNIE z roli „system" — zero wiadomości roli
    „user". Na torze LiteLLM/Anthropic kończyło się to twardym błędem
    (`BadRequestError: Anthropic requires at least one non-system message`),
    czyli wywaleniem CAŁEJ tury. Na OpenAI błąd nie występował, więc awaria była
    widoczna tylko na jednym torze — a przenośność dostawcy jest wymogiem
    projektu (patrz `bots_pro/models.py`).

    Osiągalne realnie: HEIC albo webp jako PIERWSZA wiadomość na OLX/Allegro
    (profil kanału dopuszcza jpg/png, więc `to_data_uri` odrzuca resztę).

    Intencja N4 zostaje: instrukcja dla modelu nadal idzie rolą „system" i NIE
    udaje wypowiedzi klienta — rolą „user" idzie wyłącznie rzeczowy marker
    mówiący, że wiadomość klienta nie miała tekstu."""

    def _bez_odczytu(self, monkeypatch):
        monkeypatch.setattr(obrazy, "to_data_uri",
                            _Pobieracz({"https://x/zly.heic": None}))

    def test_sam_nieodczytany_obraz_daje_wiadomosc_roli_user(self, monkeypatch):
        self._bez_odczytu(monkeypatch)

        wynik = obrazy.wejscie("", ["https://x/zly.heic"], persona="olx")

        assert [p["role"] for p in wynik] == ["user", "system"]
        assert wynik[0] == {"role": "user", "content": [
            {"type": "input_text", "text": obrazy.MARKER_WIADOMOSCI_BEZ_TEKSTU}]}
        assert wynik[1] == {"role": "system",
                            "content": obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU}

    def test_marker_nie_udaje_wypowiedzi_klienta(self, monkeypatch):
        """Marker opisuje FAKT (wiadomość bez tekstu), nie niesie instrukcji dla
        modelu — ta zostaje rolą „system". Inaczej wrócilibyśmy do N4: model
        wziąłby instrukcję za pytanie klienta i sparafrazował mu ją w odpowiedzi."""
        self._bez_odczytu(monkeypatch)

        wynik = obrazy.wejscie("", ["https://x/zly.heic"], persona="olx")

        uzytkownik = json.dumps([p for p in wynik if p["role"] == "user"],
                                ensure_ascii=False)
        assert obrazy.ZASTEPNIK_NIEODCZYTANEGO_OBRAZU not in uzytkownik
        assert "Poproś" not in uzytkownik

    @pytest.mark.parametrize("tresc,adresy", [
        ("", ["https://x/zly.heic"]),                              # samo zle zdjecie
        ("ile taki kosztuje?", ["https://x/zly.heic"]),            # tekst + zle zdjecie
        ("", ["https://x/ok.jpg", "https://x/zly.heic"]),          # czesciowe niepowodzenie
    ])
    def test_tor_openai_wejscie_ma_zawsze_role_user(self, monkeypatch, tresc, adresy):
        """Tor OpenAI: lista pozycji idzie do modelu tak, jak ją tu składamy."""
        self._bez_odczytu(monkeypatch)

        wynik = obrazy.wejscie(tresc, adresy, persona="olx")

        assert any(p["role"] == "user" for p in wynik)

    @pytest.mark.parametrize("tresc,adresy", [
        ("", ["https://x/zly.heic"]),
        ("ile taki kosztuje?", ["https://x/zly.heic"]),
        ("", ["https://x/ok.jpg", "https://x/zly.heic"]),
    ])
    def test_tor_anthropic_konwersja_daje_wiadomosc_niesystemowa(
            self, monkeypatch, tresc, adresy):
        """Tor LiteLLM/Anthropic: to samo wejście po konwersji na format Chat
        Completions (`Converter.items_to_messages` — dokładnie ta droga, którą
        idzie `LitellmModel`) MUSI mieć co najmniej jedną wiadomość spoza roli
        systemowej, inaczej Anthropic odrzuca żądanie."""
        pytest.importorskip("agents")
        from agents.models.chatcmpl_converter import Converter

        self._bez_odczytu(monkeypatch)

        wiadomosci = Converter.items_to_messages(
            obrazy.wejscie(tresc, adresy, persona="olx"))

        assert [w for w in wiadomosci if w.get("role") not in ("system", "developer")]

    def test_wejscie_bez_zalacznikow_nadal_jest_stringiem(self, monkeypatch):
        # Kontrola negatywna: sciezka bez zdjec (wiekszosc ruchu) bez zmian.
        self._bez_odczytu(monkeypatch)
        assert obrazy.wejscie("dzien dobry", None, persona="olx") == "dzien dobry"
