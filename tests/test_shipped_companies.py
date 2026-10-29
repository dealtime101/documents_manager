import re

import pytest
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.learn import NAME_RE


@pytest.fixture
def shipped(monkeypatch, tmp_path):
    """The configuration of a new install: the rules that ship with the program (the tests normally use their own). The folders of the
    person running the tests are out of reach (DOC534.247): the user's own folder, HOME and XDG_CONFIG_HOME all point into tmp_path, so
    no personal rule or learned file can be read, whatever the machine."""
    monkeypatch.delenv("DOCFLOW_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DOCFLOW_ROOT", raising=False)
    monkeypatch.setenv("DOCFLOW_HOME", str(tmp_path / "docflow-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return load_config()


def test_the_shipped_configuration_is_read_with_no_personal_folder_in_reach(shipped, tmp_path, monkeypatch):
    from docflow import usersettings
    assert usersettings.user_dir().is_relative_to(tmp_path)
    assert shipped.learn_dir.is_relative_to(tmp_path)                                  # what was learned is looked for there too...
    assert not shipped.learn_dir.exists() or not any(shipped.learn_dir.glob("*.yaml"))   # ...and nothing is
    # even without DOCFLOW_HOME, the places the code falls back to are inside tmp_path
    monkeypatch.delenv("DOCFLOW_HOME")
    assert usersettings.user_dir().is_relative_to(tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert usersettings.user_dir().is_relative_to(tmp_path)


def test_every_shipped_name_is_a_valid_company_name_and_every_pattern_compiles(shipped):
    assert {"Amazon", "Desjardins", "HelloFresh"} <= set(shipped.companies) and len(shipped.companies) >= 30
    for name, patterns in shipped.companies.items():
        assert NAME_RE.fullmatch(name), name                                  # the whole name, not only its beginning (DOC534.246)
        assert patterns, name
        for p in patterns:
            re.compile(p, re.IGNORECASE)


@pytest.mark.parametrize("bad", ["Acme\n", "Acme ", "Ac me", "Acme/x", "Société", "", "-Acme", "A" * 61, "Acme\r\n"])
def test_a_name_that_only_starts_well_is_not_a_company_name(bad, tmp_path):
    # DOC534.246: the check used .match, and `$` lets a name end with a newline; the name is used as a folder and a key
    from docflow.learn import learn_company
    assert NAME_RE.fullmatch(bad) is None and NAME_RE.match(bad) is None
    assert learn_company(load_config(sandbox=tmp_path), bad, "texte unique pour ce nom") is False
    assert not (tmp_path / "learned" / "company_aliases.yaml").exists()


@pytest.mark.parametrize("good", ["Amazon", "Hydro-Quebec", "A", "a.b_c+d-e", "A" * 60])
def test_the_names_the_program_accepts(good):
    assert NAME_RE.fullmatch(good) and NAME_RE.match(good)


@pytest.mark.parametrize("text,expected", [
    ("Amazon.ca Order Summary\nTotal 25.00", "Amazon"),
    ("HELLO FRESH\nPâtes au boeuf", "HelloFresh"),
    ("Hydro-Québec\nFacture d'électricité", "Hydro-Quebec"),
    ("Vidéotron\nVotre facture", "Videotron"),
    ("Banque Royale du Canada\nRelevé", "RBC"),
    ("Revenu Québec\nAvis de cotisation", "RevenuQuebec"),
    ("Agence du revenu du Canada\nAvis", "ARC-CRA"),
])
def test_well_known_issuers_are_recognised(shipped, text, expected):
    assert RuleBasedAnalyzer(shipped).analyze(text).company == expected


@pytest.mark.parametrize("text", [
    "Une pomme, Apple pie recipe\nPour 4 personnes",
    "Cher monsieur, la cloche (bell) sonne à midi. Le TD de maths est demain.",
    "Lettre de la tante Huguette\nLe 3 mai 2025",
])
def test_common_words_do_not_trigger_a_company(shipped, text):
    assert RuleBasedAnalyzer(shipped).analyze(text).company is None
