"""
wifi_monitor.py - Read WiFi signal strength on Raspberry Pi.
Tries multiple methods in order of reliability.
Returns signal as 0-100% and bar rating 0-4.
"""

import subprocess
import logging
import time
import re

log = logging.getLogger('wifi')


def _rssi_to_percent(rssi):
    rssi = max(-90, min(-30, rssi))
    return int((rssi + 90) * 100 / 60)


class WiFiMonitor:
    def __init__(self, interface='wlan0'):
        self.interface   = interface
        self._cached_pct = None
        self._cached_dbm = None
        self._last_read  = 0
        self._cache_secs = 30

    def read(self):
        now = time.time()
        if now - self._last_read < self._cache_secs and self._cached_pct is not None:
            return self._make_result(self._cached_pct, self._cached_dbm)
        pct, dbm = self._read_proc()
        if pct is None:
            pct, dbm = self._read_iw()
        if pct is None:
            pct, dbm = self._read_nmcli()
        self._cached_pct = pct
        self._cached_dbm = dbm
        self._last_read  = now
        return self._make_result(pct, dbm)

    def _make_result(self, pct, dbm):
        if pct is None:
            return {'percent': None, 'dbm': None, 'bars': 0}
        bars = 0 if pct < 20 else 1 if pct < 40 else 2 if pct < 60 else 3 if pct < 80 else 4
        return {'percent': pct, 'dbm': dbm, 'bars': bars}

    def _read_proc(self):
        try:
            with open('/proc/net/wireless') as f:
                for line in f:
                    if self.interface in line:
                        parts = line.split()
                        level = float(parts[3].rstrip('.'))
                        if level > 0:
                            level = level - 256
                        pct = _rssi_to_percent(int(level))
                        return pct, int(level)
        except Exception:
            pass
        return None, None

    def _read_iw(self):
        try:
            out = subprocess.check_output(
                ['iw', 'dev', self.interface, 'link'],
                stderr=subprocess.DEVNULL, timeout=3
            ).decode()
            match = re.search(r'signal:\s*(-\d+)\s*dBm', out)
            if match:
                dbm = int(match.group(1))
                return _rssi_to_percent(dbm), dbm
        except Exception:
            pass
        return None, None

    def _read_nmcli(self):
        try:
            out = subprocess.check_output(
                ['nmcli', '-t', '-f', 'SIGNAL,ACTIVE', 'dev', 'wifi'],
                stderr=subprocess.DEVNULL, timeout=3
            ).decode()
            for line in out.split('\n'):
                if line.endswith(':yes'):
                    pct = int(line.split(':')[0])
                    return pct, None
        except Exception:
            pass
        return None, None
