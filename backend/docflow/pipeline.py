"""Pipeline: detect -> SHA-256 -> duplicate -> extract -> analyse -> name -> route -> score.
`propose` touches nothing; `apply` and `undo` are the only functions that move files."""
import errno
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .analyze import Analysis, DocumentAnalyzer
from .config import Config
from .db import DB, now
from .extract import extract_text
from .fields import header_line
from .naming import FORBIDDEN, build_filename
from .routing import fill, route, safe_join, type_destination_unusable, unknown_placeholder

log = logging.getLogger("docflow")
MAX_PATH = 240  # margin under Windows' 260-character limit


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Proposal:
    source: Path
    sha256: str
    status: str = "manual"   # auto | confirm | manual | duplicate | logical_duplicate | error
    analysis: Analysis | None = None
    final_name: str | None = None
    rel_dir: str | None = None
    confidence: float = 0.0
    extraction: str = ""
    header: str = ""   # first line of the (normalised) text: used to learn a company after a correction
    text: str = ""     # the whole extracted text: kept (locally) by the web interface so the filed archive can be searched
    notes: list[str] = field(default_factory=list)


def propose(path: Path, cfg: Config, db: DB, analyzer: DocumentAnalyzer, fallback: DocumentAnalyzer | None = None,
            sha: str | None = None) -> Proposal:
    """`sha`: the content hash when the caller has just computed it (a big file is not read twice). apply() re-checks it."""
    try:
        sha = sha or sha256_file(path)
    except OSError as e:  # locked, unreadable or deleted during the scan: never crash the whole batch
        return Proposal(path, "", status="error", notes=[f"Cannot read file: {type(e).__name__}"])
    p = Proposal(path, sha)
    if db.find_sha(p.sha256):
        p.status = "duplicate"
        p.notes.append("Identical document already filed (SHA-256).")
        return p
    try:
        ex = extract_text(path, cfg.settings.get("ocr"))
    except Exception as e:  # deliberately broad: PDFium raises its own PdfiumError for a PNG renamed .pdf, and ONE unreadable
        # file must never stop the batch. The cause is logged, not lost.
        log.warning("cannot extract %s: %s: %s", path.name, type(e).__name__, e)
        p.status = "error"
        p.notes.append(f"Cannot read file: {type(e).__name__}")
        return p
    p.extraction = ex.method
    p.header = header_line(ex.text)
    p.text = ex.text
    if ex.method == "ocr_unavailable":
        p.notes.append("This page is an image and Tesseract was not found: OCR is unavailable.")
    elif ex.method == "ocr_disabled":  # a configuration choice, not a missing program: say which
        p.notes.append("OCR is disabled in the configuration: pages without text were not read.")
    elif ex.missing_pages:  # some pages were read, others were not: say so, the analysis below sees only part of the document
        p.notes.append(f"Incomplete text, pages not read: {ex.missing_pages}")  # prefix + number: translated by prefix
    a = analyzer.analyze(ex.text)
    used_llm = False
    if fallback and (not a.company or not a.document_type) and ex.text.strip():
        try:
            rules, a = a, fallback.analyze(ex.text)
            disagreements = _fill_gaps(a, rules)
            used_llm = True
            p.notes.append("Analysed by local model (confirmation required).")
            p.notes.extend(disagreements)
        except Exception as e:  # deliberately broad: the model is an optional extra, so ANY failure in it (http.client raises
            # classes that are neither OSError nor ValueError) must leave the rules' answer intact; the cause is logged
            log.warning("local model failed for %s: %s: %s", path.name, type(e).__name__, e)
            # our own ValueErrors say what Ollama replied; anything else (network...) is shown by its type only
            why = " ".join(str(e).removeprefix("Ollama: ").removeprefix("Ollama ").split())[:200] \
                if isinstance(e, ValueError) else type(e).__name__
            p.notes.append(f"Ollama unavailable: {why}")
    p.analysis = a
    if a.company and a.document_type:
        try:
            p.final_name = build_filename(a.date, a.company, a.document_type, a.detail,
                                          a.amount if a.include_amount else None, a.currency, path.suffix.lower())
        except ValueError as e:  # one document whose name cannot be built must not fail the whole batch: a human names it
            log.warning("no file name for %s: %s", path.name, e)
            p.notes.append("No file name could be built: the company or the type is empty once cleaned.")
    p.rel_dir, dest_conf, notes = resolve_destination(cfg, a)
    p.notes += notes
    a.conf["destination"] = dest_conf
    p.confidence = min(a.confidence, dest_conf)
    if db.find_logical(a.company, a.invoice_number, a.date, a.amount):
        p.status = "logical_duplicate"
        p.notes.append("Document potentially already present.")
        return p
    p.status = status_for(p.confidence, cfg.settings["thresholds"], used_llm=used_llm, has_name=bool(p.final_name),
                          incomplete=bool(ex.missing_pages))
    return p


RULES_SURE = 0.8  # a reading of the rules at least this sure is what a contradicting answer of the model is compared with


def _fill_gaps(model: Analysis, rules: Analysis) -> list[str]:
    """The model is asked because the rules found no company OR no type; what the rules DID find (company, type, date, amount,
    invoice number, detail) and the model left out is kept, with the rules' confidence. A field the model gave is never overridden. The
    status stays "confirm" at best: the caller marks the answer as coming from the model.
    Returns the notes for what the model CONTRADICTS: a date or an amount that the rules read with confidence and the model reads
    differently (a document can carry text meant to steer the model) keeps the model's value but is scored 0, so a person checks it."""
    notes: list[str] = []
    if model.date != "XXXX" and rules.date != "XXXX" and model.date != rules.date and rules.conf.get("date", 0.0) >= RULES_SURE:
        notes.append(f"The model and the rules read a different date (model / rules): {model.date} / {rules.date}")
        model.conf["date"] = 0.0
    if (model.amount is not None and rules.amount is not None and model.amount != rules.amount
            and rules.conf.get("amount", 0.0) >= RULES_SURE):
        notes.append(f"The model and the rules read a different amount (model / rules): {model.amount} / {rules.amount}")
        model.conf["amount"] = 0.0
    if not model.company and rules.company:
        model.company, model.conf["company"] = rules.company, rules.conf.get("company", 0.0)
    if not model.document_type and rules.document_type:
        model.document_type, model.conf["type"] = rules.document_type, rules.conf.get("type", 0.0)
    if model.date == "XXXX" and rules.date != "XXXX":
        model.date, model.conf["date"] = rules.date, rules.conf.get("date", 0.0)
    if model.amount is None and rules.amount is not None:
        model.amount, model.currency, model.conf["amount"] = rules.amount, rules.currency, rules.conf.get("amount", 0.0)
    if not model.invoice_number and rules.invoice_number:
        model.invoice_number = rules.invoice_number
    if not model.detail and rules.detail:
        model.detail, model.conf["detail"] = rules.detail, rules.conf.get("detail", 0.0)
    return notes


DESTINATION_CONF = 0.96  # a destination that comes from a rule: sure enough for "auto", never above the other fields


def resolve_destination(cfg: Config, a: Analysis) -> tuple[str | None, float, list[str]]:
    """(folder relative to the library, confidence, notes). THE rule for where a document goes and how sure that is:
    the engine and the benchmark that measures it both call this, so they cannot drift apart."""
    notes: list[str] = []
    rel = route(cfg.routing, a.company, a.document_type)
    year_unknown = False
    if rel:
        wrong = unknown_placeholder(rel)
        rel = fill(rel, a.date)
        if rel is None:
            year_unknown = True  # (no second "No destination rule." note: this one already says why)
            notes.append(f"The destination uses a placeholder that does not exist: {wrong}" if wrong
                         else "Year-based destination, but the document date is unknown.")
    if rel:
        try:
            safe_join(cfg.path("library_root"), rel)
            return rel, DESTINATION_CONF, notes
        except ValueError as e:
            notes.append(str(e))
    elif not year_unknown:
        if type_destination_unusable(cfg.routing, a.company, a.document_type):
            notes.append("The destination configured for this type is not usable.")  # a mistake in routing_rules.yaml, not 'no rule'
        else:
            notes.append("No destination rule.")
    return None, 0.0, notes


def status_for(confidence: float, thresholds: dict, *, used_llm: bool = False, has_name: bool = True,
               incomplete: bool = False) -> str:
    """THE rule turning a confidence into auto / confirm / manual, from the configured thresholds."""
    status = "auto" if confidence >= thresholds["auto"] else "confirm" if confidence >= thresholds["confirm"] else "manual"
    if (used_llm or incomplete) and status == "auto":
        status = "confirm"  # a model's answer, or text with unreadable pages, is never filed without a human
    return "manual" if not has_name else status


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    for i in range(2, 1000):
        c = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not c.exists():
            return c
    raise FileExistsError(dest)


def _move_verified(src: Path, dst: Path, sha: str) -> None:
    """Same filesystem: atomic rename. Across filesystems (the NAS): copy, VERIFY, and only then delete the original.
    On any mismatch the original is left (or put back) untouched."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        _link_or_rename(src, dst)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        with open(src, "rb") as fin, open(dst, "xb") as fout:   # "x": raises FileExistsError instead of replacing
            # From here `dst` is OUR file ("x" refused an existing one): whatever fails, no partial copy stays in the library
            try:
                shutil.copyfileobj(fin, fout)
            except BaseException:
                dst.unlink(missing_ok=True)
                raise
        try:
            shutil.copystat(src, dst)
            if sha256_file(dst) != sha:
                raise OSError(f"checksum mismatch after copy: {dst}") from None
        except BaseException:
            dst.unlink(missing_ok=True)
            raise
        src.unlink()
        return
    if sha256_file(dst) != sha:  # the file changed after it was analysed: undo the move
        os.rename(dst, src)
        raise OSError(f"checksum mismatch after move: {dst}")


def _link_or_rename(src: Path, dst: Path) -> None:
    """Move without ever replacing: a hard link fails if `dst` exists (rename would silently overwrite it on POSIX).
    Where hard links are unsupported (some network shares), fall back to a checked rename."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno == errno.EXDEV:
            raise
        # No hard links here (some network shares). rename() would replace a file that appears after an exists() check, so
        # reserve the name EXCLUSIVELY first (FileExistsError if anyone has it), then move over our own empty placeholder.
        os.close(os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        try:
            os.rename(src, dst)
        except BaseException:
            Path(dst).unlink(missing_ok=True)  # the placeholder is ours and empty
            raise
        return  # ponytail: a writer that does not reserve its name (not docflow) can still replace the placeholder
    try:
        os.unlink(src)
    except BaseException:
        Path(dst).unlink(missing_ok=True)  # the link is ours: without it the file stays only at src, nothing unrecorded in the library
        raise


def _move_unique(src: Path, wanted: Path, sha: str) -> Path:
    """Move to the first free name; if someone takes it between the check and the move, pick the next one."""
    for _ in range(50):
        dst = _unique(wanted)
        try:
            _move_verified(src, dst, sha)
            return dst
        except FileExistsError:
            continue
    raise FileExistsError(wanted)


def _put_back(src: Path, dst: Path, sha: str) -> None:
    """Best effort: return a moved file to where it came from after a later step failed."""
    try:
        if dst.exists() and not src.exists():
            _move_verified(dst, src, sha)
    except OSError:
        log.exception("could not put %s back to %s; it stays at %s", dst.name, src, dst)


def apply(p: Proposal, cfg: Config, db: DB, final_name: str | None = None, source: str = "LocalFolder",
          confirmed: bool = False) -> Path:
    """Rename + move. Never overwrites an existing file (' (2)' suffix). Returns the final path.
    `confirmed`: a human has approved THIS proposal (the web click, the CLI [A]pprove). Without it only what the engine is
    sure of moves: "auto", and "duplicate" (to quarantine)."""
    if p.status in ("confirm", "manual", "logical_duplicate", "error") and not confirmed:
        raise ValueError(f"a {p.status} proposal needs a human confirmation before it is filed")
    a = p.analysis
    if p.status != "duplicate" and p.sha256 and db.find_sha(p.sha256):
        # the same content was filed after this proposal was made (two copies proposed together): never a second copy
        p.status = "duplicate"
        p.notes.append("Identical to a document already filed (SHA-256).")
    if p.status == "duplicate":
        dst = _move_unique(p.source, cfg.path("quarantine") / "duplicates" / p.source.name, p.sha256)
        doc = None
        try:
            doc = db.add_document(original_filename=p.source.name, original_path=str(p.source),
                                  destination_path=str(dst), sha256=p.sha256, status="duplicate", source=source,
                                  processed_at=now())
            db.add_op(doc, "quarantine", str(p.source), str(dst))
        except Exception:  # no trace in the history = no undo: put the file back instead of orphaning it
            _put_back(p.source, dst, p.sha256)
            if doc:
                db.forget_document(doc)
            raise
        log.info("SOURCE=%s ORIGINAL=%s STATUS=DUPLICATE", source, p.source.name)
        return dst
    name = final_name or p.final_name
    if not (a and name and p.rel_dir):
        raise ValueError("incomplete proposal: manual validation required")
    if FORBIDDEN.search(name) or name.strip(" .") == "":  # separators, "..", Windows-forbidden characters
        raise ValueError(f"invalid file name: {name!r}")
    wanted = safe_join(cfg.path("library_root"), p.rel_dir) / name
    if len(str(wanted)) + len(" (999)") > MAX_PATH:  # room for a collision suffix
        raise ValueError(f"path too long ({len(str(wanted))} chars)")
    dst = _move_unique(p.source, wanted, p.sha256)
    doc = None
    try:
        doc = db.add_document(
            original_filename=p.source.name, final_filename=dst.name, original_path=str(p.source),
            destination_path=str(dst), sha256=p.sha256, company=a.company, document_type=a.document_type,
            document_date=a.date, amount=str(a.amount) if a.amount is not None else None, currency=a.currency,
            invoice_number=a.invoice_number, confidence=p.confidence, source=source, processed_at=now(),
            status="classified")
        db.add_op(doc, "move", str(p.source), str(dst))
    except Exception:  # no trace in the history = no undo: put the file back instead of orphaning it
        _put_back(p.source, dst, p.sha256)
        if doc:
            db.forget_document(doc)
        raise
    log.info("SOURCE=%s ORIGINAL=%s COMPANY=%s TYPE=%s DATE=%s FINAL=%s STATUS=SUCCESS",
             source, p.source.name, a.company, a.document_type, a.date, dst.name)
    return dst


def undo(db: DB, op_id: int | None = None) -> tuple[Path, Path]:
    """Restore the old path + old name. Refuses if the original already exists (never overwrites)."""
    op = db.op(op_id)
    if op is None or op["undone"]:
        raise ValueError("no operation to undo")
    src, dst = Path(op["src"]), Path(op["dst"])
    if not dst.exists():
        raise FileNotFoundError(f"file not found: {dst}")
    if src.exists():
        raise FileExistsError(f"the original location is occupied: {src}")
    sha = db.document_sha(op["document_id"])
    if sha and sha256_file(dst) != sha:  # replaced or corrupted since it was filed: do not silently put THAT back
        raise ValueError(f"the filed document has changed since it was filed, not restoring it: {dst}")
    _move_verified(dst, src, sha or sha256_file(dst))  # same guarantees as filing: never overwrite, verify before deleting
    try:
        db.mark_undone(op)
    except Exception:  # history and disk must agree: the document goes back where the history says it is
        _put_back(dst, src, sha or sha256_file(src))
        raise
    log.info("UNDO OP=%s RESTORED=%s", op["id"], src.name)
    return dst, src
