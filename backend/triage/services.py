"""Bridge between the API and the docflow engine. The client NEVER sends a path: only fields,
validated here (Pydantic + sanitization); names and destinations are recomputed server-side."""
import copy
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, OperationalError, connection, connections, transaction
from django.db.models import Q
from django.utils import timezone
from docflow import learn
from docflow.analyze import Analysis, RuleBasedAnalyzer
from docflow.db import DB
from docflow.extract import extract_text, find_tesseract
from docflow.naming import build_filename, sanitize
from docflow.pipeline import Proposal, apply, propose, sha256_file
from docflow.pipeline import undo as engine_undo
from docflow.routing import fill, route, safe_join

from .models import Item, ItemText, ScanJob

log = logging.getLogger("triage")

EDITABLE = {"company", "document_type", "date", "detail", "amount", "currency", "invoice_number"}


class ApiError(Exception):
    pass


def cfg():
    c = settings.DOCFLOW
    c.refresh_learned()  # a rule learned or forgotten by the other worker (or the CLI) applies here too, without a restart
    return c


def rules_snapshot(c):
    """A copy of the configuration whose RULES are its own. A correction made by another request learns IN PLACE (a company
    added to the dict, a rule appended to the list) and refresh_learned swaps four attributes one after the other: a scan
    running in its own thread must neither see half of that nor iterate a dict that grows. The scan keeps this copy."""
    return replace(c, companies=copy.deepcopy(c.companies), types=copy.deepcopy(c.types), routing=copy.deepcopy(c.routing),
                   learned_routes=set(c.learned_routes), reload=None)  # reload=None: a snapshot is never refreshed


def engine_db() -> DB:
    return DB(cfg().path("db"))


def roots() -> list[Path]:
    c = cfg()
    return [c.path("inbox"), c.path("quarantine"), c.path("library_root"), *map(Path, c.settings.get("extra_inboxes", []))]


# ------------------------------------------------------------------ scan
def pdfs_under(root: Path) -> list[Path]:
    """The ONE definition of "a PDF to scan": any case of .pdf, subfolders included, folders starting with @ or . skipped
    (NAS metadata such as @eaDir). The scan and the dashboard count both use it, so they cannot disagree."""
    out: list[Path] = []
    if not root.exists():
        return out
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(("@", ".")))
        out += [Path(d) / f for f in sorted(files) if f.lower().endswith(".pdf")]
    return out


COUNT_TTL = 30  # seconds: the dashboard refreshes every 15 s, and counting walks the whole folder (a NAS)
_counts: dict[str, tuple[float, int]] = {}  # folder -> (when counted, how many PDFs); one per worker process


def _forget_counts() -> None:
    """Called when files move (end of a scan, an approval, an undo): the next dashboard counts again at once."""
    _counts.clear()


def _pdf_count(folder: Path) -> int:
    now = time.monotonic()
    hit = _counts.get(str(folder))
    if hit and now - hit[0] < COUNT_TTL:
        return hit[1]
    n = len(pdfs_under(folder))
    _counts[str(folder)] = (now, n)
    return n


def source_files() -> list[Path]:
    """PDFs from the Inbox then from extra sources (backlog)."""
    c = cfg()
    return [f for root in [c.path("inbox"), *map(Path, c.settings.get("extra_inboxes", []))] for f in pdfs_under(root)]


HEARTBEAT_SECONDS = 20  # a running scan renews its "I am alive" mark at least this often (dead after 10 minutes)


def _beat(job: ScanJob | None) -> None:
    if job:
        ScanJob.objects.filter(pk=job.pk).update(updated_at=timezone.now())


def scan(job: ScanJob | None = None) -> dict:
    """Propose a filing for each new PDF. Read-only on files; OCR runs in parallel."""
    c = rules_snapshot(cfg())  # the rules as they are NOW, kept for the whole scan (see rules_snapshot)
    an = RuleBasedAnalyzer(c)
    files = source_files()
    present = {str(f) for f in files}
    live = [r for r in [c.path("inbox"), *map(Path, c.settings.get("extra_inboxes", []))] if r.is_dir()]
    for it in Item.objects.filter(state=Item.PENDING).exclude(source_path__in=present):
        p = Path(it.source_path)
        # Only when its source folder is there (a missing mount must not wipe the queue) and the file is really gone.
        if any(r in p.parents for r in live) and not p.exists():
            it.state, it.resolved_at = Item.REMOVED, timezone.now()
            it.save()
    if find_tesseract(c.settings.get("ocr", {}).get("tesseract", "tesseract")):  # OCR works now: what was queued without it is read again
        Item.objects.filter(state=Item.PENDING, extraction="ocr_unavailable").update(state=Item.REMOVED, resolved_at=timezone.now())
    todo, skipped = [], 0
    owner: dict[str, Path] = {}
    hashed: dict[Path, tuple[str, int, int]] = {}  # file -> (sha, size, mtime_ns), taken ONCE here and given to propose()
    # open items whose file was already read: (size, mtime) unchanged means the content is the one we hashed
    stamps = {path: (size, mtime) for path, size, mtime in Item.objects.filter(
        state__in=[Item.PENDING, Item.IGNORED], source_size__isnull=False, source_mtime_ns__isnull=False,
    ).values_list("source_path", "source_size", "source_mtime_ns")}
    last_beat = time.monotonic()
    for f in files:
        if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:  # hashing a big archive over the network takes a while
            _beat(job)
            last_beat = time.monotonic()
        try:
            st = f.stat()  # taken BEFORE reading: a change during the read leaves an older stamp, so it is read again later
            if stamps.get(str(f)) == (st.st_size, st.st_mtime_ns):
                skipped += 1  # same size and mtime as when it was hashed: not read again
                continue
            sha = sha256_file(f)
        except OSError:  # unreadable now: propose() records it as an error item, once
            if Item.objects.filter(source_path=str(f), state__in=[Item.PENDING, Item.IGNORED], sha256="").exists():
                skipped += 1
            else:
                todo.append(f)
            continue
        # the same path now holds different content: its pending item (and analysis) is stale
        Item.objects.filter(source_path=str(f), state=Item.PENDING).exclude(sha256=sha).update(
            state=Item.REMOVED, resolved_at=timezone.now())
        if Item.objects.filter(sha256=sha, state__in=[Item.PENDING, Item.IGNORED], source_path=str(f)).exists():
            skipped += 1
            # queued by an older version (no stamp yet): remember it now so the next scan can skip the read
            Item.objects.filter(sha256=sha, state__in=[Item.PENDING, Item.IGNORED], source_path=str(f)).update(
                source_size=st.st_size, source_mtime_ns=st.st_mtime_ns)
        else:
            todo.append(f)
            hashed[f] = (sha, st.st_size, st.st_mtime_ns)
            owner.setdefault(sha, f)  # of identical files, the first by path is the original, the others are copies
    batch = {str(f) for f in todo}
    if job:
        job.total, job.skipped = len(todo), skipped
        job.save()

    broken: list[Exception] = []  # the exceptions of the files the engine could not analyse (list.append is thread-safe)

    def work(f: Path):  # one SQLite connection per thread: they cannot be shared
        sha = hashed[f][0] if f in hashed else None
        try:
            with engine_db() as db:  # closed as soon as this file is done, not when the garbage collector gets to it
                return f, propose(f, c, db, an, sha=sha)
        except Exception as e:  # one file the engine chokes on must not end the scan: it becomes an item in error, the rest go on
            log.exception("scan: %s could not be analysed", f.name)
            broken.append(e)
            return f, Proposal(f, sha or "", status="error", notes=[f"Cannot analyse file: {type(e).__name__}"])

    created = processed = 0  # processed = created + set aside: the progress must reach `total` whatever happened to each file
    with ThreadPoolExecutor(max_workers=3) as ex:
        pending = {ex.submit(work, f) for f in todo}
        while pending:
            # results are consumed as they complete (a slow file must not hide the others), and the job proves it is
            # alive at least every HEARTBEAT_SECONDS even when nothing finishes (a 28-page scan takes minutes)
            finished, pending = wait(pending, timeout=HEARTBEAT_SECONDS, return_when=FIRST_COMPLETED)
            _beat(job)
            for fut in finished:
                f, p = fut.result()
                # A copy is flagged whatever the order in which results arrive: either an item from an EARLIER scan has
                # the same content, or a file that sorts before it in THIS batch does.
                earlier = Item.objects.filter(sha256=p.sha256, state=Item.PENDING).exclude(source_path__in=batch).exists()
                if p.status != "duplicate" and (earlier or owner.get(p.sha256) not in (None, f)):
                    p.status = "duplicate"  # same content as another file already in the queue
                    p.notes.append("Identical to another file in the queue (SHA-256).")
                a = p.analysis.model_dump(mode="json") if p.analysis else None
                try:
                    with transaction.atomic():
                        item = Item.objects.create(
                            source_path=str(f), sha256=p.sha256, engine_status=p.status, analysis=a,
                            original=a and dict(a), final_name=p.final_name or "", rel_dir=p.rel_dir or "",
                            confidence=p.confidence, header=p.header, extraction=p.extraction, notes=p.notes,
                            source_size=hashed[f][1] if f in hashed else None,
                            source_mtime_ns=hashed[f][2] if f in hashed else None)
                        if p.text.strip():  # kept locally so the filed archive can be searched (see search())
                            ItemText.objects.create(item=item, text=p.text[:MAX_INDEXED_TEXT])
                except IntegrityError:  # the very same file content is already pending at this path: idempotent
                    skipped += 1
                else:
                    created += 1
                processed += 1
                if job:
                    job.done, job.created, job.skipped = processed, created, skipped  # skipped: the unchanged ones AND the collisions
                    job.save()
    if todo and len(broken) == len(todo):  # EVERY file failed: that is the engine or the disk, not a bad file: say so loudly
        raise RuntimeError(f"the engine failed on all {len(todo)} file(s): {broken[0]}") from broken[0]
    _forget_counts()
    return {"created": created, "skipped": skipped}


def job_dict(j: ScanJob | None) -> dict:
    if not j:
        return {"state": "none", "total": 0, "done": 0, "created": 0, "skipped": 0, "error": ""}
    return {"state": j.state, "total": j.total, "done": j.done, "created": j.created, "skipped": j.skipped,
            "error": j.error}


def _run(job: ScanJob) -> None:
    try:
        scan(job)
        job.state = ScanJob.State.DONE
    except Exception as e:  # a scan must never die silently: the error is visible in the site AND in the log
        log.exception("scan job %s failed", job.pk)
        job.state, job.error = ScanJob.State.ERROR, f"{type(e).__name__}: {e}"
    job.save()


def _run_job(job_id: int) -> None:
    _run(ScanJob.objects.get(pk=job_id))
    connections.close_all()


def scan_start() -> dict:
    """Start a background scan (only one at a time). A "running" scan with no update for 10 min is dead."""
    cutoff = timezone.now() - timedelta(minutes=10)
    # a scan nobody has touched for 10 min belonged to a dead process: retire it so a new one can start
    ScanJob.objects.filter(state=ScanJob.State.RUNNING, updated_at__lt=cutoff).update(
        state=ScanJob.State.ERROR, error="abandoned (no update for 10 min)")
    live = ScanJob.objects.filter(state=ScanJob.State.RUNNING).first()
    if live:
        return {"job": job_dict(live)}
    try:
        with transaction.atomic():
            job = ScanJob.objects.create()
    except IntegrityError:  # lost a race: another request created the running job between our check and our insert
        rival = list(ScanJob.objects.filter(state=ScanJob.State.RUNNING).order_by("-id")[:1])
        return {"job": job_dict(rival[0] if rival else ScanJob.objects.order_by("-id").first())}
    if not settings.SCAN_ASYNC:  # tests: synchronous
        _run(job)
        return {"created": job.created, "skipped": job.skipped, "job": job_dict(job)}
    threading.Thread(target=_run_job, args=(job.id,), daemon=True).start()
    return {"job": job_dict(job)}


def scan_status() -> dict:
    return job_dict(ScanJob.objects.order_by("-id").first())


# ------------------------------------------------------------------ read
def item_dict(it: Item) -> dict:
    a = it.analysis or {}
    c = cfg()
    return {
        "id": it.id, "state": it.state, "status": it.engine_status, "filename": Path(it.source_path).name,
        "company": a.get("company"), "document_type": a.get("document_type"), "date": a.get("date", "XXXX"),
        "detail": a.get("detail", ""), "amount": a.get("amount"), "currency": a.get("currency", "CAD"),
        "invoice_number": a.get("invoice_number"), "conf": a.get("conf", {}), "confidence": it.confidence,
        "final_name": it.final_name, "rel_dir": it.rel_dir,
        "destination": str(c.path("library_root") / it.rel_dir) if it.rel_dir else "",
        "notes": it.notes, "extraction": it.extraction, "result_path": it.result_path,
        "created_at": it.created_at.isoformat(), "resolved_at": it.resolved_at and it.resolved_at.isoformat(),
    }


def pdf_path(it: Item) -> Path:
    """File to display: must be under the Inbox, the quarantine or the library."""
    p = Path(it.result_path or it.source_path).resolve()
    if not any(r.resolve() in p.parents for r in roots()) or not p.is_file():
        raise ApiError("file not found or outside the allowed folders")
    return p


# ------------------------------------------------------------------ editing
def edit(it: Item, data: dict) -> Item:
    if it.state != Item.PENDING:
        raise ApiError("this item has already been handled")
    c = cfg()
    d = dict(it.analysis or {})
    d.setdefault("conf", {})
    for k in EDITABLE & data.keys():
        v = data[k]
        if k == "amount":
            try:
                v = None if v in (None, "") else str(Decimal(str(v).replace(",", ".")))
            except InvalidOperation:
                raise ApiError("invalid amount") from None
            d["include_amount"] = v is not None
        d[k] = v if v != "" or k in ("detail",) else None
        d["conf"]["amount" if k == "amount" else "type" if k == "document_type" else k] = 1.0  # validated by the human
    try:
        a = Analysis.model_validate({k: v for k, v in d.items() if k != "conf"} | {"conf": d["conf"]})
    except ValueError as e:
        raise ApiError(f"value rejected: {e}") from None
    if "detail" in data:  # only an explicitly edited detail is human-validated; editing anything else proves nothing
        a.check_detail = False
    it.analysis = a.model_dump(mode="json")
    # name: recomputed, unless the human typed one (kept, like a chosen destination, until the field is explicitly emptied)
    orig = dict(it.original or {})
    if data.get("final_name"):
        n = sanitize(str(data["final_name"]))
        if not n.lower().endswith(".pdf"):
            raise ApiError("the name must end with .pdf")
        it.final_name = n
        orig["_name_user"] = True
    elif "final_name" not in data and orig.get("_name_user") and it.final_name:
        pass  # another field was edited: the name the human typed stays
    elif a.company and a.document_type:
        orig.pop("_name_user", None)  # sent empty or null: back to the automatic name
        try:
            it.final_name = build_filename(a.date, a.company, a.document_type, a.detail,
                                           a.amount if a.include_amount else None, a.currency, ".pdf")
        except ValueError as e:
            raise ApiError(f"value rejected: {e}") from None
    # destination: chosen by the human (validated) or recomputed by the rules
    if data.get("rel_dir"):
        try:
            safe_join(c.path("library_root"), str(data["rel_dir"]))
        except ValueError as e:
            raise ApiError(str(e)) from None
        it.rel_dir = str(data["rel_dir"]).strip("/\\")
        orig["_dir_user"] = True
    elif not orig.get("_dir_user"):
        r = route(c.routing, a.company, a.document_type)
        r = fill(r, a.date) if r else None
        it.rel_dir = r or ""
    it.original = orig
    ok = bool(it.final_name and it.rel_dir)
    it.confidence = min(a.confidence, 1.0) if ok else 0.0
    if ok and it.engine_status in ("manual", "error"):
        it.engine_status = "confirm"  # corrected by the human: ready to be approved
    it.save()
    return it


# ------------------------------------------------------------------ decisions
def _engine_proposal(it: Item) -> Proposal:
    return Proposal(Path(it.source_path), it.sha256, status=it.engine_status,
                    analysis=Analysis.model_validate(it.analysis) if it.analysis else None,
                    final_name=it.final_name or None, rel_dir=it.rel_dir or None, confidence=it.confidence,
                    header=it.header)


def _learn(it: Item) -> list[dict]:
    """A correction becomes a local rule (*_learned.yaml files). Returns structured facts, not sentences:
    the UI renders them in the user's language."""
    if not (it.analysis and it.original):
        return []
    c, new, old, learned = cfg(), it.analysis, it.original, []
    company = new.get("company")
    stored = ItemText.objects.filter(item=it).values_list("text", flat=True).first() or ""
    if company and company != old.get("company") and learn.learn_company(c, company, it.header, stored):
        learned.append({"kind": "company", "value": company, "company": company})
    if company and new.get("document_type") and new["document_type"] != old.get("document_type") \
            and learn.learn_type(c, company, new["document_type"]):
        learned.append({"kind": "type", "value": new["document_type"], "company": company})
    if company and old.get("_dir_user") and it.rel_dir:
        year = (new.get("date") or "")[:4]
        parts = it.rel_dir.split("/")
        if year.isdigit() and parts[-1] == year:
            parts[-1] = "{year}"
        if learn.learn_route(c, company, "/".join(parts)):
            learned.append({"kind": "route", "value": "/".join(parts), "company": company})
    return learned


CLAIM_TTL = timedelta(minutes=10)  # a request that died mid-way must not keep the item reserved for good


def _claim(it: Item) -> None:
    """Reserve a pending item for ONE request. A conditional UPDATE is atomic in SQLite: two tabs, or a single and a bulk
    approval, that both passed the in-memory `state` check cannot both go on to move the file. The reservation is
    `resolved_at` (always empty on a pending item); `_release` gives it back when the request ends without a decision."""
    now = timezone.now()
    won = Item.objects.filter(pk=it.pk, state=Item.PENDING).filter(
        Q(resolved_at__isnull=True) | Q(resolved_at__lt=now - CLAIM_TTL)).update(resolved_at=now)
    if not won:
        raise ApiError("this item has already been handled")
    it.resolved_at = now


def _release(it: Item) -> None:
    Item.objects.filter(pk=it.pk, state=Item.PENDING).update(resolved_at=None)
    it.resolved_at = None


class FiledButUnrecorded(ApiError):
    """The file is moved and in the engine's history, but the queue could not be told. Never `_release`d: the item is NOT
    pending any more, whatever the queue says."""


def approve(it: Item) -> dict:
    if it.state != Item.PENDING:
        raise ApiError("this item has already been handled")
    _claim(it)
    try:
        with engine_db() as db:
            return _approve(it, db)
    except FiledButUnrecorded:
        raise
    except BaseException:
        _release(it)  # refused or failed BEFORE the file moved: the user can correct the item and try again
        raise


def _record_approval(it: Item, dst: Path) -> None:
    """The file is filed: say so in the queue. The only usual failure is a database busy for a moment (the engine writes the
    same file), so try again a few times; after that, the user is told where the document is rather than left with an item
    that looks pending while its file is gone."""
    for attempt in range(3):
        try:
            it.state, it.result_path, it.resolved_at = Item.APPROVED, str(dst), timezone.now()
            it.save()
            _forget_counts()
            return
        except OperationalError:
            if attempt < 2:
                time.sleep(1)
    log.critical("item %s: the file was filed at %s but the queue could not record it", it.pk, dst)
    raise FiledButUnrecorded(f"The document was filed at {dst}, but the queue could not record it (database busy). "
                             "Check History: it can be undone from there.")


def _approve(it: Item, db: DB) -> dict:
    p = _engine_proposal(it)
    if it.engine_status != "duplicate" and db.find_sha(it.sha256):
        # an identical document was filed between the scan and now: quarantine, never a 2nd copy
        p.status = it.engine_status = "duplicate"
        it.notes = [*it.notes, "Identical to a document already filed (SHA-256)."]
    if it.engine_status != "duplicate" and not (it.final_name and it.rel_dir):
        raise ApiError("company, type and destination are required before approving")
    try:
        dst = apply(p, cfg(), db, final_name=it.final_name or None, confirmed=True)  # the approval IS the human's confirmation
    except (OSError, ValueError) as e:
        raise ApiError(str(e)) from None
    # The file is filed: record that FIRST. Learning is a bonus and must never undo or hide the approval.
    _record_approval(it, dst)
    learned: list[dict] = []
    learning_failed = False
    if it.engine_status != "duplicate":
        try:
            learned = _learn(it)
        except Exception:
            learning_failed = True  # a recoverable warning for the user: the document IS filed, the rule is just not saved
            log.exception("learning from item %s failed (the approval itself was recorded)", it.pk)
    return {"result_path": str(dst), "learned": learned, "learning_failed": learning_failed}


def decide(it: Item, state: str) -> Item:
    if state not in (Item.IGNORED, Item.REMOVED):  # approving files a document: that is approve(), never a bare state change
        raise ApiError(f"cannot decide {state!r}: only ignore or remove")
    if it.state != Item.PENDING:
        raise ApiError("this item has already been handled")
    _claim(it)  # not while an approval is moving the file
    it.state, it.resolved_at = state, timezone.now()
    it.save()
    return it


MAX_BATCH = 200  # what one request may approve: a tick-box selection, not the whole archive


def approve_all_auto() -> dict:
    """At most MAX_BATCH per request (each approval moves a file on the NAS): `remaining` tells the screen to go on."""
    auto = Item.objects.filter(state=Item.PENDING, engine_status="auto")
    batch = list(auto.order_by("id")[:MAX_BATCH])
    result = approve_many(batch)
    # counted AFTER, from the database: a failed item is still pending and still counts, an approved one does not
    return {**result, "remaining": auto.count()}


def approve_selected(ids: object) -> dict:
    """Approve exactly the items the user ticked, one by one with the same rules as a single approval. An id that does not
    exist or is no longer pending (approved from another tab, removed...) is REPORTED as a failure, never skipped silently."""
    if (not isinstance(ids, list) or not ids or len(ids) > MAX_BATCH
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids) or len(set(ids)) != len(ids)):
        raise ApiError(f"ids must be a list of 1 to {MAX_BATCH} distinct item ids")
    pending = {it.id: it for it in Item.objects.filter(pk__in=ids, state=Item.PENDING)}
    gone = [{"id": i, "detail": "item no longer pending"} for i in ids if i not in pending]
    result = approve_many(pending[i] for i in ids if i in pending)
    return {"approved": result["approved"], "failed": gone + result["failed"]}


def approve_many(items) -> dict:
    ok, failed = [], []
    for it in items:
        try:
            approve(it)
            ok.append(it.id)
        except ApiError as e:
            failed.append({"id": it.id, "detail": str(e)})
        except Exception as e:  # e.g. a SQLite error from the engine: one item must not stop the batch or hide what was filed
            log.exception("bulk approval: item %s failed unexpectedly", it.pk)
            failed.append({"id": it.id, "detail": f"unexpected error: {type(e).__name__}"})  # details stay in the log
    return {"approved": ok, "failed": failed}


# ------------------------------------------------------------------ search
MAX_INDEXED_TEXT = 200_000  # characters kept per document: a 400-page scan must not bloat the database
MAX_TERMS = 8
HIT_START, HIT_END = "\x01", "\x02"  # around the words found in a snippet: never part of a real document text


def search(query: object, limit: object = 20) -> list[dict]:
    """Full-text search of the FILED documents, from the text read at scan time (local SQLite FTS5: accents and case do not
    matter, the last word may be a beginning). Only words are passed to the index: its operators, quotes and wildcards, typed
    or pasted, never reach it as syntax."""
    if not isinstance(query, str):
        raise ApiError("q must be a text")
    words = re.findall(r"\w+", query)[:MAX_TERMS]
    if not words:
        raise ApiError("type at least one word to search for")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ApiError("limit must be a whole number from 1 to 50")
    match = " ".join([*(f'"{w}"' for w in words[:-1]), f'"{words[-1]}"*'])
    root = cfg().path("library_root").resolve()
    # only what is IN the library: an approved duplicate is in quarantine, and its copy of the text must not be a second hit
    under_root = str(root).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    with connection.cursor() as cur:
        cur.execute(
            "SELECT i.id, i.result_path, i.analysis, snippet(item_fts, 0, %s, %s, '…', 14) FROM item_fts "
            "JOIN triage_item i ON i.id = item_fts.rowid WHERE item_fts MATCH %s AND i.state = %s "
            "AND i.result_path LIKE %s ESCAPE '\\' "
            "ORDER BY bm25(item_fts) LIMIT %s", [HIT_START, HIT_END, match, Item.APPROVED, under_root, limit])
        rows = cur.fetchall()
    out = []
    for item_id, result_path, analysis, snippet in rows:
        a = json.loads(analysis) if isinstance(analysis, str) else (analysis or {})
        filed = Path(result_path)
        folder = filed.parent.relative_to(root).as_posix() if root in filed.parents else str(filed.parent)
        out.append({"id": item_id, "filename": filed.name, "folder": folder, "company": a.get("company"), "date": a.get("date"),
                    "snippet": snippet})
    return out


def reindex_text(report=None) -> dict:
    """Read again the text of the documents that have none stored (filed before the search existed, or whose text was empty),
    from the file where it is now. Local OCR: it can take a while, hence the progress callback."""
    done = missing = empty = 0
    c = cfg()
    for it in Item.objects.filter(fulltext__isnull=True).exclude(state=Item.REMOVED).order_by("id"):
        try:
            path = pdf_path(it)
            text = extract_text(path, c.settings.get("ocr")).text
        except Exception as e:  # deliberately broad: one unreadable file must not stop the others (MuPDF raises classes of its own)
            log.warning("reindex: item %s (%s): %s: %s", it.pk, it.source_path, type(e).__name__, e)
            missing += 1
            continue
        if not text.strip():
            empty += 1
            continue
        ItemText.objects.create(item=it, text=text[:MAX_INDEXED_TEXT])
        done += 1
        if report:
            report(done, it)
    return {"indexed": done, "unreadable": missing, "without_text": empty}


# ------------------------------------------------------------------ accuracy
STAT_FIELDS = ("company", "document_type", "date", "amount", "detail")
BANDS = ((0.95, "95-100"), (0.90, "90-94"), (0.85, "85-89"), (0.80, "80-84"), (0.0, "under 80"))
MIN_SAMPLE = 20  # fewer filed documents than this prove nothing about a threshold


def _proposal_confidence(original: dict) -> float:
    """How sure the engine was when it proposed the document (before anything was corrected)."""
    fields = {k: v for k, v in original.items() if not k.startswith("_")}
    try:
        return round(min(Analysis.model_validate(fields).confidence, float((original.get("conf") or {}).get("destination", 1.0))), 2)
    except (ValueError, TypeError):
        return 0.0


@dataclass
class _Filed:
    corrected: list[str]  # the fields (and "destination") that were changed by hand before approval
    conf: float  # the engine's confidence when it proposed the document
    company: str  # the company it was finally filed under
    month: str | None


def _nothing_if_blank(value):
    """None and "" both mean 'no value'; 0 is a value (an amount of zero is not an absent amount), unlike `value or None`."""
    return None if value is None or value == "" else value


def stats() -> dict:
    """How often what the engine proposed was accepted without any correction, from the filed documents: by field, month,
    company and confidence band, and the lowest auto threshold that every filed document above it would have passed."""
    docs: list[_Filed] = []
    for analysis, original, resolved in Item.objects.filter(state=Item.APPROVED).values_list("analysis", "original", "resolved_at"):
        if not (isinstance(analysis, dict) and isinstance(original, dict)):
            continue
        corrected = [f for f in STAT_FIELDS if _nothing_if_blank(analysis.get(f)) != _nothing_if_blank(original.get(f))]
        if original.get("_dir_user"):
            corrected.append("destination")  # the folder was typed by hand
        docs.append(_Filed(corrected, _proposal_confidence(original), analysis.get("company") or "",
                           timezone.localtime(resolved).strftime("%Y-%m") if resolved else None))
    months = [{"month": m, "total": sum(d.month == m for d in docs), "untouched": sum(d.month == m and not d.corrected for d in docs)}
              for m in sorted({d.month for d in docs if d.month})]
    by_company = [(c, sum(d.company == c for d in docs), sum(d.company == c and bool(d.corrected) for d in docs))
                  for c in sorted({d.company for d in docs if d.company})]
    by_company.sort(key=lambda r: (-r[2], -r[1], r[0]))  # most corrections first, then the most documents
    companies = [{"company": c, "total": total, "corrected": corrected} for c, total, corrected in by_company[:10]]
    bands = []
    for floor, name in BANDS:
        inside = [d for d in docs if d.conf >= floor and not any(d.conf >= f for f, _ in BANDS if f > floor)]
        bands.append({"band": name, "total": len(inside), "untouched": sum(not d.corrected for d in inside)})
    current = float(cfg().settings["thresholds"]["auto"])
    suggested: float | None = None
    if len(docs) >= MIN_SAMPLE:  # the lowest confidence level such that EVERY filed document at or above it was accepted untouched
        for level in sorted({d.conf for d in docs}, reverse=True):
            if any(d.corrected for d in docs if d.conf >= level):
                break
            suggested = level
    if suggested is not None and suggested >= current:
        suggested = None  # nothing to gain: today's threshold is already as low as the evidence allows
    above = [d for d in docs if suggested is not None and d.conf >= suggested]
    return {
        "total": len(docs), "untouched": sum(not d.corrected for d in docs),
        "fields": [{"field": f, "corrected": sum(f in d.corrected for d in docs), "total": len(docs)} for f in (*STAT_FIELDS, "destination")],
        "months": months, "companies": companies, "bands": bands,
        "threshold": {"current": current, "suggested": suggested, "documents": len(above),
                      "newly_automatic": sum(d.conf < current for d in above)},
    }


# ------------------------------------------------------------------ learned rules
def _learned(call):
    """Run something that reads or writes the learned files; one that cannot be read becomes a clear 400 naming the file."""
    try:
        return call()
    except learn.LearnedFileError as e:
        raise ApiError(str(e)) from None


def rules() -> dict:
    """The learned rules (never the hand-written ones), each with the number of documents filed under its company."""
    out = _learned(lambda: learn.list_rules(cfg()))
    filed: dict[str, int] = {}
    for analysis in Item.objects.filter(state=Item.APPROVED).values_list("analysis", flat=True):
        company = analysis.get("company") if isinstance(analysis, dict) else None
        if company:
            filed[company] = filed.get(company, 0) + 1
    for rows in out.values():
        for row in rows:
            row["filed"] = filed.get(row["company"], 0)
    return out


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{what} must be a non-empty text")
    return value


def forget_rule(body: object) -> dict:
    if not isinstance(body, dict) or body.get("kind") not in ("alias", "type", "route"):
        raise ApiError("kind must be alias, type or route")
    company, pattern = _text(body.get("company"), "company"), body.get("pattern")
    if pattern is not None and not isinstance(pattern, str):
        raise ApiError("pattern must be a text")
    forget = {"alias": lambda: learn.forget_alias(cfg(), company, pattern), "type": lambda: learn.forget_type(cfg(), company),
              "route": lambda: learn.forget_route(cfg(), company)}[body["kind"]]
    if not _learned(forget):
        raise NotFound("no such learned rule")
    return {"forgotten": True}


class NotFound(ApiError):
    pass


def set_route(body: object) -> dict:
    """Correct the destination of a LEARNED route. A hand-written route is never edited from here."""
    if not isinstance(body, dict):
        raise ApiError("company and destination are required")
    company, destination = _text(body.get("company"), "company"), _text(body.get("destination"), "destination")
    if company not in {r["company"] for r in _learned(lambda: learn.list_rules(cfg()))["routes"]}:
        raise ApiError("only a learned destination can be corrected here")
    try:
        safe_join(cfg().path("library_root"), destination)  # the same test every destination goes through
    except ValueError as e:
        raise ApiError(str(e)) from None
    _learned(lambda: learn.learn_route(cfg(), company, destination))  # False when it is already that: nothing to do, not an error
    return {"company": company, "destination": destination}


# ------------------------------------------------------------------ history / dashboard
def history(n: int = 30) -> list[dict]:
    with engine_db() as db:
        return [dict(r) for r in db.history(n)]


def undo(op_id: int) -> dict:
    try:
        with engine_db() as db:
            cur, old = engine_undo(db, op_id)
    except (ValueError, OSError) as e:
        raise ApiError(str(e)) from None
    Item.objects.filter(result_path=str(cur)).update(state=Item.PENDING, result_path="", resolved_at=None)
    _forget_counts()
    return {"restored": str(old)}


GROUPS = ("auto", "needs_validation", "duplicates", "errors")


def in_group(group: str) -> Q:
    """THE definition of the four disjoint categories that add up to "pending" (a duplicate or an error is not also "to
    validate"). The dashboard counts with it and the queue filters with it, so a tile and its list cannot disagree."""
    if group == "auto":
        return Q(engine_status="auto")
    if group == "duplicates":
        return Q(engine_status__in=["duplicate", "logical_duplicate"])
    if group == "errors":
        return Q(engine_status="error")
    if group == "needs_validation":
        return ~(in_group("auto") | in_group("duplicates") | in_group("errors"))
    raise ApiError(f"unknown group: {group}")


def dashboard() -> dict:
    c = cfg()
    today = timezone.localdate()
    pend = Item.objects.filter(state=Item.PENDING)
    inbox = c.path("inbox")
    return {
        "pending": pend.count(),
        "needs_validation": pend.filter(in_group("needs_validation")).count(),
        "auto_ready": pend.filter(in_group("auto")).count(),
        "duplicates": pend.filter(in_group("duplicates")).count(),
        "errors": pend.filter(in_group("errors")).count(),
        "classified_today": Item.objects.filter(state=Item.APPROVED, resolved_at__date=today).count(),
        "sources": [{"kind": "inbox" if i == 0 else "backlog", "path": str(p),
                     "files": _pdf_count(p)}
                    for i, p in enumerate([inbox, *map(Path, c.settings.get("extra_inboxes", []))])],
        "history": history(8),
    }


def destinations(limit: int = 800) -> list[str]:
    root = cfg().path("library_root")
    out: list[str] = []  # destination folders relative to the library, e.g. "Bills/Hydro-Quebec/2025"
    if not root.exists():
        return out
    base = len(root.parts)
    for d, dirs, _ in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(("@", ".")))
        depth = len(Path(d).parts) - base
        if depth and depth <= 3:
            out.append(Path(d).relative_to(root).as_posix())
        if depth >= 3:
            dirs[:] = []
        if len(out) >= limit:
            break
    return sorted(out)


def vocabulary() -> dict:
    c = cfg()
    return {"companies": sorted(c.companies), "types": sorted({r["type"] for r in c.types})}
