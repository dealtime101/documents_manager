"""DOC534.13: a type of document can say how many years it is kept (`retention_years`); the library lists what is older, and deleting it
asks first, goes to `_Trash` and is recorded in the history, where it can be undone."""
import hashlib
from datetime import date
from pathlib import Path

import pytest
from docflow import pipeline
from docflow.config import load_config
from test_api import api, sb  # noqa: F401  (fixtures: a sandbox and a signed-in client)
from triage import library as lib
from triage import services as s
from triage.models import Item

pytestmark = pytest.mark.django_db

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def config_with(tmp_path, yaml_text):
    (tmp_path / "cfg").mkdir(exist_ok=True)
    (tmp_path / "cfg" / "document_types.yaml").write_text(yaml_text, encoding="utf-8")
    return load_config(tmp_path / "cfg", sandbox=tmp_path / "sb")


def test_a_rule_gives_its_type_a_retention_and_the_longest_of_several_wins(tmp_path):
    c = config_with(tmp_path, "- {type: Facture, any: [facture], retention_years: 3}\n"
                              "- {type: FACTURE, any: [bill], retention_years: 7}\n"
                              "- {type: Avis, any: [avis]}\n")
    assert c.retention() == {"facture": 7}  # a type with no retention is simply absent: it never expires


@pytest.mark.parametrize("value", ['"7 ans"', "0", "-1", "101", "true", "7.5", "null", "[7]"])
def test_a_retention_that_is_not_a_number_of_years_stops_the_program_naming_the_rule(tmp_path, value):
    with pytest.raises(ValueError, match=r"retention_years of the rule 'Facture' must be a whole number of years from 1 to 100"):
        config_with(tmp_path, f"- {{type: Facture, any: [facture], retention_years: {value}}}\n")


def test_a_retention_on_a_rule_with_no_type_is_refused(tmp_path):
    with pytest.raises(ValueError, match="on a rule that has a type"):
        config_with(tmp_path, "- {any: [facture], retention_years: 7}\n")


def keep(settings, rel, *, kind="Facture", day="2000-01-01", state=Item.APPROVED, record=True):
    """A filed document: its file in the library, its item and (`record`) the row the history keeps for it."""
    f = settings.DOCFLOW.path("library_root") / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    content = f"%PDF-1.4 {rel}".encode()
    f.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    n = Item.objects.count()
    it = Item.objects.create(source_path=f"s{n}", sha256=sha, state=state, engine_status="auto", result_path=str(f),
                             analysis={"company": "Acme", "document_type": kind, "date": day})
    if record:
        with s.engine_db() as db:
            db.add_document(original_filename=f.name, final_filename=f.name, destination_path=str(f), sha256=sha, status="classified")
    return it, f


@pytest.fixture
def seven(settings, sb):  # noqa: F811
    settings.DOCFLOW.types = [{"type": "Facture", "any": ["facture"], "retention_years": 7}]


def names(today=date(2025, 11, 20)):
    return [d["name"] for d in lib.expired(today)["expired"]]


def test_nothing_expires_while_no_type_has_a_retention(sb, settings):  # noqa: F811
    keep(settings, "Old/a.pdf")
    assert lib.expired(date(2030, 1, 1)) == {"configured": False, "total": 0, "expired": []}


def test_a_document_expires_the_day_after_its_date_plus_the_years(seven, settings):
    keep(settings, "Tax/a.pdf", day="2018-11-20")
    assert names(date(2025, 11, 20)) == []              # dated 2018-11-20, kept 7 years: still kept on 2025-11-20
    assert names(date(2025, 11, 21)) == ["a.pdf"]
    got = lib.expired(date(2025, 11, 21))["expired"][0]
    assert got["expired_on"] == "2025-11-20" and got["years"] == 7 and got["path"] == "Tax/a.pdf" and got["date"] == "2018-11-20"


def test_29_february_is_kept_a_day_longer_not_shorter(sb, settings):  # noqa: F811
    settings.DOCFLOW.types = [{"type": "Facture", "retention_years": 1}]
    keep(settings, "a.pdf", day="2020-02-29")  # one year later there is no 29 February: the 1st of March
    assert names(date(2021, 3, 1)) == [] and names(date(2021, 3, 2)) == ["a.pdf"]


def test_only_what_can_be_judged_is_listed(seven, settings):
    keep(settings, "ok.pdf")
    keep(settings, "Other/type.pdf", kind="Releve")                      # a type with no retention
    keep(settings, "undated.pdf", day="XXXX")
    keep(settings, "partial.pdf", day="2000-XX-XX")
    keep(settings, "notadate.pdf", day="2000-13-45")                     # the shape of a date, not one
    keep(settings, "pending.pdf", state=Item.PENDING)
    keep(settings, "_Trash/trashed.pdf")                                 # already in the trash
    keep(settings, "ignored.pdf", state=Item.IGNORED)
    gone = keep(settings, "gone.pdf")[1]
    gone.unlink()                                                        # the file is no longer there
    outside = settings.DOCFLOW.path("library_root").parent / "elsewhere" / "out.pdf"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    Item.objects.create(source_path="o", sha256="f" * 64, state=Item.APPROVED, engine_status="auto", result_path=str(outside),
                        analysis={"company": "Acme", "document_type": "Facture", "date": "2000-01-01"})
    assert names() == ["ok.pdf"]


def test_the_type_is_matched_without_regard_to_case_and_the_oldest_comes_first(seven, settings):
    keep(settings, "new.pdf", kind="facture", day="2010-05-01")
    keep(settings, "old.pdf", kind="FACTURE", day="2001-05-01")
    assert names() == ["old.pdf", "new.pdf"]


def test_the_list_is_capped_and_says_how_many_there_are(seven, settings, monkeypatch):
    monkeypatch.setattr(lib, "EXPIRED_MAX", 2)
    for i in range(3):
        keep(settings, f"d{i}.pdf", day=f"200{i}-01-01")
    got = lib.expired(date(2025, 11, 20))
    assert got["total"] == 3 and [d["name"] for d in got["expired"]] == ["d0.pdf", "d1.pdf"]


def history(api):  # noqa: F811
    return api.get("/api/history").json()


def test_deleting_an_expired_document_goes_to_the_trash_and_is_recorded(seven, api, settings):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf")
    assert [d["id"] for d in api.get("/api/library/expired").json()["expired"]] == [it.id]
    r = api.post("/api/library/expired/delete", {"id": it.id}, format="json")
    assert r.status_code == 200 and r.json() == {"path": "_Trash/a.pdf", "name": "a.pdf"}
    root = settings.DOCFLOW.path("library_root")
    assert not f.exists() and (root / "_Trash" / "a.pdf").read_bytes() == b"%PDF-1.4 Tax/a.pdf"
    op = history(api)[0]
    assert op["kind"] == "expire" and op["src"] == str(f) and op["dst"] == str(root / "_Trash" / "a.pdf") and not op["undone"]
    assert api.get("/api/library/expired").json()["expired"] == []  # it is in the trash now, no longer a candidate


def test_the_deletion_can_be_undone_from_the_history_and_the_document_stays_filed(seven, api, settings):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf")
    api.post("/api/library/expired/delete", {"id": it.id}, format="json")
    op = history(api)[0]
    r = api.post(f"/api/history/{op['id']}/undo")
    assert r.status_code == 200 and r.json() == {"restored": str(f)}
    assert f.read_bytes() == b"%PDF-1.4 Tax/a.pdf"
    it.refresh_from_db()
    assert it.state == Item.APPROVED and it.result_path == str(f)  # not back in the queue: it was never unfiled
    assert history(api)[0]["undone"] == 1
    assert [d["id"] for d in api.get("/api/library/expired").json()["expired"]] == [it.id]  # and it is expired again


def test_a_file_changed_in_the_trash_is_not_put_back_by_the_undo(seven, api, settings):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf")
    api.post("/api/library/expired/delete", {"id": it.id}, format="json")
    (settings.DOCFLOW.path("library_root") / "_Trash" / "a.pdf").write_bytes(b"something else")
    r = api.post(f"/api/history/{history(api)[0]['id']}/undo")
    assert r.status_code == 400 and "changed since" in r.json()["detail"] and not f.exists()


def test_a_pdf_made_from_a_picture_is_put_back_too(seven, api, settings):  # noqa: F811
    """The history row of such a document holds the picture's hash, not the PDF's: the undo checks the PDF against what was put aside."""
    it, f = keep(settings, "Tax/a.pdf")
    Item.objects.filter(pk=it.id).update(sha256="a" * 64)
    with s.engine_db() as db:
        db.c.execute("UPDATE documents SET sha256 = ?", ("a" * 64,))
        db.c.commit()
    assert api.post("/api/library/expired/delete", {"id": it.id}, format="json").status_code == 200
    r = api.post(f"/api/history/{history(api)[0]['id']}/undo")
    assert r.status_code == 200 and f.exists()


@pytest.mark.parametrize("bad", [None, "1", True, 0, 99999, [1], {"id": 1}])
def test_the_server_deletes_nothing_that_is_not_an_expired_document(seven, api, settings, bad):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf", day="2090-01-01")  # not past its retention
    keep(settings, "Tax/b.pdf")                            # one that is: id 1 could be it
    for body in ({"id": bad}, {"id": it.id}):
        r = api.post("/api/library/expired/delete", body, format="json")
        assert r.status_code == 400 and r.json()["detail"] == "this document is not past its retention"
    assert f.exists() and history(api) == []


def test_without_a_row_in_the_history_nothing_is_deleted(seven, api, settings):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf", record=False)
    r = api.post("/api/library/expired/delete", {"id": it.id}, format="json")
    assert r.status_code == 400 and "could not be recorded" in r.json()["detail"]
    assert f.exists() and not (settings.DOCFLOW.path("library_root") / "_Trash").exists()


def test_a_deletion_that_cannot_be_recorded_puts_the_document_back(seven, api, settings, monkeypatch):  # noqa: F811
    it, f = keep(settings, "Tax/a.pdf")

    def refuse(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pipeline.DB, "add_op", refuse)
    with pytest.raises(OSError, match="disk full"):
        lib.delete_expired(it.id)
    assert f.read_bytes() == b"%PDF-1.4 Tax/a.pdf"
    it.refresh_from_db()
    assert it.result_path == str(f)  # the link follows the file back


def test_the_list_and_the_deletion_need_a_logged_in_user(sb):  # noqa: F811
    from rest_framework.test import APIClient
    for method, url in (("get", "/api/library/expired"), ("post", "/api/library/expired/delete")):
        assert getattr(APIClient(), method)(url).status_code in (401, 403)


def test_the_page_lists_asks_before_deleting_and_the_history_names_the_operation():
    api_ts = (SRC / "api.ts").read_text(encoding="utf-8")
    assert "'/api/library/expired'" in api_ts and "'/api/library/expired/delete'" in api_ts
    card = (SRC / "components" / "ExpiredDocuments.tsx").read_text(encoding="utf-8")
    assert "setAsking(d.id)" in card and "void remove(d.id, d.name)" in card  # the button asks; only the confirmation deletes
    assert "if (busy) return" in card
    assert "<ExpiredDocuments />" in (SRC / "pages" / "Library.tsx").read_text(encoding="utf-8")
    assert "expire: 'op.expire'" in (SRC / "ops.ts").read_text(encoding="utf-8")
