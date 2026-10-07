"""Text of a PDF: text layer first, page-by-page OCR only if the page is empty."""
import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

log = logging.getLogger(__name__)

# PDFium is NOT thread-safe: two threads in it crash the process (a segmentation fault, not an exception). A scan reads several
# PDFs in parallel, so every call into PDFium is made under this lock; Tesseract, the slow part, runs OUTSIDE it.
_PDFIUM = threading.RLock()

OCR_TIMEOUT = 300  # seconds PER PAGE for the orientation check and the OCR together; generous because several may run in parallel
OSD_TIMEOUT = 60   # the orientation check is quick: it never takes more than this out of the page's budget
MIN_OCR_SECONDS = 30  # whatever the orientation check used, the OCR still gets a chance
MAX_PIXELS = 40_000_000  # one rendered page: an A4 at 300 DPI is 8.7 million, an A0 is 140 million (and ~ 400 MB of memory)
MIN_DPI = 50  # below this a page is not readable by OCR: it is counted as unread instead


def _page_area(page) -> float:
    """Area of a page in square points (72 per inch), whatever its rotation."""
    width, height = page.get_size()
    return width * height


def _page_text(page) -> str:
    """The text layer of a page, with plain line breaks (PDFium separates lines with \\r\\n)."""
    textpage = page.get_textpage()
    try:
        return textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
    finally:
        textpage.close()


def _png(page, dpi: float) -> bytes:
    """The page as a grey PNG at `dpi`, for Tesseract. Written here (a header, one zlib stream) so that no imaging library is needed."""
    bitmap = page.render(scale=dpi / 72, grayscale=True)
    width, height, stride = bitmap.width, bitmap.height, bitmap.stride
    raw = bytes(bitmap.buffer)
    rows = b"".join(b"\x00" + raw[y * stride:y * stride + width] for y in range(height))  # filter byte 0 (none) before each row

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _objects(page, kind: int) -> list:
    return list(page.get_objects(filter=[kind]))


def _dpi_within_budget(page, wanted: int) -> float | None:
    """`wanted` DPI, lowered so the page stays within MAX_PIXELS; None when that would leave it unreadable (< MIN_DPI)."""
    pixels = _page_area(page) * (wanted / 72) ** 2  # 72 points per inch
    dpi = wanted if pixels <= MAX_PIXELS else wanted * (MAX_PIXELS / pixels) ** 0.5
    return dpi if dpi >= MIN_DPI else None
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: a windowed program must not flash a console per Tesseract run


def _env_for(exe: str) -> dict[str, str]:
    """The environment of a Tesseract run: one thread each (parallelism happens between documents), and the language data that sits
    next to a bundled tesseract.exe (the packaged application carries its own, so nothing has to be installed)."""
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    tessdata = Path(exe).parent / "tessdata"
    if Path(exe).is_absolute() and tessdata.is_dir():
        env["TESSDATA_PREFIX"] = str(tessdata)
    return env


@dataclass
class Extracted:
    text: str
    method: str   # text | ocr | mixed | ocr_unavailable (OCR failed) | ocr_disabled (switched off in the configuration)
    pages: int
    missing_pages: int = 0  # pages that needed OCR and could not be read (timeout, failure): the text is then incomplete,
                            # whatever `method` says (it only describes the pages that WERE read)


def ocr_image(png: bytes, tesseract: str, languages: str, timeout: float = OCR_TIMEOUT) -> str | None:
    """None if tesseract is not found or fails. Nothing is sent over the network: local binary."""
    exe = shutil.which(tesseract)
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "p.png"
        img.write_bytes(png)
        try:
            r = subprocess.run([exe, str(img), "stdout", "-l", languages], capture_output=True, text=True,
                               encoding="utf-8", errors="replace",  # Tesseract writes UTF-8 whatever the locale
                               timeout=timeout, env=_env_for(exe), check=False, creationflags=NO_WINDOW)  # the exit code is read just below, not raised
        except subprocess.TimeoutExpired:
            log.warning("%s timed out after %.0f s on a page (languages %s): the page is not read", exe, timeout, languages)
            return None  # one page that is too slow must not fail the whole document
        except OSError as e:  # found on the PATH but cannot be launched (bad format, missing interpreter, ...)
            log.warning("could not run %s: %s", exe, e)
            return None
    if r.returncode != 0:  # a missing language, a damaged picture: say which, or "pages not read" has no explanation
        log.warning("%s failed with exit code %s (languages %s): %s", exe, r.returncode, languages, " ".join(r.stderr.split())[:300])
        return None
    return r.stdout


def detect_rotation(png: bytes, tesseract: str, timeout: float = OSD_TIMEOUT) -> int:
    """Degrees (clockwise) to apply to straighten the page, 0 if unknown or unreliable (Tesseract OSD)."""
    exe = shutil.which(tesseract)
    if not exe:
        return 0
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "p.png"
        img.write_bytes(png)
        try:
            r = subprocess.run([exe, str(img), "stdout", "--psm", "0", "-l", "osd"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=_env_for(exe), check=False,
                               creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return 0
        except OSError as e:
            log.warning("could not run %s: %s", exe, e)
            return 0
    rot = re.search(r"Rotate:\s*(\d+)", r.stdout)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", r.stdout)
    if r.returncode != 0 or not rot or not conf or float(conf.group(1)) < 2.0:
        return 0
    return int(rot.group(1)) % 360


def extraction_fingerprint(pdf: Path, ocr: dict) -> str:
    """Identity of a saved extraction: the PDF bytes, the OCR settings and this module's code. A text saved by a test
    bench is only trustworthy while all three are unchanged."""
    h = hashlib.sha256()
    pdf_hash = hashlib.sha256()
    with open(pdf, "rb") as f:  # by blocks: the whole PDF is never held in memory (same digest as hashing it in one piece)
        for block in iter(lambda: f.read(1 << 20), b""):
            pdf_hash.update(block)
    h.update(pdf_hash.digest())
    for part in (json.dumps(ocr, sort_keys=True).encode(), Path(__file__).read_bytes()):
        h.update(hashlib.sha256(part).digest())
    return h.hexdigest()


SCAN_COVER = 0.8  # share of the page that images must cover for it to be "a scan" (a letterhead logo is far below)


def _scan_with_small_text(page, chars: int, limit: int) -> bool:
    """An image over (almost) the whole page with little text on it: a scan whose text layer is only a stamp, a header or a
    Bates number added by the scanner software. The body is in the picture, so the text layer must not be trusted. A
    searchable scan (full text layer, `chars` >= `limit`) is left alone: reading it again would only cost time.
    ponytail: image areas are added up, so overlapping images count twice; an over-count only means one extra OCR run."""
    if chars >= limit:
        return False
    area = _page_area(page)
    covered = 0.0
    for image in _objects(page, pdfium_raw.FPDF_PAGEOBJ_IMAGE):
        left, bottom, right, top = image.get_bounds()
        covered += max(0.0, right - left) * max(0.0, top - bottom)
    return area > 0 and covered / area >= SCAN_COVER


def _words(text: str) -> list[str]:
    """Letters and digits only, no accents, no case: what two readings of the same text have in common."""
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())


def _covers(ocr: str, native: str) -> bool:
    """Did OCR read what the text layer already says? OCR never reproduces the same spaces, line breaks, case or accents, so
    compare the WORDS: the text layer is covered when its words follow each other in the OCR text, or (OCR misreads a few
    letters) when nearly all of them are found in it. Text that OCR did not see at all (a stamp) is not covered."""
    wanted, got = _words(native), _words(ocr)
    if not wanted:
        return True
    if " ".join(wanted) in " ".join(got):
        return True
    seen = set(got)
    return sum(w in seen for w in wanted) / len(wanted) >= 0.8


def _is_blank(page, text: str) -> bool:
    """Nothing at all on the page: no text, no picture, no drawing (a separator, an empty back page). A scan always holds a
    picture, and a page whose text was turned into outlines holds drawings, so those still go to OCR."""
    return (not text.strip() and not _objects(page, pdfium_raw.FPDF_PAGEOBJ_IMAGE)
            and not _objects(page, pdfium_raw.FPDF_PAGEOBJ_PATH))


def find_tesseract(name: str) -> str:
    """The full path of Tesseract, "" when there is none: on the PATH, or on Windows where its installer puts it (it does not use PATH)."""
    bundled = Path(os.environ.get("DOCFLOW_ROOT") or "") / "tesseract" / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    if os.environ.get("DOCFLOW_ROOT") and bundled.is_file():  # the one that comes with the packaged application
        return str(bundled)
    found = shutil.which(name)
    if found or sys.platform != "win32":
        return found or ""
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        candidate = Path(base or "") / "Tesseract-OCR" / "tesseract.exe"
        if base and candidate.is_file():
            return str(candidate)
    return ""


def extract_text(path: Path, ocr: dict | None = None) -> Extracted:
    ocr = ocr or {}
    min_chars = ocr.get("min_chars_per_page", 30)
    scan_chars = ocr.get("min_chars_scanned_page", 200)  # below this, a page that is one big image is read by OCR too
    parts, used_text, used_ocr, missing_pages = [], False, False, 0
    tesseract_exe = find_tesseract(ocr.get("tesseract", "tesseract"))  # searched ONCE: the pages get the full path
    tesseract_found = bool(tesseract_exe)
    with _PDFIUM:
        doc = pdfium.PdfDocument(path)
        n = len(doc)
    try:
        for index in range(n):  # all pages
            with _PDFIUM:
                page = doc[index]
                t = _page_text(page)
                text_page = len(t.strip()) >= min_chars and not _scan_with_small_text(page, len(t.strip()), scan_chars)
                blank = not text_page and _is_blank(page, t)
                if not text_page and not blank:
                    osd_dpi, ocr_dpi = _dpi_within_budget(page, 150), _dpi_within_budget(page, 300)
            parts.append(t)
            if text_page:
                used_text = True
                continue
            if blank:  # nothing for OCR to find: read (empty), never "missing", never rendered
                used_text = True
                continue
            exe = tesseract_exe
            if not ocr.get("enabled", True):
                missing_pages += 1  # a page that needs reading and will not be: reported, never silently skipped
            elif not tesseract_found:
                missing_pages += 1  # no program to read it: do not even render the two images that would be thrown away
            elif osd_dpi is None or ocr_dpi is None:
                missing_pages += 1  # an absurd page size: reported as unread, never rendered
            else:
                started = time.monotonic()  # one budget for the page: the orientation check and the OCR share OCR_TIMEOUT
                with _PDFIUM:
                    osd_png = _png(page, round(osd_dpi))
                angle = detect_rotation(osd_png, exe, OSD_TIMEOUT)
                with _PDFIUM:
                    if angle:  # sideways or upside-down scan: straighten the page before OCR
                        page.set_rotation((page.get_rotation() + angle) % 360)
                    ocr_png = _png(page, round(ocr_dpi))
                left = max(MIN_OCR_SECONDS, OCR_TIMEOUT - (time.monotonic() - started))
                o = ocr_image(ocr_png, exe, ocr.get("languages", "fra+eng"), left)
                if o is None:
                    missing_pages += 1
                elif o.strip():  # an empty OCR result must not wipe real (if short) native text
                    native = t.strip()
                    parts[-1] = o if not native or _covers(o, native) else f"{t}\n{o}"  # keep native text OCR did not see
                    used_ocr = True
                elif not t.strip():
                    used_ocr = True  # blank page read by OCR: nothing there (kept as before: method "ocr")
                else:
                    used_text = True
    finally:
        with _PDFIUM:
            doc.close()
    method = ("mixed" if used_text and used_ocr else "ocr" if used_ocr else
              "ocr_disabled" if missing_pages and not ocr.get("enabled", True) else
              "ocr_unavailable" if missing_pages else "text")
    return Extracted("\n".join(parts), method, n, missing_pages)
