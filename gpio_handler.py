"""
gpio_handler.py - Physical button handling via gpiozero.

Button wiring (BCM):
  BTN1 PREV/UP    -> GPIO 5  (Pin 29)
  BTN2 NEXT/DOWN  -> GPIO 6  (Pin 31)
  BTN3 SELECT     -> GPIO 13 (Pin 33)
  BTN4 MODE/BACK  -> GPIO 19 (Pin 35)
  GND (shared)    -> Pin 34
"""

import time
import threading
import logging

log = logging.getLogger('gpio')

BTN_PREV   = 5
BTN_NEXT   = 6
BTN_SELECT = 13
BTN_MODE   = 19

DEBOUNCE_S = 0.3


class GPIOHandler:
    def __init__(self, state):
        self.state           = state
        self._gpio_ok        = False
        self._lib_select_idx = 0
        self._buttons        = {}
        self._last_press     = {}

        try:
            from gpiozero import Button
            self._buttons = {
                BTN_PREV:   Button(BTN_PREV,   pull_up=True, bounce_time=0.05),
                BTN_NEXT:   Button(BTN_NEXT,   pull_up=True, bounce_time=0.05),
                BTN_SELECT: Button(BTN_SELECT, pull_up=True, bounce_time=0.05),
                BTN_MODE:   Button(BTN_MODE,   pull_up=True, bounce_time=0.05),
            }
            self._buttons[BTN_PREV].when_pressed   = lambda: self._handle(BTN_PREV)
            self._buttons[BTN_NEXT].when_pressed   = lambda: self._handle(BTN_NEXT)
            self._buttons[BTN_SELECT].when_pressed = lambda: self._handle(BTN_SELECT)
            self._buttons[BTN_MODE].when_pressed   = lambda: self._handle(BTN_MODE)
            self._gpio_ok = True
            log.info("GPIO buttons initialised OK (gpiozero)")
        except ImportError:
            log.warning("gpiozero not available -- buttons disabled")
        except Exception as e:
            log.warning("GPIO init failed (%s) -- buttons disabled", e)

    def start(self):
        if self._gpio_ok:
            log.info("GPIO button callbacks active")
        else:
            log.warning("GPIO not available -- running without buttons")

    def cleanup(self):
        for btn in self._buttons.values():
            try:
                btn.close()
            except Exception:
                pass

    def _handle(self, pin):
        now  = time.time()
        last = self._last_press.get(pin, 0)
        if now - last < DEBOUNCE_S:
            return
        self._last_press[pin] = now
        s    = self.state
        mode = s.get('mode', 'weather')
        log.info("Button press: GPIO %d  mode=%s", pin, mode)
        s['last_activity'] = time.time()
        threading.Thread(
            target=self._dispatch,
            args=(pin, mode, s),
            daemon=True
        ).start()

    def _dispatch(self, pin, mode, s):
        try:
            if mode == 'reader':
                self._handle_reader(pin, s)
            elif mode == 'library':
                self._handle_library(pin, s)
            else:
                if pin == BTN_MODE:
                    self._enter_library(s)
                else:
                    self._enter_reader(s)
        except Exception as e:
            log.exception("Button handler error: %s", e)

    def _handle_reader(self, pin, s):
        reader  = s['reader']
        display = s['display']
        bat     = s['battery'].read_percent()
        bars    = s['wifi'].read().get('bars') if 'wifi' in s else None
        if reader.is_loading():
            log.info("Still loading -- ignoring button press")
            return
        if pin == BTN_NEXT:
            if reader.next_page():
                with s['lock']:
                    display.show_reader_page(
                        reader.current_page_lines(),
                        reader.page_index,
                        reader.total_pages,
                        reader.title, bat, bars)
            else:
                log.info("Already at last page")
        elif pin == BTN_PREV:
            if reader.prev_page():
                with s['lock']:
                    display.show_reader_page(
                        reader.current_page_lines(),
                        reader.page_index,
                        reader.total_pages,
                        reader.title, bat, bars)
        elif pin == BTN_SELECT:
            log.info("Bookmark not yet implemented")
        elif pin == BTN_MODE:
            self._enter_library(s)

    def _handle_library(self, pin, s):
        from book_reader import scan_library
        books   = scan_library(s['config'].get('library_path'))
        display = s['display']
        bat     = s['battery'].read_percent()
        bars    = s['wifi'].read().get('bars') if 'wifi' in s else None
        if not books:
            return
        if pin == BTN_PREV:
            self._lib_select_idx = max(0, self._lib_select_idx - 1)
            with s['lock']:
                display.show_library(books, self._lib_select_idx, bat, bars)
        elif pin == BTN_NEXT:
            self._lib_select_idx = min(len(books) - 1, self._lib_select_idx + 1)
            with s['lock']:
                display.show_library(books, self._lib_select_idx, bat, bars)
        elif pin == BTN_SELECT:
            book = books[self._lib_select_idx]
            s['reader'].load(book, background=True)
            s['mode'] = 'reader'
            s['reader_shown'] = False
            bat = s['battery'].read_percent()
            with s['lock']:
                display.show_reader_page(
                    ["Loading...", "", "Please wait,",
                     "this may take a minute for large PDFs."],
                    0, 1, s['reader'].title, bat, bars)
            threading.Thread(
                target=self._wait_and_show, args=(s,), daemon=True
            ).start()
        elif pin == BTN_MODE:
            s['mode'] = 'weather'
            s['weather_drawn'] = False

    def _wait_and_show(self, s):
        reader  = s['reader']
        display = s['display']
        for _ in range(120):
            if not reader.is_loading():
                break
            time.sleep(1)
        bat  = s['battery'].read_percent()
        bars = s['wifi'].read().get('bars') if 'wifi' in s else None
        with s['lock']:
            display.show_reader_page(
                reader.current_page_lines(),
                reader.page_index,
                reader.total_pages,
                reader.title, bat, bars)
        s['reader_shown'] = True

    def _enter_library(self, s):
        from book_reader import scan_library
        books = scan_library(s['config'].get('library_path'))
        s['mode'] = 'library'
        self._lib_select_idx = 0
        bat  = s['battery'].read_percent()
        bars = s['wifi'].read().get('bars') if 'wifi' in s else None
        with s['lock']:
            s['display'].show_library(books, 0, bat, bars)

    def _enter_reader(self, s):
        if s['reader'].is_loaded():
            s['mode'] = 'reader'
            bat  = s['battery'].read_percent()
            bars = s['wifi'].read().get('bars') if 'wifi' in s else None
            with s['lock']:
                s['display'].show_reader_page(
                    s['reader'].current_page_lines(),
                    s['reader'].page_index,
                    s['reader'].total_pages,
                    s['reader'].title, bat, bars)
        else:
            self._enter_library(s)
