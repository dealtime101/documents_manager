"""Test bench: reads (OCR if needed) the archive PDFs whose NAME already follows the standard, and keeps their text
in a disposable LOCAL folder (never in the repository). The file name serves as the expected answer.
usage: PYTHONPATH=backend uv run python scripts/build_corpus.py ARCHIVE_ROOT CACHE_FOLDER [--fresh]
A saved text is reused only if its PDF, the OCR settings and the extractor are unchanged (--fresh: extract everything).
Left out on purpose: files under a folder whose name starts with "@" (the NAS's own folders: @Recycle, @eaDir, thumbnails), and
files whose name does not follow the standard. A folder that merely CONTAINS an "@" (team@2024) is read."""
import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docflow.config import load_config
from docflow.extract import extract_text, extraction_fingerprint
from docflow.fsutil import write_atomic

STD = re.compile(r"^(\d{4}(-\d{2}(-\d{2})?)?|XXXX)\s[-–—]\s")


def entry_key(rel: str) -> str:
    """The name of a cache entry: a SHA-256 of the relative path (it only names files; the benchmark reads it from the index)."""
    return hashlib.sha256(rel.encode()).hexdigest()[:16]


def adopt_old_names(cache: Path) -> int:
    """Entries written under another key (the previous version used a SHA-1 of the path) are RENAMED to the current key, using
    the index that lists both, so the slow part (the extracted texts) is not done again. Returns how many were adopted."""
    try:
        old_rows = json.loads((cache / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    adopted = 0
    for r in old_rows if isinstance(old_rows, list) else []:
        if not isinstance(r, dict):  # a hand-edited or damaged index: that row is left alone, the others are still adopted
            continue
        old, new = r.get("key"), entry_key(str(r.get("rel", "")))
        if not old or old == new or (cache / f"{new}.txt").exists():
            continue
        if (cache / f"{old}.txt").exists() and (cache / f"{old}.txt.key").exists():
            (cache / f"{old}.txt").replace(cache / f"{new}.txt")
            (cache / f"{old}.txt.key").replace(cache / f"{new}.txt.key")  # the stamp last, as everywhere: it vouches for the text
            r["key"] = new
            adopted += 1
    if adopted:  # the index follows the files at once: an interrupted run must not leave it pointing at names that are gone
        write_atomic(cache / "index.json", json.dumps(old_rows, ensure_ascii=False))
    return adopted


def one(args: tuple[Path, Path, Path, bool, dict]) -> dict:  # always an entry: a file that failed carries its error, it is never dropped
    f, root, cache, fresh, ocr = args  # ocr: the OCR settings, read once by main()
    key = entry_key(str(f.relative_to(root)))  # identifies the ENTRY (the benchmark reads it)
    txt, stamp = cache / f"{key}.txt", cache / f"{key}.txt.key"
    try:
        # the saved text is only trusted if it was made from THIS PDF, with these OCR settings and this extractor
        fingerprint = extraction_fingerprint(f, ocr)
        if fresh or not (txt.exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == fingerprint):
            write_atomic(txt, extract_text(f, ocr).text)
            write_atomic(stamp, fingerprint)  # last: a stamp only ever vouches for a COMPLETE text
    except Exception as e:  # "error" stays the type (readers test for its presence); the message is the real cause
        print(f"ERROR {f.relative_to(root)}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return {"key": key, "rel": str(f.relative_to(root)), "name": f.name, "error": type(e).__name__, "message": str(e)}
    return {"key": key, "rel": str(f.relative_to(root)), "name": f.name}


ENTRY_FILE = re.compile(r"^[0-9a-f]{16}\.txt(\.key)?$")  # what this script writes in the cache, and nothing else


def orphans(cache: Path, rows: list[dict]) -> list[Path]:
    """Saved texts and stamps of PDFs that are no longer in the archive (deleted, moved, renamed)."""
    kept = {str(r["key"]) for r in rows}
    return sorted(p for p in cache.iterdir() if ENTRY_FILE.match(p.name) and p.name.split(".")[0] not in kept)


def main(root: Path, cache: Path, fresh: bool = False, prune: bool = False) -> int:
    """0 = done, 1 = done but some entries failed (they carry their error in the index), 2 = refused (nothing created or modified)."""
    if not root.is_dir():  # a typo must not look like "0 documents, success"
        print(f"ERROR: not a folder: {root}", file=sys.stderr)
        return 2
    files = [f for f in root.rglob("*")  # .PDF too: the glob "*.pdf" is case-sensitive on Linux
             if f.suffix.lower() == ".pdf" and f.is_file() and STD.match(f.name)
             and not any(part.startswith("@") for part in f.relative_to(root).parts)]  # @Recycle, @eaDir: the NAS's own folders
    index = cache / "index.json"
    if not files and index.exists() and index.read_text(encoding="utf-8").strip() not in ("", "[]"):
        print(f"ERROR: no PDF following the standard under {root}: the existing index of {cache} is kept", file=sys.stderr)
        return 2
    cache.mkdir(parents=True, exist_ok=True)
    if not fresh and (adopted := adopt_old_names(cache)):
        print(f"{adopted} saved text(s) renamed to the current entry names (not extracted again)", flush=True)
    print(f"{len(files)} PDFs following the standard; reading in progress...", flush=True)
    ocr = load_config().settings["ocr"]  # read here, once the folder is known to be usable: not at import
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, [(f, root, cache, fresh, ocr) for f in files]))
    write_atomic(index, json.dumps(rows, ensure_ascii=False))
    failed = sum(1 for r in rows if "error" in r)
    print(f"done: {len(rows)} entries, {failed} errors", flush=True)
    if stale := orphans(cache, rows):  # the text of a document is private: a copy must not outlive the document unnoticed
        if prune:
            for p in stale:
                p.unlink()
            print(f"{len(stale)} orphan file(s) removed from the cache", flush=True)
        else:  # not deleted by default: an archive that is only partly mounted would otherwise lose slow OCR work
            print(f"{len(stale)} orphan file(s) in the cache (their PDF is gone): --prune removes them", flush=True)
    return 1 if failed else 0  # the index is written either way; the code tells a script or CI that some entries failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read the archive PDFs whose name follows the standard into a local text cache.")
    parser.add_argument("archive_root", metavar="FOLDER", type=Path, help="the archive to read")
    parser.add_argument("cache", metavar="CACHE", type=Path, help="the disposable local folder for the saved texts")
    parser.add_argument("--fresh", action="store_true", help="extract everything again, whatever the cache holds")
    parser.add_argument("--prune", action="store_true", help="delete the saved texts of PDFs that are no longer in the archive")
    args = parser.parse_args()
    sys.exit(main(args.archive_root, args.cache, fresh=args.fresh, prune=args.prune))
