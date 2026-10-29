import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import python_path

ROOT = Path(__file__).resolve().parents[1]


def _env(tmp_path):
    env = {**os.environ, "PYTHONPATH": python_path(ROOT / "backend"), "DOCFLOW_HOME": str(tmp_path / "home"), "DOCFLOW_ROOT": str(ROOT),
           "DJANGO_SETTINGS_MODULE": "webapp.settings"}
    for key in ("DOCFLOW_SANDBOX", "DOCFLOW_SECRET_KEY", "DOCFLOW_HOSTS", "DOCFLOW_CONFIG_DIR"):
        env.pop(key, None)
    return env


SKIPPED_FOLDERS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build"}


def _files_under(root: Path) -> dict[str, tuple[int, int]]:
    """{path relative to root: (size, mtime in ns)} of the files of the program's folder, without the folders that tools and Python
    itself write to (version control, virtual environments, caches, build output)."""
    found = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED_FOLDERS]
        for name in names:
            path = Path(folder) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            found[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return found


def test_the_child_environment_keeps_the_pythonpath_the_machine_already_had(tmp_path, monkeypatch):
    # DOC534.249: PYTHONPATH was replaced by the backend folder, so a machine that finds its dependencies through it broke the self-test
    monkeypatch.setenv("PYTHONPATH", "/already/there")
    assert _env(tmp_path)["PYTHONPATH"].split(os.pathsep) == [str(ROOT / "backend"), "/already/there"]
    monkeypatch.delenv("PYTHONPATH")
    assert _env(tmp_path)["PYTHONPATH"] == str(ROOT / "backend")


def test_the_snapshot_of_the_program_folder_sees_a_created_a_changed_and_a_removed_file(tmp_path):
    (tmp_path / "keep.txt").write_text("a", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("a", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("a", encoding="utf-8")                # a cache folder: not looked at
    before = _files_under(tmp_path)
    assert set(before) == {"keep.txt", "gone.txt"}
    (tmp_path / "keep.txt").write_text("changed", encoding="utf-8")
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "new.txt").write_text("a", encoding="utf-8")
    after = _files_under(tmp_path)
    assert set(after) - set(before) == {"new.txt"} and set(before) - set(after) == {"gone.txt"} and before["keep.txt"] != after["keep.txt"]


@pytest.fixture(autouse=True)
def _main_never_starts_a_real_inbox_watcher(monkeypatch):
    from docflow import desktop
    monkeypatch.setattr(desktop, "start_inbox_watch", lambda *a, **k: None)


def _held_socket():
    """What main() gets from listening_socket(): only its port is read."""
    import types
    return types.SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1))


def test_the_settings_describe_the_one_deployment_there_is_a_local_desktop_application():
    # DOC534.33: the docstring said "LOCAL site (internal network): login required" and a comment "reached directly on the LAN",
    # while ALLOWED_HOSTS only lets 127.0.0.1 and localhost in (the server mode was removed)
    source = (ROOT / "backend" / "webapp" / "settings.py").read_text(encoding="utf-8")
    assert 'ALLOWED_HOSTS = ["127.0.0.1", "localhost"]' in source          # (the test settings add "testserver" at run time)
    assert "internal network" not in source and "login required" not in source and "on the LAN" not in source
    assert source.startswith('"""Django settings. Desktop application')


def test_the_selftest_exit_code_says_whether_it_passed(monkeypatch, capsys):
    # DOC534.35: --selftest printed the result and always returned 0: a script checking the packaged program never saw a failure
    from docflow import desktop
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("listening_socket", _held_socket),
                        ("start_server", lambda sock: None)):
        monkeypatch.setattr(desktop, name, value)
    good ={"signed_in": True, "interface": True, "database_in_user_folder": True, "version": "x", "ocr": []}
    results = iter([good, {**good, "signed_in": False}, {**good, "interface": False}, {**good, "database_in_user_folder": False}])
    monkeypatch.setattr(desktop, "selftest", lambda port, token: next(results))
    assert [desktop.main(["--selftest"]) for _ in range(4)] == [0, 1, 1, 1]
    assert capsys.readouterr().out.count('"signed_in"') == 4                         # and the result is still printed each time


def test_without_a_native_window_the_browser_fallback_stops_when_no_browser_opens_and_on_ctrl_c(monkeypatch, capsys):
    # DOC534.36: the return value of webbrowser.open was ignored and the process then waited for ever, with nothing to see or to stop
    import sys
    import webbrowser

    from docflow import desktop
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("listening_socket", _held_socket),
                        ("start_server", lambda sock: None)):
        monkeypatch.setattr(desktop, name, value)
    monkeypatch.setitem(sys.modules, "webview", None)                        # `import webview` raises ImportError

    class Interrupted:
        def wait(self):
            raise KeyboardInterrupt
    monkeypatch.setattr(desktop.threading, "Event", Interrupted)
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    assert desktop.main([]) == 1 and "No browser could be opened" in capsys.readouterr().out
    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    assert desktop.main([]) == 0 and "Stopped." in capsys.readouterr().out   # Ctrl-C ends it cleanly, without a traceback


def test_a_server_that_dies_at_start_is_reported_at_once_and_main_tells_the_user(monkeypatch, capsys):
    # DOC534.37: an exception in the waitress thread was lost (30 s of waiting, then a generic error) and main ended with no message
    import time

    import django.core.management
    import waitress

    from docflow import desktop

    def taken(*a, **k):
        raise OSError("port already in use")
    monkeypatch.setattr(waitress, "serve", taken)
    monkeypatch.setattr(django.core.management, "call_command", lambda *a, **k: None)   # the migration is not what is tested here
    started = time.monotonic()
    try:
        desktop.start_server(desktop.listening_socket())
    except RuntimeError as e:
        assert "port already in use" in str(e) and time.monotonic() - started < 20     # the cause, not "within 30 seconds"
    else:
        raise AssertionError("start_server should have raised")
    shown = []
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("listening_socket", _held_socket)):
        monkeypatch.setattr(desktop, name, value)
    monkeypatch.setattr(desktop, "show_error", shown.append)
    monkeypatch.setattr(desktop, "start_server", lambda sock: (_ for _ in ()).throw(RuntimeError("migration failed")))
    assert desktop.main([]) == 1                                                      # an exit code, not a traceback
    assert len(shown) == 1 and "migration failed" in shown[0] and "desktop.log" in shown[0]   # and a message with the log's place


def test_desktop_log_is_rotated_at_launch_when_it_has_grown_too_large(monkeypatch, tmp_path):
    # DOC534.133: desktop.log was only ever appended to, for years
    from docflow import desktop
    monkeypatch.setenv("DOCFLOW_HOME", str(tmp_path))
    log = tmp_path / "desktop.log"
    monkeypatch.setattr(sys, "stdout", None)                                         # a windowed program has no console
    monkeypatch.setattr(sys, "stderr", None)
    log.write_text("old line\n" * 10)                                                # small: appended to, as before
    desktop.log_to_file()
    sys.stdout.write("new line\n")
    sys.stdout.close()
    assert log.read_text(encoding="utf-8").endswith("new line\n") and log.read_text(encoding="utf-8").startswith("old line") and not (tmp_path / "desktop.log.1").exists()
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log.write_bytes(b"x" * (desktop.LOG_MAX_BYTES + 1))                              # too large: kept as .1, a fresh log starts
    desktop.log_to_file()
    sys.stdout.write("fresh start\n")
    sys.stdout.close()
    assert log.read_text(encoding="utf-8") == "fresh start\n" and (tmp_path / "desktop.log.1").stat().st_size == desktop.LOG_MAX_BYTES + 1


def test_the_interface_check_reads_enough_of_the_page_and_looks_at_the_title_only():
    # DOC534.132: 400 bytes were read, so a title after many meta / preload tags was a false failure; and two tests said one thing
    import inspect

    from docflow import desktop
    head = "".join(f'<link rel="modulepreload" href="/assets/chunk-{n}.js">\n' for n in range(120))                  # about 6 KB of tags
    page = f"<!doctype html><html><head>{head}<title>Documents Manager</title></head><body></body></html>"
    assert page.index("<title>") > 400 and desktop.interface_is_ours(page)                    # the title is found far from the start
    assert not desktop.interface_is_ours("<html><head><title>Other</title></head><body>Documents Manager</body></html>")   # not the name anywhere
    assert desktop.INTERFACE_READ_BYTES >= 16 * 1024 and "read(INTERFACE_READ_BYTES)" in inspect.getsource(desktop.selftest)   # and enough is read


def test_the_port_is_held_from_the_moment_it_is_chosen_and_only_our_own_server_counts_as_up(tmp_path):
    # DOC534.130: the port was given back before the server bound it, and any program that listened there made the start look done
    import http.server
    import threading

    from docflow.desktop import SERVER_IDENT, is_our_server, listening_socket
    held = listening_socket()
    port = held.getsockname()[1]
    try:
        assert 1024 <= port <= 65535 and held.getsockname()[0] == "127.0.0.1"          # loopback only
        with socket.socket() as other, pytest.raises(OSError):
            other.bind(("127.0.0.1", port))                                          # nobody else can take it meanwhile
        assert is_our_server(port) is False                                          # a socket that only listens is not our server
    finally:
        held.close()

    def serve_with(header: str):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response_only(200)                                         # (send_response adds a Server header of its own)
                self.send_header("Server", header)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    ours, someone_else = serve_with(SERVER_IDENT), serve_with("something-else")
    try:
        assert is_our_server(ours.server_address[1]) is True and is_our_server(someone_else.server_address[1]) is False
    finally:
        ours.shutdown()
        someone_else.shutdown()
    assert is_our_server(port) is False                                              # nothing there any more: not up


def test_the_desktop_selftest_starts_the_server_signs_in_and_keeps_every_file_in_the_users_folder(tmp_path):
    # the same start-up as the application, without the window: it must create its database in the USER's folder (the program
    # folder of a packaged application is read-only), sign in with the launcher's token, and report its version
    before = _files_under(ROOT)
    run = subprocess.run([sys.executable, "-m", "docflow.desktop", "--selftest"], env=_env(tmp_path), capture_output=True, text=True,
                         timeout=120, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    # DOC534.248: "every file in the user's folder" is checked on the files, not only on the report that the program makes of itself:
    # nothing in the program's own folder (read-only once packaged) was created, changed or removed by the run
    after = _files_under(ROOT)
    assert after == before, {"created": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
                             "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k])}
    report = json.loads(run.stdout.strip().splitlines()[-1])
    from docflow import __version__
    assert isinstance(report.pop("ocr"), list)                      # the languages this machine can read (none without Tesseract)
    assert report == {"version": __version__, "signed_in": True, "database_in_user_folder": True, "interface": True}
    assert (tmp_path / "home" / "docflow.db").is_file()
