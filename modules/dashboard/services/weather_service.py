"""
Serwis do pobierania danych pogodowych
"""

import requests
from datetime import datetime

def get_weather_data():
    """
    Pobiera dane pogodowe dla Rzeszowa (domyślnie)
    
    Returns:
        dict: Dane pogodowe lub puste jeśli błąd
    """
    try:
        api_key = 'b51440a74a7cc3b6e342b57a9f9ff22e'
        city = 'Rzeszów'  # Domyślnie Rzeszów
        
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&units=metric&lang=pl&appid={api_key}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            weather_data = {
                'temperature': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'description': data['weather'][0]['description'],
                'city': data['name'],
                'humidity': data['main']['humidity'],
                'pressure': data['main']['pressure'],
                'wind_speed': data['wind']['speed'],
                'icon': data['weather'][0]['icon'],
                'sunrise': format_time(data['sys']['sunrise']),
                'sunset': format_time(data['sys']['sunset']),
                'success': True
            }
            
            return weather_data
            
        else:
            print(f"[WeatherService] API Error: {response.status_code}")
            return get_weather_fallback()
            
    except requests.exceptions.Timeout:
        print("[WeatherService] Timeout - fallback")
        return get_weather_fallback()
    except requests.exceptions.RequestException as e:
        print(f"[WeatherService] Request error: {e}")
        return get_weather_fallback()
    except Exception as e:
        print(f"[WeatherService] General error: {e}")
        return get_weather_fallback()

def format_time(unix_timestamp):
    """Formatuje unix timestamp do HH:MM"""
    try:
        date = datetime.fromtimestamp(unix_timestamp)
        return date.strftime('%H:%M')
    except:
        return '--:--'

def get_weather_fallback():
    """Zwraca domyślne dane pogodowe gdy API nie działa"""
    return {
        'temperature': '--',
        'feels_like': '--', 
        'description': 'Brak danych pogodowych',
        'city': 'Rzeszów',
        'humidity': '--',
        'pressure': '--',
        'wind_speed': '--',
        'icon': '01d',  # słoneczna ikona jako fallback
        'sunrise': '--:--',
        'sunset': '--:--',
        'success': False
    }