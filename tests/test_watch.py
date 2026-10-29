"""DOC534.5: the files that arrive in the inbox are noticed (by polling), once they are complete, and analysed by themselves."""
import threading

import pytest
from docflow import cli, desktop, usersettings
from docflow.watch import FolderWatcher, watch


def test_a_new_file_is_reported_once_it_has_stopped_changing_and_only_once(tmp_path):
    files = []
    watcher = FolderWatcher(lambda: list(files))
    old = tmp_path / "old.pdf"
    old.write_bytes(b"x")
    files.append(old)
    assert watcher.poll() == []                                      # what is there when it starts is not "arriving"
    new = tmp_path / "new.pdf"
    new.write_bytes(b"12345")
    files.append(new)
    assert watcher.poll() == []                                      # seen for the first time: it may still be being written
    assert watcher.poll() == [new]                                   # the same size and time twice: it is complete
    assert watcher.poll() == [] and watcher.poll() == []             # and not reported again; the old file never was


def test_a_file_still_being_written_waits_and_a_changed_file_is_reported_again(tmp_path):
    files = []
    watcher = FolderWatcher(lambda: list(files))
    assert watcher.poll() == []
    copy = tmp_path / "scan.pdf"
    files.append(copy)
    for size in (10, 200, 3000):                                      # a copy that keeps growing is never reported
        copy.write_bytes(b"x" * size)
        assert watcher.poll() == []
    assert watcher.poll() == [copy]                                  # until it stops
    copy.write_bytes(b"y" * 4000)                                    # replaced by another content
    assert watcher.poll() == []
    assert watcher.poll() == [copy]                                  # a changed file is a new arrival


def test_a_file_that_left_is_forgotten_so_it_is_reported_again_if_it_comes_back(tmp_path):
    files = []
    watcher = FolderWatcher(lambda: list(files))
    watcher.poll()
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"1")
    files.append(pdf)
    watcher.poll()
    assert watcher.poll() == [pdf]
    files.clear()
    pdf.unlink()
    assert watcher.poll() == []
    pdf.write_bytes(b"1")                                            # the same name and content, back
    files.append(pdf)
    watcher.poll()
    assert watcher.poll() == [pdf]


def test_a_listed_file_that_vanishes_or_cannot_be_read_does_not_break_the_poll(tmp_path):
    ghost = tmp_path / "ghost.pdf"                                   # listed, but gone when it is looked at
    watcher = FolderWatcher(lambda: [ghost])
    assert watcher.poll() == [] and watcher.poll() == [] and watcher.poll() == []


def test_the_watch_loop_calls_back_survives_a_failure_and_stops_when_told(tmp_path):
    stop = threading.Event()
    got = []
    listings = iter([[], [], ["a"], ["a"], ["a"]])                   # nothing, nothing, then one file that stays
    boom = {"done": False}

    def list_files():
        if not boom["done"]:
            boom["done"] = True
            raise OSError("share unreachable")                      # the first listing fails: logged, the watch goes on
        return [tmp_path / name for name in next(listings, ["a"])]
    (tmp_path / "a").write_bytes(b"x")

    def on_arrival(paths):
        got.append(paths)
        stop.set()
    thread = threading.Thread(target=watch, args=(list_files, on_arrival, 0.01), kwargs={"stop": stop}, daemon=True)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive() and got == [[tmp_path / "a"]]


def test_the_watch_setting_is_a_boolean_that_is_saved_read_and_refused_otherwise(home):
    assert usersettings.load() == {}
    assert usersettings.validate({"watch_inbox": "yes"}) == {"watch_inbox": "must be true or false"}
    assert usersettings.validate({"watch_inbox": 1}) == {"watch_inbox": "must be true or false"}
    with pytest.raises(usersettings.InvalidSettings):
        usersettings.save({"watch_inbox": "yes"})
    assert usersettings.save({"watch_inbox": True}) == {"watch_inbox": True}
    assert usersettings.load()["watch_inbox"] is True
    assert usersettings.save({"watch_inbox": False}) == {"watch_inbox": False}         # off is a saved choice too
    assert usersettings.load()["watch_inbox"] is False


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCFLOW_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_the_desktop_starts_a_scan_when_a_pdf_arrives_only_while_the_setting_is_on(tmp_path, monkeypatch):
    from triage import services
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    state = {"on": False}
    started = threading.Event()
    calls = []
    monkeypatch.setattr(services, "source_files", lambda: sorted(inbox.glob("*.pdf")))
    monkeypatch.setattr(services, "scan_start", lambda: (calls.append(1), started.set()))
    monkeypatch.setattr(usersettings, "load", lambda: {"watch_inbox": state["on"]})
    stop = threading.Event()
    thread = _REAL_START_INBOX_WATCH(stop=stop, interval=0.01)
    try:
        (inbox / "a.pdf").write_bytes(b"%PDF-1.4 a")
        assert not started.wait(timeout=0.5) and calls == []        # the setting is off: nothing is looked at
        state["on"] = True                                          # switched on in Settings, no restart
        assert started.wait(timeout=10), "no scan was started for the file that arrived"
        assert calls == [1]
        started.clear()
        (inbox / "b.pdf").write_bytes(b"%PDF-1.4 b")
        assert started.wait(timeout=10) and len(calls) == 2         # and the next one is noticed too
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


_REAL_START_INBOX_WATCH = desktop.start_inbox_watch


@pytest.fixture(autouse=True)
def _the_other_tests_of_the_desktop_never_start_a_real_watcher(monkeypatch):
    monkeypatch.setattr(desktop, "start_inbox_watch", lambda *a, **k: None)


def test_main_starts_the_watcher_after_the_server_and_not_for_the_selftest(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "start_inbox_watch", lambda *a, **k: calls.append("watch"))
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"),
                        ("listening_socket", lambda: type("S", (), {"getsockname": lambda self: ("127.0.0.1", 1)})()),
                        ("start_server", lambda sock: None)):
        monkeypatch.setattr(desktop, name, value)
    monkeypatch.setattr(desktop, "selftest", lambda port, token: {"signed_in": True, "interface": True, "database_in_user_folder": True})
    monkeypatch.setitem(__import__("sys").modules, "webview", None)
    monkeypatch.setattr("webbrowser.open", lambda url: False)
    assert desktop.main(["--selftest"]) == 0 and calls == []        # a self-test starts nothing that runs on
    assert desktop.main([]) == 1 and calls == ["watch"]             # a normal start does (here no browser: it ends at once)


def test_docflow_watch_analyses_the_pdfs_that_arrive_without_moving_anything(tmp_path, monkeypatch, capsys):
    from docflow.config import load_config
    from docflow.db import DB
    cfg = load_config(sandbox=tmp_path)
    (tmp_path / "inbox").mkdir(exist_ok=True)
    scanned = threading.Event()
    seen = {}

    def fake_scan(cfg_, db_, dry, interactive, ollama, source=None, recursive=False, table=False):
        seen.update(dry=dry, interactive=interactive, table=table)
        scanned.set()
        return 0
    monkeypatch.setattr(cli, "scan", fake_scan)
    first_poll_done = threading.Event()
    real_poll = FolderWatcher.poll

    def counting_poll(self):                                         # (no sleep: the file is created only after the first look)
        result = real_poll(self)
        first_poll_done.set()
        return result
    monkeypatch.setattr(FolderWatcher, "poll", counting_poll)
    stop = threading.Event()
    with DB(":memory:") as db:
        thread = threading.Thread(target=cli.watch_inbox, args=(cfg, db, 0.01, stop), daemon=True)
        thread.start()
        try:
            assert first_poll_done.wait(timeout=10)
            (tmp_path / "inbox" / "new.pdf").write_bytes(b"%PDF-1.4 new")
            (tmp_path / "inbox" / "notes.txt").write_bytes(b"not a pdf")
            assert scanned.wait(timeout=10)
        finally:
            stop.set()
            thread.join(timeout=10)
    out = capsys.readouterr().out
    assert "1 PDF(s) arrived: new.pdf" in out and "notes.txt" not in out
    assert seen == {"dry": True, "interactive": False, "table": True}      # analysed, nothing filed
    assert (tmp_path / "inbox" / "new.pdf").exists()


def test_docflow_watch_refuses_a_missing_inbox_on_stderr(tmp_path, capsys):
    from docflow.config import load_config
    from docflow.db import DB
    cfg = load_config(sandbox=tmp_path)
    cfg.settings["inbox"] = str(tmp_path / "nowhere")
    with DB(":memory:") as db:
        assert cli.watch_inbox(cfg, db, 0.01, threading.Event()) == 2
    shown = capsys.readouterr()
    assert "ERROR: not a folder" in shown.err and shown.out == ""

