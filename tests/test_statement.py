"""DOC534.9: the annual statement, a CSV of the documents filed in a year (one line per document, or the totals by company and type)."""
import csv
import io

import pytest
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from test_search_filters import filed  # noqa: F401  (four filed documents: Hydro 2025 and 2024, Garage 2025, one with no date)
from triage.models import Item

pytestmark = pytest.mark.django_db


def rows(api, query: str, delimiter=",") -> list[list[str]]:
    r = api.get(f"/api/statement?{query}")
    assert r.status_code == 200, r.json()
    text = b"".join(r.streaming_content).decode("utf-8")
    assert text.startswith(chr(0xFEFF))  # Excel reads the file as UTF-8
    return list(csv.reader(io.StringIO(text[1:]), delimiter=delimiter))


def test_the_year_lists_each_document_filed_in_it_with_its_fields_oldest_first(api, filed):
    got = rows(api, "year=2025")
    assert got == [["date", "company", "type", "amount", "currency", "folder", "file"],
                   ["2025-02-01", "Garage Tremblay", "Entretien", "1200.50", "CAD", "Bills", "garage-2025.pdf"],
                   ["2025-10-07", "Hydro-Québec", "Facture", "158.98", "CAD", "Bills", "hydro-2025.pdf"]]
    assert rows(api, "year=2024")[1:] == [["2024-03-05", "Hydro-Québec", "Facture", "80.00", "CAD", "Bills", "hydro-2024.pdf"]]


def test_a_year_with_nothing_is_the_header_alone_and_a_document_with_no_date_is_in_no_year(api, filed):
    assert len(rows(api, "year=2023")) == 1
    assert not any("nodate.pdf" in line for year in ("2024", "2025", "2000") for line in rows(api, f"year={year}"))


def test_the_totals_add_up_the_amounts_by_company_type_and_currency(api, filed, settings):
    library = settings.DOCFLOW.path("library_root")
    for n, amount in enumerate(["10.10", "20.20"]):
        Item.objects.create(source_path=f"x{n}", sha256=f"{n + 9:064x}", state=Item.APPROVED, engine_status="auto",
                            result_path=str(library / "Bills" / f"more{n}.pdf"),
                            analysis={"company": "Hydro-Québec", "document_type": "Facture", "date": f"2025-0{n + 1}-10",
                                      "amount": amount, "currency": "CAD"})
    Item.objects.create(source_path="no-amount", sha256=f"{99:064x}", state=Item.APPROVED, engine_status="auto",
                        result_path=str(library / "Bills" / "none.pdf"),
                        analysis={"company": "Hydro-Québec", "document_type": "Facture", "date": "2025-05-05"})
    assert rows(api, "year=2025&layout=totals") == [
        ["company", "type", "currency", "documents", "total"],
        ["Garage Tremblay", "Entretien", "CAD", "1", "1200.50"],
        ["Hydro-Québec", "Facture", "", "1", ""],            # the document with no amount: counted, adds nothing, no currency
        ["Hydro-Québec", "Facture", "CAD", "3", "189.28"]]   # 158.98 + 10.10 + 20.20


def test_a_semicolon_file_is_offered_for_spreadsheets_set_to_french(api, filed):
    got = rows(api, "year=2025&delimiter=semicolon", ";")
    assert got[1][:3] == ["2025-02-01", "Garage Tremblay", "Entretien"] and len(got[1]) == 7


def test_a_name_that_a_spreadsheet_would_run_as_a_formula_is_written_as_text_but_a_negative_amount_stays_a_number(api, filed, settings):
    library = settings.DOCFLOW.path("library_root")
    Item.objects.create(source_path="evil", sha256=f"{77:064x}", state=Item.APPROVED, engine_status="auto",
                        result_path=str(library / "Bills" / "=cmd.pdf"),
                        analysis={"company": '=HYPERLINK("http://x")', "document_type": "+1", "date": "2025-01-01", "amount": "-5.00",
                                  "currency": "CAD"})
    line = rows(api, "year=2025")[1]
    assert line == ["2025-01-01", "'=HYPERLINK(\"http://x\")", "'+1", "-5.00", "CAD", "Bills", "'=cmd.pdf"]


def test_only_filed_documents_of_the_library_are_in_it(api, filed, settings):
    library = settings.DOCFLOW.path("library_root")
    Item.objects.create(source_path="p", sha256=f"{5:064x}", state=Item.PENDING, engine_status="auto",
                        analysis={"company": "Pending", "document_type": "Facture", "date": "2025-03-03", "amount": "1"})
    Item.objects.create(source_path="q", sha256=f"{6:064x}", state=Item.APPROVED, engine_status="duplicate", result_path="/elsewhere/q.pdf",
                        analysis={"company": "Elsewhere", "document_type": "Facture", "date": "2025-03-03", "amount": "1"})
    Item.objects.create(source_path="r", sha256=f"{7:064x}", state=Item.REMOVED, engine_status="auto", result_path=str(library / "r.pdf"),
                        analysis={"company": "Removed", "document_type": "Facture", "date": "2025-03-03", "amount": "1"})
    text = str(rows(api, "year=2025"))
    assert "Pending" not in text and "Elsewhere" not in text and "Removed" not in text


def test_the_download_has_its_own_name_and_type(api, filed):
    r = api.get("/api/statement?year=2025&layout=totals")
    assert r["Content-Type"].startswith("text/csv") and 'filename="statement-2025-totals.csv"' in r["Content-Disposition"]
    assert r["Content-Disposition"].startswith("attachment") and r["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("params,message", [("", "year must be"), ("year=25", "year must be"), ("year=abcd", "year must be"),
                                            ("year=1800", "year must be"), ("year=2025&layout=x", "layout must be one of"),
                                            ("year=2025&delimiter=tab", "delimiter must be one of")])
def test_a_bad_year_or_option_is_a_400_that_says_so(api, filed, params, message):
    r = api.get(f"/api/statement?{params}")
    assert r.status_code == 400 and message in r.json()["detail"]


def test_the_statement_needs_a_logged_in_user(sb):
    from rest_framework.test import APIClient
    assert APIClient().get("/api/statement?year=2025").status_code in (401, 403)


def test_the_search_screen_offers_the_download_as_a_link_to_the_statement():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "frontend" / "src"
    page = (src / "pages" / "Search.tsx").read_text(encoding="utf-8")
    assert "api.statementUrl(year, layout, lang === 'fr' ? 'semicolon' : 'comma')" in page and "validYear" in page
    assert "/api/statement?" in (src / "api.ts").read_text(encoding="utf-8")
