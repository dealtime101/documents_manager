"""The packaging scripts (packaging/) are PowerShell and batch files: they cannot run here, so what they promise is read in the text."""
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


def test_the_tesseract_installer_is_never_run_without_a_hash_to_check_it_against():
    # DOC534.45: "SHA256_PLACEHOLDER" switched the check off and the downloaded installer was run and shipped unchecked
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "SHA256_PLACEHOLDER" not in script
    assert "if (-not $expected) { throw " in script and "if ($actual -ne $expected) { throw " in script   # no hash is a failure, a mismatch too
    assert "[string]$Sha256" in script                                           # the hash can be given without editing the script
    run = script.index("Start-Process -FilePath $installer")
    assert script.index("if (-not $expected) { throw ") < script.index("if ($actual -ne $expected) { throw ") < run   # both checks come first
