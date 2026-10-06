from pathlib import PurePosixPath

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve


def spa(request, rest=""):
    """Serve the built React interface (frontend/dist); an unknown PAGE falls back to index.html, an unknown FILE is a 404."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Interface not built: cd frontend && npm run build")
    target = (settings.FRONTEND_DIST / rest).resolve()
    if rest and target.is_file() and settings.FRONTEND_DIST.resolve() in target.parents:
        response = serve(request, rest, document_root=settings.FRONTEND_DIST)
        if rest.startswith("assets/"):  # Vite puts a content hash in these names: a changed file has a new name
            response["Cache-Control"] = "public, max-age=31536000, immutable"
        else:  # index.html by name, favicon...: no hash in the name, so ask again each time (a 304 when unchanged)
            response["Cache-Control"] = "no-cache"
        return response
    if PurePosixPath(rest).suffix:  # app.js, logo.svg...: a stale hashed bundle must not come back as HTML with a 200
        raise Http404("No such file")
    response = FileResponse(index.open("rb"), content_type="text/html")  # FileResponse closes the file once it is sent
    response["Cache-Control"] = "no-cache"  # the page names the current bundles: fetch it again each time (it is tiny)
    return response


def api_not_found(request, rest=""):
    """An unknown /api/ route is an API error, never the single-page app (a JSON client would choke on HTML)."""
    return JsonResponse({"detail": "not found"}, status=404)


urlpatterns = [
    path("api/", include("triage.urls")),
    re_path(r"^api(?:/(?P<rest>.*))?$", api_not_found),  # reached only when no real API route matched; "/api" itself too
    re_path(r"^(?P<rest>.*)$", spa),
]
