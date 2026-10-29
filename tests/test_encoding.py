"""A text file is read in UTF-8, never in the encoding of the machine (cp1252 on a French Windows): DOC534.202."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _files() -> list[Path]:
    found = [ROOT / "manage.py", *ROOT.joinpath("tests").glob("*.py"), *ROOT.joinpath("scripts").glob("*.py")]
    found += [p for p in ROOT.joinpath("backend").rglob("*.py") if "migrations" not in p.parts]
    return found


def bare_text_reads(source: str) -> list[int]:
    """Line numbers of `.read_text()` calls with no encoding, and of `open(...)` / `.open(...)` in text mode with none."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute | ast.Name):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        keywords = {k.arg for k in node.keywords}
        if name == "read_text" and "encoding" not in keywords and not node.args:
            lines.append(node.lineno)
        elif name == "open" and "encoding" not in keywords and not _is_binary_or_not_a_file(node):
            lines.append(node.lineno)
    return sorted(lines)


def _is_binary_or_not_a_file(call: ast.Call) -> bool:
    """open() with a mode that has 'b', and the calls that are not the opening of a text file: pymupdf.open(), webbrowser.open(), a
    urllib opener's open()..."""
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in {"pymupdf", "webbrowser", "os", "opener"}:
        return True
    position = 0 if isinstance(call.func, ast.Attribute) else 1  # path.open(mode) / open(path, mode)
    modes = [a.value for a in call.args[position:position + 1] if isinstance(a, ast.Constant)]
    modes += [k.value.value for k in call.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    return any("b" in str(m) for m in modes)


def test_the_reader_finds_what_it_should():
    assert bare_text_reads("p.read_text()\nq.read_text(encoding='utf-8')\nopen(f)\nopen(f, 'rb')\npath.open('r')\npath.open('rb')\n"
                           "pymupdf.open()\nopen(f, encoding='utf-8')\nr = x.read_text('utf-8')") == [1, 3, 5]


def test_no_text_file_is_read_in_the_encoding_of_the_machine():
    offenders = {}
    for path in _files():
        lines = bare_text_reads(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert not offenders, f"read_text()/open() without encoding='utf-8': {offenders}"
