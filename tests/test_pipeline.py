from datetime import UTC
from pathlib import Path

import pymupdf
import pytest
from docflow import cli
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.db import DB
from docflow.pipeline import apply, propose, sha256_file, undo

HYDRO = ("Hydro-Québec\nFacture d'électricité du 7 octobre 2025\nNuméro de facture : 123456789\n"
         "Montant de la présente facture 158,98 $")
GOOD = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"


def mkpdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in text.split("\n"):
        page.insert_text((72, y), line, fontname="helv")
        y += 16
    doc.save(path)
    return path


@pytest.fixture
def env(tmp_path):
    cfg = load_config()
    cfg.root = tmp_path
    cfg.settings = {**cfg.settings, "inbox": "inbox", "quarantine": "q", "db": "d.db", "log": "l.log",
                    "library_root": str(tmp_path / "lib")}
    (tmp_path / "inbox").mkdir()
    return cfg, DB(":memory:"), tmp_path


def test_propose_is_read_only_and_auto(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    before = sha256_file(f)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert (p.status, p.final_name) == ("auto", GOOD)
    assert f.exists() and sha256_file(f) == before and not (tmp / "lib").exists()
    assert p.analysis.invoice_number == "123456789"


def test_apply_then_undo_restores_path_and_name(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    sha = sha256_file(f)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    assert dst == tmp / "lib" / "Bills/Hydro-Québec/2025" / GOOD and dst.exists() and not f.exists()
    undo(db)
    assert f.exists() and not dst.exists() and sha256_file(f) == sha
    with pytest.raises(ValueError):
        undo(db)  # already undone


def test_undo_refuses_to_overwrite(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    f.write_text("something else")
    with pytest.raises(FileExistsError):
        undo(db)
    assert f.read_text() == "something else"


def test_undo_refuses_to_restore_a_file_that_is_no_longer_the_one_that_was_filed(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    dst.write_bytes(dst.read_bytes() + b"\n% replaced or corrupted after filing")
    with pytest.raises(ValueError, match="changed"):
        undo(db)
    assert dst.exists() and not f.exists()                          # nothing was moved
    assert db.op(None) is not None                                  # and the operation is still in force, not "undone"


def test_undo_across_volumes_verifies_the_copy_before_deleting_the_filed_document(env, monkeypatch):
    import errno

    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    filed = dst.read_bytes()
    real = pipeline.sha256_file
    cross = lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device"))
    monkeypatch.setattr(pipeline.os, "link", cross)
    monkeypatch.setattr(pipeline.os, "rename", cross)
    monkeypatch.setattr(pipeline, "sha256_file", lambda p: real(p) if Path(p) == dst else "corrupt")   # the restored copy is bad
    with pytest.raises(OSError, match="checksum mismatch"):
        undo(db)
    assert dst.read_bytes() == filed and not f.exists()             # the filed document was never deleted
    assert db.op(None) is not None


def test_a_database_failure_after_the_undo_move_puts_the_document_back(env, monkeypatch):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    monkeypatch.setattr(type(db), "mark_undone", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked")))
    with pytest.raises(RuntimeError):
        undo(db)
    assert dst.exists() and not f.exists()                          # history and disk still agree: still filed


def test_two_identical_files_proposed_together_are_not_both_filed(env):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    b = tmp / "inbox" / "b.pdf"
    b.write_bytes(a.read_bytes())                                  # an exact copy, proposed BEFORE the first one is filed
    pa, pb = (propose(f, cfg, db, RuleBasedAnalyzer(cfg)) for f in (a, b))
    assert pa.status == pb.status == "auto"                       # neither looks like a duplicate yet
    first = apply(pa, cfg, db)
    second = apply(pb, cfg, db)                                    # the database now knows this content
    assert "duplicates" in str(second) and second.exists() and not b.exists()
    assert [p.name for p in (tmp / "lib").rglob("*.pdf")] == [first.name]      # exactly one copy in the library


def test_exact_duplicate_goes_to_quarantine_not_library(env):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    apply(propose(a, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO)
    # PyMuPDF may produce a PDF with different bytes: force exact identity
    lib = next((tmp / "lib").rglob("*.pdf"))
    b.write_bytes(lib.read_bytes())
    p = propose(b, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == "duplicate"
    dst = apply(p, cfg, db)
    assert "duplicates" in str(dst) and len(list((tmp / "lib").rglob("*.pdf"))) == 1


def test_logical_duplicate_blocks_auto(env):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    apply(propose(a, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO + "\nPage 2 de 2 (copie)")
    p = propose(b, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == "logical_duplicate" and "potentially already present" in " ".join(p.notes)


def test_logical_duplicate_is_detected_even_when_the_document_has_no_date(env):
    """An undated document carries the date 'XXXX' (a string, never NULL), so the SQL equality still matches."""
    cfg, db, tmp = env
    undated = "Hydro-Québec\nFacture d'électricité\nNuméro de facture : 123456789\nMontant de la présente facture 158,98 $"
    a = RuleBasedAnalyzer(cfg).analyze(undated)
    assert a.date == "XXXX" and a.invoice_number == "123456789"
    db.add_document(sha256="s1", company=a.company, invoice_number=a.invoice_number, document_date=a.date,
                    amount=str(a.amount), status="classified")
    assert db.find_logical(a.company, a.invoice_number, a.date, a.amount) is not None
    assert db.find_logical(a.company, "OTHER-INVOICE", a.date, a.amount) is None    # and it does not over-match


def test_logical_duplicate_lookup_matches_a_missing_date_and_a_missing_amount(env):
    cfg, db, tmp = env
    db.add_document(sha256="s1", company="A", invoice_number="N1", document_date=None, amount=None, status="classified")
    assert db.find_logical("A", "N1", None, None) is not None            # two absent dates are the same date
    assert db.find_logical("A", "N1", "2025-01-01", None) is None        # but an absent date is not a given one
    db.add_document(sha256="s2", company="A", invoice_number="N2", document_date="2025-01-01", amount="5",
                    status="classified")
    assert db.find_logical("A", "N2", None, "5") is None                 # and the other way round


def test_a_zero_amount_is_an_amount_not_an_absent_one_in_the_logical_duplicate_lookup(env):
    from decimal import Decimal
    cfg, db, tmp = env
    db.add_document(sha256="z1", company="X", invoice_number="A1", document_date="2025-01-01", amount="0.00", status="classified")
    db.add_document(sha256="z2", company="X", invoice_number="B2", document_date="2025-01-01", amount=None, status="classified")
    assert db.find_logical("X", "A1", "2025-01-01", Decimal("0.00")) is not None      # the stored zero IS found (it was "" before)
    assert db.find_logical("X", "A1", "2025-01-01", None) is None                      # but "no amount" is not zero
    assert db.find_logical("X", "B2", "2025-01-01", Decimal("0.00")) is None           # and zero is not "no amount": no false duplicate
    assert db.find_logical("X", "B2", "2025-01-01", None) is not None                  # two absent amounts still match


def test_a_new_row_id_is_always_an_int_and_a_missing_one_is_an_error_not_a_none(env):
    from types import SimpleNamespace

    from docflow.db import _row_id
    cfg, db, tmp = env
    first = db.add_document(sha256="r1", status="classified", company="X")
    op = db.add_op(first, "move", "a", "b")
    assert isinstance(first, int) and isinstance(op, int) and first >= 1 and op >= 1        # the normal case, unchanged
    assert _row_id(SimpleNamespace(lastrowid=7)) == 7
    with pytest.raises(RuntimeError, match="row id"):
        _row_id(SimpleNamespace(lastrowid=None))                                             # what the type said could happen


def test_every_kind_of_unreadable_pdf_is_an_error_proposal_never_a_crash_and_the_cause_is_logged(env, caplog):
    """The catch in propose() is deliberately broad: PDFium may raise classes that are not RuntimeError/ValueError/OSError
    (PdfiumError for a PNG renamed .pdf), and one such file must not stop a whole batch."""
    import logging
    cfg, db, tmp = env
    pngish = tmp / "inbox" / "png.pdf"
    pngish.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    garbage = tmp / "inbox" / "garbage.pdf"
    garbage.write_bytes(b"not a pdf at all")
    empty = tmp / "inbox" / "empty.pdf"
    empty.write_bytes(b"")
    an = RuleBasedAnalyzer(cfg)
    with caplog.at_level(logging.WARNING, logger="docflow"):
        for f in (pngish, garbage, empty):
            p = propose(f, cfg, db, an)
            assert p.status == "error" and p.notes and p.notes[0].startswith("Cannot read file: ")
    causes = [r.getMessage() for r in caplog.records if r.getMessage().startswith("cannot extract")]
    assert len(causes) == 3 and any("png.pdf" in c and "PdfiumError" in c for c in causes)   # name, class AND message kept


def test_engine_timestamps_carry_their_utc_offset_so_the_autumn_hour_is_not_ambiguous():
    from datetime import datetime, timedelta, timezone

    from docflow.db import now
    stamp = now()
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None                    # not a naive local time
    assert abs(parsed - datetime.now(UTC)) < timedelta(seconds=5)                  # and it is NOW
    assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()                    # the local offset, wall-clock kept
    # old rows are naive ("2026-10-04T13:10:36"): both forms still parse, so a mixed history is still readable
    assert datetime.fromisoformat("2026-10-04T13:10:36").tzinfo is None


def test_add_document_only_accepts_the_columns_of_the_table(env):
    cfg, db, tmp = env
    injection = "sha256) VALUES ('x'); DROP TABLE documents; --"
    with pytest.raises(ValueError, match="unknown column"):
        db.add_document(**{injection: "x"})                                     # a key built from outside data
    assert db.c.execute("SELECT count(*) FROM documents").fetchone()[0] == 0   # the table is still there and untouched
    with pytest.raises(ValueError, match="unknown column.*nonexistent"):
        db.add_document(sha256="s", nonexistent="boom")                         # a plain typo: a clear error, not an SQL one
    with pytest.raises(ValueError):
        db.add_document()                                                       # nothing to insert
    doc = db.add_document(sha256="s1", company="A", document_date="2025-01-01", status="classified")
    assert db.c.execute("SELECT company FROM documents WHERE id=?", (doc,)).fetchone()[0] == "A"   # real columns still work


def test_the_history_database_enforces_its_declared_foreign_keys(env):
    import sqlite3
    cfg, db, tmp = env
    assert db.c.execute("PRAGMA foreign_keys").fetchone()[0] == 1               # on for THIS connection (it is per connection)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_op(99999, "move", "/a", "/b")                                    # an operation of a document that does not exist
    doc = db.add_document(sha256="s1", status="classified")
    db.add_op(doc, "move", "/a", "/b")
    with pytest.raises(sqlite3.IntegrityError):
        db.c.execute("DELETE FROM documents WHERE id=?", (doc,))                # a document that still has history
    db.forget_document(doc)                                                     # the supported way removes the history first
    assert db.c.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    assert db.c.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
    db.c.rollback()


def test_a_document_is_undone_only_when_all_its_operations_are(env):
    cfg, db, tmp = env
    doc = db.add_document(sha256="s1", company="A", invoice_number="N1", document_date="2025-01-01",
                          amount="10.00", status="classified")
    first, second = db.add_op(doc, "move", "/a", "/b"), db.add_op(doc, "move", "/b", "/c")
    db.mark_undone(db.op(second))
    assert db.find_sha("s1") is not None                         # one operation is still in force: still filed
    assert db.find_logical("A", "N1", "2025-01-01", "10.00") is not None
    db.mark_undone(db.op(first))
    assert db.find_sha("s1") is None                             # now nothing is left: no longer filed


def test_the_same_operation_cannot_be_marked_undone_twice(env):
    cfg, db, tmp = env
    doc = db.add_document(sha256="s2", status="classified")
    op = db.add_op(doc, "move", "/a", "/b")
    db.mark_undone(db.op(op))
    with pytest.raises(ValueError, match="already undone"):
        db.mark_undone(db.op(op))


def test_name_collision_never_overwrites(env):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    d1 = apply(propose(a, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    d1_bytes = d1.read_bytes()
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO.replace("123456789", "987654321"))
    d2 = apply(propose(b, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db)
    assert d2 != d1 and d2.name.endswith("(2).pdf") and d1.read_bytes() == d1_bytes


def test_unknown_document_stays_manual(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "x.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == "manual"
    with pytest.raises(ValueError):
        apply(p, cfg, db)
    assert f.exists()


@pytest.mark.parametrize("failing", ["add_op", "add_document"])
def test_a_database_failure_after_the_move_puts_the_file_back(env, monkeypatch, failing):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    original = f.read_bytes()
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    monkeypatch.setattr(type(db), failing, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked")))
    with pytest.raises(RuntimeError):
        apply(p, cfg, db)
    assert f.exists() and f.read_bytes() == original                   # back where it was, untouched
    assert not list((tmp / "lib").rglob("*.pdf"))                       # nothing orphaned in the library
    assert db.find_sha(p.sha256) is None                           # and no half-written history row left behind


@pytest.mark.parametrize("failing", ["add_op", "add_document"])
def test_a_database_failure_after_quarantining_a_duplicate_puts_it_back(env, monkeypatch, failing):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    original = f.read_bytes()
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    p.status = "duplicate"
    monkeypatch.setattr(type(db), failing, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked")))
    with pytest.raises(RuntimeError):
        apply(p, cfg, db)
    assert f.exists() and f.read_bytes() == original
    assert not list((tmp / "q").rglob("*.pdf")) and db.find_sha(p.sha256) is None


def test_a_cross_device_move_verifies_the_copy_before_deleting_the_original(env, monkeypatch):
    import errno

    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    original = f.read_bytes()
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    real = pipeline.sha256_file
    monkeypatch.setattr(pipeline.os, "rename", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr(pipeline.os, "link", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr(pipeline, "sha256_file", lambda path: "corrupt" if str(tmp / "lib") in str(path) else real(path))
    with pytest.raises(OSError, match="checksum mismatch"):
        apply(p, cfg, db)
    assert f.exists() and f.read_bytes() == original                   # the ORIGINAL was never deleted
    assert not list((tmp / "lib").rglob("*.pdf"))                       # the bad copy was removed


def test_a_file_changed_after_analysis_is_left_where_it_was(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    f.write_bytes(f.read_bytes() + b"\n% edited after analysis")       # same-filesystem move: checksum no longer matches
    edited = f.read_bytes()
    with pytest.raises(OSError, match="checksum mismatch"):
        apply(p, cfg, db)
    assert f.exists() and f.read_bytes() == edited                     # source restored, not lost
    assert not list((tmp / "lib").rglob("*.pdf")) and db.find_sha(p.sha256) is None


@pytest.mark.parametrize("bad", ["../../escape.pdf", "sub/x.pdf", "..\\x.pdf", "a:b.pdf", "x?.pdf", "..", ".", " . ",
                                 "/etc/escape.pdf", "C:\\escape.pdf", "C:/escape.pdf", "\\\\server\\share\\x.pdf"])
def test_apply_refuses_a_file_name_that_could_leave_the_library(env, bad):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    with pytest.raises(ValueError):
        apply(p, cfg, db, final_name=bad)
    assert f.exists() and not (tmp / "escape.pdf").exists() and not (tmp / "lib").exists()


def test_apply_never_overwrites_a_file_created_after_the_availability_check(env, monkeypatch):
    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    real, calls = pipeline._unique, []

    def racy(dest):                                  # another process takes the name right after it was found free
        chosen = real(dest)
        if not calls:
            chosen.parent.mkdir(parents=True, exist_ok=True)
            chosen.write_bytes(b"someone else's file")
        calls.append(chosen)
        return chosen

    monkeypatch.setattr(pipeline, "_unique", racy)
    dst = apply(p, cfg, db)
    assert calls[0].read_bytes() == b"someone else's file"          # untouched
    assert dst != calls[0] and dst.name.endswith(" (2).pdf") and dst.exists() and not f.exists()


def test_apply_never_overwrites_across_filesystems_either(env, monkeypatch):
    import errno

    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    monkeypatch.setattr(pipeline.os, "rename", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr(pipeline.os, "link", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    real, calls = pipeline._unique, []

    def racy(dest):
        chosen = real(dest)
        if not calls:
            chosen.parent.mkdir(parents=True, exist_ok=True)
            chosen.write_bytes(b"someone else's file")
        calls.append(chosen)
        return chosen

    monkeypatch.setattr(pipeline, "_unique", racy)
    dst = apply(p, cfg, db)
    assert calls[0].read_bytes() == b"someone else's file" and dst != calls[0] and dst.exists() and not f.exists()


def test_apply_accepts_a_normal_hand_typed_name(env):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    dst = apply(propose(f, cfg, db, RuleBasedAnalyzer(cfg)), cfg, db, final_name="2025-10-07 - Hydro  - Mine.pdf")
    assert dst.name == "2025-10-07 - Hydro  - Mine.pdf" and dst.exists()


def test_a_name_that_cannot_be_built_makes_the_document_manual_instead_of_failing_the_whole_scan(env):
    from docflow.analyze import Analysis

    class Emptying:                                       # an analysis whose company is only forbidden characters
        def analyze(self, text):
            return Analysis.model_construct(date="2025-10-07", company="<>:", document_type="Facture", detail="", amount=None,
                                            currency="CAD", invoice_number=None, include_amount=False, check_detail=False,
                                            conf={k: 0.99 for k in ("date", "company", "type", "amount", "detail")}, analyzer="rules")

    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "x.pdf", HYDRO)
    p = propose(f, cfg, db, Emptying())                   # must not raise
    assert p.final_name is None and p.status == "manual"
    assert any("No file name" in n for n in p.notes)


@pytest.mark.parametrize("missing,expected", [(0, "auto"), (1, "confirm")])
def test_an_incomplete_extraction_is_noted_and_never_filed_automatically(env, monkeypatch, missing, expected):
    from docflow import pipeline
    from docflow.extract import Extracted
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    real = pipeline.extract_text
    monkeypatch.setattr(pipeline, "extract_text", lambda *a, **k: Extracted(real(*a, **k).text, "mixed", 3, missing_pages=missing))
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == expected
    assert (f"Incomplete text, pages not read: {missing}" in p.notes) is bool(missing)


def test_a_scan_with_ocr_disabled_says_so_instead_of_blaming_tesseract(env):
    cfg, db, tmp = env
    cfg.settings["ocr"] = {**cfg.settings.get("ocr", {}), "enabled": False}
    doc = pymupdf.open()
    page = doc.new_page()                                                   # an image-only page, no text layer
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 8, 8), False)
    pix.clear_with(255)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    (tmp / "inbox").mkdir(exist_ok=True)
    doc.save(tmp / "inbox" / "scan.pdf")
    p = propose(tmp / "inbox" / "scan.pdf", cfg, db, RuleBasedAnalyzer(cfg))
    assert p.extraction == "ocr_disabled" and p.status == "manual"
    assert "OCR is disabled in the configuration: pages without text were not read." in p.notes
    assert not any("Tesseract" in n for n in p.notes)                       # the cause is the setting, not a missing program


def test_a_local_model_answer_is_never_filed_automatically(env):
    from decimal import Decimal

    from docflow.analyze import Analysis

    class ConfidentLLM:                                   # even a model that claims 90 % sure, with a low threshold
        def analyze(self, text):
            return Analysis(date="2025-10-07", company="Hydro-Quebec", document_type="FactureElectricite",
                            amount=Decimal("1.00"), analyzer="ollama",
                            conf={k: 0.9 for k in ("date", "company", "type", "amount", "detail")})

    cfg, db, tmp = env
    cfg.settings["thresholds"] = {"auto": 0.5, "confirm": 0.3}
    f = mkpdf(tmp / "inbox" / "mystery.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg), fallback=ConfidentLLM())
    assert p.confidence >= 0.5 and p.status == "confirm"
    assert "Analysed by local model (confirmation required)." in p.notes


@pytest.mark.parametrize("error,expected", [
    (ValueError("Ollama HTTP 404: model 'nope' not found"), "Ollama unavailable: HTTP 404: model 'nope' not found"),
    (ValueError("Ollama: no 'response' in its answer"), "Ollama unavailable: no 'response' in its answer"),
    (ConnectionRefusedError("[Errno 111] Connection refused to 127.0.0.1"), "Ollama unavailable: ConnectionRefusedError"),
])
def test_the_note_says_why_the_local_model_was_not_used(env, error, expected):
    class Broken:
        def analyze(self, text):
            raise error

    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "mystery.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg), fallback=Broken())
    assert expected in p.notes and p.status == "manual"        # the document is still handed over for a manual decision


def test_a_failure_of_the_optional_local_model_never_loses_the_rule_based_result_and_is_logged(env, caplog):
    """The model is an optional extra: whatever goes wrong in it (even a class no narrow tuple would list, such as
    http.client.BadStatusLine, which is neither an OSError nor a ValueError) degrades to a note and a log line."""
    import http.client
    import logging
    assert not issubclass(http.client.BadStatusLine, (OSError, ValueError))              # why the catch is broad
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "mystery.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    for error in (http.client.BadStatusLine("garbage"), KeyError("boom"), ConnectionRefusedError("no server")):
        class Broken:
            def analyze(self, text, error=error):
                raise error

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="docflow"):
            p = propose(f, cfg, db, RuleBasedAnalyzer(cfg), fallback=Broken())
        assert p.status == "manual" and p.analysis is not None                           # the rules' answer is kept
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("local model failed")]
        assert len(lines) == 1 and "mystery.pdf" in lines[0] and type(error).__name__ in lines[0]


def test_unreadable_file_is_an_error_not_a_crash(env):
    cfg, db, tmp = env
    gone = tmp / "inbox" / "vanished.pdf"             # deleted (or locked) between the listing and the hash
    p = propose(gone, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == "error" and p.sha256 == ""
    assert p.notes == ["Cannot read file: FileNotFoundError"]


def test_corrupt_pdf_is_error_not_crash(env):
    cfg, db, tmp = env
    f = tmp / "inbox" / "bad.pdf"
    f.write_bytes(b"not a pdf")
    assert propose(f, cfg, db, RuleBasedAnalyzer(cfg)).status == "error"


def test_cli_scan_of_a_missing_or_non_folder_source_fails_loudly(env, capsys):
    cfg, db, tmp = env
    a_file = tmp / "inbox" / "note.txt"
    a_file.write_text("x")
    for source in (tmp / "typo" / "In_Work", a_file):
        assert cli.scan(cfg, db, dry=True, interactive=False, ollama=False, source=source) == 2
        assert "ERROR" in capsys.readouterr().out
    assert cli.scan(cfg, db, dry=True, interactive=False, ollama=False) == 0   # the real (empty) Inbox is fine


@pytest.mark.parametrize("dry", [True, False])
def test_cli_one_file_whose_proposal_fails_does_not_stop_the_batch(env, monkeypatch, capsys, dry):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a-bad.pdf", HYDRO)
    mkpdf(tmp / "inbox" / "b-good.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    real = cli.propose

    def flaky(path, *a, **k):
        if path.name == "a-bad.pdf":
            raise ValueError("boom")
        return real(path, *a, **k)

    monkeypatch.setattr(cli, "propose", flaky)
    rc = cli.scan(cfg, db, dry=dry, interactive=False, ollama=False)
    out = capsys.readouterr().out
    assert rc == 1 and "a-bad.pdf" in out and "boom" in out         # reported and counted as a failure
    assert "b-good.pdf" in out and "2 file(s)" in out and "1 FAILED" in out   # the next file was still handled


def test_cli_failures_are_written_to_the_log_not_only_printed(env, monkeypatch, caplog):
    import logging
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a-apply-fails.pdf", HYDRO)
    (tmp / "inbox" / "b-unreadable.pdf").write_bytes(b"not a pdf")
    mkpdf(tmp / "inbox" / "c-propose-fails.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    real = cli.propose

    def flaky(path, *a, **k):
        if path.name.startswith("c-"):
            raise ValueError("analyser exploded")
        return real(path, *a, **k)

    monkeypatch.setattr(cli, "propose", flaky)
    monkeypatch.setattr(cli, "apply", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with caplog.at_level(logging.INFO):
        assert cli.scan(cfg, db, dry=False, interactive=False, ollama=False) == 1
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("a-apply-fails.pdf" in m and "disk full" in m for m in errors)          # the move that failed
    assert any("b-unreadable.pdf" in m and "Cannot read file" in m for m in errors)    # the file that could not be read
    assert any("c-propose-fails.pdf" in m and "analyser exploded" in m for m in errors)  # the proposal that raised


def _typed(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


@pytest.mark.parametrize("typed,expected", [
    ("Mine", "Mine.pdf"), ("  Mine.pdf  ", "Mine.pdf"), ("Mine.PDF", "Mine.PDF"),
    ("2025-10-07 - Hydro - Mine", "2025-10-07 - Hydro - Mine.pdf"),
])
def test_a_hand_typed_name_gets_its_pdf_extension_when_missing(env, monkeypatch, typed, expected):
    cfg, db, tmp = env
    p = propose(mkpdf(tmp / "inbox" / "x.pdf", HYDRO), cfg, db, RuleBasedAnalyzer(cfg))
    _typed(monkeypatch, "m", typed)
    assert cli.ask(cfg, p) == expected


@pytest.mark.parametrize("bad", ["../../escape", "sub/dir/x", "..\\x", "a:b", "x?", "..", ".", "   ", "/etc/passwd"])
def test_an_invalid_hand_typed_name_is_refused_and_asked_again(env, monkeypatch, capsys, bad):
    cfg, db, tmp = env
    p = propose(mkpdf(tmp / "inbox" / "x.pdf", HYDRO), cfg, db, RuleBasedAnalyzer(cfg))
    _typed(monkeypatch, "m", bad, "m", "Good name", )
    assert cli.ask(cfg, p) == "Good name.pdf"                        # after the refusal, the question is asked again
    if bad.strip():
        assert "Invalid name" in capsys.readouterr().out


def test_approving_without_any_proposed_name_asks_for_one(env, monkeypatch, capsys):
    cfg, db, tmp = env
    p = propose(mkpdf(tmp / "inbox" / "x.pdf", HYDRO), cfg, db, RuleBasedAnalyzer(cfg))
    p.final_name = None
    _typed(monkeypatch, "a", "m", "Chosen")
    assert cli.ask(cfg, p) == "Chosen.pdf"
    assert "no proposed name" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("exc,code", [(EOFError, 1), (KeyboardInterrupt, 130)])
def test_interactive_mode_stops_cleanly_on_eof_or_ctrl_c_and_still_reports(env, monkeypatch, capsys, exc, code):
    cfg, db, tmp = env
    cfg.settings["thresholds"] = {"auto": 0.99, "confirm": 0.5}              # so that both documents need a human
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO.replace("123456789", "999888777"))
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(exc()))
    rc = cli.scan(cfg, db, dry=False, interactive=True, ollama=False)       # no traceback: it returns
    out = capsys.readouterr().out
    assert rc == code
    assert a.exists() and b.exists() and not (tmp / "lib").exists()           # nothing was filed or lost
    assert "2 file(s); 0 processed, 2 pending" in out and "INTERRUPTED" in out    # the batch is still accounted for


@pytest.mark.parametrize("table", [False, True])
def test_the_summary_adds_up_to_the_number_of_files_and_counts_the_skipped_ones(env, monkeypatch, capsys, table):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a-filed.pdf", HYDRO)
    mkpdf(tmp / "inbox" / "b-held.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    mkpdf(tmp / "inbox" / "c-propose-fails.pdf", "Lettre de la tante Huguette, 4 mai 2025")
    (tmp / "inbox" / "d-notes.txt").write_text("not a pdf")
    (tmp / "inbox" / "e-photo.jpg").write_bytes(b"\xff\xd8")
    real = cli.propose
    monkeypatch.setattr(cli, "propose", lambda path, *a, **k: (_ for _ in ()).throw(ValueError("boom"))
                        if path.name.startswith("c-") else real(path, *a, **k))
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False, table=table)
    summary = capsys.readouterr().out.strip().splitlines()[-1]
    # 5 files = 1 processed + 2 pending (held and failed to analyse) + 2 skipped; the failure is counted on top, not instead
    assert summary == "5 file(s); 1 processed, 2 pending, 2 skipped (not PDF), 1 FAILED"


def test_table_mode_is_one_line_per_file_with_the_outcome_as_a_column(env, monkeypatch, capsys):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a-filed.pdf", HYDRO)
    mkpdf(tmp / "inbox" / "b-held.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    (tmp / "inbox" / "c-unreadable.pdf").write_bytes(b"not a pdf")
    mkpdf(tmp / "inbox" / "d-apply-fails.pdf", HYDRO.replace("123456789", "999888777"))
    real = cli.apply

    def apply_or_fail(p, *a, **k):
        if p.source.name.startswith("d-"):
            raise OSError("disk full")
        return real(p, *a, **k)

    monkeypatch.setattr(cli, "apply", apply_or_fail)
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False, table=True)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    files, summary = lines[:-1], lines[-1]
    assert len(files) == 4 and not any(ln.lstrip().startswith("->") for ln in files)   # no interleaved result lines
    by_name = {name: next(ln for ln in files if name in ln) for name in ("a-filed", "b-held", "c-unreadable", "d-apply-fails")}
    assert by_name["a-filed"].endswith(str(tmp / "lib" / "Bills/Hydro-Québec/2025" / GOOD))   # the destination is a column
    assert by_name["b-held"].endswith(f"left in {tmp / 'inbox'} (validation required)")
    assert by_name["d-apply-fails"].endswith("ERROR: disk full")
    assert "Cannot read file" in by_name["c-unreadable"] or "error" in by_name["c-unreadable"]
    assert summary.startswith("4 file(s)") and "FAILED" in summary


def test_cli_says_where_a_held_file_really_is_not_always_the_inbox(env, capsys):
    cfg, db, tmp = env
    other = tmp / "In_Work" / "scans-2019"
    other.mkdir(parents=True)
    mkpdf(other / "unknown.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False, source=tmp / "In_Work", recursive=True)
    out = capsys.readouterr().out
    assert f"left in {other}" in out and "Inbox" not in out                       # the folder it is actually in
    assert (other / "unknown.pdf").exists()


def test_cli_scan_of_a_missing_default_inbox_fails_too(env, capsys):
    cfg, db, tmp = env
    (tmp / "inbox").rmdir()                                                    # e.g. the share is not mounted
    assert cli.scan(cfg, db, dry=True, interactive=False, ollama=False) == 2
    assert "ERROR" in capsys.readouterr().out


@pytest.mark.parametrize("table", [False, True])
def test_a_dry_run_summary_accounts_for_every_file_as_analysed_not_processed(env, capsys, table):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    mkpdf(tmp / "inbox" / "b.pdf", "Lettre de la tante Huguette, 3 mai 2025")
    (tmp / "inbox" / "c-notes.txt").write_text("not a pdf")
    cli.scan(cfg, db, dry=True, interactive=False, ollama=False, table=table)
    summary = capsys.readouterr().out.strip().splitlines()[-1]
    # 3 files = 2 analysed + 1 skipped: nothing was "processed" (nothing moved), and the line must still add up
    assert summary == "3 file(s); 2 analysed, 0 pending, 1 skipped (not PDF) [DRY-RUN: nothing moved]"


def test_cli_dry_run_moves_nothing(env, monkeypatch, capsys):
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    cli.scan(cfg, db, dry=True, interactive=False, ollama=False)
    out = capsys.readouterr().out
    assert GOOD in out and "DRY-RUN" in out and f.exists()
    assert db.c.execute("select count(*) from documents").fetchone()[0] == 0


def test_cli_dry_run_flags_duplicates_inside_the_batch(env, capsys):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    (tmp / "inbox" / "b.pdf").write_bytes(a.read_bytes())
    cli.scan(cfg, db, dry=True, interactive=False, ollama=False, table=True)
    out = capsys.readouterr().out
    assert "auto" in out.split("\n")[0] and "duplicate" in out.split("\n")[1]


def test_ollama_option_misconfiguration_is_a_clear_message_not_a_traceback(env, capsys):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "ok.pdf", HYDRO)
    cfg.settings["ollama"] = {}                                                    # no model configured
    assert cli.scan(cfg, db, dry=True, interactive=False, ollama=True) == 2
    assert "ollama.model" in capsys.readouterr().out
    cfg.settings["ollama"] = {"model": "m", "host": "http://192.0.2.5:11434"}    # a remote host: refused, nothing sent
    assert cli.scan(cfg, db, dry=True, interactive=False, ollama=True) == 2
    assert "localhost" in capsys.readouterr().out
    assert (tmp / "inbox" / "ok.pdf").exists()


def test_scan_exit_code_tells_a_cron_whether_anything_failed(env, monkeypatch):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "ok.pdf", HYDRO)
    assert cli.scan(cfg, db, dry=False, interactive=False, ollama=False) == 0     # a clean run
    (tmp / "inbox" / "bad.pdf").write_bytes(b"not a pdf")
    assert cli.scan(cfg, db, dry=True, interactive=False, ollama=False) == 1      # an unreadable file, even in a dry run
    (tmp / "inbox" / "bad.pdf").unlink()
    mkpdf(tmp / "inbox" / "again.pdf", HYDRO.replace("123456789", "999888777"))
    monkeypatch.setattr(cli, "apply", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert cli.scan(cfg, db, dry=False, interactive=False, ollama=False) == 1     # a move that failed


def test_cli_scan_applies_auto_and_holds_the_rest(env, capsys):
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "ok.pdf", HYDRO)
    mkpdf(tmp / "inbox" / "unknown.pdf", "Lettre quelconque")
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False)
    assert (tmp / "inbox" / "unknown.pdf").exists() and not (tmp / "inbox" / "ok.pdf").exists()


def test_the_usage_line_of_the_cli_lists_every_option_the_parser_accepts(capsys):
    """The module docstring is the maintainer's summary: it must not drift from the argparse definitions."""
    import re

    def options(argv):
        with pytest.raises(SystemExit):
            cli.main(argv + ["--help"])
        return set(re.findall(r"(?<![\w-])(--?[a-zA-Z][\w-]*)", capsys.readouterr().out.split("options:")[1])) - {"-h", "--help"}

    parsed = options([]) | options(["scan"])
    assert {"--config", "--sandbox", "--dry-run", "--interactive", "--ollama", "--source", "--recursive", "--table"} <= parsed
    for opt in parsed:
        assert opt in cli.__doc__, f"{opt} is accepted by the parser but missing from the usage line"
    for command in ("scan", "undo", "history"):
        assert command in cli.__doc__


def test_a_cross_device_copy_that_fails_midway_leaves_no_partial_file_in_the_library(env, monkeypatch):
    # DOC474.39: a full disk or a dropped share after the copy started must not leave a truncated file in the library
    import errno
    import shutil

    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    original = f.read_bytes()
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    monkeypatch.setattr(pipeline.os, "rename", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr(pipeline.os, "link", lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))

    def half_then_fail(fin, fout, *a, **k):
        fout.write(fin.read(100))  # a truncated copy is already on disk
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(shutil, "copyfileobj", half_then_fail)
    with pytest.raises(OSError, match="No space left"):
        apply(p, cfg, db)
    assert f.exists() and f.read_bytes() == original            # the ORIGINAL is untouched
    assert not [x for x in (tmp / "lib").rglob("*") if x.is_file()]  # and no partial copy was left behind


def test_a_retry_after_a_failed_cross_device_copy_gets_the_wanted_name_not_a_suffix(env, monkeypatch):
    # DOC474.218: the truncated leftover used to be taken for a legitimate collision, so the retry was filed as "(2)"
    import errno
    import shutil

    from docflow import pipeline
    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "invoice.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    cross = lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device"))  # noqa: E731
    monkeypatch.setattr(pipeline.os, "rename", cross)
    monkeypatch.setattr(pipeline.os, "link", cross)
    real = shutil.copyfileobj

    def half_then_fail(fin, fout, *a, **k):
        fout.write(fin.read(100))
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(shutil, "copyfileobj", half_then_fail)
    with pytest.raises(OSError):
        apply(p, cfg, db)
    monkeypatch.setattr(shutil, "copyfileobj", real)  # the share is back
    dst = apply(p, cfg, db)
    assert "(2)" not in dst.name and dst.exists() and sha256_file(dst) == p.sha256
    assert not f.exists()


def test_table_plus_interactive_shows_the_proposal_before_asking_to_approve_it(env, monkeypatch, capsys):
    # DOC474.43: --table hid the detail block, so the user was asked "[A]pprove ?" about a name and a folder never shown
    cfg, db, tmp = env
    cfg.settings["thresholds"] = {"auto": 0.99, "confirm": 0.5}              # a human has to decide
    mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    on_screen = []

    def answer(prompt=""):
        on_screen.append(capsys.readouterr().out)                            # everything printed up to the question
        return "i"
    monkeypatch.setattr("builtins.input", answer)
    cli.scan(cfg, db, dry=False, interactive=True, ollama=False, table=True)
    assert on_screen and "Proposed name:" in on_screen[0] and "Destination:" in on_screen[0]


def test_the_local_model_fills_in_the_company_but_does_not_erase_what_the_rules_found(env):
    # DOC474.149: the rules had the date and the amount, the model only the company and the type: its answer replaced all
    from decimal import Decimal

    from docflow.analyze import Analysis

    class PartialLLM:
        def __init__(self, date="XXXX"):
            self.date = date

        def analyze(self, text):
            return Analysis(date=self.date, company="Voisin", document_type="Lettre", analyzer="ollama")

    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "mystery.pdf", "Voisin Inc.\nFacture numero : 4455\nDate: 5 mars 2025\nTotal 80,00 $\n")
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg), fallback=PartialLLM())
    assert (p.analysis.company, p.analysis.document_type) == ("Voisin", "Lettre")      # what the model gave
    assert p.analysis.date == "2025-03-05" and p.analysis.amount == Decimal("80.00")   # what the rules had and it did not
    assert p.final_name and "2025-03-05" in p.final_name and p.status != "auto"          # the name uses both; still never auto
    q = propose(mkpdf(tmp / "inbox" / "mystery2.pdf", "Voisin Inc.\nDate: 5 mars 2025\nTotal 80,00 $\nautre"),
                cfg, db, RuleBasedAnalyzer(cfg), fallback=PartialLLM(date="2025-03-06"))
    assert q.analysis.date == "2025-03-06"                                            # a date the model DID give wins


def test_apply_refuses_an_uncertain_proposal_until_a_human_has_confirmed_it(env):
    # DOC474.150: "confirm", "manual" and "logical_duplicate" proposals were moved as soon as they had a name and a folder
    cfg, db, tmp = env
    cfg.settings["thresholds"] = {"auto": 0.99, "confirm": 0.5}                  # HYDRO is only "confirm" now
    f = mkpdf(tmp / "inbox" / "hydro.pdf", HYDRO)
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert p.status == "confirm"
    for status in ("confirm", "manual", "logical_duplicate"):
        p.status = status
        with pytest.raises(ValueError, match="confirmation"):
            apply(p, cfg, db)
        assert f.exists()                                                      # nothing moved
    p.status = "confirm"
    assert apply(p, cfg, db, confirmed=True).exists() and not f.exists()       # the click / the [A]pprove answer


def test_without_hard_links_the_destination_name_is_reserved_before_the_move(tmp_path, monkeypatch):
    # DOC474.152: the fallback checked exists() and then renamed; a file created in between was overwritten silently
    import errno

    from docflow import pipeline
    src, dst = tmp_path / "a.pdf", tmp_path / "lib" / "b.pdf"
    dst.parent.mkdir()
    src.write_bytes(b"new")
    monkeypatch.setattr(pipeline.os, "link", lambda *a: (_ for _ in ()).throw(OSError(errno.EPERM, "no hard links here")))
    real_rename, seen = pipeline.os.rename, []

    def spy(a, b):
        seen.append(Path(b).exists())                       # is the name already ours when the move happens?
        return real_rename(a, b)
    monkeypatch.setattr(pipeline.os, "rename", spy)
    pipeline._link_or_rename(src, dst)
    assert seen == [True] and dst.read_bytes() == b"new" and not src.exists()


def test_without_hard_links_an_existing_destination_is_never_replaced_and_a_failed_move_leaves_no_placeholder(tmp_path, monkeypatch):
    import errno

    from docflow import pipeline
    src, dst = tmp_path / "a.pdf", tmp_path / "b.pdf"
    src.write_bytes(b"new")
    dst.write_bytes(b"someone else's")
    monkeypatch.setattr(pipeline.os, "link", lambda *a: (_ for _ in ()).throw(OSError(errno.EPERM, "no hard links here")))
    with pytest.raises(FileExistsError):
        pipeline._link_or_rename(src, dst)
    assert dst.read_bytes() == b"someone else's" and src.exists()
    free = tmp_path / "free.pdf"
    monkeypatch.setattr(pipeline.os, "rename", lambda *a: (_ for _ in ()).throw(OSError(errno.EIO, "share dropped")))
    with pytest.raises(OSError, match="share dropped"):
        pipeline._link_or_rename(src, free)
    assert not free.exists() and src.exists()               # our empty placeholder was removed again


def test_a_sandbox_scan_refuses_a_source_outside_the_sandbox_unless_it_is_a_dry_run(tmp_path, capsys):
    # DOC474.158: --sandbox promises the real files are untouched, but --source made it MOVE the files of any folder
    sb, real = tmp_path / "sb", tmp_path / "real"
    real.mkdir()
    f = mkpdf(real / "hydro.pdf", HYDRO)
    with pytest.raises(SystemExit) as refused:
        cli.main(["--sandbox", str(sb), "scan", "--source", str(real)])
    assert refused.value.code == 2 and f.exists() and not sb.exists()          # nothing moved, nothing even created
    assert "--dry-run" in capsys.readouterr().err
    assert cli.main(["--sandbox", str(sb), "scan", "--source", str(real), "--dry-run"]) == 0 and f.exists()   # looking is fine
    inside = sb / "inbox"
    g = mkpdf(inside / "hydro2.pdf", HYDRO.replace("123456789", "5550001"))
    assert cli.main(["--sandbox", str(sb), "scan", "--source", str(inside)]) == 0     # a source inside the sandbox is allowed...
    assert not g.exists() and list((sb / "library").rglob("*.pdf"))                    # ...and files into the SANDBOX library


def test_the_same_content_cannot_be_filed_twice_even_by_two_scans_racing(tmp_path):
    # DOC474.170: both scans saw "sha not filed" and both inserted; the database itself now refuses the second
    db = DB(tmp_path / "h.db")
    db.add_document(sha256="abc", status="classified", original_filename="a.pdf")
    with pytest.raises(ValueError, match="already filed"):
        db.add_document(sha256="abc", status="classified", original_filename="b.pdf")
    db.add_document(sha256="abc", status="duplicate", original_filename="c.pdf")      # quarantined copies are not constrained
    db.add_document(sha256="def", status="classified", original_filename="d.pdf")     # other content is fine
    assert db.c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3


def test_a_database_that_already_holds_duplicates_still_opens(tmp_path):
    import sqlite3

    from docflow.db import SCHEMA
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA)                                                          # the schema as it was, no unique index
    raw.executemany("INSERT INTO documents (sha256, status) VALUES (?, 'classified')", [("same",), ("same",)])
    raw.commit()
    raw.close()
    db = DB(path)                                                                       # must not raise: the guard is just not installed
    assert db.c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2


def test_a_company_the_rules_found_survives_a_model_answer_that_only_gives_the_type(env):
    # DOC474.40: rules had the company but not the type; the model answered the type only and the company was lost ("manual", no name)
    from docflow.analyze import Analysis

    class TypeOnlyLLM:
        def analyze(self, text):
            return Analysis(date="XXXX", company=None, document_type="Lettre", analyzer="ollama")

    cfg, db, tmp = env
    f = mkpdf(tmp / "inbox" / "hydro-letter.pdf", "Hydro-Quebec\nObjet : renseignements sur votre compte\n3 mai 2025\n")
    rules_only = propose(f, cfg, db, RuleBasedAnalyzer(cfg))
    assert rules_only.analysis.company == "Hydro-Quebec" and not rules_only.analysis.document_type    # the situation of the finding
    p = propose(f, cfg, db, RuleBasedAnalyzer(cfg), fallback=TypeOnlyLLM())
    assert (p.analysis.company, p.analysis.document_type) == ("Hydro-Quebec", "Lettre")     # both kept
    assert p.final_name and "Hydro-Quebec" in p.final_name and "Lettre" in p.final_name


def test_ctrl_c_while_a_file_is_being_analysed_stops_cleanly_with_the_summary(env, monkeypatch, capsys):
    # DOC474.44: only an interruption inside the interactive question was handled; elsewhere a traceback and no count
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO.replace("123456789", "999888777"))
    c = mkpdf(tmp / "inbox" / "c.pdf", HYDRO.replace("123456789", "555444333"))
    real, calls = cli.propose, []

    def propose_then_interrupt(path, *args, **kwargs):
        calls.append(path.name)
        if path.name == "b.pdf":
            raise KeyboardInterrupt
        return real(path, *args, **kwargs)
    monkeypatch.setattr(cli, "propose", propose_then_interrupt)
    rc = cli.scan(cfg, db, dry=False, interactive=False, ollama=False)               # no traceback: it returns
    out = capsys.readouterr().out
    assert rc == 130 and "INTERRUPTED" in out
    assert not a.exists() and b.exists() and c.exists()                               # a was filed; b and c stay where they are
    assert "3 file(s); 1 processed, 2 pending" in out and calls == ["a.pdf", "b.pdf"]  # and the batch is still accounted for


def test_ctrl_c_while_a_file_is_being_moved_stops_cleanly_and_says_it_may_already_be_filed(env, monkeypatch, capsys):
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO.replace("123456789", "999888777"))
    monkeypatch.setattr(cli, "apply", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    rc = cli.scan(cfg, db, dry=False, interactive=False, ollama=False)
    out = capsys.readouterr().out
    assert rc == 130 and "INTERRUPTED" in out and "may already be filed" in out and "docflow history" in out
    assert a.exists() and b.exists() and "2 file(s); 0 processed, 2 pending" in out


def test_a_database_error_while_filing_one_file_does_not_stop_the_batch(env, monkeypatch, capsys):
    # DOC474.45: only OSError and ValueError were caught around apply(); a sqlite3 error ended the scan without a summary
    import sqlite3
    cfg, db, tmp = env
    a = mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    b = mkpdf(tmp / "inbox" / "b.pdf", HYDRO.replace("123456789", "999888777"))
    real = cli.apply

    def locked_for_a(p, *args, **kwargs):
        if p.source.name == "a.pdf":
            raise sqlite3.OperationalError("database is locked")
        return real(p, *args, **kwargs)
    monkeypatch.setattr(cli, "apply", locked_for_a)
    rc = cli.scan(cfg, db, dry=False, interactive=False, ollama=False)
    out = capsys.readouterr().out
    assert rc == 1 and "1 FAILED" in out and "2 file(s); 1 processed, 1 pending" in out    # the summary is printed, rc says it failed
    assert a.exists() and not b.exists()                                                      # a stays, b was filed
    assert "database is locked" in out                                                         # and the cause is shown


@pytest.mark.parametrize("table", [False, True])
def test_an_unreadable_file_is_reported_as_unreadable_not_as_waiting_for_validation(env, capsys, table):
    # DOC474.46: a PDF in error went through the "validation required" branch and the user looked for something to validate
    cfg, db, tmp = env
    (tmp / "inbox" / "broken.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)     # not a PDF: extraction fails
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False, table=table)
    out = capsys.readouterr().out
    assert "validation required" not in out and "unreadable" in out and "Cannot read file" in out


def test_every_command_line_option_and_command_explains_itself(capsys):
    # DOC474.47: --dry-run, --interactive, -r, the undo id and the sub-commands showed no help text
    import argparse
    parser = cli.build_parser()
    commands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    missing = []
    for action in parser._actions + [a for sub in commands.choices.values() for a in sub._actions]:
        if not action.help and not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            missing.append(action.dest)
    assert not missing, f"no help text for: {missing}"
    assert all(choice.help for choice in commands._choices_actions) and len(commands._choices_actions) == 3   # scan, undo, history


def test_the_operations_of_a_document_are_found_through_an_index(tmp_path):
    # DOC474.69: mark_undone, forget_document and the foreign-key check on documents scanned the whole operations table
    db = DB(tmp_path / "h.db")
    for q in ("SELECT 1 FROM operations WHERE document_id=? AND undone=0", "DELETE FROM operations WHERE document_id=?"):
        plan = " ".join(r[3] for r in db.c.execute(f"EXPLAIN QUERY PLAN {q}", (1,)))
        assert "USING INDEX ix_op_doc" in plan or "USING COVERING INDEX ix_op_doc" in plan, (q, plan)
    old = tmp_path / "old.db"                                                           # a history made before the index existed
    import sqlite3
    raw = sqlite3.connect(old)
    from docflow.db import SCHEMA
    raw.executescript("\n".join(line for line in SCHEMA.splitlines() if "ix_op_doc" not in line and "ix_doc_logical" not in line))
    assert not raw.execute("SELECT name FROM sqlite_master WHERE name IN ('ix_op_doc', 'ix_doc_logical')").fetchall()
    raw.close()
    assert DB(old).c.execute("SELECT name FROM sqlite_master WHERE name='ix_op_doc'").fetchone()   # an existing database gets it too


def test_the_logical_duplicate_lookup_uses_an_index(tmp_path):
    # DOC474.70: every analysed document ran find_logical, which scanned the whole documents table
    db = DB(tmp_path / "h.db")
    plan = " ".join(r[3] for r in db.c.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM documents WHERE status='classified' AND company=? AND invoice_number=? "
        "AND document_date IS ? AND amount IS ?", ("Hydro-Quebec", "123", "2025-10-07", "158.98")))
    assert "USING INDEX ix_doc_logical" in plan, plan
    db.add_document(sha256="a", status="classified", company="Hydro-Quebec", invoice_number="123", document_date="2025-10-07", amount="158.98")
    assert db.find_logical("Hydro-Quebec", "123", "2025-10-07", "158.98") is not None            # and it still finds it
    assert db.find_logical("Hydro-Quebec", "124", "2025-10-07", "158.98") is None


def test_a_history_connection_can_be_closed_deterministically(tmp_path):
    # DOC474.71: DB had no close() nor context manager; connections lived until the garbage collector reached them
    import sqlite3
    with DB(tmp_path / "h.db") as db:
        db.add_document(sha256="a", status="classified")
        assert db.find_sha("a")
    with pytest.raises(sqlite3.ProgrammingError):                          # closed on leaving the block
        db.c.execute("SELECT 1")
    again = DB(tmp_path / "h.db")
    again.close()
    again.close()                                                          # closing twice is harmless
    assert DB(tmp_path / "h.db").find_sha("a")                             # and nothing was lost



def test_table_mode_has_the_same_columns_in_a_dry_run_as_in_a_real_run(env, capsys):
    # DOC474.159: a dry-run row stopped before the outcome column that every real-run row ends with
    cfg, db, tmp = env
    mkpdf(tmp / "inbox" / "a.pdf", HYDRO)
    cli.scan(cfg, db, dry=True, interactive=False, ollama=False, table=True)
    dry = [line for line in capsys.readouterr().out.splitlines() if " | a.pdf" in line]
    assert len(dry) == 1 and dry[0].endswith("| dry-run (nothing moved)"), dry
    cli.scan(cfg, db, dry=False, interactive=False, ollama=False, table=True)
    real = [line for line in capsys.readouterr().out.splitlines() if " | a.pdf" in line]
    assert len(real) == 1 and dry[0].count(" | ") == real[0].count(" | ")                    # one column more in both: the outcome


def test_the_missing_tesseract_note_reads_naturally_and_old_stored_notes_stay_translatable(env, monkeypatch):
    # DOC474.198: "Image page and Tesseract not found" read as a broken noun phrase
    from docflow import extract
    cfg, db, tmp = env
    monkeypatch.setattr(extract.shutil, "which", lambda *a, **k: None)                 # no Tesseract on this machine
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 8, 8), False)
    pix.clear_with(255)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    (tmp / "inbox").mkdir(exist_ok=True)
    doc.save(tmp / "inbox" / "scan.pdf")
    p = propose(tmp / "inbox" / "scan.pdf", cfg, db, RuleBasedAnalyzer(cfg))
    assert "This page is an image and Tesseract was not found: OCR is unavailable." in p.notes
    assert not any(n.startswith("Image page and") for n in p.notes)
    table = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    fr = table[table.index("const frMessages"):]
    assert "'This page is an image and Tesseract was not found: OCR is unavailable.'" in fr     # the new text is translated...
    assert "'Image page and Tesseract not found: OCR unavailable.'" in fr                       # ...and so are the notes already stored


def test_a_source_that_cannot_be_removed_after_the_hard_link_leaves_one_copy_not_two(tmp_path, monkeypatch):
    # DOC474.219: the link was made, unlink(src) failed: dst stayed in the library with no history row, and src was filed again
    import errno

    from docflow import pipeline
    src, dst = tmp_path / "a.pdf", tmp_path / "b.pdf"
    src.write_bytes(b"x")
    real_unlink = pipeline.os.unlink

    def unlink(p, *a, **k):
        if Path(p) == src:                                  # only the source is protected; withdrawing OUR link must work
            raise OSError(errno.EACCES, "read-only share")
        return real_unlink(p, *a, **k)
    monkeypatch.setattr(pipeline.os, "unlink", unlink)
    with pytest.raises(OSError, match="read-only share"):
        pipeline._link_or_rename(src, dst)
    assert src.read_bytes() == b"x" and not dst.exists()    # the link we made was withdrawn: the file is where it was


def test_an_answer_that_is_not_a_m_or_i_is_told_so_and_the_question_is_asked_again(monkeypatch, capsys):
    # DOC474.49: any other key was swallowed and the same question came back without a word
    from docflow import cli
    answers = iter(["x", "", "I"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.ask(None, None) is None                      # "I" ends it; neither the config nor the proposal is read before that
    out = capsys.readouterr().out
    assert out.count("Please answer A, M or I") == 2        # once for "x", once for the empty answer


def test_a_model_answer_that_contradicts_the_confident_reading_of_the_rules_is_flagged_not_trusted():
    # DOC474.155: a document can carry text meant to steer the model; where the rules read the date or the amount with
    # confidence and the model says something else, the model's value is kept for the person to see but scored 0 and said aloud
    from decimal import Decimal

    from docflow.analyze import Analysis
    from docflow.pipeline import _fill_gaps
    rules = Analysis(date="2025-03-05", amount=Decimal("55.00"), company="A", document_type="T",
                     conf={"date": 1.0, "amount": 0.95})
    model = Analysis(date="2025-01-02", amount=Decimal("5500.00"), company="A", document_type="T",
                     conf={"date": 0.9, "amount": 0.9})
    notes = _fill_gaps(model, rules)
    assert model.date == "2025-01-02" and model.amount == Decimal("5500.00")          # the model's answer is not overridden
    assert model.conf["date"] == 0.0 and model.conf["amount"] == 0.0                  # ...but a human must check both
    assert notes == ["The model and the rules read a different date (model / rules): 2025-01-02 / 2025-03-05",
                     "The model and the rules read a different amount (model / rules): 5500.00 / 55.00"]


def test_agreement_or_an_unsure_reading_of_the_rules_raises_no_flag():
    from decimal import Decimal

    from docflow.analyze import Analysis
    from docflow.pipeline import _fill_gaps
    same = Analysis(date="2025-03-05", amount=Decimal("55.00"), conf={"date": 0.9, "amount": 0.9})
    assert _fill_gaps(same.model_copy(deep=True), Analysis(date="2025-03-05", amount=Decimal("55.00"), conf={"date": 1.0, "amount": 0.95})) == []
    unsure = Analysis(date="2025-03-05", amount=Decimal("55.00"), conf={"date": 0.4, "amount": 0.5})   # e.g. a due date, a guess
    other = Analysis(date="2025-01-02", amount=Decimal("5500.00"), conf={"date": 0.9, "amount": 0.9})
    assert _fill_gaps(other, unsure) == [] and other.conf["date"] == 0.9
