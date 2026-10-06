"""Documents Manager as a desktop application: starts the local server on 127.0.0.1, signs the window in with a one-time token and
shows the interface in a native window (the packaged .exe runs this). `--selftest` does everything except the window."""
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    """A port nobody holds right now, on the loopback address only."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def program_root() -> Path:
    """Where the interface build, the shipped rules and the release notes are: next to the executable's bundle when packaged."""
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[2]


def prepare_environment() -> str:
    """The environment of this run; returns the one-time sign-in token (known to this process and to nobody else)."""
    token = secrets.token_urlsafe(32)
    os.environ.update({"DOCFLOW_DESKTOP": "1", "DOCFLOW_LOCAL_TOKEN": token, "DJANGO_SETTINGS_MODULE": "webapp.settings",
                       "DOCFLOW_HOSTS": "127.0.0.1,localhost"})
    os.environ.setdefault("DOCFLOW_ROOT", str(program_root()))
    return token


def start_server(port: int) -> None:
    """Migrate the database (created in the user's folder) and serve the site in a background thread."""
    import django
    from django.core.management import call_command

    from docflow.usersettings import user_dir
    user_dir().mkdir(parents=True, exist_ok=True)
    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    from django.core.wsgi import get_wsgi_application
    from waitress import serve
    app = get_wsgi_application()
    threading.Thread(target=lambda: serve(app, host="127.0.0.1", port=port, threads=6, ident="documents-manager"), daemon=True).start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("the local server did not start within 30 seconds")


def selftest(port: int, token: str) -> dict:
    """What the window would do, without it: open the page, sign in with the token, read the version."""
    import http.cookiejar
    base = f"http://127.0.0.1:{port}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    me = json.load(opener.open(f"{base}/api/auth/me", timeout=15))
    csrf = next((c.value or "" for c in jar if c.name == "csrftoken"), "")
    request = urllib.request.Request(f"{base}/api/auth/local", data=json.dumps({"token": token}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-CSRFToken": csrf})
    try:
        opener.open(request, timeout=15)
        signed_in = json.load(opener.open(f"{base}/api/auth/me", timeout=15))["authenticated"]
    except urllib.error.HTTPError:
        signed_in = False
    page = opener.open(f"{base}/", timeout=15).read(400).decode("utf-8", "replace")
    from docflow.usersettings import user_dir
    return {"version": me["version"], "signed_in": signed_in, "database_in_user_folder": (user_dir() / "docflow.db").is_file(),
            "interface": "<title>Documents Manager</title>" in page or "Documents Manager" in page}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    token = prepare_environment()
    port = free_port()
    start_server(port)
    if "--selftest" in argv:
        print(json.dumps(selftest(port, token)))
        return 0
    url = f"http://127.0.0.1:{port}/?t={token}"
    try:
        import webview
    except ImportError:  # no native window available: the default browser shows the same page
        import webbrowser
        webbrowser.open(url)
        threading.Event().wait()
        return 0
    webview.create_window("Documents Manager", url, width=1280, height=840, min_size=(900, 600))
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
