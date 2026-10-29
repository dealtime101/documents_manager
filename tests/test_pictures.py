"""DOC534.6: a photo or an image (JPEG, PNG, HEIC...) is filed as a PDF, and the original is kept so that the undo can give it back."""
import json
import shutil
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from docflow import extract
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.db import DB
from docflow.extract import IMAGE_SUFFIXES, extract_text, image_to_pdf, is_image, is_scannable
from docflow.pipeline import apply, propose, sha256_file, undo
from PIL import Image, ImageDraw, ImageFont
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from test_pipeline import GOOD, HYDRO, env, make_db  # noqa: F401  (`env`: a configuration over a temporary folder; it needs `make_db`)


def picture(path: Path, size=(300, 200), mode="RGB", fmt=None, color="white", **save) -> Path:
    im = Image.new(mode, size, color)
    ImageDraw.Draw(im).rectangle((20, 20, 120, 60), fill=0)  # something that is not blank
    im.save(path, fmt, **save)
    return path


def pages(pdf: bytes) -> list[tuple[float, float]]:
    doc = pdfium.PdfDocument(pdf)
    try:
        return [doc[i].get_size() for i in range(len(doc))]
    finally:
        doc.close()


@pytest.fixture
def read_as_hydro(monkeypatch):
    """OCR that reads the Hydro-Québec invoice whatever the picture shows (the OCR itself has its own tests)."""
    monkeypatch.setattr(extract, "find_tesseract", lambda name: "tesseract")
    monkeypatch.setattr(extract, "detect_rotation", lambda *a, **k: 0)
    monkeypatch.setattr(extract, "ocr_image", lambda *a, **k: HYDRO)


def test_the_picture_suffixes_are_scanned_and_everything_else_is_not():
    for name in ("a.jpg", "a.JPEG", "a.png", "a.tif", "a.webp", "a.pdf", "a.PDF"):
        assert is_scannable(Path(name)), name
    for name in ("a.txt", "a.docx", "a.mp4", "a"):
        assert not is_scannable(Path(name)), name
    assert is_image(Path("PHOTO.JPG")) and not is_image(Path("a.pdf"))


def test_a_picture_becomes_a_one_page_pdf_of_about_an_a4_sheet(tmp_path):
    for fmt, name in (("JPEG", "p.jpg"), ("PNG", "p.png")):
        pdf = image_to_pdf(picture(tmp_path / name, size=(4000, 3000), fmt=fmt).read_bytes())
        assert pdf.startswith(b"%PDF-")
        (w, h), = pages(pdf)  # exactly one page
        assert max(w, h) == pytest.approx(11.69 * 72, abs=2) and w > h  # the long side is an A4's, the shape is the picture's


def test_a_small_picture_is_not_given_a_tiny_page(tmp_path):
    (w, h), = pages(image_to_pdf(picture(tmp_path / "s.png", size=(300, 200)).read_bytes()))
    assert max(w, h) == pytest.approx(300 / 150 * 72, abs=2)  # at least 150 DPI: the OCR needs pixels per inch, not inches


def test_the_orientation_of_the_camera_is_applied(tmp_path):
    im = Image.new("RGB", (400, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees clockwise to see it upright"
    f = tmp_path / "phone.jpg"
    im.save(f, exif=exif)
    (w, h), = pages(image_to_pdf(f.read_bytes()))
    assert h > w  # the picture was taken sideways: the page is upright


def test_transparency_is_flattened_onto_white_not_black(tmp_path):
    f = picture(tmp_path / "t.png", mode="RGBA", color=(0, 0, 0, 0))  # fully transparent
    doc = pdfium.PdfDocument(image_to_pdf(f.read_bytes()))
    try:
        shown = doc[0].render(scale=1, grayscale=True).to_pil().convert("L")
    finally:
        doc.close()
    assert shown.getpixel((shown.width - 5, shown.height - 5)) > 240  # the corner is white, not black


@pytest.mark.parametrize("mode", ["1", "L", "P", "CMYK", "LA"])
def test_the_other_color_modes_are_converted(tmp_path, mode):
    f = tmp_path / "m.png" if mode in ("1", "L", "P", "LA") else tmp_path / "m.jpg"
    Image.new(mode, (50, 50)).save(f)
    assert len(pages(image_to_pdf(f.read_bytes()))) == 1


@pytest.mark.parametrize("data", [b"", b"hello", b"\x89PNG\r\n\x1a\nnot really", b"%PDF-1.4 a pdf is not a picture"])
def test_something_that_is_not_a_picture_is_refused_with_a_value_error(data):
    with pytest.raises(ValueError, match="not a picture"):
        image_to_pdf(data)


def test_a_picture_too_big_to_open_is_refused_not_decoded(tmp_path, monkeypatch):
    f = picture(tmp_path / "big.png", size=(200, 200))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # Pillow refuses at twice the limit
    with pytest.raises(ValueError, match="not a picture"):
        image_to_pdf(f.read_bytes())


def test_heic_is_read_when_pillow_heif_is_installed(tmp_path):
    heif = pytest.importorskip("pillow_heif")
    assert {".heic", ".heif"} <= IMAGE_SUFFIXES
    f = tmp_path / "iphone.heic"
    heif.from_pillow(Image.new("RGB", (64, 48), "white")).save(f)
    assert len(pages(image_to_pdf(f.read_bytes()))) == 1


def test_heic_is_not_a_picture_where_pillow_heif_is_missing():
    import importlib.util
    if importlib.util.find_spec("pillow_heif"):
        pytest.skip("pillow-heif is installed here")
    assert ".heic" not in IMAGE_SUFFIXES  # the file is left alone, as every file of a type that is not handled


def test_the_text_of_a_picture_is_read_by_ocr_like_a_scanned_page(tmp_path, read_as_hydro):
    got = extract_text(picture(tmp_path / "scan.jpg", fmt="JPEG"), {})
    assert got.method == "ocr" and got.text.strip() == HYDRO and got.pages == 1 and got.missing_pages == 0


def test_a_picture_without_tesseract_says_so_like_a_scanned_page(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "find_tesseract", lambda name: "")
    got = extract_text(picture(tmp_path / "scan.png"), {})
    assert got.method == "ocr_unavailable" and got.missing_pages == 1


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs Tesseract")
def test_a_real_photographed_text_is_read(tmp_path):
    im = Image.new("L", (1400, 300), 255)
    ImageDraw.Draw(im).text((40, 80), "FACTURE HYDRO", fill=0, font=ImageFont.load_default(size=120))
    f = tmp_path / "photo.png"
    im.save(f)
    got = extract_text(f, {"languages": "eng"})
    assert "HYDRO" in got.text.upper() and got.method == "ocr"  # "FAC TURE": the drawn letters are not spaced like a font's


def test_a_picture_is_proposed_with_a_pdf_name(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.final_name == GOOD and p.sha256 == sha256_file(f) and p.extraction == "ocr"
    assert f.exists()  # nothing is moved by a proposal


def test_filing_a_picture_writes_the_pdf_keeps_the_original_and_records_both(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    sha = sha256_file(f)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    assert dst == tmp / "lib" / "Bills/Hydro-Québec/2025" / GOOD
    assert dst.read_bytes().startswith(b"%PDF-") and len(pages(dst.read_bytes())) == 1
    kept = tmp / "q" / "originals" / f"{sha}.jpg"
    assert not f.exists() and kept.is_file() and sha256_file(kept) == sha  # the original is set aside, byte for byte
    op = db.op(None)
    assert op["kind"] == "convert" and op["src"] == str(f) and op["dst"] == str(dst)
    assert json.loads(op["detail"]) == {"kept": str(kept), "pdf_sha": sha256_file(dst)}
    assert db.find_sha(sha)["destination_path"] == str(dst)  # the same photo, found again, is a duplicate


def test_the_same_photo_found_again_after_filing_is_a_duplicate(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    data = f.read_bytes()
    apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    copy = tmp / "inbox" / "again.jpg"
    copy.write_bytes(data)
    assert propose(copy, cfg, db, RuleBasedAnalyzer(cfg)).status == "duplicate"


def test_undoing_a_picture_gives_the_original_back_and_removes_the_pdf(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    sha = sha256_file(f)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    assert undo(db) == (dst, f)
    assert f.exists() and sha256_file(f) == sha and not dst.exists()
    assert not (tmp / "q" / "originals" / f"{sha}.jpg").exists()
    assert db.find_sha(sha) is None  # no longer filed
    with pytest.raises(ValueError):
        undo(db)  # already undone


def test_a_picture_can_be_filed_again_after_its_undo(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    undo(db)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    assert dst.exists() and not f.exists()


def test_undo_refuses_when_the_pdf_was_edited_since_and_changes_nothing(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    dst.write_bytes(dst.read_bytes() + b"\n% annotated by hand")
    with pytest.raises(ValueError, match="changed since it was filed"):
        undo(db)
    assert dst.exists() and not f.exists() and db.op(None)["undone"] == 0


def test_undo_refuses_when_the_original_place_is_taken_and_changes_nothing(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    f.write_bytes(b"someone else's file")
    with pytest.raises(FileExistsError):
        undo(db)
    assert dst.exists() and f.read_bytes() == b"someone else's file"


def test_undo_says_so_when_the_kept_original_is_gone(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    next((tmp / "q" / "originals").iterdir()).unlink()
    with pytest.raises(FileNotFoundError, match="no longer kept"):
        undo(db)
    assert dst.exists()


def test_a_picture_that_changed_after_it_was_analysed_is_not_filed(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    picture(f, size=(310, 200), fmt="JPEG")  # replaced by another picture
    with pytest.raises(OSError, match="changed since it was analysed"):
        apply(p, cfg, db)
    assert f.exists() and not (tmp / "lib").exists() and not (tmp / "q" / "originals").exists()


def test_a_picture_that_cannot_be_converted_is_not_filed_and_stays(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    f.write_bytes(b"not a picture any more")
    p.sha256 = sha256_file(f)  # the same bytes as read at the time of the apply
    with pytest.raises(ValueError, match="not a picture"):
        apply(p, cfg, db)
    assert f.exists() and not (tmp / "lib").exists()


def test_a_history_failure_puts_the_picture_back_and_leaves_no_pdf(env, read_as_hydro, monkeypatch):  # noqa: F811
    cfg, db, tmp = env
    f = picture(tmp / "inbox" / "IMG_0001.jpg", fmt="JPEG")
    sha = sha256_file(f)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))

    def boom(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(DB, "add_op", boom)
    with pytest.raises(RuntimeError):
        apply(p, cfg, db)
    assert f.exists() and sha256_file(f) == sha
    assert not list((tmp / "lib").rglob("*.pdf")) and not list((tmp / "q" / "originals").glob("*"))
    assert db.find_sha(sha) is None


def test_two_pictures_of_one_document_get_two_names_never_one_overwritten(env, read_as_hydro):  # noqa: F811
    cfg, db, tmp = env
    a = picture(tmp / "inbox" / "a.jpg", size=(300, 200), fmt="JPEG")
    b = picture(tmp / "inbox" / "b.jpg", size=(320, 200), fmt="JPEG")
    first = apply(propose(a, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db, confirmed=True)
    second = apply(propose(b, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db, confirmed=True)
    assert first != second and first.exists() and second.exists() and second.name.endswith(" (2).pdf")


def test_the_history_database_of_an_older_version_gets_the_new_column(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("CREATE TABLE operations (id INTEGER PRIMARY KEY, document_id INTEGER, kind TEXT, src TEXT, dst TEXT, "
                      "ts TEXT, undone INTEGER DEFAULT 0); INSERT INTO operations (kind, src, dst) VALUES ('move', 'a', 'b');")
    old.commit()
    old.close()
    with DB(tmp_path / "old.db") as db:
        assert db.op(None)["detail"] is None  # the old row is still there, with nothing to remember
        db.add_op(1, "convert", "x", "y", "{}")
    with DB(tmp_path / "old.db") as db:  # opening it again does not try to add the column twice
        assert db.op(None)["detail"] == "{}"


def test_the_scan_and_the_dashboard_count_pictures_and_pdfs_alike(tmp_path):
    from triage import services
    for name in ("a.pdf", "b.JPG", "c.png", "d.txt", "e.docx"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "@eaDir").mkdir()
    (tmp_path / "@eaDir" / "f.jpg").write_bytes(b"x")
    assert sorted(p.name for p in services.pdfs_under(tmp_path)) == ["a.pdf", "b.JPG", "c.png"]


@pytest.mark.django_db
def test_a_picture_goes_through_the_web_flow_preview_approval_and_undo(api, sb, read_as_hydro):  # noqa: F811
    f = picture(sb / "inbox" / "IMG_1.jpg", fmt="JPEG")
    before = f.read_bytes()
    assert api.post("/api/scan").json()["created"] == 1
    item = api.get("/api/items").json()[0]
    assert item["filename"] == "IMG_1.jpg" and item["final_name"].endswith(".pdf")
    preview = api.get(f"/api/items/{item['id']}/pdf")  # the browser cannot show a HEIC: it is shown as the PDF it will become
    assert preview.status_code == 200 and preview["Content-Type"] == "application/pdf"
    assert "IMG_1.pdf" in preview["Content-Disposition"] and b"".join(preview.streaming_content).startswith(b"%PDF-")
    assert f.read_bytes() == before  # looking at it moved nothing

    approved = api.post(f"/api/items/{item['id']}/approve")
    assert approved.status_code == 200
    filed = Path(approved.json()["result_path"])
    assert filed.suffix == ".pdf" and filed.read_bytes().startswith(b"%PDF-") and not f.exists()
    assert api.get(f"/api/items/{item['id']}/pdf").status_code == 200  # the filed document is the PDF itself

    op = api.get("/api/history").json()[0]
    assert op["kind"] == "convert"
    assert api.post(f"/api/history/{op['id']}/undo").status_code == 200
    assert f.read_bytes() == before and not filed.exists()  # the very bytes of the photo are back
    assert api.get("/api/items").json()[0]["filename"] == "IMG_1.jpg"  # and it waits to be filed again


@pytest.mark.django_db
def test_a_preview_of_a_picture_that_cannot_be_read_is_unavailable_not_a_server_error(api, sb, read_as_hydro):  # noqa: F811
    f = picture(sb / "inbox" / "IMG_2.jpg", fmt="JPEG")
    api.post("/api/scan")
    item = api.get("/api/items").json()[0]
    f.write_bytes(b"truncated")
    assert api.get(f"/api/items/{item['id']}/pdf").status_code == 404
