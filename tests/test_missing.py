"""DOC534.10: the documents that come on a rhythm and have not come (a monthly bill not received), and the way to stop hearing of one."""
from datetime import date, timedelta

import pytest
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from triage import services as s
from triage.models import Item

pytestmark = pytest.mark.django_db

TODAY = date(2025, 11, 20)


def monthly(start: date, n: int, step: int = 30) -> list[str]:
    return [(start + timedelta(days=step * k)).isoformat() for k in range(n)]


def file_docs(settings, company: str, kind: str, days: list[str], outside: bool = False) -> None:
    library = settings.DOCFLOW.path("library_root")
    folder = library.parent / "elsewhere" if outside else library / "Bills"
    for day in days:
        n = Item.objects.count()
        Item.objects.create(source_path=f"s{n}", sha256=f"{n:064x}", state=Item.APPROVED, engine_status="auto",
                            result_path=str(folder / f"{company}-{day}.pdf"),
                            analysis={"company": company, "document_type": kind, "date": day})


def late(today=TODAY) -> list[dict]:
    return s.missing(today)["missing"]


def test_a_monthly_bill_that_did_not_come_is_reported_with_when_it_was_expected(sb, settings):
    file_docs(settings, "Hydro-Québec", "Facture", monthly(date(2025, 4, 1), 5))  # Apr 1, May 1, May 31, Jun 30, Jul 30
    got = late()
    assert got == [{"company": "Hydro-Québec", "document_type": "Facture", "every_days": 30, "last_date": "2025-07-30",
                    "expected_date": "2025-08-29", "days_late": 83, "documents": 5}]


def test_a_bill_inside_its_margin_is_not_late_and_one_day_past_it_is(sb, settings):
    file_docs(settings, "Hydro-Québec", "Facture", monthly(date(2025, 4, 1), 5))  # expected 2025-08-29, margin 7 days
    assert late(date(2025, 9, 5)) == []
    assert [x["days_late"] for x in late(date(2025, 9, 6))] == [8]


def test_a_few_documents_or_no_steady_rhythm_say_nothing(sb, settings):
    file_docs(settings, "Three", "Facture", monthly(date(2025, 1, 1), 3))  # two gaps are no habit
    file_docs(settings, "Erratic", "Facture", ["2025-01-01", "2025-01-12", "2025-04-20", "2025-04-30", "2025-09-01"])
    file_docs(settings, "Together", "Facture", ["2025-01-01"] * 6 + ["2025-01-02"])  # arrive in one go: not a gap to wait for
    file_docs(settings, "Rare", "Facture", ["2020-01-01", "2023-06-01", "2025-01-01", "2026-06-01"])  # more than a year apart
    assert late(date(2027, 1, 1)) == []


def test_a_skipped_month_does_not_break_a_steady_rhythm(sb, settings):
    days = monthly(date(2025, 1, 1), 4) + [(date(2025, 1, 1) + timedelta(days=30 * 5)).isoformat()]  # one month with nothing
    file_docs(settings, "Garage", "Entretien", days)
    assert [x["every_days"] for x in late(date(2025, 12, 31))] == [30]


def test_a_series_is_a_company_and_a_type_and_only_the_filed_library_counts(sb, settings):
    file_docs(settings, "Hydro", "Facture", monthly(date(2025, 4, 1), 5))
    file_docs(settings, "Hydro", "Avis", monthly(date(2025, 4, 1), 5))                        # same company, other type: its own series
    file_docs(settings, "Elsewhere", "Facture", monthly(date(2025, 4, 1), 5), outside=True)
    file_docs(settings, "NoDate", "Facture", ["XXXX", "2025-13-45", "2025-04-XX", "", "2025-1-1"])
    for item in Item.objects.filter(analysis__company="Hydro", analysis__document_type="Avis")[:1]:
        Item.objects.filter(pk=item.pk).update(state=Item.REMOVED)  # a removed document is not a document that came (nor one that did not)
    names = sorted((x["company"], x["document_type"]) for x in late())
    assert names == [("Hydro", "Avis"), ("Hydro", "Facture")]
    Item.objects.filter(analysis__company="Hydro", analysis__document_type="Avis").update(state=Item.PENDING)
    assert [x["document_type"] for x in late()] == ["Facture"]  # a pending document is not filed yet


def test_the_most_late_comes_first(sb, settings):
    file_docs(settings, "Recent", "Facture", monthly(date(2025, 5, 1), 5))
    file_docs(settings, "Old", "Facture", monthly(date(2025, 2, 1), 4))
    assert [x["company"] for x in late()] == ["Old", "Recent"]


def test_the_spelling_of_the_latest_document_is_the_one_shown(sb, settings):
    days = monthly(date(2025, 4, 1), 5)
    file_docs(settings, "hydro-quebec", "facture", days[:2])
    file_docs(settings, "Hydro-Quebec", "Facture", days[2:])
    assert [(x["company"], x["document_type"], x["documents"]) for x in late()] == [("Hydro-Quebec", "Facture", 5)]


def test_an_ignored_series_is_set_apart_and_can_be_brought_back(api, sb, settings, monkeypatch):
    monkeypatch.setattr(s, "missing", lambda today=None, _real=s.missing: _real(TODAY))
    file_docs(settings, "Hydro-Québec", "Facture", monthly(date(2025, 4, 1), 5))
    assert [x["company"] for x in api.get("/api/missing").json()["missing"]] == ["Hydro-Québec"]
    r = api.post("/api/missing/ignore", {"company": "Hydro-Québec", "document_type": "Facture"}, format="json")
    assert r.status_code == 200 and r.json() == {"missing": [], "ignored": [{"company": "hydro-québec", "document_type": "facture"}]}
    api.post("/api/missing/ignore", {"company": "HYDRO-QUÉBEC ", "document_type": "facture"}, format="json")  # twice, another spelling
    assert len(api.get("/api/missing").json()["ignored"]) == 1
    r = api.post("/api/missing/restore", {"company": "Hydro-Québec", "document_type": "Facture"}, format="json")
    assert r.json()["ignored"] == [] and [x["company"] for x in r.json()["missing"]] == ["Hydro-Québec"]
    assert api.post("/api/missing/restore", {"company": "Nobody", "document_type": "X"}, format="json").status_code == 200


@pytest.mark.parametrize("body", [None, {}, {"company": "A"}, {"company": " ", "document_type": "B"}, {"company": 3, "document_type": "B"}, ["A", "B"]])
def test_a_bad_body_is_a_400_that_says_so(api, body):
    for action in ("ignore", "restore"):
        r = api.post(f"/api/missing/{action}", body, format="json")
        assert r.status_code == 400 and ("must be" in r.json()["detail"] or "required" in r.json()["detail"])


def test_the_dashboard_shows_the_card_and_it_asks_the_server_for_both_the_list_and_the_two_changes():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    assert "<MissingDocuments />" in (src / "pages" / "Dashboard.tsx").read_text(encoding="utf-8")
    api_ts = (src / "api.ts").read_text(encoding="utf-8")
    assert all(url in api_ts for url in ("'/api/missing'", "'/api/missing/ignore'", "'/api/missing/restore'"))
    card = (src / "components" / "MissingDocuments.tsx").read_text(encoding="utf-8")
    assert "if (busy) return" in card and "api.ignoreMissing(s.company, s.document_type)" in card  # one click is one request


def test_the_list_needs_a_logged_in_user(sb):
    from rest_framework.test import APIClient
    for method, url in (("get", "/api/missing"), ("post", "/api/missing/ignore"), ("post", "/api/missing/restore")):
        assert getattr(APIClient(), method)(url).status_code in (401, 403)
