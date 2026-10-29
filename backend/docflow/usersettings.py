"""What belongs to ONE user, kept outside the program's folder: the folders chosen in the Settings screen, and (in `config/` and
`learned/` under the same folder) their own rules. Nothing here is shipped with the program: a new install starts empty."""
import logging
import os
import sys
from pathlib import Path

import yaml

from .fsutil import write_atomic

log = logging.getLogger(__name__)

FOLDER_KEYS = ("inbox", "extra_inboxes", "library_root", "quarantine", "db")  # the folders the Settings screen can change
FLAG_KEYS = ("watch_inbox",)  # and its on/off choices: analyse the files that arrive in the inbox by themselves (DOC534.5)


class InvalidSettings(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def user_dir() -> Path:
    """DOCFLOW_HOME if set; else %LOCALAPPDATA%\\DocFlow on Windows, $XDG_CONFIG_HOME/docflow (or ~/.config/docflow) elsewhere."""
    if os.environ.get("DOCFLOW_HOME"):
        return Path(os.environ["DOCFLOW_HOME"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "DocFlow"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "docflow"


def _file() -> Path:
    return user_dir() / "settings.yaml"


def load() -> dict:
    """The saved folder settings, {} when there are none or the file cannot be read (said in the log, never a crash)."""
    f = _file()
    if not f.is_file():
        return {}
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("expected a mapping")
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValueError) as e:
        log.warning("settings file %s ignored (%s: %s)", f, type(e).__name__, str(e)[:120])
        return {}
    out: dict = {}
    for key in FOLDER_KEYS:
        value = data.get(key)
        if key == "extra_inboxes" and isinstance(value, list) and all(isinstance(x, str) for x in value):
            out[key] = value
        elif key != "extra_inboxes" and isinstance(value, str) and value.strip():
            out[key] = value
    for key in FLAG_KEYS:
        if isinstance(data.get(key), bool):  # true or false, nothing else ("yes", 1...) is taken for a choice
            out[key] = data[key]
    return out


def _problem(p: Path) -> str | None:
    """Why `p` cannot be used as an existing folder, in words that point at the right cause; None when it is a folder."""
    try:
        if p.stat().st_mode & 0o170000 == 0o040000:  # a directory
            return None
        return f"{p} is not a folder"
    except PermissionError:
        if sys.platform != "win32":  # the advice about a network share and the file explorer is for Windows only
            return f"access to {p} is refused"
        return f"Windows refuses access to {p}: connect the network share first (open it once in the file explorer, with the right account)"
    except OSError:
        return f"{p} does not exist"


def validate(values: dict) -> dict[str, str]:
    """{setting: what is wrong}: empty when the folders can be used. Only the keys given are checked."""
    errors: dict[str, str] = {}
    for key in FLAG_KEYS:
        if key in values and not isinstance(values[key], bool):
            errors[key] = "must be true or false"

    def folder(key: str, must_exist: bool = True) -> Path | None:
        raw = values.get(key)
        if not isinstance(raw, str) or not raw.strip():
            errors[key] = "a folder is required"
            return None
        p = Path(raw).expanduser()
        if must_exist and (why := _problem(p)):
            errors[key] = why
            return None
        return p

    inbox = folder("inbox") if "inbox" in values else None
    library = folder("library_root") if "library_root" in values else None
    quarantine = folder("quarantine", must_exist=False) if "quarantine" in values else None
    if inbox and library and inbox.resolve() == library.resolve():
        errors["library_root"] = "must be a different folder from the inbox (filed documents would be scanned again)"
    elif inbox and library and inbox.resolve() in library.resolve().parents:  # the scan reads sub-folders too
        errors["library_root"] = "must not be inside the inbox (filed documents would be scanned again)"
    if library and quarantine and (library.resolve() == quarantine.resolve() or library.resolve() in quarantine.resolve().parents):
        errors["quarantine"] = "must be outside the library (duplicates would be filed into it)"
    if library and not os.access(library, os.W_OK):
        errors.setdefault("library_root", "is not writable")
    extras = values.get("extra_inboxes") or []
    if not isinstance(extras, list):  # a string would be read letter by letter, and kept if it passed: refused as a whole
        errors["extra_inboxes"] = "must be a list of folders"
        extras = []
    for i, extra in enumerate(extras):
        if not isinstance(extra, str) or not extra.strip():
            errors[f"extra_inboxes[{i}]"] = "a folder is required"
        elif why := _problem(Path(extra).expanduser()):
            errors[f"extra_inboxes[{i}]"] = why
        elif library and (Path(extra).expanduser().resolve() in (library.resolve(), *library.resolve().parents)):
            errors[f"extra_inboxes[{i}]"] = "must not be the library or contain it (filed documents would be scanned again)"
    return errors


def save(values: dict) -> dict:
    """Validate, keep only the folder settings and write them. Nothing is written when something is wrong."""
    # What was saved before stays, whatever the request leaves out; a key sent EMPTY means "the default" and is removed. The merged
    # whole is what is validated, so the cross-checks (inbox / library / quarantine) also see the values this request does not send.
    merged = {**load(), **{k: v for k, v in values.items() if k in FOLDER_KEYS + FLAG_KEYS}}
    kept = {k: v for k, v in merged.items() if v not in ("", None)}
    errors = validate(kept)
    if errors:
        raise InvalidSettings(errors)
    _file().parent.mkdir(parents=True, exist_ok=True)
    write_atomic(_file(), yaml.safe_dump(kept, allow_unicode=True, sort_keys=False))
    return kept
