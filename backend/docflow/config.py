import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

import yaml

from . import usersettings

log = logging.getLogger(__name__)


@dataclass
class Config:
    root: Path
    settings: dict
    companies: dict[str, list[str]]
    types: list[dict]
    routing: dict
    learn_dir: Path  # learned corrections: company_aliases.yaml, types_learned.yaml, routing_learned.yaml
    # companies whose destination in `routing` was LEARNED (and may therefore be corrected); the others come from the
    # hand-written routing_rules.yaml, which is never overwritten
    learned_routes: set[str] = field(default_factory=set)
    # how to read this same configuration again, and the state of the learned files when it was read (see refresh_learned)
    reload: Callable[[], "Config"] | None = field(default=None, repr=False, compare=False)
    learned_stamp: tuple = field(default=(), repr=False, compare=False)
    inherited_dir: Path | None = field(default=None, repr=False, compare=False)  # a sandbox's read-only source of learned files
    configured: bool = field(default=True, repr=False, compare=False)  # False on a first run: no inbox / library chosen yet

    def refresh_learned(self) -> bool:
        """Pick up learned rules written (or forgotten) by ANOTHER worker or process: when a learned file changed since this
        configuration was read, read it all again. Cheap when nothing changed (three stat calls). True if it reloaded."""
        if self.reload is None:
            return False
        stamp = _stamp_of(self.learn_dir, self.inherited_dir)  # taken BEFORE reading: a write during the read is seen next time
        if stamp == self.learned_stamp:
            return False
        fresh = self.reload()
        self.configured = fresh.configured
        self.settings = fresh.settings  # a folder changed in the Settings screen (another worker saved it) applies here too
        self.companies, self.types, self.routing, self.learned_routes = fresh.companies, fresh.types, fresh.routing, fresh.learned_routes
        self.learned_stamp = stamp
        return True

    def path(self, key: str) -> Path:
        """A configured path: absolute ones as written (POSIX, 'C:\\x', 'C:/x', '\\\\server\\share'), relative ones under the
        project root. 'C:x' is neither (relative to the current directory OF A DRIVE): refused, never guessed."""
        raw = str(self.settings[key])
        windows = PureWindowsPath(raw)
        if windows.drive:
            if not windows.root:
                raise ValueError(f"settings.{key}: {raw!r} is relative to a drive; write the full path (e.g. {windows.drive}\\...)")
            return Path(raw)
        p = Path(raw)
        return p if p.is_absolute() else self.root / p


LEARNED_FILES = ("company_aliases.yaml", "types_learned.yaml", "routing_learned.yaml")


def learned_stamp(learn_dir: Path) -> tuple:
    """(mtime, size) of each learned file, None for a missing one: changes whenever any of them is rewritten."""
    out: list[tuple[int, int] | None] = []
    for name in LEARNED_FILES:
        try:
            st = (learn_dir / name).stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def learned_stamp_of_file(f: Path) -> tuple:
    """(mtime, size) of one file, None when missing."""
    try:
        st = f.stat()
        return ((st.st_mtime_ns, st.st_size),)
    except OSError:
        return (None,)


def _stamp_of(learn_dir: Path, inherited_dir: Path | None) -> tuple:
    """The state of the learned files that make up a configuration: its own folder and, in a sandbox that inherits what
    production learned, that folder too (a rule learned there later must be picked up here)."""
    return (learned_stamp(learn_dir) + (learned_stamp(inherited_dir) if inherited_dir else ())
            + learned_stamp_of_file(usersettings.user_dir() / "settings.yaml"))


def _patterns(company: str, value, source: str) -> list[str]:
    """YAML gives None for `ACME:`, a str for `ACME: pattern` and a list for the usual form. A bare string is ONE
    pattern (list('abc') would silently split it into letters); anything else is an error that names the entry."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(p, str) for p in value):
        return list(value)
    raise ValueError(f"{source}: the entry {company!r} must be a pattern or a list of patterns, got {type(value).__name__}")


PATH_SETTINGS = ("inbox", "library_root", "quarantine", "db", "log")


def _refuse_foreign_paths(settings: dict) -> None:
    """A Windows drive or share path ('C:\\docs', '\\\\server\\x') on a system where it is not absolute would be taken for a
    folder of that odd NAME under the current directory: files filed somewhere unexpected, with no error. Refuse it when the
    configuration is loaded, naming the setting. (Config.path itself keeps returning such a path as written: it is a value.)"""
    raw_paths = [(k, settings.get(k)) for k in PATH_SETTINGS] + [("extra_inboxes", v) for v in settings.get("extra_inboxes") or []]
    for key, raw in raw_paths:
        if isinstance(raw, str) and PureWindowsPath(raw).drive and not Path(raw).is_absolute():
            raise ValueError(f"settings.{key}: {raw!r} is a Windows path, not usable on this system; write a path that exists here")


def _merged(base: dict, over: dict) -> dict:
    """`over` on top of `base`, section by section (a section that is a mapping is merged, anything else is replaced)."""
    out = dict(base)
    for key, value in over.items():
        out[key] = _merged(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, dict) else value
    return out


def shipped_dir() -> Path:
    """The configuration that comes with the program (DOCFLOW_CONFIG_DIR, used by the tests, or its own config/ folder)."""
    env = os.environ.get("DOCFLOW_CONFIG_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "config"


def sandbox_settings(sb: Path) -> dict:
    sb = sb.resolve()
    return {"inbox": str(sb / "inbox"), "library_root": str(sb / "library"), "quarantine": str(sb / "quarantine"),
            "db": str(sb / "docflow.db"), "log": str(sb / "docflow.log")}


# A sandbox is a rehearsal: by default it STARTS from what production has already learned (read only), so that a try-out
# files like the real thing; what it learns itself is written to the sandbox and wins over what it inherited. The test
# suite switches this off (tests/conftest.py) so that no test depends on the real learned files.
SANDBOX_INHERITS_LEARNED = True


def load_config(config_dir: Path | str | None = None, sandbox: Path | None = None, inherit_learned: bool | None = None) -> Config:
    """Hand-written config + LEARNED config (separate files: the hand-written YAML files and their comments
    are never rewritten). In a sandbox, everything that is LEARNED is written to the sandbox, never to the real files."""
    # absolute from the start: Config.root and every path built on it must not move with the current directory
    given = config_dir is not None
    cdir = (Path(config_dir) if config_dir is not None else shipped_dir()).resolve()
    sb = sandbox.resolve() if sandbox else None
    # Where the user's OWN files are: with no explicit config folder, the learned rules and the user's hand-written rules live in
    # the per-user folder (outside the program); with one, everything stays in that folder, as the tests and the CLI --config want.
    own = None if given else usersettings.user_dir()
    prod_learned = cdir if given else usersettings.user_dir() / "learned"
    learn = (sb / "learned") if sb else prod_learned
    if inherit_learned is None:
        inherit_learned = SANDBOX_INHERITS_LEARNED
    inherited = prod_learned if (sandbox and inherit_learned) else None  # the production learned files, read only

    def hand_dir(name: str) -> Path:
        """The folder a hand-written file is read from: the user's own copy when there is one, else the shipped one."""
        return own / "config" if own is not None and (own / "config" / name).is_file() else cdir

    def rd(d: Path, name: str, default, learned: bool = False):
        f = d / name
        if not f.exists():
            return default
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or default
            if learned and not isinstance(data, type(default)):
                raise ValueError(f"expected a {type(default).__name__}, found a {type(data).__name__}")
            return data
        except (yaml.YAMLError, OSError, UnicodeDecodeError, ValueError) as e:
            if not learned:
                raise  # a hand-written file that is broken stops the program, loudly, as before
            # a LEARNED file is the program's own: losing it must not stop everything. It is left alone and reported.
            log.warning("learned file %s ignored (%s: %s); fix it or move it away", f, type(e).__name__, str(e)[:120])
            return default

    settings = rd(cdir, "settings.yaml", {})
    if own is not None and (own / "config" / "settings.yaml").is_file():  # the user's own settings.yaml adds to / overrides the shipped one
        settings = _merged(settings, rd(own / "config", "settings.yaml", {}))
    if not sandbox:
        settings.update(usersettings.load())  # the folders this user chose in the Settings screen win over the shipped ones
    configured = all(settings.get(k) for k in ("inbox", "library_root"))
    if own is not None and not sandbox:  # a new install: folders in the user's own place until the Settings screen chooses
        base = usersettings.user_dir()
        for key, default in (("inbox", base / "Inbox"), ("library_root", base / "Library"), ("quarantine", base / "Quarantine"),
                             ("db", base / "docflow.db"), ("log", base / "logs" / "docflow.log")):
            settings.setdefault(key, str(default))
    if sandbox:
        settings.update(sandbox_settings(sandbox))
        settings["extra_inboxes"] = []  # a sandbox NEVER reads the real archive
    _refuse_foreign_paths(settings)
    companies ={k: _patterns(k, v, "companies.yaml") for k, v in rd(hand_dir("companies.yaml"), "companies.yaml", {}).items()}
    for source in ([inherited] if inherited else []) + [learn]:  # inherited first: the sandbox's own come on top
        for name, pats in rd(source, "company_aliases.yaml", {}, learned=True).items():
            companies.setdefault(name, []).extend(
                p for p in _patterns(name, pats, "company_aliases.yaml") if p not in companies.get(name, []))
    # learned rules carry an in-memory marker (never written back) so they can be told apart from hand-written ones
    own_types = rd(learn, "types_learned.yaml", [], learned=True)
    taken = {r.get("company") for r in own_types}  # a company the sandbox corrected: its default type replaces the inherited one
    inherited_types = [r for r in rd(inherited, "types_learned.yaml", [], learned=True) if r.get("company") not in taken] if inherited else []
    types = list(rd(hand_dir("document_types.yaml"), "document_types.yaml", [])) + [dict(r, _learned=True) for r in inherited_types + own_types]
    routing: dict = {}
    for source in ([inherited] if inherited else []) + [learn]:
        routing.update(rd(source, "routing_learned.yaml", {}, learned=True))  # the sandbox's own override the inherited ones
    hand_written = rd(hand_dir("routing_rules.yaml"), "routing_rules.yaml", {})
    learned_routes = set(routing) - set(hand_written)  # a learned entry hidden by a hand-written rule is not "in force"
    routing.update(hand_written)  # the hand-written rule wins
    return Config(cdir.parent, settings, companies, types, routing, learn, learned_routes,
                  # the paths RESOLVED NOW (`cdir`, `sb`): a relative one would be read again from wherever the process is later
                  reload=lambda: load_config(cdir if given else None, sandbox=sb, inherit_learned=inherit_learned),
                  learned_stamp=_stamp_of(learn, inherited), inherited_dir=inherited, configured=configured or bool(sandbox))
