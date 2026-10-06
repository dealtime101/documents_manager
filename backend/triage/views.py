import logging
import os
import re
import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import FileResponse
from django.middleware.csrf import get_token
from docflow import __version__, usersettings
from docflow.changelog import parse as parse_changelog
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from . import services as s
from .models import Item

log = logging.getLogger(__name__)


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
    resp = Response([s.item_dict(i) for i in qs[offset:offset + limit]])
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


@api_view(["POST"])
def item_action(request, pk, action):
    try:
        it = get_item(pk)
        if action == "approve":
            res = s.approve(it)
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
        fh = path.open("rb")  # handed to FileResponse below, which closes it once sent
    except (Item.DoesNotExist, s.ApiError):
        return err(ValueError("file unavailable"), status.HTTP_404_NOT_FOUND)
    except OSError as e:  # the user only learns "unavailable"; the log says why (permissions, storage, a vanished file)
        log.warning("pdf of item %s unavailable: %s", pk, e)
        return err(ValueError("file unavailable"), status.HTTP_404_NOT_FOUND)
    # shown inline in the preview, but "Save as" proposes the document's own name (Django writes the RFC 6266 form, with the
    # UTF-8 filename* for accents and with quotes escaped, instead of a hand-built header)
    return FileResponse(fh, content_type="application/pdf", as_attachment=False, filename=path.name)


@api_view(["POST"])
def scan_view(request):
    return Response(s.scan_start())


@api_view(["GET"])
def scan_status(request):
    return Response(s.scan_status())


@api_view(["POST"])
def approve_auto(request):
    return Response(s.approve_all_auto())


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
        return Response(s.search(request.query_params.get("q"), int(limit) if re.fullmatch(r"-?[0-9]+", limit) else limit))
    except s.ApiError as e:
        return err(e)


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
    return Response(s.history(max(1, min(n, 500))))  # never the whole table by request, never a negative LIMIT


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
                     "extra_inboxes": list(c.settings.get("extra_inboxes") or [])})


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
