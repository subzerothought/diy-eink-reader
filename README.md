# DIY E-Ink Reader

A full-featured DIY e-reader and weather display built with a Raspberry Pi Zero W and a 7.5" e-ink display. Supports TXT, PDF, and EPUB books, shows live weather with a 5-day forecast, and is fully controllable via physical buttons or a web interface accessible from any browser on your network.

![E-Reader Photo](docs/images/ereader.jpg)
*Add your own photo here!*

---

## Features

- 📖 **Read TXT, PDF and EPUB files** — text is cached on first open for instant subsequent loads
- 🌤️ **Weather idle screen** — shows current conditions and 5-day forecast when not reading
- 🔘 **4 physical buttons** — navigate pages, open library, switch modes
- 🌐 **Web interface** — upload books, adjust settings, control the reader from any browser
- 🔋 **Battery monitor** — MAX17043 fuel gauge with percentage and voltage display
- 📶 **WiFi signal indicator** — 4-bar signal strength shown on all screens
- 💤 **E-ink friendly** — display sleeps after idle, partial refresh for fast page turns
- 🔄 **Auto-start on boot** — runs as a systemd service
- 📍 **Page position memory** — resumes where you left off across reboots

---

## Hardware

### Parts List

| Part | Notes |
|------|-------|
| Raspberry Pi Zero W | Single-core 1GHz, 512MB RAM, built-in WiFi |
| Xicoolee 7.5" e-Paper Display (800×480) | Part no. 075BN-T7-D2, black/white |
| Seengreat Universal e-Paper Driver Board Rev 1.2 | Connects display to Pi GPIO header |
| MAX17043 LiPo Fuel Gauge Module | I2C battery monitor |
| LiPo Battery 1500mAh | 3.7V single cell |
| HW-373 (or similar) LiPo Charging Board | Micro USB charging, 5V output |
| 4× Momentary Tactile Push Buttons | Standard 4-leg 6×6mm tactile switches |
| On/Off Switch | Between LiPo positive and charger input |
| 16GB+ MicroSD Card | 32GB recommended |
| Micro USB cable | For power/charging |

### Driver Board Switch Settings

The Seengreat driver board has two DIP switches:

| Switch | Setting | Description |
|--------|---------|-------------|
| Interface | 4-line | Standard SPI mode (required) |
| RESE | B (3R) | Correct resistance for 7.5" panel |

---

## Wiring

### EPD Display (SPI)

| EPD / Driver Board Pin | Pi Zero GPIO | Pi Zero Pin |
|------------------------|--------------|-------------|
| VCC | 3.3V | Pin 1 |
| GND | GND | Pin 6 |
| DIN (MOSI) | GPIO 10 | Pin 19 |
| CLK (SCLK) | GPIO 11 | Pin 23 |
| CS (CE0) | GPIO 8 | Pin 24 |
| DC | GPIO 25 | Pin 22 |
| RST | GPIO 17 | Pin 11 |
| BUSY | GPIO 24 | Pin 18 |
| PWR | GPIO 18 | Pin 12 |

> **Note:** The PWR pin is specific to the Seengreat driver board and must be driven HIGH to power the panel. Standard Waveshare HATs may not require this pin.

> **Note:** The FPC ribbon cable from the display to the adapter board inserts **upside down** relative to the other connectors on the board.

### MAX17043 Battery Monitor (I2C)

| MAX17043 Pin | Pi Zero GPIO | Pi Zero Pin |
|--------------|--------------|-------------|
| VCC | 3.3V | Pin 1 |
| GND | GND | Pin 6 |
| SDA | GPIO 2 | Pin 3 |
| SCL | GPIO 3 | Pin 5 |

> Connect CELL+ and CELL- directly to the LiPo battery terminals.

### Push Buttons

| Button | Function | Pi Zero GPIO | Pi Zero Pin |
|--------|----------|--------------|-------------|
| BTN1 | Previous Page / Scroll Up | GPIO 5 | Pin 29 |
| BTN2 | Next Page / Scroll Down | GPIO 6 | Pin 31 |
| BTN3 | Select / Open | GPIO 13 | Pin 33 |
| BTN4 | Mode / Back | GPIO 19 | Pin 35 |
| GND | Shared ground | GND | Pin 34 |

> Each button: one leg to GPIO pin, other leg to GND. Internal pull-ups are enabled in software — no external resistors needed.
>
> For standard 4-leg tactile buttons: connect legs on **opposite sides** of the button, not the same side.

---

## Software Setup

### 1. Flash Raspberry Pi OS Lite (32-bit)

Use Raspberry Pi Imager. In Advanced Options:
- Hostname: `ereader`
- Enable SSH
- Username: your choice
- Configure WiFi

### 2. Enable SPI and I2C

```bash
sudo raspi-config
# Interface Options → SPI → Enable
# Interface Options → I2C → Enable
# Finish → Reboot
```

### 3. Install System Dependencies

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-pip python3-pil python3-numpy \
    libopenjp2-7 libtiff6 fonts-dejavu git i2c-tools \
    libxslt1-dev libxml2-dev
```

### 4. Clone This Repository

```bash
cd /home/pi
git clone https://github.com/subzerothought/diy-eink-reader.git ereader
cd ereader
```

### 5. Install Waveshare EPD Driver

```bash
cd /home/pi
git clone --depth 1 https://github.com/waveshare/e-Paper.git
mkdir -p /home/pi/ereader/waveshare_epd
cp e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd/* \
   /home/pi/ereader/waveshare_epd/
```

Then apply the required patches to `waveshare_epd/epdconfig.py` — see [DRIVER_PATCHES.md](docs/DRIVER_PATCHES.md).

### 6. Install Python Dependencies

```bash
pip3 install --break-system-packages \
    flask werkzeug \
    smbus2 \
    pypdf \
    pdfminer.six \
    ebooklib \
    beautifulsoup4 \
    lxml \
    Pillow
```

### 7. Create Library Directory

```bash
mkdir -p /home/pi/ereader/library
```

### 8. Install systemd Service

```bash
# Edit ereader.service and update User= to match your username
sudo cp ereader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ereader
sudo systemctl start ereader
```

### 9. Access the Web Interface

Open a browser on the same network and navigate to:
```
http://ereader.local:5000
```
or use the Pi's IP address directly.

---

## Button Operation

| Button | Reader Mode | Library Mode | Weather Mode |
|--------|-------------|--------------|--------------|
| BTN1 | Previous Page | Scroll Up | Wake → Reader |
| BTN2 | Next Page | Scroll Down | Wake → Reader |
| BTN3 | (Bookmark — future) | Open Selected Book | Wake → Reader |
| BTN4 | Back to Library | Back to Weather | Open Library |

---

## Web Interface

| Page | Features |
|------|---------|
| **Home** | Battery %, WiFi signal, mode, page position, reader remote control |
| **Library** | Browse, open, delete, download books |
| **Upload** | Upload .txt, .pdf, or .epub files |
| **Weather** | Current conditions, 5-day forecast, force refresh |
| **Settings** | GPS coordinates, units, idle timeout, weather refresh rate, font size |
| **System** | Reboot, shutdown, clear display, disk usage, live log |

A JSON API is also available at `/api/status`.

---

## Weather

Uses [Open-Meteo](https://open-meteo.com) — completely free, no API key required.
City name is resolved via OpenStreetMap Nominatim reverse geocoding.

Set your coordinates in **Settings → Weather Location**.
Find coordinates at [latlong.net](https://www.latlong.net).

---

## Project Structure

```
/home/pi/ereader/
├── main.py               ← Entry point and main loop
├── config.py             ← Persistent JSON settings
├── display_manager.py    ← EPD drawing (reader, weather, library)
├── book_reader.py        ← TXT/PDF/EPUB parser and paginator
├── weather.py            ← Open-Meteo weather client
├── battery.py            ← MAX17043 I2C fuel gauge driver
├── wifi_monitor.py       ← WiFi signal strength reader
├── gpio_handler.py       ← Physical button handler (gpiozero)
├── web_server.py         ← Flask web UI
├── ereader.service       ← systemd unit file
├── waveshare_epd/        ← Waveshare EPD drivers (patched)
│   ├── epd7in5_V2.py
│   └── epdconfig.py
└── library/              ← Your books go here
```

---

## Troubleshooting

**Display shows nothing:**
- Check SPI is enabled: `ls /dev/spidev*` should show `spidev0.0`
- Verify driver board switch settings (4-line SPI, RESE=B)
- Check FPC ribbon cable orientation — inserts upside down on this board
- Check PWR pin wiring (GPIO 18)

**Buttons not responding:**
- Verify 4-leg button wiring — connect opposite legs, not same-side legs
- Check `sudo systemctl status ereader` for GPIO errors
- Run `python3 -c "from gpiozero import Button; b=Button(5); print(b.is_pressed)"` to test

**Battery showing N/A:**
- Run `i2cdetect -y 1` — should show device at 0x36
- Check I2C is enabled: `sudo raspi-config`
- Verify SDA/SCL wiring

**PDF loads slowly:**
- First load extracts and caches text — this takes 60-90 seconds for large PDFs
- Subsequent opens use the cache and load in seconds
- Cache files are stored as `filename.pdf.txtcache` next to the PDF

**Web UI not reachable:**
- Try `http://<pi-ip-address>:5000` if mDNS (.local) doesn't resolve
- Check `sudo systemctl status ereader`

---

## Known Limitations

- **PDF graphics** — pdfminer and pypdf extract text only; diagrams and images are skipped
- **E-ink flash** — full refresh causes a black/white flash; this is normal for e-paper displays
- **Partial refresh ghosting** — after many partial refreshes, faint shadows may appear; a full refresh clears these

---

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

## Author

JimH — [@subzerothought](https://github.com/subzerothought)

*Built with a lot of help from Claude (Anthropic) — an AI pair programmer that turned out to be surprisingly good at debugging e-ink display driver issues at 2am.*
