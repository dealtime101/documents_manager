"""DOC534.7: a scan read by OCR can be filed with its text as an invisible layer (`ocr.searchable_pdf`), the original being kept."""
import shutil
from pathlib import Path

import pymupdf
import pypdfium2 as pdfium
import pytest
from docflow import extract
from docflow.analyze import RuleBasedAnalyzer
from docflow.extract import image_to_pdf, searchable_pdf
from docflow.pipeline import apply, propose, sha256_file, undo
from PIL import Image, ImageDraw, ImageFont
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from test_pipeline import env, make_db, mkpdf  # noqa: F401  (`env`: a configuration over a temporary folder; it needs `make_db`)

needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="needs Tesseract")
OCR = {"languages": "eng"}


def scanned_pdf(path: Path | None = None, text: str = "FACTURE HYDRO") -> bytes:
    """A PDF that is one picture of `text`: what a scanner makes."""
    import io
    im = Image.new("L", (1400, 600), 255)
    ImageDraw.Draw(im).text((100, 400), text, fill=0, font=ImageFont.load_default(size=120))
    png = io.BytesIO()
    im.save(png, "PNG")
    data = image_to_pdf(png.getvalue())
    if path:
        path.write_bytes(data)
    return data


def text_of(pdf: bytes) -> str:
    doc = pdfium.PdfDocument(pdf)
    try:
        return doc[0].get_textpage().get_text_range()
    finally:
        doc.close()


@needs_tesseract
def test_a_scan_gets_its_text_laid_over_the_picture_in_the_right_place():
    scan = scanned_pdf()
    assert text_of(scan).strip() == ""
    out = searchable_pdf(scan, OCR)
    assert out != scan and "HYDRO" in text_of(out).upper()
    before, after = pdfium.PdfDocument(scan), pdfium.PdfDocument(out)
    try:
        assert len(after) == len(before) == 1 and after[0].get_size() == before[0].get_size()  # same page, same size
        assert any(o.type == 3 for o in after[0].get_objects())  # the picture itself is still there (FPDF_PAGEOBJ_IMAGE)
        width, height = after[0].get_size()
        left, bottom, right, top = after[0].get_textpage().get_charbox(0)  # the first letter, where it was drawn: left, lower half
        assert 0.03 * width < left < 0.15 * width and 0.1 * height < bottom and top < 0.5 * height
    finally:
        before.close()
        after.close()


@needs_tesseract
def test_the_text_layer_is_invisible():
    out = searchable_pdf(scanned_pdf(), OCR)
    doc = pdfium.PdfDocument(out)
    try:
        shown = doc[0].render(scale=1, grayscale=True).to_pil()
    finally:
        doc.close()
    plain = pdfium.PdfDocument(scanned_pdf())
    try:
        assert shown.tobytes() == plain[0].render(scale=1, grayscale=True).to_pil().tobytes()  # pixel for pixel the same page
    finally:
        plain.close()


def test_a_pdf_that_already_has_its_text_is_returned_untouched(tmp_path):
    data = mkpdf(tmp_path / "t.pdf", "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant 158,98 $").read_bytes()
    assert searchable_pdf(data, OCR) is data


def test_nothing_changes_without_tesseract_or_with_ocr_switched_off(monkeypatch):
    scan = scanned_pdf()
    assert searchable_pdf(scan, {**OCR, "enabled": False}) is scan
    monkeypatch.setattr(extract, "find_tesseract", lambda name: "")
    assert searchable_pdf(scan, OCR) is scan


def test_a_failing_ocr_leaves_the_pdf_alone(monkeypatch):
    scan = scanned_pdf()
    monkeypatch.setattr(extract, "find_tesseract", lambda name: "tesseract")
    monkeypatch.setattr(extract, "ocr_text_layer", lambda *a, **k: None)
    assert searchable_pdf(scan, OCR) is scan


def test_a_blank_page_and_a_turned_page_get_no_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "find_tesseract", lambda name: "tesseract")
    seen = []
    monkeypatch.setattr(extract, "ocr_text_layer", lambda *a, **k: seen.append(1))
    doc = pymupdf.open()
    doc.new_page()  # blank
    doc.save(tmp_path / "blank.pdf")
    blank = (tmp_path / "blank.pdf").read_bytes()
    assert searchable_pdf(blank, OCR) is blank and not seen
    turned = pdfium.PdfDocument(scanned_pdf())
    turned[0].set_rotation(90)
    turned.save(tmp_path / "turned.pdf")
    turned.close()
    data = (tmp_path / "turned.pdf").read_bytes()
    assert searchable_pdf(data, OCR) is data and not seen  # the OCR was not even asked


def settings_with(cfg, **ocr):
    cfg.settings = {**cfg.settings, "ocr": {**cfg.settings.get("ocr", {}), "languages": "eng", **ocr}}


def prepared(env, name="scan.pdf"):  # noqa: F811
    cfg, db, tmp = env
    f = tmp / "inbox" / name
    scanned_pdf(f)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    p.rel_dir = "Scans"
    return cfg, db, tmp, f, p


@needs_tesseract
def test_by_default_a_scan_is_filed_as_it_is(env):  # noqa: F811
    cfg, db, tmp, f, p = prepared(env)
    sha = sha256_file(f)
    dst = apply(p, cfg, db, final_name="scan.pdf", confirmed=True)
    assert sha256_file(dst) == sha and db.op(None)["kind"] == "move" and not (tmp / "q" / "originals").exists()


@needs_tesseract
def test_with_the_setting_a_scan_is_filed_searchable_and_the_undo_gives_the_original_back(env):  # noqa: F811
    cfg, db, tmp = env
    settings_with(cfg, searchable_pdf=True)
    cfg, db, tmp, f, p = prepared(env)
    assert p.extraction == "ocr"
    sha = sha256_file(f)
    dst = apply(p, cfg, db, final_name="scan.pdf", confirmed=True)
    assert "HYDRO" in text_of(dst.read_bytes()).upper() and not f.exists()
    assert sha256_file(tmp / "q" / "originals" / f"{sha}.pdf") == sha  # the scan, byte for byte
    assert db.op(None)["kind"] == "convert" and db.find_sha(sha)  # and the same scan found again is a duplicate
    assert undo(db) == (dst, f)
    assert sha256_file(f) == sha and not dst.exists()


@needs_tesseract
def test_a_scan_that_changed_after_it_was_analysed_is_not_filed_with_a_layer(env):  # noqa: F811
    cfg, db, tmp = env
    settings_with(cfg, searchable_pdf=True)
    cfg, db, tmp, f, p = prepared(env)
    scanned_pdf(f, "SOMETHING ELSE")
    with pytest.raises(OSError, match="changed since it was analysed"):
        apply(p, cfg, db, final_name="scan.pdf", confirmed=True)
    assert f.exists() and not (tmp / "lib").exists()


def test_a_pdf_with_its_own_text_is_still_just_moved_when_the_setting_is_on(env):  # noqa: F811
    cfg, db, tmp = env
    settings_with(cfg, searchable_pdf=True)
    f = mkpdf(tmp / "inbox" / "t.pdf", "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant 158,98 $")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    p.rel_dir = "Bills"
    apply(p, cfg, db, final_name="t.pdf", confirmed=True)
    assert db.op(None)["kind"] == "move"


@needs_tesseract
@pytest.mark.django_db
def test_the_web_approval_files_a_scan_searchable_too(api, sb, settings):  # noqa: F811
    settings.DOCFLOW.settings = {**settings.DOCFLOW.settings, "ocr": {**settings.DOCFLOW.settings.get("ocr", {}),
                                                                      "languages": "eng", "searchable_pdf": True}}
    scanned_pdf(sb / "inbox" / "scan.pdf")
    api.post("/api/scan")
    item = api.get("/api/items").json()[0]
    api.patch(f"/api/items/{item['id']}", {"company": "Hydro", "document_type": "Facture", "rel_dir": "Scans"}, format="json")
    approved = api.post(f"/api/items/{item['id']}/approve")
    assert approved.status_code == 200, approved.json()
    assert "HYDRO" in text_of(Path(approved.json()["result_path"]).read_bytes()).upper()
    assert api.get("/api/history").json()[0]["kind"] == "convert"
