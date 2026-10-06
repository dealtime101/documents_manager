"""Learning from corrections: writes to config/*_learned.yaml (never to the hand-written YAML files)."""
import fcntl
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import yaml

from .config import Config

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,59}$")


class LearnedFileError(ValueError):
    """A learned file that cannot be used. Nothing is ever written over it (that would destroy the rules it still holds)."""


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:  # half written, edited by hand, unreadable
        raise LearnedFileError(f"{path.name} cannot be read ({type(e).__name__}); it is left untouched. "
                               "Fix it, or move it away to start again.") from e
    if not isinstance(data, type(default)):
        raise LearnedFileError(f"{path.name} must hold a {type(default).__name__}, not a {type(data).__name__}; it is left "
                               "untouched. Fix it, or move it away to start again.")
    return data


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
    # write the whole new file beside the old one, then swap: an interruption never leaves a truncated YAML
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)  # mkstemp makes it 0600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _locked(cfg: Config):
    """One writer at a time across workers and processes: the read-check-write of a learned file must not interleave,
    or the last writer silently erases the other correction. (flock: POSIX, which is where the service runs.)"""
    cfg.learn_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.learn_dir / ".learn.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield  # released when the file closes


def _pattern(header: str) -> str | None:
    h = header.strip().lower()
    if len(h) < 4 or sum(c.isdigit() for c in h) > len(h) / 2 or sum(c.isalpha() for c in h) < 3:  # "----", "****": no issuer
        return None
    return r"\s+".join(re.escape(w) for w in h.split())


def learn_company(cfg: Config, company: str, header: str) -> bool:
    """"garage tremblay & fils" corrected to GarageTremblay -> alias. False if nothing useful to remember."""
    pat = _pattern(header)
    if not pat or not NAME_RE.match(company or ""):
        return False
    if pat in cfg.companies.get(company, []):
        return False
    f = cfg.learn_dir / "company_aliases.yaml"
    with _locked(cfg):
        data = _load(f, {})
        if pat in data.get(company, []):
            return False  # another worker just learned the same thing
        data.setdefault(company, []).append(pat)
        _save(f, data)
    cfg.companies.setdefault(company, []).append(pat)
    return True


def learn_type(cfg: Config, company: str, doc_type: str) -> bool:
    """Default type of a company (confidence 0.85: always confirmed), if it does not already exist."""
    if not (NAME_RE.match(company or "") and NAME_RE.match(doc_type or "")):
        return False
    mine = [r for r in cfg.types if r.get("company") == company and r.get("_learned")]
    other = [r for r in cfg.types if r.get("company") == company and not r.get("_learned")]
    if any(r.get("type") == doc_type for r in other) or any(r.get("type") == doc_type for r in mine):
        return False  # already known (hand-written, or already the learned one)
    if any(not (r.get("all") or r.get("any") or r.get("none")) for r in other):
        return False  # a hand-written default for this company always comes first: a learned one would never be used
    rule = {"type": doc_type, "company": company, "type_conf": 0.85}
    f = cfg.learn_dir / "types_learned.yaml"
    # the latest correction REPLACES the earlier learned default of this company (both in the file and in memory)
    with _locked(cfg):
        _save(f, [r for r in _load(f, []) if r.get("company") != company] + [rule])
    cfg.types[:] = [r for r in cfg.types if not (r.get("_learned") and r.get("company") == company)]
    cfg.types.append(dict(rule, _learned=True))
    return True


def learn_route(cfg: Config, company: str, rel_dir: str) -> bool:
    """Default destination of a company. A hand-written rule is never overwritten; a destination that was itself LEARNED
    is replaced by a later correction (otherwise the first mistake could only be undone by editing the YAML by hand)."""
    p = PurePosixPath((rel_dir or "").replace("\\", "/"))
    if not NAME_RE.match(company or "") or not p.parts or p.is_absolute() or ".." in p.parts \
            or any(re.search(r'[<>:"|?*\x00-\x1f]', x) for x in p.parts):
        return False
    if cfg.routing.get(company) and company not in cfg.learned_routes:
        return False  # it comes from the hand-written routing_rules.yaml
    f = cfg.learn_dir / "routing_learned.yaml"
    rule = {"default": {"destination": str(p)}}
    with _locked(cfg):
        data = _load(f, {})
        if data.get(company) == rule:
            return False  # already what is stored (another worker, or the same correction twice)
        data[company] = rule
        _save(f, data)
    cfg.routing[company] = rule
    cfg.learned_routes.add(company)
    return True


# ---------------------------------------------------------------- looking at and forgetting what was learned
def list_rules(cfg: Config) -> dict:
    """Everything that was LEARNED, read from the learned files themselves (so every worker shows the same list). The
    hand-written YAML files are not part of it: they are not touched by this module."""
    aliases = _load(cfg.learn_dir / "company_aliases.yaml", {})
    types = _load(cfg.learn_dir / "types_learned.yaml", [])
    routes = _load(cfg.learn_dir / "routing_learned.yaml", {})
    return {
        "aliases": [{"company": c, "patterns": list(p)} for c, p in sorted(aliases.items())],
        "types": sorted(({"company": r["company"], "type": r["type"]} for r in types), key=lambda r: r["company"]),
        "routes": [{"company": c, "destination": r["default"]["destination"]} for c, r in sorted(routes.items())],
    }


def forget_alias(cfg: Config, company: str, pattern: str | None = None) -> bool:
    """Forget one learned pattern of a company, or (no pattern) all of them. False if there was nothing learned to forget."""
    f = cfg.learn_dir / "company_aliases.yaml"
    with _locked(cfg):
        data = _load(f, {})
        if company not in data or (pattern is not None and pattern not in data[company]):
            return False
        data[company] = [] if pattern is None else [p for p in data[company] if p != pattern]
        if not data[company]:
            del data[company]
        _save(f, data)
    cfg.refresh_learned()  # memory follows the file, here and (through the same check) in the other workers
    return True


def forget_type(cfg: Config, company: str) -> bool:
    """Forget the learned default type of a company."""
    f = cfg.learn_dir / "types_learned.yaml"
    with _locked(cfg):
        rules = _load(f, [])
        kept = [r for r in rules if r.get("company") != company]
        if len(kept) == len(rules):
            return False
        _save(f, kept)
    cfg.refresh_learned()
    return True


def forget_route(cfg: Config, company: str) -> bool:
    """Forget the learned default destination of a company (a hand-written one is never in this file)."""
    f = cfg.learn_dir / "routing_learned.yaml"
    with _locked(cfg):
        data = _load(f, {})
        if company not in data:
            return False
        del data[company]
        _save(f, data)
    cfg.refresh_learned()
    return True
