"""The library explorer's actions: search, create / rename / move / delete a folder or a file, and re-file a PDF from its fields.

Everything here works INSIDE the library folder only (services._library_target refuses anything else), never replaces an
existing file or folder, and "delete" moves to a `_Trash` folder at the library's root: only what is already in `_Trash`
is removed for good.
"""
import json
import os
import re
import shutil
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone
from docflow import learn
from docflow.analyze import Analysis, RuleBasedAnalyzer
from docflow.extract import extract_text
from docflow.fields import header_line, parse_number
from docflow.naming import build_filename, sanitize, strip_accents
from docflow.pipeline import _link_or_rename, _unique, sha256_file
from docflow.routing import fill, route, safe_join

from . import services as s
from .models import Item

TRASH = "_Trash"
SEARCH_MAX = 300  # results
SEARCH_SECONDS = 8.0  # a library on a slow share: the answer says it stopped early
FIELDS = ("company", "document_type", "date", "detail", "amount", "currency")


def _clean_name(name: str) -> str:
    """One path segment that Windows accepts, exactly as typed (a name that needed cleaning is refused, not silently changed)."""
    n = sanitize(name or "")
    if not n or n != (name or "").strip():
        raise s.ApiError("invalid name")
    return n


def _entry(rel: str, must_exist: bool = True) -> tuple[Path, Path]:
    root, p = s._library_target(rel)
    if p == root:
        raise s.ApiError("the library folder itself cannot be changed")
    if must_exist and not p.exists():
        raise s.ApiError("file not found")
    if p == root / TRASH:
        raise s.ApiError("the trash cannot be changed")
    return root, p


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def _retarget(old: Path, new: Path) -> None:
    """Items already filed here keep a working "open document" link after the file or folder moved."""
    prefix = str(old)
    moved = []
    for it in Item.objects.filter(result_path__startswith=prefix):
        if it.result_path == prefix or it.result_path.startswith(prefix + os.sep):
            it.result_path = str(new) + it.result_path[len(prefix):]
            moved.append(it)
    with transaction.atomic():  # all the links follow, or none does: a moved folder is never left half pointing at the old place
        Item.objects.bulk_update(moved, ["result_path"], batch_size=500)  # a few statements, not one per document


def _move(src: Path, dst: Path) -> None:
    """Never replaces: a file goes through a hard link / exclusive reservation, a folder only if the destination is free."""
    if dst.exists() and os.path.normcase(str(dst)) != os.path.normcase(str(src)):
        raise s.ApiError("something with this name already exists there")
    try:
        if src.is_dir():
            if src in dst.parents:
                raise s.ApiError("a folder cannot be moved into itself")
            os.rename(src, dst)
        elif os.path.normcase(str(dst)) == os.path.normcase(str(src)):
            os.rename(src, dst)  # only the case of the name changes
        else:
            _link_or_rename(src, dst)
    except FileExistsError:
        raise s.ApiError("something with this name already exists there") from None
    except OSError as e:
        s.log.warning("library move %s -> %s failed: %s", src, dst, e)
        raise s.ApiError("the move failed: the file may be open elsewhere or the folder is read-only") from None
    _retarget(src, dst)


# ------------------------------------------------------------------ search
def search(q: str) -> dict:
    """Folders and files whose NAME contains the text (case and accents ignored), anywhere in the library."""
    needle = strip_accents(q or "").lower().strip()
    if len(needle) < 2:
        raise s.ApiError("type at least 2 characters")
    root, _ = s._library_target("")
    hits: list[dict] = []
    stopped = False
    deadline = time.monotonic() + SEARCH_SECONDS
    for here, dirs, files in os.walk(root):
        # the trash is not part of the library to search: what was deleted must not come back as a hit (or use up the cap)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(here) == root and d == TRASH))
        if time.monotonic() > deadline:
            stopped = True
            break
        for name, is_dir in [(d, True) for d in dirs] + [(f, False) for f in sorted(files) if not f.startswith(".")]:
            if needle not in strip_accents(name).lower():
                continue
            p = Path(here) / name
            try:
                st = p.stat()
            except OSError:
                continue
            hits.append({"name": name, "path": _rel(root, p), "folder": _rel(root, Path(here)) if Path(here) != root else "",
                         "is_dir": is_dir, "size": 0 if is_dir else st.st_size, "modified": int(st.st_mtime)})
            if len(hits) >= SEARCH_MAX:
                return {"hits": hits, "truncated": True}
    return {"hits": hits, "truncated": stopped}


# ------------------------------------------------------------------ folders and files
def _refuse_the_trash_name(root: Path, dst: Path, src: Path | None = None) -> None:
    """`_Trash` at the root is the trash, and deleting inside it is for good: no ordinary folder may take that name (any case)."""
    if dst.parent == root and dst.name.lower() == TRASH.lower() and src != root / TRASH:
        raise s.ApiError(f"{TRASH} is reserved for the trash: use Delete to put something there")


def make_folder(parent: str, name: str) -> dict:
    root, folder = s._library_target(parent)
    if not folder.is_dir():
        raise s.ApiError("folder refused")
    new = folder / _clean_name(name)
    _refuse_the_trash_name(root, new)
    try:
        new.mkdir()
    except FileExistsError:
        raise s.ApiError("something with this name already exists there") from None
    except OSError as e:
        s.log.warning("library mkdir %s failed: %s", new, e)
        raise s.ApiError("the folder could not be created") from None
    return {"path": _rel(root, new)}


def rename(rel: str, name: str) -> dict:
    root, p = _entry(rel)
    n = _clean_name(name)
    if p.is_file() and p.suffix.lower() != Path(n).suffix.lower():
        raise s.ApiError("the extension of a file cannot be changed")
    dst = p.with_name(n)
    _refuse_the_trash_name(root, dst, p)
    _move(p, dst)
    return {"path": _rel(root, dst)}


def move(rel: str, to: str) -> dict:
    """Into the folder `to` (a library folder; "" = the library's root)."""
    root, p = _entry(rel)
    _, folder = s._library_target(to)
    if not folder.is_dir():
        raise s.ApiError("folder refused")
    if folder == root / TRASH or (root / TRASH) in folder.parents:
        raise s.ApiError("use Delete to put something in the trash")
    dst = folder / p.name
    if dst == p:
        raise s.ApiError("it is already there")
    _refuse_the_trash_name(root, dst, p)
    _move(p, dst)
    return {"path": _rel(root, dst)}


def delete(rel: str) -> dict:
    """Into `_Trash`, to be put back by moving it out; what is already in `_Trash` is deleted for good."""
    root, p = _entry(rel)
    trash = root / TRASH
    if trash in p.parents:
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError as e:
            s.log.warning("library delete %s failed: %s", p, e)
            raise s.ApiError("the deletion failed: the file may be open elsewhere") from None
        return {"path": None, "permanent": True}
    trash.mkdir(exist_ok=True)
    dst = _unique(trash / p.name)
    _move(p, dst)
    return {"path": _rel(root, dst), "permanent": False}


# ------------------------------------------------------------------ documents past their retention
EXPIRED_MAX = 500  # rows sent at once; `total` says how many there are


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February in a year that has none: the day after, so the document is kept a day longer, not shorter
        return date(day.year + years, 3, 1)


def _past_retention(today: date) -> list[dict]:
    """Every filed document of the library whose type has a `retention_years` and whose date, plus those years, is before today.
    The date is the one the engine read (or the person corrected); a document with no readable date never expires. The oldest first."""
    years = s.cfg().retention()
    if not years:
        return []
    root = s.cfg().path("library_root")
    where_root, under_root = s._in_library(root)
    with connection.cursor() as cur:
        cur.execute(f"SELECT i.id, i.result_path, i.analysis FROM triage_item i WHERE i.state = %s AND ({where_root}) "
                    f"AND {s._DATE} GLOB {s._ISO_DAY} ORDER BY i.id", [Item.APPROVED, *under_root])
        rows = cur.fetchall()
    found = []
    for item_id, result_path, analysis in rows:
        a = json.loads(analysis) if isinstance(analysis, str) else (analysis or {})
        kept = years.get(str(a.get("document_type") or "").strip().casefold())
        try:
            due = _add_years(date.fromisoformat(a["date"]), kept) if kept else None
        except (KeyError, TypeError, ValueError):
            continue  # "2025-13-45" has the shape of a date and is not one
        if due is None or due >= today:
            continue
        rel = _inside(root, Path(result_path))
        if rel is None or rel.split("/")[0] == TRASH:
            continue  # moved out of the library, or already in the trash
        found.append({"id": item_id, "path": rel, "name": Path(rel).name, "company": a.get("company") or "",
                      "document_type": a.get("document_type") or "", "date": a["date"], "years": kept, "expired_on": due.isoformat()})
    found.sort(key=lambda d: (d["expired_on"], d["id"]))
    return found


def _inside(root: Path, p: Path) -> str | None:
    """`p` relative to the library root (as written or resolved: a library reached through a link), if the file is there."""
    for base in (root, root.resolve()):
        try:
            rel = p.relative_to(base)
        except ValueError:
            continue
        return rel.as_posix() if (base / rel).is_file() else None
    return None


def expired(today: date | None = None) -> dict:
    """DOC534.13: the documents that can be destroyed. `configured` is False while no type has a retention (the page then says how)."""
    found = _past_retention(today or timezone.localdate())
    return {"configured": bool(s.cfg().retention()), "total": len(found), "expired": found[:EXPIRED_MAX]}


def delete_expired(item_id: object, today: date | None = None) -> dict:
    """DOC534.13: put one expired document in `_Trash` (as Delete does) and record it in the history, where it can be undone. The age is
    checked here again: the page cannot make the server delete a document that is not past its retention."""
    due = _past_retention(today or timezone.localdate()) if isinstance(item_id, int) and not isinstance(item_id, bool) else []
    found = next((d for d in due if d["id"] == item_id), None)
    if found is None:
        raise s.ApiError("this document is not past its retention")
    root, p = _entry(found["path"])
    with s.engine_db() as db:
        doc = db.find_sha(Item.objects.get(pk=item_id).sha256)
        if doc is None:  # no trace in the history = no undo: nothing is deleted
            raise s.ApiError("this document is not in the history, so its deletion could not be recorded")
        sha = sha256_file(p)
        out = delete(found["path"])
        trash_path = root / out["path"]
        try:
            db.add_op(doc["id"], "expire", str(p), str(trash_path), json.dumps({"sha": sha}))
        except Exception:  # the history and the disk must agree: the document goes back where it was
            _move(trash_path, p)
            raise
    s.log.info("EXPIRED ITEM=%s PATH=%s", item_id, found["path"])
    return {"path": out["path"], "name": found["name"]}


# ------------------------------------------------------------------ re-filing a PDF from its fields
def _typed_amount(raw) -> Decimal:
    """An amount as a person writes it: "80", "158,98", "1 234,56", "1.234,56", "1,234.56" (blanks of any kind ignored). A clear
    ApiError, not a Decimal syntax error, when it cannot be read."""
    t = "".join(str(raw).split())  # str.split() cuts on every blank, the no-break and narrow no-break spaces included
    if re.fullmatch(r"-?\d+", t):
        return Decimal(t)
    if re.fullmatch(r"-?\d+[.,]\d", t):  # one decimal: "25.5"
        return Decimal(t.replace(",", "."))
    number = parse_number(t)  # the last separator followed by two digits is the decimal one; the others group thousands
    if number is None:
        raise s.ApiError("invalid amount")
    return number


def _plan_from(fields: dict, rel_dir: str, final_name: str) -> dict:
    c = s.cfg()
    d: dict = {k: fields.get(k) for k in FIELDS if fields.get(k) not in (None, "")}
    d.setdefault("detail", "")
    amount = d.pop("amount", None)
    try:
        if amount is not None:
            amount = _typed_amount(amount)
        a = Analysis.model_validate({**d, "amount": amount, "include_amount": amount is not None})
    except (InvalidOperation, ValueError) as e:
        raise s.ApiError(f"value rejected: {e}") from None
    name = dest = ""
    if final_name:
        name = _clean_name(final_name)  # a typed name that needs cleaning is refused, not filed under another name than the one validated
        if not name.lower().endswith(".pdf"):
            raise s.ApiError("the name must end with .pdf")
    elif a.company and a.document_type:
        try:
            name = build_filename(a.date, a.company, a.document_type, a.detail, a.amount if a.include_amount else None,
                                  a.currency, ".pdf")
        except ValueError as e:
            raise s.ApiError(f"value rejected: {e}") from None
    if rel_dir:
        try:
            safe_join(c.path("library_root"), rel_dir)
        except ValueError as e:
            raise s.ApiError(str(e)) from None
        dest = rel_dir.strip("/\\")
    elif a.company and a.document_type:
        r = route(c.routing, a.company, a.document_type)
        dest = (fill(r, a.date) if r else "") or ""
    return {"fields": {k: (str(v) if v is not None else "") for k, v in
                       {"company": a.company, "document_type": a.document_type, "date": a.date, "detail": a.detail,
                        "amount": a.amount if a.include_amount else None, "currency": a.currency}.items()},
            "final_name": name, "rel_dir": dest}


def plan(rel: str, fields: dict | None, rel_dir: str = "", final_name: str = "") -> dict:
    """What the form shows. Without `fields` the document is read and analysed (OCR if it is a scan); with them, only the name
    and the folder they give are computed."""
    root, p = _entry(rel)
    if not p.is_file() or p.suffix.lower() != ".pdf":
        raise s.ApiError("only PDF documents can be classified")
    here = _rel(root, p.parent) if p.parent != root else ""
    if fields is None:
        c = s.cfg()
        try:
            ex = extract_text(p, c.settings.get("ocr"))
        except Exception as e:  # one unreadable PDF must not be a server error
            s.log.warning("library plan: cannot read %s: %s", p.name, e)
            raise s.ApiError(f"Cannot read file: {type(e).__name__}") from None
        a = RuleBasedAnalyzer(c).analyze(ex.text)
        fields = {"company": a.company, "document_type": a.document_type, "date": a.date, "detail": a.detail,
                  "amount": a.amount if a.include_amount else None, "currency": a.currency}
    out = _plan_from(fields, rel_dir, final_name)
    return {**out, "current_dir": here, "current_name": p.name}


def _learn(p: Path, out: dict, typed_dir: bool) -> list[dict]:
    """What the human decided becomes a rule, as in "To file": the company (by its name in the text), the type of that company, and
    the folder when it was typed. Only what the rules would not already have proposed is kept. A failure here never undoes the
    re-filing: the file is already where the human wants it."""
    c = s.cfg()
    f = out["fields"]
    company, doc_type = f["company"], f["document_type"]
    if not company:
        return []
    learned: list[dict] = []
    try:
        item = Item.objects.filter(result_path=str(p)).first()
        stored = item.fulltext.text if item and hasattr(item, "fulltext") else ""
        text = stored or extract_text(p, c.settings.get("ocr")).text
        guess = RuleBasedAnalyzer(c).analyze(text)
        if guess.company != company and learn.learn_company(c, company, header_line(text), text):
            learned.append({"kind": "company", "value": company, "company": company})
        if doc_type and guess.document_type != doc_type and learn.learn_type(c, company, doc_type):
            learned.append({"kind": "type", "value": doc_type, "company": company})
        if typed_dir and out["rel_dir"]:
            parts = out["rel_dir"].split("/")
            if f["date"][:4].isdigit() and parts[-1] == f["date"][:4]:
                parts[-1] = "{year}"
            if learn.learn_route(c, company, "/".join(parts)):
                learned.append({"kind": "route", "value": "/".join(parts), "company": company})
    except Exception as e:
        s.log.warning("library: nothing learned from %s: %s: %s", p.name, type(e).__name__, e)
    return learned


def apply(rel: str, fields: dict, rel_dir: str = "", final_name: str = "") -> dict:
    root, p = _entry(rel)
    out = plan(rel, fields, rel_dir, final_name)
    if not out["final_name"] or not out["rel_dir"]:
        raise s.ApiError("company, type and destination are required before approving")
    folder = safe_join(root, out["rel_dir"])
    if (root / TRASH) in (folder, *folder.parents):
        raise s.ApiError("use Delete to put something in the trash")
    made = [d for d in (folder, *folder.parents) if root in d.parents and not d.exists()]  # the folders this call creates, deepest first
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / out["final_name"]
    try:
        if dst != p:
            _move(p, dst)
    except s.ApiError:  # name taken, file open, read-only folder: nothing was re-filed, so nothing is learned and no empty folder stays
        for d in made:
            try:
                d.rmdir()  # only an empty one goes
            except OSError:
                break
        raise
    learned = _learn(dst, out, bool(rel_dir.strip("/\\ ")))  # AFTER the move: only a re-filing that took place teaches (the item follows the file)
    return {"path": _rel(root, dst), "learned": learned}
