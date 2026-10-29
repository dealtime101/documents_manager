import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "DOCFLOW_HOME": str(tmp_path / "home"), "DOCFLOW_ROOT": str(ROOT),
           "DJANGO_SETTINGS_MODULE": "webapp.settings"}
    for key in ("DOCFLOW_SANDBOX", "DOCFLOW_SECRET_KEY", "DOCFLOW_HOSTS", "DOCFLOW_CONFIG_DIR"):
        env.pop(key, None)
    return env


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
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("free_port", lambda: 1),
                        ("start_server", lambda port: None)):
        monkeypatch.setattr(desktop, name, value)
    good = {"signed_in": True, "interface": True, "database_in_user_folder": True, "version": "x", "ocr": []}
    results = iter([good, {**good, "signed_in": False}, {**good, "interface": False}, {**good, "database_in_user_folder": False}])
    monkeypatch.setattr(desktop, "selftest", lambda port, token: next(results))
    assert [desktop.main(["--selftest"]) for _ in range(4)] == [0, 1, 1, 1]
    assert capsys.readouterr().out.count('"signed_in"') == 4                         # and the result is still printed each time


def test_without_a_native_window_the_browser_fallback_stops_when_no_browser_opens_and_on_ctrl_c(monkeypatch, capsys):
    # DOC534.36: the return value of webbrowser.open was ignored and the process then waited for ever, with nothing to see or to stop
    import sys
    import webbrowser

    from docflow import desktop
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("free_port", lambda: 1),
                        ("start_server", lambda port: None)):
        monkeypatch.setattr(desktop, name, value)
    monkeypatch.setitem(sys.modules, "webview", None)                         # `import webview` raises ImportError

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
        desktop.start_server(desktop.free_port())
    except RuntimeError as e:
        assert "port already in use" in str(e) and time.monotonic() - started < 20     # the cause, not "within 30 seconds"
    else:
        raise AssertionError("start_server should have raised")
    shown = []
    for name, value in (("log_to_file", lambda: None), ("prepare_environment", lambda: "tok"), ("free_port", lambda: 1)):
        monkeypatch.setattr(desktop, name, value)
    monkeypatch.setattr(desktop, "show_error", shown.append)
    monkeypatch.setattr(desktop, "start_server", lambda port: (_ for _ in ()).throw(RuntimeError("migration failed")))
    assert desktop.main([]) == 1                                                      # an exit code, not a traceback
    assert len(shown) == 1 and "migration failed" in shown[0] and "desktop.log" in shown[0]   # and a message with the log's place


def test_a_free_local_port_is_found_and_really_free():
    from docflow.desktop import free_port
    port = free_port()
    assert 1024 <= port <= 65535
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))                                       # nobody holds it


def test_the_desktop_selftest_starts_the_server_signs_in_and_keeps_every_file_in_the_users_folder(tmp_path):
    # the same start-up as the application, without the window: it must create its database in the USER's folder (the program
    # folder of a packaged application is read-only), sign in with the launcher's token, and report its version
    run = subprocess.run([sys.executable, "-m", "docflow.desktop", "--selftest"], env=_env(tmp_path), capture_output=True, text=True,
                         timeout=120, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(run.stdout.strip().splitlines()[-1])
    from docflow import __version__
    assert isinstance(report.pop("ocr"), list)                      # the languages this machine can read (none without Tesseract)
    assert report == {"version": __version__, "signed_in": True, "database_in_user_folder": True, "interface": True}
    assert (tmp_path / "home" / "docflow.db").is_file()
