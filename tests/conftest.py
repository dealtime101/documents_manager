import os
import tempfile
from pathlib import Path

import pytest

# No test may read or write the real user's folder (~/.config/docflow): the whole session works in a throw-away one. Set at import
# time, because several test modules load the configuration while they are being collected. Nothing of docflow is imported
# above this point, so no module can have resolved a path before the two variables are set.
os.environ["DOCFLOW_HOME"] = tempfile.mkdtemp(prefix="docflow-home-")  # forced: a DOCFLOW_HOME of the developer's shell must not be used
# ...and it uses the test rules (well-known companies only), never the rules that ship with the program.
os.environ["DOCFLOW_CONFIG_DIR"] = str(Path(__file__).parent / "fixtures" / "config")  # forced too: not the one of the developer's shell


def fr_messages_table(i18n_source: str) -> str:
    """The text of the `frMessages` table of frontend/src/i18n.tsx and nothing else: from its declaration to the closing brace at the
    start of a line (DOC534.215). Before, the tests took everything to the end of the file, so a key of another table placed after
    it passed as French, and a renamed constant stopped them with a bare ValueError."""
    start = i18n_source.find("const frMessages")
    assert start >= 0, "frontend/src/i18n.tsx no longer declares `const frMessages`: update tests/conftest.py fr_messages_table()"
    end = i18n_source.find("\n}\n", start)
    assert end > start, "the frMessages table of i18n.tsx has no closing brace at the start of a line"
    return i18n_source[start:end + 2]


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
