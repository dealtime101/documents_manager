import re

import pytest
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.learn import NAME_RE


@pytest.fixture
def shipped(monkeypatch):
    """The configuration of a new install: the rules that ship with the program (the tests normally use their own)."""
    monkeypatch.delenv("DOCFLOW_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DOCFLOW_ROOT", raising=False)
    return load_config()


def test_every_shipped_name_is_a_valid_company_name_and_every_pattern_compiles(shipped):
    assert {"Amazon", "Desjardins", "HelloFresh"} <= set(shipped.companies) and len(shipped.companies) >= 30
    for name, patterns in shipped.companies.items():
        assert NAME_RE.match(name), name
        assert patterns, name
        for p in patterns:
            re.compile(p, re.IGNORECASE)


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
