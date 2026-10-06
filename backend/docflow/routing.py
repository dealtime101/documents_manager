"""Where a document goes: YAML table only. The path never comes from an LLM."""
import re
import unicodedata
from pathlib import Path, PurePosixPath

from .naming import valid_date

_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')
# Windows device names, reserved with ANY extension ("Con.txt" too), whatever the case; "COM10" and "Console" are fine
_DEVICE = re.compile(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?")


def _windows_unsafe(segment: str) -> bool:
    """A folder name Windows cannot create or silently changes: a reserved device name, or one ending in a dot or a space
    (stripped there, so two different folders here would become one on the other machines)."""
    return bool(_DEVICE.fullmatch(segment)) or segment != segment.rstrip(" .")


def _is_folder(value: object) -> bool:
    """A destination that names a folder: text with something else than spaces, dots and separators. '', '.', '/' would
    mean the library root itself (documents piling up there without any error)."""
    return isinstance(value, str) and bool(value.strip(" ./\\"))


def _same(name: str) -> str:
    """A company name compared without its case and its spacing ('ACME  Corp ' is 'Acme Corp'; \\u00a0 counts as a space)."""
    # NFKC first: "é" as one character or as e + a combining accent (macOS, many PDFs) is the same name on screen
    return " ".join(unicodedata.normalize("NFKC", name).split()).casefold()


def _entry(routing: dict, company: str | None):
    """The routing entry of a company: the exact key if there is one, else the ONE key that differs only by case or
    spacing. Two look-alikes fit equally well, so none is picked: guessing a folder is worse than asking."""
    if not company:
        return None
    if company in routing:
        return routing[company]
    close = [v for k, v in routing.items() if isinstance(k, str) and _same(k) == _same(company)]
    return close[0] if len(close) == 1 else None


def type_destination_unusable(routing: dict, company: str | None, doc_type: str | None) -> bool:
    """The table HAS an entry for this company and type, but its destination is empty, '.' or not text: a configuration mistake
    (route() then refuses to guess a folder, and the note must say why rather than 'no rule')."""
    c = _entry(routing, company)
    e = _entry(c, doc_type) if isinstance(c, dict) and doc_type else None
    return e is not None and not (isinstance(e, dict) and _is_folder(e.get("destination")))


def route(routing: dict, company: str | None, doc_type: str | None) -> str | None:
    c = _entry(routing, company)
    if not c:
        return None
    if isinstance(c, dict):
        for key in (doc_type, "default"):
            e = _entry(c, key) if key else None  # same tolerance as the company: case and spacing; two look-alikes: no guess
            if e is None:
                continue  # this type is not in the table: next, the company's default
            if isinstance(e, dict) and _is_folder(e.get("destination")):
                return e["destination"]
            if key == doc_type:
                return None  # the type IS configured but its destination is unusable (empty, ".", not text): a mistake to show, not a folder to guess
        if _is_folder(c.get("destination")):
            return c["destination"]
    return None


def unknown_placeholder(rel: str) -> str | None:
    """The first {...} of a destination that is not {year} (the only one that exists), else None. Left alone it would become a
    folder named literally '{month}', and the documents would pile up there with no sign of the mistake."""
    return next((p for p in re.findall(r"\{[^{}]*\}", rel) if p != "{year}"), None)


def fill(rel: str, date: str) -> str | None:
    """Replace {year} with the document's year; None if the template needs a year that is unknown, or holds another {...}."""
    if unknown_placeholder(rel):
        return None
    if "{year}" not in rel:
        return rel
    year = re.match(r"([0-9]{4})(?:-|\Z)", date)  # four ASCII digits that start YYYY, YYYY-MM or YYYY-MM-DD: not "20", not "٢٠٢٥"
    # ...of a date that EXISTS ("2025-foo", "2025-99" and "2025-02-30" are not dates): the year is only trusted from a valid one
    return rel.replace("{year}", year.group(1)) if year and valid_date(date) else None


def safe_join(root: Path, rel: str) -> Path:
    """root/rel, or ValueError if rel escapes root (.., absolute, Windows drive, forbidden characters)."""
    p = PurePosixPath(rel.replace("\\", "/"))
    # no segment at all ('' or '.') is the root itself; a segment of spaces/dots cannot be a folder name on Windows
    if not p.parts or p.is_absolute() or any(x == ".." or _BAD.search(x) or not x.strip(" .") or _windows_unsafe(x) for x in p.parts):
        raise ValueError(f"destination refused: {rel!r}")
    out = (root / Path(*p.parts)).resolve()
    if root.resolve() not in (out, *out.parents):
        raise ValueError(f"destination outside root: {rel!r}")
    return out
