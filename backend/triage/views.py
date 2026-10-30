import io
import logging
import os
import re
import secrets
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import FileResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from docflow import __version__, usersettings
from docflow.changelog import parse as parse_changelog
from docflow.extract import image_to_pdf, is_image
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import library as lib
from . import services as s
from .models import Item

log = logging.getLogger(__name__)
HISTORY_MAX = 500  # the most operations /api/history answers with, whatever `n` asks for


def err(e: Exception, code=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": str(e)}, status=code)


def get_item(pk: int) -> Item:
    return Item.objects.get(pk=pk)


@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    """Also called on page load: sets the CSRF cookie and says whether the session is open."""
    get_token(request)
    u = request.user if getattr(request.user, "is_authenticated", False) else None
    return Response({"authenticated": bool(u), "username": u.get_username() if u else None, "version": __version__,
                     "local": bool(os.environ.get("DOCFLOW_LOCAL_TOKEN"))})  # the desktop application: one user, no log-out


class CsrfAlwaysSessionAuthentication(SessionAuthentication):
    """DRF only checks the CSRF token for an already-authenticated user. The sign-in is the request that is anonymous by
    nature, so check it here too: otherwise a third-party page could sign the victim in."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return super().authenticate(request)


@api_view(["POST"])
@authentication_classes([CsrfAlwaysSessionAuthentication])
@permission_classes([AllowAny])
def local_login(request):
    """Desktop application only: it has one user and no password to type. The launcher that started the server knows a random
    token (DOCFLOW_LOCAL_TOKEN) and opens the page with it. Without that variable this endpoint does not exist."""
    expected = os.environ.get("DOCFLOW_LOCAL_TOKEN")
    if not expected:
        return err(ValueError("not found"), status.HTTP_404_NOT_FOUND)
    given = request.data.get("token", "")
    if not isinstance(given, str) or not secrets.compare_digest(given.encode(), expected.encode()):
        return err(ValueError("invalid token"), status.HTTP_401_UNAUTHORIZED)
    user, created = get_user_model().objects.get_or_create(username="local")
    if created:
        user.set_unusable_password()
        user.save()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response({"authenticated": True, "username": user.get_username()})


@api_view(["GET"])
def items(request):
    state = request.query_params.get("state", Item.PENDING)
    try:
        limit, offset = int(request.query_params.get("limit", 500)), int(request.query_params.get("offset", 0))
    except ValueError:
        return err(ValueError("limit and offset must be integers"))
    if limit < 1 or offset < 0:
        return err(ValueError("limit must be at least 1 and offset at least 0"))
    if state != "all" and state not in Item.State.values:  # a typo must not look like "nothing left to file"
        return err(ValueError(f"state must be one of: all, {', '.join(Item.State.values)}"))
    qs = Item.objects.filter(state=state) if state != "all" else Item.objects.all()  # stable order: Meta.ordering
    group = request.query_params.get("group")
    if group:  # one of the dashboard's categories: the tile and the list it opens use the same definition
        try:
            qs = qs.filter(s.in_group(group))
        except s.ApiError as e:
            return err(e)
    limit = min(limit, 500)
    library_root = s.cfg().path("library_root")  # once for the whole list, not once per item
    resp = Response([s.item_dict(i, library_root) for i in qs[offset:offset + limit]])
    resp["X-Total-Count"] = str(qs.count())  # lets the client tell when the list is not the whole queue
    return resp


@api_view(["GET", "PATCH"])
def item_detail(request, pk):
    try:
        it = get_item(pk)
        if request.method == "PATCH":
            it = s.edit(it, request.data)
        return Response(s.item_dict(it))
    except Item.DoesNotExist:
        return err(ValueError("not found"), status.HTTP_404_NOT_FOUND)
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def library(request):
    try:
        return Response(s.library_list(request.query_params.get("path", "")))
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def library_search(request):
    try:
        return Response(lib.search(request.query_params.get("q", "")))
    except s.ApiError as e:
        return err(e)


def _library_action(request, call):
    """One POST of the explorer: the body names the folder or file by its path inside the library, never by an absolute path."""
    try:
        return Response(call(request.data))
    except s.ApiError as e:
        return err(e)


def _text(data, key: str) -> str:
    v = data.get(key, "")
    return v if isinstance(v, str) else ""


@api_view(["POST"])
def library_folder(request):
    return _library_action(request, lambda d: lib.make_folder(_text(d, "parent"), _text(d, "name")))


@api_view(["POST"])
def library_rename(request):
    return _library_action(request, lambda d: lib.rename(_text(d, "path"), _text(d, "name")))


@api_view(["POST"])
def library_move(request):
    return _library_action(request, lambda d: lib.move(_text(d, "path"), _text(d, "to")))


@api_view(["POST"])
def library_delete(request):
    return _library_action(request, lambda d: lib.delete(_text(d, "path")))


@api_view(["GET"])
def library_expired(request):
    return Response(lib.expired())


@api_view(["POST"])
def library_expired_delete(request):
    return _library_action(request, lambda d: lib.delete_expired(d.get("id")))


@api_view(["POST"])
def library_plan(request):
    def call(d):
        fields = d.get("fields")
        return lib.plan(_text(d, "path"), fields if isinstance(fields, dict) else None, _text(d, "rel_dir"), _text(d, "final_name"))
    return _library_action(request, call)


@api_view(["POST"])
def library_apply(request):
    def call(d):
        fields = d.get("fields")
        return lib.apply(_text(d, "path"), fields if isinstance(fields, dict) else {}, _text(d, "rel_dir"), _text(d, "final_name"))
    return _library_action(request, call)


@api_view(["GET"])
def library_file(request):
    """A file of the library, for the explorer: a PDF is shown inline, anything else is only offered for download (a page
    served inline from here would run with the application's own session)."""
    try:
        path = s.library_file(request.query_params.get("path", ""))
        fh = path.open("rb")  # handed to FileResponse, which closes it once sent
    except s.NotFound as e:
        return err(e, status.HTTP_404_NOT_FOUND)
    except s.ApiError as e:  # refused path (out of the library, empty): not "missing", a request that cannot be served
        return err(e)
    except OSError as e:
        log.warning("library file unavailable: %s", e)
        return err(ValueError("file unavailable"), status.HTTP_404_NOT_FOUND)
    pdf = path.suffix.lower() == ".pdf"
    response = FileResponse(fh, content_type="application/pdf" if pdf else "application/octet-stream",
                            as_attachment=not pdf, filename=path.name)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["POST"])
def item_action(request, pk, action):
    try:
        it = get_item(pk)
        if action == "approve":
            res = s.approve(it)
        elif action == "split":
            res = s.split_item(it)
        elif action in ("ignore", "remove"):
            s.decide(it, Item.IGNORED if action == "ignore" else Item.REMOVED)
            res = {}
        else:
            return err(ValueError("unknown action"), status.HTTP_404_NOT_FOUND)
        it.refresh_from_db()
        return Response({"item": s.item_dict(it), **res})
    except Item.DoesNotExist:
        return err(ValueError("not found"), status.HTTP_404_NOT_FOUND)
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def item_pdf(request, pk):
    try:
        # the file can vanish or become unreadable between the check of its path and the opening: still "unavailable"
        path = s.pdf_path(get_item(pk))
        # a picture waiting to be filed is shown as the PDF it will become (a browser cannot show a HEIC); else the file itself
        fh = io.BytesIO(image_to_pdf(path.read_bytes())) if is_image(path) else path.open("rb")  # FileResponse closes it once sent
    except (Item.DoesNotExist, s.ApiError, ValueError):
        return err(ValueError("file unavailable"), status.HTTP_404_NOT_FOUND)
    except OSError as e:  # the user only learns "unavailable"; the log says why (permissions, storage, a vanished file)
        log.warning("pdf of item %s unavailable: %s", pk, e)
        return err(ValueError("file unavailable"), status.HTTP_404_NOT_FOUND)
    # shown inline in the preview, but "Save as" proposes the document's own name (Django writes the RFC 6266 form, with the
    # UTF-8 filename* for accents and with quotes escaped, instead of a hand-built header)
    return FileResponse(fh, content_type="application/pdf", as_attachment=False,
                        filename=path.with_suffix(".pdf").name if is_image(path) else path.name)


@api_view(["POST"])
def scan_view(request):
    return Response(s.scan_start())


@api_view(["GET"])
def scan_status(request):
    return Response(s.scan_status())


@api_view(["POST"])
def approve_auto(request):
    after = request.data.get("after", 0) if isinstance(request.data, dict) else 0
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        return err(ValueError("after must be a whole number of at least 0"))
    return Response(s.approve_all_auto(after))


@api_view(["POST"])
def approve_selected(request):
    try:
        body = request.data
        return Response(s.approve_selected(body.get("ids") if isinstance(body, dict) else None))  # a JSON list is not an object
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def search(request):
    limit = request.query_params.get("limit", "20")
    try:
        # ASCII digits only, one optional minus: "--5" and "²" (which isdigit() accepts) would crash int(); anything else goes
        # on as text and the service refuses it with a clear 400
        params = request.query_params
        return Response(s.search(params.get("q"), int(limit) if re.fullmatch(r"-?[0-9]+", limit) else limit,
                                 {k: params.get(k) for k in s.SEARCH_FILTERS}, params.get("sort") or "relevance"))
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def statement(request):
    """DOC534.9: the CSV of the documents filed in a year, for a spreadsheet or an accountant."""
    params = request.query_params
    try:
        name, text = s.statement(params.get("year"), params.get("layout") or "documents", params.get("delimiter") or "comma")
    except s.ApiError as e:
        return err(e)
    response = FileResponse(io.BytesIO(text.encode("utf-8")), content_type="text/csv; charset=utf-8", as_attachment=True, filename=name)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["GET"])
def stats(request):
    return Response(s.stats())


@api_view(["GET"])
def rules(request):
    try:
        return Response(s.rules())
    except s.ApiError as e:  # a learned file that cannot be read: the screen shows which one
        return err(e)


@api_view(["POST"])
def rules_forget(request):
    try:
        return Response(s.forget_rule(request.data))
    except s.NotFound as e:
        return err(e, status.HTTP_404_NOT_FOUND)
    except s.ApiError as e:
        return err(e)


@api_view(["POST"])
def rules_route(request):
    try:
        return Response(s.set_route(request.data))
    except s.ApiError as e:
        return err(e)


@api_view(["POST"])
def backup_download(request):
    """DOC534.11: the archive of the database, the learned corrections and the settings, as a download. The password (optional) is
    in the body, never in the address."""
    body = request.data if isinstance(request.data, dict) else {}
    out = tempfile.TemporaryFile()  # noqa: SIM115  (the response closes it after the download, and the file is deleted then)
    try:
        s.backup_to(out, body.get("password"))
    except s.ApiError as e:
        out.close()
        return err(e)
    except (OSError, sqlite3.Error):
        out.close()
        log.exception("backup failed")
        return err(s.ApiError("the backup could not be written"), status.HTTP_500_INTERNAL_SERVER_ERROR)
    out.seek(0)
    response = FileResponse(out, content_type="application/zip", as_attachment=True,
                            filename=f"documents-manager-backup-{timezone.localdate()}.zip")
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["POST"])
@parser_classes([MultiPartParser])
def backup_restore(request):
    """DOC534.11: put an uploaded archive back; what it replaces is kept in the user's folder first."""
    try:
        return Response(s.restore_backup(request.FILES.get("file"), request.data.get("password"),
                                         request.data.get("settings") == "true"))
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def missing(request):
    """DOC534.10: the documents that came on a rhythm and have not come, and the series the person chose not to hear about."""
    return Response(s.missing())


@api_view(["POST"])
def missing_ignore(request):
    try:
        return Response(s.ignore_series(request.data))
    except s.ApiError as e:
        return err(e)


@api_view(["POST"])
def missing_restore(request):
    try:
        return Response(s.restore_series(request.data))
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def dashboard(request):
    return Response(s.dashboard())


@api_view(["GET"])
def changelog(request):
    """The release notes, read into releases for the "Release notes" screen: CHANGELOG.en.md for ?lang=en when it exists, else
    CHANGELOG.md (French, the source). Each file is the only place its language is written."""
    names = ["CHANGELOG.en.md", "CHANGELOG.md"] if request.query_params.get("lang") == "en" else ["CHANGELOG.md"]
    for name in names:
        try:
            return Response(parse_changelog((settings.BASE_DIR / name).read_text(encoding="utf-8")))
        except OSError:
            continue
    return Response([])  # a copy without the file: an empty screen, not an error


@api_view(["GET"])
def history(request):
    try:
        n = int(request.query_params.get("n", 50))
    except ValueError:
        return err(ValueError("n must be an integer"))
    return Response(s.history(max(1, min(n, HISTORY_MAX))))  # never the whole table by request, never a negative LIMIT


@api_view(["POST"])
def undo(request, op_id):
    try:
        return Response(s.undo(op_id))
    except s.ApiError as e:
        return err(e)


@api_view(["GET"])
def destinations(request):
    return Response(s.destinations())


@api_view(["GET", "POST"])
def folder_settings(request):
    """GET: the folders in use and whether the user has chosen them yet. POST: validate and save them (400 with a reason per field)."""
    if request.method == "POST":
        try:
            usersettings.save(request.data if isinstance(request.data, dict) else {})
        except usersettings.InvalidSettings as e:
            return Response({"detail": str(e), "errors": e.errors}, status=status.HTTP_400_BAD_REQUEST)
        s.cfg().refresh_learned()  # this worker follows at once; the others at their next request
    c = s.cfg()
    return Response({"configured": c.configured, **{k: c.settings.get(k) for k in ("inbox", "library_root", "quarantine")},
                     "extra_inboxes": list(c.settings.get("extra_inboxes") or []), "watch_inbox": usersettings.load().get("watch_inbox") is True})  # (read where the watcher reads it)


@api_view(["GET"])
def folders(request):
    """The sub-folders of a folder, for the folder picker of the Settings screen (folders only, names sorted)."""
    raw = request.query_params.get("path") or str(Path.home())
    p = Path(raw).expanduser()
    try:
        names = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith("."))
    except OSError:
        return err(ValueError(f"{raw} cannot be read"))
    return Response({"path": str(p), "parent": str(p.parent), "folders": names})


@api_view(["GET"])
def thresholds(request):
    """The cut-offs of config/settings.yaml that decide automatic / confirmation / manual: the screen colours its scores with them."""
    t = s.cfg().settings["thresholds"]
    return Response({"auto": t["auto"], "confirm": t["confirm"]})


@api_view(["GET"])
def vocabulary(request):
    return Response(s.vocabulary())
