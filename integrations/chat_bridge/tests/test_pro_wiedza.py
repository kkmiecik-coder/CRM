# -*- coding: utf-8 -*-
"""
Pomiar trafności bazy wiedzy „w cieniu" (P2, runda napraw 5).

Skąd to. `bots/knowledge.py::retrieve` liczy podobieństwo (`scored`) i ODRZUCA
je w tej samej linii — zwraca pięć NAJBLIŻSZYCH fragmentów, także dla pytania,
którego w bazie w ogóle nie ma. Reguła bezpieczeństwa z `prompty.WIEDZA`
(„pusta lista -> oddaj rozmowę człowiekowi") odpala się więc wyłącznie przy
AWARII indeksu (pusta tabela, zepsuty embedding zapytania), a nigdy przy braku
odpowiedzi. Bot odpowiada z pięciu przypadkowych fragmentów i brzmi pewnie.

Czego tu NIE MA i nie ma być: PROGU. Nie znamy dobrej wartości, a zgadnięta
stała tylko przeniosłaby problem (odcięłaby trafne odpowiedzi albo nie odcięła
żadnej). Ta runda robi WYŁĄCZNIE pomiar: udostępnia miarę, która dziś jest
wyrzucana, i loguje ją dla każdego zapytania agenta Wiedzy, żeby próg dało się
DOBRAĆ Z DANYCH po kilku dniach ruchu. Instrukcja odczytu jest w raporcie
rundy 5.

`bots/knowledge.py` jest współdzielony ze STARYM silnikiem obsługującym żywy
ruch (`bots/quotebot.py`, `bots/livechat.py`, `bots/suggester.py` — wszystkie
wołają `retrieve`), więc zmiana jest czysto addytywna: `retrieve` zostaje
nietknięty, a `retrieve_scored` stoi obok. Cenę tego (dwie kopie tej samej
pętli) płaci sonda `test_obie_funkcje_zwracaja_te_same_fragmenty`.
"""
import importlib

import pytest

from bots_pro import wiedza

kn = importlib.import_module("bots.knowledge")
db_mod = importlib.import_module("core.db")


def _zaindeksuj(monkeypatch, artykuly, embed_fn):
    db_mod.init_db()
    c = db_mod.db(); c.execute("DELETE FROM kb_chunks"); c.commit(); c.close()
    monkeypatch.setattr(kn, "cw_articles", lambda slug: artykuly)
    monkeypatch.setattr(kn, "embed", embed_fn)
    kn.sync_index()


def _embed_wysylka(texts, **kw):
    """Wektor zależny od obecności słowa „wysył" — ten sam wzorzec, którego
    używa test_knowledge.py::test_retrieve_zwraca_najtrafniejsze."""
    return [[1.0, 0.0] if "wysył" in t else [0.0, 1.0] for t in texts]


_ARTYKULY = [{"id": 1, "title": "A", "content": "wysyłka kurierem"},
             {"id": 2, "title": "B", "content": "gatunki drewna dąb"}]


class TestRetrieveScored:
    """Nowa funkcja obok istniejącej — miara podobieństwa udostępniona tam,
    gdzie dziś jest odrzucana."""

    def test_zwraca_pary_wynik_fragment(self, monkeypatch):
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        pary = kn.retrieve_scored("kiedy wysyłka?")
        assert pary, "indeks nie powinien być pusty"
        for wynik, fragment in pary:
            assert isinstance(wynik, float)
            assert isinstance(fragment, str)

    def test_wyniki_sa_posortowane_malejaco(self, monkeypatch):
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        wyniki = [w for w, _ in kn.retrieve_scored("kiedy wysyłka?")]
        assert wyniki == sorted(wyniki, reverse=True)

    def test_najlepszy_wynik_odpowiada_najtrafniejszemu_fragmentowi(self, monkeypatch):
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        pary = kn.retrieve_scored("kiedy wysyłka?")
        assert "wysył" in pary[0][1]
        # Embedding jest tu ortogonalny, więc trafienie to 1.0, a pudło 0.0 —
        # miara NAPRAWDĘ różnicuje, a nie zwraca stałej.
        assert pary[0][0] > pary[-1][0]

    def test_honoruje_k(self, monkeypatch):
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        assert len(kn.retrieve_scored("kiedy wysyłka?", k=1)) == 1

    def test_pusty_indeks_zwraca_pusto(self):
        db_mod.init_db()
        c = db_mod.db(); c.execute("DELETE FROM kb_chunks"); c.commit(); c.close()
        assert kn.retrieve_scored("cokolwiek") == []

    def test_zepsuty_embedding_zapytania_zwraca_pusto(self, monkeypatch):
        # Ta sama osłona co w `retrieve`: brak/uszkodzony embedding pytania to
        # stan błędu, nie „pięć losowych fragmentów".
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        monkeypatch.setattr(kn, "embed", lambda texts, **kw: None)
        assert kn.retrieve_scored("kiedy wysyłka?") == []
        monkeypatch.setattr(kn, "embed", lambda texts, **kw: [None])
        assert kn.retrieve_scored("kiedy wysyłka?") == []

    def test_obie_funkcje_zwracaja_te_same_fragmenty(self, monkeypatch):
        # SONDA: `retrieve` i `retrieve_scored` mają dwie kopie tej samej pętli,
        # bo `retrieve` obsługuje ŻYWY ruch starego silnika i celowo nie został
        # tknięty. Ta asercja jest ceną tej decyzji — gdyby kopie się rozjechały,
        # pomiar opisywałby coś innego niż to, co dostaje bot.
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        fragmenty = kn.retrieve("kiedy wysyłka?")
        pary = kn.retrieve_scored("kiedy wysyłka?")
        assert [f for _, f in pary] == fragmenty


class TestSzukajLogujeTrafnosc:
    """Log dla KAŻDEGO zapytania agenta Wiedzy: najlepszy wynik, wynik
    ostatniego (przy domyślnym BOT_RETRIEVAL_K=5 — piątego) fragmentu i samo
    pytanie. Tyle wystarczy, żeby po kilku dniach policzyć rozkład i dobrać
    próg z danych."""

    def _zloz(self, monkeypatch, pary):
        zapisane = []
        monkeypatch.setattr(wiedza, "retrieve_scored", lambda pytanie, k=None: pary)
        monkeypatch.setattr(wiedza, "log", lambda *a: zapisane.append(" ".join(str(x) for x in a)))
        return zapisane

    def test_loguje_najlepszy_i_ostatni_wynik(self, monkeypatch):
        pary = [(0.81, "a"), (0.77, "b"), (0.70, "c"), (0.66, "d"), (0.62, "e")]
        zapisane = self._zloz(monkeypatch, pary)
        wiedza.szukaj("ile trwa realizacja?")
        assert len(zapisane) == 1
        linia = zapisane[0]
        assert "KB trafnosc:" in linia
        assert "top=0.8100" in linia
        assert "ost=0.6200" in linia
        assert "n=5" in linia

    def test_loguje_samo_pytanie(self, monkeypatch):
        zapisane = self._zloz(monkeypatch, [(0.5, "a")])
        wiedza.szukaj("czy robicie blaty z sosny?")
        assert "czy robicie blaty z sosny?" in zapisane[0]

    def test_pytanie_w_logu_jest_jedna_linia(self, monkeypatch):
        # Wieloliniowe pytanie rozbiłoby log na kilka wpisów i zepsuło zliczanie.
        zapisane = self._zloz(monkeypatch, [(0.5, "a")])
        wiedza.szukaj("pierwsza linia\n\ndruga   linia")
        assert "\n" not in zapisane[0]
        assert "pierwsza linia druga linia" in zapisane[0]

    def test_bardzo_dlugie_pytanie_jest_ucinane(self, monkeypatch):
        zapisane = self._zloz(monkeypatch, [(0.5, "a")])
        wiedza.szukaj("A" * 5000)
        assert len(zapisane[0]) < 400

    def test_brak_trafien_tez_jest_zalogowany(self, monkeypatch):
        # To jest przypadek, dla którego cały pomiar powstał: pusty wynik dziś
        # oznacza AWARIĘ indeksu i musi być rozróżnialny w danych od słabego
        # dopasowania.
        zapisane = self._zloz(monkeypatch, [])
        wiedza.szukaj("cokolwiek")
        assert "n=0" in zapisane[0]
        assert "top=-" in zapisane[0]
        assert "ost=-" in zapisane[0]

    def test_mniej_niz_k_fragmentow_nie_udaje_piatego_wyniku(self, monkeypatch):
        # Przy dwóch fragmentach „wynik piątego" nie istnieje. Wpisanie tam
        # drugiego zaniżyłoby próg policzony potem z tych danych.
        zapisane = self._zloz(monkeypatch, [(0.9, "a"), (0.4, "b")])
        wiedza.szukaj("cokolwiek")
        assert "n=2" in zapisane[0]
        assert "ost=-" in zapisane[0]
        assert "top=0.9000" in zapisane[0]


class TestPomiarNieDotykaTego_CoWidziKlient:
    """Warunek konieczny tej pozycji: czysta obserwacja. Zero wpływu na
    odpowiedź bota i zero szans, żeby błąd w logowaniu przerwał turę."""

    def test_szukaj_zwraca_dokladnie_ten_sam_ksztalt_co_dotad(self, monkeypatch):
        monkeypatch.setattr(wiedza, "retrieve_scored",
                            lambda pytanie, k=None: [(0.7, "fragment A"), (0.3, "fragment B")])
        monkeypatch.setattr(wiedza, "log", lambda *a: None)
        assert wiedza.szukaj("cokolwiek") == [
            {"tytul": "", "tresc": "fragment A", "article_id": None},
            {"tytul": "", "tresc": "fragment B", "article_id": None},
        ]

    def test_kolejnosc_fragmentow_jest_ta_sama_co_z_retrieve(self, monkeypatch):
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        monkeypatch.setattr(wiedza, "log", lambda *a: None)
        assert [w["tresc"] for w in wiedza.szukaj("kiedy wysyłka?")] == kn.retrieve("kiedy wysyłka?")

    def test_blad_logowania_nie_przerywa_odpowiedzi(self, monkeypatch):
        # Pomiar nie może być w stanie zabrać klientowi odpowiedzi — to jedyna
        # rzecz gorsza od braku pomiaru.
        def wybuch(*a):
            raise RuntimeError("log padl")
        monkeypatch.setattr(wiedza, "retrieve_scored", lambda pytanie, k=None: [(0.7, "A")])
        monkeypatch.setattr(wiedza, "log", wybuch)
        assert wiedza.szukaj("cokolwiek") == [
            {"tytul": "", "tresc": "A", "article_id": None}]

    def test_pusta_lista_nadal_znaczy_stan_bledu(self, monkeypatch):
        # Reguła bezpieczeństwa z `prompty.WIEDZA` („pusta lista -> oddaj
        # rozmowę człowiekowi") ma działać dokładnie tak jak dotąd — pomiar
        # niczego nie odcina.
        monkeypatch.setattr(wiedza, "retrieve_scored", lambda pytanie, k=None: [])
        monkeypatch.setattr(wiedza, "log", lambda *a: None)
        assert wiedza.szukaj("cokolwiek") == []

    def test_jedno_embedowanie_na_zapytanie(self, monkeypatch):
        # `szukaj` woła WYŁĄCZNIE `retrieve_scored` — gdyby wołało obie
        # funkcje, każde pytanie klienta kosztowałoby dwa wywołania embed.
        _zaindeksuj(monkeypatch, _ARTYKULY, _embed_wysylka)
        licznik = {"n": 0}

        def liczacy_embed(texts, **kw):
            licznik["n"] += 1
            return _embed_wysylka(texts, **kw)

        monkeypatch.setattr(kn, "embed", liczacy_embed)
        monkeypatch.setattr(wiedza, "log", lambda *a: None)
        wiedza.szukaj("kiedy wysyłka?")
        assert licznik["n"] == 1


class TestNarzedzieWiedzyNadalOddajeTeSamaTresc:
    """Sonda spójności: narzędzie agenta (`szukaj_w_bazie_wiedzy`) przechodzi
    przez `wiedza.szukaj`, więc pomiar odpala się dla KAŻDEGO zapytania agenta
    Wiedzy, a nie tylko wtedy, gdy ktoś zawoła `szukaj` bezpośrednio."""

    def test_narzedzie_wola_szukaj(self, monkeypatch):
        pytest.importorskip("agents")
        from bots_pro import narzedzia_wiedzy
        assert narzedzia_wiedzy.wiedza is wiedza
