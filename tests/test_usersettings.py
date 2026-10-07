import pytest
from docflow import usersettings
from docflow.config import load_config


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("DOCFLOW_HOME", str(h))
    return h


def _folders(tmp_path):
    d = {name: tmp_path / name for name in ("inbox", "library", "quarantine", "extra")}
    for name in ("inbox", "library", "extra"):
        d[name].mkdir()
    return d


def test_the_user_folder_is_docflow_home_when_set_and_otherwise_a_per_user_place(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCFLOW_HOME", str(tmp_path / "h"))
    assert usersettings.user_dir() == tmp_path / "h"
    monkeypatch.delenv("DOCFLOW_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(usersettings.sys, "platform", "win32")
    assert usersettings.user_dir() == tmp_path / "local" / "DocFlow"
    monkeypatch.setattr(usersettings.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert usersettings.user_dir() == tmp_path / "xdg" / "docflow"


def test_nothing_saved_means_no_override(home):
    assert usersettings.load() == {}


def test_saved_folders_come_back_and_only_known_keys_are_kept(home, tmp_path):
    f = _folders(tmp_path)
    saved = usersettings.save({"inbox": str(f["inbox"]), "library_root": str(f["library"]),
                               "quarantine": str(f["quarantine"]), "extra_inboxes": [str(f["extra"])], "thresholds": {"auto": 0}})
    assert set(saved) == {"inbox", "library_root", "quarantine", "extra_inboxes"}      # a thresholds key is not a folder setting
    assert usersettings.load() == saved and (home / "settings.yaml").is_file()


def test_validation_names_each_wrong_folder(home, tmp_path):
    f = _folders(tmp_path)
    missing = usersettings.validate({"inbox": str(tmp_path / "missing"), "library_root": str(f["library"])})
    assert "inbox" in missing and "does not exist" in missing["inbox"]
    same = usersettings.validate({"inbox": str(f["inbox"]), "library_root": str(f["inbox"]), "quarantine": str(f["inbox"] / "q")})
    assert "different" in same["library_root"]                                           # the inbox and the library must not be the same folder
    assert "outside" in same["quarantine"]                                               # not inside the library: it would be filed into itself
    assert usersettings.validate({"inbox": str(f["inbox"]), "library_root": str(f["library"]), "quarantine": str(f["quarantine"])}) == {}


def test_saving_something_invalid_saves_nothing_and_says_why(home, tmp_path):
    with pytest.raises(usersettings.InvalidSettings) as e:
        usersettings.save({"inbox": str(tmp_path / "missing"), "library_root": str(tmp_path)})
    assert "inbox" in e.value.errors and not (home / "settings.yaml").exists()


def test_a_damaged_file_is_ignored_with_a_warning_not_a_crash(home, caplog):
    home.mkdir()
    (home / "settings.yaml").write_text("inbox: [unclosed", encoding="utf-8")
    assert usersettings.load() == {} and "settings.yaml" in caplog.text


def test_the_saved_folders_override_the_shipped_settings_and_a_change_is_picked_up_without_restart(home, tmp_path):
    f = _folders(tmp_path)
    cfg = load_config()
    assert cfg.refresh_learned() is False
    usersettings.save({"inbox": str(f["inbox"]), "library_root": str(f["library"]), "quarantine": str(f["quarantine"])})
    assert cfg.refresh_learned() is True                                                 # another worker saved: this one follows
    assert cfg.settings["inbox"] == str(f["inbox"]) and cfg.settings["library_root"] == str(f["library"])
    assert load_config().settings["quarantine"] == str(f["quarantine"])


def test_the_users_own_rule_files_and_learned_rules_live_in_their_folder_not_in_the_program(home, tmp_path):
    # a new install starts from the shipped (generic) rules; what the user wrote or learned is kept in THEIR folder
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "companies.yaml").write_text("Shipped:\n- shipped\n", encoding="utf-8")
    import os
    os.environ["DOCFLOW_CONFIG_DIR"] = str(shipped)
    try:
        assert set(load_config().companies) == {"Shipped"}
        (home / "config").mkdir(parents=True)
        (home / "config" / "companies.yaml").write_text("Mine:\n- mine\n", encoding="utf-8")
        assert set(load_config().companies) == {"Mine"}                                    # the user's copy replaces the shipped one
        (home / "learned").mkdir()
        (home / "learned" / "company_aliases.yaml").write_text("Learned:\n- learned\n", encoding="utf-8")
        assert set(load_config().companies) == {"Mine", "Learned"}                         # learned rules come from the user's folder
        cfg = load_config()
        from docflow.learn import learn_company
        learn_company(cfg, "Fresh", "texte fresh unique")
        assert (home / "learned" / "company_aliases.yaml").is_file() and cfg.learn_dir == home / "learned"
        assert not list(shipped.glob("*learned*"))                                          # nothing is ever written next to the program
    finally:
        del os.environ["DOCFLOW_CONFIG_DIR"]


def test_a_fresh_install_starts_empty_in_the_users_folder_and_says_it_is_not_configured(home, monkeypatch):
    # what ships with the program is generic: well-known public companies only, no destination, no folder of the author's
    from pathlib import Path

    from docflow.analyze import RuleBasedAnalyzer
    monkeypatch.setenv("DOCFLOW_CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "config"))
    cfg = load_config()
    assert "Amazon" in cfg.companies and cfg.types == [] and cfg.routing == {}
    assert cfg.configured is False                                                      # the first-run screen is due
    assert Path(cfg.settings["inbox"]).parent == home and Path(cfg.settings["db"]).parent == home    # nothing outside the user's folder
    assert cfg.settings["thresholds"]["auto"] == 0.95
    a = RuleBasedAnalyzer(cfg).analyze("Acme Corp\nInvoice 5 March 2025\nTotal $55.00")
    assert a.company is None and a.confidence == 0.0                                     # unknown company: a person decides
    f = home / "Inbox"
    f.mkdir(parents=True)
    (home / "Library").mkdir()
    usersettings.save({"inbox": str(f), "library_root": str(home / "Library")})
    assert cfg.refresh_learned() is True and cfg.configured is True                      # chosen: no longer a first run


def test_a_users_own_settings_yaml_overrides_section_by_section_it_does_not_replace_the_shipped_one(home):
    (home / "config").mkdir(parents=True)
    (home / "config" / "settings.yaml").write_text("ocr:\n  languages: eng\nextra_section:\n  a: 1\n", encoding="utf-8")
    s = load_config().settings
    assert s["extra_section"] == {"a": 1}                                                              # a section the user adds
    assert s["ocr"]["languages"] == "eng" and s["ocr"]["enabled"] is True                              # one key changed, the rest kept
    assert s["thresholds"]["auto"] == 0.95


def test_a_folder_windows_refuses_is_reported_as_refused_not_as_missing(home, tmp_path, monkeypatch):
    # an unconnected network share answers "access denied": telling the user it "does not exist" sends them looking in the wrong place
    from pathlib import Path
    real_stat = Path.stat
    refused = tmp_path / "share"

    def stat(self, *a, **k):
        if self == refused:
            raise PermissionError(13, "Access is denied")
        return real_stat(self, *a, **k)
    monkeypatch.setattr(Path, "stat", stat)
    errors = usersettings.validate({"inbox": str(refused), "library_root": str(tmp_path / "missing")})
    assert "refuses access" in errors["inbox"] and "connect" in errors["inbox"]
    assert "does not exist" in errors["library_root"]
    (tmp_path / "afile").write_text("x")
    assert "not a folder" in usersettings.validate({"inbox": str(tmp_path / "afile")})["inbox"]


def test_an_empty_optional_field_means_the_default_and_is_not_saved_as_an_error(home, tmp_path):
    f = _folders(tmp_path)
    saved = usersettings.save({"inbox": str(f["inbox"]), "library_root": str(f["library"]), "quarantine": "", "extra_inboxes": []})
    assert "quarantine" not in saved and usersettings.load()["inbox"] == str(f["inbox"])
