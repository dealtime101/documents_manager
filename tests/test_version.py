import re
import tomllib
from pathlib import Path

import pytest
from docflow import __version__
from docflow.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_the_version_is_written_once_in_pyproject_and_the_code_reads_it():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
    assert __version__ == _pyproject_version()


def test_the_changelog_starts_with_the_released_version_and_every_release_has_a_date():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", text, re.MULTILINE)
    assert releases, "no release heading like '## [0.2.0] - 2026-10-05'"
    assert releases[0][0] == __version__, "the newest entry of CHANGELOG.md must be the version in pyproject.toml"
    versions = [tuple(map(int, v.split("."))) for v, _ in releases]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions)   # newest first, none twice
    assert text.count("## [") == len(releases)                                                   # no heading in another shape


def test_the_command_line_says_its_version(capsys):
    with pytest.raises(SystemExit) as stop:
        build_parser().parse_args(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"docflow {__version__}"


def test_the_page_shows_the_version_the_server_sent():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "setVersion(m.version)" in app and "v{version}" in app
    assert "version: string" in (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")


def test_the_service_file_names_its_hosts_so_the_code_default_can_shrink_later():
    # DOC474.252, first step: the hosts live in the service, with the same value the code uses as its default today
    unit = (ROOT / "deploy" / "docflow-web.service").read_text(encoding="utf-8")
    line = next(ln for ln in unit.splitlines() if ln.startswith("Environment=DOCFLOW_HOSTS="))
    from webapp.settings import parse_hosts
    assert parse_hosts(line.split("=", 2)[2]) == ["localhost", "127.0.0.1"]


def test_without_docflow_hosts_the_site_answers_only_to_localhost(tmp_path):
    # DOC474.252, second step: a machine's name and address belong in the service (DOCFLOW_HOSTS), not in the code
    import json
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "DOCFLOW_SECRET_KEY": "x", "DOCFLOW_SANDBOX": str(tmp_path)}
    env.pop("DOCFLOW_HOSTS", None)
    out = subprocess.run([sys.executable, "-c", "import json; from webapp import settings as s; print(json.dumps(s.ALLOWED_HOSTS))"],
                         env=env, capture_output=True, text=True, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == ["localhost", "127.0.0.1"]


SAMPLE = """# Notes de version

Texte d'en-tête ignoré.

## [0.3.0] - 2026-11-01

Une phrase d'introduction
sur deux lignes.

### Ajouté
- **Gras** et texte ;
  suite de la même ligne.
- Deuxième point.

### Pour déployer
1. Arrêter.
2. Démarrer.

## [0.1.0] - 2026-10-04

Départ.
"""


def test_the_changelog_is_read_into_releases_sections_and_items():
    from docflow.changelog import parse
    got = parse(SAMPLE)
    assert [r["version"] for r in got] == ["0.3.0", "0.1.0"] and got[0]["date"] == "2026-11-01"
    assert got[0]["intro"] == "Une phrase d'introduction sur deux lignes."
    assert got[0]["sections"] == [
        {"title": "Ajouté", "items": ["**Gras** et texte ; suite de la même ligne.", "Deuxième point."]},
        {"title": "Pour déployer", "items": ["Arrêter.", "Démarrer."]}]
    assert got[1] == {"version": "0.1.0", "date": "2026-10-04", "intro": "Départ.", "sections": []}


def test_the_real_changelog_is_read_whole():
    from docflow.changelog import parse
    got = parse((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert got[0]["version"] == __version__ and got[0]["sections"] and all(s["items"] for r in got for s in r["sections"])


def test_the_product_is_called_documents_manager_where_people_read_its_name():
    # the display name; the internal name `docflow` (command, folders, services) is deliberately unchanged
    src = ROOT / "frontend" / "src" / "i18n.tsx"
    assert (src.read_text(encoding="utf-8")).count("'app.title': 'Documents Manager'") == 2          # English and French
    assert "<title>Documents Manager</title>" in (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert (ROOT / "README.md").read_text(encoding="utf-8").startswith("# Documents Manager")
    assert (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").startswith("# Documents Manager")
