"""docflow [--version] [--config DIR] [--sandbox DIR] COMMAND
  scan [--dry-run] [--interactive] [--ollama] [--source DIR] [-r | --recursive] [--table]
  undo [ID]
  history
--sandbox DIR works on a throw-away copy (inbox/, library/, quarantine/ and the database live in DIR); `docflow COMMAND --help`
lists what each option does."""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .analyze import OllamaAnalyzer, RuleBasedAnalyzer
from .config import Config, load_config
from .db import DB
from .naming import FORBIDDEN
from .pipeline import Proposal, apply, propose, undo

log = logging.getLogger(__name__)


def show(p: Proposal, cfg: Config) -> None:
    a = p.analysis
    amt = f"{a.amount} {a.currency}" if a and a.amount is not None else "-"
    dest = f"{cfg.path('library_root')}/{p.rel_dir}" if p.rel_dir else "[no rule]"
    print(f"\nFile:          {p.source.name}\nDetected:      {a.company if a else '?'}\n"
          f"Type:          {a.document_type if a else '?'}\nDate:          {a.date if a else '?'}\n"
          f"Detail:        {a.detail if a else ''}\nAmount:        {amt}\nProposed name: {p.final_name or '[none]'}\n"
          f"Destination:   {dest}\nConfidence: {p.confidence:.0%}   Status: {p.status}   Extraction: {p.extraction}")
    for n in p.notes:
        print(f"  ! {n}")


def typed_name(raw: str) -> str | None:
    """A hand-typed file name made usable: trimmed, '.pdf' added when missing. None if it cannot be a plain file name
    (path separators, '..', Windows-forbidden characters, nothing left): the same rule apply() enforces."""
    n = raw.strip()
    if not n or FORBIDDEN.search(n) or n.strip(" .") == "":
        return None
    return n if n.lower().endswith(".pdf") else n + ".pdf"


def ask(cfg: Config, p: Proposal) -> str | None:
    """[A]pprove / [M]odify the name / [I]gnore -> final name, or None if ignored."""
    while True:
        c = input("[A]pprove [M]odify [I]gnore ? ").strip().lower()[:1]
        if c == "a":
            if p.final_name:
                return p.final_name
            print("  There is no proposed name: use [M]odify to type one.")  # approving nothing would fail afterwards
        if c == "m":
            raw = input("New name (.pdf added if missing): ")
            n = typed_name(raw)
            if n:
                return n
            if raw.strip():
                print(f"  Invalid name: {raw.strip()!r} (no folders, no '..', none of < > : \" / \\ | ? *).")
        if c == "i":
            return None
        if c not in ("a", "m"):
            print("  Please answer A, M or I.")  # a mistyped key is told, not swallowed


def row(p: Proposal) -> str:
    a = p.analysis
    return (f"{p.status:<17} {p.confidence:>4.0%} | {a.company if a else '-'} | {a.document_type if a else '-'} | "
            f"{a.date if a else '-'} | {a.amount if a and a.amount is not None else '-'} | {p.source.name}")


def _left_over(files: list[Path], i: int) -> tuple[int, int]:
    """(PDFs, other files) that stay exactly where they are when the run stops at files[i]: that file and the following ones."""
    rest = files[i:]
    return (sum(1 for g in rest if g.suffix.lower() == ".pdf"), sum(1 for g in rest if g.suffix.lower() != ".pdf"))


def scan(cfg: Config, db: DB, dry: bool, interactive: bool, ollama: bool,
         source: Path | None = None, recursive: bool = False, table: bool = False) -> int:
    an = RuleBasedAnalyzer(cfg)
    fb = None
    if ollama:
        o = cfg.settings.get("ollama") or {}
        if not o.get("model"):
            print("ERROR: --ollama needs `ollama.model` in config/settings.yaml")
            return 2
        try:
            fb = OllamaAnalyzer(o["model"], o.get("host", "http://127.0.0.1:11434"), types=cfg.types)
        except ValueError as e:  # e.g. a host that is not localhost: refused before any document is sent
            print(f"ERROR: {e}")
            return 2
    inbox = source or cfg.path("inbox")
    if not inbox.is_dir():  # a typo or an unmounted share must not look like "scanned, nothing to do"
        print(f"ERROR: not a folder: {inbox}")
        return 2
    files = sorted(f for f in (inbox.rglob("*") if recursive else inbox.glob("*")) if f.is_file())
    done = held = failed = skipped = analysed = 0
    seen: set[str] = set()  # hashes already seen in THIS batch (a dry run records nothing in the database)
    interrupted: BaseException | None = None
    for i, f in enumerate(files):
        if f.suffix.lower() != ".pdf":
            skipped += 1  # counted in the summary even when --table hides the line
            if not table:
                print(f"\nSkipped (type not handled in Phase 1): {f.name}")
            continue
        try:
            p = propose(f, cfg, db, an, fb)
        except KeyboardInterrupt as e:  # Ctrl-C while a file is being read: stop, and still account for the batch
            interrupted = e
            pdfs, others = _left_over(files, i)
            held += pdfs
            skipped += others - (f.suffix.lower() != ".pdf")
            print("\nInterrupted: nothing else will be filed.")
            break
        except Exception as e:  # one broken file (database, analyser, value error) must not stop the batch
            held += 1  # nothing was done with it: it stays where it is, like any other pending file
            failed += 1
            outcome = f"ERROR: {type(e).__name__}: {e}"
            print(f"{'error':<17} {'':>4} | - | - | - | - | {f.name} | {outcome}" if table else f"\n{f.name}\n  -> {outcome}")
            log.error("ORIGINAL=%s STATUS=ERROR %s: %s", f.name, type(e).__name__, e)
            continue
        if dry and p.sha256 in seen and p.status != "duplicate":
            p.status = "duplicate"
            p.notes.append("Identical to another file in the same batch (SHA-256).")
        seen.add(p.sha256)
        failed += p.status == "error"  # unreadable file, even in a dry run
        if p.status == "error":
            log.error("ORIGINAL=%s STATUS=ERROR %s", f.name, "; ".join(p.notes))

        def report(outcome: str, p: Proposal = p) -> None:  # p bound at definition: it is this file's, whatever the loop does later
            """Table mode: ONE line per file, the outcome as its last column. Otherwise the detail block, then '-> outcome'."""
            print(f"{row(p)} | {outcome}", flush=True) if table else print(f"  -> {outcome}")

        if not table:
            show(p, cfg)
        elif dry:
            report("dry-run (nothing moved)")  # the same last column as a real run, so the output has one shape
        if dry:
            analysed += 1  # nothing moves in a dry run: "analysed", not "processed", so the line still adds up
            continue
        try:
            if p.status in ("auto", "duplicate"):
                dst = apply(p, cfg, db)
            elif interactive and p.status in ("confirm", "manual", "logical_duplicate") and p.analysis and p.rel_dir:
                if table:
                    show(p, cfg)  # the table prints nothing before the outcome: never ask to approve what is not on screen
                try:
                    name = ask(cfg, p)
                except (EOFError, KeyboardInterrupt) as e:  # stdin closed, Ctrl-D or Ctrl-C: stop, but still account for the batch
                    interrupted = e
                    pdfs, others = _left_over(files, i)  # this file and the following ones stay exactly where they are
                    held += pdfs
                    skipped += others - (f.suffix.lower() != ".pdf")
                    print("\nInterrupted: nothing else will be filed.")
                    break
                if name is None:
                    held += 1
                    report(f"left in {f.parent} (not confirmed)")
                    continue
                dst = apply(p, cfg, db, final_name=name, confirmed=True)  # the user answered [A]pprove or typed a name
            else:
                held += 1
                if p.status == "error":  # nothing to validate: the file itself has to be fixed or replaced
                    report(f"left in {f.parent} (unreadable: {'; '.join(p.notes) or 'unknown cause'})")
                else:
                    report(f"left in {f.parent} (validation required)")  # the real folder: --source may point elsewhere
                continue
            done += 1
            report(str(dst))
        except KeyboardInterrupt as e:  # Ctrl-C while a file is being moved: the move itself is atomic and checked, but say so
            interrupted = e
            pdfs, others = _left_over(files, i)
            held += pdfs
            skipped += others - (f.suffix.lower() != ".pdf")
            print(f"\nInterrupted: nothing else will be filed. {f.name} may already be filed: see `docflow history`.")
            break
        except (OSError, ValueError, sqlite3.Error) as e:  # sqlite3.Error: a locked or broken history is this file's failure, not the batch's
            held += 1
            failed += 1
            report(f"ERROR: {e}")
            log.error("ORIGINAL=%s STATUS=ERROR %s: %s", f.name, type(e).__name__, e)  # an unattended run must leave a trace
    handled = f"{analysed} analysed" if dry else f"{done} processed"
    print(f"\n{len(files)} file(s); {handled}, {held} pending" + (f", {skipped} skipped (not PDF)" if skipped else "")
          + (f", {failed} FAILED" if failed else "")
          + (" [DRY-RUN: nothing moved]" if dry else "") + (" [INTERRUPTED]" if interrupted else ""))
    if isinstance(interrupted, KeyboardInterrupt):
        return 130  # the shell convention for "stopped by Ctrl-C"
    return 1 if failed or interrupted else 0  # a cron or script must be able to tell that something went wrong


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="docflow")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--config", help="configuration folder")
    ap.add_argument("--sandbox", type=Path, help="sandbox: inbox/, library/, quarantine/ and the database are created "
                                                 "in this folder; the real archive is not touched")
    sub = ap.add_subparsers(dest="cmd", required=True, title="commands")
    s = sub.add_parser("scan", help="analyse the PDFs of the Inbox and file them", description="Analyse the PDFs of the Inbox.")
    s.add_argument("--dry-run", action="store_true", help="only look: analyse and print, move nothing")
    s.add_argument("--interactive", action="store_true",
                   help="file the sure ones, ask [A]pprove / [M]odify / [I]gnore for the others")
    s.add_argument("--ollama", action="store_true", help="fallback to a LOCAL model (localhost only)")
    s.add_argument("--source", type=Path, help="folder to process instead of the Inbox (e.g. In_Work)")
    s.add_argument("-r", "--recursive", action="store_true", help="also read the sub-folders of the source")
    s.add_argument("--table", action="store_true", help="one line per file")
    u = sub.add_parser("undo", help="put a filed document back where it came from", description="Undo a filing.")
    u.add_argument("id", nargs="?", type=int, help="number of the operation to undo (see history); the last one by default")
    sub.add_parser("history", help="list the latest operations, with their numbers", description="List the latest operations.")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if (args.sandbox and args.cmd == "scan" and args.source and not args.dry_run
            and not args.source.resolve().is_relative_to(args.sandbox.resolve())):
        # the sandbox promises that the real files are untouched, but a scan MOVES what it files out of its source folder
        ap.error("--sandbox with a --source outside the sandbox would move the files of that folder: "
                 "add --dry-run to only look, or copy them into the sandbox's inbox/")

    cfg = load_config(args.config, sandbox=args.sandbox)
    if args.sandbox:
        (args.sandbox / "inbox").mkdir(parents=True, exist_ok=True)
        print(f"[SANDBOX] {args.sandbox.resolve()}")
    log_path = cfg.path("log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)s %(message)s")
    db = DB(cfg.path("db"))
    if args.cmd == "scan":
        return scan(cfg, db, args.dry_run, args.interactive, args.ollama, args.source, args.recursive, args.table)
    if args.cmd == "undo":
        try:
            cur, old = undo(db, args.id)
        except (ValueError, OSError) as e:
            print(f"Cannot undo: {e}")
            return 1
        print(f"Restored: {cur.name} -> {old}")
        return 0
    for r in db.history():
        print(f"#{r['id']} {r['ts']} {r['kind']}{' (undone)' if r['undone'] else ''}: {Path(r['src']).name} -> {r['dst']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
