# Symulacja priorytetów — wynik z danych produkcyjnych

- Data uruchomienia: 2026-10-04 (ok. 23:57 czasu serwera)
- Źródło: **produkcja** (baza `crm` na `127.0.0.1`, serwer woodpower-vps) — wariant A
- Wersja skryptu: `scripts/symulacja_priorytetow.py` z gałęzi `claude/logistyka-etap-4`, commit `14adf7d`
- Polecenie (na serwerze, w katalogu aplikacji, jako użytkownik `woodpower-crm`):
  ```
  venv/bin/python /tmp/symulacja_priorytetow.py --core config/core.json --dni 60 --k 2 --blisko 2 --top 30 \
    --out /tmp/symulacja-priorytetow.md --json /tmp/symulacja-priorytetow.json
  ```
  Przebieg z gwiazdkami: to samo + `--gwiazdki /tmp/gwiazdki.csv --out /tmp/symulacja-priorytetow-gwiazdki.md`
- Czas wykonania: ok. 1,6 s (przebieg podstawowy)
- Uwagi z przebiegu:
  - Skrypt trafił na serwer przez `scp` z lokalnego checkoutu gałęzi (ten sam commit `14adf7d`), a nie przez `git fetch` + `git show` na serwerze. Dzięki temu nie dotknąłem repozytorium aplikacji na produkcji. W katalogu aplikacji nie wykonano żadnej operacji git, a skrypt leżał w `/tmp`.
  - Uruchomienie: `sudo -u woodpower-crm`, gołym `venv/bin/python`, bez `flask` i bez `create_app()`. Do bazy nic nie zapisano.
  - Baza produkcyjna nie ma jeszcze tabel logistyki (trasy), kolumny logistyki na zamówieniu są, tras roboczych/zatwierdzonych: 0. Skrypt to wykrył i je pominął, bez błędów.
  - Skrypt nie zgłosił innych ostrzeżeń ani braków kolumn.
  - Pliki wynikowe na serwerze (`/tmp/symulacja-priorytetow*.md|json`, `/tmp/gwiazdki.csv`, `/tmp/symulacja_priorytetow.py`) nadal tam leżą; nic nie kasowałem.
  - Raport i JSON przejrzane: brak nazw klientów i adresów (tylko numery zamówień/pozycji, wymiary, materiał, terminy). Nic nie trzeba było usuwać.

## Raport podstawowy

## Symulacja priorytetów produkcji — 2026-10-04

- Baza: mysql+pymysql://127.0.0.1/crm
- Parametry: stół K=2, „Blisko terminu” 2 dni rob., gwiazdek z pliku: 0, historia 60 dni
- Drabina: g5 > po_terminie > g4 > rozpoczete > blisko_terminu > g3 > g2 > g1 > g0
- Tabele logistyki: brak; kolumny logistyki na zamówieniu: są; tras roboczych/zatwierdzonych: 0

### 1. Co jest dziś w produkcji

| Miara | Wartość |
|---|---|
| zamówień aktywnych | 246 |
| pozycji aktywnych | 556 |
| po terminie | 16 |
| blisko terminu | 13 |
| rozpoczęte (Formatowanie/Pakowanie czeka) | 11 |
| bez terminu | 0 |
| na trasie roboczej/zatwierdzonej | 0 |
| z doróbką | 1 |

Pozycje po statusie: czeka_na_formatowanie 128, czeka_na_krawedzie 33, czeka_na_lakiernie 40, czeka_na_logistyke 1, czeka_na_pakowanie 74, czeka_na_skladanie 149, czeka_na_sklejanie 102, czeka_na_wyciecie 29

Zamówienia po szczeblu drabiny: blisko_terminu 12, g0 210, po_terminie 16, rozpoczete 8

### 2. Kolejki stanowisk po nowemu

„Dziś #” = miejsce w dzisiejszej kolejce (ranga). Przesunięcie liczone dla nowej czołówki.

#### Wycinanie - mikro (kafel = pozycja)

Pozycji: 29 z 20 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 2 / 12 (zamówień wielopozycyjnych: 5). Grup materiał+grubość: 13.
Największe grupy: dąb A/B 3 cm ×6, dąb A/B 1.9 cm ×5, buk A/B 4 cm ×3, dąb B/B 1.9 cm ×3, buk A/B 2 cm ×2, jesion A/B 1.9 cm ×2, dąb A/B 2.5 cm ×2, jesion A/B 2 cm ×1
Nowa czołówka 29: mediana przesunięcia 6 miejsc, max 20; 29 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1697_16 (57.4x22.2x2), 1697_15 (57.4x7.2x2)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 1697_16 | 1697 | 57.4x22.2x2 | buk A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 2 | 3 | 1697_15 | 1697 | 57.4x7.2x2 | buk A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 3 | 5 | 1685_1 | 1685 | 120x36x2 | jesion A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 4 | 1 | 1654_1 | 1654 | 90x50x1.9 | jesion A/B | mikrowczep | 2026-10-05 | blisko_terminu | blisko_terminu |
| 5 | 2 | 1654_2 | 1654 | 85x42x1.9 | jesion A/B | mikrowczep | 2026-10-05 | blisko_terminu | blisko_terminu |
| 6 | 6 | 1834_1 | 1834 | 123x80x3.8 | dąb A/B | mikrowczep | 2026-10-13 | g0 | — |
| 7 | 24 | 1883_6 | 1883 | 195x87x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 8 | 16 | 1870_1 | 1870 | 190x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 9 | 29 | 1878_1 | 1878 | 140x70x3 | dąb A/B | mikrowczep | 2026-11-02 | g0 | — |
| 10 | 22 | 1883_2 | 1883 | 110x27x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 11 | 23 | 1883_4 | 1883 | 85x30x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 12 | 21 | 1883_1 | 1883 | 85x27x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 13 | 8 | 1841_1 | 1841 | 267.5x70x2.5 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 14 | 9 | 1852_1 | 1852 | 114x50x2.5 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 15 | 26 | 1861_2 | 1861 | 150x10x1.9 | dąb A/B | mikrowczep | 2026-10-30 | g0 | — |
| 16 | 7 | 1839_1 | 1839 | 140x70x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 17 | 12 | 1854_3 | 1854 | 130x50x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 18 | 11 | 1854_2 | 1854 | 120x60x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 19 | 10 | 1854_1 | 1854 | 100x50x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 20 | 19 | 1883_3 | 1883 | 110x27x1.5 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 21 | 18 | 1864_2 | 1864 | 260x80x4 | buk A/B | mikrowczep | 2026-10-15 | g0 | — |
| 22 | 14 | 1840_1 | 1840 | 200x70x4 | buk A/B | mikrowczep | 2026-10-14 | g0 | — |
| 23 | 15 | 1843_1 | 1843 | 172.5x70x4 | buk A/B | mikrowczep | 2026-10-14 | g0 | — |
| 24 | 25 | 1844_1 | 1844 | 130x80x4 | dąb B/B | mikrowczep | 2026-10-29 | g0 | — |
| 25 | 17 | 1859_1 | 1859 | 160x80x3 | dąb B/B | mikrowczep | 2026-10-15 | g0 | — |
| 26 | 20 | 1885_1 | 1885 | 280x90x1.9 | dąb B/B | mikrowczep | 2026-10-16 | g0 | — |
| 27 | 27 | 1861_1 | 1861 | 140x10x1.9 | dąb B/B | mikrowczep | 2026-10-30 | g0 | — |
| 28 | 13 | 1853_1 | 1853 | 60x50x1.9 | dąb B/B | mikrowczep | 2026-10-14 | g0 | — |
| 29 | 28 | 1862_1 | 1862 | 120x100x4 | jesion A/B | mikrowczep | 2026-10-30 | g0 | — |

#### Składanie - lite (kafel = pozycja)

Pozycji: 149 z 59 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 10.5 / 28 (zamówień wielopozycyjnych: 20). Grup materiał+grubość: 14.
Największe grupy: dąb A/B 2 cm ×46, dąb A/B 4 cm ×27, dąb B/B 3 cm ×21, buk A/B 3 cm ×17, buk A/B 2 cm ×17, dąb A/B 1.9 cm ×5, buk A/B 1.9 cm ×4, buk A/B 4 cm ×3
Nowa czołówka 30: mediana przesunięcia 64.5 miejsc, max 133; 9 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1668_1 (130x90x4), 1791_1 (115x86x6)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1668_1 | 1668 | 130x90x4 | buk A/B | lity | 2026-10-06 | blisko_terminu | blisko_terminu |
| 2 | 11 | 1791_1 | 1791 | 115x86x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 3 | 123 | 1884_1 | 1884 | 240x100x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 4 | 137 | 1836_1 | 1836 | 230x60x4 | dąb A/B | lity | 2026-10-28 | g0 | — |
| 5 | 121 | 1872_3 | 1872 | 195x103x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 6 | 122 | 1872_4 | 1872 | 180x90x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 7 | 94 | 1858_1 | 1858 | 160x80x4 | dąb A/B | lity | 2026-10-15 | g0 | — |
| 8 | 77 | 1848_1 | 1848 | 140x70x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 9 | 6 | 1760_1 | 1760 | 140x70x4 | dąb A/B | lity | 2026-10-26 | g0 | — |
| 10 | 140 | 1849_1 | 1849 | 140x65x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 11 | 78 | 1847_1 | 1847 | 124x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 12 | 141 | 1849_2 | 1849 | 120x21x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 13 | 85 | 1847_8 | 1847 | 118x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 14 | 83 | 1847_6 | 1847 | 112x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 15 | 84 | 1847_7 | 1847 | 112x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 16 | 76 | 1820_1 | 1820 | 110x65x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 17 | 10 | 1793_1 | 1793 | 105x30x4 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 18 | 120 | 1872_2 | 1872 | 102x30.5x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 19 | 119 | 1872_1 | 1872 | 102x29.5x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 20 | 4 | 1738_2 | 1738 | 100x100x4 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 21 | 13 | 1804_1 | 1804 | 100x30x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 22 | 3 | 1738_1 | 1738 | 100x29x4 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 23 | 81 | 1847_4 | 1847 | 95x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 24 | 86 | 1847_9 | 1847 | 94x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 25 | 79 | 1847_2 | 1847 | 93x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 26 | 80 | 1847_3 | 1847 | 93x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 27 | 82 | 1847_5 | 1847 | 91x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 28 | 9 | 1780_1 | 1780 | 90x26x4 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 29 | 142 | 1855_1 | 1855 | 70x22x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 30 | 8 | 1794_2 | 1794 | 50x120x3.5 | dąb A/B | lity | 2026-10-12 | g0 | — |

#### Sklejanie (kafel = pozycja)

Pozycji: 102 z 52 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 3.5 / 23 (zamówień wielopozycyjnych: 20). Grup materiał+grubość: 16.
Największe grupy: dąb B/B 3 cm ×27, buk A/B 3 cm ×13, dąb A/B 4 cm ×13, dąb A/B 1.9 cm ×12, dąb A/B 2 cm ×12, dąb B/B 2 cm ×6, dąb A/B 6 cm ×4, dąb B/B 4 cm ×3
Nowa czołówka 30: mediana przesunięcia 24.5 miejsc, max 54; 12 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1772_1 (110x100x1.9), 1608_2 (103.5x30x3)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1772_1 (doróbka) | 1772 | 110x100x1.9 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 2 | 2 | 1608_2 | 1608 | 103.5x30x3 | dąb A/B | lity | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 3 | 3 | 1637_1 | 1637 | 140x70x3 | buk A/B | lity | 2026-10-02 | po_terminie | po_terminie |
| 4 | 8 | 1689_24 | 1689 | 260x7x4 | dąb A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 5 | 55 | 1790_3 | 1790 | 160x90x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 6 | 54 | 1790_1 | 1790 | 127x29x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 7 | 56 | 1790_10 | 1790 | 110x120x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 8 | 11 | 1719_7 | 1719 | 110x66x4 | dąb A/B | lity | 2026-10-08 | rozpoczete | rozpoczete |
| 9 | 43 | 1790_11 | 1790 | 240x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 10 | 41 | 1790_8 | 1790 | 220x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 11 | 40 | 1790_7 | 1790 | 185x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 12 | 42 | 1790_9 | 1790 | 160x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 13 | 39 | 1790_6 | 1790 | 160x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 14 | 37 | 1790_4 | 1790 | 126x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 15 | 38 | 1790_5 | 1790 | 110x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 16 | 6 | 1682_4 | 1682 | 107.2x8x2 | dąb A/B | lity | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 17 | 7 | 1682_2 | 1682 | 15x27x1.8 | dąb A/B | mikrowczep | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 18 | 20 | 1763_6 | 1763 | 90x7x2 | buk A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 19 | 9 | 1697_11 | 1697 | 52.2x81.2x2 | buk A/B | lity | 2026-10-07 | rozpoczete | rozpoczete |
| 20 | 5 | 1647_1 | 1647 | 100x60x4 | buk A/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 21 | 58 | 1789_2 | 1789 | 121.8x52.7x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 22 | 59 | 1789_3 | 1789 | 111.5x104.5x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 23 | 60 | 1789_4 | 1789 | 105.5x45x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 24 | 57 | 1789_1 | 1789 | 100x26x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 25 | 79 | 1828_5 | 1828 | 250x12x5.5 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 26 | 77 | 1818_2 | 1818 | 90x40x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 27 | 76 | 1818_1 | 1818 | 90x30x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 28 | 34 | 1754_1 | 1754 | 80x60x4 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 29 | 15 | 1724_4 | 1724 | 79x55.5x4 | dąb A/B | lity | 2026-10-08 | g0 | — |
| 30 | 12 | 1724_1 | 1724 | 79x30x4 | dąb A/B | lity | 2026-10-08 | g0 | — |

#### Formatowanie (kafel = zamówienie)

Zamówień czekających: 29, w tym kompletnych 23, niekompletnych 6 (czekają na pozycje z wcześniejszych stanowisk).
Nowa czołówka 29: mediana przesunięcia 2 miejsc, max 15; 29 z nich jest też w dzisiejszej czołówce.

Na stole (K=2, tylko kompletne): 1307, 1451

Niekompletne (do K): 1608 1/2, brakuje: 1608_2@czeka_na_sklejanie; 1689 27/28, brakuje: 1689_24@czeka_na_sklejanie

| # | Dziś # | Zam. | Kompletne | Na stan./aktywnych | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 1307 | tak | 2/2 | 2026-09-18 | po_terminie | po_terminie |
| 2 | 3 | 1451 | tak | 1/1 | 2026-09-25 | po_terminie | po_terminie |
| 3 | 4 | 1517 | tak | 1/1 | 2026-09-28 | po_terminie | po_terminie, rozpoczete |
| 4 | 5 | 1519 | tak | 1/1 | 2026-09-28 | po_terminie | po_terminie |
| 5 | 6 | 1545 | tak | 1/1 | 2026-09-29 | po_terminie | po_terminie |
| 6 | 7 | 1551 | tak | 2/2 | 2026-09-29 | po_terminie | po_terminie |
| 7 | 8 | 1608 | NIE | 1/2 | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 8 | 9 | 1621 | tak | 1/1 | 2026-10-02 | po_terminie | po_terminie |
| 9 | 10 | 1640 | tak | 1/1 | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 10 | 14 | 1689 | NIE | 27/28 | 2026-10-07 | rozpoczete | rozpoczete |
| 11 | 16 | 1697 | NIE | 15/18 | 2026-10-07 | rozpoczete | rozpoczete |
| 12 | 18 | 1719 | NIE | 13/14 | 2026-10-08 | rozpoczete | rozpoczete |
| 13 | 21 | 1763 | NIE | 5/6 | 2026-10-09 | rozpoczete | rozpoczete |
| 14 | 26 | 1790 | NIE | 1/11 | 2026-10-12 | rozpoczete | rozpoczete |
| 15 | 2 | 1304 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 16 | 13 | 1665 | tak | 2/2 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 17 | 15 | 1687 | tak | 9/9 | 2026-10-07 | g0 | — |
| 18 | 17 | 1699 | tak | 25/25 | 2026-10-08 | g0 | — |
| 19 | 19 | 1727 | tak | 2/2 | 2026-10-08 | g0 | — |
| 20 | 20 | 1743 | tak | 1/1 | 2026-10-09 | g0 | — |
| 21 | 27 | 1779 | tak | 1/1 | 2026-10-12 | g0 | — |
| 22 | 28 | 1781 | tak | 1/1 | 2026-10-12 | g0 | — |
| 23 | 24 | 1784 | tak | 6/6 | 2026-10-12 | g0 | — |
| 24 | 25 | 1786 | tak | 3/3 | 2026-10-12 | g0 | — |
| 25 | 29 | 1798 | tak | 1/1 | 2026-10-12 | g0 | — |
| 26 | 11 | 1520 | tak | 1/1 | 2026-10-13 | g0 | — |
| 27 | 12 | 1547 | tak | 1/1 | 2026-10-14 | g0 | — |
| 28 | 22 | 1680 | tak | 1/1 | 2026-10-21 | g0 | — |
| 29 | 23 | 1701 | tak | 1/1 | 2026-10-23 | g0 | — |

#### Krawędzie (kafel = pozycja)

Pozycji: 33 z 20 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 1.0 / 6 (zamówień wielopozycyjnych: 8). Grup materiał+grubość: 8.
Największe grupy: dąb A/B 3 cm ×11, dąb A/B 2 cm ×7, dąb B/B 3 cm ×5, buk A/B 3 cm ×4, dąb A/B 4 cm ×2, dąb A/B 3.2 cm ×2, buk A/B 4 cm ×1, dąb B/B 4 cm ×1
Nowa czołówka 30: mediana przesunięcia 7.5 miejsc, max 26; 27 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1682_3 (113.2x49.5x2), 1736_1 (100x33x2)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 1682_3 | 1682 | 113.2x49.5x2 | dąb A/B | lity | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 2 | 17 | 1736_1 | 1736 | 100x33x2 | dąb A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 3 | 18 | 1736_3 | 1736 | 100x33x2 | dąb A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 4 | 9 | 1657_2 | 1657 | 121x30x3 | dąb B/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 5 | 8 | 1657_1 | 1657 | 103x30x3 | dąb B/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 6 | 16 | 1710_1 | 1710 | 180x80x4 | buk A/B | mikrowczep | 2026-10-08 | g0 | — |
| 7 | 13 | 1702_1 | 1702 | 160x75x3 | buk A/B | lity | 2026-10-07 | g0 | — |
| 8 | 14 | 1722_1 | 1722 | 154x18x3 | buk A/B | lity | 2026-10-08 | g0 | — |
| 9 | 15 | 1722_2 | 1722 | 145x18x3 | buk A/B | lity | 2026-10-08 | g0 | — |
| 10 | 12 | 1692_1 | 1692 | 120x70x3 | buk A/B | lity | 2026-10-07 | g0 | — |
| 11 | 26 | 1744_1 | 1744 | 180x85x4 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 12 | 5 | 1604_1 | 1604 | 64x26x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 13 | 6 | 1598_1 | 1598 | 190.5x52.2x3.2 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 14 | 7 | 1598_2 | 1598 | 53.2x52.2x3.2 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 15 | 2 | 1513_1 | 1513 | 280x90x3 | dąb A/B | mikrowczep | 2026-10-13 | g0 | — |
| 16 | 30 | 1788_4 | 1788 | 170x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 17 | 27 | 1788_1 | 1788 | 155x15x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 18 | 25 | 1766_2 | 1766 | 150x40x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 19 | 33 | 1788_7 | 1788 | 130x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 20 | 31 | 1788_5 | 1788 | 120x30x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 21 | 29 | 1788_3 | 1788 | 120x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 22 | 32 | 1788_6 | 1788 | 120x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 23 | 1 | 1425_1 | 1425 | 108x36x3 | dąb A/B | mikrowczep | 2026-10-09 | g0 | — |
| 24 | 24 | 1766_1 | 1766 | 90x40x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 25 | 28 | 1788_2 | 1788 | 70x30x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 26 | 11 | 1704_1 | 1704 | 114x72x2 | dąb A/B | lity | 2026-10-07 | g0 | — |
| 27 | 22 | 1717_2 | 1717 | 105.5x18x2 | dąb A/B | lity | 2026-10-23 | g0 | — |
| 28 | 21 | 1717_1 | 1717 | 105.5x17.5x2 | dąb A/B | lity | 2026-10-23 | g0 | — |
| 29 | 3 | 1579_1 | 1579 | 57x25x2 | dąb A/B | lity | 2026-10-15 | g0 | — |
| 30 | 23 | 1740_1 | 1740 | 200x75x4 | dąb B/B | lity | 2026-10-26 | g0 | — |

#### Lakiernia (kafel = pozycja)

Pozycji: 40 z 24 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 2.0 / 6 (zamówień wielopozycyjnych: 8). Grup materiał+grubość: 10.
Największe grupy: dąb B/B 3 cm ×12, dąb A/B 3 cm ×10, dąb A/B 2 cm ×6, jesion A/B 2 cm ×3, dąb A/B 1.9 cm ×3, dąb A/B 4 cm ×2, dąb B/B 2.5 cm ×1, dąb B/B 1.5 cm ×1
Nowa czołówka 30: mediana przesunięcia 9.5 miejsc, max 30; 23 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1709_1 (200x40x3), 1619_1 (160x50x3)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 31 | 1709_1 | 1709 | 200x40x3 | dąb B/B | lity | 2026-10-23 | g0 | — |
| 2 | 11 | 1619_1 | 1619 | 160x50x3 | dąb B/B | lity | 2026-10-19 | g0 | — |
| 3 | 9 | 1588_1 | 1588 | 150x70x3 | dąb B/B | lity | 2026-10-16 | g0 | — |
| 4 | 18 | 1671_3 | 1671 | 140x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 5 | 14 | 1655_1 | 1655 | 135x65x3 | dąb B/B | lity | 2026-10-20 | g0 | — |
| 6 | 19 | 1671_4 | 1671 | 120x40x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 7 | 24 | 1690_2 | 1690 | 105x29x3 | dąb B/B | lity | 2026-10-22 | g0 | — |
| 8 | 17 | 1671_2 | 1671 | 100x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 9 | 23 | 1690_1 | 1690 | 100x29x3 | dąb B/B | lity | 2026-10-22 | g0 | — |
| 10 | 16 | 1671_1 | 1671 | 70x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 11 | 3 | 1538_1 | 1538 | 70x50x3 | dąb B/B | lity | 2026-10-14 | g0 | — |
| 12 | 10 | 1631_1 | 1631 | 59.5x16x3 | dąb B/B | lity | 2026-10-19 | g0 | — |
| 13 | 1 | 1481_1 | 1481 | 60x45x2.5 | dąb B/B | lity | 2026-10-12 | g0 | — |
| 14 | 38 | 1761_1 | 1761 | 46x35x1.5 | dąb B/B | lity | 2026-10-26 | g0 | — |
| 15 | 2 | 1476_1 | 1476 | 170x90x3 | jesion A/B | mikrowczep | 2026-10-12 | g0 | — |
| 16 | 7 | 1573_2 | 1573 | 80x61x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 17 | 6 | 1573_1 | 1573 | 50x60x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 18 | 8 | 1573_3 | 1573 | 40x46x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 19 | 37 | 1729_1 | 1729 | 149x44x4 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 20 | 12 | 1622_1 | 1622 | 140x80x4 | dąb A/B | lity | 2026-10-19 | g0 | — |
| 21 | 21 | 1673_2 | 1673 | 271x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 22 | 4 | 1581_1 | 1581 | 266x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 23 | 5 | 1581_2 | 1581 | 234x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 24 | 36 | 1728_1 | 1728 | 180x80x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 25 | 22 | 1673_3 | 1673 | 180x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 26 | 34 | 1711_1 | 1711 | 180x20x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 27 | 35 | 1711_2 | 1711 | 166x20x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 28 | 20 | 1673_1 | 1673 | 161.5x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 29 | 15 | 1672_1 | 1672 | 160x57x3 | dąb A/B | lity | 2026-10-21 | g0 | — |
| 30 | 39 | 1771_1 | 1771 | 80x30x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |

#### Pakowanie (kafel = zamówienie)

Zamówień czekających: 56, w tym kompletnych 54, niekompletnych 2 (czekają na pozycje z wcześniejszych stanowisk).
Nowa czołówka 30: mediana przesunięcia 8.0 miejsc, max 26; 23 z nich jest też w dzisiejszej czołówce.

Na stole (K=2, tylko kompletne): 1429, 1445

Niekompletne (do K): 1682 2/5, brakuje: 1682_2@czeka_na_sklejanie, 1682_3@czeka_na_krawedzie, 1682_4@czeka_na_sklejanie; 1736 1/3, brakuje: 1736_1@czeka_na_krawedzie, 1736_3@czeka_na_krawedzie

| # | Dziś # | Zam. | Kompletne | Na stan./aktywnych | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|
| 1 | 2 | 1429 | tak | 1/1 | 2026-09-24 | po_terminie | po_terminie |
| 2 | 3 | 1445 | tak | 3/3 | 2026-09-24 | po_terminie | po_terminie |
| 3 | 9 | 1575 | tak | 1/1 | 2026-09-30 | po_terminie | po_terminie |
| 4 | 10 | 1585 | tak | 1/1 | 2026-09-30 | po_terminie | po_terminie |
| 5 | 11 | 1630 | tak | 2/2 | 2026-10-02 | po_terminie | po_terminie |
| 6 | 22 | 1682 | NIE | 2/5 | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 7 | 33 | 1736 | NIE | 1/3 | 2026-10-09 | rozpoczete | rozpoczete |
| 8 | 1 | 1313 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 9 | 20 | 1649 | tak | 2/2 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 10 | 18 | 1656 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 11 | 19 | 1658 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 12 | 4 | 1357 | tak | 1/1 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 13 | 21 | 1674 | tak | 1/1 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 14 | 5 | 1394 | tak | 1/1 | 2026-10-07 | g0 | — |
| 15 | 25 | 1691 | tak | 1/1 | 2026-10-07 | g0 | — |
| 16 | 24 | 1693 | tak | 1/1 | 2026-10-07 | g0 | — |
| 17 | 23 | 1703 | tak | 1/1 | 2026-10-07 | g0 | — |
| 18 | 26 | 1705 | tak | 1/1 | 2026-10-07 | g0 | — |
| 19 | 6 | 1415 | tak | 1/1 | 2026-10-08 | g0 | — |
| 20 | 28 | 1707 | tak | 1/1 | 2026-10-08 | g0 | — |
| 21 | 29 | 1715 | tak | 1/1 | 2026-10-08 | g0 | — |
| 22 | 32 | 1716 | tak | 2/2 | 2026-10-08 | g0 | — |
| 23 | 30 | 1731 | tak | 1/1 | 2026-10-08 | g0 | — |
| 24 | 27 | 1733 | tak | 1/1 | 2026-10-08 | g0 | — |
| 25 | 31 | 1734 | tak | 3/3 | 2026-10-08 | g0 | — |
| 26 | 7 | 1436 | tak | 1/1 | 2026-10-09 | g0 | — |
| 27 | 38 | 1739 | tak | 1/1 | 2026-10-09 | g0 | — |
| 28 | 45 | 1741 | tak | 2/2 | 2026-10-09 | g0 | — |
| 29 | 34 | 1747 | tak | 4/4 | 2026-10-09 | g0 | — |
| 30 | 39 | 1749 | tak | 1/1 | 2026-10-09 | g0 | — |

### 3. Historia (ostatnie 60 dni, od 2026-08-05)

#### 3.1 Omijanie pilniejszych pozycji

Dla każdego zakończenia: ile pozycji innego zamówienia o wcześniejszym terminie czekało wtedy na tym stanowisku. Wejście na stanowisko = zakończenie poprzedniego (z kolumn `*_completed_at`); pozycje zakończone „w tej samej chwili” co wejście (auto-pominięcie) wyłączone.

| Stanowisko | Zakończeń | Z pominięciem pilniejszego | …o ≥3 dni | Mediana pominiętych | Mediana czekających |
|---|---|---|---|---|---|
| Wycinanie - mikro | 606 | 84% | 68% | 10.0 | 31.5 |
| Składanie - lite | 1207 | 88% | 77% | 6 | 36 |
| Sklejanie | 1737 | 96% | 88% | 12 | 53 |
| Formatowanie | 1743 | 96% | 89% | 18 | 51 |
| Krawędzie | 1539 | 78% | 69% | 4 | 15 |
| Lakiernia | 179 | 71% | 56% | 2 | 24 |
| Pakowanie | 1427 | 94% | 86% | 15 | 43 |

#### 3.2 Rozrzut pozycji jednego zamówienia przed stanowiskiem zamówieniowym

Czas między wejściem pierwszej i ostatniej pozycji zamówienia na stanowisko (zamówienia ≥2 pozycji, których ostatnia pozycja weszła w oknie). To jest dzisiejsza miara „ile Formatowanie/Pakowanie czeka na komplet”.

| Stanowisko | Zamówień | Mediana h | p90 h | >24 h | >72 h |
|---|---|---|---|---|---|
| Formatowanie | 287 | 0.4 | 70.8 | 20% | 10% |
| Pakowanie | 298 | 0.0 | 28.8 | 12% | 7% |

#### 3.3 Zdarzenia stanowiskowe (zmiany liczników)

| Stanowisko | Zdarzeń | Z tabletów | Dni z aktywnością | Średnio dziennie |
|---|---|---|---|---|
| Składanie - lite | 2788 | 2788 | 43 | 64.8 |
| Wycinanie - mikro | 1008 | 1008 | 29 | 34.8 |
| Krawędzie | 1595 | 209 | 45 | 35.4 |
| Formatowanie | 3279 | 3279 | 42 | 78.1 |
| Sklejanie | 3673 | 3673 | 42 | 87.5 |
| Pakowanie | 2764 | 2759 | 42 | 65.8 |
| Lakiernia | 283 | 250 | 25 | 11.3 |

### 4. Jak czytać

- Bez gwiazdek i tras nowa kolejka różni się od dzisiejszej głównie tagami terminowymi i grupowaniem po materiale; plik `--gwiazdki` pozwala zasymulować decyzje biura.
- Duży rozrzut pozycji zamówienia w nowej kolejce Sklejania przy małym rozrzucie historycznym oznacza, że grupowanie po materiale wydłuży czekanie Formatowania — wtedy tag „Rozpoczęte” musi stać wysoko albo trzeba ograniczyć grupowanie do bloków.
- Wysoki udział „z pominięciem pilniejszego” to miara dzisiejszego wybierania łatwych pozycji; po wdrożeniu stołu ta sama miara powinna spaść do odłożeń z powodem.

## Raport z gwiazdkami

Użyty CSV (gwiazdki wybrane hipotetycznie: zamówienia po terminie i duże rozpoczęte, tylko do pokazania efektu):

```
numer,gwiazdki
1307,5
1445,5
1608,4
1637,4
1517,4
1668,3
1790,3
1682,3
```

## Symulacja priorytetów produkcji — 2026-10-04

- Baza: mysql+pymysql://127.0.0.1/crm
- Parametry: stół K=2, „Blisko terminu” 2 dni rob., gwiazdek z pliku: 8, historia 60 dni
- Drabina: g5 > po_terminie > g4 > rozpoczete > blisko_terminu > g3 > g2 > g1 > g0
- Tabele logistyki: brak; kolumny logistyki na zamówieniu: są; tras roboczych/zatwierdzonych: 0

### 1. Co jest dziś w produkcji

| Miara | Wartość |
|---|---|
| zamówień aktywnych | 246 |
| pozycji aktywnych | 556 |
| po terminie | 16 |
| blisko terminu | 13 |
| rozpoczęte (Formatowanie/Pakowanie czeka) | 11 |
| bez terminu | 0 |
| na trasie roboczej/zatwierdzonej | 0 |
| z doróbką | 1 |

Pozycje po statusie: czeka_na_formatowanie 128, czeka_na_krawedzie 33, czeka_na_lakiernie 40, czeka_na_logistyke 1, czeka_na_pakowanie 74, czeka_na_skladanie 149, czeka_na_sklejanie 102, czeka_na_wyciecie 29

Zamówienia po szczeblu drabiny: blisko_terminu 12, g0 210, g5 2, po_terminie 14, rozpoczete 8

### 2. Kolejki stanowisk po nowemu

„Dziś #” = miejsce w dzisiejszej kolejce (ranga). Przesunięcie liczone dla nowej czołówki.

#### Wycinanie - mikro (kafel = pozycja)

Pozycji: 29 z 20 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 2 / 12 (zamówień wielopozycyjnych: 5). Grup materiał+grubość: 13.
Największe grupy: dąb A/B 3 cm ×6, dąb A/B 1.9 cm ×5, buk A/B 4 cm ×3, dąb B/B 1.9 cm ×3, buk A/B 2 cm ×2, jesion A/B 1.9 cm ×2, dąb A/B 2.5 cm ×2, jesion A/B 2 cm ×1
Nowa czołówka 29: mediana przesunięcia 6 miejsc, max 20; 29 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1697_16 (57.4x22.2x2), 1697_15 (57.4x7.2x2)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4 | 1697_16 | 1697 | 57.4x22.2x2 | buk A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 2 | 3 | 1697_15 | 1697 | 57.4x7.2x2 | buk A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 3 | 5 | 1685_1 | 1685 | 120x36x2 | jesion A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 4 | 1 | 1654_1 | 1654 | 90x50x1.9 | jesion A/B | mikrowczep | 2026-10-05 | blisko_terminu | blisko_terminu |
| 5 | 2 | 1654_2 | 1654 | 85x42x1.9 | jesion A/B | mikrowczep | 2026-10-05 | blisko_terminu | blisko_terminu |
| 6 | 6 | 1834_1 | 1834 | 123x80x3.8 | dąb A/B | mikrowczep | 2026-10-13 | g0 | — |
| 7 | 24 | 1883_6 | 1883 | 195x87x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 8 | 16 | 1870_1 | 1870 | 190x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 9 | 29 | 1878_1 | 1878 | 140x70x3 | dąb A/B | mikrowczep | 2026-11-02 | g0 | — |
| 10 | 22 | 1883_2 | 1883 | 110x27x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 11 | 23 | 1883_4 | 1883 | 85x30x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 12 | 21 | 1883_1 | 1883 | 85x27x3 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 13 | 8 | 1841_1 | 1841 | 267.5x70x2.5 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 14 | 9 | 1852_1 | 1852 | 114x50x2.5 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 15 | 26 | 1861_2 | 1861 | 150x10x1.9 | dąb A/B | mikrowczep | 2026-10-30 | g0 | — |
| 16 | 7 | 1839_1 | 1839 | 140x70x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 17 | 12 | 1854_3 | 1854 | 130x50x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 18 | 11 | 1854_2 | 1854 | 120x60x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 19 | 10 | 1854_1 | 1854 | 100x50x1.9 | dąb A/B | mikrowczep | 2026-10-14 | g0 | — |
| 20 | 19 | 1883_3 | 1883 | 110x27x1.5 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 21 | 18 | 1864_2 | 1864 | 260x80x4 | buk A/B | mikrowczep | 2026-10-15 | g0 | — |
| 22 | 14 | 1840_1 | 1840 | 200x70x4 | buk A/B | mikrowczep | 2026-10-14 | g0 | — |
| 23 | 15 | 1843_1 | 1843 | 172.5x70x4 | buk A/B | mikrowczep | 2026-10-14 | g0 | — |
| 24 | 25 | 1844_1 | 1844 | 130x80x4 | dąb B/B | mikrowczep | 2026-10-29 | g0 | — |
| 25 | 17 | 1859_1 | 1859 | 160x80x3 | dąb B/B | mikrowczep | 2026-10-15 | g0 | — |
| 26 | 20 | 1885_1 | 1885 | 280x90x1.9 | dąb B/B | mikrowczep | 2026-10-16 | g0 | — |
| 27 | 27 | 1861_1 | 1861 | 140x10x1.9 | dąb B/B | mikrowczep | 2026-10-30 | g0 | — |
| 28 | 13 | 1853_1 | 1853 | 60x50x1.9 | dąb B/B | mikrowczep | 2026-10-14 | g0 | — |
| 29 | 28 | 1862_1 | 1862 | 120x100x4 | jesion A/B | mikrowczep | 2026-10-30 | g0 | — |

#### Składanie - lite (kafel = pozycja)

Pozycji: 149 z 59 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 10.5 / 28 (zamówień wielopozycyjnych: 20). Grup materiał+grubość: 14.
Największe grupy: dąb A/B 2 cm ×46, dąb A/B 4 cm ×27, dąb B/B 3 cm ×21, buk A/B 3 cm ×17, buk A/B 2 cm ×17, dąb A/B 1.9 cm ×5, buk A/B 1.9 cm ×4, buk A/B 4 cm ×3
Nowa czołówka 30: mediana przesunięcia 64.5 miejsc, max 133; 9 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1668_1 (130x90x4), 1791_1 (115x86x6)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1668_1 | 1668 | 130x90x4 | buk A/B | lity | 2026-10-06 | blisko_terminu | blisko_terminu |
| 2 | 11 | 1791_1 | 1791 | 115x86x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 3 | 123 | 1884_1 | 1884 | 240x100x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 4 | 137 | 1836_1 | 1836 | 230x60x4 | dąb A/B | lity | 2026-10-28 | g0 | — |
| 5 | 121 | 1872_3 | 1872 | 195x103x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 6 | 122 | 1872_4 | 1872 | 180x90x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 7 | 94 | 1858_1 | 1858 | 160x80x4 | dąb A/B | lity | 2026-10-15 | g0 | — |
| 8 | 77 | 1848_1 | 1848 | 140x70x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 9 | 6 | 1760_1 | 1760 | 140x70x4 | dąb A/B | lity | 2026-10-26 | g0 | — |
| 10 | 140 | 1849_1 | 1849 | 140x65x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 11 | 78 | 1847_1 | 1847 | 124x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 12 | 141 | 1849_2 | 1849 | 120x21x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 13 | 85 | 1847_8 | 1847 | 118x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 14 | 83 | 1847_6 | 1847 | 112x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 15 | 84 | 1847_7 | 1847 | 112x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 16 | 76 | 1820_1 | 1820 | 110x65x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 17 | 10 | 1793_1 | 1793 | 105x30x4 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 18 | 120 | 1872_2 | 1872 | 102x30.5x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 19 | 119 | 1872_1 | 1872 | 102x29.5x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 20 | 4 | 1738_2 | 1738 | 100x100x4 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 21 | 13 | 1804_1 | 1804 | 100x30x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 22 | 3 | 1738_1 | 1738 | 100x29x4 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 23 | 81 | 1847_4 | 1847 | 95x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 24 | 86 | 1847_9 | 1847 | 94x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 25 | 79 | 1847_2 | 1847 | 93x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 26 | 80 | 1847_3 | 1847 | 93x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 27 | 82 | 1847_5 | 1847 | 91x30x4 | dąb A/B | lity | 2026-10-14 | g0 | — |
| 28 | 9 | 1780_1 | 1780 | 90x26x4 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 29 | 142 | 1855_1 | 1855 | 70x22x4 | dąb A/B | lity | 2026-10-29 | g0 | — |
| 30 | 8 | 1794_2 | 1794 | 50x120x3.5 | dąb A/B | lity | 2026-10-12 | g0 | — |

#### Sklejanie (kafel = pozycja)

Pozycji: 102 z 52 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 3.5 / 23 (zamówień wielopozycyjnych: 20). Grup materiał+grubość: 16.
Największe grupy: dąb B/B 3 cm ×27, buk A/B 3 cm ×13, dąb A/B 4 cm ×13, dąb A/B 1.9 cm ×12, dąb A/B 2 cm ×12, dąb B/B 2 cm ×6, dąb A/B 6 cm ×4, dąb B/B 4 cm ×3
Nowa czołówka 30: mediana przesunięcia 26.5 miejsc, max 54; 12 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1772_1 (110x100x1.9), 1608_2 (103.5x30x3)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1772_1 (doróbka) | 1772 | 110x100x1.9 | dąb A/B | lity | 2026-10-09 | g0 | — |
| 2 | 2 | 1608_2 | 1608 | 103.5x30x3 | dąb A/B | lity | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 3 | 3 | 1637_1 | 1637 | 140x70x3 | buk A/B | lity | 2026-10-02 | po_terminie | po_terminie |
| 4 | 55 | 1790_3 | 1790 | 160x90x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 5 | 54 | 1790_1 | 1790 | 127x29x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 6 | 56 | 1790_10 | 1790 | 110x120x4 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 7 | 43 | 1790_11 | 1790 | 240x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 8 | 41 | 1790_8 | 1790 | 220x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 9 | 40 | 1790_7 | 1790 | 185x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 10 | 42 | 1790_9 | 1790 | 160x28x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 11 | 39 | 1790_6 | 1790 | 160x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 12 | 37 | 1790_4 | 1790 | 126x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 13 | 38 | 1790_5 | 1790 | 110x20.2x2 | dąb A/B | lity | 2026-10-12 | rozpoczete | rozpoczete |
| 14 | 6 | 1682_4 | 1682 | 107.2x8x2 | dąb A/B | lity | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 15 | 7 | 1682_2 | 1682 | 15x27x1.8 | dąb A/B | mikrowczep | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 16 | 8 | 1689_24 | 1689 | 260x7x4 | dąb A/B | mikrowczep | 2026-10-07 | rozpoczete | rozpoczete |
| 17 | 11 | 1719_7 | 1719 | 110x66x4 | dąb A/B | lity | 2026-10-08 | rozpoczete | rozpoczete |
| 18 | 20 | 1763_6 | 1763 | 90x7x2 | buk A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 19 | 9 | 1697_11 | 1697 | 52.2x81.2x2 | buk A/B | lity | 2026-10-07 | rozpoczete | rozpoczete |
| 20 | 5 | 1647_1 | 1647 | 100x60x4 | buk A/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 21 | 58 | 1789_2 | 1789 | 121.8x52.7x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 22 | 59 | 1789_3 | 1789 | 111.5x104.5x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 23 | 60 | 1789_4 | 1789 | 105.5x45x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 24 | 57 | 1789_1 | 1789 | 100x26x6 | dąb A/B | lity | 2026-10-12 | g0 | — |
| 25 | 79 | 1828_5 | 1828 | 250x12x5.5 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 26 | 77 | 1818_2 | 1818 | 90x40x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 27 | 76 | 1818_1 | 1818 | 90x30x4 | dąb A/B | lity | 2026-10-13 | g0 | — |
| 28 | 34 | 1754_1 | 1754 | 80x60x4 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 29 | 15 | 1724_4 | 1724 | 79x55.5x4 | dąb A/B | lity | 2026-10-08 | g0 | — |
| 30 | 12 | 1724_1 | 1724 | 79x30x4 | dąb A/B | lity | 2026-10-08 | g0 | — |

#### Formatowanie (kafel = zamówienie)

Zamówień czekających: 29, w tym kompletnych 23, niekompletnych 6 (czekają na pozycje z wcześniejszych stanowisk).
Nowa czołówka 29: mediana przesunięcia 3 miejsc, max 16; 29 z nich jest też w dzisiejszej czołówce.

Na stole (K=2, tylko kompletne): 1307, 1517

Niekompletne (do K): 1608 1/2, brakuje: 1608_2@czeka_na_sklejanie; 1790 1/11, brakuje: 1790_1@czeka_na_sklejanie, 1790_3@czeka_na_sklejanie, 1790_4@czeka_na_sklejanie, 1790_5@czeka_na_sklejanie …

| # | Dziś # | Zam. | Kompletne | Na stan./aktywnych | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 1307 | tak | 2/2 | 2026-09-18 | g5 | po_terminie |
| 2 | 4 | 1517 | tak | 1/1 | 2026-09-28 | po_terminie | po_terminie, rozpoczete |
| 3 | 8 | 1608 | NIE | 1/2 | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 4 | 3 | 1451 | tak | 1/1 | 2026-09-25 | po_terminie | po_terminie |
| 5 | 5 | 1519 | tak | 1/1 | 2026-09-28 | po_terminie | po_terminie |
| 6 | 6 | 1545 | tak | 1/1 | 2026-09-29 | po_terminie | po_terminie |
| 7 | 7 | 1551 | tak | 2/2 | 2026-09-29 | po_terminie | po_terminie |
| 8 | 9 | 1621 | tak | 1/1 | 2026-10-02 | po_terminie | po_terminie |
| 9 | 10 | 1640 | tak | 1/1 | 2026-10-02 | po_terminie | po_terminie, rozpoczete |
| 10 | 26 | 1790 | NIE | 1/11 | 2026-10-12 | rozpoczete | rozpoczete |
| 11 | 14 | 1689 | NIE | 27/28 | 2026-10-07 | rozpoczete | rozpoczete |
| 12 | 16 | 1697 | NIE | 15/18 | 2026-10-07 | rozpoczete | rozpoczete |
| 13 | 18 | 1719 | NIE | 13/14 | 2026-10-08 | rozpoczete | rozpoczete |
| 14 | 21 | 1763 | NIE | 5/6 | 2026-10-09 | rozpoczete | rozpoczete |
| 15 | 2 | 1304 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 16 | 13 | 1665 | tak | 2/2 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 17 | 15 | 1687 | tak | 9/9 | 2026-10-07 | g0 | — |
| 18 | 17 | 1699 | tak | 25/25 | 2026-10-08 | g0 | — |
| 19 | 19 | 1727 | tak | 2/2 | 2026-10-08 | g0 | — |
| 20 | 20 | 1743 | tak | 1/1 | 2026-10-09 | g0 | — |
| 21 | 27 | 1779 | tak | 1/1 | 2026-10-12 | g0 | — |
| 22 | 28 | 1781 | tak | 1/1 | 2026-10-12 | g0 | — |
| 23 | 24 | 1784 | tak | 6/6 | 2026-10-12 | g0 | — |
| 24 | 25 | 1786 | tak | 3/3 | 2026-10-12 | g0 | — |
| 25 | 29 | 1798 | tak | 1/1 | 2026-10-12 | g0 | — |
| 26 | 11 | 1520 | tak | 1/1 | 2026-10-13 | g0 | — |
| 27 | 12 | 1547 | tak | 1/1 | 2026-10-14 | g0 | — |
| 28 | 22 | 1680 | tak | 1/1 | 2026-10-21 | g0 | — |
| 29 | 23 | 1701 | tak | 1/1 | 2026-10-23 | g0 | — |

#### Krawędzie (kafel = pozycja)

Pozycji: 33 z 20 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 1.0 / 6 (zamówień wielopozycyjnych: 8). Grup materiał+grubość: 8.
Największe grupy: dąb A/B 3 cm ×11, dąb A/B 2 cm ×7, dąb B/B 3 cm ×5, buk A/B 3 cm ×4, dąb A/B 4 cm ×2, dąb A/B 3.2 cm ×2, buk A/B 4 cm ×1, dąb B/B 4 cm ×1
Nowa czołówka 30: mediana przesunięcia 7.5 miejsc, max 26; 27 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1682_3 (113.2x49.5x2), 1736_1 (100x33x2)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 1682_3 | 1682 | 113.2x49.5x2 | dąb A/B | lity | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 2 | 17 | 1736_1 | 1736 | 100x33x2 | dąb A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 3 | 18 | 1736_3 | 1736 | 100x33x2 | dąb A/B | lity | 2026-10-09 | rozpoczete | rozpoczete |
| 4 | 9 | 1657_2 | 1657 | 121x30x3 | dąb B/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 5 | 8 | 1657_1 | 1657 | 103x30x3 | dąb B/B | lity | 2026-10-05 | blisko_terminu | blisko_terminu |
| 6 | 16 | 1710_1 | 1710 | 180x80x4 | buk A/B | mikrowczep | 2026-10-08 | g0 | — |
| 7 | 13 | 1702_1 | 1702 | 160x75x3 | buk A/B | lity | 2026-10-07 | g0 | — |
| 8 | 14 | 1722_1 | 1722 | 154x18x3 | buk A/B | lity | 2026-10-08 | g0 | — |
| 9 | 15 | 1722_2 | 1722 | 145x18x3 | buk A/B | lity | 2026-10-08 | g0 | — |
| 10 | 12 | 1692_1 | 1692 | 120x70x3 | buk A/B | lity | 2026-10-07 | g0 | — |
| 11 | 26 | 1744_1 | 1744 | 180x85x4 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 12 | 5 | 1604_1 | 1604 | 64x26x4 | dąb A/B | lity | 2026-10-16 | g0 | — |
| 13 | 6 | 1598_1 | 1598 | 190.5x52.2x3.2 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 14 | 7 | 1598_2 | 1598 | 53.2x52.2x3.2 | dąb A/B | mikrowczep | 2026-10-16 | g0 | — |
| 15 | 2 | 1513_1 | 1513 | 280x90x3 | dąb A/B | mikrowczep | 2026-10-13 | g0 | — |
| 16 | 30 | 1788_4 | 1788 | 170x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 17 | 27 | 1788_1 | 1788 | 155x15x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 18 | 25 | 1766_2 | 1766 | 150x40x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 19 | 33 | 1788_7 | 1788 | 130x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 20 | 31 | 1788_5 | 1788 | 120x30x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 21 | 29 | 1788_3 | 1788 | 120x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 22 | 32 | 1788_6 | 1788 | 120x25x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 23 | 1 | 1425_1 | 1425 | 108x36x3 | dąb A/B | mikrowczep | 2026-10-09 | g0 | — |
| 24 | 24 | 1766_1 | 1766 | 90x40x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |
| 25 | 28 | 1788_2 | 1788 | 70x30x3 | dąb A/B | mikrowczep | 2026-10-27 | g0 | — |
| 26 | 11 | 1704_1 | 1704 | 114x72x2 | dąb A/B | lity | 2026-10-07 | g0 | — |
| 27 | 22 | 1717_2 | 1717 | 105.5x18x2 | dąb A/B | lity | 2026-10-23 | g0 | — |
| 28 | 21 | 1717_1 | 1717 | 105.5x17.5x2 | dąb A/B | lity | 2026-10-23 | g0 | — |
| 29 | 3 | 1579_1 | 1579 | 57x25x2 | dąb A/B | lity | 2026-10-15 | g0 | — |
| 30 | 23 | 1740_1 | 1740 | 200x75x4 | dąb B/B | lity | 2026-10-26 | g0 | — |

#### Lakiernia (kafel = pozycja)

Pozycji: 40 z 24 zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): 2.0 / 6 (zamówień wielopozycyjnych: 8). Grup materiał+grubość: 10.
Największe grupy: dąb B/B 3 cm ×12, dąb A/B 3 cm ×10, dąb A/B 2 cm ×6, jesion A/B 2 cm ×3, dąb A/B 1.9 cm ×3, dąb A/B 4 cm ×2, dąb B/B 2.5 cm ×1, dąb B/B 1.5 cm ×1
Nowa czołówka 30: mediana przesunięcia 9.5 miejsc, max 30; 23 z nich jest też w dzisiejszej czołówce.

Na stole (K=2): 1709_1 (200x40x3), 1619_1 (160x50x3)

| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 31 | 1709_1 | 1709 | 200x40x3 | dąb B/B | lity | 2026-10-23 | g0 | — |
| 2 | 11 | 1619_1 | 1619 | 160x50x3 | dąb B/B | lity | 2026-10-19 | g0 | — |
| 3 | 9 | 1588_1 | 1588 | 150x70x3 | dąb B/B | lity | 2026-10-16 | g0 | — |
| 4 | 18 | 1671_3 | 1671 | 140x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 5 | 14 | 1655_1 | 1655 | 135x65x3 | dąb B/B | lity | 2026-10-20 | g0 | — |
| 6 | 19 | 1671_4 | 1671 | 120x40x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 7 | 24 | 1690_2 | 1690 | 105x29x3 | dąb B/B | lity | 2026-10-22 | g0 | — |
| 8 | 17 | 1671_2 | 1671 | 100x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 9 | 23 | 1690_1 | 1690 | 100x29x3 | dąb B/B | lity | 2026-10-22 | g0 | — |
| 10 | 16 | 1671_1 | 1671 | 70x70x3 | dąb B/B | lity | 2026-10-21 | g0 | — |
| 11 | 3 | 1538_1 | 1538 | 70x50x3 | dąb B/B | lity | 2026-10-14 | g0 | — |
| 12 | 10 | 1631_1 | 1631 | 59.5x16x3 | dąb B/B | lity | 2026-10-19 | g0 | — |
| 13 | 1 | 1481_1 | 1481 | 60x45x2.5 | dąb B/B | lity | 2026-10-12 | g0 | — |
| 14 | 38 | 1761_1 | 1761 | 46x35x1.5 | dąb B/B | lity | 2026-10-26 | g0 | — |
| 15 | 2 | 1476_1 | 1476 | 170x90x3 | jesion A/B | mikrowczep | 2026-10-12 | g0 | — |
| 16 | 7 | 1573_2 | 1573 | 80x61x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 17 | 6 | 1573_1 | 1573 | 50x60x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 18 | 8 | 1573_3 | 1573 | 40x46x2 | jesion A/B | mikrowczep | 2026-10-15 | g0 | — |
| 19 | 37 | 1729_1 | 1729 | 149x44x4 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 20 | 12 | 1622_1 | 1622 | 140x80x4 | dąb A/B | lity | 2026-10-19 | g0 | — |
| 21 | 21 | 1673_2 | 1673 | 271x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 22 | 4 | 1581_1 | 1581 | 266x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 23 | 5 | 1581_2 | 1581 | 234x70x3 | dąb A/B | mikrowczep | 2026-10-15 | g0 | — |
| 24 | 36 | 1728_1 | 1728 | 180x80x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 25 | 22 | 1673_3 | 1673 | 180x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 26 | 34 | 1711_1 | 1711 | 180x20x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 27 | 35 | 1711_2 | 1711 | 166x20x3 | dąb A/B | mikrowczep | 2026-10-23 | g0 | — |
| 28 | 20 | 1673_1 | 1673 | 161.5x60x3 | dąb A/B | mikrowczep | 2026-10-21 | g0 | — |
| 29 | 15 | 1672_1 | 1672 | 160x57x3 | dąb A/B | lity | 2026-10-21 | g0 | — |
| 30 | 39 | 1771_1 | 1771 | 80x30x3 | dąb A/B | mikrowczep | 2026-10-26 | g0 | — |

#### Pakowanie (kafel = zamówienie)

Zamówień czekających: 56, w tym kompletnych 54, niekompletnych 2 (czekają na pozycje z wcześniejszych stanowisk).
Nowa czołówka 30: mediana przesunięcia 8.0 miejsc, max 26; 23 z nich jest też w dzisiejszej czołówce.

Na stole (K=2, tylko kompletne): 1445, 1429

Niekompletne (do K): 1682 2/5, brakuje: 1682_2@czeka_na_sklejanie, 1682_3@czeka_na_krawedzie, 1682_4@czeka_na_sklejanie; 1736 1/3, brakuje: 1736_1@czeka_na_krawedzie, 1736_3@czeka_na_krawedzie

| # | Dziś # | Zam. | Kompletne | Na stan./aktywnych | Termin | Szczebel | Tagi |
|---|---|---|---|---|---|---|---|
| 1 | 3 | 1445 | tak | 3/3 | 2026-09-24 | g5 | po_terminie |
| 2 | 2 | 1429 | tak | 1/1 | 2026-09-24 | po_terminie | po_terminie |
| 3 | 9 | 1575 | tak | 1/1 | 2026-09-30 | po_terminie | po_terminie |
| 4 | 10 | 1585 | tak | 1/1 | 2026-09-30 | po_terminie | po_terminie |
| 5 | 11 | 1630 | tak | 2/2 | 2026-10-02 | po_terminie | po_terminie |
| 6 | 22 | 1682 | NIE | 2/5 | 2026-10-06 | rozpoczete | blisko_terminu, rozpoczete |
| 7 | 33 | 1736 | NIE | 1/3 | 2026-10-09 | rozpoczete | rozpoczete |
| 8 | 1 | 1313 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 9 | 20 | 1649 | tak | 2/2 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 10 | 18 | 1656 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 11 | 19 | 1658 | tak | 1/1 | 2026-10-05 | blisko_terminu | blisko_terminu |
| 12 | 4 | 1357 | tak | 1/1 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 13 | 21 | 1674 | tak | 1/1 | 2026-10-06 | blisko_terminu | blisko_terminu |
| 14 | 5 | 1394 | tak | 1/1 | 2026-10-07 | g0 | — |
| 15 | 25 | 1691 | tak | 1/1 | 2026-10-07 | g0 | — |
| 16 | 24 | 1693 | tak | 1/1 | 2026-10-07 | g0 | — |
| 17 | 23 | 1703 | tak | 1/1 | 2026-10-07 | g0 | — |
| 18 | 26 | 1705 | tak | 1/1 | 2026-10-07 | g0 | — |
| 19 | 6 | 1415 | tak | 1/1 | 2026-10-08 | g0 | — |
| 20 | 28 | 1707 | tak | 1/1 | 2026-10-08 | g0 | — |
| 21 | 29 | 1715 | tak | 1/1 | 2026-10-08 | g0 | — |
| 22 | 32 | 1716 | tak | 2/2 | 2026-10-08 | g0 | — |
| 23 | 30 | 1731 | tak | 1/1 | 2026-10-08 | g0 | — |
| 24 | 27 | 1733 | tak | 1/1 | 2026-10-08 | g0 | — |
| 25 | 31 | 1734 | tak | 3/3 | 2026-10-08 | g0 | — |
| 26 | 7 | 1436 | tak | 1/1 | 2026-10-09 | g0 | — |
| 27 | 38 | 1739 | tak | 1/1 | 2026-10-09 | g0 | — |
| 28 | 45 | 1741 | tak | 2/2 | 2026-10-09 | g0 | — |
| 29 | 34 | 1747 | tak | 4/4 | 2026-10-09 | g0 | — |
| 30 | 39 | 1749 | tak | 1/1 | 2026-10-09 | g0 | — |

### 3. Historia (ostatnie 60 dni, od 2026-08-05)

#### 3.1 Omijanie pilniejszych pozycji

Dla każdego zakończenia: ile pozycji innego zamówienia o wcześniejszym terminie czekało wtedy na tym stanowisku. Wejście na stanowisko = zakończenie poprzedniego (z kolumn `*_completed_at`); pozycje zakończone „w tej samej chwili” co wejście (auto-pominięcie) wyłączone.

| Stanowisko | Zakończeń | Z pominięciem pilniejszego | …o ≥3 dni | Mediana pominiętych | Mediana czekających |
|---|---|---|---|---|---|
| Wycinanie - mikro | 606 | 84% | 68% | 10.0 | 31.5 |
| Składanie - lite | 1207 | 88% | 77% | 6 | 36 |
| Sklejanie | 1737 | 96% | 88% | 12 | 53 |
| Formatowanie | 1743 | 96% | 89% | 18 | 51 |
| Krawędzie | 1539 | 78% | 69% | 4 | 15 |
| Lakiernia | 179 | 71% | 56% | 2 | 24 |
| Pakowanie | 1427 | 94% | 86% | 15 | 43 |

#### 3.2 Rozrzut pozycji jednego zamówienia przed stanowiskiem zamówieniowym

Czas między wejściem pierwszej i ostatniej pozycji zamówienia na stanowisko (zamówienia ≥2 pozycji, których ostatnia pozycja weszła w oknie). To jest dzisiejsza miara „ile Formatowanie/Pakowanie czeka na komplet”.

| Stanowisko | Zamówień | Mediana h | p90 h | >24 h | >72 h |
|---|---|---|---|---|---|
| Formatowanie | 287 | 0.4 | 70.8 | 20% | 10% |
| Pakowanie | 298 | 0.0 | 28.8 | 12% | 7% |

#### 3.3 Zdarzenia stanowiskowe (zmiany liczników)

| Stanowisko | Zdarzeń | Z tabletów | Dni z aktywnością | Średnio dziennie |
|---|---|---|---|---|
| Składanie - lite | 2788 | 2788 | 43 | 64.8 |
| Wycinanie - mikro | 1008 | 1008 | 29 | 34.8 |
| Krawędzie | 1595 | 209 | 45 | 35.4 |
| Formatowanie | 3279 | 3279 | 42 | 78.1 |
| Sklejanie | 3673 | 3673 | 42 | 87.5 |
| Pakowanie | 2764 | 2759 | 42 | 65.8 |
| Lakiernia | 283 | 250 | 25 | 11.3 |

### 4. Jak czytać

- Bez gwiazdek i tras nowa kolejka różni się od dzisiejszej głównie tagami terminowymi i grupowaniem po materiale; plik `--gwiazdki` pozwala zasymulować decyzje biura.
- Duży rozrzut pozycji zamówienia w nowej kolejce Sklejania przy małym rozrzucie historycznym oznacza, że grupowanie po materiale wydłuży czekanie Formatowania — wtedy tag „Rozpoczęte” musi stać wysoko albo trzeba ograniczyć grupowanie do bloków.
- Wysoki udział „z pominięciem pilniejszego” to miara dzisiejszego wybierania łatwych pozycji; po wdrożeniu stołu ta sama miara powinna spaść do odłożeń z powodem.

## Testy

`docker compose exec app pytest tests/test_symulacja_priorytetow.py -q` →

```
8 passed, 8 warnings in 0.23s
```

(ostrzeżenia to DeprecationWarning adaptera datetime w sqlite na Pythonie 3.12, bez znaczenia)

## Pliki

- Surowe dane: `2026-10-04-priorytety-produkcji-symulacja.json` (267 KB, w repo).

## Analiza wyniku (sesja planująca, 5.10)

Liczby z raportu podstawowego i z JSON-a (`kolejka_pelna`), warianty kolejności przeliczone na tych samych danych.
Produkcja nie ma jeszcze tras ani gwiazdek, więc drabina działa tu wyłącznie tagami; 210 z 246 zamówień siedzi na
szczeblu „bez gwiazdek” — to w tym szczeblu rozstrzyga się, czy grupowanie po materiale pomaga, czy szkodzi.

### A. Dzisiejsza hala (historia 60 dni)

- **Omijanie pilniejszych jest regułą, nie wyjątkiem.** 84–96 % zakończeń na każdym stanowisku nastąpiło, gdy na tym
  samym stanowisku czekała pozycja innego zamówienia o wcześniejszym terminie; w 68–89 % o co najmniej 3 dni
  wcześniejszym. Mediana pominiętych: 6–18 pozycji; mediana czekających w chwili zakończenia: 31–53 (Sklejanie 53,
  Formatowanie 51). Część tego to dzisiejszy algorytm (tydzień opłacenia, częstość gatunku — nie termin), ale skala
  pokazuje, że termin nie steruje dziś niczym.
- **Rozrzut pozycji zamówienia przed Formatowaniem:** mediana 0,4 h, p90 70,8 h; 20 % zamówień czeka na komplet
  ponad dobę, 10 % ponad 3 doby. Przed Pakowaniem: mediana 0 h, p90 28,8 h, 12 % ponad dobę. Czyli dziś większość
  zamówień schodzi razem, ale co piąte czeka na komplet ponad dobę — to jest poziom odniesienia dla obawy z 5.6 specu.
- **Zdarzenia liczników:** 380 dziennie na wszystkie stanowiska (Sklejanie 88, Formatowanie 78, Pakowanie 66,
  Składanie 65). Dla sygnałów Centrifugo to nic; ~1 sygnał na minutę w godzinach pracy.
- Zamówienia z pozycjami naraz na Wycinaniu i Składaniu: 3 na 76 — mieszana technologia prawie nie występuje.

### B. Nowa kolejka wg specu (A1: grupa = materiał → grubość ↓ → długość ↓) — co pokazały prawdziwe dane

- **Przezbrojenia spadają 2–3 razy.** Zmiany (materiał, grubość) między sąsiednimi pozycjami: Składanie 14 (dziś 44),
  Sklejanie 20 (dziś 39). Grupowanie robi to, po co jest.
- **Ale w szczeblu „bez gwiazdek” grubość i długość przebijają termin.** Składanie (149 pozycji, 59 zamówień): na
  miejscu 4 stoi 1836 z terminem 28.10 (dąb A/B 4 cm, 230 cm), a 1738 z terminem 9.10 na miejscach 20–22 i 1753
  (9.10) na 33. Sklejanie: 1750, 1751, 1768 z terminem 9.10 lądują na miejscach 85–101 ze 102, bo ich grupa (dąb B/B)
  ma 27 pozycji 3 cm przed ich 1,9 cm. Tag „Blisko terminu” z progiem 2 dni ich nie łapie — mają 5 dni.
- **Rozrzut pozycji jednego zamówienia w kolejce:** Składanie mediana 11 / p90 28 miejsc (dziś 2 / 8), Sklejanie 4 / 23
  (dziś 2 / 8). Przy ~20 zakończeniach dziennie na Składaniu i ~29 na Sklejaniu p90 to 1–1,5 dnia — porównywalnie
  z dzisiejszym p90 70 h przed Formatowaniem, ale mediana rośnie z „razem” do „pół dnia”.
- **Formatowanie:** 29 zamówień czeka, 23 kompletne, 6 niekompletnych (21 %). Brakujące pozycje tych sześciu siedzą
  na Sklejaniu na miejscach 2–19 (tag „Rozpoczęte” działa) — zostałyby sklejone w ciągu dnia. Pakowanie: 54 z 56
  kompletnych. Sekcja „Niekompletne” do K=2 wystarcza.
- **Koszt tagu „Rozpoczęte” nad „Blisko terminu”:** 1790 (termin 12.10, 1/11 na Formatowaniu) wciąga 10 pozycji na
  miejsca 5–15 Sklejania, przed 1647 z terminem 5.10 (blisko) i 1724 z terminem 8.10. Przy progu „blisko” 2 dni
  i tagu „Rozpoczęte” wyżej od „Blisko terminu” domykanie dużego zamówienia wygrywa z pilnym małym.

### C. Warianty na tych samych danych

| Wariant (szczebel „bez gwiazdek”) | Składanie: rozrzut med/p90 | pilne ≤7 dni: mediana/max miejsca | przezbrojeń | Sklejanie: rozrzut | pilne med/max | przezbrojeń |
|---|---|---|---|---|---|---|
| DZIŚ (`priority_rank`) | 2 / 8 | 3 / 4 | 44 | 2 / 8 | 13 / 23 | 39 |
| A1 spec, blisko 2 dni | 11 / 28 | 21 / 33 | 14 | 4 / 23 | 30 / 101 | 20 |
| A1 spec, **blisko 5 dni** | 11 / 28 | 3 / 4 | 16 | 4 / 22 | 22 / 32 | 25 |
| **A2**: grupa = (materiał, grubość) po najbliższym terminie → termin → długość ↓, blisko 5 dni | **3 / 15** | 3 / 4 | 16 | **4 / 13** | 22 / 32 | 25 |
| A2b: jak A2, ale długość ↓ przed terminem | 11 / 19 | 3 / 4 | 16 | 4 / 22 | 22 / 32 | 25 |
| A3: bloki po 5 zamówień, w bloku materiał | 2 / 10 | 3 / 4 | 45 | 3 / 5 | 22 / 32 | 45 |
| A0: bez grupowania (szczebel → termin) | 2 / 8 | 3 / 4 | 54 | 2 / 5 | 22 / 32 | 50 |

„pilne ≤7 dni” = pozycje zamówień z terminem do 7 dni kalendarzowych od dziś; w kolumnie ich mediana i najgorsze
miejsce w nowej kolejce. Na Sklejaniu mediana 22 w każdym wariancie z progiem 5 dni wynika z tagu „Rozpoczęte”
(1790 ×10 i inne rozpoczęte stoją wyżej).

### D. Wnioski i propozycje do specu

1. **Próg „Blisko terminu” 5 dni roboczych zamiast 2.** Przy 2 dniach zamówienia z terminem za 5 dni toną w szczeblu
   „bez gwiazdek” pod grubszymi deskami (Sklejanie: miejsce 101 ze 102). Przy 5 dniach wszystkie pilne są w czołówce,
   a przezbrojenia rosną tylko z 14→16 i 20→25. Parametr P-4 w specu.
2. **Grupa materiału = (gatunek, klasa, grubość), grupy po najbliższym terminie w grupie, w grupie termin przed
   długością (wariant A2).** Te same przezbrojenia co w specu, rozrzut pozycji zamówienia spada z p90 28→15 (Składanie)
   i 23→13 (Sklejanie), a z czołówki znikają zamówienia z terminem za 3 tygodnie. Koszt: w obrębie jednej grubości
   i materiału długość przestaje być pierwsza — operator dalej dostaje ten sam materiał i grubość pod rząd, ale deski
   w tej serii idą po terminie, nie od najdłuższej. Jeśli długość ↓ musi zostać pierwsza (A2b), rozrzut p90 wynosi
   19/22 — też lepiej niż A1, gorzej niż A2. Do decyzji Konrada; sekcja 3.2 specu.
3. **Bloki po N zamówień (A3) odrzucić:** przezbrojenia wracają do dzisiejszych 45 — tracimy całą korzyść grupowania.
   Skreślić z „na później” albo zostawić wyłącznie jako awaryjny parametr.
4. **„Blisko terminu” nad „Rozpoczęte” w domyślnej drabinie** (★★★★★, Po terminie, ★★★★, Blisko terminu, Rozpoczęte,
   ★★★, …): domykanie dużego zamówienia na 12.10 nie powinno wygrywać z małym na 5.10. Biuro i tak może to przestawić.
   Parametr P-8.
5. **Stół K=2 i sekcja „Niekompletne” do K** wystarczają: na Formatowaniu 6 z 29 niekompletnych, ich brakujące pozycje
   w czołówce Sklejania; na Pakowaniu 2 z 56. Parametry P-2 i P-9 bez zmian.
6. **Sygnały realtime:** ~380 zdarzeń dziennie — brak ryzyka po stronie brokera; odpytywanie awaryjne 30 s / 5 min
   zostaje (P-7).
7. **Po wdrożeniu mierzyć tym samym skryptem:** udział zakończeń „z pominięciem pilniejszego” (dziś 84–96 %) ma spaść
   do poziomu odłożeń z powodem; rozrzut przed Formatowaniem (dziś p90 70 h) nie może wzrosnąć. Oba liczniki są już
   w sekcji 3 raportu, więc porównanie po P3 to jedno uruchomienie.
8. Jedna pozycja w archiwalnym statusie `czeka_na_logistyke` — cron logistyki etapu 1 przeniesie ją do pakowania; dla
   priorytetów bez znaczenia.

### E. Decyzje Konrada (5.10) i co z nich wynika na tych danych

- **Próg „Blisko terminu”: 3 dni robocze**, konfigurowalny (termin zamówienia to dziś 10 dni roboczych; niedawno było 5).
  Przy progu 3 w migawce z niedzieli 4.10 zamówienia z terminem na piątek 9.10 (4 dni robocze) jeszcze nie mają tagu:
  na Składaniu 1753 ląduje na miejscu 29, na Sklejaniu 1750/1751/1768 na 52–80 ze 102. Tag złapie je we wtorek 6.10
  i wtedy wskoczą do czołówki — koszt to dzień opóźnienia wobec progu 5. Parametr zostaje w Konfiguracji do korekty
  bez wdrożenia.
- **W grupie termin przed długością** (wariant A2): przezbrojenia Składanie 14, Sklejanie 23 (dziś 44 / 39); rozrzut
  pozycji zamówienia med/p90 3/15 i 3/10 miejsc.
- **„Blisko terminu” nad „Rozpoczęte”** w domyślnej drabinie.
- Bloki po N zamówień — odrzucone.
- Spec zaktualizowany w sekcjach 2 (p. 14), 3.1, 3.2, 3.3, 4.3, 5.6, 8.6, 13, 14; skrypt symulacji liczy od tej wersji
  wariant A2 z progiem domyślnym 3 i nową kolejnością drabiny.
