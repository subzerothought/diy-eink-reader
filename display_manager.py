"""
display_manager.py - All EPD drawing logic.
Hardware: Waveshare/Seengreat 7.5" e-Paper (800x480)
"""

import os
import time
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger('display')

EPD_WIDTH  = 800
EPD_HEIGHT = 480

FONT_DIR     = "/usr/share/fonts/truetype/dejavu"
FONT_REGULAR = os.path.join(FONT_DIR, "DejaVuSans.ttf")
FONT_BOLD    = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FONT_MONO    = os.path.join(FONT_DIR, "DejaVuSansMono.ttf")


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


class DisplayManager:
    def __init__(self, config):
        self.config = config
        self.epd    = None
        self._init_epd()

    def _init_epd(self):
        try:
            from waveshare_epd import epd7in5_V2
            self.epd = epd7in5_V2.EPD()
            log.info("EPD driver loaded OK")
        except ImportError:
            log.warning("waveshare_epd not found -- running in HEADLESS/stub mode")
            self.epd = _StubEPD()

    def init(self):
        log.info("Initialising EPD...")
        self.epd.init()

    def clear(self):
        log.info("Clearing EPD...")
        self.epd.init()
        self.epd.Clear()
        self.epd.sleep()
        log.info("EPD cleared and sleeping")

    def sleep(self):
        log.info("EPD sleeping")
        self.epd.sleep()

    def _display(self, image, partial=False):
        log.info("EPD: waking driver...")
        self.epd.init()
        buf = self.epd.getbuffer(image)
        if partial and hasattr(self.epd, 'display_Partial'):
            log.info("EPD: partial refresh...")
            self.epd.display_Partial(buf, 0, 0, EPD_WIDTH, EPD_HEIGHT)
            log.info("EPD: partial frame written")
        else:
            self.epd.display(buf)
            log.info("EPD: frame written -- will sleep after idle")
        self._last_display = time.time()
        self._needs_sleep  = True

    def sleep_if_idle(self, idle_secs=30):
        if getattr(self, '_needs_sleep', False) and \
                (time.time() - getattr(self, '_last_display', 0)) > idle_secs:
            log.info("EPD: sleeping after idle")
            self.epd.sleep()
            self._needs_sleep = False

    def _blank_canvas(self):
        img  = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
        draw = ImageDraw.Draw(img)
        return img, draw

    def _draw_status_icons(self, draw, bat_pct, wifi_bars, y=6):
        bat_x  = EPD_WIDTH - 90
        _draw_battery(draw, bat_x, y, bat_pct)
        wifi_x = bat_x - 52
        _draw_wifi(draw, wifi_x, y, wifi_bars)

    def show_reader_page(self, lines, page_num, total_pages,
                         title, bat_pct, wifi_bars=None):
        margin    = self.config.get('margin_px', 20)
        font_size = self.config.get('font_size', 22)
        f_body    = _font(FONT_REGULAR, font_size)
        f_small   = _font(FONT_REGULAR, 16)
        f_title   = _font(FONT_BOLD,    18)

        img, draw = self._blank_canvas()

        draw.rectangle([0, 0, EPD_WIDTH, 32], fill=0)
        short_title = title[:70] + '...' if len(title) > 70 else title
        draw.text((margin, 7), short_title, font=f_title, fill=255)
        self._draw_status_icons(draw, bat_pct, wifi_bars, y=6)

        y      = 38
        line_h = int(font_size * self.config.get('line_spacing', 1.35))
        max_y  = EPD_HEIGHT - 30

        for line in lines:
            if y + line_h > max_y:
                break
            draw.text((margin, y), line, font=f_body, fill=0)
            y += line_h

        draw.line([0, EPD_HEIGHT - 26, EPD_WIDTH, EPD_HEIGHT - 26], fill=0, width=1)
        footer = "Page " + str(page_num + 1) + " / " + str(total_pages)
        draw.text((margin, EPD_HEIGHT - 22), footer, font=f_small, fill=0)
        ts = datetime.now().strftime("%H:%M")
        draw.text((EPD_WIDTH - 60, EPD_HEIGHT - 22), ts, font=f_small, fill=0)

        self._display(img, partial=True)
        log.info("Reader page %d/%d displayed", page_num + 1, total_pages)

    def show_weather(self, data, bat_pct, wifi_bars=None):
        if not data:
            self._show_message("No weather data.\nCheck settings at\nhttp://<pi-ip>:5000")
            return

        f_city   = _font(FONT_BOLD,    38)
        f_temp   = _font(FONT_BOLD,    88)
        f_desc   = _font(FONT_REGULAR, 24)
        f_detail = _font(FONT_REGULAR, 20)
        f_small  = _font(FONT_REGULAR, 16)
        f_fc_day = _font(FONT_BOLD,    18)
        f_fc_val = _font(FONT_REGULAR, 17)

        img, draw = self._blank_canvas()

        units = data.get('units', 'imperial')
        t_sym = 'F' if units == 'imperial' else 'C'
        w_sym = 'mph' if units == 'imperial' else 'm/s'

        LEFT = 16
        DIVX = 420

        draw.text((LEFT, 8),  data.get('city', 'Unknown'), font=f_city, fill=0)
        draw.text((LEFT, 54), data.get('description', '').capitalize(),
                  font=f_desc, fill=0)
        temp_str = str(round(data.get('temp', 0))) + ' ' + t_sym
        draw.text((LEFT, 84), temp_str, font=f_temp, fill=0)
        draw.text((LEFT, 196),
                  "Feels like " + str(round(data.get('feels_like', 0))) + ' ' + t_sym,
                  font=f_detail, fill=0)
        draw.text((LEFT, 224),
                  "Humidity:   " + str(data.get('humidity', 0)) + '%',
                  font=f_detail, fill=0)
        draw.text((LEFT, 252),
                  "Wind:       " + str(round(data.get('wind_speed', 0), 1)) + ' ' + w_sym,
                  font=f_detail, fill=0)

        draw.line([DIVX, 0, DIVX, EPD_HEIGHT - 30], fill=0, width=2)

        forecast = data.get('forecast', [])[:5]
        ROW_H    = (EPD_HEIGHT - 36) // max(len(forecast), 1)
        RX       = DIVX + 12

        for i, day in enumerate(forecast):
            ry = i * ROW_H
            if i > 0:
                draw.line([DIVX + 4, ry, EPD_WIDTH - 4, ry], fill=0, width=1)
            draw.text((RX, ry + 4),
                      day.get('dow', '?'), font=f_fc_day, fill=0)
            draw.text((RX + 60, ry + 6),
                      day.get('description', '')[:18], font=f_fc_val, fill=0)
            draw.text((RX,      ry + ROW_H - 24),
                      "H:" + str(round(day.get('temp_max', 0))) + t_sym,
                      font=f_fc_val, fill=0)
            draw.text((RX + 90, ry + ROW_H - 24),
                      "L:" + str(round(day.get('temp_min', 0))) + t_sym,
                      font=f_fc_val, fill=0)

        draw.line([0, EPD_HEIGHT - 30, EPD_WIDTH, EPD_HEIGHT - 30], fill=0, width=1)
        draw.text((LEFT, EPD_HEIGHT - 24),
                  "Updated: " + data.get('updated_at', ''), font=f_small, fill=0)
        _draw_battery(draw, EPD_WIDTH - 90,  EPD_HEIGHT - 26, bat_pct)
        _draw_wifi(draw,    EPD_WIDTH - 138, EPD_HEIGHT - 26, wifi_bars)

        self._display(img)
        log.info("Weather screen displayed")

    def _show_message(self, text):
        img, draw = self._blank_canvas()
        f = _font(FONT_REGULAR, 26)
        y = 150
        for line in text.split(chr(10)):
            draw.text((60, y), line, font=f, fill=0)
            y += 40
        self._display(img)

    def show_boot_screen(self):
        img, draw = self._blank_canvas()
        f_big   = _font(FONT_BOLD,    52)
        f_small = _font(FONT_REGULAR, 24)
        draw.text((180, 170), "DIY E-Reader",   font=f_big,   fill=0)
        draw.text((220, 238), "Starting up...", font=f_small, fill=0)
        draw.text((140, 290), "Web UI -> http://<pi-ip>:5000", font=f_small, fill=0)
        self._display(img)

    def show_library(self, books, selected, bat_pct, wifi_bars=None):
        f_title = _font(FONT_BOLD,    20)
        f_item  = _font(FONT_REGULAR, 22)
        f_sel   = _font(FONT_BOLD,    22)
        f_small = _font(FONT_REGULAR, 16)

        img, draw = self._blank_canvas()

        draw.rectangle([0, 0, EPD_WIDTH, 32], fill=0)
        draw.text((16, 7), "Library", font=f_title, fill=255)
        self._draw_status_icons(draw, bat_pct, wifi_bars, y=6)

        max_visible = 13
        start   = max(0, selected - max_visible // 2)
        visible = books[start:start + max_visible]

        y = 38
        for i, book in enumerate(visible):
            actual_i = start + i
            name = os.path.basename(book)
            name = name[:72] + '...' if len(name) > 72 else name
            if actual_i == selected:
                draw.rectangle([8, y - 1, EPD_WIDTH - 8, y + 26], fill=0)
                draw.text((18, y), "> " + name, font=f_sel,  fill=255)
            else:
                draw.text((18, y), "  " + name, font=f_item, fill=0)
            y += 30

        draw.line([0, EPD_HEIGHT - 24, EPD_WIDTH, EPD_HEIGHT - 24], fill=0)
        draw.text((16, EPD_HEIGHT - 20),
                  "BTN1=Up  BTN2=Down  BTN3=Open  BTN4=Back",
                  font=f_small, fill=0)
        self._display(img)


def _draw_battery(draw, x, y, pct):
    pct = max(0, min(100, pct if pct is not None else 0))
    W, H, nub = 36, 18, 3
    draw.rectangle([x, y, x + W, y + H], outline=0, width=2)
    draw.rectangle([x + W, y + 5, x + W + nub, y + H - 5], fill=0)
    fill_w = int((W - 4) * pct / 100)
    if fill_w > 0:
        draw.rectangle([x + 2, y + 2, x + 2 + fill_w, y + H - 2], fill=0)
    try:
        f = ImageFont.truetype(FONT_REGULAR, 12)
    except Exception:
        f = ImageFont.load_default()
    draw.text((x + W + nub + 3, y + 3), str(pct) + '%', font=f, fill=0)


def _draw_wifi(draw, x, y, bars):
    if bars is None:
        bars = 0
    BAR_W   = 5
    BAR_GAP = 2
    HEIGHTS = [4, 7, 11, 15]
    BASE_Y  = y + 16
    for i, h in enumerate(HEIGHTS):
        bx = x + i * (BAR_W + BAR_GAP)
        by = BASE_Y - h
        if i < bars:
            draw.rectangle([bx, by, bx + BAR_W, BASE_Y], fill=0)
        else:
            draw.rectangle([bx, by, bx + BAR_W, BASE_Y], outline=0, width=1)
    try:
        f = ImageFont.truetype(FONT_REGULAR, 11)
    except Exception:
        f = ImageFont.load_default()
    label = "WiFi" if bars > 0 else "No WiFi"
    draw.text((x, BASE_Y + 2), label, font=f, fill=0)


class _StubEPD:
    def init(self):  log.info("[STUB] EPD init")
    def Clear(self): log.info("[STUB] EPD clear")
    def sleep(self): log.info("[STUB] EPD sleep")
    def getbuffer(self, img):
        img.save("/tmp/ereader_last_frame.png")
        log.info("[STUB] Frame saved to /tmp/ereader_last_frame.png")
        return b''
    def display(self, buf): log.info("[STUB] EPD display")
    def display_Partial(self, buf, x0, y0, x1, y1):
        log.info("[STUB] EPD display_Partial")
