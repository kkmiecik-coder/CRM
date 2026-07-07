# Audyt bazy wiedzy Help Center — raport redakcyjny (2026-07-02)

> ✅ **WDROŻONE 2026-07-03** — wszystkie sekcje 1–6 zrealizowane po odpowiedziach właściciela
> (6 sub-agentów, 1 na sekcję). Sekcja 4: dodane art. 74–77 + dopiski w 13/14/57/63; luka „jak mierzyć"
> świadomie POMINIĘTA (decyzja właściciela — ryzyko złego pomiaru wg instrukcji bota). Fakty rozstrzygnięte:
> gwarancja od ODBIORU; raty Przelewy24 TAK; zagranica tylko kurier UE; R1–R10 mm; showroom próbek w Bachórzu;
> 30 lat/20 000 m²/polskie lasy/30–40% wilgotności — POTWIERDZONE; „dąb najtwardszy" → przeformułowane
> na „najtrwalszy, jeden z najtwardszych". Raport poniżej = stan sprzed poprawek (archiwalny).

> Zakres: 72 artykuły w `docs/help-center/articles/` + INDEX.md, porównane z faktami z PLAN.md
> i listą źródła prawdy. Cel: wsad do przeredagowania PRZED publikacją do Chatwoota.
> Kontrola techniczna: **wszystkie artykuły ≤ 1139 B** → każdy = 1 chunk (limit 1800). ✓
> Tytuły i pierwsze zdania nazywają temat we wszystkich artykułach. ✓ Zero cen. ✓
> Zero obietnic pomiaru/montażu. ✓ URL-e surowe (02, 59, 61). ✓ Zero meta-odsyłaczy. ✓

---

## 1. SPRZECZNOŚCI FAKTÓW

### 1.1 Barwny lakier „z połyskiem" — sprzeczność 24/34/50 z 17/18 ⚠️ WYSOKI PRIORYTET
Źródło prawdy: kolor = bejca + lakier **mat lub półmat** (połysk tylko dla bezbarwnego).
- `17-lakierowanie-mat-polysk.md` (poprawnie): „wykończenie barwne uzyskujemy, bejcując drewno na wybrany kolor i pokrywając je lakierem **matowym lub półmatowym**"
- `18-bejcowanie-i-kolory.md` (poprawnie): „na powierzchnię bejcowaną nakładamy lakier matowy lub półmatowy"
- `24-blaty-wykonczenia.md`, `34-parapety-wykonczenia.md`, `50-schody-wykonczenia.md` (błędnie sugerują):
  „lakier (Adler) tworzy twardą powłokę ochronną, **w wariancie matowym lub z połyskiem; bezbarwny albo barwny** (kolor z palety bejc)"
  → chunk czytany samodzielnie pozwala botowi obiecać **barwny lakier z połyskiem**.

**Poprawka (w 24/34/50, jednakowo):**
> „…lakier (Adler) tworzy twardą powłokę ochronną; bezbarwny w wariancie matowym lub z połyskiem, albo barwny (bejca z palety + lakier matowy lub półmatowy)."

### 1.2 Klasy „A/B i B/B" bez zastrzeżenia „B/B tylko dąb" w chunkach zakresowych ⚠️ WYSOKI PRIORYTET
Macierz: B/B wyłącznie dąb. Chunki są dopasowywane niezależnie, a te trzy mówią samodzielnie:
- `19-blaty-zakres-oferty.md`: „w trzech gatunkach (dąb, jesion, buk) … oraz **w klasach drewna A/B i B/B**"
- `29-parapety-zakres-oferty.md`: identyczna konstrukcja
- `37-schody-zakres-oferty.md`: identyczna konstrukcja
→ bot na podstawie samego chunku 29 zaoferuje „parapet jesionowy w klasie B/B".

**Poprawka (w 19/29/37):** po „w klasach drewna A/B i B/B" dopisać „**(klasa B/B wyłącznie dla dębu)**".

---

## 2. BŁĘDY MERYTORYCZNE / NIEPOTWIERDZONE TWIERDZENIA

### 2.1 „Dąb — najtwardszy z oferowanych gatunków" — merytorycznie wątpliwe ⚠️
Powtórzone w 5 artykułach:
- `06-dab-wlasciwosci.md`: „Dąb jest najtwardszym z oferowanych gatunków (dąb, jesion, buk)."
- `20-blaty-wybor-gatunku.md`: „Blat dębowy — najtwardszy i najbardziej wytrzymały z gatunków"
- `27-blaty-zastosowania.md`: „polecamy przede wszystkim dąb — najtwardszy z gatunków"
- `30-parapety-wybor-gatunku.md`, `48-schody-wybor-gatunku.md`: analogicznie.

Wg twardości Brinella jesion (~4,0) i buk (~3,8) są porównywalne lub twardsze od dębu (~3,4).
Przewaga dębu to **trwałość i odporność** (garbniki, odporność biologiczna, stabilność), nie sama twardość.
Bot będzie tę tezę autorytatywnie powtarzał. Do decyzji właściciela; jeśli to świadomy przekaz handlowy — zostawić.

**Proponowana poprawka (bezpieczna merytorycznie):**
> „Dąb — najtrwalszy i najbardziej odporny na warunki użytkowania gatunek w ofercie; jeden z najtwardszych."
(analogicznie w 20/27/30/48; w 27 rekomendację dębu oprzeć na trwałości, nie twardości)

### 2.2 `01-woodpower-kim-jestesmy.md` — liczby spoza źródła prawdy
Cytat: „30 lat doświadczenia … 20 000 m², w tym 3 500 m² hal produkcyjnych".
Brak tych faktów w PLAN.md §6. Prawdopodobnie ze strony www — **potwierdzić u właściciela** (zwłaszcza „30 lat", bo się starzeje).

### 2.3 `04-drewno-pochodzenie-suszenie-wilgotnosc.md` — pochodzenie drewna
Cytat: „Drewno WoodPower pochodzi z polskich lasów oraz od lokalnych dostawców."
Plan potwierdza tylko: własne suszarnie, 8–10%. Pochodzenie — **niepotwierdzone, do weryfikacji**.

### 2.4 `64-dostawa-cala-polska.md` — zakres dostawy własnym transportem
Cytat: „Dostawa własnym transportem realizowana jest do miejsca dostępnego dla pojazdu dostawczego."
Decyzją 02.07 usunięto z KB „bez wnoszenia do wnętrza" (właściciel nie potwierdził) — to zdanie
tylnymi drzwiami wprowadza deklarację zakresu dostawy. **Potwierdzić albo usunąć zdanie.**

### 2.5 `53-dociecie-do-wymiaru.md` — „docięcie domyślne" vs opcja w kalkulatorze
Cytat: „Domyślnie wszystkie produkty docinamy na wymiar. Tylko na wyraźne polecenie klienta dostarczamy produkt bez docięcia".
W kalkulatorze/produkcji „Docięcie do wymiaru" to **osobne pole/opcja** (pomija formatowanie po klejeniu).
Sprawdzić, czy semantyka artykułu (docięcie = darmowy standard, brak docięcia = wyjątek) zgadza się
z tym, jak opcja działa w wycenie — jeśli docięcie bywa pozycją płatną, bot wprowadzi klienta w błąd.

### 2.6 `70-pielegnacja-blatow.md` — wilgotność 30–40%
Cytat: „temperatura około 17–23°C, wilgotność powietrza około 30–40%".
Zgodne z draftem/Kartą, ale nietypowe (standardowe zalecenia dla drewna: 40–60%; 30% to dolna granica ryzyka pęknięć).
**Zweryfikować z aktualną Kartą informacyjną** — bot będzie te liczby podawał wprost.

### 2.7 `15-surowe-drewno-kiedy-wybrac.md` — instrukcja wykonawcza
Cytat: „nałożyć lakier lub olej, co najmniej dwa razy z każdej strony … lekko przeszlifować drobnym papierem ściernym".
Porada techniczna o skutkach gwarancyjnych (złe zabezpieczenie → wygięcie). Potwierdzić zgodność z Kartą informacyjną.

---

## 3. PROBLEMY Z RETRIEVALEM

### 3.1 Dosłowny duplikat akapitu „praca drewna" w 04 i 05 ⚠️
`04-…-wilgotnosc.md` i `05-naturalne-cechy-drewna.md` zawierają niemal identyczny akapit
(„reaguje na zmienne warunki … ±2–3 mm na metr … nie wadą"). Zapytanie o pracę/wyginanie drewna
ściągnie OBA chunki → strata jednego z 5 slotów top-K.
**Poprawka:** w 04 zostawić tylko pochodzenie+suszenie+wilgotność i jedno zdanie:
> „Drewno o wilgotności 8–10% pozostaje materiałem naturalnym i pracuje przy zmianach temperatury i wilgotności powietrza."
Pełny akapit z ±2–3 mm/m — wyłącznie w 05.

### 3.2 `25-blaty-wyciecia.md` ↔ `55-wyciecia-i-otwory.md` — niemal identyczna treść
Oba: zlew/płyta/bateria/gniazdka + „potrzebujemy wymiarów i położenia, opis lub szkic, wycena indywidualna".
Zapytanie „wycięcie pod zlew w blacie" pobierze oba → slot stracony.
**Poprawka:** zróżnicować — w 55 usunąć przykłady blatowe (zlew/płyta/bateria), zostawić ogólną zasadę
+ przykłady nieblatowe (rury grzewcze w parapetach, gniazdka w blatach biurek, przejścia instalacji),
albo scalić 55 w 25/35 i usunąć 55.

### 3.3 `26-blaty-ksztalty.md` ↔ `58-nietypowe-ksztalty.md` — j.w.
Ta sama treść (CNC, dowolny kształt, szkic/szablon, wycena indywidualna); 58 dodaje tylko listę figur.
**Poprawka:** w 26 zostawić specyfikę blatów (prostokątny/okrągły/zaokrąglony), w 58 listę figur
+ wskazanie, że dotyczy blatów, parapetów i elementów schodów (jest); usunąć z 58 zdania powtórzone 1:1
(o szkicu/szablonie zostawić w obu — to kluczowa informacja operacyjna — ale przeredagować innymi słowami,
żeby cosine ich nie sklejał).

### 3.4 `51-schody-klasy-i-technologia.md` — dwa tematy w jednym artykule
Blaty i parapety mają klasy (23/33) i technologie (22/32) osobno; schody łącznie. Chunk < 1800, więc działa,
ale zapytanie „schody mikrowczep" konkuruje z 10/11/22/32. Akceptowalne — tylko odnotowane, bez zmiany.

### 3.5 Kotwice tytułów — OK
Wszystkie tytuły + pierwsze zdania nazywają temat; kluczowy rzeczownik powtarzany w akapitach
(wzorowo w 39–46: każdy element schodów nazwany w każdym akapicie).

---

## 4. LUKI (pytania klienta bez pokrycia)

1. **„Czego NIE robimy"** — brak artykułu negatywnego. Pytania: „czy robicie podłogi / deski tarasowe /
   drzwi / fronty meblowe / gotowe meble / nogi i stelaże do stołów?" → bot nie ma żadnego chunku,
   ryzyko halucynacji „tak". Jedyna negacja w KB: listwy/cokoły (art 37) i wykończenia (art 14).
   **Propozycja: nowy artykuł „Czego WoodPower nie wykonuje"** (fakty do potwierdzenia z właścicielem):
   podłogi, drzwi, meble gotowe, stelaże/nogi, konstrukcje metalowe schodów, montaż, pomiar u klienta.
2. **Wosk i lazura** — plan mówi „NIE oferujemy", żaden artykuł nie mówi tego wprost (art 14 tylko
   „Nie oferujemy innych wykończeń"). Pytanie „czy macie blaty woskowane?" nie ma kotwicy „wosk".
   **Poprawka w 14:** dopisać „Nie oferujemy woskowania (wosku) ani lazury."
3. **Inne gatunki** — „czy macie sosnę / brzozę / orzech amerykański / egzotyk?" — art 13 wymienia ofertę,
   ale bez negacji. **Poprawka w 13:** „Innych gatunków (np. sosna, brzoza, orzech, drewno egzotyczne) nie oferujemy."
4. **Wysyłka za granicę** — jest tylko „cała Polska". Pytanie „czy wyślecie do Niemiec?" bez odpowiedzi. 🔒 fakt od właściciela.
5. **Produkty na zewnątrz** — „blat na taras / schody zewnętrzne / parapet zewnętrzny?" Parapety mają
   „wewnętrzne", blaty i schody nic. 🔒 fakt od właściciela (podejrzewam: tylko wnętrza).
6. **Jak mierzyć** — skoro wymiary podaje klient, brak artykułu „jak zmierzyć parapet/blat/schody"
   (bardzo częste pytanie; teraz bot wymyśli własną instrukcję).
7. **Schody na konstrukcji metalowej** — czy WoodPower dostarcza konstrukcję metalową, czy tylko drewno?
   Art 38 nie rozstrzyga → ryzyko obietnicy. 🔒 fakt od właściciela; dopisać do 38.
8. **Promień zaokrąglenia R** — art 57 „wybrany promień R" bez zakresu/przykładów (np. R2–R10?). 🔒
9. **Waga produktów** — „ile waży blat 200×60×4?" — brak gęstości gatunków; bot policzy z pamięci
   (halucynacja liczb). Rozważyć podanie orientacyjnych gęstości (dąb ~700, jesion ~690, buk ~720 kg/m³ — potwierdzić).
10. **Minimalne wymiary** — max jest (art 54), min brak („czy zrobicie półkę 20×20 cm?").
11. **Raty / płatność przy odbiorze** — art 63 mówi „z góry w całości", ale pytanie „czy są raty?" nie ma
    wprost kotwicy (Przelewy24 oferuje raty — czy dostępne?). 🔒
12. **Ekspozycja/showroom** — „czy mogę przyjechać zobaczyć drewno?" — jest tylko odbiór osobisty; 🔒.
13. **Status zamówienia** — „gdzie jest moje zamówienie?" — brak wskazówki (wystarczy: kontakt tel/mail
    z numerem zamówienia); można dopisać zdanie w 62 lub 65.

---

## 5. NARUSZENIA ZASAD

1. `73-probki-drewna-i-wykonczen.md` — pre-stylizacja „Państwo" (zakazana w §2):
   „wskazać, które gatunki lub kolory **Państwa interesują**".
   **Poprawka:** „…i wskazać interesujące gatunki lub kolory."
2. `38-rodzaje-schodow.md` — „Rodzaj schodów oraz ich elementy **dobieramy indywidualnie do konkretnej
   klatki schodowej**" — może być odczytane jako doradztwo/pomiar na miejscu.
   **Poprawka:** „Rodzaj schodów i elementy dobieramy na podstawie wymiarów i opisu klatki schodowej podanych przez klienta."
3. `02-woodpower-kontakt…` — „konsultanci … odpowiadają na pytania, przygotowują wyceny i pomagają dobrać
   parametry" — lekki balast, ale niesie informację o funkcji kanałów; można zostawić.
4. Ceny — brak naruszeń (art 61 opisuje, że kalkulator *pokazuje* ceny — OK).
5. Pomiar/montaż — brak obietnic; 36 i 52 wzorowo mówią „nie montujemy/nie mierzymy".
6. Surowe URL-e — ✓ (02: maps, 59 i 61: kalkulator). Meta-odsyłacze — brak. Mega-FAQ — brak.

---

## 6. RYZYKA DLA BOTA (poza już wymienionymi 1.1, 1.2, 2.1)

1. **Brak artykułu negatywnego** (luka 4.1) — największa powierzchnia halucynacji całej bazy.
2. `61-kalkulator-online.md` — opisuje konkretny UI („Zapytaj o ofertę", zestawienie „Wyliczenia",
   wykończenia: brak/lakier/olej). Po każdej zmianie kalkulatora artykuł trzeba aktualizować,
   inaczej bot będzie instruował wg nieistniejącego interfejsu. Dodać do checklisty utrzymania.
3. `69-reklamacje-i-zwroty.md` — „przez **formularz kontaktowy**" bez URL → bot może zmyślić link.
   **Poprawka:** podać surowy URL formularza albo usunąć ten kanał z listy.
4. `68-gwarancja.md` — „24-miesięcznej gwarancji **od momentu zakupu**" — doprecyzować (data zakupu
   vs data odbioru/dostawy); przy sporze bot zacytuje dosłownie.
5. `65-czas-realizacji.md` — liczby 16–21/28–30 dni bot poda wprost; zastrzeżenie „orientacyjne" jest
   w tym samym chunku — OK, zostawić razem (nie rozbijać akapitu przy edycji!).
6. `36` + `31` — parapet-siedzisko: art 36 dopuszcza „siedzisko lub ławkę (szerszy parapet)", art 31
   ogranicza grubość do 4 cm — dla siedziska o dużej rozpiętości bez wzmocnienia może być za cienko;
   bot nie ostrzeże. Rozważyć zdanie w 36: „Parapet używany jako siedzisko wymaga podparcia/wzmocnienia
   odpowiedniego do rozpiętości — dobieramy indywidualnie przy wycenie." (potwierdzić z właścicielem).
7. Wszystkie chunki zakresowe (19/29/37) wymieniają pełną paletę opcji — po poprawce 1.2 ryzyko spada.

---

## 7. DUPLIKATY — pełna lista

### A. Zamierzone (zgodne z zasadą „osobny artykuł per produkt" — NIE ruszać)
| Informacja | Artykuły |
|---|---|
| Definicje klas A/B i B/B | 12, 23, 33, 51 (+13 dostępność) |
| Opis technologii lite/mikrowczep | 10, 11, 22, 32, 51 (+9, 13) |
| Lista wykończeń surowe/olej/lakier | 14, 24, 34, 50 (+19, 29, 37 skrótowo) |
| Charakterystyki gatunków dąb/jesion/buk | 06–08, 20, 30, 48 |
| „>4 cm — indywidualna weryfikacja" | 21, 31 |
| „CNC — dowolny kształt" | 19, 26, 29, 35, 58 |
| URL kalkulatora | 59, 61 |
| Godziny pracy biura | 02, 67 |
| Adres Bachórz 14N | 02, 67, 69 |
| „Nie montujemy / wymiary podaje klient" | 36, 52 (+53 pokrewne) |
| Refren „wyceniamy indywidualnie na podstawie wymiarów i specyfikacji" | 39–46 i inne |
| Okresowe odnawianie powłoki | 16, 70, 71, 72 |
| Karta informacyjna dołączana do zamówienia | 28, 68, 70, 71, 72 |
| Zmiana/anulacja tylko do rozpoczęcia realizacji | 62, 69 |
| Szkody transportowe zgłaszać w dniu odbioru | 66, 69 |

### B. Ryzykowne (niemal identyczny tekst → konkurencja w top-5, do zróżnicowania)
1. **04 ↔ 05** — akapit „praca drewna ±2–3 mm/m" dosłownie zduplikowany (fix: §3.1).
2. **25 ↔ 55** — wycięcia i otwory, ta sama treść i przykłady (fix: §3.2).
3. **26 ↔ 58** — nietypowe kształty CNC (fix: §3.3).

---

## 8. Priorytety do przeredagowania (kolejność)

1. **1.1** — barwny lakier połysk/półmat (24, 34, 50) — bot obieca niedostępną opcję.
2. **1.2** — „(B/B wyłącznie dąb)" w 19, 29, 37 — bot obieca niedostępną klasę.
3. **4.1 + 4.2 + 4.3** — nowy artykuł „czego nie robimy" + negacje wosk/lazura (14) i gatunki (13).
4. **3.1–3.3** — deduplikacja 04/05, 25/55, 26/58 (jakość retrievalu).
5. **2.1** — „dąb najtwardszy" (5 artykułów) — decyzja właściciela.
6. **2.2–2.7** — weryfikacja niepotwierdzonych faktów u właściciela (30 lat/20 000 m², pochodzenie drewna,
   „miejsce dostępne dla pojazdu", semantyka docięcia, wilgotność 30–40%, instrukcja zabezpieczania surowego).
7. **5.1, 5.2, 6.3, 6.4** — kosmetyka: „Państwo" (73), klatka schodowa (38), formularz bez URL (69), moment zakupu (68).
8. **Luki 🔒 do zebrania od właściciela:** wysyłka zagranica, produkty na zewnątrz, konstrukcja metalowa
   schodów, zakres promienia R, raty, showroom, min. wymiary, gęstości/wagi, jak mierzyć.
