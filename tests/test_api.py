from pathlib import Path

import pymupdf
import pytest
from django.contrib.auth import get_user_model
from docflow.config import load_config
from rest_framework.test import APIClient
from triage.models import Item, ScanJob

pytestmark = pytest.mark.django_db

HYDRO = ["Hydro-Quebec", "Facture d'electricite du 7 octobre 2025", "Numero de facture : 123456789",
         "Montant de la presente facture : 158,98 $"]
GARAGE = ["Garage Tremblay et Fils", "Date: 5 mars 2025", "Entretien complet du vehicule", "Total 80,00 $"]


def pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, t in enumerate(lines):
        page.insert_text((60, 90 + i * 22), t, fontsize=12)
    doc.save(path)
    return path


@pytest.fixture
def sb(tmp_path, settings):
    cfg = load_config(sandbox=tmp_path)
    settings.DOCFLOW = cfg
    settings.SCAN_ASYNC = False  # tests wait for the result; the real service scans in the background
    # a private throttle cache per test: login attempt counters must not leak between tests
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": str(tmp_path)}}
    (tmp_path / "inbox").mkdir()
    return tmp_path


@pytest.fixture
def api(sb):
    c = APIClient()
    c.force_login(get_user_model().objects.create_user("dany", password="x"))
    return c


def test_everything_requires_login(sb):
    c = APIClient()
    assert c.get("/api/items").status_code == 403
    assert c.post("/api/scan").status_code == 403
    assert c.get("/api/auth/me").json()["authenticated"] is False


def test_login_and_logout(sb):
    get_user_model().objects.create_user("dany", password="secret-123")
    c = APIClient()
    assert c.post("/api/auth/login", {"username": "dany", "password": "wrong"}, format="json").status_code == 401
    assert c.post("/api/auth/login", {"username": "dany", "password": "secret-123"}, format="json").status_code == 200
    assert c.get("/api/items").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/items").status_code == 403


def test_login_attempts_are_rate_limited_even_with_a_forged_forwarded_for(sb):
    get_user_model().objects.create_user("dany", password="secret-123")
    c = APIClient()
    codes = [c.post("/api/auth/login", {"username": "dany", "password": f"wrong-{i}"}, format="json",
                    HTTP_X_FORWARDED_FOR=f"10.9.8.{i}").status_code for i in range(12)]   # a new "IP" every time
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    # while locked out, even the right password is refused: that is the point
    assert c.post("/api/auth/login", {"username": "dany", "password": "secret-123"}, format="json").status_code == 429


def test_unknown_api_routes_are_json_404_but_ui_routes_still_get_the_app(sb, settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    settings.FRONTEND_DIST = dist
    c = APIClient()
    for method in (c.get, c.post):
        r = method("/api/does-not-exist")
        assert r.status_code == 404 and r["Content-Type"] == "application/json"       # not index.html with a 200
        assert r.json()["detail"] == "not found"
    assert c.get("/api/items/999999/pdf").status_code in (403, 404)                    # real routes are untouched
    r = c.get("/queue")                                                                 # a UI route: the single-page app
    assert r.status_code == 200 and b"app" in b"".join(r.streaming_content)


def test_a_missing_asset_is_a_404_not_the_app_with_a_200(sb, settings, tmp_path):
    """After a redeploy an open tab asks for the old hashed bundle: HTML answered 200 shows up as a MIME error or a blank page."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "index-new.js").write_text("console.log(1)")
    settings.FRONTEND_DIST = dist
    c = APIClient()
    for gone in ("/assets/index-old.js", "/assets/index-old.css", "/favicon.ico", "/logo.svg", "/robots.txt", "/a/b/c.woff2"):
        r = c.get(gone)
        assert r.status_code == 404 and b"app" not in r.content, gone                 # not index.html
    assert c.get("/assets/index-new.js").status_code == 200                           # a real file is still served
    for route in ("/", "/queue", "/history", "/queue/some-id", "/v1.2/release"):      # pages (even with a dot mid-path) keep the app
        r = c.get(route)
        assert r.status_code == 200 and b"app" in b"".join(r.streaming_content), route


def test_hashed_assets_are_cached_for_good_and_the_page_that_names_them_is_always_revalidated(sb, settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    settings.FRONTEND_DIST = dist
    c = APIClient()
    asset = c.get("/assets/index-abc123.js")
    assert asset.status_code == 200 and asset["Cache-Control"] == "public, max-age=31536000, immutable"   # the name IS the version
    for page in ("/", "/history"):
        r = c.get(page)
        assert r.status_code == 200 and r["Cache-Control"] == "no-cache"        # a new deploy is seen at once (the page is tiny)
    assert "immutable" not in c.get("/favicon.svg").get("Cache-Control", "")          # only the hashed bundles are forever


def test_csrf_is_enforced_for_browser_sessions(sb):
    c = APIClient(enforce_csrf_checks=True)
    c.force_login(get_user_model().objects.create_user("dany", password="x"))
    assert c.post("/api/scan").status_code == 403


def test_login_requires_a_csrf_token_even_for_an_anonymous_request(sb):
    get_user_model().objects.create_user("dany", password="secret-123")
    creds = {"username": "dany", "password": "secret-123"}
    c = APIClient(enforce_csrf_checks=True)
    assert c.post("/api/auth/login", creds, format="json").status_code == 403         # forged cross-site login
    assert c.get("/api/items").status_code == 403                                      # and no session was opened
    token = c.get("/api/auth/me").cookies["csrftoken"].value                            # what the page does on load
    assert c.post("/api/auth/login", creds, format="json", HTTP_X_CSRFTOKEN="wrong").status_code == 403
    assert c.post("/api/auth/login", creds, format="json", HTTP_X_CSRFTOKEN=token).status_code == 200
    assert c.get("/api/items").status_code == 200


def test_items_list_is_paged_and_says_how_many_there_are(api):
    for n in range(5):
        Item.objects.create(source_path=f"/{n}.pdf", sha256=f"h{n}", engine_status="auto", confidence=0.9 - n / 100)
    everything = api.get("/api/items")
    assert len(everything.json()) == 5 and everything["X-Total-Count"] == "5"
    page1, page2 = api.get("/api/items?limit=2"), api.get("/api/items?limit=2&offset=2")
    assert [i["filename"] for i in page1.json()] == ["0.pdf", "1.pdf"] and page1["X-Total-Count"] == "5"
    assert [i["filename"] for i in page2.json()] == ["2.pdf", "3.pdf"]                     # stable order, no overlap
    assert [i["filename"] for i in api.get("/api/items?limit=2&offset=4").json()] == ["4.pdf"]
    for bad in ("limit=0", "limit=x", "offset=-1", "limit=-3"):
        assert api.get(f"/api/items?{bad}").status_code == 400
    assert len(api.get("/api/items?limit=99999").json()) == 5                              # capped, not an error


def test_secret_key_creation_never_overwrites_a_key_published_by_another_process(tmp_path, monkeypatch):
    from webapp import settings as webapp_settings
    target = tmp_path / "storage" / ".django_secret"
    real = webapp_settings.secrets.token_urlsafe

    def other_process_wins_the_race(n):
        target.write_text("KEY-OF-THE-OTHER-PROCESS")         # published while this process was still generating its own
        return real(n)

    monkeypatch.setattr(webapp_settings.secrets, "token_urlsafe", other_process_wins_the_race)
    assert webapp_settings.load_or_create_secret(target) == "KEY-OF-THE-OTHER-PROCESS"
    assert target.read_text() == "KEY-OF-THE-OTHER-PROCESS"


def test_secret_key_file_is_never_readable_by_others_not_even_for_an_instant(tmp_path, monkeypatch):
    import os
    import stat

    from webapp import settings as webapp_settings
    target = tmp_path / "storage" / ".django_secret"
    seen = []
    real = webapp_settings.secrets.token_urlsafe

    def look_while_the_key_is_being_made(n):
        seen.extend(stat.S_IMODE(p.stat().st_mode) for p in target.parent.iterdir())   # the file that exists RIGHT NOW
        return real(n)

    monkeypatch.setattr(webapp_settings.secrets, "token_urlsafe", look_while_the_key_is_being_made)
    old_umask = os.umask(0)                                       # the worst case: a umask that adds no restriction at all
    try:
        webapp_settings.load_or_create_secret(target)
    finally:
        os.umask(old_umask)
    assert seen == [0o600]                                        # private from its creation (a write-then-chmod would be 0o666 here)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_the_site_database_waits_for_a_locked_file_and_uses_the_write_ahead_log(tmp_path):
    from django.conf import settings
    from django.db import ConnectionHandler
    options = settings.DATABASES["default"].get("OPTIONS", {})          # exactly what the deployed site is configured with
    conn = ConnectionHandler({"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(tmp_path / "site.db"),
                                          "OPTIONS": options}})["default"]
    with conn.cursor() as cur:
        assert cur.execute("PRAGMA busy_timeout").fetchone()[0] == 20000     # was 5 s: "database is locked" during a long write
        assert cur.execute("PRAGMA journal_mode").fetchone()[0] == "wal"     # readers are not blocked by a writer
    conn.close()


def test_the_engine_database_has_the_same_waiting_time_and_log_mode(tmp_path):
    from docflow.db import DB
    db = DB(tmp_path / "engine.db")
    assert db.c.execute("PRAGMA busy_timeout").fetchone()[0] == 20000
    assert db.c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize("kind", ["RuntimeError", "FzErrorFormat", "KeyError"])
def test_a_scan_that_fails_is_written_to_the_log_with_its_traceback_not_only_stored(api, sb, monkeypatch, caplog, kind):
    """The catch in the job runner is deliberately broad (BLE001): MuPDF's FzErrorFormat is not even a RuntimeError, and a
    job that dies unrecorded would sit as 'running' until the watchdog retires it. Whatever the class, the job ends in
    'error' with the cause in the site AND the traceback in the log."""
    import logging

    from pymupdf import mupdf
    from triage import services
    error = {"RuntimeError": RuntimeError, "FzErrorFormat": mupdf.FzErrorFormat, "KeyError": KeyError}[kind]("disk exploded")
    monkeypatch.setattr(services, "scan", lambda job=None: (_ for _ in ()).throw(error))
    with caplog.at_level(logging.ERROR):
        res = api.post("/api/scan").json()
    assert res["job"]["state"] == "error" and f"{kind}: " in res["job"]["error"] and "disk exploded" in res["job"]["error"]
    record = next(r for r in caplog.records if "scan job" in r.getMessage())
    assert record.exc_info and "disk exploded" in str(record.exc_info[1])                          # ...and in the log
    assert ScanJob.objects.filter(state=ScanJob.State.RUNNING).count() == 0                        # nothing left "running"


@pytest.mark.parametrize("attempt", range(5))
def test_many_connections_opened_at_once_on_a_new_database_all_succeed(tmp_path, attempt):
    import threading

    from docflow.db import DB
    path = tmp_path / f"new{attempt}.db"
    start, errors, modes = threading.Barrier(8), [], []

    def open_one():                                # the scan's workers each open their own connection, at the same moment
        start.wait()
        try:
            modes.append(DB(path).c.execute("PRAGMA journal_mode").fetchone()[0])
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=open_one) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == [] and modes == ["wal"] * 8


def test_a_second_writer_gets_through_a_write_lock_that_lasts_longer_than_the_old_default(tmp_path):
    import sqlite3
    import threading
    import time

    from docflow.db import DB
    path = tmp_path / "shared.db"
    DB(path).c.close()                                                      # creates the file and its tables
    held, release = threading.Event(), threading.Event()

    def writer_holding_the_lock():                                         # e.g. the background scan saving its results
        hold = sqlite3.connect(path, isolation_level=None)
        hold.execute("BEGIN IMMEDIATE")
        held.set()
        release.wait()
        hold.execute("COMMIT")
        hold.close()

    threading.Thread(target=writer_holding_the_lock).start()
    held.wait()
    threading.Timer(6.0, release.set).start()                             # the lock is released after 6 s: longer than 5 s
    start = time.time()
    db = DB(path)
    doc = db.add_document(sha256="s1", status="classified")                 # waits for the lock instead of "database is locked"
    assert doc and 5.5 < time.time() - start < 15


@pytest.mark.parametrize("raw,expected", [
    ("a,b", ["a", "b"]), ("a, b", ["a", "b"]), (" a ,\tb\n,, c ,", ["a", "b", "c"]),
    ("my-server, 192.0.2.10 ,localhost", ["my-server", "192.0.2.10", "localhost"]),
    ("a,a, a", ["a"]),                                              # a repeated host is listed once
])
def test_the_allowed_hosts_list_ignores_spaces_and_empty_entries(raw, expected):
    from webapp import settings as webapp_settings
    assert webapp_settings.parse_hosts(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", ",", " , ,\n"])
def test_a_hosts_setting_that_lists_no_host_is_refused_not_silently_accepted(raw):
    from django.core.exceptions import ImproperlyConfigured
    from webapp import settings as webapp_settings
    with pytest.raises(ImproperlyConfigured, match="DOCFLOW_HOSTS"):                  # instead of a site that answers 400 to all
        webapp_settings.parse_hosts(raw)


def test_the_hosts_actually_in_use_are_clean():
    from webapp import settings as webapp_settings
    assert webapp_settings.HOSTS and all(h == h.strip() and h for h in webapp_settings.HOSTS)
    assert all(o == o.strip() and " " not in o for o in webapp_settings.CSRF_TRUSTED_ORIGINS)


@pytest.mark.parametrize("content", ["", "   ", "\n", " \n\t "])
def test_an_empty_secret_key_file_is_refused_with_a_clear_message_never_used(tmp_path, content):
    from webapp import settings as webapp_settings
    target = tmp_path / "storage" / ".django_secret"
    target.parent.mkdir()
    target.write_text(content)                                    # e.g. left by an old start that was interrupted
    with pytest.raises(RuntimeError, match="empty.*delete"):
        webapp_settings.load_or_create_secret(target)
    assert target.read_text() == content                          # and nothing was overwritten behind anybody's back


def test_eight_workers_starting_together_all_end_up_with_the_same_key(tmp_path):
    import threading

    from webapp import settings as webapp_settings
    target = tmp_path / "storage" / ".django_secret"
    start, keys = threading.Barrier(8), []

    def worker():
        start.wait()                                               # all eight check "does the file exist?" at the same moment
        keys.append(webapp_settings.load_or_create_secret(target))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(keys) == 8 and len(set(keys)) == 1 and len(keys[0]) >= 64
    assert [p.name for p in target.parent.iterdir()] == [".django_secret"]


def test_secret_key_file_is_private_complete_and_leaves_nothing_behind(tmp_path):
    from webapp import settings as webapp_settings
    target = tmp_path / "storage" / ".django_secret"
    key = webapp_settings.load_or_create_secret(target)
    assert len(key) >= 64 and target.read_text() == key
    assert target.stat().st_mode & 0o777 == 0o600
    assert webapp_settings.load_or_create_secret(target) == key               # stable on the next start
    assert [p.name for p in target.parent.iterdir()] == [".django_secret"]    # no temporary file left


def test_a_scan_job_can_only_be_running_done_or_error_at_every_level():
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from triage.models import ScanJob
    assert (ScanJob.State.RUNNING, ScanJob.State.DONE, ScanJob.State.ERROR) == ("running", "done", "error")
    assert ScanJob().state == ScanJob.State.RUNNING                          # a new job starts running, as before
    with pytest.raises(ValidationError) as invalid:
        ScanJob(state="runing").full_clean()
    assert "state" in invalid.value.message_dict
    ScanJob(state="done").full_clean()                                       # a real state raises nothing
    with pytest.raises(IntegrityError), transaction.atomic():
        ScanJob.objects.create(state="runing")                               # a typo would be a scan that never shows as over
    job = ScanJob.objects.create(state="done")
    with pytest.raises(IntegrityError), transaction.atomic():
        ScanJob.objects.filter(pk=job.pk).update(state="runing")
    assert ScanJob.objects.get(pk=job.pk).state == "done"


def test_an_item_can_only_have_one_of_the_four_known_states_at_every_level():
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    for n, ok in enumerate(["pending", "approved", "ignored", "removed"]):
        Item.objects.create(source_path=f"/{n}.pdf", sha256=f"h{n}", engine_status="auto", state=ok)       # the four are fine
    assert (Item.PENDING, Item.APPROVED, Item.IGNORED, Item.REMOVED) == ("pending", "approved", "ignored", "removed")
    with pytest.raises(ValidationError) as invalid:                         # forms and the admin: a closed list
        Item(source_path="/x.pdf", sha256="x", engine_status="auto", state="aproved").full_clean()
    assert "state" in invalid.value.message_dict                            # about the state, not about some other field
    with pytest.raises(ValidationError) as fine:
        Item(source_path="/x.pdf", sha256="x", engine_status="auto", state="approved").full_clean()
    assert "state" not in fine.value.message_dict                           # while a real state raises nothing about it
    with pytest.raises(IntegrityError), transaction.atomic():               # a typo in a view or a script: the database refuses
        Item.objects.create(source_path="/y.pdf", sha256="y", engine_status="auto", state="aproved")
    good = Item.objects.get(source_path="/0.pdf")
    with pytest.raises(IntegrityError), transaction.atomic():               # even a bulk .update() that skips every Python check
        Item.objects.filter(pk=good.pk).update(state="aproved")
    assert Item.objects.get(pk=good.pk).state == "pending"                  # and the row is untouched


def test_notes_migration_writes_in_batches_not_one_row_at_a_time():
    import importlib
    from types import SimpleNamespace

    from django.apps import apps as real_apps
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    migration = importlib.import_module("triage.migrations.0003_english_notes")
    Item.objects.bulk_create([Item(source_path=f"/{n}.pdf", sha256=f"h{n}", engine_status="manual",
                                   notes=["Aucune règle de destination.", "Lecture impossible: OSError"] if n % 2 == 0
                                   else ["already english"]) for n in range(1200)], batch_size=300)
    with CaptureQueriesContext(connection) as queries:
        migration.to_english(real_apps, SimpleNamespace(connection=connection))
    writes = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith("UPDATE")]
    assert len(writes) <= 6                                       # 600 rows to change: a handful of batches (was 600 UPDATEs)
    translated = Item.objects.filter(notes__0="No destination rule.").count()
    assert translated == 600 and Item.objects.filter(notes__1="Cannot read file: OSError").count() == 600
    assert Item.objects.filter(notes=["already english"]).count() == 600     # rows that needed nothing were left alone


def test_notes_migration_reads_and_writes_the_database_it_is_migrating():
    import importlib
    from types import SimpleNamespace
    migration = importlib.import_module("triage.migrations.0003_english_notes")
    used = []

    class FakeItem:
        def __init__(self, notes):
            self.notes = notes

    items = [FakeItem(["Lecture impossible: X", "already english"]), FakeItem(["Aucune règle de destination."])]

    class OnDatabase:                                       # what Item.objects.using(alias) returns
        def __init__(self, alias):
            self.alias = alias

        def only(self, *fields):
            return self

        def iterator(self, chunk_size=None):
            used.append(("read", self.alias, ()))
            return iter(items)

        def bulk_update(self, objs, fields, batch_size=None):
            used.append(("write", self.alias, tuple(fields)))
            assert len(objs) == 2                            # both rows were translated and handed over together

    class Manager:
        def all(self):
            used.append(("all", "default", ()))             # what the old code did: always the default database
            return items

        def using(self, alias):
            return OnDatabase(alias)

    apps = SimpleNamespace(get_model=lambda app, model: SimpleNamespace(objects=Manager()))
    migration.to_english(apps, SimpleNamespace(connection=SimpleNamespace(alias="other")))
    assert ("all", "default", ()) not in used                # never the default database
    assert used == [("read", "other", ()), ("write", "other", ("notes",))]       # read and written on the migrated one


def test_scan_creates_items_and_moves_nothing(api, sb):
    h = pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    pdf(sb / "inbox" / "unknown.pdf", ["Lettre de la tante Huguette", "Le 3 mai 2025"])
    first =api.post("/api/scan").json()
    assert (first["created"], first["skipped"]) == (2, 0)
    second = api.post("/api/scan").json()
    assert (second["created"], second["skipped"]) == (0, 2)  # idempotent
    rows = {r["filename"]: r for r in api.get("/api/items").json()}
    assert rows["hydro.pdf"]["status"] == "auto" and rows["hydro.pdf"]["amount"] == "158.98"
    assert rows["hydro.pdf"]["final_name"].startswith("2025-10-07 - Hydro-Quebec - FactureElectricite")
    assert rows["unknown.pdf"]["status"] == "manual" and rows["unknown.pdf"]["final_name"] == ""
    assert h.exists() and not (sb / "library").exists()


@pytest.fixture
def hash_calls(monkeypatch):
    """Counts every full read of a file for its SHA-256, wherever it happens (scan or propose)."""
    from docflow import pipeline
    from triage import services
    calls = []
    for module in (pipeline, services):
        real = module.sha256_file
        monkeypatch.setattr(module, "sha256_file", lambda p, real=real: (calls.append(str(p)), real(p))[1])
    return calls


def test_a_scan_hashes_each_new_file_once_and_an_unchanged_queued_file_never(api, sb, hash_calls):
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    pdf(sb / "inbox" / "garage.pdf", GARAGE)
    assert api.post("/api/scan").json()["created"] == 2
    assert len(hash_calls) == 2                                   # one read per new file, not two (scan + propose)
    hash_calls.clear()
    second = api.post("/api/scan").json()
    assert (second["created"], second["skipped"]) == (0, 2) and hash_calls == []   # already queued, unchanged: no read


def test_a_changed_file_is_read_again_and_replaces_its_stale_item(api, sb, hash_calls):
    f = pdf(sb / "inbox" / "doc.pdf", HYDRO)
    api.post("/api/scan")
    hash_calls.clear()
    pdf(sb / "inbox" / "doc.pdf", GARAGE)                          # same path, other content (size and mtime change)
    again = api.post("/api/scan").json()
    assert again["created"] == 1 and len(hash_calls) == 1
    states = sorted(Item.objects.filter(source_path=str(f)).values_list("state", flat=True))
    assert states == ["pending", "removed"]


def test_items_queued_before_the_stamp_existed_are_stamped_by_one_read_then_left_alone(api, sb, hash_calls):
    f = pdf(sb / "inbox" / "old.pdf", HYDRO)
    api.post("/api/scan")
    Item.objects.update(source_size=None, source_mtime_ns=None)   # as if created by an earlier version
    hash_calls.clear()
    assert api.post("/api/scan").json()["skipped"] == 1 and len(hash_calls) == 1
    assert Item.objects.get().source_size == f.stat().st_size
    hash_calls.clear()
    assert api.post("/api/scan").json()["skipped"] == 1 and hash_calls == []


@pytest.mark.parametrize("what", ["vanishes", "is_a_folder", "unreadable"])
def test_a_pdf_that_cannot_be_opened_after_the_path_was_checked_is_a_404_not_a_500(api, sb, monkeypatch, what):
    from triage import services
    f = pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    item = Item.objects.get()
    assert api.get(f"/api/items/{item.id}/pdf").status_code == 200           # the normal case
    if what == "vanishes":
        target = sb / "inbox" / "gone.pdf"                                   # checked path no longer exists when opened
    elif what == "is_a_folder":
        target = sb / "inbox"
    else:
        target = sb / "locked.pdf"
        target.write_bytes(b"%PDF-1.4")
        target.chmod(0)
    monkeypatch.setattr(services, "pdf_path", lambda it: target)
    try:
        r = api.get(f"/api/items/{item.id}/pdf")
    finally:
        target.chmod(0o644) if target.is_file() else None
    assert r.status_code == 404 and r.json() == {"detail": "file unavailable"}
    assert f.exists()


@pytest.mark.parametrize("name,expected", [
    ("a.pdf", 'inline; filename="a.pdf"'),
    ("Facture Hydro-Québec 2025.pdf", "filename*=utf-8''Facture%20Hydro-Qu%C3%A9bec%202025.pdf"),   # non-ASCII: RFC 6266 form
    ('weird"name.pdf', 'filename="weird\\"name.pdf"'),                                                 # the quote is escaped, the header holds
])
def test_the_pdf_is_served_with_its_own_file_name_so_saving_it_does_not_give_a_generic_name(api, sb, name, expected):
    pdf(sb / "inbox" / name, HYDRO)
    api.post("/api/scan")
    item = Item.objects.get()
    r = api.get(f"/api/items/{item.id}/pdf")
    disposition = r["Content-Disposition"]
    assert r.status_code == 200 and disposition.startswith("inline;") and expected in disposition
    assert "attachment" not in disposition                                    # still shown in the preview, not downloaded


def test_serving_the_pdf_preview_does_not_leak_file_descriptors(api, sb):
    """The view hands an open file to FileResponse on purpose (a `with` block would close it before the body is streamed):
    the response closes it itself. 300 previews, fully read, must not leave 300 descriptors open."""
    import os
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    item = Item.objects.get()
    api.get(f"/api/items/{item.id}/pdf")                                              # warm-up (first-use allocations)
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(300):
        r = api.get(f"/api/items/{item.id}/pdf")
        assert r.status_code == 200 and b"".join(r.streaming_content).startswith(b"%PDF")
        r.close()
    assert len(os.listdir("/proc/self/fd")) <= before + 3                             # not +300


def test_a_pdf_that_cannot_be_opened_leaves_the_reason_in_the_log(api, sb, monkeypatch, caplog):
    """The user is told 'file unavailable'; the operator needs to know WHY (permissions, storage, a vanished file)."""
    import logging

    from triage import services
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    item = Item.objects.get()
    locked = sb / "locked.pdf"
    locked.write_bytes(b"%PDF-1.4")
    locked.chmod(0)
    monkeypatch.setattr(services, "pdf_path", lambda it: locked)
    try:
        with caplog.at_level(logging.WARNING):
            assert api.get(f"/api/items/{item.id}/pdf").status_code == 404
    finally:
        locked.chmod(0o644)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("pdf of item")]
    assert len(lines) == 1 and f"pdf of item {item.id} unavailable" in lines[0]
    assert "locked.pdf" in lines[0] and "Permission denied" in lines[0]


def _three_hydro_invoices_and_a_letter(sb):
    for name, lines in (("a.pdf", HYDRO), ("b.pdf", HYDRO[:2] + ["Numero de facture : 777000111", HYDRO[3]]),
                        ("c.pdf", HYDRO[:2] + ["Numero de facture : 555222333", HYDRO[3]]),
                        ("letter.pdf", ["Lettre de la tante Huguette", "Le 3 mai 2025", "Chere famille."])):
        pdf(sb / "inbox" / name, lines)


def test_ticked_items_are_approved_together_and_only_those(api, sb):
    _three_hydro_invoices_and_a_letter(sb)
    api.post("/api/scan")
    by_name = {Path(i.source_path).name: i for i in Item.objects.all()}
    ids = [by_name["a.pdf"].id, by_name["c.pdf"].id]
    r = api.post("/api/items/approve-selected", {"ids": ids}, format="json")
    assert r.status_code == 200 and r.json() == {"approved": ids, "failed": []}                 # in the order given
    assert {Path(i.source_path).name: i.state for i in Item.objects.all()} == {
        "a.pdf": "approved", "b.pdf": "pending", "c.pdf": "approved", "letter.pdf": "pending"}
    assert len(list((sb / "library").rglob("*.pdf"))) == 2                                       # two files really filed, the others untouched


def test_a_ticked_item_that_cannot_be_filed_is_reported_and_the_others_still_are(api, sb):
    _three_hydro_invoices_and_a_letter(sb)
    api.post("/api/scan")
    by_name = {Path(i.source_path).name: i for i in Item.objects.all()}
    letter = by_name["letter.pdf"]                                                               # no company, no name: nothing to file
    ok = by_name["a.pdf"]
    already = by_name["b.pdf"]
    api.post(f"/api/items/{already.id}/approve")                                                 # approved in another tab meanwhile
    r = api.post("/api/items/approve-selected", {"ids": [letter.id, ok.id, already.id, 99999]}, format="json").json()
    assert r["approved"] == [ok.id]
    failed = {f["id"]: f["detail"] for f in r["failed"]}
    assert set(failed) == {letter.id, already.id, 99999}                                         # every id is accounted for
    assert "no longer pending" in failed[already.id] and "no longer pending" in failed[99999]
    assert Item.objects.get(pk=letter.id).state == "pending" and Item.objects.get(pk=ok.id).state == "approved"


@pytest.mark.parametrize("body", [{}, {"ids": []}, {"ids": "1,2"}, {"ids": [1, "2"]}, {"ids": [True]}, {"ids": [1, 1]},
                                  {"ids": list(range(1, 202))}, {"ids": None}, [1, 2], "text"])
def test_the_batch_approval_refuses_a_malformed_or_oversized_list(api, sb, body):
    r = api.post("/api/items/approve-selected", body, format="json")
    assert r.status_code == 400 and "ids" in r.json()["detail"]                                  # a clear 400, never a 500, nothing filed
    assert not list((sb / "library").rglob("*.pdf"))


def test_the_batch_approval_needs_a_logged_in_user(sb):
    assert APIClient().post("/api/items/approve-selected", {"ids": [1]}, format="json").status_code in (401, 403)


def test_one_unexpected_error_does_not_stop_the_bulk_approval_nor_hide_what_was_already_filed(api, sb, monkeypatch, caplog):
    import logging

    from triage import services
    for name, lines in (("a.pdf", HYDRO), ("b.pdf", HYDRO[:2] + ["Numero de facture : 777000111", HYDRO[3]]),
                        ("c.pdf", HYDRO[:2] + ["Numero de facture : 555222333", HYDRO[3]])):
        pdf(sb / "inbox" / name, lines)
    api.post("/api/scan")
    assert Item.objects.filter(engine_status="auto").count() == 3
    real = services.approve
    ids = list(Item.objects.order_by("id").values_list("id", flat=True))

    def flaky(it):
        if it.id == ids[1]:
            raise RuntimeError("database is locked")           # NOT an ApiError: e.g. a SQLite error from the engine
        return real(it)

    monkeypatch.setattr(services, "approve", flaky)
    with caplog.at_level(logging.ERROR):
        r = api.post("/api/items/approve-auto")
    assert r.status_code == 200                                   # an answer, not a 500 after a partial run
    body = r.json()
    assert sorted(body["approved"]) == [ids[0], ids[2]]           # the item after the broken one was still processed
    assert [f["id"] for f in body["failed"]] == [ids[1]] and "RuntimeError" in body["failed"][0]["detail"]
    assert "database is locked" not in body["failed"][0]["detail"]    # internals stay in the log, not in the interface
    assert any("database is locked" in r.getMessage() or "database is locked" in str(r.exc_info) for r in caplog.records)


def test_every_dashboard_tile_count_is_exactly_the_size_of_its_filtered_list(api):
    for n, status in enumerate(["auto", "auto", "confirm", "manual", "duplicate", "logical_duplicate", "error", "error", "error"]):
        Item.objects.create(source_path=f"/{n}.pdf", sha256=f"h{n}", engine_status=status)
    Item.objects.create(source_path="/done.pdf", sha256="hd", engine_status="auto", state=Item.APPROVED)   # not pending
    d = api.get("/api/dashboard").json()
    tiles = {"auto": d["auto_ready"], "needs_validation": d["needs_validation"], "duplicates": d["duplicates"], "errors": d["errors"]}
    assert tiles == {"auto": 2, "needs_validation": 2, "duplicates": 2, "errors": 3}
    for group, count in tiles.items():
        r = api.get(f"/api/items?group={group}")
        assert len(r.json()) == count and r["X-Total-Count"] == str(count), group    # the tile and the list cannot disagree
    assert {i["status"] for i in api.get("/api/items?group=duplicates").json()} == {"duplicate", "logical_duplicate"}
    assert {i["status"] for i in api.get("/api/items?group=needs_validation").json()} == {"confirm", "manual"}
    assert len(api.get("/api/items").json()) == 9                                  # no group: the whole queue, as before
    assert api.get("/api/items?group=nonsense").status_code == 400
    page = api.get("/api/items?group=errors&limit=2")
    assert len(page.json()) == 2 and page["X-Total-Count"] == "3"                  # the total is the filtered one, with paging


def test_dashboard_categories_are_disjoint_and_add_up_to_the_pending_count(api):
    for n, status in enumerate(["auto", "auto", "confirm", "manual", "duplicate", "logical_duplicate", "error", "error"]):
        Item.objects.create(source_path=f"/{n}.pdf", sha256=f"h{n}", engine_status=status)
    Item.objects.create(source_path="/done.pdf", sha256="hd", engine_status="auto", state=Item.APPROVED)   # not pending
    d = api.get("/api/dashboard").json()
    assert (d["pending"], d["auto_ready"], d["needs_validation"], d["duplicates"], d["errors"]) == (8, 2, 2, 2, 2)
    assert d["auto_ready"] + d["needs_validation"] + d["duplicates"] + d["errors"] == d["pending"]   # nothing counted twice


def test_dashboard_file_count_follows_the_rules_of_the_scan(api, sb):
    from triage import services
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    pdf(sb / "inbox" / "SCANNER.PDF", GARAGE)                         # upper-case extension: scanned, so counted
    (sb / "inbox" / "@eaDir").mkdir()
    pdf(sb / "inbox" / "@eaDir" / "thumb.pdf", HYDRO)                 # NAS metadata folder: ignored by the scan
    (sb / "inbox" / ".hidden").mkdir()
    pdf(sb / "inbox" / ".hidden" / "h.pdf", HYDRO)                    # hidden folder: ignored by the scan
    (sb / "inbox" / "sub").mkdir()
    pdf(sb / "inbox" / "sub" / "b.pdf", GARAGE)
    shown = api.get("/api/dashboard").json()["sources"][0]["files"]
    assert shown == len(services.source_files()) == 3


def test_scan_reads_extra_sources_and_subfolders(api, sb, settings):
    backlog = sb / "backlog"
    (backlog / "documents2022").mkdir(parents=True)
    (backlog / "@Recycle").mkdir()
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    pdf(backlog / "documents2022" / "b.pdf", ["Lettre B", "Le 3 mai 2025"])
    pdf(backlog / "@Recycle" / "trash.pdf", ["Corbeille"])         # system folders ignored
    (backlog / "archive.zip").write_bytes(b"PK")                      # other types ignored
    settings.DOCFLOW.settings["extra_inboxes"] = [str(backlog)]
    res = api.post("/api/scan").json()
    assert res["created"] == 2 and res["job"]["state"] == "done" and res["job"]["total"] == 2
    assert sorted(r["filename"] for r in api.get("/api/items").json()) == ["a.pdf", "b.pdf"]
    d = api.get("/api/dashboard").json()
    assert [s["files"] for s in d["sources"]] == [1, 1]                # the count follows the scan: @Recycle is left out


def test_pdf_preview_works_for_an_extra_source_outside_the_library(api, sb, settings):
    elsewhere = sb / "elsewhere"            # an extra inbox that is NOT under library_root
    elsewhere.mkdir()
    pdf(elsewhere / "b.pdf", HYDRO)
    settings.DOCFLOW.settings["extra_inboxes"] = [str(elsewhere)]
    api.post("/api/scan")
    item = api.get("/api/items").json()[0]
    assert api.get(f"/api/items/{item['id']}/pdf").status_code == 200


def test_unmounted_source_does_not_wipe_its_pending_items(api, sb, settings):
    backlog = sb / "backlog"
    backlog.mkdir()
    pdf(backlog / "b.pdf", HYDRO)
    settings.DOCFLOW.settings["extra_inboxes"] = [str(backlog)]
    api.post("/api/scan")
    item_id = api.get("/api/items").json()[0]["id"]
    api.patch(f"/api/items/{item_id}", {"detail": "ByHand"}, format="json")      # a manual correction
    settings.DOCFLOW.settings["extra_inboxes"] = [str(sb / "not-mounted")]       # the source disappears (NAS down)
    api.post("/api/scan")
    kept = api.get("/api/items").json()
    assert [i["id"] for i in kept] == [item_id] and kept[0]["detail"] == "ByHand"  # nothing lost
    settings.DOCFLOW.settings["extra_inboxes"] = [str(backlog)]
    (backlog / "b.pdf").unlink()                                                  # file really deleted, source present
    api.post("/api/scan")
    assert api.get("/api/items").json() == []


def test_rewritten_file_replaces_its_stale_pending_item(api, sb):
    f = pdf(sb / "inbox" / "doc.pdf", ["Lettre A", "Le 3 mai 2025"])
    api.post("/api/scan")
    old_id = api.get("/api/items").json()[0]["id"]
    pdf(f, HYDRO)                                    # same path, new content (a rescan dropped over it)
    api.post("/api/scan")
    items = api.get("/api/items").json()
    assert len(items) == 1 and items[0]["id"] != old_id and items[0]["company"] == "Hydro-Quebec"
    assert api.post(f"/api/items/{old_id}/approve").status_code == 400   # the stale one is no longer pending
    assert f.exists()                                                    # and nothing was moved


def test_approving_after_the_file_was_replaced_without_a_rescan_moves_nothing(api, sb):
    f = pdf(sb / "inbox" / "doc.pdf", HYDRO)
    api.post("/api/scan")
    item_id = api.get("/api/items").json()[0]["id"]
    pdf(f, ["Something else entirely", "Le 3 mai 2025"])               # replaced AFTER the scan, no rescan
    new_content = f.read_bytes()
    r = api.post(f"/api/items/{item_id}/approve")
    assert r.status_code == 400 and "checksum mismatch" in r.json()["detail"]
    assert f.exists() and f.read_bytes() == new_content                 # the new file was not filed under a stale analysis
    assert not list((sb / "library").rglob("*.pdf"))
    assert Item.objects.get(pk=item_id).state == Item.PENDING            # and the item is still open


def test_a_learning_failure_after_the_move_still_records_the_approval(api, sb, monkeypatch):
    from triage import services
    f = pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    item_id = api.get("/api/items").json()[0]["id"]
    monkeypatch.setattr(services, "_learn", lambda it: (_ for _ in ()).throw(OSError("disk full")))
    r = api.post(f"/api/items/{item_id}/approve")
    assert r.status_code == 200 and r.json()["learned"] == []
    assert r.json()["learning_failed"] is True                           # reported as a recoverable warning, not hidden
    assert not f.exists()                                                # the file was filed...
    assert Item.objects.get(pk=item_id).state == Item.APPROVED           # ...and the record says so


def test_one_unreadable_file_does_not_abort_the_scan(api, sb, monkeypatch):
    from docflow import pipeline
    from triage import services
    real = pipeline.sha256_file

    def locked(path):
        if path.name == "locked.pdf":
            raise PermissionError("locked by another program")
        return real(path)

    monkeypatch.setattr(services, "sha256_file", locked)
    monkeypatch.setattr(pipeline, "sha256_file", locked)
    pdf(sb / "inbox" / "locked.pdf", HYDRO)
    pdf(sb / "inbox" / "fine.pdf", ["Lettre fine", "Le 3 mai 2025"])
    res = api.post("/api/scan").json()
    assert res["job"]["state"] == "done" and res["created"] == 2           # the scan went all the way
    rows = {r["filename"]: r for r in api.get("/api/items").json()}
    assert rows["locked.pdf"]["status"] == "error" and rows["locked.pdf"]["notes"] == ["Cannot read file: PermissionError"]
    assert rows["fine.pdf"]["status"] != "error"
    assert api.post("/api/scan").json()["created"] == 0                    # and a rescan does not pile up duplicates


def test_the_database_itself_allows_only_one_running_scan_and_one_pending_item_per_file(sb):
    from django.db import IntegrityError, transaction
    from triage.models import ScanJob
    ScanJob.objects.create(state="running")
    with pytest.raises(IntegrityError), transaction.atomic():
        ScanJob.objects.create(state="running")                        # a second concurrent scan is impossible
    ScanJob.objects.create(state="done")                                # finished jobs pile up freely
    Item.objects.create(source_path="/x.pdf", sha256="h", engine_status="auto")
    with pytest.raises(IntegrityError), transaction.atomic():
        Item.objects.create(source_path="/x.pdf", sha256="h", engine_status="auto")   # same path + content, both pending
    Item.objects.create(source_path="/x.pdf", sha256="other", engine_status="auto")   # other content is a different item


def test_two_simultaneous_scan_requests_start_one_job_not_two(api, sb, monkeypatch):
    """Simulate the race: request B read 'no running scan' just before request A inserted its job."""
    from django.db.models.query import QuerySet
    from triage.models import ScanJob
    live = ScanJob.objects.create(state="running", total=5, done=1)
    monkeypatch.setattr(QuerySet, "first", lambda self: None)         # B's check-then-create sees an empty table
    res = api.post("/api/scan").json()
    assert ScanJob.objects.filter(state="running").count() == 1       # still exactly one active scan
    assert res["job"]["state"] == "running" and res["job"]["total"] == 5 and ScanJob.objects.get(pk=live.pk)


def test_a_slow_file_does_not_make_a_live_scan_look_dead(api, sb, monkeypatch):
    import time

    from docflow import pipeline
    from triage import services
    real = pipeline.propose
    beats = []
    monkeypatch.setattr(services, "HEARTBEAT_SECONDS", 0.2)
    monkeypatch.setattr(services, "_beat", lambda job: beats.append(time.monotonic()))

    def slow(*a, **k):
        time.sleep(1.2)                                   # one big scanned PDF taking a long time
        return real(*a, **k)

    monkeypatch.setattr(services, "propose", slow)
    pdf(sb / "inbox" / "big.pdf", HYDRO)
    assert api.post("/api/scan").json()["created"] == 1
    assert len(beats) >= 4, beats                          # alive signals while waiting, not only when a result arrives


def test_results_are_consumed_as_they_complete_not_in_file_order(api, sb, monkeypatch):
    import time

    from docflow import pipeline
    from triage import services
    real = pipeline.propose
    monkeypatch.setattr(services, "HEARTBEAT_SECONDS", 0.2)

    def slow_first(path, *a, **k):
        if path.name == "a_slow.pdf":
            time.sleep(1.5)
        return real(path, *a, **k)

    monkeypatch.setattr(services, "propose", slow_first)
    pdf(sb / "inbox" / "a_slow.pdf", ["Lettre lente", "Le 3 mai 2025"])
    pdf(sb / "inbox" / "b_fast.pdf", HYDRO)
    seen = []
    orig = Item.objects.create
    monkeypatch.setattr(Item.objects, "create", lambda **kw: (seen.append(kw["source_path"].split("/")[-1]), orig(**kw))[1])
    api.post("/api/scan")
    assert seen == ["b_fast.pdf", "a_slow.pdf"]            # the fast one is visible without waiting for the slow one


def test_the_copy_is_the_duplicate_even_when_it_finishes_before_the_original(api, sb, monkeypatch):
    import time

    from docflow import pipeline
    from triage import services
    real = pipeline.propose

    def slow_original(path, *a, **k):
        if path.name == "a_original.pdf":
            time.sleep(1.0)                               # the original is analysed last
        return real(path, *a, **k)

    monkeypatch.setattr(services, "propose", slow_original)
    a = pdf(sb / "inbox" / "a_original.pdf", HYDRO)
    (sb / "inbox" / "b_copy.pdf").write_bytes(a.read_bytes())
    api.post("/api/scan")
    rows = {r["filename"]: r["status"] for r in api.get("/api/items").json()}
    assert rows["b_copy.pdf"] == "duplicate" and rows["a_original.pdf"] != "duplicate"


def test_scan_status_and_stale_running_job(api, sb, settings):
    from datetime import timedelta

    from django.utils import timezone
    from triage.models import ScanJob
    assert api.get("/api/scan/status").json()["state"] == "none"
    live = ScanJob.objects.create(state="running", total=10, done=3)
    r = api.post("/api/scan").json()                                  # a live scan: no 2nd scan in parallel
    assert r["job"]["state"] == "running" and ScanJob.objects.count() == 1
    ScanJob.objects.filter(pk=live.pk).update(updated_at=timezone.now() - timedelta(minutes=11))  # dead process
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    assert api.post("/api/scan").json()["created"] == 1               # the dead scan is taken over
    assert api.get("/api/scan/status").json()["state"] == "done"


def test_scan_error_is_reported_not_swallowed(api, sb, monkeypatch):
    from triage import services
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    monkeypatch.setattr(services, "propose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unreadable disk")))
    api.post("/api/scan")
    st = api.get("/api/scan/status").json()
    assert st["state"] == "error" and "unreadable disk" in st["error"]


def test_identical_copy_is_quarantined_never_filed_twice(api, sb):
    a = pdf(sb / "inbox" / "a.pdf", HYDRO)
    (sb / "inbox" / "b_copy.pdf").write_bytes(a.read_bytes())
    api.post("/api/scan")
    rows = {r["filename"]: r for r in api.get("/api/items").json()}
    assert rows["b_copy.pdf"]["status"] == "duplicate"            # flagged from the scan
    res = api.post("/api/items/approve-auto").json()
    assert len(res["approved"]) == 1
    api.post(f"/api/items/{rows['b_copy.pdf']['id']}/approve")
    assert len(list((sb / "library").rglob("*.pdf"))) == 1        # only one copy filed
    assert (sb / "quarantine" / "duplicates" / "b_copy.pdf").exists()


def test_stale_item_is_requarantined_at_approval_time(api, sb):
    """Two items already proposed as "auto" then approved one by one: the 2nd does not create a copy."""
    a = pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    a_id = api.get("/api/items").json()[0]["id"]
    b = sb / "inbox" / "b.pdf"
    b.write_bytes(a.read_bytes())
    Item.objects.create(source_path=str(b), sha256=Item.objects.get(pk=a_id).sha256, engine_status="auto",
                        analysis=Item.objects.get(pk=a_id).analysis, original=None,
                        final_name=Item.objects.get(pk=a_id).final_name, rel_dir=Item.objects.get(pk=a_id).rel_dir)
    ids = [i["id"] for i in api.get("/api/items").json()]
    for i in ids:
        api.post(f"/api/items/{i}/approve")
    assert len(list((sb / "library").rglob("*.pdf"))) == 1


def test_dashboard_counts(api, sb):
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    pdf(sb / "inbox" / "unknown.pdf", ["Lettre", "Le 3 mai 2025"])
    api.post("/api/scan")
    d = api.get("/api/dashboard").json()
    assert (d["pending"], d["auto_ready"], d["needs_validation"], d["classified_today"]) == (2, 1, 1, 0)
    assert d["sources"][0]["files"] == 2 and d["sources"][0]["kind"] == "inbox"
    api.post("/api/items/approve-auto")
    assert api.get("/api/dashboard").json()["classified_today"] == 1


def test_edit_approve_and_learn_then_next_document_is_recognised(api, sb):
    pdf(sb / "inbox" / "g1.pdf", GARAGE)
    api.post("/api/scan")
    it = api.get("/api/items").json()[0]
    assert it["company"] is None
    r = api.patch(f"/api/items/{it['id']}", {"company": "Garage Tremblay", "document_type": "facture entretien",
                                             "amount": "80,00", "date": "2025-03-05", "rel_dir": "Cars/Entretiens"},
                  format="json")
    assert r.status_code == 200, r.content
    e = r.json()
    assert e["final_name"] == "2025-03-05 - GarageTremblay - FactureEntretien - 80.00$.pdf"
    assert e["status"] == "confirm" and e["destination"].endswith("library/Cars/Entretiens")
    res = api.post(f"/api/items/{it['id']}/approve").json()
    assert (sb / "library" / "Cars" / "Entretiens" / e["final_name"]).exists()
    assert {(x["kind"], x["value"]) for x in res["learned"]} == {
        ("company", "GarageTremblay"), ("type", "FactureEntretien"), ("route", "Cars/Entretiens")}
    assert all(x["company"] == "GarageTremblay" for x in res["learned"])
    assert not (sb / "inbox" / "g1.pdf").exists()
    # the second document from the same garage is recognised WITHOUT correction
    pdf(sb / "inbox" / "g2.pdf", ["Garage Tremblay et Fils", "Date: 9 avril 2025", "Pneus", "Total 400,00 $"])
    api.post("/api/scan")
    new = api.get("/api/items").json()[0]
    assert new["company"] == "GarageTremblay" and new["document_type"] == "FactureEntretien"
    assert new["rel_dir"] == "Cars/Entretiens"  # destination learned too


AMAZON = ["Amazon.com.ca ULC", "Invoice date / Date de facturation: 09 January 2026",
          "Order date / Date de commande: 08 January 2026", "Description Quantity Unit price",
          "Friskies Chef's Blend Dry Cat Food 7.5kg 1 $22.99 $0.00 $1.15 $2.29 $26.43", "Total $26.43"]


def test_editing_another_field_does_not_silently_validate_the_guessed_detail(api, sb):
    pdf(sb / "inbox" / "amazon.pdf", AMAZON)
    api.post("/api/scan")
    item = api.get("/api/items").json()[0]
    assert item["conf"]["detail"] == 0.85 and item["confidence"] <= 0.85    # a guessed item title: to be confirmed
    after_amount = api.patch(f"/api/items/{item['id']}", {"amount": "26.43"}, format="json").json()
    assert after_amount["conf"]["detail"] == 0.85 and after_amount["confidence"] <= 0.85   # still unverified
    assert after_amount["conf"]["amount"] == 1.0                                          # the edited field IS validated
    after_detail = api.patch(f"/api/items/{item['id']}", {"detail": "FriskiesCatFood"}, format="json").json()
    assert after_detail["conf"]["detail"] == 1.0 and after_detail["confidence"] >= 0.95    # explicitly confirmed


def test_edit_rejects_bad_input_and_path_tricks(api, sb):
    pdf(sb / "inbox" / "g.pdf", GARAGE)
    api.post("/api/scan")
    i = api.get("/api/items").json()[0]["id"]
    bad = [{"rel_dir": "../../etc"}, {"rel_dir": "/etc"}, {"rel_dir": "C:/Windows"}, {"date": "yesterday"},
           {"date": "2024-02-30"}, {"date": "2024-13-45"}, {"date": "2023-02-29"}, {"date": "2024-01-01\n"},
           {"amount": "a lot"}, {"final_name": "no-extension"},{"currency": "cad$"}]
    for body in bad:
        assert api.patch(f"/api/items/{i}", body, format="json").status_code == 400, body
    r = api.patch(f"/api/items/{i}", {"company": "../../x", "document_type": "A/B", "final_name": "a/../b.pdf"},
                  format="json").json()
    assert "/" not in r["company"] and ".." not in r["company"] and "/" not in r["final_name"]


def test_approve_requires_complete_proposal(api, sb):
    f = pdf(sb / "inbox" / "x.pdf", ["Lettre", "Le 3 mai 2025"])
    api.post("/api/scan")
    i = api.get("/api/items").json()[0]["id"]
    r = api.post(f"/api/items/{i}/approve")
    assert r.status_code == 400 and f.exists()


def test_ignore_survives_rescan_remove_does_not(api, sb):
    pdf(sb / "inbox" / "a.pdf", ["Lettre A", "Le 3 mai 2025"])
    pdf(sb / "inbox" / "b.pdf", ["Lettre B", "Le 4 mai 2025"])
    api.post("/api/scan")
    a, b = sorted(api.get("/api/items").json(), key=lambda r: r["filename"])
    api.post(f"/api/items/{a['id']}/ignore")
    api.post(f"/api/items/{b['id']}/remove")
    assert api.get("/api/items").json() == []
    res = api.post("/api/scan").json()
    assert res["created"] == 1 and res["skipped"] == 1  # a stays ignored, b comes back
    assert (sb / "inbox" / "a.pdf").exists() and (sb / "inbox" / "b.pdf").exists()  # nothing deleted from disk


def test_pdf_preview_and_path_confinement(api, sb):
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    i = api.get("/api/items").json()[0]["id"]
    r = api.get(f"/api/items/{i}/pdf")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and b"".join(r.streaming_content)[:5] == b"%PDF-"
    Item.objects.filter(pk=i).update(source_path="/etc/passwd")  # even a tampered database cannot escape the folders
    assert api.get(f"/api/items/{i}/pdf").status_code == 404


def test_undo_through_api_restores_and_requeues(api, sb):
    h = pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    api.post("/api/items/approve-auto")
    assert not h.exists()
    op = api.get("/api/history").json()[0]
    assert api.post(f"/api/history/{op['id']}/undo").status_code == 200
    assert h.exists()
    assert api.get("/api/items").json()[0]["filename"] == "hydro.pdf"
    assert api.post(f"/api/history/{op['id']}/undo").status_code == 400  # already undone


def test_history_n_parameter_is_validated_and_bounded(api, sb):
    for i in range(3):
        pdf(sb / "inbox" / f"h{i}.pdf", HYDRO[:3] + [f"Montant de la presente facture : {100 + i},00 $"])
    api.post("/api/scan")
    api.post("/api/items/approve-auto")
    assert len(api.get("/api/history").json()) == 3
    assert len(api.get("/api/history?n=2").json()) == 2
    assert len(api.get("/api/history?n=-5").json()) == 1          # clamped, not "everything"
    assert len(api.get("/api/history?n=100000").json()) == 3      # bounded (500), never the whole table by request
    r = api.get("/api/history?n=abc")
    assert r.status_code == 400 and "integer" in r.json()["detail"]


def test_destinations_and_vocabulary(api, sb):
    (sb / "library" / "Cars" / "Entretiens").mkdir(parents=True)
    (sb / "library" / "@Recently-Snapshot").mkdir()
    assert api.get("/api/destinations").json() == ["Cars", "Cars/Entretiens"]
    v = api.get("/api/vocabulary").json()
    assert "Hydro-Quebec" in v["companies"] and "FactureElectricite" in v["types"]


# ------------------------------------------------------------------ learned rules (screen: Rules)
def _learn_voisin(sb):
    from docflow.learn import learn_company, learn_route, learn_type
    from triage import services
    cfg = services.cfg()
    assert learn_company(cfg, "Voisin", "Famille Voisin et fils") and learn_type(cfg, "Voisin", "Lettre")
    assert learn_route(cfg, "Voisin", "Famille/Voisin")


def test_the_learned_rules_are_listed_with_what_they_have_filed(api, sb):
    assert api.get("/api/rules").json() == {"aliases": [], "types": [], "routes": []}
    _learn_voisin(sb)
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    item = Item.objects.get()
    api.post(f"/api/items/{item.id}/approve")                                          # one Hydro-Quebec document filed
    from docflow.learn import learn_company
    from triage import services
    learn_company(services.cfg(), "Hydro-Quebec", "Hydro Quebec Inc")                   # a learned pattern for a known company
    rules = api.get("/api/rules").json()
    assert [(a["company"], a["filed"]) for a in rules["aliases"]] == [("Hydro-Quebec", 1), ("Voisin", 0)]
    assert rules["types"] == [{"company": "Voisin", "type": "Lettre", "filed": 0}]
    assert rules["routes"] == [{"company": "Voisin", "destination": "Famille/Voisin", "filed": 0}]


def test_a_learned_rule_can_be_forgotten_and_a_hand_written_one_cannot(api, sb):
    _learn_voisin(sb)
    for body in ({"kind": "type", "company": "Voisin"}, {"kind": "route", "company": "Voisin"}, {"kind": "alias", "company": "Voisin"}):
        assert api.post("/api/rules/forget", body, format="json").json() == {"forgotten": True}
    assert api.get("/api/rules").json() == {"aliases": [], "types": [], "routes": []}
    again = api.post("/api/rules/forget", {"kind": "route", "company": "Voisin"}, format="json")
    assert again.status_code == 404 and "no such learned rule" in again.json()["detail"]      # nothing left to forget
    hand = api.post("/api/rules/forget", {"kind": "route", "company": "Hydro-Quebec"}, format="json")
    assert hand.status_code == 404                                                            # hand-written: not in the learned files
    from triage import services
    assert "Hydro-Quebec" in services.cfg().routing                                            # and still in force


def test_one_pattern_of_a_company_can_be_forgotten_on_its_own(api, sb):
    from docflow.learn import learn_company
    from triage import services
    learn_company(services.cfg(), "Voisin", "Famille Voisin et fils")
    learn_company(services.cfg(), "Voisin", "Maison Voisin")
    first = api.get("/api/rules").json()["aliases"][0]["patterns"][0]
    assert api.post("/api/rules/forget", {"kind": "alias", "company": "Voisin", "pattern": first}, format="json").status_code == 200
    assert len(api.get("/api/rules").json()["aliases"][0]["patterns"]) == 1


def test_the_destination_of_a_learned_route_can_be_corrected(api, sb):
    _learn_voisin(sb)
    ok = api.post("/api/rules/route", {"company": "Voisin", "destination": "Famille/Voisin/Lettres"}, format="json")
    assert ok.status_code == 200 and api.get("/api/rules").json()["routes"][0]["destination"] == "Famille/Voisin/Lettres"
    for body in ({"company": "Voisin", "destination": "../out"}, {"company": "Voisin", "destination": "/etc"},
                 {"company": "Voisin", "destination": ""}, {"company": "Voisin", "destination": "."},
                 {"company": "Nobody", "destination": "A/B"}, {"company": "Hydro-Quebec", "destination": "A/B"}, {"company": "Voisin"}):
        r = api.post("/api/rules/route", body, format="json")
        assert r.status_code == 400, body                                                     # refused, never half-applied
    assert api.get("/api/rules").json()["routes"][0]["destination"] == "Famille/Voisin/Lettres"


@pytest.mark.parametrize("body", [{}, {"kind": "other", "company": "A"}, {"kind": "alias"}, {"kind": "alias", "company": 3},
                                  {"kind": "alias", "company": "A", "pattern": 5}, [], "text"])
def test_forgetting_a_rule_refuses_a_malformed_request(api, sb, body):
    assert api.post("/api/rules/forget", body, format="json").status_code == 400


def test_the_rules_need_a_logged_in_user(sb):
    c = APIClient()
    assert c.get("/api/rules").status_code == 403
    assert c.post("/api/rules/forget", {"kind": "alias", "company": "A"}, format="json").status_code in (401, 403)
    assert c.post("/api/rules/route", {"company": "A", "destination": "B"}, format="json").status_code in (401, 403)


# ------------------------------------------------------------------ accuracy (dashboard)
def _filed(n, *, original, final=None, confidence=None, month="2026-09", company="Hydro-Quebec", dir_user=False):
    """An approved item as the engine proposed it (`original`) and as it was finally filed (`final`: the fields changed by hand)."""
    base = {"company": company, "document_type": "Facture", "date": "2026-09-01", "amount": "10.00", "detail": "", "currency": "CAD",
            "analyzer": "rules", "include_amount": True, "check_detail": False, "invoice_number": None,
            "conf": {"company": confidence or 0.99, "type": 0.95, "date": 1.0, "amount": 0.95, "destination": 0.96}}
    orig = dict(base, **original, _dir_user=dir_user)
    return Item.objects.create(source_path=f"/in/{n}.pdf", sha256=f"s{n}", engine_status="auto", state="approved",
                               analysis=dict(orig, **(final or {})), original=orig, confidence=confidence or 0.95,
                               resolved_at=f"{month}-15T12:00:00+00:00")


def test_the_accuracy_counts_what_was_accepted_without_correction_by_field_company_and_month(api, sb):
    assert api.get("/api/stats").json()["total"] == 0                                    # nothing filed yet: zeros, not an error
    _filed(1, original={})                                                               # accepted as proposed
    _filed(2, original={}, month="2026-10")                                              # accepted as proposed, next month
    _filed(3, original={"company": "Hidro"}, final={"company": "Hydro-Quebec"}, company="Hidro")        # company corrected
    _filed(4, original={}, final={"amount": "12.50"}, dir_user=True, company="Telus")    # amount corrected AND destination typed
    s = api.get("/api/stats").json()
    assert s["total"] == 4 and s["untouched"] == 2
    f = {x["field"]: x for x in s["fields"]}
    assert (f["company"]["corrected"], f["amount"]["corrected"], f["destination"]["corrected"]) == (1, 1, 1)
    assert f["date"]["corrected"] == 0 and f["document_type"]["corrected"] == 0
    assert [(m["month"], m["total"], m["untouched"]) for m in s["months"]] == [("2026-09", 3, 1), ("2026-10", 1, 1)]
    companies = {c["company"]: c for c in s["companies"]}
    assert companies["Telus"]["corrected"] == 1 and companies["Hydro-Quebec"]["total"] == 3          # by the company finally filed under


def test_the_accuracy_by_confidence_band_and_the_suggested_threshold(api, sb):
    # 24 documents the engine was at least 90 % sure of, all accepted as proposed; then 3 at 85-89 %, one of them corrected
    for n in range(24):
        _filed(n, original={}, confidence=0.90 + (n % 5) * 0.01)
    for n, corrected in zip(range(100, 103), (False, False, True)):
        _filed(n, original={}, final={"company": "Other"} if corrected else None, confidence=0.86 + (n - 100) * 0.01)
    s = api.get("/api/stats").json()
    bands = {b["band"]: (b["total"], b["untouched"]) for b in s["bands"]}
    assert bands["90-94"] == (24, 24) and bands["85-89"] == (3, 2)
    assert s["threshold"]["current"] == 0.95
    assert s["threshold"]["suggested"] == 0.90 and s["threshold"]["documents"] == 24      # every document at or above 90 % was untouched
    assert s["threshold"]["newly_automatic"] == 24                                          # and all 24 are below today's 95 %


def test_no_threshold_is_suggested_from_too_few_documents_or_when_the_top_ones_were_corrected(api, sb):
    for n in range(5):
        _filed(n, original={}, confidence=0.9)
    assert api.get("/api/stats").json()["threshold"]["suggested"] is None                  # 5 documents prove nothing
    Item.objects.all().delete()
    for n in range(30):
        _filed(n, original={}, final={"date": "2020-01-01"} if n == 0 else None, confidence=0.99 if n == 0 else 0.9)
    assert api.get("/api/stats").json()["threshold"]["suggested"] is None                  # the most confident one was wrong


def test_the_accuracy_needs_a_logged_in_user(sb):
    assert APIClient().get("/api/stats").status_code == 403


# ------------------------------------------------------------------ search of the filed archive
def _scan_and_file_everything(api, sb):
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    pdf(sb / "inbox" / "second.pdf", HYDRO[:2] + ["Numero de facture : 777000111", HYDRO[3]])
    api.post("/api/scan")
    ids = [i.id for i in Item.objects.filter(engine_status__in=["auto", "confirm"])]            # both are filed as proposed
    assert len(ids) == 2 and api.post("/api/items/approve-selected", {"ids": ids}, format="json").json()["failed"] == []


def test_the_text_read_at_scan_time_is_kept_and_a_filed_document_is_found_by_its_words(api, sb):
    from triage.models import ItemText
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    pdf(sb / "inbox" / "second.pdf", HYDRO[:2] + ["Numero de facture : 777000111", HYDRO[3]])
    api.post("/api/scan")
    assert ItemText.objects.count() == 2 and "Facture" in ItemText.objects.filter(item__source_path__endswith="hydro.pdf").get().text
    assert api.get("/api/search?q=electricite").json() == []                                   # pending: not in the archive yet
    api.post("/api/items/approve-auto")
    hits = api.get("/api/search?q=electricite").json()
    assert {(h["company"], h["filename"].split(" - ")[1]) for h in hits} == {("Hydro-Quebec", "Hydro-Quebec")} and len(hits) == 2
    assert hits[0]["folder"].startswith("Bills/") and "\x01" in hits[0]["snippet"] and "\x02" in hits[0]["snippet"]   # the words found are marked
    assert api.get(f"/api/items/{hits[0]['id']}/pdf").status_code == 200                       # and the filed document can be opened


@pytest.mark.parametrize("query,expected", [("électricité", 2), ("ELECTRICITE", 2), ("elect", 2),            # accents, case, a beginning (both invoices say it)
                                            ("facture 123456789", 1), ("777000111", 1), ("hydro 777000111", 1),
                                            ("hydro introuvable", 0), ("introuvable", 0)])   # every word must be there
def test_the_search_ignores_accents_and_case_wants_every_word_and_accepts_a_beginning(api, sb, query, expected):
    _scan_and_file_everything(api, sb)
    assert len(api.get("/api/search", {"q": query}).json()) == expected


@pytest.mark.parametrize("query", ['"', "*", "NEAR(", "hydro AND", "a OR b NOT c", "-hydro", "col:umn", "(", ")", "'; DROP TABLE x; --",
                                   "hydro*", '"hydro', "‮", "😀", "x" * 300, "hydro " * 30])
def test_the_search_syntax_typed_or_pasted_never_reaches_the_index_and_never_gives_a_500(api, sb, query):
    _scan_and_file_everything(api, sb)
    r = api.get("/api/search", {"q": query})
    assert r.status_code in (200, 400)                                                           # words found, or a clear refusal
    if r.status_code == 400:
        assert "word" in r.json()["detail"]


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "   "}, {"q": "!!!"}, {"q": "a", "limit": "0"}, {"q": "a", "limit": "51"},
                                    {"q": "a", "limit": "abc"}, {"q": "a", "limit": "-3"}])
def test_the_search_refuses_an_empty_query_or_a_bad_limit(api, sb, params):
    assert api.get("/api/search", params).status_code == 400


def test_the_search_only_shows_filed_documents_and_follows_the_text_when_an_item_goes_away(api, sb):
    from triage.models import ItemText
    _scan_and_file_everything(api, sb)
    pdf(sb / "inbox" / "later.pdf", GARAGE[:1] + ["Date: 6 avril 2025", "Poubelle rare", "Total 9,00 $"])
    api.post("/api/scan")                                                                          # pending, with its text
    assert api.get("/api/search?q=poubelle").json() == []
    ItemText.objects.filter(item__state="approved", item__source_path__endswith="hydro.pdf").update(text="remplace par autre chose")
    assert len(api.get("/api/search?q=electricite").json()) == 1 and len(api.get("/api/search?q=autre").json()) == 1   # the index follows an update
    Item.objects.filter(source_path__endswith="hydro.pdf").delete()
    assert api.get("/api/search?q=autre").json() == []                                             # and a deletion (cascade)


def test_the_text_kept_for_a_document_is_capped(api, sb, monkeypatch):
    from triage import services
    from triage.models import ItemText
    monkeypatch.setattr(services, "MAX_INDEXED_TEXT", 40)
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    assert len(ItemText.objects.get().text) == 40


def test_documents_filed_before_the_search_existed_are_read_again_by_reindex_text(api, sb):
    from triage import services
    from triage.models import ItemText
    _scan_and_file_everything(api, sb)
    ItemText.objects.all().delete()                                                                # as if filed by an older version
    Item.objects.filter(source_path__endswith="second.pdf").update(result_path="/nowhere/gone.pdf")   # one filed file went missing
    assert api.get("/api/search?q=123456789").json() == []
    result = services.reindex_text()
    assert result == {"indexed": 1, "unreadable": 1, "without_text": 0}                           # the missing one is counted, not fatal
    assert len(api.get("/api/search?q=123456789").json()) == 1
    assert services.reindex_text() == {"indexed": 0, "unreadable": 1, "without_text": 0}           # nothing more to do for the readable one


def test_the_search_needs_a_logged_in_user(sb):
    assert APIClient().get("/api/search?q=hydro").status_code == 403


def test_an_item_being_approved_by_another_request_is_refused_not_filed_twice(api, sb):
    # DOC474.19: two tabs (or a single and a batch approval) both pass the in-memory state check; only ONE may file it
    from triage import services
    f = pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    it = Item.objects.get()
    stale = Item.objects.get(pk=it.pk)  # what the second request loaded before the first one started
    assert services._claim(it) is None  # the first request has reserved it and is about to move the file
    with pytest.raises(services.ApiError):
        services.approve(stale)  # still PENDING in memory: must be refused by the database, before any move
    assert f.exists() and Item.objects.get(pk=it.pk).state == Item.PENDING
    Item.objects.filter(pk=it.pk).update(resolved_at=None)
    assert api.post(f"/api/items/{it.pk}/approve").status_code == 200  # a released item can be approved


def test_a_failed_approval_releases_the_item(api, sb):
    pdf(sb / "inbox" / "x.pdf", ["Lettre", "Le 3 mai 2025"])
    api.post("/api/scan")
    i = api.get("/api/items").json()[0]["id"]
    assert api.post(f"/api/items/{i}/approve").status_code == 400  # incomplete proposal
    assert Item.objects.get(pk=i).resolved_at is None  # not left reserved: the user can fix it and approve


def _approvable(api, sb):
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    return Item.objects.get()


def test_a_busy_database_right_after_filing_is_retried_and_the_approval_is_recorded(api, sb, monkeypatch):
    # DOC474.140: the file is moved and in the engine's history; the queue must not stay "pending" for a passing lock
    from django.db.utils import OperationalError
    from triage import services
    it = _approvable(api, sb)
    monkeypatch.setattr(services.time, "sleep", lambda s: None)
    real, fails = Item.save, [OperationalError("database is locked")]

    def flaky(self, *a, **k):
        if self.state == Item.APPROVED and fails:
            raise fails.pop()
        return real(self, *a, **k)
    monkeypatch.setattr(Item, "save", flaky)
    assert api.post(f"/api/items/{it.pk}/approve").status_code == 200
    assert Item.objects.get(pk=it.pk).state == Item.APPROVED and Item.objects.get(pk=it.pk).result_path


def test_a_filed_document_that_cannot_be_recorded_says_where_it_went_and_stays_reserved(api, sb, monkeypatch):
    from django.db.utils import OperationalError
    from triage import services
    it = _approvable(api, sb)
    monkeypatch.setattr(services.time, "sleep", lambda s: None)
    real = Item.save

    def always_locked(self, *a, **k):
        if self.state == Item.APPROVED:
            raise OperationalError("database is locked")
        return real(self, *a, **k)
    monkeypatch.setattr(Item, "save", always_locked)
    r = api.post(f"/api/items/{it.pk}/approve")
    assert r.status_code == 400 and "was filed" in str(r.json())          # the user is told, with the destination
    assert not (sb / "inbox" / "hydro.pdf").exists() and list((sb / "library").rglob("*.pdf"))   # it IS filed
    assert Item.objects.get(pk=it.pk).resolved_at is not None                # and not handed back to the queue as "pending"


def test_decide_only_ignores_or_removes_it_never_approves_without_filing(api, sb):
    # DOC474.141: decide(it, "approved") marked an item approved without any file being filed
    from triage import services
    it = _approvable(api, sb)
    for bad in (Item.APPROVED, Item.PENDING, "nonsense", ""):
        with pytest.raises(services.ApiError):
            services.decide(Item.objects.get(pk=it.pk), bad)
    assert Item.objects.get(pk=it.pk).state == Item.PENDING and (sb / "inbox" / "hydro.pdf").exists()
    assert services.decide(Item.objects.get(pk=it.pk), Item.IGNORED).state == Item.IGNORED


def test_the_scan_counters_are_bounded_by_the_database(sb):
    # DOC474.186: nothing stopped a negative counter, or more files done than there are to do
    from django.db import IntegrityError, transaction
    for bad in ({"total": -1}, {"done": -1}, {"created": -1}, {"skipped": -1}, {"total": 1, "done": 2}, {"done": 1, "created": 2}):
        with pytest.raises(IntegrityError), transaction.atomic():
            ScanJob.objects.create(state="done", **bad)
    ok = ScanJob.objects.create(state="done", total=3, done=3, created=2, skipped=1)
    assert ok.pk


def test_the_progress_reaches_the_total_even_when_a_file_is_set_aside_by_a_collision(api, sb, monkeypatch):
    from django.db import IntegrityError
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    pdf(sb / "inbox" / "b.pdf", GARAGE)
    real, calls = Item.objects.create, []

    def collide_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("the same file is already pending")        # the race the scan already tolerates
        return real(*a, **k)
    monkeypatch.setattr(Item.objects, "create", collide_once)
    job = api.post("/api/scan").json()["job"]
    assert job["state"] == "done" and job["total"] == 2
    assert job["done"] == 2 and job["created"] == 1                          # both processed, one created, one set aside


def test_the_models_and_the_migrations_agree(sb):
    # DOC474.186: the new constraints exist in models.py AND in a migration, so a deployed database gets them
    from django.core.management import call_command
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)        # exits non-zero if a migration is missing


def test_one_file_the_engine_cannot_analyse_does_not_stop_the_scan(api, sb, monkeypatch):
    # DOC474.205: an exception from propose() was re-raised by fut.result() and the whole scan ended in error
    from triage import services
    pdf(sb / "inbox" / "a-breaks.pdf", HYDRO)
    pdf(sb / "inbox" / "b-fine.pdf", GARAGE)
    real = services.propose

    def breaks_on_a(path, *args, **kwargs):
        if path.name == "a-breaks.pdf":
            raise RuntimeError("the analyser choked on this one")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(services, "propose", breaks_on_a)
    job = api.post("/api/scan").json()["job"]
    assert job["state"] == "done" and job["total"] == 2 and job["done"] == 2 and job["created"] == 2
    by_name = {Path(i.source_path).name: i for i in Item.objects.all()}
    assert by_name["a-breaks.pdf"].engine_status == "error" and "RuntimeError" in " ".join(by_name["a-breaks.pdf"].notes)
    assert by_name["b-fine.pdf"].engine_status != "error"                      # the other file was analysed as usual


def test_the_dashboard_does_not_walk_the_source_folders_on_every_refresh(api, sb, monkeypatch):
    # DOC474.206: the page refreshes every 15 s; each refresh walked the whole inbox (a NAS) again
    from triage import services
    walks = []
    real = services.pdfs_under
    monkeypatch.setattr(services, "pdfs_under", lambda p: walks.append(p) or real(p))
    clock = [1000.0]
    monkeypatch.setattr(services.time, "monotonic", lambda: clock[0])
    services._forget_counts()
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    first = api.get("/api/dashboard").json()
    n = len(walks)
    assert n >= 1 and first["sources"][0]["files"] == 1
    clock[0] += 10
    api.get("/api/dashboard")
    assert len(walks) == n                                       # inside the delay: counted from memory
    pdf(sb / "inbox" / "b.pdf", GARAGE)
    clock[0] += 60
    assert api.get("/api/dashboard").json()["sources"][0]["files"] == 2 and len(walks) > n      # after it: counted again
    n = len(walks)
    api.post("/api/scan")                                        # a scan changes the files: the next view is fresh at once
    api.get("/api/dashboard")
    assert len(walks) > n


def test_a_scan_left_running_by_a_killed_worker_does_not_block_the_next_one(api, sb):
    # DOC474.254: claimed to forbid any new scan for good; scan_start retires a "running" scan nobody touched for 10 minutes
    from datetime import timedelta

    from django.utils import timezone
    dead = ScanJob.objects.create()                                            # state running, as left by a killed process
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    assert api.post("/api/scan").json()["job"]["state"] == "running"           # recent: it is alive, no second scan starts
    assert ScanJob.objects.count() == 1 and Item.objects.count() == 0
    ScanJob.objects.filter(pk=dead.pk).update(updated_at=timezone.now() - timedelta(minutes=11))
    job = api.post("/api/scan").json()["job"]
    assert job["state"] == "done" and job["created"] == 1 and ScanJob.objects.count() == 2   # stale: retired, a new scan runs
    old = ScanJob.objects.get(pk=dead.pk)
    assert old.state == "error" and "abandoned" in old.error


def test_a_file_set_aside_by_a_collision_is_counted_in_the_jobs_skipped(api, sb, monkeypatch):
    # DOC474.17: skipped went up locally but job.skipped (and the synchronous answer) never saw it
    from django.db import IntegrityError
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    pdf(sb / "inbox" / "b.pdf", GARAGE)
    real, calls = Item.objects.create, []

    def collide_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("the same file is already pending")
        return real(*a, **k)
    monkeypatch.setattr(Item.objects, "create", collide_once)
    res = api.post("/api/scan").json()
    assert res["created"] == 1 and res["skipped"] == 1                       # the synchronous answer
    assert res["job"]["skipped"] == 1 and res["job"]["created"] == 1 and res["job"]["done"] == 2


def test_search_finds_the_filed_document_not_the_copy_that_went_to_quarantine(api, sb):
    # DOC474.18: an approved duplicate sits in quarantine/duplicates but its text was indexed too: two hits for one document
    a = pdf(sb / "inbox" / "a.pdf", HYDRO)
    (sb / "inbox" / "b_copy.pdf").write_bytes(a.read_bytes())
    api.post("/api/scan")
    rows = {r["filename"]: r for r in api.get("/api/items").json()}
    api.post("/api/items/approve-auto")
    api.post(f"/api/items/{rows['b_copy.pdf']['id']}/approve")                 # the copy is quarantined, state approved
    assert (sb / "quarantine" / "duplicates" / "b_copy.pdf").exists()
    hits = api.get("/api/search", {"q": "Hydro"}).json()
    assert len(hits) == 1 and "quarantine" not in hits[0]["folder"]            # one document, the one in the library


def test_approve_all_auto_files_at_most_one_batch_and_says_how_many_remain(api, sb, monkeypatch):
    # DOC474.20: the button ignored MAX_BATCH: hundreds of moves on the NAS inside ONE request
    from triage import services
    for n in (1, 2, 3):
        pdf(sb / "inbox" / f"h{n}.pdf", HYDRO[:1] + [f"Facture d'electricite du {n} octobre 2025", f"Numero de facture : 10000000{n}",
                                                    "Montant de la presente facture : 158,98 $"])
    api.post("/api/scan")
    assert Item.objects.filter(engine_status="auto").count() == 3
    monkeypatch.setattr(services, "MAX_BATCH", 2)
    first = api.post("/api/items/approve-auto").json()
    assert len(first["approved"]) == 2 and first["remaining"] == 1               # one batch, and the rest is announced
    second = api.post("/api/items/approve-auto").json()
    assert len(second["approved"]) == 1 and second["remaining"] == 0


def test_a_hand_typed_name_survives_the_edit_of_another_field_until_it_is_cleared(api, sb):
    # DOC474.22: the destination had a "chosen by the human" flag (_dir_user), the name did not
    pdf(sb / "inbox" / "hydro.pdf", HYDRO)
    api.post("/api/scan")
    i = api.get("/api/items").json()[0]["id"]
    assert api.patch(f"/api/items/{i}", {"final_name": "Ma facture d'octobre.pdf"}, format="json").status_code == 200
    r = api.patch(f"/api/items/{i}", {"date": "2025-10-08"}, format="json").json()          # another field, no name sent
    assert r["final_name"] == "Ma facture d'octobre.pdf" and r["date"] == "2025-10-08"        # the typed name is kept
    r = api.patch(f"/api/items/{i}", {"amount": "99.00"}, format="json").json()
    assert r["final_name"] == "Ma facture d'octobre.pdf"
    r = api.patch(f"/api/items/{i}", {"final_name": ""}, format="json").json()              # explicitly emptied: back to automatic
    assert r["final_name"] != "Ma facture d'octobre.pdf" and "2025-10-08" in r["final_name"] and "99.00" in r["final_name"]
    r = api.patch(f"/api/items/{i}", {"date": "2025-10-09"}, format="json").json()
    assert "2025-10-09" in r["final_name"]                                                   # and it follows the fields again


@pytest.mark.parametrize("limit", ["--5", "²", "٣", "5.5", "1e1", "", "abc", "-5", "0", "51"])
def test_a_search_limit_that_is_not_a_whole_number_from_1_to_50_is_a_400_never_a_500(api, sb, limit):
    # DOC474.54: lstrip("-").isdigit() let "--5" and Unicode digits like "²" reach int(), which raised: HTTP 500
    r = api.get("/api/search", {"q": "hydro", "limit": limit})
    assert r.status_code == 400, (limit, r.status_code)
    assert api.get("/api/search", {"q": "hydro", "limit": "5"}).status_code == 200


def test_an_unknown_state_filter_is_a_400_like_an_unknown_group(api, sb):
    # DOC474.55: "state=pendng" returned an empty list and X-Total-Count 0, as if everything were filed
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    for bad in ("pendng", "", "APPROVED", "approved ", "all,pending"):
        assert api.get("/api/items", {"state": bad}).status_code == 400, bad
    for good in ("pending", "approved", "ignored", "removed", "all"):
        assert api.get("/api/items", {"state": good}).status_code == 200, good
    assert len(api.get("/api/items", {"state": "pending"}).json()) == 1                       # (and the default is unchanged)
    assert api.get("/api/items", {"group": "nope"}).status_code == 400                         # the behaviour it should match


def test_the_web_services_close_every_history_connection_they_open(api, sb, monkeypatch):
    from docflow.db import DB as DBClass
    from triage import services
    opened, closed = [], []
    real_init, real_close = DBClass.__init__, DBClass.close

    def counting_init(self, *a, **k):
        opened.append(1)
        real_init(self, *a, **k)

    def counting_close(self):
        closed.append(1)
        real_close(self)
    monkeypatch.setattr(DBClass, "__init__", counting_init)
    monkeypatch.setattr(DBClass, "close", counting_close)
    pdf(sb / "inbox" / "a.pdf", HYDRO)
    api.post("/api/scan")
    api.post("/api/items/approve-auto")
    services.history()
    assert opened and len(closed) == len(opened), (len(opened), len(closed))


@pytest.mark.django_db(transaction=True)   # no wrapping test transaction: the atomic block below is the outermost one, a real BEGIN
def test_a_transaction_takes_the_write_lock_when_it_begins_so_the_busy_timeout_applies(sb):
    # DOC474.94: a DEFERRED transaction that reads and then writes gets SQLITE_BUSY at once (WAL), without waiting its 20 s
    from django.db import connection, transaction
    seen = []

    def spy(execute, sql, params, many, context):
        seen.append(sql)
        return execute(sql, params, many, context)
    with connection.execute_wrapper(spy), transaction.atomic():
        Item.objects.count()
    assert any(s.upper().startswith("BEGIN IMMEDIATE") for s in seen), seen
    assert connection.settings_dict["OPTIONS"]["timeout"] == 20


def test_errors_of_the_site_and_the_engine_reach_a_log_handler_whatever_debug_is():
    # DOC474.95: with DEBUG off Django mails django.request errors to ADMINS (none): a crash left no trace in the journal
    import logging

    from django.conf import settings
    assert settings.LOGGING["disable_existing_loggers"] is False
    for name in ("django", "docflow", "triage"):
        logger = logging.getLogger(name)
        handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert handlers, f"{name} has no console handler"
        assert logger.level <= logging.WARNING and handlers[0].level <= logging.WARNING, name
    assert logging.getLogger("django.request").getEffectiveLevel() <= logging.ERROR


def test_a_new_secret_key_is_on_the_disk_before_it_is_published_and_the_publication_is_too(tmp_path, monkeypatch):
    # DOC474.96: a power cut right after the hard link could leave a PUBLISHED but empty file, and the site then refuses to start
    import os

    from webapp import settings as webapp_settings
    events = []
    real_fsync, real_link = os.fsync, os.link
    monkeypatch.setattr(webapp_settings.os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(webapp_settings.os, "link", lambda a, b: (events.append("link"), real_link(a, b))[1])
    target = tmp_path / "storage" / ".django_secret"
    key = webapp_settings.load_or_create_secret(target)
    assert key and target.read_text().strip() == key
    assert events == ["fsync", "link", "fsync"], events           # the file first, then the link, then the folder that holds it
    events.clear()
    assert webapp_settings.load_or_create_secret(target) == key   # an existing key: read as is, nothing written
    assert events == []


def test_engine_status_is_a_closed_list_in_the_model_and_in_the_database(sb):
    # DOC474.102: a typo such as "confrim" was stored without a word and the item vanished from every filter on that status
    import re
    from pathlib import Path

    from django.db import IntegrityError, transaction
    for good in ("auto", "confirm", "manual", "duplicate", "logical_duplicate", "error"):
        assert Item.objects.create(source_path=f"/x/{good}.pdf", sha256=good, engine_status=good).pk
    with pytest.raises(IntegrityError), transaction.atomic():
        Item.objects.create(source_path="/x/typo.pdf", sha256="typo", engine_status="confrim")
    assert set(Item._meta.get_field("engine_status").choices and dict(Item._meta.get_field("engine_status").choices)) == {
        "auto", "confirm", "manual", "duplicate", "logical_duplicate", "error"}
    pipeline = (Path(__file__).resolve().parents[1] / "backend" / "docflow" / "pipeline.py").read_text()
    produced = set(re.findall(r"status(?:\s*=\s*|=)\"(\w+)\"", pipeline)) - {"classified", "quarantine", "move"}
    assert produced <= {"auto", "confirm", "manual", "duplicate", "logical_duplicate", "error"}, produced     # the engine writes no other


def test_the_database_constraints_are_built_from_the_choices_not_copied_from_them():
    # DOC474.100 / .101: the CHECK lists were typed a second time; a state added to the choices alone would be refused by the database
    import re
    from pathlib import Path

    from triage.models import ScanJob
    source = (Path(__file__).resolve().parents[1] / "backend" / "triage" / "models.py").read_text()
    assert not re.search(r'__in=\[\s*"', source), "a constraint still carries a typed list of values"
    assert 'state="pending"' not in source and 'state="running"' not in source
    def listed(model, name):
        constraint = next(c for c in model._meta.constraints if c.name == name)
        return set(constraint.condition.children[0][1])
    assert listed(Item, "item_state_is_known") == set(Item.State.values)
    assert listed(Item, "item_engine_status_is_known") == set(Item.EngineStatus.values)
    assert listed(ScanJob, "scan_state_is_known") == set(ScanJob.State.values)


def test_the_full_text_migration_says_clearly_that_it_needs_sqlite_with_fts5():
    # DOC474.133: on PostgreSQL, MySQL or a SQLite built without FTS5, migrate stopped on a SQL syntax error with no explanation
    import importlib
    import types
    migration = importlib.import_module("triage.migrations.0008_item_text_search")
    check = migration.require_sqlite_with_fts5

    class Fake:
        def __init__(self, vendor, fts5=True):
            self.connection = types.SimpleNamespace(vendor=vendor, cursor=lambda: Cursor(fts5))

    class Cursor:
        def __init__(self, fts5):
            self.fts5 = fts5

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            return self

        def fetchone(self):
            return (1 if self.fts5 else 0,)
    for vendor in ("postgresql", "mysql"):
        with pytest.raises(RuntimeError, match="requires SQLite"):
            check(None, Fake(vendor))
    with pytest.raises(RuntimeError, match="FTS5"):
        check(None, Fake("sqlite", fts5=False))
    check(None, Fake("sqlite", fts5=True))                                           # SQLite with FTS5: fine
    from django.db import connection
    check(None, types.SimpleNamespace(connection=connection))                       # the SQLite this very test runs on


def test_api_routes_have_no_trailing_slash_and_a_wrong_one_is_a_json_404(api, sb):
    # DOC474.135 feared a catch-all that hides APPEND_SLASH redirects: every route is declared WITHOUT the slash, so none is needed
    for good in ("/api/items", "/api/history", "/api/dashboard", "/api/rules", "/api/scan/status"):
        assert api.get(good).status_code == 200, good
    for slashed in ("/api/items/", "/api/history/", "/api/dashboard/"):
        r = api.get(slashed)
        assert r.status_code == 404 and r["Content-Type"] == "application/json" and r.json() == {"detail": "not found"}, slashed


def test_the_pending_list_is_read_in_its_default_order_through_an_index(sb):
    # DOC474.137: Meta.ordering is (-confidence, id) and the queue filters on state: the table was sorted on every read
    from django.db import connection
    sql, params = Item.objects.filter(state=Item.PENDING).query.sql_with_params()
    with connection.cursor() as cursor:
        plan = " ".join(row[3] for row in cursor.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall())
    assert "item_state_conf_idx" in plan and "TEMP B-TREE" not in plan, plan


def test_a_zero_amount_is_an_amount_not_an_absent_one_in_the_accuracy_figures(sb):
    # DOC474.142: `value or None` turned 0 into None: an amount corrected from "absent" to zero counted as untouched
    from django.utils import timezone
    from triage import services
    base = {"company": "Acme", "document_type": "Facture", "date": "2025-10-07", "detail": "", "currency": "CAD", "conf": {}}
    cases = {                                           # (what the engine proposed, what was filed) -> was the amount corrected?
        "absent_to_zero": ({**base, "amount": None}, {**base, "amount": 0}, True),
        "absent_to_zero_text": ({**base, "amount": None}, {**base, "amount": "0.00"}, True),
        "zero_to_absent": ({**base, "amount": 0}, {**base, "amount": None}, True),
        "zero_kept": ({**base, "amount": 0}, {**base, "amount": 0}, False),
        "none_and_empty_are_the_same": ({**base, "amount": None}, {**base, "amount": ""}, False),
        "unchanged": ({**base, "amount": "158.98"}, {**base, "amount": "158.98"}, False),
    }
    for name, (original, analysis, _) in cases.items():
        Item.objects.create(source_path=f"/x/{name}.pdf", sha256=name, engine_status="auto", state=Item.APPROVED, analysis=analysis,
                            original=original, resolved_at=timezone.now())
    fields = {f["field"]: f for f in services.stats()["fields"]}
    assert fields["amount"]["total"] == len(cases)
    assert fields["amount"]["corrected"] == sum(1 for *_, corrected in cases.values() if corrected)      # 3: no zero lost


def test_the_rules_screen_says_which_learned_file_is_unreadable_instead_of_a_500(api, sb, settings):
    # DOC474.162: a corrupt learned file made GET /api/rules (and forget / route) crash with a raw YAML error
    learn_dir = settings.DOCFLOW.learn_dir
    learn_dir.mkdir(parents=True, exist_ok=True)
    bad = learn_dir / "company_aliases.yaml"
    bad.write_text("Acme: [unclosed\n  - x", encoding="utf-8")
    before = bad.read_bytes()
    r = api.get("/api/rules")
    assert r.status_code == 400 and "company_aliases.yaml" in r.json()["detail"] and "left untouched" in r.json()["detail"]
    r = api.post("/api/rules/forget", {"kind": "alias", "company": "Acme", "pattern": "x"}, format="json")
    assert r.status_code == 400 and "company_aliases.yaml" in r.json()["detail"]
    r = api.post("/api/rules/route", {"company": "Acme", "destination": "A/B"}, format="json")
    assert r.status_code == 400 and "company_aliases.yaml" in r.json()["detail"]
    assert bad.read_bytes() == before                                                       # never overwritten
    bad.write_text("Acme:\n- acme\n", encoding="utf-8")
    assert api.get("/api/rules").status_code == 200                                          # fixed by hand: it works again


def test_in_the_sandbox_the_secret_key_and_the_rate_limit_cache_live_in_the_sandbox_not_in_production_storage(tmp_path):
    # DOC474.251: the database followed DOCFLOW_SANDBOX, the key and the login counters kept using the real storage folder
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()
    env = {**os.environ, "DOCFLOW_SANDBOX": str(sandbox), "PYTHONPATH": str(root / "backend")}
    env.pop("DOCFLOW_SECRET_KEY", None)
    code = ("import json; from webapp import settings as s; "
            "print(json.dumps([s.CACHES['default']['LOCATION'], s.DATABASES['default']['NAME']]))")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout
    cache, db = json.loads(out.strip().splitlines()[-1])
    assert Path(cache) == sandbox / ".cache" and Path(db).parent == sandbox
    assert (sandbox / ".django_secret").is_file()                  # created next to the sandbox database, not in storage/


def test_index_html_asked_for_by_name_is_revalidated_like_the_page_at_the_root(sb, settings, tmp_path):
    # DOC474.280: /index.html took the "file" branch and got no Cache-Control: a stale copy could name bundles that are gone
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    settings.FRONTEND_DIST = dist
    c = APIClient()
    assert c.get("/index.html")["Cache-Control"] == "no-cache"
    assert c.get("/favicon.svg")["Cache-Control"] == "no-cache"                        # not hashed: always asked again (a 304 if unchanged)
    assert "immutable" in c.get("/assets/index-abc123.js")["Cache-Control"]            # the hashed bundles stay forever


@pytest.mark.parametrize("url", ["/api", "/api/", "/api/nope"])
def test_the_api_root_with_or_without_a_slash_is_a_json_404_never_the_app(sb, settings, tmp_path, url):
    # DOC474.281: a JSON client asking for "/api" must not receive index.html with a 200
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    settings.FRONTEND_DIST = dist
    r = APIClient().get(url)
    assert r.status_code == 404 and r["Content-Type"] == "application/json", url


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["pending", "approved"])
def test_looking_an_item_up_by_its_source_path_uses_an_index_whatever_its_state(state):
    # DOC474.282: a rescan asks "is there an item for this path?" once per file: that must not read the whole table
    from django.db import connection
    from triage.models import Item
    qs = Item.objects.filter(source_path="/x/a.pdf", state=state)
    sql, params = qs.query.sql_with_params()
    with connection.cursor() as cur:
        cur.execute("EXPLAIN QUERY PLAN " + sql, params)
        plan = " ".join(str(r[-1]) for r in cur.fetchall())
    assert plan.startswith("SEARCH") and "USING" in plan and "SCAN" not in plan, plan


def test_a_scan_works_on_a_snapshot_of_the_rules_that_a_correction_made_meanwhile_cannot_change(sb):
    # DOC474.230: the scan thread read the shared rules while a request learned a rule IN PLACE (a company added to the dict
    # being iterated: "dictionary changed size during iteration", or a half-updated mix of old and new rules)
    from django.conf import settings
    from triage import services
    live = settings.DOCFLOW
    snap = services.rules_snapshot(live)
    before = {k: list(v) for k, v in snap.companies.items()}
    live.companies.setdefault("NouvelleSociete", []).append("nouvelle")
    live.types.append({"type": "X", "_learned": True})
    live.routing["NouvelleSociete"] = {"default": {"destination": "A/B"}}
    live.learned_routes.add("NouvelleSociete")
    try:
        assert {k: list(v) for k, v in snap.companies.items()} == before and "NouvelleSociete" not in snap.routing
        assert {"type": "X", "_learned": True} not in snap.types and "NouvelleSociete" not in snap.learned_routes
        assert snap.settings is live.settings and snap.root == live.root           # everything else is shared as it was
    finally:
        live.companies.pop("NouvelleSociete", None)
        live.types[:] = [r for r in live.types if r.get("type") != "X"]
        live.routing.pop("NouvelleSociete", None)
        live.learned_routes.discard("NouvelleSociete")


def test_the_session_endpoint_tells_the_page_which_version_runs(sb):
    from docflow import __version__
    body = APIClient().get("/api/auth/me").json()
    assert body["version"] == __version__ and body["authenticated"] is False


def test_the_release_notes_are_served_to_a_signed_in_user_only(api):
    from docflow import __version__
    notes = api.get("/api/changelog").json()
    assert notes[0]["version"] == __version__ and notes[0]["sections"]
    assert APIClient().get("/api/changelog").status_code in (401, 403)


def test_the_filing_thresholds_are_served_so_the_screen_colours_with_the_engine_s_own_cut_offs(api, sb):
    # DOC474.259: the confidence colours of the screen were two numbers written in the component
    from django.conf import settings
    got = api.get("/api/thresholds").json()
    assert got == {"auto": settings.DOCFLOW.settings["thresholds"]["auto"], "confirm": settings.DOCFLOW.settings["thresholds"]["confirm"]}
    assert APIClient().get("/api/thresholds").status_code in (401, 403)


def test_the_settings_screen_reads_and_saves_the_folders_and_refuses_bad_ones_with_a_reason_per_field(api, sb, tmp_path, monkeypatch):
    # first-run: the user chooses the inbox / library in the tool; nothing is written when a folder is wrong
    from docflow import usersettings
    monkeypatch.setenv("DOCFLOW_HOME", str(tmp_path / "home"))
    got = api.get("/api/settings").json()
    assert {"configured", "inbox", "library_root", "quarantine", "extra_inboxes"} <= set(got)
    inbox, library = tmp_path / "in", tmp_path / "lib"
    inbox.mkdir()
    library.mkdir()
    bad = api.post("/api/settings", {"inbox": str(tmp_path / "nope"), "library_root": str(library)}, format="json")
    assert bad.status_code == 400 and "inbox" in bad.json()["errors"] and not usersettings.load()
    ok = api.post("/api/settings", {"inbox": str(inbox), "library_root": str(library), "quarantine": str(tmp_path / "q"),
                                    "extra_inboxes": []}, format="json")
    assert ok.status_code == 200 and usersettings.load()["inbox"] == str(inbox)
    assert APIClient().post("/api/settings", {}, format="json").status_code in (401, 403)       # signed-in users only


def test_the_folder_browser_lists_sub_folders_only_and_only_for_a_signed_in_user(api, sb, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "file.txt").write_text("x")
    got = api.get("/api/folders", {"path": str(tmp_path)}).json()
    assert got["path"] == str(tmp_path) and got["parent"] == str(tmp_path.parent)
    assert [f for f in got["folders"] if f in ("a", "b", "file.txt")] == ["a", "b"]              # folders, sorted; no files
    assert api.get("/api/folders", {"path": str(tmp_path / "nope")}).status_code == 400
    assert APIClient().get("/api/folders", {"path": str(tmp_path)}).status_code in (401, 403)


def test_the_desktop_launcher_signs_in_with_its_one_time_token_and_nothing_else_does(sb, monkeypatch):
    # the desktop application has one user and no password to type: the launcher that starts the server knows a random token and
    # opens the page with it; without that token (or without DOCFLOW_LOCAL_TOKEN at all) the endpoint signs nobody in
    c = APIClient(enforce_csrf_checks=True)
    c.get("/api/auth/me")
    csrf = c.cookies["csrftoken"].value
    monkeypatch.delenv("DOCFLOW_LOCAL_TOKEN", raising=False)
    assert c.post("/api/auth/local", {"token": "x"}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code == 404          # not a desktop run
    monkeypatch.setenv("DOCFLOW_LOCAL_TOKEN", "s3cret-token-of-this-launch")
    bad = c.post("/api/auth/local", {"token": "wrong"}, format="json", HTTP_X_CSRFTOKEN=csrf)
    assert bad.status_code == 401 and c.get("/api/auth/me").json()["authenticated"] is False
    assert c.post("/api/auth/local", {}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code == 401
    ok = c.post("/api/auth/local", {"token": "s3cret-token-of-this-launch"}, format="json", HTTP_X_CSRFTOKEN=csrf)
    assert ok.status_code == 200 and c.get("/api/auth/me").json()["authenticated"] is True


def test_the_release_notes_come_in_english_on_request_and_the_session_says_whether_it_is_the_desktop_application(api, monkeypatch):
    fr = api.get("/api/changelog").json()
    en = api.get("/api/changelog", {"lang": "en"}).json()
    assert [r["version"] for r in en] == [r["version"] for r in fr] and en[0]["sections"][0]["title"] != fr[0]["sections"][0]["title"]
    monkeypatch.delenv("DOCFLOW_LOCAL_TOKEN", raising=False)
    assert api.get("/api/auth/me").json()["local"] is False
    monkeypatch.setenv("DOCFLOW_LOCAL_TOKEN", "t")
    assert api.get("/api/auth/me").json()["local"] is True
