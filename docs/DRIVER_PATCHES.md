# Waveshare EPD Driver Patches

The standard Waveshare `epdconfig.py` uses `gpiozero` with the `lgpio` backend
which conflicts with our button handling on Raspberry Pi OS Bookworm.
It also lacks the `PWR` pin required by the Seengreat driver board.

After copying the Waveshare drivers, replace `waveshare_epd/epdconfig.py`
with the patched version included in this repository.

## Key changes from stock epdconfig.py

1. **Switched from gpiozero to RPi.GPIO** — avoids lgpio conflicts
2. **Added PWR pin (GPIO 18)** — drives the Seengreat board's panel power
3. **CS pin handled by SPI hardware** — removed from GPIO setup to avoid conflicts
4. **module_exit() does not call GPIO.cleanup()** — GPIO lifetime managed by gpio_handler.py
5. **SPI open/close wrapped in try/except** — handles repeated init calls gracefully

## ReadBusy patch in epd7in5_V2.py

The stock `ReadBusy()` method loops forever if the BUSY pin is stuck LOW.
Add a timeout to prevent the application hanging on startup:

```python
def ReadBusy(self):
    logger.debug("e-Paper busy")
    timeout = 50
    while(epdconfig.digital_read(self.busy_pin) == 0):
        epdconfig.delay_ms(100)
        timeout -= 1
        if timeout <= 0:
            logger.warning("BUSY timeout - continuing anyway")
            break
    logger.debug("e-Paper busy release")
```

Also add a hard reset at the start of `init()` to clear the BUSY state on startup:

```python
def init(self):
    if (epdconfig.module_init() != 0):
        return -1
    # Hard reset to clear BUSY
    epdconfig.digital_write(self.reset_pin, 1)
    epdconfig.delay_ms(200)
    epdconfig.digital_write(self.reset_pin, 0)
    epdconfig.delay_ms(200)
    epdconfig.digital_write(self.reset_pin, 1)
    epdconfig.delay_ms(200)
    # ... rest of original init ...
```
