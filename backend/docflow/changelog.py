"""CHANGELOG.md read into data, for the "Release notes" screen. The file is the only place the notes are written."""
import logging
import re

log = logging.getLogger(__name__)
# "## [1.2.3] - 2026-01-02", also with a pre-release / build suffix ("1.0.0-beta.1"), trailing spaces, or Keep a Changelog's [YANKED]
RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)\] - (\d{4}-\d{2}-\d{2})(?:\s+\[YANKED\])?\s*$")
ITEM = re.compile(r"^(?:[-*+] |\d+\. )(.*)$")  # the three Markdown bullets; "**bold**" has no space after its first star


def parse(text: str) -> list[dict]:
    """[{version, date, intro, sections: [{title, items: [str]}]}], newest first as written. What comes before the first
    release heading is ignored. An item that continues on indented lines is joined into one."""
    releases: list[dict] = []
    release: dict | None = None
    section: dict | None = None
    intro: list[str] = []
    for line in text.splitlines():
        if m := RELEASE.match(line):
            if release is not None:
                release["intro"] = " ".join(intro)
            release = {"version": m.group(1), "date": m.group(2), "intro": "", "sections": []}
            releases.append(release)
            section, intro = None, []
        elif release is None:
            continue
        elif line.startswith("### "):
            release["intro"] = " ".join(intro)
            section = {"title": line[4:].strip(), "items": []}
            release["sections"].append(section)
        elif line.startswith("## "):  # another kind of heading: not a release, so it ends the previous one
            if line.startswith("## ["):  # it looks like a release heading and was not recognised: never drop it in silence
                log.warning("CHANGELOG heading not recognised as a release, its notes are left out: %s", line.strip()[:80])
            release["intro"] = release["intro"] or " ".join(intro)  # a release with an intro and no section keeps it
            release, section = None, None
        elif section is not None:
            if m := ITEM.match(line):
                section["items"].append(m.group(1).strip())
            elif line.strip() and line.startswith(" ") and section["items"]:
                section["items"][-1] += " " + line.strip()
        elif line.strip():
            intro.append(line.strip())
    if release is not None and not release["intro"] and intro:
        release["intro"] = " ".join(intro)
    return releases
