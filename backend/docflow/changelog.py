"""CHANGELOG.md read into data, for the "Release notes" screen. The file is the only place the notes are written."""
import re

RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$")
ITEM = re.compile(r"^(?:- |\d+\. )(.*)$")


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
