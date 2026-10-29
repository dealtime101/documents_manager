"""DOC534.11: one archive (a zip) of everything the program learned and keeps for one user: the database (filing history, text read
from the documents), the folders chosen in Settings, the learned corrections and the user's own rules. `create` writes it, with a
password if one is given (AES-256, which 7-Zip and most archivers open); `restore` puts it back, after keeping a copy of what it
replaces. The documents themselves are not in it: they are in the library, which is backed up like any other folder."""
import json
import logging
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO

import pyzipper
import yaml

from . import usersettings
from .config import Config
from .fsutil import write_atomic

log = logging.getLogger(__name__)

FORMAT = 1
MANIFEST, DATABASE, SETTINGS = "manifest.json", "docflow.db", "settings.yaml"
FOLDERS = ("learned", "config")   # the folders of the archive that hold YAML files
MAX_YAML_BYTES = 5_000_000        # a rules file is a few kilobytes: a member far larger is not one of ours


BAD_ZIP = (zipfile.BadZipFile, pyzipper.BadZipFile)  # pyzipper brings its own copy of the zip module, with its own exception


class BackupError(ValueError):
    """What is wrong with an archive or its password, in words for the person."""


def _live_db(cfg: Config) -> Path:
    return cfg.path("db")


def _folders(cfg: Config) -> dict[str, Path]:
    """Where each YAML folder of the archive lives on this computer."""
    return {"learned": cfg.learn_dir, "config": usersettings.user_dir() / "config"}


def _open(target: Path | IO[bytes], mode: str, password: str | None) -> pyzipper.AESZipFile:
    z = pyzipper.AESZipFile(target, mode, compression=zipfile.ZIP_DEFLATED)
    if mode == "w" and password:
        z.setpassword(password.encode("utf-8"))
        z.setencryption(pyzipper.WZ_AES, nbits=256)
    elif password:
        z.setpassword(password.encode("utf-8"))
    return z


def create(cfg: Config, target: Path | IO[bytes], password: str | None = None, version: str = "") -> list[str]:
    """Write the archive to `target` (a path or an open binary file); the names of what went in. The database is copied with
    SQLite's own backup API, so the copy is whole even while the program writes to it."""
    names: list[str] = []
    with tempfile.TemporaryDirectory() as tmp, _open(target, "w", password) as z:
        live = _live_db(cfg)
        if live.is_file():
            copy = Path(tmp) / DATABASE
            src, dst = sqlite3.connect(live, timeout=30), sqlite3.connect(copy)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            z.write(copy, DATABASE)
            names.append(DATABASE)
        if usersettings._file().is_file():
            z.write(usersettings._file(), SETTINGS)
            names.append(SETTINGS)
        for folder, where in _folders(cfg).items():
            for f in sorted(where.glob("*.yaml")) if where.is_dir() else []:
                z.write(f, f"{folder}/{f.name}")
                names.append(f"{folder}/{f.name}")
        z.writestr(MANIFEST, json.dumps({"format": FORMAT, "version": version, "created": datetime.now().isoformat(timespec="seconds"),
                                         "contains": names}, indent=1))
    return names


def _member_ok(name: str) -> bool:
    """A name this program wrote: a few fixed ones and flat YAML files in learned/ and config/. Nothing with a path in it."""
    if name in (MANIFEST, DATABASE, SETTINGS):
        return True
    folder, _, leaf = name.partition("/")
    return folder in FOLDERS and leaf.endswith(".yaml") and "/" not in leaf and "\\" not in leaf and leaf not in ("", ".", "..") \
        and ":" not in leaf


def _read(z: pyzipper.AESZipFile, name: str, limit: int | None = None) -> bytes:
    info = z.getinfo(name)
    if limit is not None and info.file_size > limit:
        raise BackupError(f"a file in this backup is too large: {name}")
    return z.read(name)


def encrypted(archive: Path | IO[bytes]) -> bool:
    """True when the archive asks for a password (False for anything that is not an archive: `restore` will say what is wrong)."""
    try:
        with pyzipper.AESZipFile(archive) as z:
            return any(i.flag_bits & 1 for i in z.infolist())
    except (*BAD_ZIP, OSError):
        return False


def restore(cfg: Config, archive: Path | IO[bytes], password: str | None = None, with_settings: bool = False,
            known_migrations: Callable[[], set[str]] | None = None) -> dict:
    """Put the archive back. Everything is read and checked first (names, YAML, the database itself); only then is anything
    replaced, after a copy of the present state is kept in `backups/` under the user's folder. The database is copied in with
    SQLite's backup API, which works while the program has it open. The folders of Settings come back only when `with_settings`,
    and only the ones that exist on this computer. `known_migrations` names the schema versions the program knows ("app.name"):
    a database made by a newer program is refused rather than half understood."""
    try:
        z = _open(archive, "r", password)
    except (*BAD_ZIP, OSError):
        raise BackupError("this file is not a backup made by Documents Manager") from None
    with z, tempfile.TemporaryDirectory() as tmp:
        members = z.namelist()
        if MANIFEST not in members or not all(_member_ok(n) for n in members):
            raise BackupError("this file is not a backup made by Documents Manager")
        try:
            manifest = json.loads(_read(z, MANIFEST, MAX_YAML_BYTES))
            if manifest.get("format") != FORMAT:
                raise BackupError("this backup was made by a different version of the program and cannot be read")
            yamls = {n: _read(z, n, MAX_YAML_BYTES) for n in members if n != MANIFEST and n != DATABASE}
            db_file = Path(tmp) / DATABASE
            if DATABASE in members:
                db_file.write_bytes(z.read(DATABASE))
        except RuntimeError:  # pyzipper: "Bad password for file" (and "password required")
            raise BackupError("the password is missing or wrong" if password is None else "wrong password") from None
        except (*BAD_ZIP, json.JSONDecodeError, OSError, EOFError) as e:
            raise BackupError(f"this backup is damaged: {type(e).__name__}") from None
        for name, raw in yamls.items():
            try:
                yaml.safe_load(raw.decode("utf-8"))
            except (yaml.YAMLError, UnicodeDecodeError):
                raise BackupError(f"a file in this backup is not readable: {name}") from None
        if db_file.is_file():
            try:
                check = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
                try:
                    if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise BackupError("the database in this backup is damaged")
                    has_log = check.execute("SELECT 1 FROM sqlite_master WHERE name = 'django_migrations'").fetchone()
                    if known_migrations is not None and has_log:  # a database only the command line used has no such table
                        unknown = {f"{a}.{n}" for a, n in check.execute("SELECT app, name FROM django_migrations")} - known_migrations()
                        if unknown:
                            raise BackupError("this backup was made by a newer version of the program: update the program first")
                finally:
                    check.close()
            except sqlite3.Error:
                raise BackupError("the database in this backup is damaged") from None
        # checked: from here on things change. What is replaced is kept first.
        safety = usersettings.user_dir() / "backups" / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.zip"
        safety.parent.mkdir(parents=True, exist_ok=True)
        create(cfg, safety)
        done: list[str] = []
        if db_file.is_file():
            src, dst = sqlite3.connect(db_file), sqlite3.connect(_live_db(cfg), timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            done.append(DATABASE)
        for name, raw in yamls.items():
            if name == SETTINGS:
                continue
            folder, _, leaf = name.partition("/")
            where = _folders(cfg)[folder]
            where.mkdir(parents=True, exist_ok=True)
            write_atomic(where / leaf, raw.decode("utf-8"))
            done.append(name)
        skipped: dict[str, str] = {}
        if with_settings and SETTINGS in yamls:
            skipped = _restore_settings(yaml.safe_load(yamls[SETTINGS].decode("utf-8")))
            done.append(SETTINGS)
    return {"restored": done, "settings_skipped": skipped, "safety_copy": str(safety), "created": manifest.get("created", "")}


def _restore_settings(saved: object) -> dict[str, str]:
    """The folders of the archive that exist (and agree with each other) on this computer are kept; the others are left as they
    are here, and named. The place of the database is never taken from an archive."""
    if not isinstance(saved, dict):
        return {}
    wanted = {k: v for k, v in saved.items() if k in usersettings.FOLDER_KEYS + usersettings.FLAG_KEYS and k != "db"}
    skipped: dict[str, str] = {}
    while wanted:
        try:
            usersettings.save(wanted)
            return skipped
        except usersettings.InvalidSettings as e:
            bad = {k.split("[")[0] for k in e.errors} & set(wanted)
            if not bad:  # an error on a key that was not sent (the cross-checks): nothing more can be dropped
                skipped.update(e.errors)
                return skipped
            for key in bad:
                skipped[key] = next(why for k, why in e.errors.items() if k.split("[")[0] == key)
                del wanted[key]
    return skipped
