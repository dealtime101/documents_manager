"""A test closes the history database it opens (DOC534.213): an open connection lives until the garbage collector, keeps its file
locked on Windows and shows up as a ResourceWarning."""
import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def unclosed_db_calls(source: str) -> list[int]:
    """Lines of `DB(...)` calls that are not (a) the expression of a `with`, (b) closed on the spot (`DB(...).close()`), or
    (c) the one in the `make_db` fixture, which closes what it made."""
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    lines = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DB"):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.withitem):
            continue
        if isinstance(parent, ast.Attribute) and parent.attr == "close":
            continue
        scope = parent
        while scope is not None and not isinstance(scope, ast.FunctionDef):
            scope = parents.get(scope)
        if scope is not None and scope.name == "make":
            continue
        lines.append(node.lineno)
    return lines


def test_the_reader_finds_what_it_should():
    source = ("with DB(p) as a:\n    pass\nb = DB(p)\nDB(p).close()\nc = DB(p).c\n"
              "def make(path):\n    return DB(path)\ndef other(path):\n    return DB(path)\n")
    assert unclosed_db_calls(source) == [3, 5, 9]


def test_no_test_leaves_a_history_connection_open():
    offenders = {p.name: unclosed_db_calls(p.read_text(encoding="utf-8")) for p in TESTS.glob("test_*.py")}
    offenders = {name: lines for name, lines in offenders.items() if lines and name != "test_connections.py"}
    assert not offenders, f"DB(...) neither in a with, nor closed, nor from make_db: {offenders}"
