"""DOC534.11: backup and restore of the database, the learned corrections, the user's rules and (on request) the folders of Settings."""
import io
import json
import sqlite3
import zipfile

import pytest
import yaml
from docflow import backup, usersettings
from docflow.cli import main
from docflow.config import load_config
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A user's folder (settings, rules), a sandbox configuration with its learned files, and a database with one row in it."""
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    monkeypatch.setenv("DOCFLOW_HOME", str(home))
    cfg = load_config(sandbox=tmp_path / "sb")
    cfg.learn_dir.mkdir(parents=True, exist_ok=True)
    (cfg.learn_dir / "company_aliases.yaml").write_text("Hydro-Québec: [hydro]\n", encoding="utf-8")
    (home / "config" / "companies.yaml").write_text("Garage: [garage]\n", encoding="utf-8")
    db = cfg.path("db")
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE doc (name TEXT)")
        c.execute("INSERT INTO doc VALUES ('facture-secrete.pdf')")
    return cfg


def rows(cfg) -> list[str]:
    c = sqlite3.connect(cfg.path("db"))
    try:
        return [r[0] for r in c.execute("SELECT name FROM doc ORDER BY rowid")]
    finally:
        c.close()


def test_the_archive_holds_the_database_the_learned_files_the_user_rules_and_a_manifest(world, tmp_path):
    names = backup.create(world, tmp_path / "b.zip", version="9.9")
    assert sorted(names) == ["config/companies.yaml", "docflow.db", "learned/company_aliases.yaml"]
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        assert sorted(z.namelist()) == sorted([*names, "manifest.json"])
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["format"] == 1 and manifest["version"] == "9.9" and sorted(manifest["contains"]) == sorted(names)
        z.extract("docflow.db", tmp_path / "out")
    assert [r[0] for r in sqlite3.connect(tmp_path / "out" / "docflow.db").execute("SELECT name FROM doc")] == ["facture-secrete.pdf"]


def test_the_database_is_copied_whole_while_another_connection_has_it_open_and_is_writing(world, tmp_path):
    other = sqlite3.connect(world.path("db"), isolation_level=None)
    other.execute("PRAGMA journal_mode=WAL")
    other.execute("BEGIN IMMEDIATE")
    other.execute("INSERT INTO doc VALUES ('en-cours.pdf')")
    other.execute("COMMIT")
    backup.create(world, tmp_path / "b.zip")
    other.close()
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        z.extract("docflow.db", tmp_path / "out")
    assert sorted(r[0] for r in sqlite3.connect(tmp_path / "out" / "docflow.db").execute("SELECT name FROM doc")) == [
        "en-cours.pdf", "facture-secrete.pdf"]


def test_a_password_encrypts_the_archive_and_only_that_password_opens_it(world, tmp_path):
    backup.create(world, tmp_path / "plain.zip")
    backup.create(world, tmp_path / "secret.zip", "s3cret")
    assert not backup.encrypted(tmp_path / "plain.zip") and backup.encrypted(tmp_path / "secret.zip")
    assert b"facture-secrete" not in (tmp_path / "secret.zip").read_bytes()  # the database is not readable in it
    with pytest.raises(backup.BackupError, match="password"):
        backup.restore(world, tmp_path / "secret.zip")                    # none given
    with pytest.raises(backup.BackupError, match="wrong password"):
        backup.restore(world, tmp_path / "secret.zip", "nope")
    assert backup.restore(world, tmp_path / "secret.zip", "s3cret")["restored"]
    assert backup.restore(world, tmp_path / "plain.zip", "unneeded")["restored"]  # a password nobody asked for does no harm


def test_restore_gives_back_the_database_and_the_rules_and_keeps_what_it_replaced(world, tmp_path):
    backup.create(world, tmp_path / "b.zip")
    with sqlite3.connect(world.path("db")) as c:
        c.execute("DELETE FROM doc")
        c.execute("INSERT INTO doc VALUES ('apres.pdf')")
    (world.learn_dir / "company_aliases.yaml").write_text("Autre: [autre]\n", encoding="utf-8")
    (usersettings.user_dir() / "config" / "companies.yaml").unlink()
    result = backup.restore(world, tmp_path / "b.zip")
    assert sorted(result["restored"]) == ["config/companies.yaml", "docflow.db", "learned/company_aliases.yaml"]
    assert rows(world) == ["facture-secrete.pdf"]
    assert yaml.safe_load((world.learn_dir / "company_aliases.yaml").read_text(encoding="utf-8")) == {"Hydro-Québec": ["hydro"]}
    assert (usersettings.user_dir() / "config" / "companies.yaml").is_file()
    with zipfile.ZipFile(result["safety_copy"]) as z:               # the state before the restore, ready to be restored itself
        z.extract("docflow.db", tmp_path / "before")
    assert [r[0] for r in sqlite3.connect(tmp_path / "before" / "docflow.db").execute("SELECT name FROM doc")] == ["apres.pdf"]


@pytest.mark.parametrize("member", ["../evil.yaml", "learned/../evil.yaml", "learned/sub/x.yaml", "/abs.yaml", "learned/x.txt",
                                    "other/x.yaml", "learned/C:evil.yaml", "learned\\x.yaml"])
def test_an_archive_with_a_name_this_program_never_writes_is_refused_before_anything_is_touched(world, tmp_path, member):
    backup.create(world, tmp_path / "b.zip")
    with zipfile.ZipFile(tmp_path / "b.zip", "a") as z:
        z.writestr(member, "x: 1\n")
    with sqlite3.connect(world.path("db")) as c:
        c.execute("INSERT INTO doc VALUES ('garde.pdf')")
    with pytest.raises(backup.BackupError, match="not a backup"):
        backup.restore(world, tmp_path / "b.zip")
    assert rows(world) == ["facture-secrete.pdf", "garde.pdf"] and not (tmp_path / "evil.yaml").exists()
    assert not (usersettings.user_dir() / "backups").exists()


def test_what_is_not_a_backup_or_is_damaged_is_refused_and_says_why(world, tmp_path):
    (tmp_path / "text.zip").write_text("not a zip")
    with pytest.raises(backup.BackupError, match="not a backup"):
        backup.restore(world, tmp_path / "text.zip")
    with zipfile.ZipFile(tmp_path / "nomanifest.zip", "w") as z:
        z.writestr("docflow.db", b"")
    with pytest.raises(backup.BackupError, match="not a backup"):
        backup.restore(world, tmp_path / "nomanifest.zip")

    def archive(name, members, manifest=None):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest or {"format": 1}))
            for member, data in members.items():
                z.writestr(member, data)
        return tmp_path / name
    with pytest.raises(backup.BackupError, match="different version"):
        backup.restore(world, archive("v2.zip", {}, {"format": 2}))
    with pytest.raises(backup.BackupError, match="not readable: learned/a.yaml"):
        backup.restore(world, archive("yml.zip", {"learned/a.yaml": b"a: [unclosed"}))
    with pytest.raises(backup.BackupError, match="not readable"):
        backup.restore(world, archive("bytes.zip", {"learned/a.yaml": b"\xff\xfe\x00"}))
    with pytest.raises(backup.BackupError, match="database in this backup is damaged"):
        backup.restore(world, archive("db.zip", {"docflow.db": b"this is not a database" * 100}))
    assert rows(world) == ["facture-secrete.pdf"]


def test_a_database_from_a_newer_program_is_refused_and_an_older_one_is_taken(world, tmp_path):
    other = tmp_path / "other.db"
    with sqlite3.connect(other) as c:
        c.execute("CREATE TABLE django_migrations (app TEXT, name TEXT)")
        c.execute("INSERT INTO django_migrations VALUES ('triage', '0001_initial'), ('triage', '0099_future')")
    with zipfile.ZipFile(tmp_path / "n.zip", "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 1}))
        z.write(other, "docflow.db")
    with pytest.raises(backup.BackupError, match="newer version"):
        backup.restore(world, tmp_path / "n.zip", known_migrations=lambda: {"triage.0001_initial", "triage.0002_scanjob"})
    assert backup.restore(world, tmp_path / "n.zip", known_migrations=lambda: {"triage.0001_initial", "triage.0099_future"})["restored"]


def test_the_settings_come_back_only_on_request_only_the_folders_that_exist_and_never_the_place_of_the_database(world, tmp_path):
    inbox, library = tmp_path / "Inbox", tmp_path / "Library"
    inbox.mkdir()
    library.mkdir()
    usersettings.save({"inbox": str(inbox), "library_root": str(library), "watch_inbox": True})
    backup.create(world, tmp_path / "b.zip")
    # this computer: the same folders do not exist any more (a new machine), and the settings are different
    (usersettings._file()).write_text(yaml.safe_dump({"watch_inbox": False}), encoding="utf-8")
    assert backup.restore(world, tmp_path / "b.zip")["settings_skipped"] == {}                 # not asked: untouched
    assert usersettings.load() == {"watch_inbox": False}
    inbox.rmdir()
    result = backup.restore(world, tmp_path / "b.zip", with_settings=True)
    assert set(result["settings_skipped"]) >= {"inbox"} and "does not exist" in result["settings_skipped"]["inbox"]
    assert usersettings.load().get("watch_inbox") is True and "inbox" not in usersettings.load()
    # the archive may carry a database place of another computer: it is not taken
    with zipfile.ZipFile(tmp_path / "evil.zip", "w") as z:
        z.writestr("manifest.json", json.dumps({"format": 1}))
        z.writestr("settings.yaml", yaml.safe_dump({"db": "/elsewhere/docflow.db", "watch_inbox": True}))
    backup.restore(world, tmp_path / "evil.zip", with_settings=True)
    assert "db" not in usersettings.load()


# ------------------------------------------------------------------------------------------------------ the web


def test_the_download_is_a_zip_with_its_own_name_and_the_password_is_in_the_body(api, sb, monkeypatch, settings):
    monkeypatch.setenv("DOCFLOW_HOME", str(sb / "home"))
    sqlite3.connect(settings.DOCFLOW.path("db")).close()
    r = api.post("/api/backup", {}, format="json")
    assert r.status_code == 200 and r["Content-Type"] == "application/zip" and r["X-Content-Type-Options"] == "nosniff"
    assert r["Content-Disposition"].startswith("attachment") and "documents-manager-backup-" in r["Content-Disposition"]
    body = b"".join(r.streaming_content)
    assert not backup.encrypted(io.BytesIO(body)) and "manifest.json" in zipfile.ZipFile(io.BytesIO(body)).namelist()
    r = api.post("/api/backup", {"password": "pw"}, format="json")
    assert backup.encrypted(io.BytesIO(b"".join(r.streaming_content)))
    assert api.post("/api/backup", {"password": 5}, format="json").status_code == 400


def test_the_restore_takes_the_upload_and_answers_what_it_did_or_why_not(api, sb, monkeypatch, settings):
    monkeypatch.setenv("DOCFLOW_HOME", str(sb / "home"))
    cfg = settings.DOCFLOW
    cfg.learn_dir.mkdir(parents=True, exist_ok=True)
    (cfg.learn_dir / "company_aliases.yaml").write_text("Un: [un]\n", encoding="utf-8")
    sqlite3.connect(cfg.path("db")).close()
    archive = b"".join(api.post("/api/backup", {"password": "pw"}, format="json").streaming_content)
    (cfg.learn_dir / "company_aliases.yaml").write_text("Deux: [deux]\n", encoding="utf-8")

    def upload(data=archive, **fields):
        from django.core.files.uploadedfile import SimpleUploadedFile
        body = {"file": SimpleUploadedFile("b.zip", data), **fields} if data is not None else dict(fields)
        return api.post("/api/backup/restore", body, format="multipart")
    r = upload(password="wrong")
    assert r.status_code == 400 and r.json()["detail"] == "wrong password"
    assert upload(None).status_code == 400
    assert upload(b"not a zip").status_code == 400 and "not a backup" in upload(b"not a zip").json()["detail"]
    r = upload(password="pw")
    assert r.status_code == 200 and "learned/company_aliases.yaml" in r.json()["restored"] and r.json()["safety_copy"]
    assert yaml.safe_load((cfg.learn_dir / "company_aliases.yaml").read_text(encoding="utf-8")) == {"Un": ["un"]}


def test_both_need_a_logged_in_user(sb):
    from rest_framework.test import APIClient
    assert APIClient().post("/api/backup").status_code in (401, 403)
    assert APIClient().post("/api/backup/restore").status_code in (401, 403)


# ------------------------------------------------------------------------------------------------------ the command line


def test_the_command_line_writes_a_backup_never_over_a_file_and_restores_it(world, tmp_path, monkeypatch, capsys):
    sandbox = ["--sandbox", str(tmp_path / "sb")]
    target = tmp_path / "cli.zip"
    assert main([*sandbox, "backup", str(target)]) == 0 and target.is_file()
    assert "Backup written" in capsys.readouterr().out
    assert main([*sandbox, "backup", str(target)]) == 1 and "exists already" in capsys.readouterr().out   # nothing is overwritten
    with sqlite3.connect(world.path("db")) as c:
        c.execute("DELETE FROM doc")
    assert main([*sandbox, "restore", str(target)]) == 0
    assert rows(world) == ["facture-secrete.pdf"] and "previous state is kept" in capsys.readouterr().out
    assert main([*sandbox, "restore", str(tmp_path / "absent.zip")]) == 1 and "Cannot restore" in capsys.readouterr().out


def test_the_command_line_asks_for_the_password_twice_when_it_encrypts_and_once_when_it_restores(world, tmp_path, monkeypatch, capsys):
    typed = iter(["pw", "pw", "pw"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(typed))
    sandbox = ["--sandbox", str(tmp_path / "sb")]
    assert main([*sandbox, "backup", str(tmp_path / "e.zip"), "--encrypt"]) == 0 and backup.encrypted(tmp_path / "e.zip")
    assert main([*sandbox, "restore", str(tmp_path / "e.zip")]) == 0
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a" if "Again" not in prompt else "b")
    assert main([*sandbox, "backup", str(tmp_path / "f.zip"), "--encrypt"]) == 1 and not (tmp_path / "f.zip").exists()
    capsys.readouterr()


def test_the_settings_screen_offers_the_backup_and_the_restore():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    page = (src / "components" / "BackupRestore.tsx").read_text(encoding="utf-8")
    assert "api.backup(" in page and "api.restore(" in page and "confirm(t('backup.confirmRestore'))" in page
    assert "'/api/backup'" in (src / "api.ts").read_text(encoding="utf-8")
    assert "<BackupRestore />" in (src / "App.tsx").read_text(encoding="utf-8")
