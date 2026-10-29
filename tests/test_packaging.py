"""The packaging scripts (packaging/) are PowerShell and batch files: they cannot run here, so what they promise is read in the text."""
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


def test_the_language_data_comes_from_one_pinned_commit_and_every_file_is_checked():
    # DOC534.46: fra.traineddata came from the moving `main` branch with no check, while eng and osd came from the installer
    import hashlib
    import re
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "/raw/main/" not in script and "tessdata_best/$tessdataCommit/$lang.traineddata" in script
    commit = re.search(r'\$tessdataCommit = "([0-9a-f]{40})"', script)
    assert commit                                                                 # a full commit id, not a branch or a short one
    ids = dict(re.findall(r'(\w{3}) = "([0-9a-f]{40})"', script.split("$blobIds")[1].split("\n")[0]))
    assert set(ids) == {"eng", "osd", "fra"}                                      # the three languages the program carries
    assert 'Copy-Item (Join-Path $install "tessdata' not in script                # none of them from the installer any more
    assert "does not match the pinned file" in script and script.index("Get-GitBlobId $target") < script.index("does not match")
    # the blob id the script computes is git's: sha1("blob <size>\0" + content)
    assert hashlib.sha1(b"blob 3\0abc").hexdigest() == "f2ba8f84ab5c1bce84a7b441cb1959cfc7093b7f"
    assert '"blob $($bytes.Length)" + [char]0' in script


def test_the_tesseract_installer_is_never_run_without_a_hash_to_check_it_against():
    # DOC534.45: "SHA256_PLACEHOLDER" switched the check off and the downloaded installer was run and shipped unchecked
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "SHA256_PLACEHOLDER" not in script
    assert "if (-not $expected) { throw " in script and "if ($actual -ne $expected) { throw " in script   # no hash is a failure, a mismatch too
    assert "[string]$Sha256" in script                                           # the hash can be given without editing the script
    run = script.index("Start-Process -FilePath $installer")
    assert script.index("if (-not $expected) { throw ") < script.index("if ($actual -ne $expected) { throw ") < run   # both checks come first
