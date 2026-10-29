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
    failure: list[BaseException] = []  # what the server thread died of (port taken, WSGI error): seen at once, not after 30 seconds

    def run() -> None:
        try:
            serve(app, host="127.0.0.1", port=port, threads=6, ident="documents-manager")
        except BaseException as e:  # noqa: BLE001
            failure.append(e)  # kept for the main thread, which reports it

    threading.Thread(target=run, daemon=True).start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if failure:
            raise RuntimeError(f"the local server stopped: {type(failure[0]).__name__}: {failure[0]}") from failure[0]
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("the local server did not start within 30 seconds")


def ocr_languages() -> list[str]:
    """The OCR languages the application can read (empty when there is no Tesseract): asks the Tesseract it would really use."""
    import subprocess

    from docflow.extract import NO_WINDOW, _env_for, find_tesseract
    exe = find_tesseract("tesseract")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30, env=_env_for(exe), check=False,
                             creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(line.strip() for line in out.splitlines()[1:] if line.strip())


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
    return {"ocr": ocr_languages(), "version": me["version"], "signed_in": signed_in, "database_in_user_folder": (user_dir() / "docflow.db").is_file(),
            "interface": "<title>Documents Manager</title>" in page or "Documents Manager" in page}


def log_to_file() -> None:
    """A windowed program has no console (stdout / stderr are None): what it says goes to desktop.log in the user's folder."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from docflow.usersettings import user_dir
    user_dir().mkdir(parents=True, exist_ok=True)
    log = (user_dir() / "desktop.log").open("a", encoding="utf-8", buffering=1)  # kept open for the whole run
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def show_error(message: str) -> None:
    """Without a console the user sees nothing: on Windows a message box, everywhere the message goes to the log."""
    print(message, file=sys.stderr, flush=True)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Documents Manager", 0x10)  # MB_ICONERROR


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    log_to_file()
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "starting", argv, flush=True)
    try:
        token = prepare_environment()
        port = free_port()
        print("server starting on port", port, flush=True)
        start_server(port)
    except Exception as e:  # noqa: BLE001
        # a failed start (migration, port, server) must be told, not end in silence
        import traceback

        from docflow.usersettings import user_dir
        traceback.print_exc()
        show_error(f"Documents Manager could not start: {type(e).__name__}: {e}\nDetails: {user_dir() / 'desktop.log'}")
        return 1
    print("server up", flush=True)
    if "--selftest" in argv:
        result = selftest(port, token)
        print(json.dumps(result))
        return 0 if result["signed_in"] and result["interface"] and result["database_in_user_folder"] else 1  # a script can tell
    url = f"http://127.0.0.1:{port}/?t={token}"
    try:
        import webview
    except ImportError:  # no native window available: the default browser shows the same page
        import webbrowser
        if not webbrowser.open(url):  # nothing opened: do not keep a server nobody can reach running (the address goes to desktop.log)
            print("No browser could be opened. The program stops; open the application from a machine with a window system.", flush=True)
            return 1
        print("Opened in the default browser. Press Ctrl-C to stop the program.", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("Stopped.", flush=True)
        return 0
    webview.create_window("Documents Manager", url, width=1280, height=840, min_size=(900, 600))
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
