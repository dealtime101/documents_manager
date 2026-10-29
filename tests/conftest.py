import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# No test may read or write the real user's folder (~/.config/docflow): the whole session works in a throw-away one. Set at import
# time, because several test modules load the configuration while they are being collected. Nothing of docflow is imported
# above this point, so no module can have resolved a path before the two variables are set.
_HOME = tempfile.mkdtemp(prefix="docflow-home-")
os.environ["DOCFLOW_HOME"] = _HOME  # forced: a DOCFLOW_HOME of the developer's shell must not be used
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)  # and gone when the session ends: one folder per run would pile up in /tmp
# ...and it uses the test rules (well-known companies only), never the rules that ship with the program.
os.environ["DOCFLOW_CONFIG_DIR"] = str(Path(__file__).parent / "fixtures" / "config")  # forced too: not the one of the developer's shell


def python_path(*folders: Path) -> str:
    """A PYTHONPATH for a child process: the folders with the separator of the system (':' or ';'), then the one the environment
    already had, which is kept, not replaced (DOC534.204, DOC534.249): a machine may rely on it to find its dependencies."""
    return os.pathsep.join([*map(str, folders), *filter(None, [os.environ.get("PYTHONPATH")])])


def top_level_block(source: str, start: str) -> str:
    """From `start` to the closing brace that stands alone at the start of a line: the whole function or table, however long, and not
    a word more (DOC534.240; DOC534.215 for the French table). A fixed number of characters either cut the code short or ran on into
    the next declaration; a name that is gone is a clear failure, not a bare ValueError."""
    first = source.find(start)
    assert first >= 0, f"{start!r} is no longer in the source: update the test that reads it"
    end = source.find("\n}\n", first)
    assert end > first, f"the block that starts with {start!r} has no closing brace at the start of a line"
    return source[first:end + 2]


def fr_messages_table(i18n_source: str) -> str:
    """The text of the `frMessages` table of frontend/src/i18n.tsx and nothing else."""
    return top_level_block(i18n_source, "const frMessages")


SUBPROCESS_TIMEOUT = 180  # seconds; read at each call, so a test can lower it


@pytest.fixture(autouse=True)
def _a_child_process_that_hangs_fails_the_test_instead_of_freezing_the_suite(monkeypatch):
    """DOC534.200: a script waiting for input or an OCR that never ends held the whole run until the timeout of the CI, with no message.
    Every subprocess.run made while a test runs gets a timeout unless the call sets its own."""
    import subprocess
    real = subprocess.run

    def run(*args, **kwargs):
        kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT)
        return real(*args, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture(autouse=True)
def _tests_do_not_depend_on_what_production_has_learned(monkeypatch):
    """A sandbox normally starts from the learned files of config/ (the real ones). A test must not: its result would
    change whenever the user corrects a document. The one test about that behaviour switches it back on itself."""
    monkeypatch.setattr("docflow.config.SANDBOX_INHERITS_LEARNED", False)
