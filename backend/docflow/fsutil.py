"""Small file helpers shared by the scripts."""
import os
import uuid
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Whole text in a temporary file next to the target, then swapped in: an interruption leaves the old file intact.
    The temporary name is the writer's own (process and random part): two writers of the same target never share one."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
