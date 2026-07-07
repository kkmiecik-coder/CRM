# WoodPower — plan bazy wiedzy Help Center (dla bota live-chat)

> Status: **WSZYSTKIE ARTYKUŁY NAPISANE** — 2026-07-02 (72 pliki w `docs/help-center/articles/`;
> v4 miała 73 numeracji: art. 47 i 49 pominięte, art. 55a dodany). Wszystkie §5 OTWARTE rozstrzygnięte.
> Format: gęsto-faktograficzny dla bota (§2). Pliki `.md` w `docs/help-center/articles/NN-slug.md`.
> **AUDYT + POPRAWKI 2026-07-03**: pełny audyt w `docs/help-center/AUDYT.md`, wszystkie sekcje 1–6
> wdrożone (odpowiedzi właściciela); dodane art. **74–77** (czego nie wykonujemy / na zewnątrz /
> min. wymiary / waga-gęstość) → razem **76 artykułów**. Nowe fakty od właściciela: gwarancja liczona
> OD ODBIORU; raty przez Przelewy24; wysyłka zagraniczna TYLKO kurierem po UE; zaokrąglenie R1–R10 mm;
> próbki/showroom do obejrzenia w Bachórzu; bez docięcia = produkt z naddatkiem (spadem); konstrukcje
> metalowe schodów poza ofertą. ⚠️ UTRZYMANIE: art. 61 opisuje UI kalkulatora — aktualizować przy
> każdej zmianie kalkulatora.
> **POZOSTAJE: publikacja do Centrum Pomocy Chatwoot** (portal `woodpower`, MD→HTML) + `sync_index` (§8).

---

## 1. Cel i kontekst

Baza wiedzy zasila **RAG bota live-chat** (`integrations/chat_bridge/bots/knowledge.py` →
`kb_chunks`, cosine). Bot pobiera top-K fragmentów najbliższych zapytaniu i odpowiada
wyłącznie na ich podstawie. Te same artykuły widzą klienci w Centrum Pomocy.

**Jak bot konsumuje treść:** `core/chatwoot.py::cw_articles(slug)` pobiera opublikowane
artykuły portalu i robi `html_to_text(content)`. Chatwoot trzyma treść jako **HTML**;
dla bota format jest obojętny (i tak strippuje do tekstu). Dlatego autoring w **Markdown**
jest OK — przy publikacji albo wklejamy MD do edytora Chatwoota (konwertuje formatowanie),
albo pushujemy przez API konwertując MD→HTML.

## 2. Zasady pisania (format KB tylko-dla-bota — decyzja 2026-07-02)

> **Kontekst decyzji:** portal Centrum Pomocy NIE jest czytany przez klientów — to wyłącznie
> magazyn danych dla RAG bota (`bots/knowledge.py::retrieve()` → top-5 chunków `BOT_RETRIEVAL_K=5`
> → LLM układa własną odpowiedź w głosie persony). Klient nigdy nie widzi tych zdań w tej formie.
> Dlatego piszemy **gęsto i faktograficznie**, nie prozą.

- **Jeden temat = jeden artykuł**, 1–3 akapity (mieści się w 1 chunku; chunk = max 1800 znaków,
  cięcie po akapicie `\n\n`).
- **Tytuł i pierwsze zdanie wprost nazywają temat** („Grubości blatów — …") — kotwica retrievalu
  (tytuł jest doklejany do treści przed chunkowaniem, więc jego słowa też liczą się do dopasowania).
- **Powtarzaj kluczowy rzeczownik (produkt/temat) w każdym akapicie** — chunki dopasowywane
  niezależnie; zaimki są dla retrievalu niewidzialne.
- **Osobne artykuły per produkt** („Grubości blatów" vs „Grubości parapetów") — klient pyta słowami produktu.
- **Rozdział tematów — nie dubluj przekrojowych zagadnień:** artykuły o gatunku (dąb/jesion/buk)
  opisują TYLKO właściwości drewna (twardość, wygląd, zastosowania) — bez klas i technologii
  (mają własne artykuły 10–13). Framing „naturalna cecha ≠ wada/reklamacja" trzymamy w art. 69 (Reklamacje).
- **Fakty wprost i gęsto** — krótkie zdania oznajmujące lub zwarte listy; liczby, zakresy i
  wyliczenia podane jawnie (łatwa ekstrakcja przez LLM, mniej parafraz). Chudy wpis = więcej
  różnych tematów mieści się w tych samych 5 slotach top-K.
- **Tniemy uprzejmościowy balast** — bez „chętnie doradzimy", „Zapraszamy do kontaktu",
  „jeśli nie są Państwo pewni". Zero wartości dla dopasowania, zjada budżet top-5.
- **Bez pre-stylizacji „Państwo"** — piszemy neutralnie/rzeczowo („wykonujemy", „oferujemy").
  Głos (na OLX/Allegro 1. os. l. poj.) nakłada persona; sztywne „Państwo" w źródle może z nią kolidować.
- **Myślniki dozwolone** — reguła „zero myślników" dotyczyła copy do klienta; źródła KB klient nie czyta.
- **Surowe URL-e jako tekst** (nie tylko link Markdown) — żeby przetrwały `html_to_text` i bot mógł je podać.
- **Bez meta-odsyłaczy** typu „opisujemy w osobnym artykule" — bot sam pobierze potrzebny artykuł; odsyłacz to balast.
- **Bez mega-FAQ** — rozbijać na wpisy tematyczne.
- **NIGDY nie podajemy konkretnych cen** — wycena zawsze indywidualna.

## 3. Decyzje produktowe (ustalone)

- **Gatunki:** dąb, jesion, buk (brzoza/sosna w SKU = legacy, pomijamy).
- **Technologie: 2** — `lite` i `mikrowczep`. „Klejonka" to **nie** technologia, tylko wspólny
  sposób budowy: wszystkie produkty z lameli 4×4 cm klejonych. „Lity" ≠ jeden kawałek drewna.
  - **Lite** — lamele ~4 cm klejone **wyłącznie na szerokości**; jednolity układ słojów,
    wysoka wytrzymałość i odporność mechaniczna, stabilność.
  - **Mikrowczep** — krótkie lamele/klepki ~4 cm klejone **na długości i szerokości**;
    stabilność, odporność na pękanie.
- **Klasy: 2** — `A/B` i `B/B`.
  - **A/B** — strona A najczęściej bezsęczna (możliwe pojedyncze sęki szpilkowe do ⌀5 mm);
    strona B sęki zdrowe do ⌀40 mm.
  - **B/B** — obie strony sęki do ⌀40 mm, zdrowe lub wypełnione szpachlą w kolorze
    naturalnym lub czarnym.
  - **Dostępność:** A/B dla wszystkich gatunków; **B/B tylko dąb**.
- **Schody** — pełny rozkład per element (terminologia z diagramu: stopień/trep, podstopień,
  stopień zabiegowy, podest, policzek/wanga, poręcz, tralka, słup).
- **Wosk / lazura** — NIE oferujemy (kody `WOS`/`LAZ` w SKU = legacy).
- **Fazowanie krawędzi:** kąty **45° lub 60°** (ustalone przez właściciela; kod kalkulatora
  3–10° = do zignorowania w treści artykułu).
- **Telefony:** główny **+48 690 009 890**, drugi **+48 793 911 916**. Numerów **nie
  rozdzielamy** per temat/wiadomość (numer 690 002 109 z draftu = nieaktualny).

## 4. Zatwierdzona lista (v4 — 73 artykuły)

Legenda: 🔒 = wymaga danych spoza kodu. „(mamy)" = pokryte draftem (§6), do potwierdzenia
aktualności. „OTWARTE" = realnie do zebrania (§5).

### A. O firmie i drewnie
1. WoodPower — kim jesteśmy i co produkujemy
2. WoodPower — kontakt, adres i godziny pracy
3. Dodatkowe usługi i produkty (suszenie kontraktowe, sprzedaż desek, worki opałowe)
4. Drewno w WoodPower — pochodzenie, suszenie i wilgotność 🔒 (mamy: własne suszarnie, 8–10%)
5. Naturalne cechy drewna — sęki, słoje, praca drewna
6. Dąb — właściwości drewna
7. Jesion — właściwości drewna
8. Buk — właściwości drewna
9. Klejonka i lamele — z czego powstają nasze produkty
10. Technologia: drewno lite
11. Technologia: mikrowczep
12. Klasy drewna A/B i B/B — różnice
13. Dostępność gatunków, klas i technologii (macierz oferty) ✅ (A/B wszystkie gatunki, B/B tylko dąb; obie technologie lite+mikrowczep dla wszystkich gatunków i klas — potw. 02.07)

### B. Wykończenia
14. Wykończenia drewna w WoodPower — przegląd
15. Surowe (niewykończone) drewno — kiedy wybrać
16. Olejowanie — na czym polega
17. Lakierowanie — mat i połysk
18. Bejcowanie i kolory — paleta ✅ (popiel, beż, brunat, orzech, brąz; kolor tylko z lakierem mat/półmat, olej nie barwiony — potw. 02.07)

### C. Blaty
19. Blaty drewniane na wymiar — zakres oferty
20. Blaty — wybór gatunku (dąb, jesion, buk)
21. Grubości blatów ✅ (grupy zastosowań z grubościami: dekor. 1,5–2,5 / biurka 2–3 / użytkowe 3–4 cm; >4 indyw. — potw. 02.07)
22. Blaty — technologie (lite i mikrowczep)
23. Blaty — klasy drewna A/B i B/B
24. Blaty — wykończenia
25. Blaty — wycięcia pod zlew, płytę i baterię
26. Blaty — kształty i nietypowe formy
27. Blaty — zastosowania (kuchnia, jadalnia, stolik, biurko, łazienka)
28. Blaty — montaż i wzmocnienie *(dot. gwarancji; z draftu)*

### D. Parapety
29. Parapety drewniane wewnętrzne — zakres oferty
30. Parapety — wybór gatunku (dąb, jesion, buk)
31. Grubości parapetów ✅ (2,5–4 cm, standard 3 cm, >4 cm indywidualnie — potw. 02.07)
32. Parapety — technologie (lite i mikrowczep)
33. Parapety — klasy drewna
34. Parapety — wykończenia
35. Parapety — docięcie do wnęki, wycięcia, kształty
36. Parapety — montaż i zastosowania wewnętrzne ✅ (tylko dostawa, montaż po stronie klienta; zastosowania: pod okno / siedzisko / półka-blat / nietypowe wnęki — potw. 02.07)

### E. Schody (pełno, per element)
37. Schody drewniane WoodPower — zakres oferty
38. Rodzaje schodów ✅ (na konstrukcji metalowej, półkowe, na beton, policzkowe, spiralne, dywanowe — potw. 02.07)
39. Trepy (stopnie schodowe)
40. Podstopnice (podstopnie)
41. Stopnie zabiegowe
42. Podesty i spoczniki
43. Policzki (wangi)
44. Poręcze drewniane
45. Tralki
46. Słupy schodowe
47. ~~Elementy wykończeniowe schodów (listwy, cokoły)~~ ❌ POMINIĘTY 02.07 — WoodPower NIE robi osobnych elementów wykończeniowych; fakt scalony do art. 37. (efektywnie 72 artykuły)
48. Schody — wybór gatunku (dąb, jesion, buk)
49. ~~Schody — grubości i wymiary elementów~~ ❌ POMINIĘTY 02.07 — dublet; grubość trepu w art. 39, limity wymiarów w art. 54 (maks. wymiary). (efektywnie 71 artykułów)
50. Schody — wykończenia
51. Schody — klasy i technologia drewna ✅ (jak reszta: obie technologie + A/B wszystkie, B/B tylko dąb — potw. 02.07)
52. Schody — pomiar, wycena i montaż ✅ (NIE mierzymy, NIE montujemy — gotowy produkt na wymiar + wysyłka; wymiary od klienta — potw. 02.07)

### F. Personalizacja i obróbka
53. Docięcie do wymiaru
54. Maksymalne wymiary produktów WoodPower (limity) ✅ (dł. max 500 cm mikrowczep / 450 cm lite; szer. max 120 cm; blaty=parapety=schody — potw. 02.07)
55. Wycięcia i otwory (pod zlew, gniazdka, rury)
55a. Obróbka krawędzi — przegląd (ostra / fazowana / zaokrąglona) ✅ DODANY 02.07
56. Obróbka krawędzi — fazowanie (45° lub 60°)
57. Obróbka krawędzi — zaokrąglenie (promień R)
58. Nietypowe kształty (koło, trójkąt, trapez, wielokąt)

### G. Wycena i zamówienie
59. Jak działa wycena w WoodPower (indywidualna, bez cen)
60. Co jest potrzebne do wyceny
61. Kalkulator online — jak korzystać
62. Jak złożyć zamówienie
63. Płatności i faktura 🔒 (mamy: pełne dane, §6)

### H. Dostawa i realizacja
64. Dostawa — cała Polska (kurier / własny transport) 🔒 (mamy)
65. Czas realizacji zamówienia 🔒 (mamy: 16–21 dni surowe / 28–30 dni z obróbką)
66. Pakowanie i transport wielkogabarytowy 🔒 (mamy: własny transport, bez wnoszenia)
67. Odbiór osobisty w Bachórzu ✅ (możliwy, w godz. pracy biura pn–pt 8:00–16:00; Bachórz 14N — potw. 02.07)

### I. Po sprzedaży i pielęgnacja
68. Gwarancja na produkty WoodPower 🔒 (mamy: 24 mies. + wyłączenia)
69. Reklamacje i zwroty 🔒 (mamy: pełne dane)
70. Pielęgnacja blatów drewnianych (mamy: pełna treść)
71. Pielęgnacja parapetów drewnianych
72. Pielęgnacja schodów drewnianych
73. Próbki drewna i wykończeń ✅ (oferujemy, ale TYLKO po kontakcie z agentem; sposób udostępnienia indywidualnie — potw. 02.07)

## 5. Dane wciąż OTWARTE (do zebrania od właściciela)

1. ~~Maksymalne wymiary produktów~~ ✅ ROZSTRZYGNIĘTE 02.07: dł. max **500 cm mikrowczep / 450 cm lite**, szer. max **120 cm**; te same limity dla blatów, parapetów i schodów.
2. ~~Grubości parapetów~~ ✅ ROZSTRZYGNIĘTE 02.07: 2,5–4 cm, standard 3 cm, >4 cm indywidualnie.
3. ~~Parapety — montaż i zastosowania~~ ✅ ROZSTRZYGNIĘTE 02.07: **tylko dostawa** (montaż po stronie klienta); zastosowania: pod okno / siedzisko we wnęce / półka-blat / nietypowe wnęki.
4. ~~Schody — rodzaje~~ ✅ ROZSTRZYGNIĘTE 02.07: na konstrukcji metalowej, półkowe, na beton, policzkowe, spiralne, dywanowe. (opisy „półkowe"/„dywanowe" do finalnej weryfikacji właściciela)
5. ~~Schody — grubości i wymiary elementów~~ ✅ ROZSTRZYGNIĘTE 02.07: art. 49 pominięty (dublet); limity w art. 54, grubość trepu w art. 39.
6. ~~Schody — elementy wykończeniowe~~ ✅ ROZSTRZYGNIĘTE 02.07: **NIE robimy** osobnych listew/cokołów/maskownic (fakt w art. 37, art. 47 pominięty).
7. ~~Schody — pomiar, wycena i montaż~~ ✅ ROZSTRZYGNIĘTE 02.07: **NIE mierzymy, NIE montujemy** (zasada ogólna dla wszystkich produktów) — wykonujemy gotowy produkt i wysyłamy; wymiary podaje klient.
8. ~~Odbiór osobisty w Bachórzu~~ ✅ ROZSTRZYGNIĘTE 02.07: możliwy, w godzinach pracy biura (pn–pt 8:00–16:00).
9. ~~Próbki drewna i wykończeń~~ ✅ ROZSTRZYGNIĘTE 02.07: oferujemy, ale **tylko po kontakcie z agentem** (sposób udostępnienia indywidualnie).
10. **Adres** — ✅ ROZSTRZYGNIĘTE 2026-07-02: **36-068 Bachórz 14N** (potwierdził właściciel).

## 6. Fakty zebrane z istniejącego draftu (źródło: `docs/help-center-articles-draft.md`)

> Treść obecnych 17 artykułów („do wyrzucenia", ale dane aktualne wg właściciela).
> Do potwierdzenia, że nadal aktualne przy pisaniu.

**Drewno / produkcja**
- Suszenie we własnych suszarniach do wilgotności **~8–10%**.
- Drewno naturalne: różnice koloru/słojów; dopuszczalne wygięcie **±2–3 mm/m**.
- Preparaty: lakier **Adler**, olej **Osmo**, bejca **Sopur**, klej **Meblocoll**.

**Grubości / klasy**
- Blaty: grubość **1,5–4 cm**; powyżej 4 cm — indywidualna weryfikacja.
- Orientacyjne grubości blatów wg grup zastosowań (potw. 02.07): dekoracyjne/lekko obciążone
  (półki, stoliki kawowe, stoliki pomocnicze) **1,5–2,5 cm**; biurka/toaletki **2–3 cm**;
  użytkowe/obciążone (kuchenne, robocze, jadalniane/stoły, łazienkowe, barowe/wyspy) **3–4 cm**.
- Parapety: grubość **2,5–4 cm**, standard **3 cm**, >4 cm indywidualnie (potw. 02.07).
- **Maksymalne wymiary** (potw. 02.07, blaty=parapety=schody): dł. max **500 cm mikrowczep / 450 cm lite**, szer. max **120 cm**.
- Stopnie/trepy 3–4 cm (dot. schodów, nie blatów).
- **Blaty łazienkowe:** wszystkie gatunki OK, ale **zalecane lakierowanie** powierzchni (wilgoć) — do art. 24/27.
- Klasy: A/B dla wszystkich gatunków; **B/B tylko dąb**.

**Wykończenia** (model potwierdzony 02.07)
- **Surowe** — bez wykończenia powierzchni.
- **Olejowane** (Osmo) — zawsze naturalny kolor drewna; olejowanych **NIE barwimy**.
- **Lakierowane** (Adler) — bezbarwne lub barwne; nakładane **natryskowo, w podwójnej warstwie** (potw. 02.07).
- **Kolor = tylko z lakierem:** bejca (Sopur) nadaje kolor, na wierzch lakier mat/półmat. Paleta (kody Sopur, potw. 02.07): **Popiel 20-07, Beż BN-125/09, Brunat 22-05/22-10/22-15/22-23, Orzech 22-66/22-74, Brąz 22-50**. Kolory **niestandardowe (spoza palety)** = tylko przy większych ilościach zamówienia.
- **Mat/połysk dotyczy tylko lakieru** (na powierzchni bejcowanej: mat lub półmat).
- **NIE oferujemy** wosku ani lazury (kody WOS/LAZ = legacy).

**Obróbka krawędzi**
- Ostra (prosta) / **fazowana 45° lub 60°** / zaokrąglona (promień R). *(kąty potwierdzone 2026-07-02)*

**Kształty / CNC** (potw. 02.07)
- Prostokątne, okrągłe, zaokrąglone; dzięki **maszynie CNC dowolny kształt** na życzenie klienta (dot. blatów, parapetów, nietypowych kształtów).

**Czas realizacji**
- Surowe: **16–21 dni kalendarzowych**. Z obróbką powierzchni: **28–30 dni kalendarzowych**.

**Zakres usługi** (potw. 02.07) — WAŻNE, dotyczy WSZYSTKICH produktów
- WoodPower **NIE mierzy u klienta i NIE montuje**. Wykonujemy gotowy produkt na wymiar i **wysyłamy**.
  Wymiary podaje klient; montaż po stronie klienta lub jego ekipy. Bot NIGDY nie obiecuje pomiaru ani montażu.

**Dostawa** (korekta 02.07)
- Cała Polska. Kurier (różne firmy) + **własny transport zależny od bieżących zamówień/tras** (NIE od wielkości — korekta 02.07).
- **Większe zamówienia na paletach.** Koszt dostawy indywidualny.
- USUNIĘTE z KB 02.07: „przekładki/listewki min. 2 cm" (właściciel nie potwierdza pakowania) oraz „bez wnoszenia do wnętrza".

**Płatności / faktury**
- Przelew, **Przelewy24** (BLIK, Apple Pay, Google Pay). Proforma dla e-mail/OLX; Allegro — bramka Allegro.
- **B2C** — płatność z góry. **B2B (znany klient)** — zaliczka **30%** + reszta przy odbiorze.
  - ⚠️ DECYZJA 02.07: w KB/bocie piszemy TYLKO „pełna opłata z góry" — zaliczki B2B **nie reklamujemy** publicznie (art. 63).
- Faktura VAT lub e-paragon. **Brak minimum zamówienia.** Rabaty przy stałej współpracy.

**Kontakt**
- Telefony: główny **+48 690 009 890**, drugi **+48 793 911 916** (nie rozdzielane per temat).
- **Kalkulator online (publiczny):** https://crm.woodpower.pl/kalkulator (do art. 59/61, surowy URL w treści).
- E-mail: biuro@woodpower.pl; reklamacje: reklamacje@woodpower.pl. Godziny pn.–pt. 8:00–16:00.
- Firma: Wood Power Sp. z o.o., 36-068 Bachórz 14 / 14N (adres do potwierdzenia — §5.10).

**Gwarancja / reklamacje / zwroty**
- Gwarancja **24 miesiące** na produkty z litego drewna (wyłączenia: naturalne cechy, uszkodzenia
  użytkowe, zły montaż, wycieranie olejów/wosków).
- Reklamacje: reklamacje@woodpower.pl, biuro@woodpower.pl, telefonicznie, formularz, pisemnie.
  Transport — zgłaszać w dniu odbioru. Termin: 14 dni (konsument) / do 30 dni (pozostali).
- Zwroty: produkty na wymiar **wyłączone z prawa odstąpienia** (art. 38 pkt 3 u.p.k.);
  zmiana/anulacja tylko do rozpoczęcia realizacji.

**Pielęgnacja / montaż blatu**
- Codzienna pielęgnacja, warunki (17–23°C, wilgotność 30–40%), po rozpakowaniu.
- Montaż i wzmocnienie: wsporniki w poprzek lameli, max 6 cm od krawędzi, co ≤100 cm;
  brak wzmocnienia = utrata gwarancji. Karta informacyjna dołączana do zamówienia.

**Dodatkowe usługi**
- Suszenie usługowe/kontraktowe, sprzedaż desek, worki opałowe.

## 7. Rozbieżności — status

1. **Kąty fazowania** — ROZSTRZYGNIĘTE: **45° lub 60°** (kod 3–10° ignorujemy).
2. **Telefony** — ROZSTRZYGNIĘTE: główny 690 009 890, drugi 793 911 916, nie rozdzielane per temat.
3. **Adres** — ROZSTRZYGNIĘTE 2026-07-02: **36-068 Bachórz 14N** (potwierdził właściciel).

## 8. Plan następnej sesji

1. ✅ ZROBIONE 02.07: wszystkie 72 artykuły napisane (`docs/help-center/articles/`), zaakceptowane przez właściciela.
2. ✅ ZROBIONE 02.07: wszystkie 10 pozycji OTWARTYCH (§5) zebrane i rozstrzygnięte.
3. **DO ZROBIENIA: Publikacja do Chatwoota** — portal `woodpower`, każdy plik jako artykuł (MD→HTML:
   wklejenie do edytora Chatwoota LUB push przez API z konwersją). Po publikacji `sync_index`
   (`integrations/chat_bridge/bots/knowledge.py`) przebuduje `kb_chunks` z opublikowanych artykułów.
   UWAGA: bot indeksuje tylko **opublikowane** artykuły portalu o slugu `BOT_HELP_CENTER_SLUG`.
4. Po publikacji: E2E test bota (pytania klientów → czy trafia w artykuły, czy nie zmyśla, czy podaje linki
   kalkulatora/mapy). Ewentualne korekty treści wg trafień retrievalu.
