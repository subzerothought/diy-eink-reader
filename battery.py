"""
battery.py — Read state-of-charge from a MAX17043 fuel gauge.

Wiring (I2C):
  MAX17043  →  Pi Zero
  VCC       →  3.3 V  (Pin 1)
  GND       →  GND    (Pin 6)
  SDA       →  GPIO2  (Pin 3)
  SCL       →  GPIO3  (Pin 5)
  ALERT     →  Not connected (optional GPIO interrupt)

I2C must be enabled: sudo raspi-config → Interface Options → I2C → Enable
"""

import logging
import time

log = logging.getLogger('battery')

MAX17043_ADDR  = 0x36
REG_VCELL      = 0x02   # 12-bit ADC voltage (read two bytes)
REG_SOC        = 0x04   # State of charge (byte 0 = integer %, byte 1 = 1/256 %)
REG_MODE       = 0x06
REG_VERSION    = 0x08
REG_CONFIG     = 0x0C
REG_COMMAND    = 0xFE

QUICK_START    = 0x4000
RESET_CMD      = 0x5400


class BatteryMonitor:
    def __init__(self):
        self._bus    = None
        self._ok     = False
        self._cached = None
        self._last_t = 0
        self._init_i2c()

    def _init_i2c(self):
        try:
            import smbus2
            self._bus = smbus2.SMBus(1)
            # Read version register to confirm comms
            ver = self._read_word(REG_VERSION)
            log.info("MAX17043 detected, version reg=0x%04X", ver)
            self._ok = True
        except ImportError:
            log.warning("smbus2 not installed — battery monitor disabled")
        except Exception as e:
            log.warning("MAX17043 not found (%s) — battery monitor disabled", e)

    # ------------------------------------------------------------------  Public
    def read_percent(self):  # returns Optional[int]
        """Return SoC as integer 0-100, or None if unavailable."""
        # Cache for 30 s to avoid hammering I2C on every EPD refresh
        if time.time() - self._last_t < 30:
            return self._cached

        if not self._ok:
            return None

        try:
            word = self._read_word(REG_SOC)
            pct  = (word >> 8) & 0xFF          # integer part
            pct  = max(0, min(100, pct))
            self._cached = pct
            self._last_t = time.time()
            log.debug("Battery: %d%%", pct)
            return pct
        except Exception as e:
            log.warning("Battery read error: %s", e)
            return self._cached

    def read_voltage(self):  # returns Optional[float]
        """Return cell voltage in volts."""
        if not self._ok:
            return None
        try:
            word  = self._read_word(REG_VCELL)
            volts = (word >> 4) * 0.00125       # 1.25 mV per LSB
            return round(volts, 3)
        except Exception:
            return None

    def quick_start(self):
        """Trigger a MAX17043 QuickStart (re-calibrate)."""
        if self._ok:
            self._write_word(REG_MODE, QUICK_START)

    # ------------------------------------------------------------------  I2C helpers
    def _read_word(self, reg: int) -> int:
        data = self._bus.read_i2c_block_data(MAX17043_ADDR, reg, 2)
        return (data[0] << 8) | data[1]

    def _write_word(self, reg: int, value: int):
        hi = (value >> 8) & 0xFF
        lo = value & 0xFF
        self._bus.write_i2c_block_data(MAX17043_ADDR, reg, [hi, lo])
