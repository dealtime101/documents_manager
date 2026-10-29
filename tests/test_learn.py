import re

import pytest
import yaml
from docflow.analyze import RuleBasedAnalyzer
from docflow.config import load_config
from docflow.fields import header_line
from docflow.learn import learn_company, learn_route, learn_type


def cfg_in(tmp_path):
    cfg = load_config(sandbox=tmp_path)
    return cfg


def test_sandbox_never_points_at_the_real_archive(tmp_path):
    cfg = load_config(sandbox=tmp_path)
    assert cfg.settings["extra_inboxes"] == []
    for k in ("inbox", "library_root", "quarantine", "db", "log"):
        assert str(tmp_path.resolve()) in str(cfg.path(k)), k
    assert "/mnt/example-share" not in str(cfg.settings)


def test_saving_learned_config_replaces_the_file_atomically_and_survives_a_failure(tmp_path, monkeypatch):
    import os

    from docflow.learn import _save
    target = tmp_path / "learned" / "company_aliases.yaml"
    _save(target, {"A": ["old"]})
    posix = os.name != "nt"                       # DOC534.235: on Windows chmod and st_mode do not carry these bits, nor the inode the identity
    if posix:
        assert target.stat().st_mode & 0o777 == 0o644                              # readable like the other config files
        target.chmod(0o640)
        first_inode = target.stat().st_ino
    _save(target, {"A": ["old", "new"]})
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"A": ["old", "new"]}
    if posix:
        assert target.stat().st_ino != first_inode                                 # the file was replaced, not written in place
        assert target.stat().st_mode & 0o777 == 0o640                              # an existing file keeps its mode

    def interrupted(*a, **k):
        raise OSError("interrupted before the new file could replace the old one")

    monkeypatch.setattr(os, "replace", interrupted)
    try:
        _save(target, {"A": ["lost"]})
    except OSError:
        pass
    else:
        raise AssertionError("the failure was swallowed")
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"A": ["old", "new"]}          # the earlier corrections are intact
    assert [p.name for p in target.parent.iterdir()] == ["company_aliases.yaml"]  # and no temporary file is left


def _production_with_learned(tmp_path):
    """A 'production' config folder that has already LEARNED things (the three *_learned.yaml files)."""
    tmp_path.mkdir(exist_ok=True)
    d = _config_dir(tmp_path, "Hydro: [hydro]\n")
    (d / "routing_rules.yaml").write_text("Hydro:\n  default:\n    destination: Factures/Hydro\n", encoding="utf-8")
    (d / "company_aliases.yaml").write_text("Voisin: [voisin tremblay]\n", encoding="utf-8")
    (d / "types_learned.yaml").write_text("- {type: Lettre, company: Voisin, type_conf: 0.85}\n"
                                          "- {type: Facture, company: Garage, type_conf: 0.85}\n", encoding="utf-8")
    (d / "routing_learned.yaml").write_text("Voisin:\n  default:\n    destination: Amis/Voisin\n"
                                            "Garage:\n  default:\n    destination: Auto/Garage\n", encoding="utf-8")
    return d


def test_one_malformed_learned_alias_costs_that_entry_not_the_start_of_the_program(tmp_path, caplog):
    # DOC534.26: _patterns raised ValueError outside the tolerant reader, so a single bad entry of a learned file stopped load_config
    import logging
    prod = _production_with_learned(tmp_path / "prod")
    (prod / "company_aliases.yaml").write_text("Voisin: [voisin tremblay]\nBad: {x: 1}\nOk: [ok pattern]\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(prod)
    assert cfg.companies["Voisin"][-1] == "voisin tremblay" and cfg.companies["Ok"] == ["ok pattern"]   # the good entries are kept
    assert "Bad" not in cfg.companies
    assert any("Bad" in r.getMessage() and "learned entry ignored" in r.getMessage() for r in caplog.records)
    # a hand-written file with the same mistake still stops the program, loudly
    (prod / "companies.yaml").write_text("Bad: {x: 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="companies.yaml"):
        load_config(prod)


def test_the_windows_lock_is_written_once_and_gives_up_with_a_message_instead_of_waiting_for_ever(tmp_path, monkeypatch, caplog):
    # DOC534.109: the loop never ended (an OSError of any kind was retried silently) and every call added a byte to .learn.lock
    import logging
    import sys
    import types

    from docflow import learn
    calls = []
    fake = types.SimpleNamespace(LK_LOCK=1, locking=lambda fd, mode, n: calls.append(n))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(learn.sys, "platform", "win32")
    cfg = cfg_in(tmp_path)
    for _ in range(3):
        with learn._locked(cfg):
            pass
    assert (cfg.learn_dir / ".learn.lock").stat().st_size == 1 and len(calls) == 3                 # one byte, however many corrections
    fake.locking = lambda fd, mode, n: (_ for _ in ()).throw(OSError(13, "Permission denied"))     # a lock that is never released
    with caplog.at_level(logging.WARNING, logger="docflow"):
        with pytest.raises(TimeoutError, match=f"gave up after {learn.LOCK_ATTEMPTS} attempts"):
            with learn._locked(cfg):
                pass
    assert len([r for r in caplog.records if "lock is still held" in r.getMessage()]) == learn.LOCK_ATTEMPTS   # each try is in the log


@pytest.mark.parametrize("name,text,words", [
    ("company_aliases.yaml", "Acme: acme\n", "'Acme' must be a list of patterns"),             # a string: list() would have split it into letters
    ("company_aliases.yaml", "Acme: [1, 2]\n", "'Acme' must be a list of patterns"),
    ("types_learned.yaml", "- {type: Lettre}\n", "rule 1 must be a mapping with a 'company' and a 'type'"),
    ("types_learned.yaml", "- oops\n", "rule 1 must be a mapping"),
    ("routing_learned.yaml", "Acme: {default: {}}\n", "'Acme' must hold default: destination"),
    ("routing_learned.yaml", "Acme: here\n", "'Acme' must hold default: destination")])
def test_a_learned_file_with_a_badly_shaped_entry_is_a_clear_learned_file_error_everywhere(tmp_path, name, text, words):
    # DOC534.108: only the top level was checked: the rest ended in KeyError / AttributeError, or in aliases cut into letters
    from docflow.learn import LearnedFileError, forget_alias, list_rules
    cfg = cfg_in(tmp_path)
    (cfg.learn_dir).mkdir(parents=True, exist_ok=True)
    f = cfg.learn_dir / name
    f.write_text(text, encoding="utf-8")
    with pytest.raises(LearnedFileError, match="left untouched") as caught:
        list_rules(cfg)
    assert name in str(caught.value) and words in str(caught.value)
    if name == "company_aliases.yaml":
        with pytest.raises(LearnedFileError):
            learn_company(cfg, "Acme", "texte acme unique")
        with pytest.raises(LearnedFileError):
            forget_alias(cfg, "Acme")
    assert f.read_text(encoding="utf-8") == text                                      # never written over


@pytest.mark.parametrize("name,text,found", [("companies.yaml", "- Hydro\n- Voisin\n", "list"), ("settings.yaml", "- a\n", "list"),
                                              ("document_types.yaml", "Hydro: x\n", "dict"), ("routing_rules.yaml", "- x\n", "list")])
def test_a_hand_written_file_of_the_wrong_shape_names_the_file_and_what_was_found(tmp_path, name, text, found):
    # DOC534.98: a list instead of a mapping gave "'list' object has no attribute 'items'", with no file name
    d = _config_dir(tmp_path, "ACME: [acme]\n")
    (d / name).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=rf"{name}: expected a (mapping|list), found a {found}"):
        load_config(d, sandbox=tmp_path / "sb")


def test_a_sandbox_rule_with_no_company_does_not_hide_the_inherited_rules_that_have_none(tmp_path):
    # DOC534.97: None entered `taken`, so every inherited rule without a company disappeared as soon as the sandbox had one
    prod = _production_with_learned(tmp_path / "prod")
    (prod / "types_learned.yaml").write_text("- {type: Lettre, company: Voisin, type_conf: 0.85}\n"
                                             "- {type: Generale, type_conf: 0.7}\n", encoding="utf-8")
    sb = tmp_path / "sb"
    (sb / "learned").mkdir(parents=True)
    (sb / "learned" / "types_learned.yaml").write_text("- {type: Autre, type_conf: 0.6}\n"
                                                      "- {type: Facture, company: Garage, type_conf: 0.85}\n", encoding="utf-8")
    cfg = load_config(prod, sandbox=sb, inherit_learned=True)
    learned = {(r.get("company"), r["type"]) for r in cfg.types if r.get("_learned")}
    assert learned == {("Voisin", "Lettre"), (None, "Generale"), (None, "Autre"), ("Garage", "Facture")}   # nothing hidden
    (sb / "learned" / "types_learned.yaml").write_text("- {type: Facture, company: Voisin, type_conf: 0.9}\n", encoding="utf-8")
    cfg = load_config(prod, sandbox=sb, inherit_learned=True)                           # a company the sandbox corrected still wins
    assert {(r.get("company"), r["type"]) for r in cfg.types if r.get("_learned")} == {("Voisin", "Facture"), (None, "Generale")}


def test_a_learned_type_entry_that_is_not_a_mapping_is_ignored_not_fatal(tmp_path, caplog):
    # DOC534.27: types_learned.yaml was checked as a list only; a string or null item crashed `.get` / dict() in load_config
    import logging
    prod = _production_with_learned(tmp_path / "prod")
    (prod / "types_learned.yaml").write_text("- {type: Lettre, company: Voisin, type_conf: 0.85}\n- oops\n- null\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        sandbox = load_config(prod, sandbox=tmp_path / "sb", inherit_learned=True)
        own = load_config(prod)
    for cfg in (sandbox, own):
        assert {(r["company"], r["type"]) for r in cfg.types if r.get("_learned")} == {("Voisin", "Lettre")}
    assert any("types_learned.yaml" in r.getMessage() and "2 entries" in r.getMessage() for r in caplog.records)


def test_the_docstring_of_refresh_learned_counts_the_stat_calls_it_really_makes(tmp_path, monkeypatch):
    # DOC534.254: it said "three stat calls"; there are four (own folder + user settings) and up to seven (a sandbox that inherits)
    from pathlib import Path

    from docflow import config
    prod = _production_with_learned(tmp_path / "prod")
    calls = []
    real_stat = Path.stat

    def counting(self, *a, **k):
        calls.append(self.name)
        return real_stat(self, *a, **k)
    for cfg, expected in ((load_config(prod), 4), (load_config(prod, sandbox=tmp_path / "sb", inherit_learned=True), 7)):
        calls.clear()
        monkeypatch.setattr(Path, "stat", counting)
        assert cfg.refresh_learned() is False
        monkeypatch.setattr(Path, "stat", real_stat)
        assert len([c for c in calls if c.endswith(".yaml")]) == expected, calls
    doc = config.Config.refresh_learned.__doc__
    assert "three stat calls" not in doc and "four to seven" in doc


def test_a_sandbox_rehearses_with_what_production_has_learned(tmp_path):
    prod = _production_with_learned(tmp_path / "prod")
    sandbox = load_config(prod, sandbox=tmp_path / "sb", inherit_learned=True)
    assert "voisin tremblay" in sandbox.companies["Voisin"]                              # learned alias
    assert {(r["company"], r["type"]) for r in sandbox.types if r.get("_learned")} == {("Voisin", "Lettre"), ("Garage", "Facture")}
    assert sandbox.routing["Voisin"]["default"]["destination"] == "Amis/Voisin"           # learned route
    assert sandbox.routing["Hydro"]["default"]["destination"] == "Factures/Hydro"
    assert sandbox.learned_routes == {"Voisin", "Garage"}                                 # and they stay correctable
    isolated = load_config(prod, sandbox=tmp_path / "sb2", inherit_learned=False)
    assert "Voisin" not in isolated.routing and not any(r.get("_learned") for r in isolated.types)   # opt-out: the old isolation


def test_what_the_sandbox_learns_overrides_what_it_inherits_and_never_reaches_production(tmp_path):
    prod = _production_with_learned(tmp_path / "prod")
    before = {p.name: p.read_bytes() for p in prod.iterdir()}
    cfg = load_config(prod, sandbox=tmp_path / "sb", inherit_learned=True)
    assert learn_route(cfg, "Voisin", "Famille/Voisin") is True                           # corrects an INHERITED learned route
    assert learn_type(cfg, "Voisin", "Carte") is True                                     # replaces the inherited default type
    assert learn_company(cfg, "Voisin", "voisin du coin") is True
    again = load_config(prod, sandbox=tmp_path / "sb", inherit_learned=True)              # a new run of the same sandbox
    assert again.routing["Voisin"]["default"]["destination"] == "Famille/Voisin"          # the sandbox's own correction wins
    assert [r["type"] for r in again.types if r.get("_learned") and r["company"] == "Voisin"] == ["Carte"]   # not Lettre AND Carte
    assert {"voisin tremblay", r"voisin\s+du\s+coin"} <= set(again.companies["Voisin"])   # inherited + its own (stored as a regex)
    assert {p.name: p.read_bytes() for p in prod.iterdir()} == before                     # production files: byte for byte the same


def test_inheriting_is_the_default_for_real_use_but_the_test_suite_stays_hermetic(tmp_path, monkeypatch):
    from docflow import config
    prod = _production_with_learned(tmp_path / "prod")
    assert config.SANDBOX_INHERITS_LEARNED is False                                       # set by tests/conftest.py for every test
    assert "Voisin" not in load_config(prod, sandbox=tmp_path / "a").routing              # so a test never depends on real files
    monkeypatch.setattr(config, "SANDBOX_INHERITS_LEARNED", True)                         # what the CLI and the sandbox site get
    assert load_config(prod, sandbox=tmp_path / "b").routing["Voisin"]["default"]["destination"] == "Amis/Voisin"


def test_a_learned_destination_can_be_corrected_but_a_hand_written_one_never(tmp_path):
    cfg = cfg_in(tmp_path)
    routes = cfg.learn_dir / "routing_learned.yaml"
    assert learn_route(cfg, "Voisin", "Divers/Voisin") is True                   # first correction: learned
    assert learn_route(cfg, "Voisin", "Divers/Voisin") is False                  # the same again: nothing new
    assert learn_route(cfg, "Voisin", "Amis/Voisin") is True                     # a LATER correction replaces it (was ignored)
    assert yaml.safe_load(routes.read_text(encoding="utf-8"))["Voisin"]["default"]["destination"] == "Amis/Voisin"
    assert cfg.routing["Voisin"]["default"]["destination"] == "Amis/Voisin"      # and the running engine uses it at once
    again = load_config(sandbox=tmp_path)                                        # after a restart it is still the corrected one
    assert again.routing["Voisin"]["default"]["destination"] == "Amis/Voisin" and "Voisin" in again.learned_routes
    hand_written = next(iter(cfg.routing.keys() - cfg.learned_routes))           # a company of routing_rules.yaml
    before = routes.read_text(encoding="utf-8")
    assert learn_route(cfg, hand_written, "Quelque/Part") is False               # never overwritten
    assert routes.read_text(encoding="utf-8") == before and "Quelque/Part" not in str(cfg.routing[hand_written])


def test_a_hand_written_rule_added_later_wins_over_an_old_learned_one(tmp_path):
    d = _config_dir(tmp_path, "Voisin: voisin\n")
    (d / "routing_rules.yaml").write_text("Voisin:\n  default:\n    destination: Manuel/Voisin\n", encoding="utf-8")
    (d / "routing_learned.yaml").write_text("Voisin:\n  default:\n    destination: Appris/Voisin\n", encoding="utf-8")
    cfg = load_config(config_dir=d)
    assert cfg.routing["Voisin"]["default"]["destination"] == "Manuel/Voisin"    # the hand-written rule wins, as before
    assert "Voisin" not in cfg.learned_routes                                     # so it is NOT treated as correctable
    assert learn_route(cfg, "Voisin", "Autre/Voisin") is False
    assert "Appris/Voisin" in (d / "routing_learned.yaml").read_text(encoding="utf-8")           # and the learned file is left alone


MEET_SECONDS = 0.3  # without a lock the second worker is in _load within milliseconds; with one, this is all the test costs


def test_simultaneous_learning_does_not_lose_either_correction(tmp_path, monkeypatch):
    import threading

    from docflow import learn
    cfg = cfg_in(tmp_path)
    cfg.learn_dir = tmp_path / "learned"
    real_load = learn._load
    meet = threading.Barrier(2)

    def load_then_meet(path, default):
        data = real_load(path, default)
        try:
            meet.wait(timeout=MEET_SECONDS)  # both workers hold the SAME initial state before either one saves
        except threading.BrokenBarrierError:
            pass                          # (with a lock the second one cannot get here until the first has saved: the wait times out
            #                                once, DOC534.233, and the barrier then stays broken, so the second worker does not wait)
        return data

    monkeypatch.setattr(learn, "_load", load_then_meet)
    results = {}
    workers = [threading.Thread(target=lambda c=c, h=h: results.__setitem__(c, learn_company(cfg, c, h)))
               for c, h in (("GarageTremblay", "garage tremblay et fils"), ("BoutiqueLavoie", "boutique lavoie inc"))]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    saved = yaml.safe_load((cfg.learn_dir / "company_aliases.yaml").read_text(encoding="utf-8"))
    assert results == {"GarageTremblay": True, "BoutiqueLavoie": True}
    assert set(saved) == {"GarageTremblay", "BoutiqueLavoie"}                 # both are on disk, not just the last writer's


def _config_dir(tmp_path, companies_yaml: str):
    d = tmp_path / "cfg"
    d.mkdir()
    (d / "companies.yaml").write_text(companies_yaml, encoding="utf-8")
    return d


def test_the_thresholds_are_always_complete_and_a_bad_value_names_its_key(tmp_path):
    # DOC534.87: a settings.yaml without (or with half of) `thresholds` made /api/thresholds and the engine fail with a bare KeyError
    import pytest
    from docflow.config import DEFAULT_THRESHOLDS

    def with_settings(text: str):
        d = tmp_path / ("cfg-" + str(abs(hash(text))))
        d.mkdir()
        (d / "companies.yaml").write_text("ACME: [acme]\n", encoding="utf-8")
        (d / "settings.yaml").write_text(text, encoding="utf-8")
        return d
    assert load_config(with_settings("inbox: x\n"), sandbox=tmp_path / "s1").settings["thresholds"] == DEFAULT_THRESHOLDS
    half = load_config(with_settings("thresholds:\n  auto: 0.9\n"), sandbox=tmp_path / "s2").settings["thresholds"]
    assert half == {"auto": 0.9, "confirm": DEFAULT_THRESHOLDS["confirm"]}                 # the key left out gets its default
    with pytest.raises(ValueError, match="thresholds must be a mapping"):
        load_config(with_settings("thresholds: 5\n"), sandbox=tmp_path / "s3")
    with pytest.raises(ValueError, match=r"thresholds\.confirm must be a number"):
        load_config(with_settings("thresholds:\n  confirm: high\n"), sandbox=tmp_path / "s4")


def test_company_patterns_accept_empty_and_single_string_values(tmp_path):
    cfg = load_config(_config_dir(tmp_path, "ACME:\nHydro: hydro-quebec\nList:\n  - a one\n  - b two\n"),
                      sandbox=tmp_path / "sb")
    assert cfg.companies["ACME"] == []                       # no pattern: loads, matches nothing
    assert cfg.companies["Hydro"] == ["hydro-quebec"]        # a bare string is ONE pattern, not its letters
    assert cfg.companies["List"] == ["a one", "b two"]


def test_a_malformed_company_entry_is_named_in_the_error(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="companies.yaml.*'Broken'"):
        load_config(_config_dir(tmp_path, "Broken:\n  nested: dict\n"), sandbox=tmp_path / "sb")


def test_header_line_skips_noise_and_normalises():
    t = "\n  \n12\nAmazon.com.ca ULC\nautre ligne"
    assert header_line(t) == "amazon.com.ca ulc"
    assert header_line("1234\n--\n") == ""


def test_learn_company_writes_alias_and_next_analysis_uses_it(tmp_path):
    cfg = cfg_in(tmp_path)
    assert RuleBasedAnalyzer(cfg).analyze("Garage Tremblay & Fils\nFacture").company is None
    assert learn_company(cfg, "GarageTremblay", "garage tremblay & fils") is True
    assert RuleBasedAnalyzer(cfg).analyze("GARAGE  TREMBLAY & Fils\nFacture").company == "GarageTremblay"
    saved = yaml.safe_load((tmp_path / "learned" / "company_aliases.yaml").read_text(encoding="utf-8"))
    assert "GarageTremblay" in saved
    # reloaded from disk: learning survives a restart
    assert "GarageTremblay" in load_config(sandbox=tmp_path).companies


def test_a_correction_back_to_a_value_another_worker_replaced_is_not_refused_as_already_known(tmp_path):
    # DOC534.29: the "already known" test read this worker's memory, stale after another worker replaced the learned type in the file
    worker_a = cfg_in(tmp_path)
    assert learn_type(worker_a, "Voisin", "Lettre") is True
    worker_b = load_config(sandbox=tmp_path)                       # another worker, same learned folder
    assert learn_type(worker_b, "Voisin", "Facture") is True       # replaces Lettre in the file; worker A still remembers Lettre
    assert learn_type(worker_a, "Voisin", "Lettre") is True        # the user corrects back: A must see the file, not its memory
    saved = yaml.safe_load((tmp_path / "learned" / "types_learned.yaml").read_text(encoding="utf-8"))
    assert [r["type"] for r in saved if r["company"] == "Voisin"] == ["Lettre"]
    assert learn_type(worker_b, "Voisin", "Lettre") is False       # and now B sees it is already there


def test_the_pattern_drawn_from_a_company_name_has_word_limits_and_a_length_counted_on_the_name():
    # DOC534.28: "Bell" matched "Isabelle", and "A-B" (a\s*b) passed the length test on its escapes and matched "about"
    from docflow.learn import _name_pattern
    assert _name_pattern("Bell", "Isabelle Tremblay\nFacture") is None
    assert _name_pattern("Bell", "Facture\nBell Canada") is not None
    assert _name_pattern("A-B", "about the thing") is None
    assert _name_pattern("HelloFresh", "Powered by HELLO FRESH") is not None


def test_a_company_named_in_the_text_is_learned_by_its_name_not_by_the_title_line(tmp_path):
    cfg = cfg_in(tmp_path)
    text = "Pâtes au boeuf style taco\nHelloFresh\nPour 2 personnes"
    assert learn_company(cfg, "HelloFresh", header_line(text), text) is True
    assert RuleBasedAnalyzer(cfg).analyze("Poulet crémeux\nPowered by HELLO FRESH\n4 portions").company == "HelloFresh"


def test_learn_company_is_idempotent_and_refuses_junk(tmp_path):
    cfg = cfg_in(tmp_path)
    assert learn_company(cfg, "X", "garage tremblay") is True
    assert learn_company(cfg, "X", "garage tremblay") is False       # already learned
    assert learn_company(cfg, "X", "ab") is False                    # too short
    assert learn_company(cfg, "X", "1234 5678 90") is False          # mostly digits
    assert learn_company(cfg, "../x", "garage tremblay") is False    # invalid name


def test_learn_type_default_rule_needs_confirmation(tmp_path):
    cfg = cfg_in(tmp_path)
    assert learn_type(cfg, "GarageTremblay", "FactureEntretien") is True
    assert learn_type(cfg, "GarageTremblay", "FactureEntretien") is False
    cfg.companies["GarageTremblay"] = ["garage tremblay"]
    a = RuleBasedAnalyzer(cfg).analyze("Garage Tremblay\nDate: 5 mars 2025\nTotal 80,00 $")
    assert a.document_type == "FactureEntretien" and 0.80 <= a.confidence < 0.95


def test_a_later_type_correction_replaces_the_earlier_learned_one(tmp_path):
    cfg = cfg_in(tmp_path)
    assert learn_company(cfg, "GarageTremblay", "garage tremblay") is True   # in the file, not only in memory: learning re-reads the file
    text = "Garage Tremblay\nDate: 5 mars 2025\nTotal 80,00 $"
    assert learn_type(cfg, "GarageTremblay", "FactureEntretien") is True
    assert learn_type(cfg, "GarageTremblay", "FacturePneus") is True           # the user changed their mind
    assert RuleBasedAnalyzer(cfg).analyze(text).document_type == "FacturePneus"   # the NEW correction is the one used
    saved = yaml.safe_load((tmp_path / "learned" / "types_learned.yaml").read_text(encoding="utf-8"))
    assert [r["type"] for r in saved if r["company"] == "GarageTremblay"] == ["FacturePneus"]
    assert learn_type(cfg, "GarageTremblay", "FactureEntretien") is True       # and back again
    assert RuleBasedAnalyzer(cfg).analyze(text).document_type == "FactureEntretien"
    cfg2 = load_config(sandbox=tmp_path)                                       # the replacement survives a reload
    assert [r["type"] for r in cfg2.types if r.get("company") == "GarageTremblay"] == ["FactureEntretien"]


def test_a_hand_written_default_rule_is_never_shadowed_by_a_learned_one(tmp_path):
    cfg = cfg_in(tmp_path)
    assert any(r.get("company") == "Dashlane" and r["type"] == "AbonnementPremium" and not r.get("all") for r in cfg.types)
    assert learn_type(cfg, "Dashlane", "SomethingElse") is False               # it would never be used: refused
    assert not (tmp_path / "learned" / "types_learned.yaml").exists()


def test_learn_route_never_overwrites_a_hand_written_rule_but_replaces_a_learned_one(tmp_path):
    cfg = cfg_in(tmp_path)
    assert learn_route(cfg, "GarageTremblay", "Cars/Entretiens") is True
    assert cfg.routing["GarageTremblay"]["default"]["destination"] == "Cars/Entretiens"
    assert learn_route(cfg, "GarageTremblay", "Other/Folder") is True    # a learned destination can be corrected (DOC468.123)
    assert cfg.routing["GarageTremblay"]["default"]["destination"] == "Other/Folder"
    assert learn_route(cfg, "Hydro-Quebec", "Other") is False             # hand-written rule: never
    assert learn_route(cfg, "Y", "../outside") is False and learn_route(cfg, "Y", "/abs") is False


def test_learned_files_never_touch_hand_written_yaml(tmp_path):
    cfg = cfg_in(tmp_path)
    base = (cfg.root / "config" / "companies.yaml").read_text(encoding="utf-8")
    learn_company(cfg, "GarageTremblay", "garage tremblay")
    assert (cfg.root / "config" / "companies.yaml").read_text(encoding="utf-8") == base
    assert re.search(r"garage", (tmp_path / "learned" / "company_aliases.yaml").read_text(encoding="utf-8"))


def test_a_relative_config_folder_does_not_make_paths_depend_on_the_current_directory(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "config", tmp_path / "proj" / "config")
    settings = tmp_path / "proj" / "config" / "settings.yaml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["inbox"] = "Inbox"                                              # a path relative to the project root, as allowed
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.chdir(tmp_path / "proj")
    cfg = load_config("config")                                          # relative on purpose
    assert cfg.root.is_absolute() and cfg.root == (tmp_path / "proj").resolve()
    where = cfg.path("inbox")
    monkeypatch.chdir(tmp_path)                                          # the process moves elsewhere afterwards
    assert cfg.path("inbox") == where == (tmp_path / "proj").resolve() / "Inbox"   # still the same place


@pytest.mark.parametrize("raw,expected", [("C:\\Docs\\In", "C:\\Docs\\In"), ("C:/Docs/In", "C:/Docs/In"),
                                          ("\\\\nas\\share\\In", "\\\\nas\\share\\In"), ("/srv/in", "/srv/in"),
                                          ("In/Sub", "{root}/In/Sub")])
def test_config_paths_tell_absolute_windows_paths_from_relative_ones(tmp_path, raw, expected):
    from docflow.config import Config
    cfg = Config(tmp_path, {"inbox": raw}, {}, [], {}, tmp_path)
    assert str(cfg.path("inbox")) == expected.replace("{root}", str(tmp_path))      # absolute kept as written, relative under root


@pytest.mark.parametrize("raw", ["C:archive", "d:in/sub", "Z:"])
def test_a_drive_relative_path_is_refused_with_a_message_that_names_the_setting(tmp_path, raw):
    from docflow.config import Config
    cfg = Config(tmp_path, {"inbox": raw}, {}, [], {}, tmp_path)
    with pytest.raises(ValueError, match=r"inbox.*drive"):                        # not silently read as if it were absolute
        cfg.path("inbox")


def _learn_three_things(cfg):
    assert learn_company(cfg, "Voisin", "Famille Voisin et fils") and learn_type(cfg, "Voisin", "Lettre")
    assert learn_route(cfg, "Voisin", "Famille/Voisin")


def test_learned_rules_can_be_listed(tmp_path):
    from docflow.learn import list_rules
    cfg = cfg_in(tmp_path)
    assert list_rules(cfg) == {"aliases": [], "types": [], "routes": []}                   # nothing learned yet
    _learn_three_things(cfg)
    rules = list_rules(cfg)
    assert [(a["company"], len(a["patterns"])) for a in rules["aliases"]] == [("Voisin", 1)]
    assert rules["aliases"][0]["patterns"][0].startswith("famille")                       # the pattern as it was remembered
    assert rules["types"] == [{"company": "Voisin", "type": "Lettre"}]
    assert rules["routes"] == [{"company": "Voisin", "destination": "Famille/Voisin"}]


def test_a_learned_rule_can_be_forgotten_in_the_file_and_in_memory_and_only_that_one(tmp_path):
    from docflow.learn import forget_alias, forget_route, forget_type, list_rules
    cfg = cfg_in(tmp_path)
    _learn_three_things(cfg)
    assert learn_company(cfg, "Voisin", "Maison Voisin")                                  # a second pattern for the same company
    first, second = list_rules(cfg)["aliases"][0]["patterns"]
    assert forget_alias(cfg, "Voisin", first) is True and forget_alias(cfg, "Voisin", first) is False   # idempotent
    assert list_rules(cfg)["aliases"][0]["patterns"] == [second] and first not in cfg.companies["Voisin"]
    assert forget_alias(cfg, "Voisin") is True                                            # no pattern given: the whole company entry
    assert list_rules(cfg)["aliases"] == [] and "Voisin" not in cfg.companies
    assert forget_type(cfg, "Voisin") is True and forget_type(cfg, "Voisin") is False
    assert not any(r.get("company") == "Voisin" for r in cfg.types)
    assert forget_route(cfg, "Voisin") is True and forget_route(cfg, "Voisin") is False
    assert "Voisin" not in cfg.routing and "Voisin" not in cfg.learned_routes


def test_a_hand_written_rule_cannot_be_forgotten_through_the_learned_files(tmp_path):
    from docflow.learn import forget_alias, forget_route, forget_type
    cfg = cfg_in(tmp_path)
    hand_written = {"company": "Hydro-Quebec", "route": "Hydro-Quebec" in cfg.routing, "patterns": list(cfg.companies["Hydro-Quebec"])}
    assert hand_written["patterns"] and hand_written["route"]
    assert forget_alias(cfg, "Hydro-Quebec") is False and forget_type(cfg, "Hydro-Quebec") is False
    assert forget_route(cfg, "Hydro-Quebec") is False
    assert cfg.companies["Hydro-Quebec"] == hand_written["patterns"] and "Hydro-Quebec" in cfg.routing   # untouched
    # DOC534.232: none of the three learned files, company_aliases.yaml included (the old glob "*_learned.yaml" did not match it)
    from docflow.config import LEARNED_FILES
    assert set(LEARNED_FILES) == {"company_aliases.yaml", "types_learned.yaml", "routing_learned.yaml"}
    assert not any((cfg.learn_dir / name).exists() for name in LEARNED_FILES)
    assert not cfg.learn_dir.exists() or {p.name for p in cfg.learn_dir.iterdir()} <= {".learn.lock"}   # and nothing else but the lock


def test_another_worker_sees_what_this_one_learned_and_forgot(tmp_path):
    from docflow.learn import forget_alias
    a, b = cfg_in(tmp_path), cfg_in(tmp_path)                                             # two workers, one learned folder
    assert b.refresh_learned() is False                                                    # nothing changed yet: no reload
    learn_company(a, "Voisin", "Famille Voisin et fils")
    assert "Voisin" not in b.companies                                                     # b still has the old picture...
    assert b.refresh_learned() is True and "Voisin" in b.companies                         # ...until it looks at the files
    assert b.refresh_learned() is False                                                    # and only reloads when they change
    forget_alias(a, "Voisin")
    assert b.refresh_learned() is True and "Voisin" not in b.companies


def test_a_reload_does_not_depend_on_the_current_directory(tmp_path, monkeypatch):
    # DOC474.65: the reload re-used `config_dir` and `sandbox` as the caller wrote them (relative): after a chdir it read
    # another folder, found nothing, and replaced the companies in memory with an empty set
    import shutil
    from pathlib import Path

    from docflow.config import load_config
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "config", tmp_path / "cfg")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = load_config("cfg", sandbox=Path("sb"))                                           # both RELATIVE
    assert "Hydro-Quebec" in cfg.companies
    monkeypatch.chdir(tmp_path / "elsewhere")                                              # the process moved
    learn_company(cfg, "Voisin", "Famille Voisin et fils")                                  # another worker learns something
    assert cfg.refresh_learned() is True
    assert "Hydro-Quebec" in cfg.companies and "Voisin" in cfg.companies                   # still the same configuration


def test_a_reload_of_a_relative_config_dir_without_sandbox_survives_a_chdir(tmp_path, monkeypatch):
    # DOC474.168: same root cause as .65, the case with NO sandbox: learned files live in the config folder itself
    import shutil
    from pathlib import Path

    from docflow.config import load_config
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "config", tmp_path / "cfg")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = load_config("cfg")                                                               # RELATIVE, no sandbox
    monkeypatch.chdir(tmp_path / "elsewhere")
    (tmp_path / "cfg" / "company_aliases.yaml").write_text("Voisin:\n- Famille Voisin et fils\n", encoding="utf-8")
    assert cfg.refresh_learned() is True
    assert "Hydro-Quebec" in cfg.companies and "Voisin" in cfg.companies


@pytest.mark.parametrize("header", ["----", "****", "....", "++++ ====", "----------------", "[ ] ( )", "12 3456", "A--", "a.b.", "_ _ _ _"])
def test_a_header_with_too_few_letters_never_becomes_a_company_pattern(header):
    # DOC474.57: "----" or "****" is not an issuer; as a learned pattern it would attach unrelated documents to a company
    from docflow.learn import _pattern
    assert _pattern(header) is None, header


@pytest.mark.parametrize("header", ["Hydro-Quebec", "Garage Tremblay & Fils", "ABC Inc", "Desjardins", "3M Canada", "A1B Corp"])
def test_a_real_issuer_header_still_becomes_a_pattern(header):
    from docflow.learn import _pattern
    assert _pattern(header)


def test_a_sandbox_notices_a_rule_learned_later_in_the_production_files_it_inherits(tmp_path, monkeypatch):
    # DOC474.66: the stamp only watched the sandbox's own learned folder, so what production learned afterwards was never picked up
    import shutil
    from pathlib import Path

    from docflow import config
    from docflow.config import load_config
    monkeypatch.setattr(config, "SANDBOX_INHERITS_LEARNED", True)
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "config", tmp_path / "prod")      # a COPY: the real files are never touched
    cfg = load_config(tmp_path / "prod", sandbox=tmp_path / "sb")
    assert "Voisin" not in cfg.companies and cfg.refresh_learned() is False                 # nothing changed yet
    (tmp_path / "prod" / "company_aliases.yaml").write_text("Voisin:\n- famille voisin et fils\n", encoding="utf-8")
    assert cfg.refresh_learned() is True and "Voisin" in cfg.companies                     # production learned it: the sandbox follows
    assert cfg.refresh_learned() is False                                                  # and only once


def test_loading_a_configuration_with_a_windows_drive_path_on_a_system_that_cannot_use_it_is_refused(tmp_path):
    # DOC474.67: on Linux "C:\docs" became a folder NAMED "C:\docs" under the current directory, with no error
    import os
    import shutil
    from pathlib import Path

    import yaml
    from docflow.config import load_config
    if os.name == "nt":
        pytest.skip("this system understands Windows drive paths")
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "config", tmp_path / "cfg")        # a COPY: the real files are never touched
    settings = yaml.safe_load((tmp_path / "cfg" / "settings.yaml").read_text(encoding="utf-8"))
    for key, raw in (("library_root", "C:\\docs"), ("inbox", "D:/archive/in"), ("db", "\\\\server\\share\\h.db")):
        bad = {**settings, key: raw}
        (tmp_path / "cfg" / "settings.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=rf"{key}.*not usable on this system"):
            load_config(tmp_path / "cfg")
    bad = {**settings, "extra_inboxes": ["/mnt/ok", "E:\\old"]}
    (tmp_path / "cfg" / "settings.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="extra_inboxes"):
        load_config(tmp_path / "cfg")
    (tmp_path / "cfg" / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    assert load_config(tmp_path / "cfg").path("inbox")                                       # the real settings still load


@pytest.mark.parametrize("name,garbage", [("company_aliases.yaml", "Acme: [unclosed\n  - x"), ("types_learned.yaml", "{ not: a list"),
                                          ("routing_learned.yaml", "a: b: c: d"), ("company_aliases.yaml", "- a list\n- where a mapping belongs\n")])
def test_a_learned_file_that_cannot_be_read_is_reported_by_name_never_overwritten_and_never_crashes_the_loading(tmp_path, caplog, name, garbage):
    # DOC474.162: a half-written or hand-edited learned file raised a raw YAMLError from every learn, forget and list operation
    from docflow.learn import LearnedFileError, learn_route, learn_type, list_rules
    cfg = cfg_in(tmp_path)
    cfg.learn_dir.mkdir(parents=True, exist_ok=True)
    bad = cfg.learn_dir / name
    bad.write_text(garbage, encoding="utf-8")
    before = bad.read_bytes()
    writes_that_file = {"company_aliases.yaml": lambda: learn_company(cfg, "Voisin", "Famille Voisin et fils"),
                        "types_learned.yaml": lambda: learn_type(cfg, "Voisin", "Lettre"),
                        "routing_learned.yaml": lambda: learn_route(cfg, "Voisin", "Famille/Voisin")}[name]
    # DOC534.234: the contract the comment states, as assertions: callers that catch ValueError are protected, and a YAML error is not
    # what they get
    assert issubclass(LearnedFileError, ValueError) and not issubclass(LearnedFileError, yaml.YAMLError)
    for operation in (lambda: list_rules(cfg), writes_that_file):
        with pytest.raises(LearnedFileError, match=name) as caught:             # named, and a plain ValueError (not a YAMLError)
            operation()
        assert isinstance(caught.value, ValueError) and not isinstance(caught.value, yaml.YAMLError)
    assert bad.read_bytes() == before                                            # the user's rules are NEVER overwritten
    caplog.clear()
    reloaded = load_config(sandbox=tmp_path)                                      # loading the configuration must not crash...
    assert "Hydro-Quebec" in reloaded.companies                                   # ...it keeps the hand-written rules...
    assert name in caplog.text and "ignored" in caplog.text                       # ...and says which learned file it ignored
