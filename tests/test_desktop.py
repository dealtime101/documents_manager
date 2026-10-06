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
    assert report == {"version": __version__, "signed_in": True, "database_in_user_folder": True, "interface": True}
    assert (tmp_path / "home" / "docflow.db").is_file()
