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


def test_a_tesseract_folder_that_lacks_a_language_or_its_dlls_is_not_taken_for_prepared():
    # DOC534.47: only tesseract.exe was looked for, so a run interrupted after the copy of the executable was "already prepared"
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert 'if (Test-Path (Join-Path $out "tesseract.exe")) {' not in script
    first = script[:script.index("exit 0")]
    for needed in ("tesseract.exe", "tessdata\\eng.traineddata", "tessdata\\osd.traineddata", "tessdata\\fra.traineddata", "*.dll"):
        assert needed in first                                                   # every file the program carries is part of the test
    assert "$missing.Count -eq 0 -and $dlls.Count -gt 0" in first


def test_a_failed_tesseract_install_stops_the_script_with_its_own_message():
    # DOC534.154: the exit code was not read, so a refused install went on to a Copy-Item of a file that was not there
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    run = script.index("Start-Process -FilePath $installer")
    line = script[run:script.index("\n", run)]
    assert "-Wait -PassThru" in line and line.lstrip().startswith("Start-Process") is True and "$proc = " in script[run - 12:run]
    assert script.index("$proc.ExitCode -ne 0", run) < script.index("Test-Path (Join-Path $install \"tesseract.exe\")", run)
    assert script.index("has no tesseract.exe", run) < script.index("Copy-Item (Join-Path $install \"tesseract.exe\")")


def test_the_windows_build_leaves_the_calling_console_as_it_found_it():
    # DOC534.170: PY, the UTF-8 code page and the directory stayed in the cmd session that ran the script
    script = (PACKAGING / "build_windows.bat").read_text(encoding="utf-8")
    lines = [line.strip() for line in script.splitlines()]
    assert lines.index("setlocal") < next(i for i, line in enumerate(lines) if line.startswith("chcp 65001"))     # variables stay local
    saved = next(i for i, line in enumerate(lines) if "'chcp'" in line)
    assert saved < lines.index("chcp 65001 >nul")                                   # the original code page is read before it is changed
    assert not any(line.startswith("cd /d") for line in lines) and lines.count("popd") >= 2     # pushd at the start, popd at both exits
    for exit_line in [i for i, line in enumerate(lines) if line.startswith("exit /b")]:
        assert lines[exit_line - 1] == "chcp %OLDCP% >nul" and lines[exit_line - 2] == "popd", lines[exit_line - 2:exit_line + 1]
    assert len([line for line in lines if line.startswith("exit /b")]) == 2


def test_a_double_clicked_windows_build_waits_for_a_key_before_its_window_closes():
    # DOC534.173: started from Explorer, the console closed with the script and hid both the result and the error
    script = (PACKAGING / "build_windows.bat").read_text(encoding="utf-8")
    lines = [line.strip() for line in script.splitlines()]
    assert 'echo %cmdcmdline% | find /i "%~nx0" >nul && if not defined CI set "DBLCLICK=1"' in lines   # not CI, not a console already open
    assert lines.count("if defined DBLCLICK pause") == 2                              # the success exit and the failure exit
    for exit_line in [i for i, line in enumerate(lines) if line.startswith("exit /b")]:
        assert lines[exit_line - 3] == "if defined DBLCLICK pause", lines[exit_line - 3:exit_line + 1]   # before popd and the code page
    assert lines.index('set "DBLCLICK="') < lines.index('echo %cmdcmdline% | find /i "%~nx0" >nul && if not defined CI set "DBLCLICK=1"')


def test_the_windows_build_installs_what_uv_lock_pins_with_hashes():
    # DOC534.172: `pip install . pyinstaller pywebview` took the newest version of each at every build, so two builds of one commit differed
    import re
    root = PACKAGING.parent
    script = (PACKAGING / "build_windows.bat").read_text(encoding="utf-8")
    assert "pip install --quiet --require-hashes -r packaging\\requirements-build.txt" in script
    assert "pip install --quiet --no-deps ." in script and "pyinstaller pywebview" not in script
    required = (PACKAGING / "requirements-build.txt").read_text(encoding="utf-8")
    pins = dict(re.findall(r"^([A-Za-z0-9._-]+)==([^\s;]+)", required, flags=re.M))
    assert {"pyinstaller", "pywebview", "django"} <= set(pins)
    assert required.count("--hash=sha256:") >= len(pins)                                  # every pin carries at least one hash
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    locked = dict(re.findall(r'^name = "([^"]+)"\nversion = "([^"]+)"', lock, flags=re.M))
    stale = {name: (version, locked.get(name)) for name, version in pins.items() if locked.get(name) != version}
    assert not stale, f"packaging/requirements-build.txt is out of date with uv.lock, regenerate it (see build_windows.bat): {stale}"


def test_the_windows_build_checks_the_python_version_and_remakes_an_old_build_venv():
    # DOC534.171: an old .venv-build, or a py/python older than 3.12, failed later with an unclear error
    import re
    script = (PACKAGING / "build_windows.bat").read_text(encoding="utf-8")
    minimum = re.search(r"requires-python = \">=(\d+\.\d+)\"", (PACKAGING.parent / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    major, minor = minimum.split(".")
    check = f'-c "import sys; sys.exit(sys.version_info < ({major}, {minor}))"'                   # the bar of pyproject, not another
    assert script.count(check) == 2                                                               # the interpreter found AND the old venv
    interpreter = script.index("%PY% " + check)
    old_venv = script.index('".venv-build\\Scripts\\python.exe" ' + check)
    assert interpreter < old_venv < script.index("rmdir /s /q .venv-build") < script.index("%PY% -m venv .venv-build")


def test_the_front_end_lockfile_resolves_the_versions_that_fix_the_advisories_it_once_had():
    # DOC534.569 and following: osv-scanner and trivy named these packages in package-lock.json; `npm audit fix` raised them
    import json

    def version(text):
        return tuple(int(part) for part in text.split("-")[0].split(".")[:3])
    packages = json.loads((PACKAGING.parent / "frontend" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    at_least = {"vite": "8.3.5", "zod": "4.6.6", "undici": "7.30.1", "fast-uri": "3.1.9", "ip-address": "10.7.5"}
    found = {name: packages.get(f"node_modules/{name}", {}).get("version") for name in at_least}
    behind = {name: found[name] for name, floor in at_least.items() if found[name] and version(found[name]) < version(floor)}
    assert behind == {}, behind
    assert "node_modules/body-parser" not in packages and "node_modules/qs" not in packages     # the express tree is no longer pulled in
    assert version("8.3.10") > version("8.3.5") and version("4.6.7") >= version("4.6.6")         # the comparison is numeric, not textual


def test_uv_lock_resolves_the_python_versions_that_fix_the_advisories_it_once_had():
    # DOC534.576 and DOC534.700: osv-scanner and trivy named setuptools 84.0.0 and djangorestframework 3.18.1 in uv.lock
    import re
    lock = (PACKAGING.parent / "uv.lock").read_text(encoding="utf-8")
    locked = dict(re.findall(r'^name = "([^"]+)"\nversion = "([^"]+)"', lock, flags=re.MULTILINE))

    def version(text):
        return tuple(int(part) for part in text.split(".")[:3])
    at_least = {"setuptools": "84.2.1", "djangorestframework": "3.18.3"}
    behind = {name: locked[name] for name, floor in at_least.items() if version(locked[name]) < version(floor)}
    assert behind == {}, behind


def test_the_tesseract_work_folder_is_assigned_once_where_it_is_used():
    # DOC534.263: it was set before the `if` and again inside it, the same way; only the inner one is read
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert script.count('$work = ') == 1
    assert script.index('$work = ') > script.index("if (-not $install) {")                 # inside the block that uses it


def test_the_progress_bar_is_off_before_the_first_download():
    # DOC534.158: on Windows PowerShell 5.1 the progress bar of Invoke-WebRequest makes a big download many times slower
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert '$ProgressPreference = "SilentlyContinue"' in script
    assert script.index('$ProgressPreference = "SilentlyContinue"') < script.index("Invoke-WebRequest")


def test_from_takes_the_pinned_language_files_it_already_holds_and_downloads_only_the_others():
    # DOC534.157: -From claimed to skip the download, yet the three language files were always fetched, so an offline build failed
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "skips the download and the installer" not in script
    local = script.index('$local = Join-Path $install "tessdata\\$lang.traineddata"')
    assert "(Get-GitBlobId $local) -eq $blobIds[$lang]" in script[local:local + 200]       # taken only when it is THE pinned file
    assert local < script.index("Invoke-WebRequest -UseBasicParsing -Uri \"https://raw") < script.index("$blob = Get-GitBlobId $target")


def test_a_tesseract_package_without_a_licence_text_is_a_failure_not_a_silent_omission():
    # DOC534.156: Copy-Item ... -ErrorAction SilentlyContinue let the package go out with no licence at all
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert 'LICENSE-Tesseract.txt") -ErrorAction' not in script
    assert "if ($licences.Count -eq 0) { throw " in script
    assert script.index("if ($licences.Count -eq 0) { throw ") < script.index("foreach ($file in $licences)") < script.index('Write-Host "Prepared')


def test_the_tesseract_script_does_not_promise_that_nothing_stays_installed():
    # DOC534.155: the header said nothing is left on the machine, but the NSIS installer is run and never uninstalled
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "nothing is left installed" not in script and "never into the system" not in script
    head = script[:script.index("param(")]
    assert "not uninstalled" in head and "uninstall entry" in head and "-From" in head


def test_the_tesseract_installer_is_never_run_without_a_hash_to_check_it_against():
    # DOC534.45: "SHA256_PLACEHOLDER" switched the check off and the downloaded installer was run and shipped unchecked
    script = (PACKAGING / "fetch_tesseract.ps1").read_text(encoding="utf-8")
    assert "SHA256_PLACEHOLDER" not in script
    assert "if (-not $expected) { throw " in script and "if ($actual -ne $expected) { throw " in script   # no hash is a failure, a mismatch too
    assert "[string]$Sha256" in script                                           # the hash can be given without editing the script
    run = script.index("Start-Process -FilePath $installer")
    assert script.index("if (-not $expected) { throw ") < script.index("if ($actual -ne $expected) { throw ") < run   # both checks come first
