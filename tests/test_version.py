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


def test_release_headings_with_a_suffix_trailing_spaces_or_yanked_are_read_and_an_unreadable_one_is_reported(caplog):
    # DOC534.48: such a heading was not a release: it vanished from the screen and cut the notes of the release before it
    import logging

    from docflow.changelog import parse
    text = ("## [1.0.0-beta.1] - 2026-12-01  \n### Added\n- Beta.\n"
            "## [0.9.0] - 2026-11-20 [YANKED]\n### Fixed\n- Pulled.\n"
            "## [0.8.0+build.5] - 2026-11-10\n### Added\n- Built.\n"
            "## [Unreleased]\n### Added\n- Later.\n"
            "## [0.7.0] - 2026-11-01\n### Added\n- Last.\n")
    with caplog.at_level(logging.WARNING):
        got = parse(text)
    assert [r["version"] for r in got] == ["1.0.0-beta.1", "0.9.0", "0.8.0+build.5", "0.7.0"]
    assert [s["items"] for r in got for s in r["sections"]] == [["Beta."], ["Pulled."], ["Built."], ["Last."]]
    assert any("[Unreleased]" in r.getMessage() for r in caplog.records)             # reported, not dropped in silence


def test_the_intro_of_a_release_without_section_survives_a_heading_that_is_not_a_release():
    # DOC534.162: "## [Unreleased]" (or an appendix) right after an intro-only release dropped that intro: the version showed empty
    from docflow.changelog import parse
    got = parse("## [1.0.0] - 2026-12-01\nOnly an intro,\non two lines.\n## [Unreleased]\n### Added\n- Later.\n"
                "## [0.9.0] - 2026-11-20\nAnother.\n## Appendix\nnot a release\n")
    assert got == [{"version": "1.0.0", "date": "2026-12-01", "intro": "Only an intro, on two lines.", "sections": []},
                   {"version": "0.9.0", "date": "2026-11-20", "intro": "Another.", "sections": []}]


def test_an_indented_sub_bullet_is_an_item_and_a_tab_indents_a_continuation():
    # DOC534.164: "- a / <2 spaces>- b" gave the one item "a - b"; a continuation indented with a tab was dropped
    from docflow.changelog import parse
    got = parse("## [1.0.0] - 2026-12-01\n### Added\n- a\n  - b\n\t* c\n- d\n  continues\n\tand more\n")
    assert got[0]["sections"] == [{"title": "Added", "items": ["a", "b", "c", "d continues and more"]}]


def test_the_three_markdown_bullets_are_items_and_a_bold_line_is_not():
    # DOC534.163: "* " and "+ " are valid Markdown bullets and were skipped in silence
    from docflow.changelog import parse
    got = parse("## [1.0.0] - 2026-12-01\n### Added\n- Dash.\n* Star.\n+ Plus.\n1. One.\n**Bold line**, not an item.\n")
    assert got[0]["sections"] == [{"title": "Added", "items": ["Dash.", "Star.", "Plus.", "One."]}]


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


