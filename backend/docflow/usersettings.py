"""What belongs to ONE user, kept outside the program's folder: the folders chosen in the Settings screen, and (in `config/` and
`learned/` under the same folder) their own rules. Nothing here is shipped with the program: a new install starts empty."""
import logging
import os
import sys
from pathlib import Path

import yaml

from .fsutil import write_atomic

log = logging.getLogger(__name__)

FOLDER_KEYS = ("inbox", "extra_inboxes", "library_root", "quarantine", "db")  # what the Settings screen can change


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
    return out


def validate(values: dict) -> dict[str, str]:
    """{setting: what is wrong}: empty when the folders can be used. Only the keys given are checked."""
    errors: dict[str, str] = {}

    def folder(key: str, must_exist: bool = True) -> Path | None:
        raw = values.get(key)
        if not isinstance(raw, str) or not raw.strip():
            errors[key] = "a folder is required"
            return None
        p = Path(raw).expanduser()
        if must_exist and not p.is_dir():
            errors[key] = f"{p} does not exist or is not a folder"
            return None
        return p

    inbox = folder("inbox") if "inbox" in values else None
    library = folder("library_root") if "library_root" in values else None
    quarantine = folder("quarantine", must_exist=False) if "quarantine" in values else None
    if inbox and library and inbox.resolve() == library.resolve():
        errors["library_root"] = "must be a different folder from the inbox (filed documents would be scanned again)"
    if library and quarantine and library.resolve() in quarantine.resolve().parents:
        errors["quarantine"] = "must be outside the library (duplicates would be filed into it)"
    if library and not os.access(library, os.W_OK):
        errors.setdefault("library_root", "is not writable")
    for i, extra in enumerate(values.get("extra_inboxes") or []):
        if not Path(str(extra)).expanduser().is_dir():
            errors[f"extra_inboxes[{i}]"] = f"{extra} does not exist or is not a folder"
    return errors


def save(values: dict) -> dict:
    """Validate, keep only the folder settings and write them. Nothing is written when something is wrong."""
    kept = {k: v for k, v in values.items() if k in FOLDER_KEYS}
    errors = validate(kept)
    if errors:
        raise InvalidSettings(errors)
    _file().parent.mkdir(parents=True, exist_ok=True)
    write_atomic(_file(), yaml.safe_dump(kept, allow_unicode=True, sort_keys=False))
    return kept
