"""
Baza wiedzy dla asystenta AI
Zawiera informacje o produktach, procesach i systemie CRM
"""

import re
from typing import Optional

from .status_emitter import emit_status


class KnowledgeBase:
    """Klasa zarządzająca bazą wiedzy dla AI"""

    def __init__(self):
        self.knowledge = self._load_knowledge()

    def _load_knowledge(self) -> dict:
        """Ładuje bazę wiedzy"""
        return {
            # ============================================
            # PRODUKTY I DREWNO
            # ============================================
            "gatunki_drewna": {
                "keywords": ["gatunek", "drewno", "dąb", "jesion", "buk", "oak", "ash", "beech", "rodzaj drewna"],
                "content": """
## Gatunki drewna w ofercie WoodPower

WoodPower specjalizuje się w produkcji klejonek litych z trzech gatunków drewna:

### Dąb (Oak)
- **Charakterystyka**: Twarde, wytrzymałe drewno o pięknym rysunku słojów
- **Trwałość**: Klasa 2 (trwałe) - może służyć nawet kilkadziesiąt lat
- **Zastosowania**: Blaty kuchenne, schody, parapety, meble
- **Pielęgnacja**: Regularne olejowanie (co 6-12 miesięcy), unikać bezpośredniego kontaktu z wodą
- **Klasy jakości**:
  - **A/B** (Prima/Select) - najwyższa jakość, minimalna ilość sęków, jednolita barwa
  - **B/B** (Natur) - naturalny wygląd, więcej sęków i różnic w kolorze

### Jesion (Ash)
- **Charakterystyka**: Jasne drewno z wyraźnym, eleganckim rysunkiem słojów
- **Trwałość**: Klasa 1-2 - bardzo trwałe, twarde i elastyczne
- **Zastosowania**: Blaty, schody, elementy meblowe, parkiety
- **Pielęgnacja**: Podobna do dębu - regularne olejowanie, ochrona przed wilgocią
- **Wygląd**: Jasnobrązowa barwa z widocznymi słojami, nadaje wnętrzom lekkości

### Buk (Beech)
- **Charakterystyka**: Równomierna, jasnoróżowa barwa, gładka tekstura
- **Trwałość**: Klasa 5 (nietrwałe na zewnątrz) - wymaga ochrony przed wilgocią
- **Zastosowania**: Meble, blaty (wewnętrzne), schody, elementy dekoracyjne
- **Pielęgnacja**: Wymaga szczególnej ochrony przed wilgocią, regularne olejowanie
- **Uwaga**: Zalecany głównie do zastosowań wewnętrznych
"""
            },

            "technologia_blaty": {
                "keywords": ["blat", "lity", "mikrowczep", "klejonka", "finger-joint", "technologia"],
                "content": """
## Technologie produkcji klejonek

WoodPower produkuje klejonki lite w dwóch technologiach:

### Blat Lity (Solid Wood)
**Opis**: Wykonany z całych, szerokich lameli drewna sklejonych ze sobą bokami.

**Zalety**:
- Naturalny, spójny wygląd z pięknymi, ciągłymi słojami
- Brak widocznych połączeń poprzecznych
- Prestiżowy, elegancki efekt wizualny
- Idealne pod olejowanie z zachowaniem naturalnego rysunku

**Wady**:
- Wyższa cena (wyższe wymagania materiałowe)
- Większa podatność na odkształcenia przy zmianach wilgotności
- Ograniczona dostępność bardzo szerokich desek

**Zastosowania**: Premium blaty kuchenne, ekskluzywne meble, reprezentacyjne elementy

### Blat Mikrowczepowy (Finger-Joint)
**Opis**: Składa się z krótszych kawałków drewna łączonych na mikrowczepy (zazębienia).

**Zalety**:
- Stabilność wymiarowa - mniejsze odkształcenia przy zmianach wilgotności
- Niższa cena (wykorzystanie krótszych kawałków drewna)
- Ekologiczność - mniejsze odpady produkcyjne
- Świetne pod lakierowanie lub malowanie

**Wady**:
- Widoczne połączenia mikrowczepowe co 20-40 cm
- Mniej naturalny wygląd pod olejowaniem
- Nie nadaje się tam, gdzie liczy się ciągłość słojów

**Zastosowania**: Schody, parapety, blaty robocze, meble do malowania

### Którą technologię wybrać?
- **Blat lity** - gdy zależy Ci na wyglądzie, ciągłości słojów, masz wyższy budżet
- **Mikrowczep** - gdy priorytetem jest stabilność, cena, lub planujesz malować/lakierować
"""
            },

            "klasy_jakosci": {
                "keywords": ["klasa", "jakość", "prime", "select", "natur", "rustic", "sortowanie", "A/B", "B/B"],
                "content": """
## Klasy jakości drewna

### A/B (Prima/Select)
- Najwyższa jakość
- Minimalna ilość sęków (małe, zdrowe)
- Brak pęknięć
- Jednolita barwa
- Najlepszy wybór na reprezentacyjne elementy

### B/B (Natur)
- Naturalny wygląd
- Więcej sęków (zdrowe, różnej wielkości)
- Naturalne przebarwienia dozwolone
- Dobry stosunek jakości do ceny
- Podkreśla naturalny charakter drewna
"""
            },

            "zastosowania": {
                "keywords": ["zastosowanie", "do czego", "gdzie użyć", "na co"],
                "content": """
## Zastosowania klejonek WoodPower

### Blaty kuchenne
- Zalecane: Dąb, Jesion
- Technologia: Blat lity (wygląd) lub mikrowczep (stabilność)
- Klasa: A/B dla reprezentacyjnych kuchni
- Obróbka: Olejowanie (podkreśla rysunek drewna)

### Schody
- Zalecane: Dąb (trwałość), Jesion (jasność), Buk (ekonomia)
- Technologia: Mikrowczep (stabilność, cena) lub lity (prestiż)
- Uwaga: Wysoka odporność na ścieranie

### Parapety
- Wszystkie gatunki odpowiednie
- Technologia: Mikrowczep (stabilność przy zmianach temperatury)
- Klasa: B/B wystarczająca (mniejsza ekspozycja)

### Meble
- Blaty stołów: Dąb A/B lity (prestiż), mikrowczep (budżet)
- Fronty: Jesion (jasność), Buk (do malowania)
- Półki: Dowolny gatunek, klasa B/B
"""
            },

            "pielegnacja": {
                "keywords": ["pielęgnacja", "olejowanie", "czyszczenie", "konserwacja", "olej", "lakier", "utrzymanie"],
                "content": """
## Pielęgnacja klejonek drewnianych

### Olejowanie
- **Częstotliwość**: Co 6-12 miesięcy (intensywnie używane powierzchnie częściej)
- **Oleje**: Olej do blatów kuchennych (bezpieczny dla żywności)
- **Sposób**: Nakładać cienką warstwę wzdłuż słojów, wytrzeć nadmiar

### Codzienne użytkowanie
- Wycierać rozlane płyny natychmiast
- Używać podkładek pod gorące naczynia
- Nie stawiać bezpośrednio mokrych przedmiotów
- Czyścić wilgotną (nie mokrą) ściereczką

### Czego unikać
- Silnych detergentów i środków ściernych
- Bezpośredniego kontaktu z wodą przez dłuższy czas
- Gwałtownych zmian temperatury i wilgotności
- Stawiania gorących garnków bezpośrednio na blacie

### Specyfika gatunków
- **Dąb**: Najbardziej odporny, standardowa pielęgnacja
- **Jesion**: Podobnie do dębu, uważać na wilgoć
- **Buk**: Wymaga szczególnej ochrony przed wilgocią
"""
            },

            # ============================================
            # MODUŁY CRM - SZCZEGÓŁOWE OPISY
            # ============================================
            "modul_dashboard": {
                "keywords": ["dashboard", "pulpit", "strona główna", "widgety", "aktywność"],
                "content": """
## Dashboard (Pulpit główny)

**Dostęp**: Kliknij "Dashboard" w menu bocznym lub wejdź na stronę główną po zalogowaniu.

### Co znajdziesz na Dashboard:
- **Widgety ze statystykami** - szybki podgląd najważniejszych liczb
- **Aktywni użytkownicy** - kto jest obecnie online/offline w systemie
- **Ostatnie aktywności** - log zmian w systemie
- **Wykresy sprzedaży** - wizualizacja danych
- **Changelog** - lista zmian i aktualizacji systemu

### Funkcje:
- Śledzenie aktywności użytkowników (status: online/offline/idle/away)
- Przegląd zdrowia systemu
- Szybki dostęp do wszystkich modułów z menu bocznego
"""
            },

            "modul_kalkulator": {
                "keywords": ["kalkulator", "wycena", "cena", "oblicz", "kalkulacja", "wymiary", "m3", "metr sześcienny"],
                "content": """
## Kalkulator produktowy

**Dostęp**: Menu boczne → "Kalkulator" lub `/calculator/`

### Jak stworzyć wycenę:

**1. Sekcja danych klienta:**
- Wybierz istniejącego klienta lub dodaj nowego
- Ustaw grupę cenową (mnożnik ceny)

**2. Sekcja produktu:**
- Wprowadź wymiary: długość, szerokość, grubość (w cm)
- Wybierz gatunek drewna (dąb/jesion/buk)
- Wybierz klasę drewna (A/B lub B/B)
- Wybierz technologię (lity/mikrowczep)
- Ustaw stan wykończenia (surowy/lakierowany/olejowany)

**3. Warianty produktu:**
- Dodaj różne warianty (różne wymiary/wykończenia)
- Dla każdego wariantu ustaw ilość sztuk
- System automatycznie obliczy objętość i cenę

**4. Obliczenia automatyczne:**
- Objętość w m³
- Cena za m³ (z cennika)
- Cena brutto/netto (przełącznik u góry)

**5. Wysyłka:**
- Kliknij "Dostarczanie" aby obliczyć koszt wysyłki
- Wprowadź wymiary paczki

**6. Zapisanie:**
- Kliknij "Zapisz wycenę"
- System nada numer wyceny automatycznie
- Możesz wysłać link do klienta
"""
            },

            "modul_wyceny": {
                "keywords": ["wyceny", "oferta", "lista wycen", "historia wycen", "status wyceny", "rabat"],
                "content": """
## Wyceny

**Dostęp**: Menu boczne → "Wyceny" lub `/quotes/`

### Lista wycen:
Po lewej stronie panel filtrów:
- **Status** - filtruj po statusie (kolorowe kwadraty)
- **Numer wyceny** - szukaj po numerze
- **Klient** - szukaj po nazwie/numerze klienta
- **Data** - zakres dat (od-do)
- **Pracownik** - filtruj po handlowcu (tylko Admin)
- **Źródło** - skąd przyszło zapytanie

### Akcje na wycenie:
- **Podgląd** - szczegóły wyceny
- **Edycja** - zmiana statusu, dodanie rabatu
- **Link dla klienta** - skopiuj link do udostępnienia
- **PDF** - eksport wyceny do PDF
- **Utwórz zamówienie** - wyślij do Baselinker

### Statusy wycen:
- Szkic (draft)
- Wysłana do klienta
- Zaakceptowana przez klienta
- Zamówienie złożone w Baselinker

### Rabaty:
- Rabat procentowy lub kwotowy
- Wybierz powód rabatu z listy
- System zachowuje oryginalne ceny do porównania
"""
            },

            "modul_klienci": {
                "keywords": ["klient", "klienci", "kontrahent", "baza klientów", "dane klienta", "adres", "nip"],
                "content": """
## Klienci

**Dostęp**: Menu boczne → "Klienci" lub `/clients/`

### Lista klientów:
- Tabela z kolumnami: Nazwa, Imię/Nazwisko, Email, Telefon
- **Wyszukiwanie** - wpisz nazwę w pole szukania
- **Sortowanie** - kliknij nagłówek kolumny
- **Paginacja** - wybierz ilość wierszy (20-500)

### Dodawanie klienta:
Kliknij przycisk "Dodaj klienta" i wypełnij:

**Dane podstawowe:**
- Nazwa firmy/klienta
- Email, telefon

**Adres dostawy:**
- Ulica, kod pocztowy, miasto
- Województwo, kraj

**Adres do faktury** (osobny dla B2B):
- Dane firmy, NIP, REGON

**Źródło klienta:**
- Skąd klient trafił do nas

### Edycja klienta:
- Kliknij na wiersz klienta
- Otworzy się modal ze szczegółami
- Możesz edytować wszystkie dane

### Uwaga dla Partnerów:
Partnerzy widzą tylko klientów, których sami dodali.
"""
            },

            "modul_produkcja": {
                "keywords": ["produkcja", "panel produkcji", "stanowisko", "workflow", "praca", "sztuki", "wykonane"],
                "content": """
## Panel Produkcji

**Dostęp**: Menu boczne → "Produkcja" lub `/production/`

### Dashboard produkcji:
- Statystyki per stanowisko (ile czeka, ile zrobiono dziś)
- Alerty deadline
- Status zdrowia systemu

### Lista produktów:
Wejdź w `/production/products` aby zobaczyć:
- Wszystkie produkty w produkcji
- Filtry: status, priorytet, deadline, daty
- Import z Baselinker

### Stanowiska pracy (6 stanowisk):
Każde stanowisko ma własny widok:

1. **Wycinanie** (`/production/stations/cutting`)
2. **Składanie** (`/production/stations/assembly`)
3. **Sklejanie** (`/production/stations/gluing`)
4. **Formatowanie** (`/production/stations/formatting`)
5. **Wykańczanie** (`/production/stations/finishing`)
6. **Pakowanie** (`/production/stations/packaging`)

### Jak pracować na stanowisku:
- Wybierz swoje stanowisko z menu
- Widzisz listę produktów do wykonania
- **Przyciski +/-** - zwiększ/zmniejsz licznik wykonanych sztuk
- Gdy wykonasz wszystkie sztuki, produkt przechodzi do następnego stanowiska

### Format ID produktu:
`YY_NNNNN_S` np. `25_05248_1`
- 25 = rok 2025
- 05248 = numer zamówienia
- 1 = pozycja w zamówieniu

### System priorytetów:
Produkty są sortowane według daty opłacenia zamówienia.
Najpierw realizujemy najstarsze opłacone zamówienia.
"""
            },

            "modul_raporty": {
                "keywords": ["raport", "raporty", "statystyki", "excel", "eksport", "analiza", "sprzedaż"],
                "content": """
## Raporty

**Dostęp**: Menu boczne → "Raporty" lub `/reports/`

### Główna tabela raportów:
Wielokolumnowa tabela ze wszystkimi zamówieniami:

**Dane zamówienia:**
- Data, M³, Kwota netto/brutto
- Nr Baselinker, Nr wewnętrzny
- Klient, Adres, Miasto, Województwo
- Telefon, Opiekun, Metoda dostawy

**Dane produktu:**
- Rodzaj (klejonka/deska/usługa)
- Gatunek, Technologia, Klasa
- Wymiary (D/S/G), Ilość

**Finanse:**
- Cena, Wartość, Cena za m³
- Status płatności, Saldo

### Filtrowanie:
- Data od-do
- Dropdown dla każdej kolumny
- Wyszukiwanie tekstowe

### Eksport do Excel:
- Kliknij przycisk "Eksport"
- Pobierz plik XLSX ze wszystkimi danymi
- Zachowane formatowanie i sumowania

### Statystyki dolne:
Na dole strony automatyczne podsumowania:
- Suma M³, Kwota netto/brutto
- Średnia cena za m³
- Liczba zamówień/produktów
- Saldo do zapłaty
"""
            },

            "modul_baselinker": {
                "keywords": ["baselinker", "synchronizacja", "zamówienie", "sklep", "integracja", "faktura"],
                "content": """
## Integracja Baselinker

### Co to jest Baselinker:
System do zarządzania sprzedażą wielokanałową. WoodPower używa go do:
- Przyjmowania zamówień ze sklepu
- Wystawiania faktur
- Zarządzania wysyłkami

### Synchronizacja z CRM:
- Zamówienia z Baselinker automatycznie trafiają do Panelu Produkcji
- System parsuje nazwy produktów (gatunek, wymiary, klasę)
- Synchronizacja działa automatycznie (CRON)

### Tworzenie zamówienia z wyceny:
1. Otwórz zaakceptowaną wycenę
2. Kliknij "Utwórz zamówienie w Baselinker"
3. Wybierz źródło i status zamówienia
4. System utworzy zamówienie i zwróci numer

### Dokumenty z Baselinker:
Z poziomu wyceny możesz pobrać:
- Fakturę (PDF)
- Korektę faktury
- E-paragon
- Link do strony zamówienia

### Pola z Baselinker w CRM:
- `extra_field_1` → wewnętrzny numer zamówienia (np. "1617/2025")
- `admin_comments` → uwagi do zamówienia
- `products[].name` → parsowane na szczegóły produktu
"""
            },

            # ============================================
            # PRODUKCJA - SZCZEGÓŁY
            # ============================================
            "stanowiska_produkcji": {
                "keywords": ["stanowisko", "wycinanie", "składanie", "sklejanie", "pakowanie", "wykańczanie", "formatowanie", "cutting", "assembly", "gluing"],
                "content": """
## Stanowiska produkcji (workflow)

Zamówienie przechodzi przez 6 stanowisk w kolejności:

### 1. Wycinanie (cutting)
- Cięcie drewna na odpowiednie wymiary
- Status: czeka_na_wyciecie → czeka_na_skladanie

### 2. Składanie (assembly)
- Montaż elementów
- Status: czeka_na_skladanie → czeka_na_sklejanie

### 3. Sklejanie (gluing)
- Klejenie elementów
- Status: czeka_na_sklejanie → czeka_na_formatowanie

### 4. Formatowanie (formatting)
- Nadawanie ostatecznych wymiarów
- Status: czeka_na_formatowanie → czeka_na_wykanczanie

### 5. Wykańczanie (finishing)
- Szlifowanie, olejowanie
- Status: czeka_na_wykanczanie → czeka_na_pakowanie

### 6. Pakowanie (packaging)
- Pakowanie gotowego produktu
- Status: czeka_na_pakowanie → spakowane

### Jak oznaczyć wykonanie:
- Na każdym stanowisku są przyciski +/-
- Zwiększaj licznik wykonanych sztuk
- Gdy wszystkie sztuki gotowe, produkt przechodzi dalej
"""
            },

            "statusy": {
                "keywords": ["status", "czeka", "anulowane", "wstrzymane", "spakowane", "w realizacji"],
                "content": """
## Statusy zamówień/produktów

### Statusy workflow (produkcja):
- `czeka_na_wyciecie` - oczekuje na wycinanie
- `czeka_na_skladanie` - oczekuje na składanie
- `czeka_na_sklejanie` - oczekuje na sklejanie
- `czeka_na_formatowanie` - oczekuje na formatowanie
- `czeka_na_wykanczanie` - oczekuje na wykańczanie
- `czeka_na_pakowanie` - oczekuje na pakowanie
- `spakowane` - gotowe do wysyłki

### Statusy specjalne:
- `anulowane` - zamówienie anulowane
- `wstrzymane` - produkcja wstrzymana (np. brak materiału)
- `w_realizacji` - aktualnie w produkcji
"""
            },

            "id_produktu": {
                "keywords": ["id", "numer", "identyfikator", "25_", "pozycja", "numer zamówienia"],
                "content": """
## Format ID produktu w systemie

Format: `YY_NNNNN_S`

Przykład: `25_05248_1`
- `25` - rok (2025)
- `05248` - numer zamówienia
- `1` - pozycja w zamówieniu

**Ważne:**
- Jedno ID = jedna pozycja w zamówieniu (może zawierać wiele sztuk)
- Ilość sztuk przechowywana w polu `quantity`
- Na stanowisku widzisz ile sztuk do wykonania i ile już zrobiono
"""
            },

            # ============================================
            # OGÓLNE INFORMACJE
            # ============================================
            "nawigacja": {
                "keywords": ["menu", "nawigacja", "gdzie", "jak wejść", "jak znaleźć", "sidebar", "panel boczny"],
                "content": """
## Nawigacja w systemie CRM

### Menu boczne (sidebar):
Po lewej stronie ekranu znajdziesz menu z modułami:

- **Dashboard** - strona główna, statystyki
- **Produkcja** - panel produkcji, stanowiska
- **Klienci** - baza klientów
- **Wyceny** - lista wycen i ofert
- **Kalkulator** - tworzenie nowych wycen
- **Raporty** - analizy i statystyki

### Górny pasek:
- Nazwa zalogowanego użytkownika
- Powiadomienia
- Wylogowanie

### Skróty klawiaturowe:
- ESC - zamknij modal/popup

### Uprawnienia:
- **Admin** - dostęp do wszystkiego
- **User** - produkcja, klienci, wyceny, kalkulator, raporty
- **Partner** - ograniczony dostęp (tylko swoi klienci i wyceny)
"""
            },

            "firma": {
                "keywords": ["woodpower", "firma", "producent", "oferta", "kontakt", "o nas", "o firmie"],
                "content": """
## O firmie WoodPower

**Specjalizacja**: Produkcja klejonek litych z drewna liściastego

**Gatunki w ofercie**:
- Dąb (Oak)
- Jesion (Ash)
- Buk (Beech)

**Technologie**:
- Blaty lite (ciągłe słoje)
- Blaty mikrowczepowe (finger-joint)

**Klasy jakości**:
- A/B (Prima/Select)
- B/B (Natur)

**Produkty**:
- Blaty kuchenne
- Stopnie schodowe
- Parapety
- Elementy meblowe

**Integracje systemowe**:
- Baselinker - zarządzanie zamówieniami
- Responso - obsługa klienta
"""
            },

            "pomoc_techniczna": {
                "keywords": ["pomoc", "problem", "błąd", "nie działa", "error", "wsparcie", "kontakt"],
                "content": """
## Pomoc techniczna

### Masz problem z systemem CRM?
Skontaktuj się z **Konradem** (administrator systemu).

### Typowe problemy:

**Nie mogę się zalogować:**
- Sprawdź poprawność hasła
- Upewnij się, że masz aktywne konto
- Skontaktuj się z administratorem

**Strona się nie ładuje:**
- Odśwież stronę (F5)
- Wyczyść cache przeglądarki
- Sprawdź połączenie internetowe

**Brak uprawnień:**
- Niektóre funkcje dostępne tylko dla Admin/User
- Partnerzy mają ograniczony dostęp
- Skontaktuj się z administratorem po rozszerzenie uprawnień

**Błąd przy zapisie:**
- Sprawdź czy wszystkie wymagane pola są wypełnione
- Sprawdź format danych (np. email, NIP)
- Spróbuj ponownie za chwilę
"""
            }
        }

    def get_relevant_context(self, user_message: str) -> str:
        """
        Zwraca kontekst odpowiedni do pytania użytkownika

        Args:
            user_message: Wiadomość użytkownika

        Returns:
            Odpowiedni fragment wiedzy
        """
        # Emituj status: przeszukuję bazę wiedzy
        emit_status('knowledge_base')

        message_lower = user_message.lower()
        relevant_sections = []

        for section_key, section_data in self.knowledge.items():
            keywords = section_data.get("keywords", [])
            # Sprawdź czy któreś słowo kluczowe pasuje
            if any(keyword in message_lower for keyword in keywords):
                relevant_sections.append(section_data["content"])

        # NOWE: Sprawdź czy pytanie dotyczy zamówień Baselinker
        order_keywords = [
            'zamówienie', 'zamowienie', 'order', 'status zamówienia', 'status zamowienia',
            'opłacone', 'oplacone', 'płatność', 'platnosc', 'zapłacone', 'zaplacone',
            'baselinker', 'bl ', 'numer zamówienia', 'id zamówienia',
            'zamówienia klienta', 'zamowienia klienta'
        ]

        order_id = self._extract_order_id(user_message)
        client_name = self._extract_client_name(user_message)

        if order_id or client_name or any(kw in message_lower for kw in order_keywords):
            # Emituj status: pobieram z Baselinker
            emit_status('baselinker')
            bl_context = self._get_baselinker_context(user_message, order_id, client_name)
            if bl_context:
                relevant_sections.append(bl_context)

        # NOWE: Sprawdź czy pytanie dotyczy wycen lub klientów z CRM
        crm_keywords = [
            'wycena', 'wyceny', 'oferta', 'oferty', 'quote',
            'klient', 'klienci', 'kontrahent',
            'statystyki', 'statystyka', 'ile wycen', 'ile ofert',
            'wartość wycen', 'wartosc wycen', 'suma wycen',
            'ostatnie wyceny', 'moje wyceny', 'lista wycen',
            'szczegóły wyceny', 'szczegoly wyceny', 'dane wyceny',
            'szczegóły klienta', 'szczegoly klienta', 'dane klienta'
        ]

        quote_number = self._extract_quote_number(user_message)
        crm_client_query = self._extract_crm_client_query(user_message)

        # Logowanie ekstrakcji
        from flask import current_app
        current_app.logger.info(f"[KnowledgeBase] Ekstrakcja CRM: quote_number={quote_number}, crm_client_query={crm_client_query}")

        if quote_number or crm_client_query or any(kw in message_lower for kw in crm_keywords):
            current_app.logger.info(f"[KnowledgeBase] Wykryto zapytanie CRM, wywołuję _get_crm_context")
            # Emituj status: sprawdzam w CRM (wyceny lub klienci)
            if quote_number or any(kw in message_lower for kw in ['wycena', 'wyceny', 'oferta', 'oferty']):
                emit_status('crm_quotes')
            elif crm_client_query or 'klient' in message_lower:
                emit_status('crm_clients')
            else:
                emit_status('crm_quotes')
            crm_context = self._get_crm_context(user_message, quote_number, crm_client_query)
            current_app.logger.info(f"[KnowledgeBase] Kontekst CRM (pierwsze 300 znaków): {crm_context[:300] if crm_context else 'BRAK'}...")
            if crm_context:
                relevant_sections.append(crm_context)

        # Sprawdź czy pytanie dotyczy szukania produktu w sklepie
        product_keywords = ['mamy', 'macie', 'jest w sklepie', 'szukam', 'klient szuka',
                          'klient chce', 'klient pyta', 'dostępny', 'dostępność',
                          'link do', 'gdzie kupić', 'w ofercie']
        if any(kw in message_lower for kw in product_keywords):
            # Emituj status: szukam w sklepie
            emit_status('prestashop')
            # Spróbuj wyszukać produkty w PrestaShop
            shop_results = self._search_shop_products(user_message)
            if shop_results:
                relevant_sections.append(shop_results)

        if relevant_sections:
            return "\n\n".join(relevant_sections)

        # Jeśli nie znaleziono konkretnego kontekstu, zwróć podstawowe info
        return """
## Podstawowe informacje o WoodPower CRM

**Firma WoodPower:**
- Producent klejonek litych z drewna liściastego
- Gatunki: dąb, jesion, buk
- Technologie: blaty lite, mikrowczep
- Produkty: blaty kuchenne, schody, parapety, meble

**Moduły systemu CRM:**
- Dashboard - pulpit główny ze statystykami
- Kalkulator - tworzenie wycen
- Wyceny - lista ofert dla klientów
- Klienci - baza kontrahentów
- Produkcja - zarządzanie stanowiskami pracy
- Raporty - analizy sprzedaży

**Produkcja (6 stanowisk):**
wycinanie → składanie → sklejanie → formatowanie → wykańczanie → pakowanie

Jeśli potrzebujesz szczegółów o konkretnym module lub produkcie, zapytaj!
"""

    def _search_shop_products(self, user_message: str) -> str:
        """Wyszukuje produkty w sklepie PrestaShop na podstawie pytania"""
        try:
            from .prestashop_service import PrestaShopService
            from flask import current_app

            # Wyciągnij słowa kluczowe do wyszukania
            search_query = self._extract_search_query(user_message)
            if not search_query:
                return ""

            current_app.logger.info(f"[KnowledgeBase] Szukam w sklepie: '{search_query}'")

            prestashop = PrestaShopService()
            if not prestashop.is_configured():
                return ""

            # Sprawdź czy są wymiary w pytaniu
            dimensions = self._extract_dimensions(user_message)

            if dimensions:
                # Szukaj z tolerancją wymiarów (tylko produkty >= szukanych wymiarów)
                current_app.logger.info(f"[KnowledgeBase] Wykryto wymiary: {dimensions}, szukam produktów >= te wymiary")
                products = prestashop.search_with_dimension_tolerance(search_query, dimensions, tolerance=15)

                if products:
                    result = prestashop.format_products_for_ai(products)
                    # Dodaj info że można skrócić
                    result += "\n\n*Uwaga: Pokazano produkty o wymiarach >= szukanych. Można je skrócić do potrzebnego rozmiaru. Wszystkie produkty są produkowane na zamówienie.*"
                    return result
                else:
                    # Brak pasujących produktów - za duże wymiary
                    dim_str = "x".join(str(v) for v in dimensions.values())
                    return f"""\n\n**Nie znaleziono produktów w sklepie o wymiarach >= {dim_str} cm.**

To wymiar niestandardowy. Żeby przygotować wycenę dla klienta:

1. Wejdź w **Kalkulator** (menu boczne → Kalkulator)
2. Wprowadź wymiary klienta ({dim_str} cm)
3. Wybierz gatunek drewna, technologię i wykończenie
4. System automatycznie obliczy cenę

Możemy wyprodukować praktycznie dowolny wymiar na zamówienie."""
            else:
                products = prestashop.search_products(search_query, limit=5)
                if products:
                    return prestashop.format_products_for_ai(products)

            return ""

        except Exception as e:
            from flask import current_app
            current_app.logger.error(f"[KnowledgeBase] Błąd wyszukiwania w sklepie: {e}")
            return ""

    def _extract_dimensions(self, message: str) -> dict:
        """Wyciąga wymiary z wiadomości (np. 146x38x4 lub 150x60)"""
        import re

        dimensions = {}

        # Wzorce wymiarów
        patterns = [
            r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)',  # 150x60x4
            r'(\d+)\s*[xX×]\s*(\d+)',  # 150x60
        ]

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                groups = match.groups()
                if len(groups) >= 1:
                    dimensions['length'] = int(groups[0])
                if len(groups) >= 2:
                    dimensions['width'] = int(groups[1])
                if len(groups) >= 3:
                    dimensions['thickness'] = int(groups[2])
                break

        return dimensions

    def _extract_search_query(self, message: str) -> str:
        """Wyciąga frazę do wyszukania z wiadomości użytkownika"""
        message_lower = message.lower()

        # Słowa do usunięcia (stop words)
        stop_words = ['mamy', 'macie', 'czy', 'jest', 'są', 'klient', 'szuka', 'chce',
                     'pyta', 'o', 'w', 'na', 'do', 'z', 'i', 'a', 'lub', 'albo',
                     'sklepie', 'ofercie', 'dostępny', 'dostępne', 'link', 'gdzie',
                     'kupić', 'zamówić', 'potrzebuje', 'potrzebuje', 'proszę', 'prosze']

        # Wyciągnij słowa
        words = message_lower.split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Szukaj typowych fraz produktowych
        product_terms = []
        for word in keywords:
            # Gatunki drewna
            if any(g in word for g in ['dęb', 'dąb', 'jesion', 'buk', 'dębowy', 'jesionowy', 'bukowy']):
                product_terms.append(word)
            # Typy produktów
            elif any(t in word for t in ['blat', 'stopień', 'schod', 'parapet', 'klejonka']):
                product_terms.append(word)
            # Technologie
            elif any(t in word for t in ['lity', 'mikrowczep', 'surowy', 'olejowany', 'lakierowany']):
                product_terms.append(word)
            # Wymiary (np. 150x60, 100x40x3)
            elif 'x' in word and any(c.isdigit() for c in word):
                product_terms.append(word)
            # Klasy jakości
            elif word in ['a/b', 'ab', 'b/b', 'bb']:
                product_terms.append(word)

        if product_terms:
            return ' '.join(product_terms[:4])  # Max 4 słowa

        # Fallback - weź pierwsze 3 sensowne słowa
        return ' '.join(keywords[:3]) if keywords else ""

    def get_all_knowledge(self) -> str:
        """Zwraca całą bazę wiedzy (do debugowania)"""
        all_content = []
        for section_data in self.knowledge.values():
            all_content.append(section_data["content"])
        return "\n\n".join(all_content)

    # =====================================================
    # INTEGRACJA Z BASELINKER
    # =====================================================

    def _extract_order_id(self, message: str) -> Optional[int]:
        """Wyciąga ID zamówienia Baselinker z wiadomości"""
        # Wzorce: "zamówienie 25208907", "order #25208907", "BL ID: 25208907"
        patterns = [
            r'zamówieni[ae]\s*(?:#|nr|numer|id)?[:\s]*(\d{7,10})',
            r'zamowieni[ae]\s*(?:#|nr|numer|id)?[:\s]*(\d{7,10})',
            r'order\s*(?:#|id)?[:\s]*(\d{7,10})',
            r'bl\s*(?:#|id)?[:\s]*(\d{7,10})',
            r'baselinker\s*(?:#|id)?[:\s]*(\d{7,10})',
            r'#(\d{7,10})',
            r'(?:^|\s)(\d{8})(?:\s|$)',  # 8-cyfrowy numer samodzielnie
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def _extract_client_name(self, message: str) -> Optional[str]:
        """Wyciąga imię/nazwisko klienta z wiadomości"""
        # Wzorce: "zamówienia Kowalskiego", "klient Jan Nowak", "znajdź Zbyszka"
        patterns = [
            r'zamówieni[ae]\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
            r'zamowieni[ae]\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
            r'klient[a]?\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
            r'(?:znajd[źz]|szukaj)\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
            r'(?:status|sprawdź|sprawdz)\s+(?:pana\s+|pani\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Odfiltruj słowa kluczowe które mogą być fałszywie pozytywne
                skip_words = ['zamówienie', 'zamowienie', 'status', 'baselinker', 'order']
                if name.lower() not in skip_words:
                    return name

        return None

    def _get_baselinker_context(self, message: str, order_id: Optional[int] = None,
                                client_name: Optional[str] = None) -> str:
        """
        Pobiera kontekst z Baselinker na podstawie wykrytych parametrów.
        """
        try:
            from .baselinker_ai_service import BaselinkerAIService
            from flask import current_app

            service = BaselinkerAIService()
            user = service._get_current_user()

            if not user:
                return "**Błąd:** Musisz być zalogowany aby sprawdzić zamówienia."

            # Zapytanie o konkretne zamówienie po ID
            if order_id:
                result = service.get_order_by_id(order_id, user)
                if result['success']:
                    return f"**Dane zamówienia z Baselinker:**\n\n{service.format_order_response(result['order'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Zapytanie o klienta
            if client_name:
                clients = service.search_clients_by_name(client_name, user)

                if not clients:
                    # Sprawdź czy to partner i czy klient w ogóle istnieje
                    if service._is_partner(user):
                        return f"**Nie mogę udzielić odpowiedzi** - nie znaleziono klienta '{client_name}' wśród Twoich klientów."
                    else:
                        return f"**Nie znaleziono klientów** pasujących do: {client_name}"

                if len(clients) == 1:
                    # Jeden klient - pobierz jego zamówienia
                    client = clients[0]
                    result = service.get_orders_for_client(client['id'], user)

                    if result['success']:
                        if result['orders']:
                            orders_text = "\n\n---\n\n".join([
                                service.format_order_response(o) for o in result['orders']
                            ])
                            return f"**Zamówienia klienta {client['client_name']}:**\n\n{orders_text}"
                        else:
                            return f"**Klient {client['client_name']}** nie ma jeszcze zamówień w systemie."
                    else:
                        return f"**Błąd:** {result['error']}"

                else:
                    # Wielu klientów - poproś o doprecyzowanie
                    clients_list = "\n".join([
                        f"- {c['client_name']} ({c.get('city', 'brak miasta')}) - {c.get('email', 'brak email')}"
                        for c in clients
                    ])
                    return f"""**Znaleziono {len(clients)} klientów pasujących do "{client_name}":**

{clients_list}

Proszę doprecyzować, o którego klienta chodzi (podaj pełne imię i nazwisko lub email)."""

            # Ogólne zapytanie o zamówienia - dla partnerów pokaż statystyki
            if service._is_partner(user):
                stats = service.get_partner_statistics(user)
                if stats['success']:
                    s = stats['stats']
                    return f"""**Twoje statystyki jako partnera:**
- Wszystkich wycen: {s['total_quotes']}
- Złożonych zamówień: {s['total_orders']}
- Łączna wartość: {s['total_value']:.2f} zł
- Konwersja: {s['conversion_rate']}%

Jeśli chcesz sprawdzić konkretne zamówienie, podaj jego numer ID lub wyszukaj po kliencie."""

            return """**Pomoc - zapytania o zamówienia Baselinker:**

Mogę sprawdzić dla Ciebie:
- Status konkretnego zamówienia (podaj ID np. "zamówienie 25208907")
- Zamówienia klienta (np. "zamówienia Kowalskiego")
- Czy zamówienie jest opłacone

Podaj więcej szczegółów, a sprawdzę w systemie!"""

        except Exception as e:
            from flask import current_app
            current_app.logger.error(f"[KnowledgeBase] Błąd pobierania kontekstu BL: {e}")
            return f"**Błąd komunikacji z Baselinker:** {str(e)}"

    # =====================================================
    # INTEGRACJA Z CRM (WYCENY, KLIENCI)
    # =====================================================

    def _extract_quote_number(self, message: str) -> Optional[str]:
        """Wyciąga numer wyceny z wiadomości"""
        # Format numeru wyceny: NN/MM/RR/W
        # NN = numer (1-3 cyfry), MM = miesiąc (2 cyfry), RR = rok (2 cyfry), W = litera
        # Przykłady: 123/01/25/W, 45/12/24/W, 1/05/25/W
        patterns = [
            # Dokładny format: NN/MM/RR/W (z opcjonalnym słowem "wycena/oferta" przed)
            r'(?:wycen[aę]|ofert[aę])\s+(\d{1,3}/\d{2}/\d{2}/[A-Z])',
            r'(\d{1,3}/\d{2}/\d{2}/[A-Z])',
            # Wariant z myślnikami: NN-MM-RR-W
            r'(?:wycen[aę]|ofert[aę])\s+(\d{1,3}-\d{2}-\d{2}-[A-Z])',
            r'(\d{1,3}-\d{2}-\d{2}-[A-Z])',
            # Ogólny fallback: "wycena nr X" lub "oferta X"
            r'(?:wycen[aę]|ofert[aę])\s+(?:nr|numer)?[:\s]*(\d{1,3}[/\-]\d{2}[/\-]\d{2}[/\-][A-Z])',
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                # Normalizuj format (zamień myślniki na ukośniki)
                quote_num = match.group(1).replace('-', '/')
                return quote_num.upper()

        return None

    def _extract_crm_client_query(self, message: str) -> Optional[str]:
        """Wyciąga zapytanie o klienta dla CRM (różne od Baselinker)"""
        # Wzorce: "dane klienta Kowalski", "szczegóły klienta 123", "klient Jan Nowak",
        # "wyceny Pana Henryk Kamiński", "status wyceny Kowalskiego"

        # Lista słów do odfiltrowania (nie są imionami/nazwiskami)
        skip_words = [
            'wycena', 'wyceny', 'wycenę', 'oferta', 'oferty', 'ofertę',
            'dane', 'szczegóły', 'info', 'status', 'jaki', 'jaka', 'jest',
            'pana', 'pani', 'pan', 'klienta', 'klient',
            # Dodatkowe słowa które NIE są imionami
            'znajdź', 'znajdz', 'szukaj', 'pokaż', 'pokaz', 'sprawdź', 'sprawdz',
            'numerze', 'numer', 'nr', 'po', 'dla', 'tego', 'ten', 'ta', 'to',
            'proszę', 'prosze', 'podaj', 'daj', 'zobacz',
        ]

        # WAŻNE: Jeśli wiadomość dotyczy szukania po numerze wyceny, NIE szukaj klienta
        if re.search(r'(?:po\s+)?numer(?:ze)?\s+\d', message, re.IGNORECASE):
            return None
        if re.search(r'\d{1,3}[/\-]\d{2}[/\-]\d{2}[/\-][A-Z]', message, re.IGNORECASE):
            return None

        patterns = [
            # "wyceny Pana/Pani [imię] [nazwisko]" - wymaga DWÓCH słów po Pan/Pani
            r'(?:wycen[ayę]|ofert[ayę]|status)[^a-ząćęłńóśźż]*(?:pana?|pani)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
            # "Pana/Pani [imię] [nazwisko]" - wymaga DWÓCH słów
            r'(?:pana?|pani)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)',
            # "dane klienta Kowalski"
            r'(?:dane|szczegóły|szczegoly|info)\s+klient[a]?\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ0-9\s]+)',
            # "klient Jan Nowak"
            r'klient[a]?\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?)',
            # "wyceny dla klienta X"
            r'(?:wyceny|oferty)\s+(?:dla\s+)?klient[a]?\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ\s]+)',
            # "[imię nazwisko] wyceny/wycena" (odwrotna kolejność)
            r'([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)\s+(?:wycen[ayę]|ofert[ayę])',
        ]
        # UWAGA: Usunięto fallback "samo imię i nazwisko" - zbyt agresywny

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Odfiltruj słowa kluczowe - sprawdź każde słowo osobno
                name_words = name.lower().split()
                if all(word not in skip_words for word in name_words) and len(name) > 3:
                    return name

        return None

    def _get_crm_context(self, message: str, quote_number: Optional[str] = None,
                        client_query: Optional[str] = None) -> str:
        """
        Pobiera kontekst z lokalnej bazy CRM.
        """
        try:
            from .crm_query_service import CRMQueryService
            from flask import current_app

            current_app.logger.info(f"[KnowledgeBase] _get_crm_context: quote_number={quote_number}, client_query={client_query}")

            service = CRMQueryService()
            user = service._get_current_user()

            if not user:
                current_app.logger.warning("[KnowledgeBase] Brak zalogowanego użytkownika")
                return "**Błąd:** Musisz być zalogowany aby sprawdzić dane CRM."

            current_app.logger.info(f"[KnowledgeBase] User: {user.username}, role: {user.role}")
            message_lower = message.lower()

            # Zapytanie o konkretną wycenę
            if quote_number:
                current_app.logger.info(f"[KnowledgeBase] Szukam wyceny: {quote_number}")
                result = service.get_quote_details(user, quote_number)
                current_app.logger.info(f"[KnowledgeBase] Wynik wyceny: success={result.get('success')}")
                if result['success']:
                    formatted = service.format_quote_response(result['quote'])
                    current_app.logger.debug(f"[KnowledgeBase] Sformatowana wycena: {formatted[:200]}...")
                    return f"**Dane wyceny z CRM:**\n\n{formatted}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Zapytanie o klienta
            if client_query:
                current_app.logger.info(f"[KnowledgeBase] Szukam klienta: {client_query}")
                # Sprawdź czy to numer klienta czy nazwa
                result = service.get_client_details(user, client_query)
                current_app.logger.info(f"[KnowledgeBase] Wynik klienta: success={result.get('success')}")

                if result['success']:
                    return f"**Dane klienta z CRM:**\n\n{service.format_client_response(result['client'], result.get('recent_quotes', []))}"
                else:
                    # Może być kilku klientów - wyszukaj
                    search_result = service.search_clients(user, client_query)
                    if search_result['success'] and search_result['clients']:
                        if len(search_result['clients']) == 1:
                            # Jeden klient - pobierz szczegóły
                            client = search_result['clients'][0]
                            detail_result = service.get_client_details(user, client['client_number'])
                            if detail_result['success']:
                                return f"**Dane klienta z CRM:**\n\n{service.format_client_response(detail_result['client'], detail_result.get('recent_quotes', []))}"

                        else:
                            # Wielu klientów
                            clients_list = "\n".join([
                                f"- {c['client_name']} ({c.get('city', 'brak miasta')}) - {c.get('email', 'brak email')}"
                                for c in search_result['clients']
                            ])
                            return f"""**Znaleziono {len(search_result['clients'])} klientów pasujących do "{client_query}":**

{clients_list}

Proszę doprecyzować, o którego klienta chodzi."""

                    return f"**Nie znaleziono klienta:** {client_query}"

            # Zapytanie o statystyki
            if any(kw in message_lower for kw in ['statystyki', 'statystyka', 'ile wycen', 'suma wycen', 'wartość wycen']):
                # Sprawdź czy podano okres
                days = 30
                if '7 dni' in message_lower or 'tydzień' in message_lower or 'tydzien' in message_lower:
                    days = 7
                elif '90 dni' in message_lower or '3 miesiące' in message_lower or '3 miesiac' in message_lower:
                    days = 90
                elif 'rok' in message_lower or '365' in message_lower:
                    days = 365

                result = service.get_quotes_statistics(user, days=days)
                if result['success']:
                    return f"**Dane z CRM:**\n\n{service.format_statistics_response(result['statistics'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Zapytanie o ostatnie wyceny
            if any(kw in message_lower for kw in ['ostatnie wyceny', 'moje wyceny', 'lista wycen', 'pokaż wyceny', 'pokaz wyceny']):
                # Sprawdź filtry
                status_name = None
                if 'zaakceptowan' in message_lower:
                    status_name = 'zaakceptowan'
                elif 'oczekuj' in message_lower or 'wysłan' in message_lower or 'wyslan' in message_lower:
                    status_name = 'wysłan'
                elif 'szkic' in message_lower or 'draft' in message_lower:
                    status_name = 'szkic'

                result = service.search_quotes(user, status_name=status_name, limit=10)
                if result['success']:
                    return f"**Dane z CRM:**\n\n{service.format_quotes_list_response(result['quotes'])}"
                else:
                    return f"**Błąd:** {result['error']}"

            # Ogólna pomoc o wycenach/klientach
            if service._is_partner(user):
                stats = service.get_quotes_statistics(user, days=30)
                if stats['success']:
                    s = stats['statistics']
                    return f"""**Twoje dane w CRM (ostatnie 30 dni):**
- Wycen: {s['total_quotes']}
- Łączna wartość: {s['total_value']:.2f} zł
- Złożonych zamówień: {s['with_orders']}

Mogę pomóc ze szczegółami wyceny (podaj numer) lub klienta (podaj nazwę)."""

            return """**Pomoc - zapytania o CRM:**

Mogę sprawdzić dla Ciebie:
- Szczegóły wyceny (podaj numer np. "wycena 123/01/25/W")
- Dane klienta (np. "dane klienta Kowalski")
- Statystyki wycen (np. "ile wycen w tym miesiącu")
- Ostatnie wyceny (np. "pokaż ostatnie wyceny")

Podaj więcej szczegółów!"""

        except Exception as e:
            from flask import current_app
            import traceback
            current_app.logger.error(f"[KnowledgeBase] Błąd pobierania kontekstu CRM: {e}")
            current_app.logger.error(f"[KnowledgeBase] Traceback: {traceback.format_exc()}")
            return f"**Błąd komunikacji z bazą CRM:** {str(e)}"
