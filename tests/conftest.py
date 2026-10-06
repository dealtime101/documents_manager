import os
import tempfile
from pathlib import Path

import pytest
from docflow import config

# No test may read or write the real user's folder (~/.config/docflow): the whole session works in a throw-away one. Set at import
# time, because several test modules load the configuration while they are being collected.
os.environ.setdefault("DOCFLOW_HOME", tempfile.mkdtemp(prefix="docflow-home-"))
# ...and it uses the test rules (well-known companies only), never the rules that ship with the program.
os.environ.setdefault("DOCFLOW_CONFIG_DIR", str(Path(__file__).parent / "fixtures" / "config"))


@pytest.fixture(autouse=True)
def _tests_do_not_depend_on_what_production_has_learned(monkeypatch):
    """A sandbox normally starts from the learned files of config/ (the real ones). A test must not: its result would
    change whenever the user corrects a document. The one test about that behaviour switches it back on itself."""
    monkeypatch.setattr(config, "SANDBOX_INHERITS_LEARNED", False)
