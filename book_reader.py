"""
book_reader.py - Parse .txt, .pdf and .epub files into display-ready pages.
"""

import os
import logging
import threading
from PIL import ImageFont

log = logging.getLogger('reader')

FONT_DIR     = "/usr/share/fonts/truetype/dejavu"
FONT_REGULAR = os.path.join(FONT_DIR, "DejaVuSans.ttf")

EPD_WIDTH  = 800
EPD_HEIGHT = 480


def _font(size):
    try:
        return ImageFont.truetype(FONT_REGULAR, size)
    except Exception:
        return ImageFont.load_default()


class BookReader:
    def __init__(self, config):
        self.config      = config
        self.title       = ""
        self.pages       = []
        self.page_index  = 0
        self.file_path   = ""
        self.loading     = False
        self._load_error = ""

    def load(self, path, background=True):
        ext = os.path.splitext(path)[1].lower()
        if ext not in ('.txt', '.pdf', '.epub'):
            log.error("Unsupported format: %s", ext)
            return False
        if not os.path.exists(path):
            log.error("File not found: %s", path)
            return False
        self.title       = os.path.splitext(os.path.basename(path))[0]
        self.file_path   = path
        self.pages       = []
        self.page_index  = 0
        self.loading     = True
        self._load_error = ""
        if background:
            t = threading.Thread(target=self._load_worker,
                                 args=(path, ext), daemon=True, name='BookLoad')
            t.start()
        else:
            self._load_worker(path, ext)
        return True

    def _load_worker(self, path, ext):
        try:
            if ext == '.txt':
                raw = self._read_txt(path)
            elif ext == '.pdf':
                raw = self._read_pdf(path)
            elif ext == '.epub':
                raw = self._read_epub(path)
            else:
                raw = "[Unsupported format]"
            pages = self._paginate(raw)
            start_page = 0
            if self.config.get('last_book') == path:
                saved = self.config.get('last_page', 0)
                start_page = min(saved, len(pages) - 1)
            self.pages      = pages
            self.page_index = start_page
            self.config.set('last_book', path)
            self.config.set('last_page', start_page)
            log.info("Loaded '%s' (%d pages)", self.title, len(pages))
        except Exception as e:
            self._load_error = str(e)
            log.exception("Failed to load %s: %s", path, e)
        finally:
            self.loading = False

    def current_page_lines(self):
        if self.loading:
            return ["Loading...", "", "Please wait."]
        if self._load_error:
            return ["Error: " + self._load_error]
        if not self.pages:
            return ["No book loaded."]
        return self.pages[self.page_index]

    def next_page(self):
        if self.loading or not self.pages:
            return False
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
            self._save_position()
            return True
        return False

    def prev_page(self):
        if self.loading or not self.pages:
            return False
        if self.page_index > 0:
            self.page_index -= 1
            self._save_position()
            return True
        return False

    def goto_page(self, n):
        if not self.loading and self.pages:
            self.page_index = max(0, min(n, len(self.pages) - 1))
            self._save_position()

    @property
    def total_pages(self):
        return len(self.pages)

    def is_loaded(self):
        return bool(self.pages) and not self.loading

    def is_loading(self):
        return self.loading

    @staticmethod
    def _read_txt(path):
        for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
            try:
                with open(path, encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError("Cannot decode " + path)

    @staticmethod
    def _read_pdf(path):
        cache_path = path + '.txtcache'
        if os.path.exists(cache_path) and \
                os.path.getmtime(cache_path) >= os.path.getmtime(path):
            with open(cache_path, encoding='utf-8') as f:
                cached = f.read()
            if cached.strip():
                log.info("Loaded PDF from cache: %s", cache_path)
                return cached
        try:
            import pypdf
            import logging as _logging
            _logging.getLogger('pypdf').setLevel(_logging.ERROR)
            log.info("Extracting PDF text with pypdf...")
            text_parts = []
            with open(path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                total = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
                    if i % 20 == 0:
                        log.info("PDF progress: %d/%d pages", i + 1, total)
            text = chr(10).join(text_parts)
            if not text.strip():
                return "[This PDF contains no selectable text.]"
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                log.info("PDF text cached to %s", cache_path)
            except Exception as ce:
                log.warning("Could not cache PDF text: %s", ce)
            return text
        except ImportError:
            try:
                from pdfminer.high_level import extract_text
                return extract_text(path)
            except ImportError:
                return "[PDF support requires: pip install pypdf]"

    @staticmethod
    def _read_epub(path):
        cache_path = path + '.txtcache'
        if os.path.exists(cache_path) and \
                os.path.getmtime(cache_path) >= os.path.getmtime(path):
            with open(cache_path, encoding='utf-8') as f:
                cached = f.read()
            if cached.strip():
                log.info("Loaded EPUB from cache: %s", cache_path)
                return cached
        try:
            from ebooklib import epub, ITEM_DOCUMENT
            from bs4 import BeautifulSoup
            log.info("Extracting EPUB text...")
            book       = epub.read_epub(path, options={'ignore_ncx': True})
            parts      = []
            spine_ids  = [item_id for item_id, _ in book.spine]
            for item_id in spine_ids:
                item = book.get_item_with_id(item_id)
                if item is None:
                    continue
                try:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    for tag in soup(['script', 'style', 'nav', 'aside']):
                        tag.decompose()
                    for tag in soup.find_all(['h1','h2','h3','h4','p','li','br']):
                        text = tag.get_text(separator=' ').strip()
                        if text:
                            parts.append(text)
                    parts.append('')
                except Exception as e:
                    log.warning("Skipping EPUB item %s: %s", item_id, e)
            text = chr(10).join(parts)
            if not text.strip():
                return "[This EPUB contains no readable text.]"
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                log.info("EPUB text cached to %s", cache_path)
            except Exception as ce:
                log.warning("Could not cache EPUB: %s", ce)
            return text
        except ImportError as e:
            return "[EPUB support requires: pip install ebooklib beautifulsoup4]\nError: " + str(e)

    def _paginate(self, raw):
        import textwrap
        font_size      = self.config.get('font_size', 22)
        line_spacing   = self.config.get('line_spacing', 1.35)
        margin         = self.config.get('margin_px', 20)
        line_h         = int(font_size * line_spacing)
        text_w         = EPD_WIDTH - margin * 2
        text_h         = EPD_HEIGHT - 38 - 28
        lines_per_page = max(1, text_h // line_h)
        avg_char_w     = font_size * 0.52
        chars_per_line = max(20, int(text_w / avg_char_w))
        all_lines = []
        for para in raw.split(chr(10)):
            para = para.rstrip()
            if not para:
                all_lines.append('')
            else:
                wrapped = textwrap.wrap(para, width=chars_per_line)
                all_lines.extend(wrapped if wrapped else [''])
        pages = []
        i = 0
        while i < len(all_lines):
            chunk = all_lines[i:i + lines_per_page]
            while chunk and chunk[0] == '':
                chunk = chunk[1:]
                i += 1
            if chunk:
                pages.append(chunk)
            i += lines_per_page
        return pages if pages else [['']]

    def _save_position(self):
        self.config.set('last_page', self.page_index)


def scan_library(library_path):
    if not os.path.isdir(library_path):
        os.makedirs(library_path, exist_ok=True)
        return []
    results = []
    for root, _, files in os.walk(library_path):
        for f in files:
            if f.lower().endswith(('.txt', '.pdf', '.epub')):
                results.append(os.path.join(root, f))
    return sorted(results)
