"""Measures a LOCAL Ollama model on documents whose answer is known (existing archive names).
usage: PYTHONPATH=backend uv run python scripts/llm_eval.py CACHE MODEL N
Documents the rules do not recognise are favoured: that is where the model would be used."""
import http.client
import random
import sys
import time
from decimal import Decimal
from pathlib import Path

from benchmark import key, load  # run from scripts/ or with PYTHONPATH=backend:scripts
from docflow.analyze import BadModelAnswer, OllamaAnalyzer, OllamaError, RuleBasedAnalyzer
from docflow.config import load_config

MAX_UNREACHABLE_IN_A_ROW = 3  # after this many server failures in a row there is nothing left to measure


def same_company(answer: str | None, expected: str) -> bool:
    """Equal once normalised (case, accents, spaces, dashes; declared aliases in benchmark.SAME). Never a substring:
    a fragment, or the expected name plus another company, is a wrong answer. Nothing left after normalising = no match."""
    a, e = key(answer), key(expected)
    return bool(a) and a == e


def main(cache: Path, model: str, n: int) -> None:
    if n < 1:  # before anything is read or measured: random.sample would raise a traceback on a negative size
        raise ValueError(f"N must be a whole number of at least 1, got {n}")
    rows = load(cache)
    cfg = load_config()
    an = RuleBasedAnalyzer(cfg)
    hard = [r for r in rows if not an.analyze(r["text"]).company and len(r["text"].strip()) > 80]
    random.seed(7)
    sample = random.sample(hard, min(n, len(hard)))
    llm = OllamaAnalyzer(model, max_chars=3000, types=cfg.types)
    stats = {"json": 0, "company": 0, "date": 0, "amount": 0, "amount_n": 0}
    secs = []
    judged = unreachable = in_a_row = 0
    for r in sample:
        t0 = time.monotonic()  # monotonic: the wall clock can jump (NTP, daylight saving) and give a negative duration
        try:
            a = llm.analyze(r["text"])
        except (OllamaError, OSError, http.client.HTTPException) as e:  # the SERVER failed (down, model missing, HTTP error,
            # a cut or garbled HTTP exchange: BadStatusLine/IncompleteRead are neither OSError nor ValueError): not the model's fault
            unreachable += 1
            in_a_row += 1
            print(f"  ! server problem, document left out: {type(e).__name__}: {str(e)[:60]}", flush=True)
            if in_a_row >= MAX_UNREACHABLE_IN_A_ROW:
                print(f"\nstopped: the model server looks unreachable ({in_a_row} failures in a row), no score is given.")
                return
            continue
        except BadModelAnswer as e:  # the model answered, with something unusable: that IS a failure of the model
            in_a_row = 0
            judged += 1
            stats["amount_n"] += bool(r["amount"])  # expected from the name: a failed analysis is a miss, not an absence
            secs.append(time.monotonic() - t0)
            print(f"  ✗ unusable answer: {str(e)[:60]}", flush=True)
            continue
        in_a_row = 0
        judged += 1
        stats["json"] += 1
        stats["amount_n"] += bool(r["amount"])
        secs.append(time.monotonic() - t0)
        c_ok = same_company(a.company, r["company"])
        d_ok = a.date == r["date"]
        stats["company"] += c_ok
        stats["date"] += d_ok
        if r["amount"]:
            stats["amount"] += a.amount is not None and a.amount == Decimal(r["amount"])
        print(f"  {secs[-1]:5.1f}s  expected {r['company'][:18]:<18} {r['date']:<10} | model {str(a.company)[:18]:<18} {a.date:<10}"
              f" {'✓' if c_ok else '✗'}{'✓' if d_ok else '✗'}", flush=True)
    print(f"\n{model}: {len(sample)} hard documents, {judged} judged | valid JSON {stats['json']}/{judged}"
          f" | company {stats['company']}/{judged} | date {stats['date']}/{judged}"
          f" | amount {stats['amount']}/{stats['amount_n']}"
          f" | infrastructure errors {unreachable} (left out of every score)"
          f" | mean time {sum(secs) / max(len(secs), 1):.1f}s (max {max(secs, default=0):.0f}s)")


if __name__ == "__main__":
    try:
        sample_size = int(sys.argv[3])
        if sample_size < 1:
            raise ValueError(f"got {sample_size}")
    except ValueError as e:  # a bad N is a usage error: say it on stderr, exit 2, no traceback
        print(f"usage error: N must be a whole number of at least 1 ({e})", file=sys.stderr)
        sys.exit(2)
    main(Path(sys.argv[1]), sys.argv[2], sample_size)
