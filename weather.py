"""
weather.py — Download weather data from Open-Meteo (free, no API key).

Current conditions + 5-day forecast.
Falls back to cached data if the network is unavailable.
"""

import json
import os
import time
import logging
import threading
from datetime import datetime, timedelta

log = logging.getLogger('weather')

CACHE_PATH = "/home/pi/ereader/weather_cache.json"

# Open-Meteo WMO weather interpretation codes → short description
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Heavy showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm",
}

DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class WeatherManager:
    def __init__(self, config):
        self.config      = config
        self._data       = {}
        self._last_fetch = 0
        self._lock       = threading.Lock()
        self._load_cache()

    # ------------------------------------------------------------------  Public
    def get_data(self) -> dict:
        with self._lock:
            return dict(self._data)

    def maybe_refresh(self, interval_secs: int = 900):
        """Fetch if data is older than interval_secs."""
        if time.time() - self._last_fetch >= interval_secs:
            threading.Thread(target=self._fetch, daemon=True).start()

    def force_refresh(self):
        self._fetch()

    def last_fetch_time(self) -> float:
        return self._last_fetch

    # ------------------------------------------------------------------  Fetch
    def _fetch(self):
        lat  = self.config.get('latitude',  42.9634)
        lon  = self.config.get('longitude', -85.6681)
        units = self.config.get('units', 'imperial')

        wind_unit  = 'mph'          if units == 'imperial' else 'kmh'
        temp_unit  = 'fahrenheit'   if units == 'imperial' else 'celsius'

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
            f"wind_speed_10m,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min,weather_code"
            f"&wind_speed_unit={wind_unit}"
            f"&temperature_unit={temp_unit}"
            f"&timezone=auto"
            f"&forecast_days=6"
        )

        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = json.loads(resp.read())

            cur = raw['current']
            daily = raw['daily']

            # Reverse-geocode city name (Open-Meteo doesn't provide one)
            city = self._reverse_geocode(lat, lon)

            # Build forecast list (skip today = index 0)
            forecast = []
            for i in range(1, min(6, len(daily['time']))):
                dt  = datetime.strptime(daily['time'][i], "%Y-%m-%d")
                forecast.append({
                    'dow':         DAYS_OF_WEEK[dt.isoweekday() % 7],
                    'description': WMO_CODES.get(daily['weather_code'][i], 'Unknown'),
                    'temp_max':    daily['temperature_2m_max'][i],
                    'temp_min':    daily['temperature_2m_min'][i],
                })

            data = {
                'city':        city,
                'temp':        cur['temperature_2m'],
                'feels_like':  cur['apparent_temperature'],
                'humidity':    cur['relative_humidity_2m'],
                'wind_speed':  cur['wind_speed_10m'],
                'description': WMO_CODES.get(cur['weather_code'], 'Unknown'),
                'forecast':    forecast,
                'units':       units,
                'updated_at':  datetime.now().strftime("%b %d  %H:%M"),
            }

            with self._lock:
                self._data       = data
                self._last_fetch = time.time()

            self._save_cache(data)
            log.info("Weather updated for %.4f, %.4f", lat, lon)

        except Exception as e:
            log.warning("Weather fetch failed: %s", e)

    @staticmethod
    def _reverse_geocode(lat: float, lon: float) -> str:
        """Best-effort city name via Nominatim (OSM). Falls back to coords."""
        try:
            import urllib.request
            url = (f"https://nominatim.openstreetmap.org/reverse"
                   f"?lat={lat}&lon={lon}&format=json")
            req = urllib.request.Request(url,
                    headers={'User-Agent': 'DIY-EReader/1.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                j = json.loads(resp.read())
            addr = j.get('address', {})
            return (addr.get('city')
                    or addr.get('town')
                    or addr.get('village')
                    or addr.get('county')
                    or f"{lat:.2f}, {lon:.2f}")
        except Exception:
            return f"{lat:.2f}, {lon:.2f}"

    # ------------------------------------------------------------------  Cache
    def _save_cache(self, data: dict):
        try:
            with open(CACHE_PATH, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            log.warning("Could not save weather cache: %s", e)

    def _load_cache(self):
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH) as f:
                    self._data = json.load(f)
                log.info("Loaded cached weather data")
            except Exception:
                pass
