"""Small file helpers shared by the scripts."""
import os
import shutil
import uuid
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Whole text in a temporary file next to the target, then swapped in: an interruption leaves the old file intact.
    The temporary name is the writer's own (process and random part): two writers of the same target never share one.
    The data is on the disk (fsync) BEFORE the swap, and the swap itself is made durable after it (the folder is synced where the
    system allows it): after a power cut the target is the old text or the new one, never an empty or truncated file.
    The file keeps the permissions it had, and a symbolic link is followed: the file it points to is the one replaced."""
    path = path.resolve()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copymode(path, tmp)  # the new file would get the umask's rights, losing (or adding) the old file's
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    if os.name != "nt":  # Windows cannot open a folder to sync it; the rename is journalled there
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
