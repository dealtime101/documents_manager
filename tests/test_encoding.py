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


def invisible_format_characters(text: str) -> list[str]:
    """The Unicode 'format' characters (category Cf: bidirectional controls, zero-width characters, the soft hyphen, a byte order mark)
    that a text holds: invisible to whoever reads it, the stuff of a 'Trojan Source' attack (DOC534.580)."""
    import unicodedata
    return sorted({hex(ord(c)) for c in text if unicodedata.category(c) == "Cf"})


def test_no_source_file_holds_an_invisible_format_character():
    assert invisible_format_characters("a" + chr(0x202E) + "b" + chr(0x200B)) == ["0x200b", "0x202e"]     # built by number, like the rule
    assert invisible_format_characters("plain, accentuated: éà, no-break space") == []
    folders = ("backend", "tests", "scripts", "packaging", "config", "frontend/src")
    files = [ROOT / name for name in ("manage.py", "README.md", "CHANGELOG.md", "CHANGELOG.en.md", "pyproject.toml")]
    for folder in folders:
        files += [p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and p.suffix in {".py", ".ts", ".tsx", ".css", ".html", ".md", ".yaml", ".yml", ".bat", ".ps1", ".spec", ".txt", ".json"}]
    found = {}
    for path in files:
        hits = invisible_format_characters(path.read_text(encoding="utf-8"))
        if hits:
            found[str(path.relative_to(ROOT))] = hits
    assert found == {}, found


def unused_imports(source: str) -> list[str]:
    """Names imported at the top of a module and never used in it (vulture / pyflakes F401); a name listed in __all__ counts as used."""
    import ast
    tree = ast.parse(source)
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    exported = {c.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in n.targets)
                for c in ast.walk(n.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return sorted(name for name in imported if name not in used and name not in exported)


def test_no_module_of_the_backend_imports_a_name_it_does_not_use():
    # DOC534.704 to .706: `logout`, `throttle_classes` and `ImproperlyConfigured` were imported and never used
    assert unused_imports("import os\nimport re\nfrom a import b, c\nprint(re, b)\n") == ["c", "os"]
    assert unused_imports("from a import b\n__all__ = ['b']\n") == []
    found = {}
    for path in sorted(ROOT.joinpath("backend").rglob("*.py")):
        if "migrations" in path.parts or path.name == "__init__.py":                     # (an __init__ may re-export)
            continue
        names = unused_imports(path.read_text(encoding="utf-8"))
        if names:
            found[str(path.relative_to(ROOT))] = names
    assert found == {}, found


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
