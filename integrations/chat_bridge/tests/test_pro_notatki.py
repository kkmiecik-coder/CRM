# -*- coding: utf-8 -*-
"""
U7: każde wyjście handoffowe zostawia ślad — notatkę dla konsultanta ORAZ
wiadomość do klienta.

Przed tą poprawką w CAŁYM `bots_pro/` nie było ani jednego `cw_note`, a trzy
z czterech wyjść handoffowych (`limit tur`, `podwójne naruszenie G1`,
`nieudane podsumowanie`) robiły `return` BEZ żadnej wysyłki: klient dostawał
ciszę, a człowiek nie wiedział, że ma przejąć rozmowę. Stary silnik ma
`bots.quotebot.handoff_with_apology` (przeprosiny + notatka z parametrami).

Ten plik NIE wymaga SDK — `bots_pro.notatki` i `bots_pro.stan` są od niego
niezależne (jak `bots_pro.wysylka`).
"""
from bots_pro import notatki, stan


class TestTrescNotatki:
    def test_zawiera_powod(self):
        tresc = notatki.tresc_dla_agenta("limit dlugosci rozmowy (ponad 12 tur)", pozycje=[])
        assert "limit dlugosci rozmowy (ponad 12 tur)" in tresc

    def test_zawiera_pozycje_wyceny(self):
        pozycje = [{"id": "1", "produkt": "blat", "gatunek": "Dąb", "technologia": "lity",
                    "klasa": "A/B", "dlugosc": 180, "szerokosc": 60, "grubosc": 4, "ilosc": 1,
                    "wykonczenie": "surowe"}]
        tresc = notatki.tresc_dla_agenta("powod", pozycje=pozycje)
        assert "180x60x4" in tresc
        assert "Dąb" in tresc

    def test_zawiera_dostawe_i_link_do_wyceny(self):
        tresc = notatki.tresc_dla_agenta(
            "powod", pozycje=[],
            dostawa={"kod_pocztowy": "31-000", "kurier": "DPD", "netto": 200.0, "brutto": 246.0},
            wycena={"edit_uuid": "UUID-1", "public_url": "https://crm/x/abc"})
        assert "DPD" in tresc
        assert "31-000" in tresc
        assert "246" in tresc
        assert "https://crm/x/abc" in tresc

    def test_bez_danych_nie_wywala_sie_i_mowi_ze_ich_brak(self):
        tresc = notatki.tresc_dla_agenta("powod")
        assert "powod" in tresc
        assert tresc.strip()


class TestWyslijNotatke:
    def test_uzywa_tokenu_bota_pro(self, monkeypatch):
        wywolania = []
        monkeypatch.setattr(notatki, "cw_note",
                            lambda conv_id, tekst, token=None: wywolania.append(
                                (conv_id, tekst, token)) or True)
        monkeypatch.setattr(notatki, "BOT_PRO_CW_AGENT_TOKEN", "TOKEN-PRO")

        assert notatki.wyslij_notatke(4242, "tresc") is True
        assert wywolania == [(4242, "tresc", "TOKEN-PRO")]

    def test_blad_notatki_nie_rzuca(self, monkeypatch):
        def _wybuch(*a, **k):
            raise RuntimeError("Chatwoot padl")

        monkeypatch.setattr(notatki, "cw_note", _wybuch)
        assert notatki.wyslij_notatke(1, "tresc") is False


class _Odpowiedz:
    """Namiastka `requests.Response` — `cw_note` zwraca wlasnie taki obiekt."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


class TestKodHttpNotatki:
    """W2: `wyslij_notatke` lapala wylacznie WYJATEK i meldowala sukces przy
    KAZDYM kodzie HTTP. Bledny albo wygasly BOT_PRO_CW_AGENT_TOKEN daje 401,
    ktore przechodzilo jako "notatka wyslana" — a oznaczenie notatki w stanie
    tury (`oznacz_notatke_w_turze`) blokowalo wtedy ponowna probe z
    `notatka_stanu`. Zly token objawial sie w notatkach CISZA zamiast bledu.
    `bots_pro/podsumowanie.py` wynik wysylki sprawdza — tu jest tak samo."""

    def test_401_to_porazka_nie_sukces(self, monkeypatch):
        monkeypatch.setattr(notatki, "cw_note", lambda *a, **k: _Odpowiedz(401))
        assert notatki.wyslij_notatke(4243, "tresc") is False

    def test_403_i_500_tez_sa_porazka(self, monkeypatch):
        for kod in (403, 404, 422, 500, 502):
            monkeypatch.setattr(notatki, "cw_note", lambda *a, _k=kod, **kw: _Odpowiedz(_k))
            assert notatki.wyslij_notatke(4244, "tresc") is False, "kod %s" % kod

    def test_200_i_201_to_sukces(self, monkeypatch):
        for kod in (200, 201, 204):
            monkeypatch.setattr(notatki, "cw_note", lambda *a, _k=kod, **kw: _Odpowiedz(_k))
            assert notatki.wyslij_notatke(4245, "tresc") is True, "kod %s" % kod

    def test_zly_kod_jest_widoczny_w_logu(self, monkeypatch):
        logi = []
        monkeypatch.setattr(notatki, "log", lambda *czesci: logi.append(" ".join(str(c) for c in czesci)))
        monkeypatch.setattr(notatki, "cw_note", lambda *a, **k: _Odpowiedz(401))

        notatki.wyslij_notatke(4246, "tresc")

        assert any("401" in wpis for wpis in logi)

    def test_nieudana_notatka_nie_oznacza_notatki_w_turze(self, monkeypatch):
        """Sedno bledu: oznaczenie w stanie tury blokuje PONOWNA probe, wiec
        notatka odrzucona przez Chatwoota nie moze sie liczyc jako napisana."""
        stan.ustaw_kontekst(96402010, persona_tury="pro")
        monkeypatch.setattr(notatki, "cw_note", lambda *a, **k: _Odpowiedz(401))

        assert notatki.wyslij_notatke(96402010, "notatka odrzucona") is False
        assert stan.notatka_w_turze() is False


class TestHandoffZostawiaNotatke:
    """Notatka siedzi w `stan.handoff`, więc obejmuje TAKŻE handoff wywołany
    przez sam model (narzędzie `oddaj_czlowiekowi`), nie tylko bezpieczniki tury."""

    def test_handoff_pisze_notatke_z_powodem_przed_toggle_statusu(self, monkeypatch):
        conv_id = 96401001
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        kolejnosc = []
        monkeypatch.setattr(notatki, "wyslij_notatke",
                            lambda cid, tekst: kolejnosc.append(("notatka", cid, tekst)) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff",
                            lambda cid, token=None: kolejnosc.append(("toggle", cid)) or True)

        wynik = stan.handoff("klient prosi o czlowieka")

        assert wynik["ok"] is True
        assert [k[0] for k in kolejnosc] == ["notatka", "toggle"]
        assert "klient prosi o czlowieka" in kolejnosc[0][2]

    def test_nieudana_notatka_nie_blokuje_handoffu(self, monkeypatch):
        conv_id = 96401002
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        monkeypatch.setattr(notatki, "wyslij_notatke", lambda cid, tekst: False)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff", lambda cid, token=None: True)

        assert stan.handoff("powod")["ok"] is True


class TestJednaNotatkaNaTure:
    """N7 (rerecenzja gałęzi): notatka dublowała się na szczęśliwej ścieżce
    Allegro — `przygotuj_zamowienie` pisze bogatą notatkę
    (`zamowienie_do_agenta`), a stojący zaraz za nim `stan.handoff` dokładał
    drugą, prawie identyczną (`notatka_stanu`). Konsultant dostawał dwa wpisy
    o tym samym.

    Zasada: JEDNA notatka na turę. Wygrywa ta napisana pierwsza, bo to zawsze
    ta bardziej szczegółowa (powód konkretnej ścieżki), a `notatka_stanu` jest
    ogólnym uzupełnieniem dla wyjść, które własnej notatki nie mają."""

    def _slady(self, monkeypatch):
        slady = {"notatki": [], "toggle": []}
        monkeypatch.setattr(notatki, "cw_note",
                            lambda cid, tekst, token=None: slady["notatki"].append(tekst) or True)
        monkeypatch.setattr("core.chatwoot.cw_bot_handoff",
                            lambda cid, token=None: slady["toggle"].append(cid) or True)
        return slady

    def test_notatka_stanu_nie_dubluje_wczesniejszej_notatki_tury(self, monkeypatch):
        stan.ustaw_kontekst(96402001, persona_tury="allegro")
        slady = self._slady(monkeypatch)

        notatki.wyslij_notatke(96402001, "bogata notatka o zamowieniu")
        stan.handoff("Allegro — gotowa wycena do domkniecia")

        assert slady["notatki"] == ["bogata notatka o zamowieniu"]
        assert len(slady["toggle"]) == 1

    def test_bez_wczesniejszej_notatki_handoff_pisze_swoja(self, monkeypatch):
        # Kontrola negatywna: najczestsze wyjscie (oddaj_czlowiekowi) nie moze
        # zostac bez notatki.
        stan.ustaw_kontekst(96402002, persona_tury="pro")
        slady = self._slady(monkeypatch)

        stan.handoff("klient prosi o czlowieka")

        assert len(slady["notatki"]) == 1
        assert "klient prosi o czlowieka" in slady["notatki"][0]

    def test_nieudana_notatka_nie_blokuje_notatki_handoffu(self, monkeypatch):
        # Notatka, ktora NIE doszla, nie liczy sie jako "notatka tury" —
        # inaczej awaria Chatwoota zostawialaby konsultanta bez czegokolwiek.
        stan.ustaw_kontekst(96402003, persona_tury="pro")
        slady = self._slady(monkeypatch)

        def _padnij(cid, tekst, token=None):
            raise RuntimeError("Chatwoot 500")

        monkeypatch.setattr(notatki, "cw_note", _padnij)
        assert notatki.wyslij_notatke(96402003, "notatka, ktora nie doszla") is False
        monkeypatch.setattr(notatki, "cw_note",
                            lambda cid, tekst, token=None: slady["notatki"].append(tekst) or True)

        stan.handoff("powod")

        assert len(slady["notatki"]) == 1

    def test_nowa_tura_znowu_pozwala_napisac_notatke(self, monkeypatch):
        conv_id = 96402004
        stan.ustaw_kontekst(conv_id, persona_tury="pro")
        slady = self._slady(monkeypatch)
        notatki.wyslij_notatke(conv_id, "notatka z tury 1")

        stan.ustaw_kontekst(conv_id, persona_tury="pro")   # NOWA tura
        stan.handoff("powod")

        assert len(slady["notatki"]) == 2
