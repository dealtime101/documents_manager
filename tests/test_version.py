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


def test_the_english_release_notes_list_the_same_versions_with_the_same_dates_as_the_french_ones():
    # the screen follows the interface language; both files are written by hand, so a version missing from one is caught here
    from docflow.changelog import parse
    fr = parse((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    en = parse((ROOT / "CHANGELOG.en.md").read_text(encoding="utf-8"))
    assert [(r["version"], r["date"]) for r in en] == [(r["version"], r["date"]) for r in fr]
    assert all(r["sections"] for r in en[:2])                       # the two recent versions are described, not just listed


