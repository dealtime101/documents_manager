"""Small file helpers shared by the scripts."""
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Whole text in a temporary file next to the target, then swapped in: an interruption leaves the old file intact."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
