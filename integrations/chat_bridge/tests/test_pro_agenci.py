# -*- coding: utf-8 -*-
"""
Skład routera i agentów.

Router ma JEDNO zadanie: wybrać agenta. Nie wolno mu dać narzędzi biznesowych,
bo wtedy zacznie sam prowadzić rozmowę i wracamy do jednego wielkiego promptu.

narzedzia.py (i przez niego agenci.py) importuje `agents` na poziomie modułu —
bez zainstalowanego SDK cały ten plik ma zostać POMINIĘTY (wzorzec z
test_pro_narzedzia.py / test_pro_models.py).
"""
import pytest

pytest.importorskip("agents")  # patrz docstring modulu

from bots_pro import agenci

# Narzędzia hostowane przez dostawcę zamykają drogę do Anthropica (inwariant
# przenośności 1b, patrz test_pro_narzedzia.py::TestZestawNarzedzi).
_ZAKAZANE_NARZEDZIA = {"file_search", "web_search", "code_interpreter", "computer"}


class TestRouter:
    def test_router_ma_trzy_przekazania(self):
        router = agenci.zbuduj_router()
        assert len(router.handoffs) == 3

    def test_router_nie_ma_narzedzi_biznesowych(self):
        router = agenci.zbuduj_router()
        assert router.tools == []

    def test_prompt_routera_jest_krotki(self):
        # Runda poprawek 1 (recenzja): licznik ZNAKÓW mierzył niewłaściwą
        # jednostkę — polski tekst to ~3,1 znaku na token (nie ~4 jak dla
        # angielskiego), więc próg "< 1600 znaków" przepuszczał prompt, który
        # w tokenach modelu (o200k_base) już przekraczał budżet 400 tokenów
        # (ROLA+ROUTER wyszło wtedy 451 tokenów). Liczymy teraz naprawdę.
        tiktoken = pytest.importorskip("tiktoken")
        router = agenci.zbuduj_router()
        enc = tiktoken.get_encoding("o200k_base")
        liczba_tokenow = len(enc.encode(router.instructions))
        assert liczba_tokenow < 400, (
            "Prompt routera (ROLA+ROUTER) ma %d tokenow, budzet to 400 — "
            "logika biznesowa wpelza w ROLA albo ROUTER." % liczba_tokenow
        )


class TestAgentWyceny:
    def test_agent_wyceny_ma_narzedzia(self):
        # RUNDA NAPRAW 4 (P2): 11 -> 12, doszlo `wyslij_obraz` (probka gatunkow,
        # wzornik kolorow, schemat wymiarow, schemat krawedzi — regres wobec
        # starego silnika).
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.tools) == 12

    def test_prompt_wyceny_ma_hojny_ale_skonczony_budzet(self):
        # Runda poprawek 1: nie ograniczamy tresci merytorycznej (reguly
        # handlowe z personas.json) sztywnym niskim progiem jak dla routera —
        # ale hojny sufit pilnuje, zeby przyszle zadanie nie dokladalo po
        # cichu bez zauwazenia. 6000 znakow to bylo ok. 1150 znakow zapasu
        # ponad stan tamtej rundy (ROLA+WYCENA ~5170 zn).
        #
        # NAPRAWY PO TESTACH NA ZYWYM CZACIE (runda 1, N0): prog podniesiony do
        # 7800 znakow, bo szesc rozmow z zywego czatu wskazalo szesc regul,
        # ktorych w prompcie nie bylo, a ktore lacznie zajmuja ok. 1660 znakow:
        #   - PYTANIE ZOBOWIAZUJE (N1b, ~340 zn) — bot pytal i w tej samej
        #     turze oddawal rozmowe, klient zostawal z pytaniem bez adresata;
        #   - KSZTALT (N4, ~445 zn) — blat okragly ⌀120 policzony jak kwadrat
        #     120x120, czyli 27% materialu roznicy bez pokrycia;
        #   - dostawa w POTWIERDZENIE (N2, ~155 zn) — prosba o potwierdzenie
        #     kwoty z dostawa BEZ pokazania nowego podsumowania;
        #   - WYMIARY: dlugosc/szerokosc i poprawki klienta (N5, ~245 zn);
        #   - krawedzie przy blatach kuchennych (N8, ~+80 zn wzgledem zdania,
        #     ktore zastapily) — wymog wlasciciela;
        #   - KONSTRUKCJA (N10, ~400 zn) — zakaz orzekania o nosnosci.
        # RUNDA NAPRAW 2: prog podniesiony 7800 -> 8300. Trzy pozycje, lacznie
        # do ok. 1070 znakow ponad stan po rundzie 1 (ROLA+WYCENA 6816 zn):
        #   - WYMIARY: zastrzezenie, ze wyjasnienie i podsumowanie ida w
        #     OSOBNYCH turach (P1, ~145 zn) — bez niego regula z rundy 1 byla
        #     niewykonalna, bo bramka W3 w tura.py gasi wypowiedz modelu, gdy
        #     w tej samej turze poszlo deterministyczne podsumowanie;
        #   - CENY: zawezenie zakazu do wyceny PRODUKTU i jawna zgoda na
        #     zdanie o obrobce niestandardowej (P2, ~145 zn) — regula bez
        #     zakresu przeczyla prawdziwej adnotacji, ktora podsumowanie
        #     dokleja przy wycieciach;
        #   - KONTAKT (P3/N6, ~475 zn) — bot prosil o e-mail, ktory mial od
        #     pierwszej sekundy rozmowy, z formularza wstepnego widgetu.
        # Do tego dochodzi sekcja DANE KLIENTA skladana w KODZIE
        # (prompty.blok_danych_klienta): do ok. 300 znakow przy maksymalnej
        # dlugosci wszystkich trzech pol (limit `_MAX_DLUGOSC_POLA`). Ten test
        # mierzy prompt BEZ niej (brak kontekstu rozmowy) — wariant z kompletem
        # danych pilnuje test w TestN6KontaktWPrompcieAgentaWyceny nizej.
        # RUNDA NAPRAW 3: prog podniesiony 8300 -> 9500. Dwie pozycje, lacznie
        # 1179 znakow ponad stan po rundzie 2 (ROLA+WYCENA 7586 -> 8765 zn):
        #   - PORÓWNANIE (P1, 1056 zn) — bot obiecywal porownanie wariantow,
        #     dopytywal, dostawal odpowiedz i oddawal rozmowe konsultantowi;
        #     zapytany o cene innego wariantu odsylal do wyboru „w ciemno".
        #     Sekcja mowi, ze porownanie klient zobaczy w WYCENIE (strona
        #     wyceny pokazuje wszystkie osiem wariantow z cenami), ze prosba
        #     o porownanie nie jest powodem do przekazania rozmowy, ze cen
        #     pozostalych wariantow bot NIE MA (policz_wycene je przycina)
        #     i co zrobic, gdy wariant jest niedostepny dla tych wymiarow;
        #   - PYTANIE ZOBOWIAZUJE: przeformulowane zakonczenie (P1, +123 zn) —
        #     zdanie „przekazac rozmowe wolno DOPIERO wtedy, gdy klient
        #     odpowie" model czytal jako licencje na przekazanie PO odpowiedzi,
        #     czyli dokladnie na obserwowana sekwencje: zapytaj, poczekaj,
        #     przekaz.
        # RUNDA NAPRAW 4: prog podniesiony 9500 -> 9950. JEDNA pozycja, 454 znaki
        # ponad stan po rundzie 3 (ROLA+WYCENA 8765 zn + blok 454 zn = 9219 zn):
        #   - NIEZDECYDOWANY KLIENT (P1, 454 zn, `prompty.WYBOR_W_WYCENIE`) —
        #     rozstrzygniecie wlasciciela: „jak klient nie jest zdecydowany na
        #     gatunek czy technologie, to bot sam proponuje pokazanie wszystkich
        #     wariantow – cen – dopiero klient wybiera". Sekcja PORÓWNANIE
        #     z rundy 3 wyzwala sie PROSBA o porownanie, a klient z zywego czatu
        #     o porownanie nie prosil („nie wiem czy dab czy jesion, co
        #     polecasz") — brakowal wiec sam WYZWALACZ i obietnica, ze wyboru
        #     dokona klient na stronie wyceny.
        # Blok jest BRAMKOWANY kanalem (`prompty.blok_wyboru_w_wycenie`
        # + `wysylka.wolno_linkowac`) — na Allegro go NIE MA, wiec ten test
        # mierzy wariant NAJDLUZSZY (bez kontekstu rozmowy persona jest None,
        # a `caps_for(None)` oddaje DEFAULT_CAPS z links=True).
        # PRZEFORMULOWANIE ZAMIAST DOPISYWANIA, tak jak nakazywalo zlecenie:
        # regula w naturalnym brzmieniu miala ok. 600 znakow; skrocona zostala
        # przez ODWOLANIE do sekcji PORÓWNANIE zamiast powtorzenia jej zakazow
        # (zero kwot, zadnego zestawienia w czacie, zadnego przekazania rozmowy).
        # Zadna cudza regula nie zostala skrocona ani wycieta.
        # Prog ma 429 znakow zapasu ponad NAJGORSZY przypadek po tej rundzie
        # (9521 zn = 8765 + 454 + 302 zn sekcji DANE KLIENTA) — praktycznie tyle
        # samo co po rundzie 2 (412) i 3 (433), wiec pilnuje dokladnie tak samo.
        # Kolejne podniesienie ma byc rownie jawne: z lista tego, co doszlo, i po co.
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.instructions) < 9950


class TestAgentWiedzy:
    def test_agent_wiedzy_nie_ma_narzedzi_cenowych(self):
        # Agent wiedzy nie moze przypadkiem zapisac wyceny.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy

    def test_agent_wiedzy_bez_narzedzi_hostowanych_przez_dostawce(self):
        # Ten sam inwariant 1b co dla NARZEDZIA_WYCENY (test_pro_narzedzia.py)
        # — recenzja: dotad sprawdzany tylko dla zestawu agenta Wyceny.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert nazwy & _ZAKAZANE_NARZEDZIA == set()

    def test_agent_wiedzy_ma_handoff_do_wyceny(self):
        # Task 8, B4: przed ta zmiana agenci wyspecjalizowani NIE MIELI wlasnych
        # handoffs (patrz docstring modulu i tura.py) — droga z Wiedzy do Wyceny
        # istniala WYLACZNIE miedzy turami, przez ponowne wejscie przez Router.
        # Skutek: zlozone pytanie w JEDNEJ wiadomosci ("z czego robicie blaty i
        # ile wyjdzie 180x60x4?") nie dostawalo wyceny w tej samej turze, a
        # korekta guardraila (tura.py:_KOMUNIKAT_KOREKTY) wracajaca przez Router
        # mogla trafic do Wiedzy — agenta BEZ policz_wycene, niezdolnego naprawic
        # ceny. Wiedza dostaje wiec WLASNY handoff do Wyceny (nie odwrotnie —
        # patrz brak takiego testu dla agenta Wyceny: to on ma juz kompletny
        # zestaw narzedzi cenowych, nie potrzebuje uciekac donikad).
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {h.name for h in agent.handoffs}
        assert nazwy == {"Wycena"}


class TestAgentPosprzedazowy:
    def test_agent_posprzedazowy_nie_ma_narzedzi_cenowych(self):
        # Tak samo jak agent wiedzy — sprawy indywidualne nigdy nie licza/zapisuja wyceny.
        agent = agenci.zbuduj_agenta_posprzedazowego()
        nazwy = {t.name for t in agent.tools}
        assert "zapisz_wycene" not in nazwy
        assert "policz_wycene" not in nazwy
        assert "oddaj_czlowiekowi" in nazwy

    def test_agent_posprzedazowy_bez_narzedzi_hostowanych_przez_dostawce(self):
        agent = agenci.zbuduj_agenta_posprzedazowego()
        nazwy = {t.name for t in agent.tools}
        assert nazwy & _ZAKAZANE_NARZEDZIA == set()


class TestTracingWylaczonyDomyslnie:
    """U14a (recenzja końcowa): tracing Agents SDK jest w bibliotece włączony
    DOMYŚLNIE i wysyła treść rozmów, argumenty narzędzi i handoffy do backendu
    tracingu OpenAI — TAKŻE w konfiguracji Anthropic przez LiteLLM (w przebiegu
    testów widać to jako `[non-fatal] Tracing client error 401`). Treść rozmów
    to dane klientów; ma być wyłączone domyślnie, włączane świadomie."""

    def _czy_wylaczony(self):
        from agents.tracing import get_trace_provider
        return get_trace_provider()._disabled

    def test_import_modulu_wylaczyl_tracing(self):
        # Efekt wywołania na poziomie modułu `agenci` (import jest na górze pliku).
        assert self._czy_wylaczony() is True

    def test_domyslna_konfiguracja_to_tracing_wylaczony(self):
        import config
        assert config.BOT_PRO_TRACING is False

    def test_swiadome_wlaczenie_dziala(self):
        try:
            agenci.zastosuj_ustawienia_tracingu(True)
            assert self._czy_wylaczony() is False
        finally:
            agenci.zastosuj_ustawienia_tracingu(False)
        assert self._czy_wylaczony() is True


class TestHandoffeRoutera(object):
    def test_handoffy_routera_to_trzej_wlasciwi_agenci(self):
        # handoffs=[...] w Agent() przyjmuje surowe obiekty Agent (nie owinięte
        # w Handoff), więc atrybut to .name, tak samo jak przy zwykłym Agent().
        router = agenci.zbuduj_router()
        nazwy = {h.name for h in router.handoffs}
        assert nazwy == {"Wycena", "Wiedza", "Posprzedaz"}


class TestN6KontaktWPrompcieAgentaWyceny:
    """N6: dane kontaktowe wczytane na starcie tury (`stan.wczytaj_kontakt`)
    muszą DOTRZEĆ do agenta Wyceny — reguła KONTAKT odwołuje się do sekcji
    DANE KLIENTA, więc bez tego doklejenia mówiłaby o czymś, czego nie ma.

    Router ich NIE dostaje: jego budżet to 400 tokenów (test wyżej), a do
    wyboru agenta e-mail klienta nie jest potrzebny."""

    def _z_kontaktem(self, monkeypatch, kontakt):
        monkeypatch.setattr(agenci.stan, "kontakt", lambda: kontakt)

    def test_agent_wyceny_widzi_dane_z_kontaktu_rozmowy(self, monkeypatch):
        self._z_kontaktem(monkeypatch, {"name": "TEST S5", "phone": "",
                                        "email": "test-s5@example.invalid"})
        agent = agenci.zbuduj_agenta_wyceny()
        assert "DANE KLIENTA znane systemowi" in agent.instructions
        assert "test-s5@example.invalid" in agent.instructions

    def test_bez_kontaktu_prompt_wyceny_jest_taki_jak_dotad(self, monkeypatch):
        # Kanaly bez formularza wstepnego (OLX, Allegro) — zaden dopisek.
        # Kotwica to naglowek SEKCJI, nie samo „DANE KLIENTA": ta fraza wystepuje
        # takze w regule KONTAKT, ktora stoi w prompcie zawsze.
        self._z_kontaktem(monkeypatch, {})
        agent = agenci.zbuduj_agenta_wyceny()
        assert "DANE KLIENTA znane systemowi" not in agent.instructions

    def test_router_nie_dostaje_danych_kontaktowych(self, monkeypatch):
        self._z_kontaktem(monkeypatch, {"name": "TEST S5", "phone": "",
                                        "email": "test-s5@example.invalid"})
        router = agenci.zbuduj_router()
        assert "test-s5@example.invalid" not in router.instructions

    def test_prompt_wyceny_z_kontaktem_tez_miesci_sie_w_budzecie(self, monkeypatch):
        # Budzet z TestAgentWyceny mierzy prompt BEZ sekcji DANE KLIENTA (w
        # tescie nie ma kontekstu rozmowy). Sufit ma obejmowac takze wariant
        # z kompletem danych — inaczej pilnowalby czegos, co w produkcji nie
        # wystepuje. Mierzymy NAJGORSZY przypadek: kazde z trzech pol wypelnione
        # do limitu `prompty._MAX_DLUGOSC_POLA`, bo dlugosc wartosci ustala
        # klient (wpisuje je w formularzu wstepnym widgetu), nie my.
        from bots_pro import prompty
        maks = "x" * prompty._MAX_DLUGOSC_POLA
        self._z_kontaktem(monkeypatch, {"name": maks, "email": maks, "phone": maks})
        agent = agenci.zbuduj_agenta_wyceny()
        assert len(agent.instructions) < 9950


class TestP1RegulaWyboruWWycenieBramkowanaKanalem:
    """Runda napraw 4, P1: reguła „klient nie musi wybierać teraz, bo wybierze
    w wycenie" jest obietnicą, która ma pokrycie WYŁĄCZNIE tam, gdzie klient
    dostanie link do wyceny. Na Allegro regulamin zabrania kierowania
    kupującego poza platformę (`ALLEGRO_CAPS['links'] = False`), a wycena idzie
    do konsultanta w prywatnej notatce — obietnica byłaby bez pokrycia.

    Bramkowanie jest DOKŁADNIE takie samo jak dla `podsumowanie.
    ZDANIE_O_WARIANTACH` z rundy 3: `wysylka.wolno_linkowac(stan.persona())`.
    Prompt jest składany raz na turę (`tura.uruchom` -> `zbuduj_router` ->
    `zbuduj_agenta_wyceny`), więc persona tury jest już wtedy ustawiona."""

    def _z_persona(self, monkeypatch, persona):
        monkeypatch.setattr(agenci.stan, "persona", lambda: persona)

    def test_livechat_dostaje_regule(self):
        # Bez kontekstu rozmowy persona jest None -> DEFAULT_CAPS (links=True).
        agent = agenci.zbuduj_agenta_wyceny()
        assert "NIEZDECYDOWANY KLIENT." in agent.instructions

    def test_olx_dostaje_regule(self, monkeypatch):
        # OLX linki DOPUSZCZA — tam link do wyceny jest głównym sposobem
        # przekazania szczegółów (patrz OLX_CAPS w bots/channel_caps.py).
        self._z_persona(monkeypatch, "quote_olx")
        agent = agenci.zbuduj_agenta_wyceny()
        assert "NIEZDECYDOWANY KLIENT." in agent.instructions

    def test_allegro_reguly_NIE_dostaje(self, monkeypatch):
        self._z_persona(monkeypatch, "quote_allegro")
        agent = agenci.zbuduj_agenta_wyceny()
        assert "NIEZDECYDOWANY KLIENT." not in agent.instructions

    def test_reszta_promptu_na_allegro_zostaje_nietknieta(self, monkeypatch):
        # Kontrola negatywna: bramkujemy JEDEN blok, nie okrajamy promptu.
        self._z_persona(monkeypatch, "quote_allegro")
        agent = agenci.zbuduj_agenta_wyceny()
        assert "PORÓWNANIE." in agent.instructions
        assert "KONSTRUKCJA." in agent.instructions

    def test_router_reguly_nie_dostaje(self):
        # Budżet routera to 400 tokenów — reguła handlowa mieszka w agencie Wyceny.
        router = agenci.zbuduj_router()
        assert "NIEZDECYDOWANY KLIENT." not in router.instructions


class TestR5PropozycjaWycenyMaPokrycieWDrodze:
    """Runda napraw 5, P1 — sonda spójności między promptem a składem agentów.

    Reguła „PO ODPOWIEDZI PROPONUJ WYCENĘ" w `prompty.WIEDZA` każe agentowi
    Wiedzy zaproponować wycenę, a po zgodzie klienta przekazać rozmowę
    agentowi o nazwie `Wycena`. Agent Wiedzy sam wyceny nie policzy (nie ma
    ani `policz_wycene`, ani `zapisz_wycene`), więc CAŁE pokrycie tej obietnicy
    leży w handoffie. Gdyby ten handoff kiedykolwiek zniknął — albo gdyby
    agent Wyceny został przemianowany — reguła obiecywałaby klientowi coś,
    czego bot nie zrobi. To dokładnie ta awaria, którą naprawiały rundy 1-4,
    więc pilnuje jej test, a nie tylko komentarz.

    Druga droga (główna, opisana w `tura.py`) jest MIĘDZY turami: zgoda klienta
    przychodzi następną wiadomością i wchodzi od nowa przez Router. Ta sonda
    pilnuje drogi WEWNĄTRZ tury — tej jedynej, której Router nie ratuje, gdy
    odeśle „tak, poproszę" do Wiedzy zamiast do Wyceny."""

    def test_nazwa_agenta_z_reguly_odpowiada_prawdziwemu_przekazaniu(self):
        from bots_pro import prompty
        agent = agenci.zbuduj_agenta_wiedzy()
        assert "przekaż rozmowę agentowi Wycena" in prompty.WIEDZA
        assert "Wycena" in {h.name for h in agent.handoffs}

    def test_agent_wiedzy_nadal_nie_liczy_wyceny_sam(self):
        # Kontrola negatywna do testu wyżej: reguła nie jest realizowalna
        # z pozycji Wiedzy, więc handoff nie jest wygodą, tylko warunkiem.
        agent = agenci.zbuduj_agenta_wiedzy()
        nazwy = {t.name for t in agent.tools}
        assert "policz_wycene" not in nazwy
        assert "wyslij_podsumowanie" not in nazwy
