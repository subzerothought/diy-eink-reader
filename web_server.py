"""
web_server.py - Flask web UI for the e-reader.
"""

import os
import time
import logging
import threading
from flask import (Flask, render_template_string, request, redirect,
                   url_for, flash, jsonify, send_from_directory)
from werkzeug.utils import secure_filename

log = logging.getLogger('web')

ALLOWED_EXT = {'txt', 'pdf', 'epub'}


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def create_app(state):
    app = Flask(__name__)
    app.secret_key = 'ereader-secret-2024'
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024

    config  = state['config']
    reader  = state['reader']
    weather = state['weather']
    battery = state['battery']
    display = state['display']

    def _library():
        from book_reader import scan_library
        return scan_library(config.get('library_path'))

    def _render(template, **kwargs):
        return render_template_string(
            BASE_HTML.replace('{% block content %}{% endblock %}', template),
            **kwargs)

    def _refresh_reader():
        state['mode'] = 'reader'
        state['last_activity'] = time.time()
        state['reader_shown'] = True
        bat  = battery.read_percent()
        bars = state['wifi'].read().get('bars') if 'wifi' in state else None
        with state['lock']:
            display.show_reader_page(
                reader.current_page_lines(),
                reader.page_index, reader.total_pages,
                reader.title, bat, bars)

    @app.route('/')
    def index():
        bat     = battery.read_percent()
        vol     = battery.read_voltage()
        w       = weather.get_data()
        wifi    = state['wifi'].read() if 'wifi' in state else {}
        loading = reader.is_loading()
        return _render(INDEX_HTML,
                       bat=bat, vol=vol, weather=w,
                       wifi_pct=wifi.get('percent'),
                       wifi_bars=wifi.get('bars', 0),
                       mode=state.get('mode', '?'),
                       book=reader.title or 'None',
                       page=reader.page_index + 1,
                       total=reader.total_pages,
                       loading=loading)

    @app.route('/library')
    def library():
        books    = _library()
        lib_path = config.get('library_path')
        sizes    = {}
        for b in books:
            try:
                sizes[b] = os.path.getsize(b)
            except Exception:
                sizes[b] = 0
        return _render(LIBRARY_HTML, books=books, lib_path=lib_path,
                       current=reader.file_path, sizes=sizes)

    @app.route('/library/open/<path:filename>')
    def open_book(filename):
        lib  = config.get('library_path')
        full = os.path.join(lib, os.path.basename(filename))
        if reader.load(full, background=True):
            state['mode']          = 'reader'
            state['reader_shown']  = False
            state['last_activity'] = time.time()
            bat  = battery.read_percent()
            bars = state['wifi'].read().get('bars') if 'wifi' in state else None
            with state['lock']:
                display.show_reader_page(
                    ["Loading...", "", "Please wait."],
                    0, 1, reader.title, bat, bars)
            flash('Opening: ' + reader.title, 'success')
            threading.Thread(
                target=_wait_and_show, args=(state,), daemon=True
            ).start()
        else:
            flash('Could not open file.', 'error')
        return redirect(url_for('library'))

    def _wait_and_show(s):
        for _ in range(120):
            if not s['reader'].is_loading():
                break
            time.sleep(1)
        bat  = s['battery'].read_percent()
        bars = s['wifi'].read().get('bars') if 'wifi' in s else None
        with s['lock']:
            s['display'].show_reader_page(
                s['reader'].current_page_lines(),
                s['reader'].page_index,
                s['reader'].total_pages,
                s['reader'].title, bat, bars)
        s['reader_shown'] = True

    @app.route('/library/delete/<path:filename>', methods=['POST'])
    def delete_book(filename):
        lib  = config.get('library_path')
        full = os.path.join(lib, os.path.basename(filename))
        try:
            os.remove(full)
            cache = full + '.txtcache'
            if os.path.exists(cache):
                os.remove(cache)
            flash('Deleted: ' + os.path.basename(filename), 'success')
        except Exception as e:
            flash('Error: ' + str(e), 'error')
        return redirect(url_for('library'))

    @app.route('/library/download/<path:filename>')
    def download_book(filename):
        lib = config.get('library_path')
        return send_from_directory(lib, os.path.basename(filename),
                                   as_attachment=True)

    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        if request.method == 'POST':
            files = request.files.getlist('files')
            saved, errors = 0, []
            lib = config.get('library_path')
            os.makedirs(lib, exist_ok=True)
            for f in files:
                if f and _allowed(f.filename):
                    name = secure_filename(f.filename)
                    dest = os.path.join(lib, name)
                    f.save(dest)
                    saved += 1
                    log.info("Uploaded: %s", dest)
                else:
                    errors.append(f.filename)
            if saved:
                flash(str(saved) + ' file(s) uploaded successfully.', 'success')
            if errors:
                flash('Rejected (not .txt/.pdf/.epub): ' + ', '.join(errors), 'error')
            return redirect(url_for('library'))
        return _render(UPLOAD_HTML)

    @app.route('/reader/next')
    def reader_next():
        if reader.is_loading():
            flash('Still loading, please wait.', 'error')
            return redirect(url_for('index'))
        if reader.next_page():
            _refresh_reader()
        else:
            flash('Already at last page.', 'error')
        return redirect(url_for('index'))

    @app.route('/reader/prev')
    def reader_prev():
        if reader.is_loading():
            flash('Still loading, please wait.', 'error')
            return redirect(url_for('index'))
        if reader.prev_page():
            _refresh_reader()
        else:
            flash('Already at first page.', 'error')
        return redirect(url_for('index'))

    @app.route('/reader/goto', methods=['POST'])
    def reader_goto():
        if reader.is_loading():
            flash('Still loading, please wait.', 'error')
            return redirect(url_for('index'))
        if not reader.is_loaded():
            flash('No book loaded.', 'error')
            return redirect(url_for('index'))
        try:
            n = int(request.form['page']) - 1
            if n < 0 or n >= reader.total_pages:
                flash('Page must be between 1 and ' + str(reader.total_pages), 'error')
                return redirect(url_for('index'))
            reader.goto_page(n)
            _refresh_reader()
        except ValueError:
            flash('Invalid page number.', 'error')
        return redirect(url_for('index'))

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            updates = {}
            try: updates['latitude']  = float(request.form['latitude'])
            except: pass
            try: updates['longitude'] = float(request.form['longitude'])
            except: pass
            updates['units'] = request.form.get('units', 'imperial')
            try: updates['idle_timeout_minutes']    = int(request.form['idle_timeout'])
            except: pass
            try: updates['weather_refresh_minutes'] = int(request.form['weather_refresh'])
            except: pass
            try:
                new_font = int(request.form['font_size'])
                if new_font != config.get('font_size'):
                    updates['font_size'] = new_font
                    if reader.is_loaded():
                        reader.load(reader.file_path, background=True)
            except: pass
            lib = request.form.get('library_path', '').strip()
            if lib:
                updates['library_path'] = lib
            config.update(updates)
            flash('Settings saved.', 'success')
            threading.Thread(target=weather.force_refresh, daemon=True).start()
            return redirect(url_for('settings'))
        return _render(SETTINGS_HTML, cfg=config.all())

    @app.route('/weather')
    def weather_page():
        w = weather.get_data()
        return _render(WEATHER_HTML, w=w)

    @app.route('/weather/refresh')
    def weather_refresh():
        threading.Thread(target=weather.force_refresh, daemon=True).start()
        flash('Weather refresh triggered.', 'success')
        return redirect(url_for('weather_page'))

    @app.route('/weather/show')
    def weather_show():
        state['mode'] = 'weather'
        state['weather_drawn'] = False
        bat  = battery.read_percent()
        bars = state['wifi'].read().get('bars') if 'wifi' in state else None
        with state['lock']:
            display.show_weather(weather.get_data(), bat, bars)
        flash('Weather shown on display.', 'success')
        return redirect(url_for('weather_page'))

    @app.route('/system')
    def system_page():
        log_tail = _tail_log(40)
        import shutil
        total, used, free = shutil.disk_usage('/home/pi/ereader')
        disk = {
            'total': total // (1024*1024*1024),
            'used':  used  // (1024*1024*1024),
            'free':  free  // (1024*1024*1024),
        }
        return _render(SYSTEM_HTML, log_tail=log_tail, disk=disk)

    @app.route('/system/reboot', methods=['POST'])
    def reboot():
        flash('Rebooting...', 'success')
        threading.Timer(2, lambda: os.system('sudo reboot')).start()
        return redirect(url_for('system_page'))

    @app.route('/system/shutdown', methods=['POST'])
    def shutdown():
        flash('Shutting down...', 'success')
        threading.Timer(2, lambda: os.system('sudo shutdown -h now')).start()
        return redirect(url_for('system_page'))

    @app.route('/system/clear_display', methods=['POST'])
    def clear_display():
        with state['lock']:
            display.clear()
        flash('Display cleared.', 'success')
        return redirect(url_for('system_page'))

    @app.route('/api/status')
    def api_status():
        wifi_data = state['wifi'].read() if 'wifi' in state else {}
        return jsonify({
            'mode':        state.get('mode'),
            'book':        reader.title,
            'page':        reader.page_index + 1,
            'total_pages': reader.total_pages,
            'loading':     reader.is_loading(),
            'battery_pct': battery.read_percent(),
            'battery_v':   battery.read_voltage(),
            'wifi_pct':    wifi_data.get('percent'),
            'wifi_bars':   wifi_data.get('bars'),
            'weather':     weather.get_data(),
        })

    return app


def _tail_log(n=40):
    path = '/home/pi/ereader/ereader.log'
    try:
        with open(path) as f:
            lines = f.readlines()
        return ''.join(lines[-n:])
    except Exception:
        return '(log not available)'


BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DIY E-Reader</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;min-height:100vh}
  nav{background:#16213e;padding:12px 20px;display:flex;gap:16px;align-items:center;
      border-bottom:2px solid #0f3460;flex-wrap:wrap}
  nav a{color:#e94560;text-decoration:none;font-weight:600;font-size:14px;
        padding:4px 10px;border-radius:4px;transition:.2s}
  nav a:hover{background:#e94560;color:#fff}
  nav .brand{color:#fff;font-size:18px;font-weight:700;margin-right:16px}
  .container{max-width:960px;margin:24px auto;padding:0 20px}
  h1,h2{color:#e94560;margin-bottom:16px}
  h3{color:#a8dadc;margin:12px 0 8px}
  .card{background:#16213e;border-radius:8px;padding:20px;margin-bottom:20px;
        border:1px solid #0f3460}
  .btn{display:inline-block;padding:8px 18px;border-radius:5px;border:none;
       cursor:pointer;font-size:14px;text-decoration:none;transition:.2s}
  .btn-primary{background:#e94560;color:#fff}
  .btn-primary:hover{background:#c73652}
  .btn-secondary{background:#0f3460;color:#a8dadc;border:1px solid #a8dadc}
  .btn-secondary:hover{background:#a8dadc;color:#0f3460}
  .btn-danger{background:#7f1d1d;color:#fca5a5}
  .btn-danger:hover{background:#991b1b}
  .btn-sm{padding:4px 10px;font-size:12px}
  table{width:100%;border-collapse:collapse}
  th{background:#0f3460;color:#a8dadc;padding:8px 12px;text-align:left}
  td{padding:8px 12px;border-bottom:1px solid #0f3460}
  tr:hover td{background:#0f346030}
  input,select{background:#0f3460;color:#e0e0e0;border:1px solid #a8dadc55;
               border-radius:4px;padding:7px 10px;width:100%;font-size:14px}
  input:focus,select:focus{outline:none;border-color:#e94560}
  label{display:block;margin-bottom:4px;color:#a8dadc;font-size:13px}
  .form-group{margin-bottom:14px}
  .flash{padding:10px 16px;border-radius:5px;margin-bottom:16px;font-size:14px}
  .flash-success{background:#14532d;color:#86efac;border:1px solid #16a34a}
  .flash-error{background:#7f1d1d;color:#fca5a5;border:1px solid #dc2626}
  pre{background:#000;color:#0f0;padding:14px;border-radius:6px;
      font-size:12px;overflow-x:auto;max-height:300px;overflow-y:auto}
  .stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
  .stat-box{background:#0f3460;border-radius:6px;padding:14px;text-align:center}
  .stat-val{font-size:28px;font-weight:700;color:#e94560}
  .stat-lbl{font-size:12px;color:#a8dadc;margin-top:4px}
  .tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;
       background:#0f3460;color:#a8dadc;margin-right:4px}
  .loading-badge{background:#b45309;color:#fef3c7;padding:2px 8px;
                 border-radius:3px;font-size:11px}
  .wifi-bars{display:inline-flex;align-items:flex-end;gap:2px;height:16px;margin-left:6px}
  .wifi-bars span{background:#a8dadc;border-radius:1px;display:inline-block;width:5px}
  .wifi-bars span.off{background:#0f3460;border:1px solid #a8dadc}
</style>
</head>
<body>
<nav>
  <span class="brand">E-Reader</span>
  <a href="/">Home</a>
  <a href="/library">Library</a>
  <a href="/upload">Upload</a>
  <a href="/weather">Weather</a>
  <a href="/settings">Settings</a>
  <a href="/system">System</a>
</nav>
<div class="container">
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}{% for cat,msg in messages %}
<div class="flash flash-{{ cat }}">{{ msg }}</div>
{% endfor %}{% endif %}{% endwith %}
{% block content %}{% endblock %}
</div>
</body></html>
"""

INDEX_HTML = """
<h1>Dashboard</h1>
<div class="stat-grid">
  <div class="stat-box">
    <div class="stat-val">{{ bat if bat is not none else '?' }}%</div>
    <div class="stat-lbl">Battery{% if vol %} ({{ vol }}V){% endif %}</div>
  </div>
  <div class="stat-box">
    <div class="stat-val" style="font-size:18px">
      {{ wifi_pct if wifi_pct is not none else '?' }}%
      <span class="wifi-bars">
        {% for i in range(4) %}
        <span style="height:{{ (i+1)*4 }}px"
              class="{{ '' if i < wifi_bars else 'off' }}"></span>
        {% endfor %}
      </span>
    </div>
    <div class="stat-lbl">WiFi Signal</div>
  </div>
  <div class="stat-box">
    <div class="stat-val">{{ mode|upper }}</div>
    <div class="stat-lbl">Current Mode</div>
  </div>
  <div class="stat-box">
    <div class="stat-val">{{ page }}/{{ total }}</div>
    <div class="stat-lbl">Page
      {% if loading %}<span class="loading-badge">Loading</span>{% endif %}
    </div>
  </div>
  <div class="stat-box">
    <div class="stat-val" style="font-size:16px">{{ book[:20] }}</div>
    <div class="stat-lbl">Open Book</div>
  </div>
</div>

<div class="card">
  <h2>Reader Control</h2>
  {% if loading %}
  <p style="color:#fef3c7;background:#b45309;padding:8px 12px;
            border-radius:4px;margin-bottom:12px">
    Book is loading - controls available shortly.
  </p>
  {% endif %}
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <a href="/reader/prev" class="btn btn-secondary">Prev Page</a>
    <a href="/reader/next" class="btn btn-secondary">Next Page</a>
    <form method="post" action="/reader/goto"
          style="display:flex;gap:8px;align-items:center">
      <input type="number" name="page" min="1"
             max="{{ total if total > 0 else 1 }}"
             value="{{ page }}" style="width:80px"
             {% if loading %}disabled{% endif %}>
      <button class="btn btn-primary" type="submit"
              {% if loading %}disabled{% endif %}>Go to Page</button>
    </form>
  </div>
</div>

<div class="card">
  <h2>Weather Snapshot</h2>
  {% if weather %}
  <p><b>{{ weather.city }}</b> - {{ weather.description }}<br>
     Temp: {{ weather.temp|round|int }} |
     Feels: {{ weather.feels_like|round|int }} |
     Humidity: {{ weather.humidity }}% |
     Wind: {{ weather.wind_speed }}<br>
     <small style="color:#a8dadc">Updated: {{ weather.updated_at }}</small>
  </p>
  {% else %}
  <p style="color:#a8dadc">No weather data - check Settings for coordinates.</p>
  {% endif %}
  <br>
  <a href="/weather/show" class="btn btn-secondary btn-sm">Show on Display</a>
  <a href="/weather/refresh" class="btn btn-secondary btn-sm">Refresh</a>
</div>
"""

LIBRARY_HTML = """
<h1>Library</h1>
<p style="color:#a8dadc;margin-bottom:12px">Path: <code>{{ lib_path }}</code></p>
<a href="/upload" class="btn btn-primary" style="margin-bottom:16px">+ Upload Books</a>
{% if books %}
<div class="card">
<table>
  <tr><th>Filename</th><th>Type</th><th>Size</th><th>Actions</th></tr>
  {% for b in books %}
  <tr {% if b == current %}style="background:#0f346060"{% endif %}>
    <td>
      {{ b.split('/')[-1] }}
      {% if b == current %}<span class="tag">OPEN</span>{% endif %}
    </td>
    <td style="font-size:12px;color:#a8dadc">
      {{ b.split('.')[-1].upper() }}
    </td>
    <td style="font-size:12px;color:#a8dadc;white-space:nowrap">
      {% set s = sizes[b] %}
      {% if s < 1024 %}{{ s }} B
      {% elif s < 1048576 %}{{ (s/1024)|round(1) }} KB
      {% else %}{{ (s/1048576)|round(1) }} MB{% endif %}
    </td>
    <td style="white-space:nowrap">
      <a href="/library/open/{{ b.split('/')[-1] }}"
         class="btn btn-primary btn-sm">Open</a>
      <a href="/library/download/{{ b.split('/')[-1] }}"
         class="btn btn-secondary btn-sm">Download</a>
      <form method="post" action="/library/delete/{{ b.split('/')[-1] }}"
            style="display:inline"
            onsubmit="return confirm('Delete this book?')">
        <button class="btn btn-danger btn-sm">Delete</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
</div>
{% else %}
<div class="card">
  <p style="color:#a8dadc">No books found. Upload some .txt, .pdf or .epub files!</p>
</div>
{% endif %}
"""

UPLOAD_HTML = """
<h1>Upload Books</h1>
<div class="card">
  <form method="post" enctype="multipart/form-data">
    <div class="form-group">
      <label>Select Files (.txt, .pdf or .epub - multiple allowed)</label>
      <input type="file" name="files" multiple accept=".txt,.pdf,.epub">
    </div>
    <button type="submit" class="btn btn-primary">Upload</button>
  </form>
</div>
<div class="card">
  <h3>Tips</h3>
  <ul style="color:#a8dadc;line-height:1.8;padding-left:20px">
    <li>TXT: plain text files load instantly</li>
    <li>PDF: text-based PDFs work best; scanned/image PDFs cannot be displayed</li>
    <li>EPUB: fully supported - text extracted and cached on first open</li>
    <li>First open of PDF/EPUB extracts text and caches it - subsequent opens are instant</li>
    <li>Max upload size: 64MB</li>
  </ul>
</div>
"""

SETTINGS_HTML = """
<h1>Settings</h1>
<form method="post">
<div class="card">
  <h2>Weather Location</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div class="form-group">
      <label>Latitude</label>
      <input type="number" step="0.0001" name="latitude"
             value="{{ cfg.latitude }}">
    </div>
    <div class="form-group">
      <label>Longitude</label>
      <input type="number" step="0.0001" name="longitude"
             value="{{ cfg.longitude }}">
    </div>
  </div>
  <div class="form-group">
    <label>Units</label>
    <select name="units">
      <option value="imperial"
        {% if cfg.units=='imperial' %}selected{% endif %}>Imperial (F, mph)</option>
      <option value="metric"
        {% if cfg.units=='metric' %}selected{% endif %}>Metric (C, m/s)</option>
    </select>
  </div>
  <p style="font-size:12px;color:#a8dadc">
    Find coordinates:
    <a href="https://www.latlong.net" target="_blank"
       style="color:#e94560">latlong.net</a>
  </p>
</div>
<div class="card">
  <h2>Display and Idle</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div class="form-group">
      <label>Idle Timeout (minutes before weather screen)</label>
      <input type="number" name="idle_timeout" min="1" max="120"
             value="{{ cfg.idle_timeout_minutes }}">
    </div>
    <div class="form-group">
      <label>Weather Refresh Interval (minutes)</label>
      <input type="number" name="weather_refresh" min="5" max="360"
             value="{{ cfg.weather_refresh_minutes }}">
    </div>
    <div class="form-group">
      <label>Font Size (px) - current: {{ cfg.font_size }}px</label>
      <input type="number" name="font_size" min="16" max="48"
             value="{{ cfg.font_size }}">
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
        <span style="color:#a8dadc;font-size:12px;align-self:center">
          Quick set:
        </span>
        {% for sz in [18, 20, 22, 24, 26, 28, 32] %}
        <button type="submit" name="font_size" value="{{ sz }}"
                class="btn btn-secondary btn-sm"
                {% if cfg.font_size == sz %}
                style="border-color:#e94560;color:#e94560"
                {% endif %}>{{ sz }}px</button>
        {% endfor %}
      </div>
    </div>
  </div>
</div>
<div class="card">
  <h2>Library</h2>
  <div class="form-group">
    <label>Library Path on Pi</label>
    <input type="text" name="library_path" value="{{ cfg.library_path }}">
  </div>
</div>
<button type="submit" class="btn btn-primary">Save Settings</button>
</form>
"""

WEATHER_HTML = """
<h1>Weather</h1>
<div style="margin-bottom:12px">
  <a href="/weather/refresh" class="btn btn-secondary">Refresh Now</a>
  <a href="/weather/show" class="btn btn-primary">Show on Display</a>
</div>
{% if w %}
<div class="card">
  <h2>{{ w.city }}</h2>
  <div class="stat-grid">
    <div class="stat-box">
      <div class="stat-val">{{ w.temp|round|int }}</div>
      <div class="stat-lbl">Temperature</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ w.feels_like|round|int }}</div>
      <div class="stat-lbl">Feels Like</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ w.humidity }}%</div>
      <div class="stat-lbl">Humidity</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ w.wind_speed }}</div>
      <div class="stat-lbl">Wind Speed</div>
    </div>
  </div>
  <p style="margin-top:12px;color:#a8dadc">
    {{ w.description }} - Updated: {{ w.updated_at }}
  </p>
</div>
<div class="card">
  <h3>5-Day Forecast</h3>
  <div class="stat-grid">
    {% for d in w.forecast %}
    <div class="stat-box">
      <div style="font-weight:700;color:#a8dadc">{{ d.dow }}</div>
      <div style="font-size:12px;color:#e0e0e0;margin:4px 0">
        {{ d.description }}
      </div>
      <div style="color:#e94560">H: {{ d.temp_max|round|int }}</div>
      <div style="color:#a8dadc">L: {{ d.temp_min|round|int }}</div>
    </div>
    {% endfor %}
  </div>
</div>
{% else %}
<div class="card">
  <p style="color:#a8dadc">No weather data yet. Set coordinates in
  <a href="/settings" style="color:#e94560">Settings</a> and click Refresh.</p>
</div>
{% endif %}
"""

SYSTEM_HTML = """
<h1>System</h1>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">
  <form method="post" action="/system/clear_display">
    <button class="btn btn-secondary">Clear Display</button>
  </form>
  <form method="post" action="/system/reboot"
        onsubmit="return confirm('Reboot the Pi?')">
    <button class="btn btn-secondary">Reboot</button>
  </form>
  <form method="post" action="/system/shutdown"
        onsubmit="return confirm('Shut down the Pi?')">
    <button class="btn btn-danger">Shutdown</button>
  </form>
</div>
<div class="card">
  <h3>Storage</h3>
  <p style="color:#a8dadc">
    Used: {{ disk.used }}GB / {{ disk.total }}GB
    ({{ disk.free }}GB free)
  </p>
</div>
<div class="card">
  <h3>Log (last 40 lines)</h3>
  <pre>{{ log_tail }}</pre>
</div>
<div class="card">
  <h3>API</h3>
  <p style="color:#a8dadc">JSON status:
    <a href="/api/status" style="color:#e94560">/api/status</a>
  </p>
</div>
"""
