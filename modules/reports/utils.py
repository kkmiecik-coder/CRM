# modules/reports/utils.py
"""
Narzędzia pomocnicze dla modułu Reports
Zawiera mapowanie kodów pocztowych na województwa
"""

import re
from typing import Optional
from modules.logging import get_structured_logger
# Inicjalizacja loggera
reports_logger = get_structured_logger('reports.routers')
reports_logger.info("✅ reports_logger zainicjowany poprawnie w utils.py")


class PostcodeToStateMapper:
    """
    Klasa do automatycznego przypisywania województw na podstawie kodów pocztowych
    
    Polska ma 16 województw i każde ma przypisane zakresy kodów pocztowych
    """
    
    # Mapowanie przedziałów kodów pocztowych (dwie pierwsze cyfry) na województwa.
    # Zakresy dobrane wg geografii okręgów pocztowych tak, żeby KAŻDY prefiks 00–99 należał
    # do dokładnie jednego województwa (bez luk, bez nakładania — pilnuje tego
    # tests/test_reports_mapa_kodow.py::test_zakresy_dwucyfrowe_pokrywaja_00_99_rozlacznie).
    # Prefiks dwucyfrowy to okręg pocztowy, który miejscami przecina granice województw —
    # te miejscowości są wyjątkami trzycyfrowymi w POSTCODE_OVERRIDES niżej. To jedna mapa dla
    # filtra województw Logistyki (modules/production/logistics/wojewodztwa.py), kolumny
    # „Region” w eksporcie Routimo i uzupełniania województwa w Analizie sprzedażowej.
    POSTCODE_RANGES = {
        # Dolnośląskie: 50-xxx do 59-xxx
        'dolnośląskie': [(50, 59)],

        # Kujawsko-Pomorskie: 85-xxx do 89-xxx (88 Inowrocław/Mogilno/Żnin, 89 Nakło/Szubin/
        # Sępólno/Tuchola — dawna luka)
        'kujawsko-pomorskie': [(85, 89)],

        # Lubelskie: 20-xxx do 24-xxx (24 Puławy, Kraśnik — dawna luka)
        'lubelskie': [(20, 24)],

        # Lubuskie: 65-xxx do 69-xxx (69 Słubice, Sulęcin — dawna luka)
        'lubuskie': [(65, 69)],

        # Łódzkie: 90-xxx do 99-xxx
        'łódzkie': [(90, 99)],

        # Małopolskie: 30-xxx do 34-xxx
        'małopolskie': [(30, 34)],

        # Mazowieckie: 00-xxx do 09-xxx + 26-xxx (Radom)
        'mazowieckie': [(0, 9), (26, 26)],

        # Opolskie: 45-xxx do 49-xxx
        'opolskie': [(45, 49)],

        # Podkarpackie: 35-xxx do 39-xxx
        'podkarpackie': [(35, 39)],

        # Podlaskie: 15-xxx do 19-xxx
        'podlaskie': [(15, 19)],

        # Pomorskie: 77-xxx (Bytów, Miastko, Człuchów) + 80-xxx do 84-xxx
        'pomorskie': [(77, 77), (80, 84)],

        # Śląskie: 40-xxx do 44-xxx
        'śląskie': [(40, 44)],

        # Świętokrzyskie: 25-xxx, 27-xxx do 29-xxx (27 Starachowice/Ostrowiec/Opatów/
        # Sandomierz — dawniej mazowieckie)
        'świętokrzyskie': [(25, 25), (27, 29)],

        # Warmińsko-Mazurskie: 10-xxx do 14-xxx
        'warmińsko-mazurskie': [(10, 14)],

        # Wielkopolskie: 60-xxx do 64-xxx
        'wielkopolskie': [(60, 64)],

        # Zachodniopomorskie: 70-xxx do 76-xxx + 78-xxx do 79-xxx (77 wydzielone do pomorskiego)
        'zachodniopomorskie': [(70, 76), (78, 79)]
    }

    # Wyjątki trzycyfrowe: miejscowości, których gmina/powiat leży w innym województwie niż
    # reszta dwucyfrowego okręgu pocztowego z POSTCODE_RANGES (np. Ryki i Dęblin mają prefiks
    # 08, jak Mazowieckie, ale administracyjnie to Lubelskie). Sprawdzane PRZED zakresem
    # dwucyfrowym w get_state_from_postcode, gdy kod ma co najmniej 3 cyfry. Nadal przybliżenie
    # dla pojedynczych miejscowości — nie każdy zakątek gminy musi się zgadzać.
    POSTCODE_OVERRIDES = {
        '085': 'lubelskie',            # Ryki, Dęblin
        '193': 'warmińsko-mazurskie',  # Ełk
        '194': 'warmińsko-mazurskie',  # Olecko
        '195': 'warmińsko-mazurskie',  # Gołdap
        '260': 'świętokrzyskie',       # okolice Kielc
        '261': 'świętokrzyskie',       # Skarżysko-Kamienna, Suchedniów
        '262': 'świętokrzyskie',       # Końskie, Stąporków
        '263': 'łódzkie',              # Opoczno, Drzewica
        '271': 'mazowieckie',          # Iłża
        '273': 'mazowieckie',          # Lipsko
        '343': 'śląskie',              # Żywiec
        '474': 'śląskie',              # Racibórz
        '672': 'dolnośląskie',         # Głogów
        '762': 'pomorskie',            # Słupsk, Ustka
        '774': 'wielkopolskie',        # Złotów
        '823': 'warmińsko-mazurskie',  # Elbląg
        '893': 'wielkopolskie',        # Wyrzysk
        '896': 'pomorskie',            # Chojnice, Czersk
        '963': 'mazowieckie',          # Żyrardów, Mszczonów
        '965': 'mazowieckie',          # Sochaczew
    }

    # Mapowanie nazw województw do form kanonicznych
    STATE_NORMALIZATION = {
        'dolnoslaskie': 'Dolnośląskie',
        'dolnośląskie': 'Dolnośląskie',
        'dolnoślaskie': 'Dolnośląskie',
        
        'kujawsko-pomorskie': 'Kujawsko-Pomorskie',
        'kujawsko pomorskie': 'Kujawsko-Pomorskie',
        'kujawskopomorskie': 'Kujawsko-Pomorskie',
        
        'lubelskie': 'Lubelskie',
        
        'lubuskie': 'Lubuskie',
        
        'łódzkie': 'Łódzkie',
        'lodzkie': 'Łódzkie',
        'łodzkie': 'Łódzkie',
        
        'małopolskie': 'Małopolskie',
        'malopolskie': 'Małopolskie',
        'małopolskie': 'Małopolskie',
        
        'mazowieckie': 'Mazowieckie',
        
        'opolskie': 'Opolskie',
        
        'podkarpackie': 'Podkarpackie',
        
        'podlaskie': 'Podlaskie',
        
        'pomorskie': 'Pomorskie',
        
        'śląskie': 'Śląskie',
        'slaskie': 'Śląskie',
        'ślaskie': 'Śląskie',
        
        'świętokrzyskie': 'Świętokrzyskie',
        'swietokrzyskie': 'Świętokrzyskie',
        'świetokrzyskie': 'Świętokrzyskie',
        
        'warmińsko-mazurskie': 'Warmińsko-Mazurskie',
        'warminsko-mazurskie': 'Warmińsko-Mazurskie',
        'warminsko mazurskie': 'Warmińsko-Mazurskie',
        'warmińsko mazurskie': 'Warmińsko-Mazurskie',
        
        'wielkopolskie': 'Wielkopolskie',
        
        'zachodniopomorskie': 'Zachodniopomorskie'
    }
    
    @classmethod
    def get_state_from_postcode(cls, postcode: str) -> Optional[str]:
        """
        Zwraca nazwę województwa na podstawie kodu pocztowego
        
        Args:
            postcode (str): Kod pocztowy w formacie XX-XXX lub XXXXX
            
        Returns:
            Optional[str]: Nazwa województwa lub None jeśli nie rozpoznano
        """
        if not postcode:
            return None

        # Wyczyść kod pocztowy - zostaw tylko cyfry
        clean_postcode = re.sub(r'[^0-9]', '', postcode.strip())

        # Wyjątek trzycyfrowy ma pierwszeństwo przed zakresem dwucyfrowym (np. 085 Ryki/Dęblin
        # to lubelskie, mimo że reszta prefiksu 08 to mazowieckie)
        if len(clean_postcode) >= 3:
            state = cls.POSTCODE_OVERRIDES.get(clean_postcode[:3])
            if state:
                return cls.STATE_NORMALIZATION.get(state, state.capitalize())

        if len(clean_postcode) < 2:
            return None

        # Pobierz pierwsze dwie cyfry jako integer
        try:
            prefix = int(clean_postcode[:2])
        except ValueError:
            return None

        # Znajdź województwo dla tego prefiksu
        for state, ranges in cls.POSTCODE_RANGES.items():
            for start, end in ranges:
                if start <= prefix <= end:
                    return cls.STATE_NORMALIZATION.get(state, state.capitalize())

        return None
    
    @classmethod
    def normalize_state_name(cls, state: str) -> Optional[str]:
        """
        Normalizuje nazwę województwa do formy kanonicznej
        
        Args:
            state (str): Nazwa województwa w dowolnej formie
            
        Returns:
            Optional[str]: Znormalizowana nazwa lub None
        """
        if not state:
            return None
        
        state_lower = state.strip().lower()
        return cls.STATE_NORMALIZATION.get(state_lower, state.strip().title())
    
    @classmethod
    def auto_fill_state(cls, postcode: str, current_state: str = None) -> str:
        """
        Automatycznie uzupełnia województwo na podstawie kodu pocztowego
        
        Args:
            postcode (str): Kod pocztowy
            current_state (str): Obecne województwo (jeśli jest)
            
        Returns:
            str: Województwo - automatycznie uzupełnione lub znormalizowane istniejące
        """
        # Jeśli mamy województwo, znormalizuj je
        if current_state and current_state.strip():
            normalized = cls.normalize_state_name(current_state)
            if normalized:
                return normalized
        
        # Jeśli nie ma województwa, spróbuj uzupełnić z kodu pocztowego
        if postcode:
            auto_state = cls.get_state_from_postcode(postcode)
            if auto_state:
                return auto_state
        
        # Jeśli nic nie zadziałało, zwróć obecne województwo lub pusty string
        return current_state or ''


if __name__ == "__main__":
    test_postcode_mapper()