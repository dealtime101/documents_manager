"""Django settings. LOCAL site (internal network): login required, no telemetry, no external service."""
import os
import secrets
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from docflow.config import load_config

BASE_DIR = Path(__file__).resolve().parents[2]
SANDBOX = Path(os.environ["DOCFLOW_SANDBOX"]) if os.environ.get("DOCFLOW_SANDBOX") else None
DOCFLOW = load_config(sandbox=SANDBOX)  # same config as the CLI; sandbox if DOCFLOW_SANDBOX is set
# What the web app keeps for itself (signing key, rate-limit counters): in the sandbox with its database, never in the real storage
STATE_DIR = SANDBOX if SANDBOX else BASE_DIR / "storage"


def load_or_create_secret(f: Path) -> str:
    """Several workers may start together on the very first run: the key is written COMPLETE to a private temporary
    file (mkstemp: mode 0600 from the start) and published with a hard link, which fails if someone else got there
    first. Everybody then reads the one key that won; nobody ever sees a half-written or world-readable file."""
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".django_secret.")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(secrets.token_urlsafe(64))
                out.flush()
                os.fsync(out.fileno())  # on the disk BEFORE it is published: a power cut must not leave a published empty file
            try:
                os.link(tmp, f)
                dir_fd = os.open(f.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)  # and the publication itself (the new directory entry) too
                finally:
                    os.close(dir_fd)
            except FileExistsError:
                pass  # another process published its key first: use that one
        finally:
            os.unlink(tmp)
    key = f.read_text().strip()
    if not key:  # never a blank key (it would sign sessions with nothing): and never silently replaced either, a race
        raise RuntimeError(f"{f} is empty: delete it so that a new key is generated")
    return key


def _secret() -> str:
    if os.environ.get("DOCFLOW_SECRET_KEY"):
        return os.environ["DOCFLOW_SECRET_KEY"]
    return load_or_create_secret(STATE_DIR / ".django_secret")


SECRET_KEY = _secret()
DEBUG = os.environ.get("DOCFLOW_DEBUG") == "1"


def parse_hosts(raw: str) -> list[str]:
    """'a, b ,,c' -> ['a', 'b', 'c']: spaces and empty entries dropped, repeats listed once. A host with a stray space never
    matches the Host header (a site that answers 400 to everybody), so a setting with NO host at all is refused outright."""
    hosts = list(dict.fromkeys(h.strip() for h in raw.split(",") if h.strip()))
    if not hosts:
        raise ImproperlyConfigured("DOCFLOW_HOSTS is set but lists no host name: give at least one, e.g. localhost")
    return hosts


# this machine's own names and address go in the service (DOCFLOW_HOSTS in deploy/docflow-web.service), not in the code
HOSTS = parse_hosts(os.environ.get("DOCFLOW_HOSTS", "localhost,127.0.0.1"))
ALLOWED_HOSTS = HOSTS
CSRF_TRUSTED_ORIGINS = [f"http://{h}:{os.environ.get('DOCFLOW_PORT', '8420')}" for h in HOSTS]

INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "rest_framework", "triage",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "webapp.urls"
WSGI_APPLICATION = "webapp.wsgi.application"
# The scan writes in the background while web requests write too. Wait up to 20 s for a lock (the default is 5 s: "database
# is locked" in the middle of a scan) and use the write-ahead log so that readers are not blocked by a writer. WAL needs a
# LOCAL disk: the database must not be moved to a network share.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3", "NAME": str(DOCFLOW.path("db")),
    # IMMEDIATE: a transaction takes the write lock when it BEGINS, so it waits for the busy timeout like any writer. A deferred
    # one that reads first and writes later gets "database is locked" at once if a scan wrote in between (WAL), timeout or not.
    "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE",
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"},
}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "fr-ca"
TIME_ZONE = "America/Toronto"
USE_TZ = True

# What goes wrong must reach the journal (`journalctl -u docflow-web`) whatever DEBUG is: by default, with DEBUG off, Django sends
# the traceback of a 500 only to mail_admins, and no ADMINS or mail server is configured here, so it would be lost. The engine
# (docflow) and the web app (triage) log their warnings and errors the same way. systemd adds the time, so the format has none.
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain", "level": "WARNING"}},
    "loggers": {name: {"handlers": ["console"], "level": "WARNING", "propagate": False} for name in ("django", "docflow", "triage")},
}

# Shared by the gunicorn workers (a per-process cache would multiply every limit by the number of workers).
CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                      "LOCATION": str(STATE_DIR / ".cache")}}

REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {"login": "10/min"},
    # The server is reached directly on the LAN: trust REMOTE_ADDR only. With the default (None) DRF believes a client's
    # X-Forwarded-For header, and forging it would reset every per-address limit.
    "NUM_PROXIES": 0,
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
X_FRAME_OPTIONS = "SAMEORIGIN"  # the PDF preview is shown in a frame of the same page
SECURE_CONTENT_TYPE_NOSNIFF = True
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
SCAN_ASYNC = os.environ.get("DOCFLOW_SCAN_SYNC") != "1"  # background scan (tests switch it to synchronous)
