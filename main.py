#!/usr/bin/env python3
"""
DIY E-Reader - Main Entry Point
Raspberry Pi Zero W + Seengreat/Waveshare 7.5" e-Paper HAT (800x480)
"""

import sys
import os
import threading
import logging
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'waveshare_epd'))

from config import Config
from display_manager import DisplayManager
from book_reader import BookReader
from weather import WeatherManager
from battery import BatteryMonitor
from wifi_monitor import WiFiMonitor
from gpio_handler import GPIOHandler
from web_server import create_app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/home/pi/ereader/ereader.log'),
    ]
)
log = logging.getLogger('main')


def main():
    log.info("=== DIY E-Reader Starting ===")

    config  = Config()
    display = DisplayManager(config)
    battery = BatteryMonitor()
    wifi    = WiFiMonitor()
    reader  = BookReader(config)
    weather = WeatherManager(config)

    state = {
        'mode':          'weather',
        'display':       display,
        'reader':        reader,
        'weather':       weather,
        'battery':       battery,
        'wifi':          wifi,
        'config':        config,
        'lock':          threading.Lock(),
        'last_activity': time.time(),
        'weather_drawn': False,
        'reader_shown':  False,
    }

    gpio = GPIOHandler(state)
    gpio.start()

    flask_app = create_app(state)
    web_thread = threading.Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=5000,
                                     debug=False, use_reloader=False),
        daemon=True, name='WebServer'
    )
    web_thread.start()
    log.info("Web interface running on port 5000")

    display.clear()

    last_book = config.get('last_book', '')
    if last_book and os.path.exists(last_book):
        log.info("Restoring last book: %s", last_book)
        reader.load(last_book, background=True)
        state['mode'] = 'reader'
        state['reader_shown'] = False

    try:
        while True:
            idle_secs = time.time() - state['last_activity']
            timeout   = config.get('idle_timeout_minutes', 5) * 60
            mode      = state['mode']

            if mode == 'reader':
                if reader.is_loading():
                    state['last_activity'] = time.time()
                    state['reader_shown']  = False

                if not reader.is_loading() and reader.is_loaded():
                    if not state.get('reader_shown'):
                        bat  = battery.read_percent()
                        bars = wifi.read().get('bars')
                        with state['lock']:
                            display.show_reader_page(
                                reader.current_page_lines(),
                                reader.page_index,
                                reader.total_pages,
                                reader.title, bat, bars)
                        state['reader_shown'] = True

                if idle_secs >= timeout:
                    log.info("Idle timeout -- switching to weather")
                    state['mode']          = 'weather'
                    state['weather_drawn'] = False
                    state['reader_shown']  = False
                    _show_weather(state)

                time.sleep(2)

            elif mode == 'weather':
                refresh     = config.get('weather_refresh_minutes', 15) * 60
                was_updated = weather.last_fetch_time()
                weather.maybe_refresh(refresh)

                if not state.get('weather_drawn'):
                    _show_weather(state)
                    state['weather_drawn'] = True

                for _ in range(62):
                    if state['mode'] != 'weather':
                        break
                    time.sleep(1)

                if state['mode'] == 'weather':
                    if weather.last_fetch_time() != was_updated:
                        _show_weather(state)

            else:
                time.sleep(0.5)

            display.sleep_if_idle(30)

    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        gpio.cleanup()
        display.sleep()
        log.info("Goodbye.")


def _show_weather(state):
    bat  = state['battery'].read_percent()
    bars = state['wifi'].read().get('bars')
    with state['lock']:
        state['display'].show_weather(state['weather'].get_data(), bat, bars)


if __name__ == '__main__':
    main()
