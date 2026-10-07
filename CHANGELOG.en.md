# Documents Manager — release notes

Format: newest version first; a number `major.minor.patch` (written once, in `pyproject.toml`). Minor: a new feature or behaviour.
Patch: a fix only. Major: a change that needs something from you before it starts.

## [0.4.3] - 2026-10-06

### Fixed
- **Learning a company**: when the document contains the company's name (e.g. "HelloFresh"), that name is kept as the rule, no
  longer the first line of the document (the title of a recipe or a letter, different every time). The company is then proposed
  on the next documents.

## [0.4.2] - 2026-10-06

### Fixed
- Windows: a scan no longer opens a console window for every page read by OCR.

### Changed
- The scan shows a progress bar (besides the counter on the button).

## [0.4.1] - 2026-10-06

### Fixed
- Documents queued while OCR was unavailable are read again at the next scan, once Tesseract is found (the "OCR is unavailable"
  message stayed on them because an unchanged file was not read again).

## [0.4.0] - 2026-10-06

### Added
- **Tesseract (OCR) bundled in the executable**, with French, English and orientation detection. Nothing to install to read
  scanned documents.

### Removed
- The "OCR is unavailable" message when Tesseract is not installed on the machine.

## [0.3.0] - 2026-10-06

Preparation for a public release under the MIT license.

### Added
- **Windows desktop application** (`DocumentsManager.exe`, built by `packaging/build_windows.bat`): a native window that starts
  the local server (`127.0.0.1`, never the network) and opens already signed in thanks to a one-time token, with no password to
  create. The database, the settings and the rules live in the user's folder. Tesseract (OCR, with French, English and
  orientation detection) is **bundled in the executable**: nothing to install.
- **"Settings" screen**: the folder to watch, the library, the quarantine and more folders to watch are chosen in the tool, with
  a folder picker and one message per field when something is wrong (folder not found, access refused, inbox and library
  the same, quarantine inside the library). They are saved in the user's folder, not in the program's. On a first run this
  screen opens by itself.
- **User rules outside the program**: what the user writes or the program learns lives in their own folder
  (`%LOCALAPPDATA%\DocFlow` on Windows, `~/.config/docflow` elsewhere). The rules that ship are empty: no company, destination
  or folder of the author.
- **Release notes in English and French**: the screen follows the interface language.

### Removed
- **Everything that only served the server mode**: password sign-in, log-out, the sign-in attempt limit, the host list
  (`DOCFLOW_HOSTS`), the systemd service templates (`deploy/`), `gunicorn`, and the `backup` command. The program now listens on
  `127.0.0.1` only and has no password: only the launcher's token sign-in exists.

### Changed
- **Product name: Documents Manager** (page title, browser tab, README and these notes). The internal name `docflow` (command,
  folders, services, `DOCFLOW_*` variables) is kept: changing it would break an existing installation.
- **PDF reading: PyMuPDF (AGPL) is replaced by PDFium** (through `pypdfium2`, Apache-2.0/BSD). The program no longer contains any
  copyleft library, which allows publishing it under the MIT license. PDFium is not safe in parallel: every call into it goes
  through a lock (OCR, the slow part, stays outside). PyMuPDF is now used only to build sample PDFs in the tests (a development
  dependency).

## [0.2.0] - 2026-10-05

A complete correction pass (audit 474: 457 findings, all handled). Nothing applies to a running service until it is restarted.

### Added
- **Backup**: `manage.py backup` takes a consistent snapshot of the database (even while the service works) and copies the learned
  rules into a dated folder, keeps the 14 newest, and refuses to write if the share is not mounted; `--restore` puts one back. A
  nightly timer is ready in `deploy/`.
- **Version**: `docflow --version`, and the number is shown in the page header.
- **Release notes**: a "Release notes" tab shows this file, newest version first.
- **Dashboard**: the counters are announced to screen readers when they change; a warning appears if the automatic refresh fails
  (figures may be out of date).
- **"To file" screen**: the open document and what was typed in it survive a change of filter, even when it is not in the new
  category (it stays at the top of the list, with a note); the confirmation to forget a rule names the company and the pattern.
- **"Approve all (auto)"**: files at most 200 documents per press and says how many automatic ones are still waiting.
- **Confidence colours** follow the engine's real thresholds (`/api/thresholds`).
- **Quality**: mypy without errors, ruff configured in `pyproject.toml`, French typography (no-break spaces).

### Fixed
- **Filing**: a file is no longer left in two places if deleting the source fails; an interrupted cross-volume copy leaves no
  partial file; reserved Windows names and trailing dots or spaces are refused; amounts (sign, currency, whole numbers,
  fractions) are read better; French month abbreviations; "overdue" and "residue" are no longer taken for a due date; a company
  or detail written in another alphabet (Cyrillic, Greek, Arabic, CJK) is kept instead of erased.
- **Concurrency**: approval locks, two simultaneous scans, and a scan that works on a snapshot of the rules.
- **OCR**: a time budget shared per page, a pixel limit, native text not duplicated, Tesseract failures logged, Tesseract looked up once.
- **Local model**: the document text is delimited in the prompt, the answer is bounded, and a date or an amount the model reads
  differently from the (confident) rules is flagged and scored 0.
- **Interface**: translated errors, loading states announced, History and Search without stale results, confidence also given by a
  symbol and a word, contrasts, tabs that scroll instead of being cut.
- **Server**: `/api` without a slash returns JSON, `index.html` is no longer cached, the secret and the cache follow the sandbox.

### To deploy (nothing was done for you)
1. Stop the service.
2. `uv run python manage.py migrate` (migrations 0009, 0010, 0011).
3. `cd frontend && npm run build`.
4. Copy `deploy/docflow-web.service` to `/etc/systemd/system/` (it now sets `DOCFLOW_HOSTS`), then `sudo systemctl daemon-reload`.
   **Required**: without `DOCFLOW_HOSTS` the site answers to `localhost` only.
5. Start the service; install the backup timer if not done yet (see the README).

## [0.1.0] - 2026-10-04

Starting version of the audit: the filing engine (local OCR, learned rules), the web interface, full-text search.
