"""Consistent backup and restore of the database and the learned rules.

The database runs in WAL mode: copying the file while the service works can give a file that never existed. SQLite's own
backup API (`Connection.backup`) takes a consistent snapshot at any time, without stopping anything."""
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

LEARNED_FILES = ("company_aliases.yaml", "types_learned.yaml", "routing_learned.yaml")
PREFIX = "docflow-"
DB_NAME = "docflow.db"


def make_backup(db: Path, learn_dir: Path, dest_root: Path, keep: int = 14, now: datetime | None = None) -> Path:
    """Write `dest_root/docflow-YYYYmmdd-HHMMSS/` (the database + the learned files that exist), then delete the oldest
    docflow-* folders beyond `keep`. `dest_root` must already exist, or its parent must: an unmounted network share would
    otherwise be replaced by a plain local folder and the backup would silently stay on this machine."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not dest_root.is_dir():
        if not dest_root.parent.is_dir():
            raise FileNotFoundError(f"neither {dest_root} nor its parent exists: is the backup share mounted?")
        dest_root.mkdir()
    out = dest_root / f"{PREFIX}{(now or datetime.now()):%Y%m%d-%H%M%S}"
    out.mkdir()  # FileExistsError if there is one already: a backup is never overwritten
    try:
        # The snapshot is made in a LOCAL temporary folder, then the finished file is copied: SQLite cannot lock files on a
        # network share (CIFS), and writing the snapshot straight onto one hangs.
        with tempfile.TemporaryDirectory(prefix="docflow-backup-") as tmp:
            snap = Path(tmp) / DB_NAME
            src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            dst = sqlite3.connect(snap)
            try:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise sqlite3.DatabaseError(f"the copy of {db} failed its integrity check")
            finally:
                dst.close()
                src.close()
            shutil.copyfile(snap, out / DB_NAME)
            if (out / DB_NAME).stat().st_size != snap.stat().st_size:
                raise OSError(f"{out / DB_NAME} is not the size of the snapshot: the copy was cut short")
        for name in LEARNED_FILES:
            if (learn_dir / name).is_file():
                shutil.copy2(learn_dir / name, out / name)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)  # a half backup must not look like a good one
        raise
    for old in sorted(p for p in dest_root.iterdir() if p.is_dir() and p.name.startswith(PREFIX))[:-keep]:
        shutil.rmtree(old)
    return out


def restore(folder: Path, db: Path, learn_dir: Path) -> None:
    """Put a backup back. The service must be stopped. What is replaced is kept next to it as `*.before-restore`, and the
    old write-ahead log is removed (replayed over the restored file it would corrupt it)."""
    if not (folder / DB_NAME).is_file():
        raise FileNotFoundError(f"{folder / DB_NAME} not found: not a docflow backup folder")
    pairs = [(folder / DB_NAME, db)] + [(folder / n, learn_dir / n) for n in LEARNED_FILES if (folder / n).is_file()]
    for _, target in pairs:
        if target.exists():
            shutil.copy2(target, target.with_name(target.name + ".before-restore"))
    for suffix in ("-wal", "-shm"):
        db.with_name(db.name + suffix).unlink(missing_ok=True)
    for source, target in pairs:
        shutil.copy2(source, target)
