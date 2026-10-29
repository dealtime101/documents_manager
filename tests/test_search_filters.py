"""DOC534.8: the search can be narrowed by the fields read from each filed document (company, type, period, amount) and sorted."""
import pytest
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from triage.models import Item

pytestmark = pytest.mark.django_db

DOCS = [  # (name, company, type, date, amount, text)
    ("hydro-2025.pdf", "Hydro-Québec", "Facture", "2025-10-07", "158.98", "electricite octobre"),
    ("hydro-2024.pdf", "Hydro-Québec", "Facture", "2024-03-05", "80.00", "electricite mars"),
    ("garage-2025.pdf", "Garage Tremblay", "Entretien", "2025-02-01", "1200.50", "pneus et freins"),
    ("nodate.pdf", "Hydro-Québec", "Avis", "XXXX", None, "avis sans date ni montant"),
]


@pytest.fixture
def filed(sb, settings):
    """Four filed documents with the fields set directly (what the engine read, or the person corrected)."""
    from triage.models import ItemText
    library = settings.DOCFLOW.path("library_root")
    (library / "Bills").mkdir(parents=True)
    for n, (name, company, kind, day, amount, text) in enumerate(DOCS):
        path = library / "Bills" / name
        path.write_bytes(b"%PDF-1.4")
        item = Item.objects.create(source_path=str(sb / "inbox" / name), sha256=f"{n:064x}", state=Item.APPROVED,
                                   engine_status="auto", result_path=str(path), final_name=name, rel_dir="Bills",
                                   analysis={"company": company, "document_type": kind, "date": day, "amount": amount, "currency": "CAD"})
        ItemText.objects.create(item=item, text=text)
    return [d[0] for d in DOCS]


def names(api, query="") -> list[str]:
    r = api.get(f"/api/search?{query}")
    assert r.status_code == 200, r.json()
    return [h["filename"] for h in r.json()]


def test_a_filter_alone_lists_the_documents_that_match_newest_first(api, filed):
    assert names(api, "company=hydro") == ["hydro-2025.pdf", "hydro-2024.pdf", "nodate.pdf"]  # contains, any case; no date comes last
    assert names(api, "type=entretien") == ["garage-2025.pdf"]
    hit = api.get("/api/search?type=entretien").json()[0]
    assert (hit["company"], hit["document_type"], hit["date"], hit["amount"], hit["currency"], hit["snippet"]) == (
        "Garage Tremblay", "Entretien", "2025-02-01", "1200.50", "CAD", "")


def test_the_period_keeps_the_documents_dated_in_it_and_drops_the_ones_without_a_date(api, filed):
    assert names(api, "company=hydro&date_from=2025-01-01&date_to=2025-12-31") == ["hydro-2025.pdf"]  # "all the Hydro bills of 2025"
    assert names(api, "date_from=2025-01-01") == ["hydro-2025.pdf", "garage-2025.pdf"]
    assert names(api, "date_to=2024-12-31") == ["hydro-2024.pdf"]
    assert names(api, "date_from=2025-10-07&date_to=2025-10-07") == ["hydro-2025.pdf"]  # both ends are in the period


def test_the_amount_range_keeps_the_documents_with_an_amount_in_it(api, filed):
    assert names(api, "amount_min=100&amount_max=200") == ["hydro-2025.pdf"]
    assert names(api, "amount_min=100", ) == ["hydro-2025.pdf", "garage-2025.pdf"]
    assert names(api, "amount_max=100") == ["hydro-2024.pdf"]  # the document with no amount is never "under 100"
    assert names(api, "amount_min=1200.50&amount_max=1200.50") == ["garage-2025.pdf"]


def test_the_words_and_the_filters_work_together(api, filed):
    assert sorted(names(api, "q=electricite")) == ["hydro-2024.pdf", "hydro-2025.pdf"]  # (ranked by relevance: the order is not asserted)
    assert names(api, "q=electricite&date_from=2025-01-01") == ["hydro-2025.pdf"]
    assert names(api, "q=pneus&company=hydro") == []
    hit = api.get("/api/search?q=electricite&date_from=2025-01-01").json()[0]
    assert "\x01" in hit["snippet"]  # the words found are still marked


def test_the_hits_can_be_sorted_by_date_or_amount_either_way(api, filed):
    assert names(api, "company=hydro&sort=date") == ["hydro-2024.pdf", "hydro-2025.pdf", "nodate.pdf"]
    assert names(api, "company=hydro&sort=-date") == ["hydro-2025.pdf", "hydro-2024.pdf", "nodate.pdf"]
    assert names(api, "date_from=2000-01-01&sort=amount") == ["hydro-2024.pdf", "hydro-2025.pdf", "garage-2025.pdf"]
    assert names(api, "company=&type=&sort=-amount&amount_min=0") == ["garage-2025.pdf", "hydro-2025.pdf", "hydro-2024.pdf"]
    assert names(api, "company=hydro&sort=-amount")[-1] == "nodate.pdf"  # no amount: last, whichever way


def test_the_percent_and_underscore_typed_in_a_filter_are_letters_not_wildcards(api, filed):
    assert names(api, "company=%25") == [] and names(api, "company=Hydro_Qu") == []
    assert names(api, "company=Hydro-Qu%C3%A9bec") == ["hydro-2025.pdf", "hydro-2024.pdf", "nodate.pdf"]


def test_a_filter_that_is_empty_is_no_filter_and_no_words_and_no_filter_is_still_refused(api, filed):
    assert api.get("/api/search?q=&company=&type=").status_code == 400
    assert api.get("/api/search").status_code == 400
    assert sorted(names(api, "q=electricite&company=&date_from=")) == ["hydro-2024.pdf", "hydro-2025.pdf"]  # empty values filter nothing


@pytest.mark.parametrize("params,message", [
    ("date_from=2025-13-01", "date_from must be a date"), ("date_to=yesterday", "date_to must be a date"),
    ("date_from=20250101", "date_from must be a date"), ("date_from=2025-02-30", "date_from must be a date"),
    ("date_from=2025-02-01&date_to=2025-01-01", "the period ends before it starts"),
    ("amount_min=abc", "amount_min must be a number"), ("amount_max=NaN", "amount_max must be a number"),
    ("amount_min=Infinity", "amount_min must be a number"),
    ("amount_min=5&amount_max=1", "the minimum amount is above the maximum"),
    ("company=hydro&sort=random", "sort must be one of"), ("company=" + "x" * 101, "at most 100 characters"),
])
def test_a_bad_filter_is_a_400_that_says_which_never_a_silent_ignore_or_a_500(api, filed, params, message):
    r = api.get(f"/api/search?{params}")
    assert r.status_code == 400 and message in r.json()["detail"]


def test_a_pending_document_and_a_document_outside_the_library_never_show_up(api, filed, sb):
    Item.objects.create(source_path="p", sha256="f" * 64, state=Item.PENDING, engine_status="auto",
                        analysis={"company": "Hydro-Québec", "document_type": "Facture", "date": "2025-10-08", "amount": "1"})
    Item.objects.create(source_path="q", sha256="e" * 64, state=Item.APPROVED, engine_status="duplicate", result_path="/elsewhere/q.pdf",
                        analysis={"company": "Hydro-Québec", "document_type": "Facture", "date": "2025-10-09", "amount": "1"})
    assert "q.pdf" not in names(api, "company=hydro") and len(names(api, "company=hydro")) == 3


def test_the_search_screen_sends_the_filters_and_lets_a_search_start_from_them():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    page = (src / "pages" / "Search.tsx").read_text(encoding="utf-8")
    for field in ("company", "type", "date_from", "date_to", "amount_min", "amount_max", "sort"):
        assert f"setFilter('{field}')" in page, field
    assert "canSearch = query.trim() !== '' || narrowed" in page and 'type="date"' in page
    assert "Object.fromEntries(Object.entries(filters).filter(([, v]) => v))" in (src / "api.ts").read_text(encoding="utf-8")
