"""The library explorer's actions: search, create / rename / move / delete a folder or a file, and re-file a PDF from its fields.

Everything here works INSIDE the library folder only (services._library_target refuses anything else), never replaces an
existing file or folder, and "delete" moves to a `_Trash` folder at the library's root: only what is already in `_Trash`
is removed for good.
"""
import os
import shutil
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from docflow.analyze import Analysis, RuleBasedAnalyzer
from docflow.extract import extract_text
from docflow.naming import build_filename, sanitize, strip_accents
from docflow.pipeline import _link_or_rename, _unique
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
    for it in Item.objects.filter(result_path__startswith=prefix):
        if it.result_path == prefix or it.result_path.startswith(prefix + os.sep):
            it.result_path = str(new) + it.result_path[len(prefix):]
            it.save(update_fields=["result_path"])


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
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
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
def make_folder(parent: str, name: str) -> dict:
    root, folder = s._library_target(parent)
    if not folder.is_dir():
        raise s.ApiError("folder refused")
    new = folder / _clean_name(name)
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


# ------------------------------------------------------------------ re-filing a PDF from its fields
def _plan_from(fields: dict, rel_dir: str, final_name: str) -> dict:
    c = s.cfg()
    d: dict = {k: fields.get(k) for k in FIELDS if fields.get(k) not in (None, "")}
    d.setdefault("detail", "")
    amount = d.pop("amount", None)
    try:
        if amount is not None:
            amount = Decimal(str(amount).replace(",", "."))
        a = Analysis.model_validate({**d, "amount": amount, "include_amount": amount is not None})
    except (InvalidOperation, ValueError) as e:
        raise s.ApiError(f"value rejected: {e}") from None
    name = dest = ""
    if final_name:
        name = sanitize(final_name)
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


def apply(rel: str, fields: dict, rel_dir: str = "", final_name: str = "") -> dict:
    root, p = _entry(rel)
    out = plan(rel, fields, rel_dir, final_name)
    if not out["final_name"] or not out["rel_dir"]:
        raise s.ApiError("company, type and destination are required before approving")
    folder = safe_join(root, out["rel_dir"])
    if (root / TRASH) in (folder, *folder.parents):
        raise s.ApiError("use Delete to put something in the trash")
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / out["final_name"]
    if dst != p:
        _move(p, dst)
    return {"path": _rel(root, dst)}
