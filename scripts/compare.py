"""Compare the engine to the names the user ALREADY set (ground truth). Never touches the PDFs, but it does save the text
it extracts from each one as <name>.txt (+ <name>.txt.key) beside the samples, because OCR is slow: delete them any time.
If the folder cannot be written the comparison still runs, only the texts are not saved (and the report says so).
usage: PYTHONPATH=backend uv run python scripts/compare.py SAMPLE_FOLDER [--fresh]
       (std/ = files following the standard; --fresh ignores the saved texts and extracts everything again)"""
import argparse
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from benchmark import (  # the one reader of the amount written in a name (run from scripts/ or PYTHONPATH=scripts)
    LOOKS_LIKE_AMOUNT,
    name_amount,
    name_currency,
)
from docflow import extract as extractor
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.extract import extract_text
from docflow.fields import find_amount, find_date, norm
from docflow.fsutil import write_atomic


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "n/a"


def cache_key(pdf: Path, ocr: dict) -> str:
    """Fingerprint of everything the saved text depends on: the PDF bytes, the OCR settings and the extractor code."""
    return extractor.extraction_fingerprint(pdf, ocr)


def saved_method(cache: Path, key_file: Path, key: str) -> str | None:
    """The extraction method recorded with a saved text, if that text is still valid for this PDF, these OCR settings and
    this extractor (the stamp holds the fingerprint AND the method); None otherwise (missing, stale, or the old format)."""
    try:
        stamp = json.loads(key_file.read_text(encoding="utf-8"))
        if stamp["key"] == key and cache.exists():
            return str(stamp["method"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def main(root: Path, fresh: bool = False) -> int:
    """0 = done, 2 = refused: there is no std/ folder of samples under `root`."""
    if not (root / "std").is_dir():
        print(f"ERROR: no std/ folder in {root} (it must hold the sample PDFs named <n>__<real file name>)")
        return 2
    cfg = load_config()
    an = RuleBasedAnalyzer(cfg)
    meth: Counter[str] = Counter()  # extraction method -> number of samples ('error' included)
    date_ok = date_tot = amt_ok = amt_tot = comp_ok = comp_tot = 0
    bad_date, bad_amt, bad_comp, empty, failures = [], [], [], [], []
    skipped = unsaved = unreadable = amount_unread = 0
    # not glob("*.pdf"): it is case-sensitive on Linux and would silently leave out the .PDF files scanners write
    for f in sorted(p for p in (root / "std").iterdir() if p.suffix.lower() == ".pdf" and p.is_file()):
        _, sep, name = f.name.partition("__")  # sample files are named <n>__<real file name>
        parts = name[:-4].split(" - ")
        if not sep or len(parts) < 3:
            skipped += 1
            continue
        # What the NAME says the engine should find: counted for every file, whatever happens to its text afterwards
        # (an unreadable or empty document is a miss, not a document that does not count).
        expect_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]))
        expected_amount = name_amount(parts[-1])  # '1,234.56$', '12,34 $', '150 $' too, not only '158.98$'
        amount_unread += expected_amount is None and bool(LOOKS_LIKE_AMOUNT.search(parts[-1]))  # meant as an amount, not readable
        expect_company = parts[1] in cfg.companies
        date_tot += expect_date
        amt_tot += expected_amount is not None
        comp_tot += expect_company
        cache = f.with_suffix(".txt")  # OCR is slow: text kept next to the sample (local, disposable)
        key_file, key = cache.with_name(cache.name + ".key"), cache_key(f, cfg.settings["ocr"])
        saved = None if fresh else saved_method(cache, key_file, key)  # the ORIGINAL method of a still-valid saved text
        if saved is not None:
            try:
                text, method = cache.read_text(encoding="utf-8"), saved
            except (OSError, UnicodeDecodeError):  # the key vouches for the PDF and the settings, not for the bytes on disk
                unreadable += 1
                saved = None  # read it again below, and save it again
        if saved is None:
            try:
                ex = extract_text(f, cfg.settings["ocr"])
            except Exception as e:  # counted as a miss in every rate (DOC468.240) AND named in the report
                meth["error"] += 1
                failures.append((name, f"{type(e).__name__}: {str(e)[:80]}"))
                continue
            text, method = ex.text, ex.method
            if not ex.missing_pages:  # pages lost to a timeout or a failure: that gap is not the answer, never remember it
                try:  # text first, key last: a key only ever vouches for a COMPLETE text
                    write_atomic(cache, text)
                    write_atomic(key_file, json.dumps({"key": key, "method": method}))
                except OSError:  # read-only or full folder: this run is unaffected, the text is simply not saved
                    unsaved += 1
        meth[method] += 1
        if not text.strip():
            empty.append(name)
            continue
        t = norm(text)
        if expect_date:
            d = find_date(t)
            if d and d.text == parts[0]:
                date_ok += 1
            else:
                bad_date.append((name, d.text if d else None, d.kind if d else None, d.confidence if d else 0.0))
        if expected_amount is not None:
            a = find_amount(t)
            expected_currency = name_currency(parts[-1])  # None: the name says no currency, so none is expected
            if a and a.value == Decimal(expected_amount) and (expected_currency is None or a.currency == expected_currency):
                amt_ok += 1
            else:
                shown = (f"{a.value} {a.currency}" if a.value == Decimal(expected_amount) else str(a.value)) if a else None
                bad_amt.append((name, shown, a.confidence if a else None))  # the currency is shown when the NUMBER was right
        if expect_company:
            found = an.analyze(text).company
            if found == parts[1]:
                comp_ok += 1
            else:
                bad_comp.append((name, parts[1], found))  # (file, company expected from its name, company found or None)

    print("extraction:", dict(meth), "| PDFs with no usable text after extraction (OCR included):", len(empty), f"| skipped {skipped}")
    print("(rates below count a file with no usable text, or whose extraction failed, as a miss)")
    if unreadable:
        print(f"({unreadable} saved text(s) could not be read (corrupt file): extracted again)")
    if unsaved:
        print(f"({unsaved} extracted text(s) could not be saved next to the samples: the folder is read-only or full;"
              " they will be extracted again next time)")
    print("exact full date      :", pct(date_ok, date_tot))
    print("exact amount         :", pct(amt_ok, amt_tot))
    if amount_unread:
        print(f"({amount_unread} amount-like name(s) not read: left out of the amount rate, e.g. '790.70Net')")
    print("company (config)     :", pct(comp_ok, comp_tot))
    sure = sum(1 for r in bad_date if r[3] >= 0.95)
    mid = sum(1 for r in bad_date if 0.80 <= r[3] < 0.95)
    print(f"WRONG dates with confidence >=95% (auto): {sure} | 80-94% (confirm): {mid}"
          f" | <80% (manual): {len(bad_date) - sure - mid}")
    for title, rows in (("WRONG DATES", bad_date), ("WRONG AMOUNTS", bad_amt), ("WRONG COMPANIES", bad_comp)):
        print(f"\n{title} (max 10)")
        for r in rows[:10]:
            print("  ", r)
    print("\nNO TEXT (max 8):", [e[:60] for e in empty[:8]])
    if failures:
        print(f"\nEXTRACTION ERRORS ({len(failures)}, max 10; each counts as a miss in the rates above)")
        for name, why in failures[:10]:
            print("  ", name, "->", why)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare the engine to the names already set on a folder of sample PDFs.")
    parser.add_argument("folder", metavar="SAMPLE_FOLDER", type=Path, help="holds std/ (files named <n>__<real file name>)")
    parser.add_argument("--fresh", action="store_true", help="ignore the saved texts and extract everything again")
    args = parser.parse_args()
    sys.exit(main(args.folder, fresh=args.fresh))
