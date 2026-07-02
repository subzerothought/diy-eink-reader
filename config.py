"""
config.py — Persistent JSON configuration for the e-reader.
Settings are saved to /home/pi/ereader/config.json and survive reboots.
"""

import json
import os
import logging

log = logging.getLogger('config')

DEFAULT_CONFIG = {
    # Weather
    "latitude":  42.9634,
    "longitude": -85.6681,
    "units": "imperial",            # "imperial" | "metric"

    # Idle / display
    "idle_timeout_minutes":   5,
    "weather_refresh_minutes": 15,

    # Reader
    "font_size":      28,
    "line_spacing":   1.4,
    "margin_px":      40,

    # Library path (on the 16 GB SD card — see README for mount instructions)
    "library_path": "/home/pi/ereader/library",

    # Last open book / page (restored on boot)
    "last_book":  "",
    "last_page":  0,
}

CONFIG_PATH = "/home/pi/ereader/config.json"


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self._path = path
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    # ------------------------------------------------------------------
    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    saved = json.load(f)
                self._data.update(saved)
                log.info("Config loaded from %s", self._path)
            except Exception as e:
                log.warning("Could not load config (%s) — using defaults", e)
        else:
            log.info("No config file found — using defaults")
            self.save()

    def save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, 'w') as f:
            json.dump(self._data, f, indent=2)
        log.info("Config saved")

    # ------------------------------------------------------------------
    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def update(self, d: dict):
        self._data.update(d)
        self.save()

    def all(self) -> dict:
        return dict(self._data)
