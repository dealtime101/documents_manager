import sqlite3
from datetime import datetime

import pytest
from docflow.backup import make_backup, restore

LEARNED = ("company_aliases.yaml", "types_learned.yaml", "routing_learned.yaml")


@pytest.fixture
def live(tmp_path):
    """A WAL database with rows still in the -wal file (never checkpointed), and the learned rule files."""
    db = tmp_path / "storage" / "docflow.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t(x)")
    conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    learn = tmp_path / "config"
    learn.mkdir()
    for name in LEARNED:
        (learn / name).write_text(f"# {name}\n", encoding="utf-8")
    yield db, learn, conn
    conn.close()


def test_a_backup_holds_a_consistent_copy_of_the_live_database_and_the_learned_rules(live, tmp_path):
    db, learn, _conn = live
    out = make_backup(db, learn, tmp_path / "nas", keep=5, now=datetime(2026, 10, 5, 3, 0, 0))
    assert out.name == "docflow-20261005-030000"                                  # a dated folder, never overwritten
    copy = sqlite3.connect(out / "docflow.db")
    assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert copy.execute("SELECT count(*) FROM t").fetchone() == (3,)               # the rows that lived only in the WAL are there
    copy.close()
    assert sorted(p.name for p in out.glob("*.yaml")) == sorted(LEARNED)


def test_a_missing_learned_file_is_skipped_not_an_error(live, tmp_path):
    db, learn, _conn = live
    (learn / "types_learned.yaml").unlink()
    out = make_backup(db, learn, tmp_path / "nas", keep=5, now=datetime(2026, 10, 5))
    assert not (out / "types_learned.yaml").exists() and (out / "company_aliases.yaml").exists()


def test_only_the_newest_backups_are_kept_and_nothing_else_is_touched(live, tmp_path):
    db, learn, _conn = live
    dest = tmp_path / "nas"
    (dest / "other").mkdir(parents=True)
    (dest / "notes.txt").write_text("mine")
    for day in range(1, 6):
        make_backup(db, learn, dest, keep=3, now=datetime(2026, 10, day))
    kept = sorted(p.name for p in dest.iterdir() if p.name.startswith("docflow-"))
    assert kept == ["docflow-20261003-000000", "docflow-20261004-000000", "docflow-20261005-000000"]
    assert (dest / "other").is_dir() and (dest / "notes.txt").read_text() == "mine"


def test_the_same_second_twice_does_not_overwrite_a_backup(live, tmp_path):
    db, learn, _conn = live
    when = datetime(2026, 10, 5, 3, 0, 0)
    first = make_backup(db, learn, tmp_path / "nas", keep=5, now=when)
    with pytest.raises(FileExistsError):
        make_backup(db, learn, tmp_path / "nas", keep=5, now=when)
    assert first.is_dir()


def test_a_destination_that_is_not_there_is_refused_not_created_from_nothing(live, tmp_path):
    db, learn, _conn = live
    with pytest.raises(FileNotFoundError, match="parent"):
        make_backup(db, learn, tmp_path / "unmounted" / "DocFlowBckp", keep=5)    # the share is not mounted: no silent local folder


def test_restore_puts_the_backup_back_and_keeps_what_it_replaces(live, tmp_path):
    db, learn, conn = live
    out = make_backup(db, learn, tmp_path / "nas", keep=5, now=datetime(2026, 10, 5))
    conn.execute("DELETE FROM t")
    conn.commit()
    conn.close()
    (learn / "company_aliases.yaml").write_text("# changed\n", encoding="utf-8")
    restore(out, db, learn)
    back = sqlite3.connect(db)
    assert back.execute("SELECT count(*) FROM t").fetchone() == (3,)
    back.close()
    assert (learn / "company_aliases.yaml").read_text(encoding="utf-8") == "# company_aliases.yaml\n"
    assert (learn / "company_aliases.yaml.before-restore").read_text(encoding="utf-8") == "# changed\n"   # nothing is lost
    assert (db.parent / "docflow.db.before-restore").is_file()
    assert not (db.parent / "docflow.db-wal").exists()                           # a stale log must not be replayed on the restored file


def test_restore_refuses_a_folder_that_is_not_a_backup(live, tmp_path):
    db, learn, _conn = live
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="docflow.db"):
        restore(tmp_path / "empty", db, learn)


class _Cfg:
    def __init__(self, db, learn, settings_):
        self._db, self.learn_dir, self.settings = db, learn, settings_

    def path(self, key):
        return self._db


def test_the_manage_command_backs_up_to_the_configured_folder_and_says_so_when_it_cannot(live, tmp_path, settings):
    from django.core.management import CommandError, call_command
    db, learn, _conn = live
    nas = tmp_path / "nas"
    nas.mkdir()
    settings.DOCFLOW = _Cfg(db, learn, {"backup": {"dir": str(nas / "DocFlowBckp"), "keep": 2}})
    call_command("backup")
    assert len(list((nas / "DocFlowBckp").glob("docflow-*"))) == 1
    settings.DOCFLOW = _Cfg(db, learn, {"backup": {"dir": str(tmp_path / "unmounted" / "DocFlowBckp")}})
    with pytest.raises(CommandError, match="mounted"):
        call_command("backup")
    settings.DOCFLOW = _Cfg(db, learn, {})
    with pytest.raises(CommandError, match="no destination"):
        call_command("backup")
    call_command("backup", "--to", str(nas / "explicit"))                          # an explicit folder works without any setting
    assert len(list((nas / "explicit").glob("docflow-*"))) == 1


def test_the_snapshot_is_made_on_the_local_disk_and_only_the_finished_file_is_copied_to_the_destination(live, tmp_path, monkeypatch):
    # a network share (CIFS) cannot take SQLite's file locks: writing the snapshot straight onto it hung forever
    import sqlite3 as real
    opened = []
    real_connect = real.connect

    def spy(target, *a, **k):
        opened.append(str(target))
        return real_connect(target, *a, **k)
    monkeypatch.setattr("docflow.backup.sqlite3.connect", spy)
    db, learn, _conn = live
    dest = tmp_path / "nas"
    make_backup(db, learn, dest, keep=5, now=datetime(2026, 10, 5))
    assert opened and not any(str(dest) in p for p in opened), opened
