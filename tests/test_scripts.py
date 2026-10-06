"""Tests for the helper scripts in scripts/ (measurement tools, not part of the application)."""
import importlib.util
import sys
from pathlib import Path

import pymupdf
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    if str(SCRIPTS) not in sys.path:  # as when a script runs: its own folder is on the path, so scripts can import each other
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None, name
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)


def test_the_sandbox_amazon_invoice_adds_up():
    """A sandbox sample is a test input: a total that is not the sum of its lines would mislead any amount check."""
    import re
    from decimal import Decimal
    lines = load_script("make_sandbox").SAMPLES["amazon_order.pdf"]
    item = next(ln for ln in lines if ln.startswith("Friskies"))
    price, *taxes_and_total = [Decimal(m) for m in re.findall(r"\$(\d+\.\d\d)", item)]
    *taxes, line_total = taxes_and_total
    assert price + sum(taxes) == line_total                              # unit price + the three tax columns
    assert lines[-1] == f"Total ${line_total}"                           # and the invoice total is that line
    header = next(ln for ln in lines if ln.startswith("Description"))
    labels = ["Unit price", "Discount", "GST", "QST", "Total"]            # one label per money column, in the same order
    assert [header.index(x) for x in labels] == sorted(header.index(x) for x in labels)
    assert len(re.findall(r"\$(\d+\.\d\d)", item)) == len(labels)


def test_the_sandbox_samples_are_accented_like_real_french_documents_and_still_classify(tmp_path):
    from decimal import Decimal

    from docflow.analyze import RuleBasedAnalyzer
    from docflow.config import load_config
    from docflow.extract import extract_text
    module = load_script("make_sandbox")
    cfg = load_config(sandbox=tmp_path / "sb")
    texts = {}
    for name, lines in module.SAMPLES.items():
        pdf = tmp_path / name
        module.make(pdf, lines)
        texts[name] = extract_text(pdf, cfg.settings.get("ocr")).text
    for accented in ("Hydro-Québec", "électricité", "Numéro", "présente", "égaux", "santé", "Chère"):
        assert any(accented in t for t in texts.values()), accented      # the accents survive the PDF round trip
    an = RuleBasedAnalyzer(cfg)
    hydro = an.analyze(texts["hydro_bill_oct.pdf"])
    assert (hydro.company, hydro.document_type, hydro.date, hydro.amount) == (
        "Hydro-Quebec", "FactureElectricite", "2025-10-07", Decimal("158.98"))   # names are stored without accents
    assert an.analyze(texts["hydro_equal_payments.pdf"]).document_type == "FactureElectriciteMVE"
    assert an.analyze(texts["blue_cross_card.pdf"]).company == "CroixBleueMedavie"


def test_make_sandbox_without_a_folder_prints_the_usage_not_a_traceback(tmp_path):
    import subprocess
    import sys
    script = str(SCRIPTS / "make_sandbox.py")
    bare = subprocess.run([sys.executable, script], capture_output=True, text=True, cwd=tmp_path)
    assert bare.returncode == 2 and "usage:" in bare.stderr and "FOLDER" in bare.stderr
    assert "Traceback" not in bare.stderr and "IndexError" not in bare.stderr
    assert list(tmp_path.iterdir()) == []                                # and nothing was created behind the error
    ok = subprocess.run([sys.executable, script, str(tmp_path / "sb")], capture_output=True, text=True)
    assert ok.returncode == 0 and "6 sample PDFs" in ok.stdout
    assert len(list((tmp_path / "sb" / "inbox").glob("*.pdf"))) == 6     # five samples + the exact duplicate


def test_make_sandbox_counts_the_samples_it_wrote_not_every_pdf_found_in_the_inbox(tmp_path):
    import subprocess
    import sys
    inbox = tmp_path / "sb" / "inbox"
    inbox.mkdir(parents=True)
    make_pdf(inbox / "mine-from-before.pdf", "a document already there")
    make_pdf(inbox / "another.PDF", "and another one")
    script = str(SCRIPTS / "make_sandbox.py")
    first = subprocess.run([sys.executable, script, str(tmp_path / "sb")], capture_output=True, text=True)
    assert first.returncode == 0 and first.stdout.startswith("6 sample PDFs ")          # 5 samples + the exact duplicate, not 8
    again = subprocess.run([sys.executable, script, str(tmp_path / "sb")], capture_output=True, text=True)
    assert again.stdout.startswith("6 sample PDFs ")                                     # a second run rewrites the same six
    assert len(list(inbox.iterdir())) == 8                                                # (the two others are untouched)


def test_build_corpus_includes_upper_case_pdf_extensions(tmp_path, capsys):
    root = tmp_path / "archive"
    root.mkdir()
    make_pdf(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.PDF", "Hydro-Quebec facture")
    make_pdf(root / "2025-10-08 - Telus - ReleveMobilite.pdf", "Telus releve")
    load_script("build_corpus").main(root, tmp_path / "cache")
    assert "2 PDFs following the standard" in capsys.readouterr().out


def test_build_corpus_does_not_reuse_the_text_of_a_pdf_replaced_at_the_same_path(tmp_path):
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    pdf = root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    build = load_script("build_corpus")
    make_pdf(pdf, "FIRST version of the document, long enough to be read")
    build.main(root, cache)
    assert "FIRST" in next(cache.glob("*.txt")).read_text()
    pdf.unlink()
    make_pdf(pdf, "SECOND version replaced at the very same path")                      # same name, same entry, other bytes
    build.main(root, cache)
    texts = [p.read_text() for p in cache.glob("*.txt")]
    assert len(texts) == 1 and "SECOND" in texts[0] and "FIRST" not in texts[0]         # the cache followed the file


def test_build_corpus_keeps_the_message_of_an_extraction_error_and_names_the_failing_file(tmp_path, capsys):
    import json
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    (root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf").write_bytes(b"this is not a pdf")
    load_script("build_corpus").main(root, cache)
    (entry,) = json.loads((cache / "index.json").read_text())
    assert entry["error"] == "PdfiumError"                                            # the type stays: readers test "error" in r
    assert "Failed to load document" in entry["message"]                                 # and the real cause is now kept too
    err = capsys.readouterr().err
    assert "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf" in err and "PdfiumError" in err


def test_build_corpus_survives_a_file_whose_error_is_not_a_runtime_error_and_still_reads_the_others(tmp_path, capsys):
    """PDFium's PdfiumError (a PNG renamed .pdf) is not a ValueError or an OSError: a narrow `except` would end the whole run."""
    import json
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    (root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    make_pdf(root / "2025-10-08 - Telus - ReleveMobilite.pdf", "Telus releve du mois, texte suffisant pour etre lu")
    assert load_script("build_corpus").main(root, cache) == 1                                # done, one entry failed (DOC474.90)
    rows = {r["name"]: r for r in json.loads((cache / "index.json").read_text())}
    assert rows["2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"]["error"] == "PdfiumError"
    assert "error" not in rows["2025-10-08 - Telus - ReleveMobilite.pdf"]                 # the next file was still read
    assert "PdfiumError" in capsys.readouterr().err


def test_build_corpus_gives_every_file_an_index_entry_whatever_happens_to_it(tmp_path, capsys):
    import json
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    make_pdf(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf", "Hydro-Quebec facture, assez de texte pour etre lu")
    (root / "2025-10-08 - Telus - ReleveMobilite.pdf").write_bytes(b"not a pdf")
    (root / "2025-10-09 - Bell - Facture.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    build = load_script("build_corpus")
    assert build.main(root, cache) == 1                                                       # two entries failed (DOC474.90)
    rows = json.loads((cache / "index.json").read_text())
    assert len(rows) == 3 and sum("error" in r for r in rows) == 2                    # none is left out, the two failures say so
    assert "done: 3 entries, 2 errors" in capsys.readouterr().out
    assert build.one.__annotations__["return"] is dict                                # and the type says it (never None)


def test_build_corpus_names_its_entries_with_sha256_and_adopts_a_cache_made_under_the_old_names(tmp_path):
    """The entry name was a SHA-1 of the relative path (flagged, though only a file name is derived from it). It is a SHA-256
    now, and the slow part, the extracted texts, is renamed to the new names instead of being extracted again."""
    import hashlib
    import json
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    cache.mkdir()
    pdf = root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf, "Hydro-Quebec facture d'electricite, assez de texte pour etre lu")
    build = load_script("build_corpus")
    old = hashlib.new("sha1", pdf.name.encode()).hexdigest()[:16]          # what the previous version wrote
    stamp = build.extraction_fingerprint(pdf, build.load_config().settings["ocr"])
    (cache / f"{old}.txt").write_text("TEXT EXTRACTED BY THE PREVIOUS VERSION", encoding="utf-8")
    (cache / f"{old}.txt.key").write_text(stamp, encoding="utf-8")
    (cache / "index.json").write_text(json.dumps([{"key": old, "rel": pdf.name, "name": pdf.name}]), encoding="utf-8")
    calls = []
    real = build.extract_text
    build.extract_text = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    assert build.main(root, cache) == 0
    new = hashlib.sha256(pdf.name.encode()).hexdigest()[:16]
    assert [r["key"] for r in json.loads((cache / "index.json").read_text())] == [new]
    assert (cache / f"{new}.txt").read_text(encoding="utf-8") == "TEXT EXTRACTED BY THE PREVIOUS VERSION"
    assert not (cache / f"{old}.txt").exists() and not (cache / f"{old}.txt.key").exists()   # moved, not copied
    assert calls == []                                                                        # and nothing was extracted again
    # and an interrupted adoption leaves a consistent cache: the index is rewritten with the files
    (cache / f"{new}.txt").replace(cache / f"{old}.txt")
    (cache / f"{new}.txt.key").replace(cache / f"{old}.txt.key")
    (cache / "index.json").write_text(json.dumps([{"key": old, "rel": pdf.name, "name": pdf.name}]), encoding="utf-8")
    assert build.adopt_old_names(cache) == 1
    assert [r["key"] for r in json.loads((cache / "index.json").read_text())] == [new] and (cache / f"{new}.txt").exists()
    assert build.adopt_old_names(cache) == 0                                                  # idempotent


def test_build_corpus_without_arguments_prints_the_usage_and_keeps_its_command_line(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS.parent / "backend")}
    script = str(SCRIPTS / "build_corpus.py")
    bare = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
    assert bare.returncode == 2 and "usage:" in bare.stderr and "FOLDER" in bare.stderr and "CACHE" in bare.stderr
    assert "Traceback" not in bare.stderr and "IndexError" not in bare.stderr
    one = subprocess.run([sys.executable, script, str(tmp_path)], capture_output=True, text=True, env=env)
    assert one.returncode == 2 and "usage:" in one.stderr                             # the second path is needed too
    root = tmp_path / "archive"
    root.mkdir()
    make_pdf(root / "2025-10-08 - Telus - ReleveMobilite.pdf", "Telus releve")
    for extra in ([], ["--fresh"]):                                                    # the documented forms still work
        ok = subprocess.run([sys.executable, script, str(root), str(tmp_path / "cache"), *extra],
                            capture_output=True, text=True, env=env)
        assert ok.returncode == 0 and "1 PDFs following the standard" in ok.stdout


def test_discover_finds_pdf_files_whatever_the_case_of_the_extension(tmp_path, capsys):
    make_pdf(tmp_path / "scanner_output.PDF", "Garage Tremblay et Fils inconnu")      # scanners often write .PDF
    make_pdf(tmp_path / "Mixed.Pdf", "Boutique Lavoie Inc commande")
    load_script("discover").main(tmp_path)
    assert "2 PDFs" in capsys.readouterr().out


def test_discover_counts_a_pdf_with_no_usable_line_in_its_own_group(tmp_path, capsys):
    make_pdf(tmp_path / "digits_only.pdf", "12 34 56 78")          # readable, but no line with real words
    make_pdf(tmp_path / "words.pdf", "Garage Tremblay et Fils inconnu")
    load_script("discover").main(tmp_path)
    out = capsys.readouterr().out
    assert "without company: 2" in out and "[no text]" in out     # both are counted and both are visible


def test_discover_does_not_count_an_unreadable_pdf_as_one_without_a_company(tmp_path, capsys):
    (tmp_path / "broken.pdf").write_bytes(b"this is not a pdf")                     # we cannot know its company at all
    make_pdf(tmp_path / "digits_only.pdf", "12 34 56 78")                           # readable: really without a company
    make_pdf(tmp_path / "words.pdf", "Garage Tremblay et Fils inconnu")
    make_pdf(tmp_path / "known.pdf", "Hydro-Quebec facture d'electricite")           # recognised: neither
    load_script("discover").main(tmp_path)
    out = capsys.readouterr().out
    assert "4 PDFs; without company: 2; unreadable: 1; groups: 2" in out             # two problems, two numbers
    assert "[unreadable]" in out and "[no text]" in out                              # and each still has its row


def test_discover_says_why_files_were_unreadable_so_a_general_failure_is_not_taken_for_corrupt_pdfs(tmp_path, capsys):
    make_pdf(tmp_path / "a.pdf", "Garage Tremblay et Fils inconnu")
    make_pdf(tmp_path / "b.pdf", "Boutique Lavoie Inc commande")
    discover = load_script("discover")

    def no_tesseract(path, ocr):
        raise RuntimeError("tesseract is not installed")

    discover.extract_text = no_tesseract                                             # a failure of the whole run
    discover.main(tmp_path)
    out = capsys.readouterr().out
    assert "unreadable: 2" in out
    assert "RuntimeError: tesseract is not installed" in out and "2" in out.split("RuntimeError")[0].splitlines()[-1]


def test_discover_says_how_many_groups_it_does_not_show(tmp_path, capsys):
    for i, word in enumerate(["Garage Tremblay", "Boutique Lavoie", "Clinique Roy", "Atelier Gagnon", "Librairie Pelletier"]):
        make_pdf(tmp_path / f"{i}.pdf", f"{word} et Fils inconnu")
    discover = load_script("discover")
    discover.main(tmp_path, limit=3)
    out = capsys.readouterr().out
    assert "groups: 5" in out and "... 2 more groups (2 files) not shown" in out    # the summary and the list agree
    discover.main(tmp_path, limit=5)
    assert "not shown" not in capsys.readouterr().out                                 # nothing hidden: nothing said


def test_discover_takes_the_group_limit_from_the_command_line(tmp_path):
    import os
    import subprocess
    import sys
    for i, word in enumerate(["Garage Tremblay", "Boutique Lavoie", "Clinique Roy"]):
        make_pdf(tmp_path / f"{i}.pdf", f"{word} et Fils inconnu")
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS.parent / "backend")}
    run = subprocess.run([sys.executable, str(SCRIPTS / "discover.py"), str(tmp_path), "--limit", "1"],
                         capture_output=True, text=True, env=env)
    assert run.returncode == 0 and "... 2 more groups (2 files) not shown" in run.stdout
    bare = subprocess.run([sys.executable, str(SCRIPTS / "discover.py")], capture_output=True, text=True, env=env)
    assert bare.returncode == 2 and "usage:" in bare.stderr


def test_discover_refuses_a_folder_that_does_not_exist_instead_of_reporting_zero_pdfs(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS.parent / "backend")}
    typo = tmp_path / "scanz"
    run = subprocess.run([sys.executable, str(SCRIPTS / "discover.py"), str(typo)], capture_output=True, text=True, env=env)
    assert run.returncode == 2 and "not a folder" in run.stderr and str(typo) in run.stderr and run.stdout == ""
    a_file = tmp_path / "x.pdf"
    a_file.write_bytes(b"x")
    run = subprocess.run([sys.executable, str(SCRIPTS / "discover.py"), str(a_file)], capture_output=True, text=True, env=env)
    assert run.returncode == 2 and "not a folder" in run.stderr                       # a file is not a folder either


def test_discover_survives_a_file_whose_error_is_not_a_runtime_error_and_still_groups_the_others(tmp_path, capsys):
    """PDFium's PdfiumError (a PNG renamed .pdf) is not a ValueError or an OSError: a narrow `except` would end the whole run."""
    (tmp_path / "disguised.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    make_pdf(tmp_path / "words.pdf", "Garage Tremblay et Fils inconnu")
    load_script("discover").main(tmp_path)
    out = capsys.readouterr().out
    assert "2 PDFs; without company: 1; unreadable: 1; groups: 1" in out                  # the second file was still read
    assert "PdfiumError" in out and "(e.g. disguised.pdf)" in out                        # and the cause of the first is shown


def test_discover_names_each_example_with_its_folder_so_same_named_files_can_be_told_apart(tmp_path, capsys):
    (tmp_path / "taxes").mkdir()
    (tmp_path / "garage").mkdir()
    make_pdf(tmp_path / "taxes" / "scan.pdf", "Cabinet Gagnon et Fils inconnu")
    make_pdf(tmp_path / "garage" / "scan.pdf", "Garage Tremblay et Fils inconnu")      # same file name, other folder
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "scan.pdf").write_bytes(b"this is not a pdf")
    load_script("discover").main(tmp_path)
    out = capsys.readouterr().out
    assert "e.g.: taxes/scan.pdf" in out and "e.g.: garage/scan.pdf" in out        # the folder is part of the example
    assert "(e.g. broken/scan.pdf)" in out                                         # also for an unreadable file
    long_dir = tmp_path / ("d" * 60)
    long_dir.mkdir()
    make_pdf(long_dir / "x.pdf", "Atelier Pelletier et Fils inconnu")
    load_script("discover").main(tmp_path)
    assert f"{'d' * 60}/x.pdf" in capsys.readouterr().out                          # never cut off: the whole path is printed


def test_compare_skips_and_counts_a_badly_named_file_instead_of_crashing(tmp_path, capsys):
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "no-double-underscore.pdf", "Hydro-Quebec facture d'electricite")   # not named <n>__<real name>
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    load_script("compare").main(tmp_path)
    out = capsys.readouterr().out
    assert "skipped 1" in out and "exact full date" in out


def test_compare_without_arguments_prints_the_usage_and_keeps_its_command_line(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS.parent / "backend")}
    script = str(SCRIPTS / "compare.py")
    bare = subprocess.run([sys.executable, script], capture_output=True, text=True, env=env)
    assert bare.returncode == 2 and "usage:" in bare.stderr and "SAMPLE_FOLDER" in bare.stderr
    assert "Traceback" not in bare.stderr and "IndexError" not in bare.stderr
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    for extra in ([], ["--fresh"]):                                                    # the documented forms still work
        ok = subprocess.run([sys.executable, script, str(tmp_path), *extra], capture_output=True, text=True, env=env)
        assert ok.returncode == 0 and "exact full date" in ok.stdout
    missing = subprocess.run([sys.executable, script, str(tmp_path / "typo")], capture_output=True, text=True, env=env)
    assert missing.returncode == 2 and "no std/ folder" in missing.stdout             # the existing refusal is kept


def test_compare_names_an_extraction_failure_of_any_class_and_still_reads_the_other_samples(tmp_path, capsys):
    """PDFium's PdfiumError (a PNG renamed .pdf) is not a ValueError or an OSError: the broad catch is what keeps the run going."""
    std = tmp_path / "std"
    std.mkdir()
    (std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    make_pdf(std / "001__2025-10-08 - Telus - ReleveMobilite.pdf", "Telus releve du mois, texte suffisant pour etre lu")
    assert load_script("compare").main(tmp_path) == 0
    out = capsys.readouterr().out
    assert "'error': 1, 'text': 1" in out                                                  # one failed, one read
    assert "EXTRACTION ERRORS (1" in out and "PdfiumError:" in out and "FactureElectricite" in out   # named, with its cause
    assert "company (config)     : 1/2 = 50%" in out                                       # the failure counts as a miss, not as absent


def test_compare_works_on_a_read_only_sample_folder_and_says_it_could_not_save_the_texts(tmp_path, capsys):
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    std.chmod(0o555)                                                       # the ground-truth folder is protected
    try:
        load_script("compare").main(tmp_path)
    finally:
        std.chmod(0o755)                                                   # so that pytest can clean up
    out = capsys.readouterr().out
    assert "exact full date      : 1/1 = 100%" in out                     # the measurement itself is unaffected
    assert "could not be saved" in out and not list(std.glob("*.txt"))     # and it says so, instead of crashing


def test_compare_never_leaves_a_half_written_text_that_a_later_run_would_trust(tmp_path, monkeypatch, capsys):
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    pdf_path = std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf_path, "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $ "
                       + "ligne de detail " * 20)
    compare.main(tmp_path)
    saved = pdf_path.with_suffix(".txt")
    complete = saved.read_text()
    real_write = Path.write_text

    def dies_halfway(self, data, *a, **k):
        if ".txt" in self.name and not self.name.endswith(".key"):
            real_write(self, data[: len(data) // 2], *a, **k)            # half the text reaches the disk, then the crash
            raise OSError("disk full")
        return real_write(self, data, *a, **k)

    monkeypatch.setattr(Path, "write_text", dies_halfway)
    compare.main(tmp_path, fresh=True)                                  # an interrupted rebuild: not fatal, only not saved
    monkeypatch.setattr(Path, "write_text", real_write)
    compare.main(tmp_path)
    assert saved.read_text() == complete                                # never the half text with a still-valid key
    assert sorted(p.name for p in std.iterdir() if p.suffix != ".pdf") == sorted([saved.name, saved.name + ".key"])  # no temp
    capsys.readouterr()


def test_compare_includes_pdf_files_whatever_the_case_of_the_extension(tmp_path, capsys):
    std = tmp_path / "std"
    std.mkdir()
    text = "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $"
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf", text)
    make_pdf(std / "001__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.PDF", text)      # scanners write .PDF
    make_pdf(std / "002__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.Pdf", text)
    (std / "003__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.txt").write_text("not a pdf")
    load_script("compare").main(tmp_path)
    out = capsys.readouterr().out
    assert "exact full date      : 3/3 = 100%" in out and "extraction: {'text': 3}" in out   # all three, not the single .pdf


def test_compare_says_so_when_the_sample_folder_has_no_std_folder(tmp_path, capsys):
    compare = load_script("compare")
    assert compare.main(tmp_path) == 2                                      # not a traceback, not a quiet "0 files"
    assert compare.main(tmp_path / "nowhere") == 2
    out = capsys.readouterr().out
    assert out.count("ERROR") == 2 and "std" in out


def test_compare_names_the_files_whose_extraction_failed_and_why(tmp_path, capsys):
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    (std / "001__2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf").write_bytes(b"not a pdf at all")
    (std / "002__2025-10-09 - Hydro-Quebec - FactureElectricite - 30.00$.pdf").write_bytes(b"")
    load_script("compare").main(tmp_path)
    out = capsys.readouterr().out
    assert "EXTRACTION ERRORS (2," in out
    section = out.split("EXTRACTION ERRORS (2,")[1]
    assert "2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf" in section      # which file...
    assert "2025-10-09 - Hydro-Quebec - FactureElectricite - 30.00$.pdf" in section
    assert "PdfiumError" in section or "Error" in section                              # ...and why (the exception type)
    assert "extraction: {'text': 1, 'error': 2}" in out                                    # the counter is still there


def test_compare_statistics_keep_the_real_extraction_method_even_for_a_saved_text(tmp_path, capsys):
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    compare.main(tmp_path)
    first = capsys.readouterr().out
    compare.main(tmp_path)                                               # the second run reads the saved text
    second = capsys.readouterr().out
    assert "extraction: {'text': 1}" in first
    assert "extraction: {'text': 1}" in second and "cache" not in second     # not "{'cache': 1}": that hides text vs OCR


def test_compare_does_not_save_a_text_from_an_extraction_that_lost_pages(tmp_path, monkeypatch, capsys):
    from docflow.extract import Extracted
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    pdf_path = std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf_path, "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    real = compare.extract_text
    monkeypatch.setattr(compare, "extract_text", lambda *a, **k: Extracted("", "ocr_unavailable", 1, missing_pages=1))
    compare.main(tmp_path)                                                # OCR failed this time: empty text, 1 page lost
    assert not pdf_path.with_suffix(".txt").exists()                      # a failure must not be remembered as the answer
    monkeypatch.setattr(compare, "extract_text", real)
    compare.main(tmp_path)
    assert "exact full date      : 1/1 = 100%" in capsys.readouterr().out.split("(rates below")[-1]   # the next run re-extracts


def test_compare_documentation_matches_what_it_does():
    doc = load_script("compare").__doc__
    assert "read-only" not in doc.lower() or "except" in doc.lower()       # it is not "read-only": it saves texts beside the samples
    assert ".txt" in doc


def test_compare_counts_documents_without_text_as_failures_in_every_rate(tmp_path, capsys):
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    pymupdf_doc = pymupdf.open()
    pymupdf_doc.new_page()                                              # a blank page: nothing to read
    pymupdf_doc.save(std / "001__2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf")
    (std / "002__2025-10-09 - Hydro-Quebec - FactureElectricite - 30.00$.pdf").write_bytes(b"not a pdf")  # extraction fails
    load_script("compare").main(tmp_path)
    out = capsys.readouterr().out
    assert "exact full date      : 1/3 = 33%" in out                    # not 1/1 = 100%
    assert "exact amount         : 1/3 = 33%" in out
    assert "company (config)     : 1/3 = 33%" in out


def test_compare_text_cache_follows_the_pdf_and_can_be_forced(tmp_path, monkeypatch, capsys):
    compare = load_script("compare")
    calls = []
    real = compare.extract_text
    monkeypatch.setattr(compare, "extract_text", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    std = tmp_path / "std"
    std.mkdir()
    pdf = std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf, "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    compare.main(tmp_path)
    compare.main(tmp_path)
    assert len(calls) == 1                                               # second run: cache still matches the PDF
    pdf.unlink()
    make_pdf(pdf, "Hydro-Quebec\nFacture d'electricite du 8 octobre 2025\nMontant de la presente facture : 20,00 $")
    compare.main(tmp_path)
    assert len(calls) == 2                                               # the PDF changed: stale text is not reused
    compare.main(tmp_path, fresh=True)
    assert len(calls) == 3                                               # forced fresh extraction
    capsys.readouterr()


def test_compare_cache_key_depends_on_the_pdf_the_ocr_settings_and_the_extractor(tmp_path, monkeypatch):
    compare = load_script("compare")
    a = tmp_path / "a.pdf"
    a.write_bytes(b"one")
    base = compare.cache_key(a, {"languages": "fra"})
    assert compare.cache_key(a, {"languages": "fra"}) == base
    assert compare.cache_key(a, {"languages": "fra+eng"}) != base        # OCR configuration
    a.write_bytes(b"two")
    assert compare.cache_key(a, {"languages": "fra"}) != base            # PDF content
    a.write_bytes(b"one")
    fake = tmp_path / "extract.py"
    fake.write_text("changed extractor")
    monkeypatch.setattr(compare.extractor, "__file__", str(fake))
    assert compare.cache_key(a, {"languages": "fra"}) != base            # extractor code


def test_build_corpus_text_cache_follows_the_pdf_at_the_same_path_and_can_be_forced(tmp_path, monkeypatch, capsys):
    corpus = load_script("build_corpus")
    calls = []
    real = corpus.extract_text
    monkeypatch.setattr(corpus, "extract_text", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    pdf = root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf, "Hydro-Quebec facture du 7 octobre 2025 montant 158,98 $")
    corpus.main(root, cache)
    corpus.main(root, cache)
    assert len(calls) == 1                                          # unchanged PDF: the saved text is reused
    pdf.unlink()
    make_pdf(pdf, "Garage Tremblay entretien complet du vehicule total 80,00 $")   # another archive, same relative path
    corpus.main(root, cache)
    assert len(calls) == 2
    (key,) = [r["key"] for r in __import__("json").loads((cache / "index.json").read_text())]
    assert "Garage Tremblay" in (cache / f"{key}.txt").read_text()   # the new text, not the old PDF's
    corpus.main(root, cache, fresh=True)
    assert len(calls) == 3                                          # forced
    capsys.readouterr()


def test_build_corpus_refuses_a_bad_root_and_never_replaces_an_index_with_an_empty_one(tmp_path, capsys):
    corpus = load_script("build_corpus")
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    make_pdf(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf", "Hydro-Quebec facture")
    assert corpus.main(root, cache) == 0
    index = (cache / "index.json").read_text()
    assert corpus.main(tmp_path / "typo-in-the-path", cache) == 2                  # does not exist
    assert corpus.main(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf", cache) == 2   # not a folder
    empty = tmp_path / "empty-archive"
    empty.mkdir()
    assert corpus.main(empty, cache) == 2                                          # valid folder, nothing found, index exists
    assert (cache / "index.json").read_text() == index                             # the existing index was never touched
    assert capsys.readouterr().err.count("ERROR") == 3                             # on stderr, with the per-file errors (DOC474.89)
    fresh_cache = tmp_path / "other-cache"
    assert corpus.main(tmp_path / "typo-in-the-path", fresh_cache) == 2 and not fresh_cache.exists()   # nothing created
    assert corpus.main(empty, fresh_cache) == 0                                    # first run on an empty archive: fine


def test_an_interrupted_write_never_leaves_a_partial_text_that_looks_valid(tmp_path, monkeypatch, capsys):
    import json
    corpus = load_script("build_corpus")
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    make_pdf(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec facture du 7 octobre 2025 montant 158,98 $ " + "ligne de detail " * 20)
    corpus.main(root, cache)
    (key,) = [r["key"] for r in json.loads((cache / "index.json").read_text())]
    complete = (cache / f"{key}.txt").read_text()

    real_write = Path.write_text

    def dies_halfway(self, data, *a, **k):
        if "txt" in self.name and not self.name.endswith(".key"):
            real_write(self, data[: len(data) // 2], *a, **k)      # half of the text reaches the disk, then the crash
            raise OSError("disk full")
        return real_write(self, data, *a, **k)

    monkeypatch.setattr(Path, "write_text", dies_halfway)
    corpus.main(root, cache, fresh=True)                            # interrupted rebuild
    monkeypatch.setattr(Path, "write_text", real_write)
    corpus.main(root, cache)                                        # next run
    assert (cache / f"{key}.txt").read_text() == complete           # the complete text, never the half one
    assert sorted(p.name for p in cache.iterdir()) == sorted([f"{key}.txt", f"{key}.txt.key", "index.json"])  # no leftovers
    capsys.readouterr()


@pytest.mark.parametrize("argv", [[], ["nope", "x"], ["score"], ["mine", "only-a-cache"], ["score", "a", "b"]])
def test_benchmark_usage_errors_print_the_usage_not_a_traceback(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        load_script("benchmark").main(argv)
    assert stop.value.code == 2                                         # argparse's code for "wrong command line"
    err = capsys.readouterr().err
    assert "usage:" in err and "Traceback" not in err


def test_benchmark_counts_the_documents_it_leaves_out_by_reason(tmp_path, capsys):
    import json
    cache = tmp_path / "cache"
    cache.mkdir()
    good = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    (cache / "k1.txt").write_text("Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    (cache / "k4.txt").write_text("some text")
    index = [{"key": "k1", "rel": good, "name": good},
             {"key": "k2", "rel": "b.pdf", "name": "2025-10-08 - Telus - ReleveMobilite.pdf", "error": "FileDataError", "message": "x"},
             {"key": "k3", "rel": "c.pdf", "name": "2025-10-09 - Bell - Facture.pdf"},                  # its text file is missing
             {"key": "k4", "rel": "d.pdf", "name": "2025-10-10 - OnlyTwoParts.pdf"}]                    # not <date> - <company> - <type>
    (cache / "index.json").write_text(json.dumps(index))
    assert load_script("benchmark").main(["score", str(cache)]) == 0
    out = capsys.readouterr().out
    assert "1 documents" in out                                                    # the scored ones, as before
    assert "4 index entries, 1 scored; left out: 1 extraction error, 1 text missing, 1 name not in the standard form" in out
    assert "rates cover the scored documents only" in out


def test_the_company_alias_table_holds_only_real_merges():
    benchmark = load_script("benchmark")
    assert [k for k, v in benchmark.SAME.items() if k == v] == []                       # an alias onto itself merges nothing
    assert [v for v in benchmark.SAME.values() if v in benchmark.SAME] == []            # no chain: the target is a final name
    import re
    assert all(re.fullmatch(r"[a-z0-9]+", k) and re.fullmatch(r"[a-z0-9]+", v) for k, v in benchmark.SAME.items())   # written normalised
    # "Acme Corp" and "AcmeCorp" need no alias: the normalisation alone makes them one key
    assert benchmark.key("Acme Corp") == benchmark.key("AcmeCorp")
    assert benchmark.key("Desjardins") != benchmark.key("DesjardinsAssurances")         # two companies, kept apart


def test_mine_groups_spelling_variants_of_a_type_so_they_do_not_count_against_each_other(tmp_path, capsys):
    import json
    cache = tmp_path / "cache"
    cache.mkdir()
    index = []
    for i, (label, text) in enumerate([("ReleveVisa", "alpha bravo charlie delta"), ("ReleveVisa", "alpha bravo charlie delta"),
                                       ("Visa", "alpha bravo charlie delta"), ("Visa", "alpha bravo charlie delta"),   # same type, other spelling
                                       ("Facture", "zulu yankee xray whiskey"), ("Facture", "zulu yankee xray whiskey")]):
        name = f"2025-01-0{i + 1} - Desjardins - {label}.pdf"
        index.append({"key": f"k{i}", "rel": name, "name": name})
        (cache / f"k{i}.txt").write_text(text)
    (cache / "index.json").write_text(json.dumps(index))
    load_script("benchmark").main(["mine", str(cache), "Desjardins"])
    out = capsys.readouterr().out
    assert "Desjardins: 6 documents, 2 types" in out                            # ReleveVisa and Visa are ONE type
    line = next(ln for ln in out.splitlines() if "(4)" in ln)
    assert "alpha" in line and "bravo" in line                                  # their words are no longer each other's counter-examples
    assert "(2)" in out and "zulu" in out                                       # and the other type is untouched


def test_benchmark_says_what_to_do_when_the_corpus_is_missing(tmp_path, capsys):
    benchmark = load_script("benchmark")
    assert benchmark.main(["score", str(tmp_path / "no-such-corpus")]) == 2
    assert benchmark.main(["mine", str(tmp_path), "Hydro-Quebec"]) == 2            # a folder without an index.json
    out = capsys.readouterr().out
    assert out.count("ERROR") == 2 and "build_corpus.py" in out


def test_benchmark_subcommands_still_run(tmp_path, capsys):
    import json
    benchmark = load_script("benchmark")
    (tmp_path / "k1.txt").write_text("Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $",
                                     encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": "k1", "name": "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"}]),
                                         encoding="utf-8")
    assert benchmark.main(["score", str(tmp_path)]) == 0 and "1 documents" in capsys.readouterr().out
    assert benchmark.main(["mine", str(tmp_path), "Hydro-Quebec"]) == 0 and "Hydro-Quebec: 1 documents" in capsys.readouterr().out


def test_benchmark_measures_the_engines_current_thresholds_not_a_copy_of_them(tmp_path, monkeypatch, capsys):
    import json

    from docflow.config import load_config
    benchmark = load_script("benchmark")
    (tmp_path / "k1.txt").write_text("Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nNumero de facture : 123456789\n"
                                     "Montant de la presente facture : 158,98 $", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": "k1", "name": "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"}]),
                                         encoding="utf-8")

    def with_thresholds(auto, confirm):
        cfg = load_config()
        cfg.settings["thresholds"] = {"auto": auto, "confirm": confirm}
        monkeypatch.setattr(benchmark, "load_config", lambda: cfg)
        benchmark.score(tmp_path)
        return next(ln for ln in capsys.readouterr().out.splitlines() if "=> auto" in ln).strip()

    assert with_thresholds(0.95, 0.80) == "=> auto 1 | confirm 0 | manual 0"
    assert with_thresholds(0.99, 0.80) == "=> auto 0 | confirm 1 | manual 0"      # the engine would not file it automatically
    assert with_thresholds(0.99, 0.99) == "=> auto 0 | confirm 0 | manual 1"


@pytest.mark.parametrize("confidence,llm,named,expected", [
    (0.96, False, True, "auto"), (0.95, False, True, "auto"), (0.9499, False, True, "confirm"), (0.80, False, True, "confirm"),
    (0.7999, False, True, "manual"), (0.0, False, True, "manual"),
    (0.96, True, True, "confirm"),                      # a model's answer is never filed without a human
    (0.96, False, False, "manual"),                     # no file name could be built
])
def test_the_status_decision_is_one_function_of_the_configured_thresholds(confidence, llm, named, expected):
    from docflow.pipeline import status_for
    assert status_for(confidence, {"auto": 0.95, "confirm": 0.80}, used_llm=llm, has_name=named) == expected


def test_the_destination_decision_is_one_function_shared_by_the_engine_and_its_measurement(tmp_path):
    from docflow.analyze import Analysis
    from docflow.config import load_config
    from docflow.pipeline import DESTINATION_CONF, resolve_destination
    cfg = load_config(sandbox=tmp_path)
    ok = resolve_destination(cfg, Analysis(date="2025-10-07", company="Hydro-Quebec", document_type="FactureElectricite"))
    assert ok[0] == "Bills/Hydro-Québec/2025" and ok[1] == DESTINATION_CONF == 0.96 and ok[2] == []
    undated = resolve_destination(cfg, Analysis(date="XXXX", company="Hydro-Quebec", document_type="FactureElectricite"))
    assert undated[0] is None and undated[1] == 0.0 and "date is unknown" in undated[2][0]
    unknown = resolve_destination(cfg, Analysis(date="2025-10-07", company="Nobody", document_type="Whatever"))
    assert unknown == (None, 0.0, ["No destination rule."])


@pytest.mark.parametrize("part,expected", [
    ("158.98$", "158.98"), ("158,98 $", "158.98"), ("1 234,56 $", "1234.56"), ("1 234,56 $", "1234.56"),
    ("1,234.56$", "1234.56"), ("1.234,56 $", "1234.56"), ("12.50 CAD", "12.50"), ("1.12EUR", "1.12"), ("30.00 USD", "30.00"),
    ("-16.19$", "-16.19"), ("158.98", "158.98"),
    ("790.70Net", None), ("abc", None), ("2025", None), ("12.5", None), ("1,234", None), ("", None), ("Facture 40.00", None),
])
def test_benchmark_reads_the_amount_formats_found_in_file_names(part, expected):
    assert load_script("benchmark").name_amount(part) == expected


def test_benchmark_flags_and_counts_names_whose_ending_looks_like_an_amount_but_was_not_read(tmp_path, capsys):
    import json
    benchmark = load_script("benchmark")
    names = {"k1": "2025-10-07 - Hydro-Quebec - FactureElectricite - 158,98 $.pdf",       # read (comma format)
             "k2": "2025-10-08 - Hydro-Quebec - FactureElectricite - 790.70Net.pdf",     # looks like an amount, not read
             "k3": "2025-10-09 - Hydro-Quebec - FactureElectricite.pdf"}                  # no amount at all
    for k in names:
        (tmp_path / f"{k}.txt").write_text("texte sans rien", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": k, "name": n} for k, n in names.items()]), encoding="utf-8")
    rows = {r["key"]: r for r in benchmark.load(tmp_path)}
    assert rows["k1"]["amount"] == "158.98" and not rows["k1"]["amount_unread"]
    assert rows["k2"]["amount"] is None and rows["k2"]["amount_unread"]
    assert rows["k3"]["amount"] is None and not rows["k3"]["amount_unread"]
    benchmark.score(tmp_path)
    assert "amount-like but not read (left out of the amount score): 1" in capsys.readouterr().out


def test_benchmark_reads_the_expected_values_whatever_the_length_of_the_extension(tmp_path):
    import json
    benchmark = load_script("benchmark")
    names = {"k1": "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "k2": "2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.jpeg",
             "k3": "2025-10-09 - Hydro-Quebec - FactureElectricite - 30.00$.docx",
             "k4": "2025-10-10 - Hydro-Quebec - FactureElectricite - 40.00$.PDF"}
    for k in names:
        (tmp_path / f"{k}.txt").write_text("texte", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": k, "name": n} for k, n in names.items()]), encoding="utf-8")
    got = {r["key"]: (r["type"], r["amount"]) for r in benchmark.load(tmp_path)}
    assert got == {"k1": ("FactureElectricite", "158.98"), "k2": ("FactureElectricite", "20.00"),
                   "k3": ("FactureElectricite", "30.00"), "k4": ("FactureElectricite", "40.00")}


def test_llm_eval_counts_a_failed_analysis_as_a_wrong_amount(tmp_path, monkeypatch, capsys):
    import json
    from decimal import Decimal

    from docflow.analyze import Analysis
    monkeypatch.syspath_prepend(str(SCRIPTS))                       # llm_eval imports benchmark from its own folder
    llm_eval = load_script("llm_eval")
    names = {"k1": "2025-10-07 - Voisin - Lettre - 158.98$.pdf", "k2": "2025-10-08 - Voisin - Lettre - 20.00$.pdf"}
    for k, name in names.items():
        amount = name.rsplit(" - ", 1)[1].removesuffix("$.pdf")
        (tmp_path / f"{k}.txt").write_text("Lettre manuscrite sans entreprise connue, " * 5 + f"montant {amount}", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": k, "name": n} for k, n in names.items()]), encoding="utf-8")

    from docflow.analyze import BadModelAnswer

    class FakeModel:
        def __init__(self, *a, **k):
            self.calls = 0

        def analyze(self, text):
            self.calls += 1
            if self.calls == 2:
                raise BadModelAnswer("model returned garbage")       # one document gets an unusable answer
            amount = Decimal(text.rsplit("montant ", 1)[1])          # the model reads the right amount when it answers
            return Analysis(date="2025-10-07", company="Voisin", document_type="Lettre", amount=amount)

    monkeypatch.setattr(llm_eval, "OllamaAnalyzer", FakeModel)
    llm_eval.main(tmp_path, "fake-model", 2)
    out = capsys.readouterr().out
    assert "valid JSON 1/2" in out
    assert "amount 1/2" in out                                       # the failed document is a miss, not an absent one


def _llm_corpus(tmp_path, count):
    import json
    names = {f"k{i}": f"2025-10-0{i + 1} - Voisin - Lettre - {10 + i}.00$.pdf" for i in range(count)}
    for k, name in names.items():
        amount = name.rsplit(" - ", 1)[1].removesuffix("$.pdf")
        (tmp_path / f"{k}.txt").write_text("Lettre manuscrite sans entreprise connue, " * 5 + f"montant {amount}", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": k, "name": n} for k, n in names.items()]), encoding="utf-8")


def _model_that(monkeypatch, llm_eval, behaviours):
    """A fake model answering call after call according to `behaviours`: an exception instance is raised, anything else is OK."""
    from decimal import Decimal

    from docflow.analyze import Analysis
    calls = []

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def analyze(self, text):
            behaviour = behaviours[len(calls)]
            calls.append(behaviour)
            if isinstance(behaviour, Exception):
                raise behaviour
            return Analysis(date="2025-10-07", company="Voisin", document_type="Lettre",
                            amount=Decimal(text.rsplit("montant ", 1)[1]))

    monkeypatch.setattr(llm_eval, "OllamaAnalyzer", FakeModel)
    return calls


@pytest.mark.parametrize("written,value", [("12,50 $", "12.50"), ("1 234,56 $", "1234.56"), ("1.234,56 $", "1234.56"), ("-8,00 $", "-8.00"),
                                           ("12.50$", "12.50"), ("30.00 USD", "30.00")])
def test_llm_eval_reads_amounts_written_in_any_format_of_the_names_without_crashing(tmp_path, monkeypatch, capsys, written, value):
    import json
    from decimal import Decimal

    from docflow.analyze import Analysis
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    name = f"2025-10-07 - Voisin - Lettre - {written}.pdf"
    (tmp_path / "k0.txt").write_text("Lettre manuscrite sans entreprise connue, " * 5, encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": "k0", "name": name}]), encoding="utf-8")

    class Model:
        def __init__(self, *a, **k):
            pass

        def analyze(self, text):
            return Analysis(date="2025-10-07", company="Voisin", document_type="Lettre", amount=Decimal(value))

    monkeypatch.setattr(llm_eval, "OllamaAnalyzer", Model)
    llm_eval.main(tmp_path, "fake-model", 1)                      # used to raise InvalidOperation for a decimal comma
    assert "amount 1/1" in capsys.readouterr().out                # and the comparison is exact, not "almost"


def test_the_model_being_unreachable_is_not_counted_as_the_model_writing_bad_json(tmp_path, monkeypatch, capsys):
    from docflow.analyze import BadModelAnswer, OllamaError
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 6)
    _model_that(monkeypatch, llm_eval, ["ok", BadModelAnswer("not JSON"), OllamaError("Ollama HTTP 404: model not found"),
                                        "ok", ConnectionRefusedError("[Errno 111]"), "ok"])
    llm_eval.main(tmp_path, "fake-model", 6)
    out = capsys.readouterr().out
    assert "valid JSON 3/4" in out                                  # 4 documents were really judged: 3 good answers, 1 bad
    assert "infrastructure errors 2" in out                         # the two the model is not responsible for, counted apart
    assert "company 3/4" in out                                     # the same denominator for every score: 4 judged documents


def test_a_server_that_cuts_the_connection_or_answers_garbage_is_an_infrastructure_error_too(tmp_path, monkeypatch, capsys):
    """http.client reports a broken HTTP exchange with HTTPException subclasses that are neither OSError nor ValueError."""
    import http.client
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 4)
    _model_that(monkeypatch, llm_eval, ["ok", http.client.BadStatusLine("garbage"), http.client.IncompleteRead(b"par", 10), "ok"])
    llm_eval.main(tmp_path, "fake-model", 4)                      # used to end in a traceback
    out = capsys.readouterr().out
    assert "infrastructure errors 2" in out and "valid JSON 2/2" in out        # left out of every score, 2 really judged
    assert "BadStatusLine" in out and "IncompleteRead" in out                   # and each one named


def test_the_evaluation_stops_when_the_model_server_is_clearly_down(tmp_path, monkeypatch, capsys):
    from docflow.analyze import OllamaError
    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 8)
    calls = _model_that(monkeypatch, llm_eval, [OllamaError("Ollama HTTP 503")] * 8)
    llm_eval.main(tmp_path, "fake-model", 8)
    out = capsys.readouterr().out
    assert len(calls) == 3                                          # three in a row: no point asking the other five
    assert "stopped" in out and "unreachable" in out
    assert "valid JSON" not in out                                  # no score at all: nothing was judged, so none is invented


def test_an_unexpected_error_is_not_silently_taken_for_a_model_failure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 2)
    _model_that(monkeypatch, llm_eval, [RuntimeError("a bug in our own code")])
    with pytest.raises(RuntimeError, match="a bug in our own code"):
        llm_eval.main(tmp_path, "fake-model", 2)


def test_llm_eval_company_match_is_equality_of_normalised_names_not_substring(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    same = load_script("llm_eval").same_company
    assert same("Hydro-Québec", "HydroQuebec") and same("hydro quebec", "Hydro-Quebec")   # case, accents, spaces, dashes
    assert same("Collège MultiHexa", "MultiHexa")                                         # a declared alias (benchmark.SAME)
    assert not same("Hydro", "HydroQuebec")                      # a fragment of the expected name
    assert not same("Hydro-Quebec et Bell", "HydroQuebec")       # the expected name plus another company
    assert not same("", "HydroQuebec") and not same(None, "HydroQuebec")
    assert not same("HydroQuebec", "") and not same("---", "!!!")                         # nothing left after normalising


def test_benchmark_counts_an_unrecognised_field_as_an_error_but_not_a_missing_reference_amount():
    errors = load_script("benchmark").auto_errors
    assert errors(co=True, ty=True, da=True, am=True) == []
    assert errors(co=None, ty=True, da=True, am=True) == ["company"]       # nothing recognised: not "no error"
    assert errors(co=True, ty=None, da=True, am=True) == ["type"]
    assert errors(co=False, ty=False, da=False, am=False) == ["company", "type", "date", "amount"]
    assert errors(co=True, ty=True, da=True, am=None) == []                # no reference amount: nothing to compare


def test_the_projects_dev_tools_include_mypy_and_the_stubs_of_the_untyped_libraries_it_imports():
    import tomllib
    root = Path(__file__).resolve().parents[1]
    dev = [d.lower() for d in tomllib.loads((root / "pyproject.toml").read_text())["dependency-groups"]["dev"]]
    assert any(d.startswith("mypy") for d in dev)                                    # `uv run mypy` is a supported check
    assert any(d.startswith("types-pyyaml") for d in dev)                            # yaml ships no type information
    assert "import yaml" in (root / "backend" / "docflow" / "config.py").read_text()  # (and it is imported: the stubs are needed)


def test_manage_py_has_no_shebang_because_it_is_run_through_uv():
    """`python` does not exist on every machine and the system interpreter has no Django: the documented way is
    `uv run python manage.py ...`, so the file must not pretend to be directly executable."""
    first = (Path(__file__).resolve().parents[1] / "manage.py").read_text().splitlines()[0]
    assert not first.startswith("#!")


def test_the_benchmark_stop_words_are_a_set_of_27_common_words():
    stop = load_script("benchmark").STOP
    assert isinstance(stop, set) and len(stop) == 27
    assert {"de", "la", "the", "and", "this"} <= stop and "facture" not in stop       # common words only, never a distinguishing one


def test_the_yaml_rule_files_pass_the_projects_yamllint_line_length():
    """The configuration files hold long regexes and their explanations: the project states its own limit (.yamllint)
    instead of the 80 columns of the default, and the files must respect it."""
    import re
    root = Path(__file__).resolve().parents[1]
    config = (root / ".yamllint").read_text()
    limit = int(re.search(r"max:\s*(\d+)", config).group(1))
    assert 100 <= limit <= 160
    too_long = [(f.name, n) for f in sorted((root / "config").glob("*.yaml"))
                for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if len(line) > limit]
    assert too_long == []


def test_llm_eval_finishes_when_the_model_answers_without_a_date(tmp_path, monkeypatch, capsys):
    # DOC474.112 / .262 claimed `{a.date:<10}` raises on None. It cannot: an answer without a date is read as "XXXX" by
    # parse_llm_json and Analysis.date is a str. This guards that invariant, which the script's formatting relies on.
    from docflow.analyze import parse_llm_json
    monkeypatch.syspath_prepend(str(SCRIPTS))
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 2)

    class NoDateModel:
        def __init__(self, *a, **k):
            pass

        def analyze(self, text):  # what the real OllamaAnalyzer returns for a model that omitted or nulled the date
            amount = text.rsplit("montant ", 1)[1]
            return parse_llm_json(f'{{"date": null, "company": "Voisin", "document_type": "Lettre", "amount": "{amount}"}}')

    monkeypatch.setattr(llm_eval, "OllamaAnalyzer", NoDateModel)
    llm_eval.main(tmp_path, "fake-model", 2)
    out = capsys.readouterr().out
    assert "date 0/2" in out and "valid JSON 2/2" in out          # the final score is printed, the missing date counts as a miss


def test_benchmark_never_reads_a_text_file_outside_the_cache_folder(tmp_path):
    # DOC474.161: a key such as "../outside" or an absolute path made load() read any file the process could open
    import json
    from collections import Counter
    benchmark = load_script("benchmark")
    cache = tmp_path / "cache"
    cache.mkdir()
    (tmp_path / "outside.txt").write_text("PRIVATE TEXT", encoding="utf-8")
    name = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    (cache / "good.txt").write_text("texte", encoding="utf-8")
    keys = ["good", "../outside", str(tmp_path / "outside"), "sub/../../outside", "", "..", 7]
    (cache / "index.json").write_text(json.dumps([{"key": k, "name": name} for k in keys]), encoding="utf-8")
    left_out = Counter()
    rows = benchmark.load(cache, left_out)
    assert [r["key"] for r in rows] == ["good"] and all("PRIVATE" not in r["text"] for r in rows)
    assert left_out["key is not a plain file name"] == len(keys) - 1                # every refusal is counted, none silent


def test_compare_extracts_again_a_saved_text_it_cannot_read_instead_of_stopping(tmp_path, capsys):
    # DOC474.166: a saved text that is not valid UTF-8 (a crash, a disk fault) raised UnicodeDecodeError out of the whole run
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    pdf_path = std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(pdf_path, "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    compare.main(tmp_path)
    saved = pdf_path.with_suffix(".txt")
    saved.write_bytes(b"\xff\xfe broken \x80")                               # the key still vouches for it, the bytes are garbage
    capsys.readouterr()
    assert compare.main(tmp_path) == 0
    out = capsys.readouterr().out
    assert "exact full date      : 1/1 = 100%" in out                       # the document was read again and counted
    assert "1 saved text(s) could not be read" in out                       # and the corrupt one is named in the report
    assert "158,98" in saved.read_text(encoding="utf-8")                    # and the saved text was rebuilt


def test_build_corpus_skips_the_nas_system_folders_but_not_a_folder_that_merely_contains_an_at_sign(tmp_path):
    # DOC474.181: "@" anywhere in the path excluded a legitimate archive folder such as "equipe@2024"
    build_corpus = load_script("build_corpus")
    name = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    for folder in ("equipe@2024", "@Recycle", "ok/@eaDir", "plain"):
        (tmp_path / "root" / folder).mkdir(parents=True)
        make_pdf(tmp_path / "root" / folder / name, "Hydro-Quebec\nFacture")
    cache = tmp_path / "cache"
    build_corpus.main(tmp_path / "root", cache)
    import json
    rels = sorted(r["rel"] for r in json.loads((cache / "index.json").read_text(encoding="utf-8")))
    assert rels == [f"equipe@2024/{name}", f"plain/{name}"]                # the two system folders only are left out


def test_build_corpus_reports_orphan_texts_and_only_deletes_them_when_asked(tmp_path, capsys):
    # DOC474.182: the texts (private content) of deleted or moved PDFs stayed in the cache forever
    import json
    build_corpus = load_script("build_corpus")
    root, cache = tmp_path / "root", tmp_path / "cache"
    root.mkdir()
    name = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(root / name, "Hydro-Quebec\nFacture")
    gone = root / ("2025-10-08 - Telus - ReleveMobilite.pdf")
    make_pdf(gone, "Telus releve")
    build_corpus.main(root, cache)
    gone.unlink()                                                                   # the PDF is deleted from the archive
    (cache / "notes.txt").write_text("my own file", encoding="utf-8")                # not a cache entry: never touched
    before = sorted(p.name for p in cache.iterdir())
    capsys.readouterr()
    build_corpus.main(root, cache)
    out = capsys.readouterr().out
    assert sorted(p.name for p in cache.iterdir()) == before                        # nothing deleted without being asked...
    assert "2 orphan file(s)" in out and "--prune" in out                           # ...but it is said, with the way to remove them
    build_corpus.main(root, cache, prune=True)
    left = sorted(p.name for p in cache.iterdir())
    keys = {r["key"] for r in json.loads((cache / "index.json").read_text(encoding="utf-8"))}
    assert left == sorted(["index.json", "notes.txt", *(f"{k}.txt" for k in keys), *(f"{k}.txt.key" for k in keys)])
    assert len(keys) == 1


def test_discover_keeps_the_first_lines_of_a_document_written_in_another_alphabet(tmp_path, monkeypatch):
    # DOC474.191: a line needed three ASCII letters, so a Cyrillic, Arabic, Greek or Japanese issuer was listed as "[no text]"
    import types
    discover = load_script("discover")
    for text in ("Газпром Нефть ООО\nСчёт 2025", "شركة النفط الوطنية\nفاتورة", "Ελληνική Εταιρεία Α.Ε.\nΤιμολόγιο", "株式会社東京商事\n請求書"):
        monkeypatch.setattr(discover, "extract_text", lambda *a, _t=text, **k: types.SimpleNamespace(text=_t))
        name, first_lines, cause = discover.head(tmp_path / "x.pdf")
        assert first_lines and cause == "", text
    monkeypatch.setattr(discover, "extract_text", lambda *a, **k: types.SimpleNamespace(text="123 456\n--- ---\n42"))
    assert discover.head(tmp_path / "x.pdf")[1] == ""                       # digits and punctuation alone are still "no text"


def test_benchmark_names_the_real_auto_threshold_in_its_report(tmp_path, monkeypatch, capsys):
    # DOC474.50: the report said "CONFIDENCE >= 95%" whatever thresholds.auto is configured to
    import json
    benchmark = load_script("benchmark")
    real_load = benchmark.load_config

    def with_threshold():
        cfg = real_load()
        cfg.settings["thresholds"] = {"auto": 0.9, "confirm": 0.7}
        return cfg
    monkeypatch.setattr(benchmark, "load_config", with_threshold)
    (tmp_path / "k1.txt").write_text("Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $",
                                     encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([{"key": "k1", "name": "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"}]),
                                         encoding="utf-8")
    benchmark.score(tmp_path)
    out = capsys.readouterr().out
    assert "ERRORS WITH CONFIDENCE >= 90%" in out and ">= 95%" not in out


def test_benchmark_mine_gives_the_same_words_as_the_plain_definition(tmp_path, capsys):
    # DOC474.51: mine() is rewritten to count each word once per type instead of once per (word, other document); same answers
    import json
    import random
    import re
    from collections import defaultdict
    benchmark = load_script("benchmark")
    rnd = random.Random(7)
    vocab = ["golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "nova", "oscar", "papa"]   # filler, none of the own words
    rows, texts = [], {}
    for t, own in (("FactureElectricite", "alpha bravo"), ("ReleveCompte", "charlie delta"), ("AvisCotisation", "echo")):
        for i in range(10):
            key = f"{t}{i}"
            texts[key] = " ".join([own, *rnd.sample(vocab, 5)])
            (tmp_path / f"{key}.txt").write_text(texts[key], encoding="utf-8")
            rows.append({"key": key, "name": f"2025-01-0{1 + i % 9} - Acme - {t} - 10.00$.pdf"})
    (tmp_path / "index.json").write_text(json.dumps(rows), encoding="utf-8")
    benchmark.mine(tmp_path, "Acme")
    printed = capsys.readouterr().out
    by_type = defaultdict(list)                                          # the definition, written the slow way
    for r in rows:
        by_type[r["name"].split(" - ")[2]].append(set(re.findall(r"[a-z]{4,}", texts[r["key"]].lower())) - benchmark.STOP)
    for group, docs in by_type.items():
        others = [d for k, v in by_type.items() if k != group for d in v]
        words = sorted(((sum(w in d for d in docs) / len(docs) - sum(w in d for d in others) / len(others), w)
                        for w in set().union(*docs)
                        if sum(w in d for d in docs) / len(docs) >= 0.7 and sum(w in d for d in others) / len(others) <= 0.15),
                       reverse=True)
        expected = [w for _, w in words[:7]]
        line = next(line for line in printed.splitlines() if line.strip().startswith(group))
        assert line.endswith(f"-> {expected}"), (group, line, expected)
    assert "alpha" in printed and "charlie" in printed                       # (the corpus really has distinguishing words)


def test_benchmark_mine_says_what_it_left_out_and_suggests_the_company_when_it_is_not_found(tmp_path, capsys):
    # DOC474.52: a typo in the company printed "0 documents" with no clue, and left-out entries vanished silently
    import json
    benchmark = load_script("benchmark")
    good = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    (tmp_path / "k1.txt").write_text("facture electricite", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps([
        {"key": "k1", "name": good},
        {"key": "k2", "name": "2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf"},       # its text is missing
        {"key": "k3", "name": "not in the standard form.pdf", "error": "OSError"}]), encoding="utf-8")
    benchmark.mine(tmp_path, "Hydro-Quebec")
    out = capsys.readouterr().out
    assert "Hydro-Quebec: 1 documents" in out
    assert "left out" in out and "text missing" in out and "extraction error" in out        # nothing disappears silently
    benchmark.mine(tmp_path, "Hydro-Quebc")                                                    # a typo
    out = capsys.readouterr().out
    assert "no document" in out.lower() and "Hydro-Quebec" in out                              # and the right name is suggested


@pytest.mark.parametrize("part,expected,unread", [
    ("150 $", "150.00", False), ("1 200 $", "1200.00", False), ("1,200 $", "1200.00", False), ("-80 CAD", "-80.00", False),
    ("158.98$", "158.98", False), ("1 234,56 $", "1234.56", False),                        # unchanged
    ("2025", None, False), ("150", None, False),                                            # no currency: not an amount
    ("150.5 $", None, True), ("1.200 $", None, True)])                                      # ambiguous: left out, but SAID
def test_benchmark_reads_whole_amounts_and_reports_the_ambiguous_ones(part, expected, unread):
    # DOC474.53: "150 $" was neither read nor counted as "amount-like but not read"
    benchmark = load_script("benchmark")
    assert benchmark.name_amount(part) == expected, part
    assert (expected is None and bool(benchmark.LOOKS_LIKE_AMOUNT.search(part))) is unread, part


def test_compare_lists_the_wrong_companies_with_the_one_found_instead(tmp_path, capsys):
    # DOC474.62: dates and amounts had a "WRONG ..." list; the company rate had none, so a regression meant instrumenting the script
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 158,98 $")
    make_pdf(std / "001__2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf",
             "Lettre de la tante Huguette sans entreprise connue\nLe 8 octobre 2025\nMontant : 20,00 $")      # the company is missed
    compare.main(tmp_path)
    out = capsys.readouterr().out
    assert "company (config)     : 1/2 = 50%" in out
    wrong = out.split("WRONG COMPANIES (max 10)", 1)[1].split("NO TEXT", 1)[0]
    assert "2025-10-08 - Hydro-Quebec - FactureElectricite - 20.00$.pdf" in wrong    # the file that is wrong is named...
    assert "'Hydro-Quebec', None" in wrong                                           # ...with what was expected and what was found
    assert "2025-10-07" not in wrong                                                 # and the one that is right is not


def test_compare_does_not_say_ocr_is_required_for_a_file_that_was_already_through_ocr(tmp_path, capsys):
    # DOC474.63: "PDFs without text (OCR required)" pointed at OCR for files that had just been extracted WITH it
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    doc = pymupdf.open()
    doc.new_page()                                                              # a blank page: nothing to read, even with OCR
    doc.save(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf")
    compare.main(tmp_path)
    out = capsys.readouterr().out
    assert "OCR required" not in out and "no usable text after extraction (OCR included): 1" in out


def test_compare_reads_the_reference_amount_of_a_name_with_a_thousands_or_decimal_comma_and_counts_the_unreadable(tmp_path, capsys):
    # DOC474.64: "1,234.56 $" and "12,34 $" matched nothing: the file counted neither as a hit nor as a miss
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Hydro-Quebec - FactureElectricite - 1,234.56$.pdf",
             "Hydro-Quebec\nFacture d'electricite du 7 octobre 2025\nMontant de la presente facture : 1 234,56 $")
    make_pdf(std / "001__2025-10-08 - Hydro-Quebec - FactureElectricite - 12,34 $.pdf",
             "Hydro-Quebec\nFacture d'electricite du 8 octobre 2025\nMontant de la presente facture : 12,34 $")
    make_pdf(std / "002__2025-10-09 - Hydro-Quebec - FactureElectricite - 790.70Net.pdf",
             "Hydro-Quebec\nFacture d'electricite du 9 octobre 2025\nMontant de la presente facture : 790,70 $")
    compare.main(tmp_path)
    out = capsys.readouterr().out
    assert "exact amount         : 2/2 = 100%" in out                           # both are now REFERENCES, and both are right
    assert "1 amount-like name(s) not read" in out                              # and the third one is not silently dropped


def test_build_corpus_refusals_go_to_stderr_like_its_per_file_errors(tmp_path, capsys):
    # DOC474.89: "ERROR: not a folder" went to stdout while the per-file errors went to stderr: a script filtering one missed them
    corpus = load_script("build_corpus")
    assert corpus.main(tmp_path / "typo", tmp_path / "cache") == 2
    out, err = capsys.readouterr()
    assert "not a folder" in err and out == ""
    root, cache = tmp_path / "root", tmp_path / "cache"
    root.mkdir()
    cache.mkdir()
    (cache / "index.json").write_text('[{"key": "k", "name": "x"}]', encoding="utf-8")            # an index that would be wiped
    assert corpus.main(root, cache) == 2
    out, err = capsys.readouterr()
    assert "no PDF following the standard" in err and out == ""


def test_build_corpus_returns_1_when_some_entries_failed_so_a_script_or_ci_notices(tmp_path, capsys):
    # DOC474.90: 'done: 5 entries, 5 errors' still returned 0
    corpus = load_script("build_corpus")
    root, cache = tmp_path / "archive", tmp_path / "cache"
    root.mkdir()
    good = "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    make_pdf(root / good, "Hydro-Quebec facture")
    assert corpus.main(root, cache) == 0                                                  # nothing failed: success
    (root / "2025-10-08 - Telus - ReleveMobilite - 20.00$.pdf").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)   # cannot be read
    capsys.readouterr()
    assert corpus.main(root, cache) == 1                                                  # one failed: done, but not a success
    out = capsys.readouterr().out
    assert "1 errors" in out and "2 entries" in out                                       # (the index is still written, with the error)


def test_build_corpus_does_not_read_the_configuration_until_it_has_work_to_do(tmp_path, monkeypatch, capsys):
    # DOC474.92: load_config() ran at import, so even --help (or an import in a test) failed on a bad configuration
    import docflow.config

    def broken(*a, **k):
        raise FileNotFoundError("no settings.yaml")
    monkeypatch.setattr(docflow.config, "load_config", broken)
    corpus = load_script("build_corpus")                                       # importing must not raise
    assert corpus.main(tmp_path / "typo", tmp_path / "cache") == 2             # a refusal needs no configuration
    root = tmp_path / "archive"
    root.mkdir()
    make_pdf(root / "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf", "Hydro-Quebec facture")
    with pytest.raises(FileNotFoundError, match="settings.yaml"):               # the broken configuration shows up when work starts
        corpus.main(root, tmp_path / "cache")


def test_build_corpus_documents_which_folders_it_skips():
    # DOC474.93: files under a NAS system folder were left out with no word in the docstring or the usage
    corpus = load_script("build_corpus")
    assert "@Recycle" in corpus.__doc__ and "@eaDir" in corpus.__doc__ and "starts with" in corpus.__doc__


def test_discover_groups_the_same_failure_even_when_its_message_carries_the_file_path(tmp_path, monkeypatch, capsys):
    # DOC474.113: five files failing the same way (a path in each message) were listed as five separate causes
    discover = load_script("discover")
    for i in range(5):
        make_pdf(tmp_path / f"scan{i}.pdf", f"texte {i}")

    def broken(path, *a, **k):
        raise OSError(f"cannot open {path} (code 13)")
    monkeypatch.setattr(discover, "extract_text", broken)
    discover.main(tmp_path)
    out = capsys.readouterr().out
    causes = out.split("why files were unreadable:")[1].strip().splitlines()
    assert len(causes) == 1 and causes[0].lstrip().startswith("5 "), causes                 # ONE cause, counted five times
    assert "OSError" in causes[0] and "e.g." in causes[0]                                      # with an example kept for display


def test_discover_goes_on_when_the_analysis_of_one_text_raises(tmp_path, monkeypatch, capsys):
    # DOC474.114: only the extraction was protected; an exception from analyze() or norm() ended the whole run without a summary
    discover = load_script("discover")
    make_pdf(tmp_path / "a-good.pdf", "Lettre de la tante Huguette\nBonjour tout le monde")
    make_pdf(tmp_path / "b-odd.pdf", "texte etrange")
    real = discover.an.analyze

    def choke_on_odd(text):
        if "etrange" in text:
            raise RecursionError("maximum recursion depth exceeded")
        return real(text)
    monkeypatch.setattr(discover.an, "analyze", choke_on_odd)
    discover.main(tmp_path)                                                                  # must not raise
    out = capsys.readouterr().out
    assert "2 PDFs" in out and "unreadable: 1" in out                                         # the odd one is counted, the run finished
    assert "why files were unreadable" in out and "RecursionError" in out                    # and the cause is named
    assert "lettre de la tante" in out.lower()                                                # the good file is still grouped


@pytest.mark.parametrize("bad", ["0", "-1", "-45", "abc", "1.5"])
def test_discover_refuses_a_limit_that_is_not_a_positive_whole_number(tmp_path, bad):
    # DOC474.115: --limit -1 listed every group but the last and said "1 more groups"; 0 listed none, with no error
    import os
    import subprocess
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS.parent / "backend")}
    script = str(SCRIPTS / "discover.py")
    run = subprocess.run([sys.executable, script, str(tmp_path), "--limit", bad], capture_output=True, text=True, env=env)
    assert run.returncode == 2 and "--limit" in run.stderr and "Traceback" not in run.stderr, (bad, run.stderr)
    ok = subprocess.run([sys.executable, script, str(tmp_path), "--limit", "3"], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "0 PDFs" in ok.stdout                                  # a valid limit still runs


def test_make_sandbox_writes_complete_readable_pdfs_without_any_pdf_library(tmp_path):
    # DOC474.132 asked for the document to be closed after saving; the samples are now written by hand (no document to close),
    # so what is checked is that each file is complete and reads back, accents and parentheses included
    from docflow.extract import extract_text
    sandbox = load_script("make_sandbox")
    sandbox.make(tmp_path / "a.pdf", ["Facture d'électricité (Hydro-Québec)", "Total 26,43 $"])
    sandbox.make(tmp_path / "b.pdf", ["Autre"])
    got = extract_text(tmp_path / "a.pdf")
    assert got.pages == 1 and got.method == "text"
    assert "Facture d'électricité (Hydro-Québec)" in got.text and "Total 26,43 $" in got.text
    assert extract_text(tmp_path / "b.pdf").pages == 1
    assert "pymupdf" not in (Path(sandbox.__file__).read_text(encoding="utf-8"))   # the product ships no AGPL library


def test_compare_checks_the_currency_written_in_the_sample_name(tmp_path, capsys):
    # DOC474.167: "... - 100.00 USD.pdf" counted as right when the document said 100,00 $ (CAD): only the number was compared
    compare = load_script("compare")
    std = tmp_path / "std"
    std.mkdir()
    make_pdf(std / "000__2025-10-07 - Acme - Facture - 100.00 USD.pdf", "Acme\nFacture du 7 octobre 2025\nTotal a payer : 100,00 $")      # CAD
    make_pdf(std / "001__2025-10-08 - Acme - Facture - 100.00 USD.pdf", "Acme\nFacture du 8 octobre 2025\nTotal a payer : 100.00 USD")    # USD
    make_pdf(std / "002__2025-10-09 - Acme - Facture - 50.00.pdf", "Acme\nFacture du 9 octobre 2025\nTotal a payer : 50,00 $")           # no currency
    compare.main(tmp_path)
    out = capsys.readouterr().out
    assert "exact amount         : 2/3 = 67%" in out                                  # the CAD document is NOT a match for an USD name
    wrong = out.split("WRONG AMOUNTS (max 10)", 1)[1].split("WRONG COMPANIES", 1)[0]
    assert "2025-10-07 - Acme - Facture - 100.00 USD.pdf" in wrong and "CAD" in wrong   # listed, with the currency it found
    assert "2025-10-08" not in wrong and "2025-10-09" not in wrong                    # the two right ones are not


@pytest.mark.parametrize("bad", ["-1", "0", "-10", "abc"])
def test_llm_eval_refuses_a_sample_size_that_is_not_a_positive_whole_number_with_a_clear_message(tmp_path, bad):
    # DOC474.189: N=-1 reached random.sample and raised a ValueError traceback before any measure was taken
    import os
    import subprocess
    llm_eval = load_script("llm_eval")
    if bad.lstrip("-").isdigit():
        with pytest.raises(ValueError, match="at least 1"):
            llm_eval.main(tmp_path, "fake-model", int(bad))
    env = {**os.environ, "PYTHONPATH": f"{SCRIPTS.parent / 'backend'}:{SCRIPTS}"}
    run = subprocess.run([sys.executable, str(SCRIPTS / "llm_eval.py"), str(tmp_path), "fake-model", bad], capture_output=True, text=True, env=env)
    assert run.returncode == 2 and "Traceback" not in run.stderr and "N" in run.stderr and "whole number" in run.stderr, run.stderr


def test_llm_eval_measures_durations_with_a_monotonic_clock(tmp_path, monkeypatch, capsys):
    # DOC474.190: time.time() jumps (NTP correction, DST, manual change): a negative duration would corrupt the mean and the max
    llm_eval = load_script("llm_eval")
    _llm_corpus(tmp_path, 2)
    _model_that(monkeypatch, llm_eval, ["ok", "ok"])
    ticks = iter([100.0, 101.5, 200.0, 203.0])                               # the monotonic clock, never going back
    monkeypatch.setattr(llm_eval.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(llm_eval.time, "time", lambda: (_ for _ in ()).throw(AssertionError("the wall clock must not time anything")))
    llm_eval.main(tmp_path, "fake-model", 2)
    out = capsys.readouterr().out
    assert "mean time 2.2s (max 3s)" in out or "mean time 2.3s (max 3s)" in out, out     # (1.5 + 3.0) / 2 = 2.25


def test_an_index_row_that_is_not_an_object_does_not_stop_the_adoption_of_old_names(tmp_path):
    # DOC474.250: r.get(...) on a null / number / string row raised AttributeError and stopped the whole script
    import json

    build = load_script("build_corpus")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "oldkey.txt").write_text("T", encoding="utf-8")
    (cache / "oldkey.txt.key").write_text("{}", encoding="utf-8")
    rows = [None, 7, "text", ["x"], {"key": "oldkey", "rel": "a.pdf", "name": "a.pdf"}]
    (cache / "index.json").write_text(json.dumps(rows), encoding="utf-8")
    assert build.adopt_old_names(cache) == 1
    assert rows[:4] == json.loads((cache / "index.json").read_text())[:4]      # the odd rows are left as they were


def test_discover_says_how_far_it_got_on_stderr_and_keeps_its_report_on_stdout(tmp_path, monkeypatch, capsys):
    # DOC474.116: over hundreds of scanned PDFs the script stayed silent for minutes
    discover = load_script("discover")
    for i in range(60):
        (tmp_path / f"f{i:02d}.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(discover, "head", lambda path: (path.name, "Une ligne", ""))
    discover.main(tmp_path)
    out, err = capsys.readouterr()
    assert err.splitlines() == ["  25/60 read", "  50/60 read", "  60/60 read"]    # every 25 files, and the last one
    assert "60 PDFs; without company: 60" in out and "25/60" not in out             # the report itself is not mixed with it
