"""Helps complete companies.yaml: for PDFs whose company is not recognised, groups their first
lines of text (the issuer usually opens the document). Read-only, nothing is kept.
usage: PYTHONPATH=backend uv run python scripts/discover.py FOLDER [--limit N]"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.extract import extract_text
from docflow.fields import norm

cfg = load_config()
an = RuleBasedAnalyzer(cfg)


def head(path: Path) -> tuple[str, str | None, str]:
    """(file name, first lines / "__known__" / None when unreadable, the cause when unreadable)."""
    try:  # the reading AND the analysis: one text that makes analyze() or norm() raise must not end a run over hundreds of PDFs
        text = extract_text(path, cfg.settings["ocr"]).text
        if an.analyze(text).company:
            return path.name, "__known__", ""
        lines = [re.sub(r"\s+", " ", norm(x)).strip() for x in text.split("\n")]
    except Exception as e:  # the cause is kept and shown in the summary: a general failure must not look like corrupt PDFs
        return path.name, None, f"{type(e).__name__}: {e}"
    good = [x for x in lines if len(x) >= 4 and re.search(r"[^\W\d_]{3}", x)]  # 3 letters of ANY alphabet, not digits or marks
    return path.name, " | ".join(good[:2])[:90] if good else "", ""


def positive_int(text: str) -> int:
    """An argparse type: a whole number of at least 1 (a slice by a negative or zero limit gives a misleading listing)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{value} is not at least 1")
    return value


def cause_key(cause: str) -> str:
    """A failure without what is specific to one file (its path, its numbers): the same general breakdown (OCR missing, a bad
    setting) on five files is ONE cause, not five."""
    return re.sub(r"\d+", "#", re.sub(r"(?:[A-Za-z]:)?[\\/][^\s'\"()]+", "<path>", cause))


def main(root: Path, limit: int = 45) -> None:
    files = sorted(f for f in root.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf")  # .PDF too (scanners)
    groups = defaultdict(list)
    causes: Counter[str] = Counter()
    first_file: dict[str, str] = {}
    example: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as ex:
        for done, (f, (_, h, cause)) in enumerate(zip(files, ex.map(head, files)), 1):
            if done % 25 == 0 or done == len(files):  # OCR makes this slow: say how far it got, on stderr (the report stays on stdout)
                print(f"  {done}/{len(files)} read", file=sys.stderr, flush=True)
            name = f.relative_to(root).as_posix()  # with its folder: same-named files in different folders must be told apart
            if cause:
                same = cause_key(cause)  # grouped without the file's own path and numbers, shown with one real example
                causes[same] += 1
                first_file.setdefault(same, name)
                example.setdefault(same, cause)
            if h and h != "__known__":
                groups[re.sub(r"\d+", "#", h.lower())].append(name)
            elif h is None:
                groups["[unreadable]"].append(name)
            elif h == "":  # readable, but no line with real words: still a document to deal with, so it is counted
                groups["[no text]"].append(name)
    unreadable = len(groups.get("[unreadable]", []))  # their company is unknown, not missing: a separate problem
    without = sum(len(v) for k, v in groups.items() if k != "[unreadable]")
    print(f"{len(files)} PDFs; without company: {without}; unreadable: {unreadable}; groups: {len(groups) - (1 if unreadable else 0)}\n")
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for key, names in ranked[:limit]:
        print(f"{len(names):>3}  {key[:88]:<88}  e.g.: {names[0]}")
    if len(ranked) > limit:  # the list is cut: say by how much, or the maintainer thinks the list is complete
        hidden = ranked[limit:]
        print(f"... {len(hidden)} more groups ({sum(len(n) for _, n in hidden)} files) not shown; use --limit to see more")
    if causes:
        print("\nwhy files were unreadable:")
        for same, n in causes.most_common(5):
            print(f"{n:>3}  {example[same][:150]}  (e.g. {first_file[same]})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Group the first lines of the PDFs whose company is not recognised.")
    parser.add_argument("folder", metavar="FOLDER", type=Path)
    parser.add_argument("--limit", type=positive_int, default=45, help="how many groups to list, at least 1 (default 45)")
    args = parser.parse_args()
    if not args.folder.is_dir():  # a typo would otherwise be reported as a successful run over 0 PDFs
        parser.error(f"not a folder: {args.folder}")
    main(args.folder, args.limit)
