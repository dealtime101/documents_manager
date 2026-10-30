"""DOC534.12: a scanner that feeds a stack of documents makes ONE PDF. The scan suggests where it is cut (a blank separator sheet, another
company, another invoice number), the person confirms, and each piece becomes a document of its own in the queue."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pypdfium2 as pdfium
import pytest
from docflow import pipeline
from docflow.analyze import RuleBasedAnalyzer
from docflow.extract import extract_text, split_pages
from docflow.pipeline import propose
from docflow.splitting import suggest
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from test_pipeline import HYDRO as PIPELINE_HYDRO
from test_pipeline import env, make_db  # noqa: F401  (`env`: a configuration over a temporary folder; it needs `make_db`)
from triage import services
from triage.models import Item

pytestmark = pytest.mark.django_db

HYDRO = PIPELINE_HYDRO.split("\n")  # the invoice that the engine files on its own ("auto")
HYDRO_NEXT = ["Detail de la consommation", "Mois precedent : 410 kWh"]  # the second sheet of the same invoice: names nobody
VIDEOTRON = ["Videotron", "Facture du 3 novembre 2025", "Numero de facture : 555000111", "Montant : 99,00 $"]


def stack(path, pages):
    """A PDF with one page per entry of `pages`: the lines written on it ([] = a blank sheet)."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        for i, text in enumerate(lines):
            page.insert_text((60, 90 + i * 22), text, fontsize=12)
    doc.save(path)
    return path


def page_count(data: bytes) -> int:
    doc = pdfium.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


class Says:
    """An analyzer that reads (company, invoice number) from the first two words of a page, so the cut rules are tested alone."""

    def analyze(self, text: str):
        words = text.split()
        company = words[0] if words and words[0].isupper() else None
        number = words[1] if company and len(words) > 1 and words[1].isdigit() else None
        return SimpleNamespace(company=company, invoice_number=number)


@pytest.mark.parametrize(("pages", "blank", "expected"), [
    (["A 1", "x", "B 2", "y"], [], [(1, 2), (3, 4)]),                      # another company opens a document
    (["A 1", "x", "A 2", "y"], [], [(1, 2), (3, 4)]),                      # the same company, another invoice number
    (["A 1", "A 1", "x"], [], []),                                         # the same document over three pages
    (["A 1", "x", "", "A 1", "x"], [3], [(1, 2), (4, 5)]),                 # a blank sheet separates, whoever follows it
    (["A 1", "x", ""], [3], []),                                           # a separator at the end alone is not a stack
    (["A 1", "", "x", "x"], [2], [(1, 1), (3, 4)]),                        # the sheet after a separator opens a document, named or not
    (["", "A 1", "x", "", "", "B 2", ""], [1, 4, 5, 7], [(2, 3), (6, 6)]),  # separators at both ends and doubled are all left out
    (["A 1", "x", "x"], [], []),                                           # pages that name nobody follow the document before
    (["x", "x", "A 1"], [], []),                                           # ...and so does one that names the first company late
    (["A 1", "x", "B"], [], [(1, 2), (3, 3)]),                             # a company without a number still opens a document
    (["a", ""], [], []),                                                   # a lower-case first word is not a company here
])
def test_where_a_stack_is_cut(pages, blank, expected):
    assert suggest(pages, blank, Says()) == expected


def test_the_same_company_in_another_case_is_the_same_document():
    class Case:
        def analyze(self, text):
            return SimpleNamespace(company=text, invoice_number=None)
    assert suggest(["Hydro-Quebec", "HYDRO-QUEBEC"], [], Case()) == []


def test_extract_gives_the_text_of_each_page_and_the_blank_ones(tmp_path):
    f = stack(tmp_path / "s.pdf", [HYDRO, [], VIDEOTRON])
    ex = extract_text(f)
    assert ex.pages == 3 and len(ex.page_texts) == 3
    assert "Hydro-Québec" in ex.page_texts[0] and ex.page_texts[1].strip() == "" and "Videotron" in ex.page_texts[2]
    assert ex.blank_pages == [2]
    assert ex.text == "\n".join(ex.page_texts)  # the whole text is these, as before


def test_pages_are_cut_out_with_their_text(tmp_path):
    data = stack(tmp_path / "s.pdf", [HYDRO, HYDRO_NEXT, [], VIDEOTRON]).read_bytes()
    first, second = split_pages(data, [(1, 2), (4, 4)])
    assert (page_count(first), page_count(second)) == (2, 1)
    (tmp_path / "a.pdf").write_bytes(first)
    (tmp_path / "b.pdf").write_bytes(second)
    a, b = extract_text(tmp_path / "a.pdf").text, extract_text(tmp_path / "b.pdf").text
    assert "Hydro-Québec" in a and "kWh" in a and "Videotron" not in a
    assert "Videotron" in b and "Hydro" not in b


@pytest.mark.parametrize("ranges", [[(0, 1)], [(2, 3)], [(2, 1)], [(1, 1), (3, 3)]])
def test_a_range_outside_the_document_is_refused(tmp_path, ranges):
    data = stack(tmp_path / "s.pdf", [HYDRO, VIDEOTRON]).read_bytes()
    with pytest.raises(ValueError, match="are not in a document of 2 pages"):
        split_pages(data, ranges)


def test_a_stack_is_proposed_with_its_ranges_and_never_filed_on_its_own(env):
    cfg, db, tmp = env
    f = stack(tmp / "inbox" / "stack.pdf", [HYDRO, HYDRO_NEXT, [], VIDEOTRON])
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.split == [(1, 2), (4, 4)]
    assert "This file seems to hold several documents." in p.notes
    assert p.status != "auto"  # one name and one destination for a pile of documents: a person decides


def test_one_document_over_two_pages_is_not_a_stack(env):
    cfg, db, tmp = env
    f = stack(tmp / "inbox" / "one.pdf", [HYDRO, HYDRO_NEXT])
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.split == [] and "This file seems to hold several documents." not in p.notes
    assert p.status == "auto"  # the stack rule does not hold back a document that was fine


def test_pages_that_could_not_be_read_make_no_suggestion(env, monkeypatch):
    cfg, db, tmp = env
    f = stack(tmp / "inbox" / "stack.pdf", [HYDRO, VIDEOTRON])
    real = pipeline.extract_text

    def unread(path, ocr):
        ex = real(path, ocr)
        ex.missing_pages = 1  # a page OCR could not read: where a document ends is unknown
        return ex
    monkeypatch.setattr(pipeline, "extract_text", unread)
    assert propose(f, cfg, db, RuleBasedAnalyzer(cfg)).split == []


# ------------------------------------------------------------------ the web interface
def scanned(api, sb, pages=None):
    """A stack in the inbox, scanned: its item."""
    stack(sb / "inbox" / "stack.pdf", pages or [HYDRO, HYDRO_NEXT, [], VIDEOTRON])
    api.post("/api/scan")
    return Item.objects.get(state=Item.PENDING)


def test_the_queue_shows_the_ranges_of_a_stack(api, sb):  # noqa: F811
    it = scanned(api, sb)
    got = api.get(f"/api/items/{it.id}").json()
    assert got["split"] == [[1, 2], [4, 4]] and got["status"] != "auto"


def test_a_stack_is_cut_into_documents_that_join_the_queue(api, sb):  # noqa: F811
    it = scanned(api, sb)
    original = (sb / "inbox" / "stack.pdf").read_bytes()
    r = api.post(f"/api/items/{it.id}/split")
    assert r.status_code == 200, r.content
    assert r.json()["children"] == 2 and r.json()["item"]["state"] == "removed"
    inbox = sorted(f.name for f in (sb / "inbox").iterdir())
    assert inbox == ["stack - 1.pdf", "stack - 2.pdf"]  # the stack itself has left the inbox
    kept = services.cfg().path("quarantine") / "originals" / f"{hashlib.sha256(original).hexdigest()}.pdf"
    assert kept.read_bytes() == original  # ...and is kept, whole
    pending = {Path(i.source_path).name: i for i in Item.objects.filter(state=Item.PENDING)}
    assert set(pending) == {"stack - 1.pdf", "stack - 2.pdf"}  # each piece is read as a document of its own
    assert pending["stack - 1.pdf"].analysis["company"] == "Hydro-Quebec" and pending["stack - 2.pdf"].analysis["company"] == "Videotron"
    assert all(i.split is None for i in pending.values())  # a piece is not cut again


def test_a_stack_that_was_already_handled_or_is_not_one_is_refused(api, sb):  # noqa: F811
    it = scanned(api, sb)
    assert api.post(f"/api/items/{it.id}/split").status_code == 200
    again = api.post(f"/api/items/{it.id}/split")
    assert again.status_code == 400 and again.json()["detail"] == "this item has already been handled"
    stack(sb / "inbox" / "one.pdf", [HYDRO, HYDRO_NEXT])
    api.post("/api/scan")
    one = Item.objects.get(source_path__endswith="one.pdf", state=Item.PENDING)
    r = api.post(f"/api/items/{one.id}/split")
    assert r.status_code == 400 and r.json()["detail"] == "this file was not found to hold several documents"
    assert (sb / "inbox" / "one.pdf").exists()


def test_a_file_that_changed_since_the_scan_is_left_alone(api, sb):  # noqa: F811
    it = scanned(api, sb)
    stack(sb / "inbox" / "stack.pdf", [VIDEOTRON, HYDRO])  # replaced after it was analysed: the ranges no longer describe it
    r = api.post(f"/api/items/{it.id}/split")
    assert r.status_code == 400 and r.json()["detail"].startswith("the file could not be split: ")
    assert [f.name for f in (sb / "inbox").iterdir()] == ["stack.pdf"]
    it.refresh_from_db()
    assert it.state == Item.PENDING and it.resolved_at is None  # not stuck "being handled": the person can try again or ignore it


def test_a_failure_while_setting_the_stack_aside_leaves_no_piece_behind(api, sb, monkeypatch):  # noqa: F811
    it = scanned(api, sb)
    before = (sb / "inbox" / "stack.pdf").read_bytes()

    def refuse(src, dst, sha):
        raise OSError("disk full")
    monkeypatch.setattr(pipeline, "_move_verified", refuse)
    r = api.post(f"/api/items/{it.id}/split")
    assert r.status_code == 400 and r.json()["detail"] == "the file could not be split: OSError"
    assert [f.name for f in (sb / "inbox").iterdir()] == ["stack.pdf"] and (sb / "inbox" / "stack.pdf").read_bytes() == before
    it.refresh_from_db()
    assert it.state == Item.PENDING and it.resolved_at is None


def test_a_piece_never_replaces_a_file_that_has_its_name(api, sb):  # noqa: F811
    it = scanned(api, sb)
    (sb / "inbox" / "stack - 1.pdf").write_bytes(b"mine")
    assert api.post(f"/api/items/{it.id}/split").status_code == 200
    assert (sb / "inbox" / "stack - 1.pdf").read_bytes() == b"mine"
    assert sorted(f.name for f in (sb / "inbox").iterdir()) == ["stack - 1 (2).pdf", "stack - 1.pdf", "stack - 2.pdf"]

