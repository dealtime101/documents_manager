"""Compare the engine to your existing file names (expected answers), on the corpus built by build_corpus.py.
usage: PYTHONPATH=backend uv run python scripts/benchmark.py score CACHE
       PYTHONPATH=backend uv run python scripts/benchmark.py mine CACHE COMPANY"""
import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.fields import norm, parse_number
from docflow.naming import strip_accents
from docflow.pipeline import resolve_destination, status_for

SEP = re.compile(r"\s[-–—]\s+")
# an amount ALONE as the last part of a name: optional minus, digits with optional thousands separators (space, NBSP,
# comma or dot), a decimal separator and exactly two digits, optional currency
AMT = re.compile(r"^(-?)(\d[\d   .,]*?[.,]\d{2})[\s  ]*(\$|CAD|USD|EUR)?$")
# A WHOLE amount ("150 $", "1 200 $", "1,200 $"): only with a currency (a bare number may be a year) and with no decimal
# separator, like the engine's own whole amounts. "150.5 $" and "1.200 $" cannot be read with certainty: not accepted.
WHOLE = re.compile(r"^(-?)(\d{1,3}(?:[   ,]\d{3})+|\d+)[\s  ]*(\$|CAD|USD|EUR)$")
# the ending was meant as an amount: a decimal pair, or a number glued to a currency
LOOKS_LIKE_AMOUNT = re.compile(r"\d[.,]\d{2}(?!\d)|\d[\s  ]*(\$|CAD|USD|EUR)\s*$")
STOP = {  # words too common to tell one type of document from another
    "de", "la", "le", "les", "des", "du", "et", "en", "un", "une", "au", "aux",
    "pour", "par", "sur", "dans", "que", "qui", "est", "the", "and", "of", "to", "for", "with", "from", "this",
}


# variants of the same company in existing names (merged as in companies.yaml)
SAME = {"collegemultihexa": "multihexa", "croixbleue": "croixbleuemedavie", "operationenfantsoleil": "enfantsoleil",
        "syndicats264626482650": "syndicat2646", "syndicat2646eauxvives": "syndicat2646", "blackwells": "blackwell"}


def key(s: str | None) -> str:
    k = re.sub(r"[^a-z0-9]", "", strip_accents(s or "").lower())
    return SAME.get(k, k)


TYPE_SAME = {"visa": "relevevisa", "relevedecompte": "relevecompte"}  # spelling variants of the same type


def tkey(s: str | None) -> str:
    k = re.sub(r"[^a-z0-9]", "", strip_accents(s or "").lower())
    return TYPE_SAME.get(k, k)


def pc(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "n/a"


def name_amount(part: str) -> str | None:
    """The amount written alone in a name part, normalised ('1 234,56 $' -> '1234.56'), or None if it is not one."""
    m = AMT.match(part.strip())
    value = parse_number(m.group(2).replace(" ", " ").replace(" ", " ")) if m else None  # (narrow) NBSP: French style
    if m and value is not None:
        return f"{m.group(1)}{value}"
    whole = WHOLE.match(part.strip())
    if whole:
        return f"{whole.group(1)}{int(re.sub(r'[^0-9]', '', whole.group(2)))}.00"
    return None


def name_currency(part: str) -> str | None:
    """The currency written after the amount in a name part ('158.98$' -> CAD, '100.00 USD' -> USD), None when none is written
    (then the name expects no particular currency)."""
    m = re.search(r"(\$|CAD|USD|EUR)\s*$", part.strip())
    return None if not m else "CAD" if m.group(1) == "$" else m.group(1)


def load(cache: Path, left_out: Counter | None = None) -> list[dict]:
    """The usable documents. `left_out`, if given, receives how many entries were dropped and why (never silently)."""
    rows, left_out = [], left_out if left_out is not None else Counter()
    for r in json.loads((cache / "index.json").read_text(encoding="utf-8")):
        left_out["entries"] += 1
        if "error" in r:
            left_out["extraction error"] += 1
            continue
        k = r.get("key")
        if not (isinstance(k, str) and k not in ("", ".", "..") and Path(k).name == k):  # a path would read outside the cache
            left_out["key is not a plain file name"] += 1
            continue
        if not (cache / f"{r['key']}.txt").exists():
            left_out["text missing"] += 1
            continue
        parts = SEP.split(Path(r["name"]).stem)  # not [:-4]: that assumes a 3-letter extension
        if len(parts) < 3:
            left_out["name not in the standard form"] += 1
            continue
        amount = name_amount(parts[-1])
        r.update(date=parts[0].strip(), company=parts[1].strip(), type=parts[2].strip(), amount=amount,
                 # an ending that looks like an amount but was not read must not silently leave the amount score
                 amount_unread=amount is None and len(parts) > 3 and bool(LOOKS_LIKE_AMOUNT.search(parts[-1])),
                 text=(cache / f"{r['key']}.txt").read_text(encoding="utf-8"))
        rows.append(r)
    return rows


def auto_errors(co: bool | None, ty: bool | None, da: bool, am: bool | None) -> list[str]:
    """Fields that are wrong for a document filed automatically. company/type are None when nothing was recognised
    (an error: the answer is missing); amount is None when the name has no reference amount (nothing to compare)."""
    return [k for k, ok in (("company", co is True), ("type", ty is True), ("date", da), ("amount", am is not False)) if not ok]


def score(cache: Path) -> None:
    cfg = load_config()
    an = RuleBasedAnalyzer(cfg)
    left_out: Counter = Counter()
    rows = load(cache, left_out)
    n: Counter[str] = Counter()  # the figures of the report: total, company_found, date_ok, auto, confirm, manual...
    danger: list[tuple[str, list[str]]] = []  # (name, wrong fields) of every document filed automatically with an error
    type_missing: Counter[str] = Counter()  # company recognised, type not: company -> number of documents
    comp_missing: Counter[str] = Counter()  # company not recognised: the company written in the name -> number of documents
    for r in rows:
        a = an.analyze(r["text"])
        n["total"] += 1
        co = key(a.company) == key(r["company"]) if a.company else None
        ty = tkey(a.document_type) == tkey(r["type"]) if a.document_type else None
        da = a.date == r["date"]
        am = None if not r["amount"] else (a.amount is not None and a.amount == Decimal(r["amount"]))
        n["company_found"] += a.company is not None
        n["company_ok"] += bool(co)
        n["type_found"] += a.document_type is not None
        n["type_ok"] += bool(ty)
        n["date_ok"] += da
        if r["amount"]:
            n["amount_total"] += 1
            n["amount_ok"] += bool(am)
        if not a.company:
            comp_missing[r["company"]] += 1
        elif not a.document_type:
            type_missing[a.company] += 1
        # the engine's own decision (shared functions, configured thresholds): no destination means never auto
        _, dest_conf, _ = resolve_destination(cfg, a)
        status = status_for(min(a.confidence, dest_conf), cfg.settings["thresholds"],
                            has_name=bool(a.company and a.document_type))
        if status == "auto":
            n["auto"] += 1
            bad = auto_errors(co, ty, da, am)
            if bad:
                danger.append((r["name"][:80], bad))
        elif status == "confirm":
            n["confirm"] += 1
        else:
            n["manual"] += 1
    t = n["total"]
    print(f"{t} documents")
    reasons = ", ".join(f"{left_out[k]} {k}" for k in ("extraction error", "text missing", "name not in the standard form")
                        if left_out[k]) or "nothing"
    print(f"  {left_out['entries']} index entries, {t} scored; left out: {reasons}; rates cover the scored documents only")
    print(f"  company recognised : {pc(n['company_found'], t)} (correct: {pc(n['company_ok'], n['company_found'])})")
    print(f"  type recognised    : {pc(n['type_found'], t)} (correct: {pc(n['type_ok'], n['type_found'])})")
    print(f"  exact date         : {pc(n['date_ok'], t)}")
    print(f"  exact amount       : {pc(n['amount_ok'], n['amount_total'])}")
    unread = [r["name"] for r in rows if r["amount_unread"]]
    print(f"  amount-like but not read (left out of the amount score): {len(unread)}"
          + (f"  e.g. {[u[-40:] for u in unread[:3]]}" if unread else ""))
    print(f"  => auto {n['auto']} | confirm {n['confirm']} | manual {n['manual']}")
    print(f"  ERRORS WITH CONFIDENCE >= {cfg.settings['thresholds']['auto']:.0%}: {len(danger)}")  # the configured "auto" threshold
    for d in danger[:12]:
        print("    ", d)
    print("\nunknown company (archive names):", comp_missing.most_common(14))
    print("known company but unknown type:", type_missing.most_common(14))


def mine(cache: Path, company: str) -> None:
    left_out: Counter = Counter()
    everything = load(cache, left_out)
    rows = [r for r in everything if key(r["company"]) == key(company)]
    dropped = ", ".join(f"{n} {why}" for why, n in left_out.items() if why != "entries")
    if dropped:  # as score does: an entry that does not take part is said, never silent
        print(f"({left_out['entries']} index entries; left out: {dropped})")
    if not rows:
        known = sorted({r["company"] for r in everything})
        close = difflib.get_close_matches(company, known, n=5, cutoff=0.5) or known[:5]
        print(f"no document of {company!r} in this corpus. Closest companies: {close}")
        return
    # grouped by tkey, like the score: "Visa" and "ReleveVisa" are ONE type, not counter-examples of each other
    by_type: defaultdict[str, list] = defaultdict(list)
    labels: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_type[tkey(r["type"])].append(set(re.findall(r"[a-z]{4,}", norm(r["text"]).lower())) - STOP)
        labels[tkey(r["type"])][r["type"]] += 1
    print(f"{company}: {len(rows)} documents, {len(by_type)} types")
    # In how many documents each word appears: per type, and in all. Counted ONCE, so the words of the other types are not
    # scanned again for every word of every type (that was words x documents x types, minutes on a big company).
    per_type = {g: Counter(w for d in docs for w in d) for g, docs in by_type.items()}
    overall: Counter[str] = Counter()
    for counts in per_type.values():
        overall.update(counts)
    n_all = sum(len(docs) for docs in by_type.values())
    for group, docs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        t = labels[group].most_common(1)[0][0]  # the spelling used most often, for display
        n_others = n_all - len(docs)
        words = []
        for w, in_group in per_type[group].items():
            inside = in_group / len(docs)
            outside = ((overall[w] - in_group) / n_others) if n_others else 0
            if inside >= 0.7 and outside <= 0.15:
                words.append((inside - outside, w))
        print(f"  {t[:50]:<50} ({len(docs)}) -> {[w for _, w in sorted(words, reverse=True)[:7]]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("score", help="measure the engine against the names (CACHE built by build_corpus.py)").add_argument("cache", type=Path)
    mine_p = sub.add_parser("mine", help="words that distinguish the types of one company")
    mine_p.add_argument("cache", type=Path)
    mine_p.add_argument("company")
    args = ap.parse_args(argv)
    if not (args.cache / "index.json").is_file():  # not a traceback: say what is missing and how to get it
        print(f"ERROR: no index.json in {args.cache}: build the corpus first (scripts/build_corpus.py ARCHIVE_ROOT {args.cache})")
        return 2
    score(args.cache) if args.command == "score" else mine(args.cache, args.company)
    return 0


if __name__ == "__main__":
    sys.exit(main())
