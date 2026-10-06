# Documents Manager

Local, private filing of personal documents. Drop PDFs in a folder: Documents Manager reads them (text layer, or local OCR for
scans), proposes a name and a destination folder, and files them when you approve. Everything stays on your machine: no document
leaves it, no cloud service is used (Ollama on `localhost` is an optional extra).

- **To file**: a PDF preview, the proposed company / type / date / amount, a score per field, corrections, batch approval.
- **Learns from your corrections**: correct a document once and the company, type and destination are remembered.
- **Safe by design**: nothing is moved without your approval (except what you explicitly mark automatic), nothing is ever
  overwritten, duplicates go to a quarantine folder, and every move can be undone from **History**.
- **Search** the full text of what you filed, **Dashboard** with the accuracy of the proposals, **Release notes** inside the app.
- Interface in English and French. Command line available (`docflow`).

> The program's internal name — used by its command, its services and its settings folder — is `docflow`.

## Install

**Windows (recommended):** download `DocumentsManager.exe` and double-click it. It opens a window already signed in (no password,
no account): the program runs only on your computer and listens on `127.0.0.1`. On the first run the **Settings** screen opens:
choose the folder to watch (the inbox) and the folder documents are filed into (the library). Then press **Scan inbox** in **To file**.
It files with the rights of your Windows session: a folder on a network drive works if the drive is connected in Windows.

**From source** (any system): Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+ and [Tesseract
OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) (scans only; PDFs that already contain text are read without it).

```bash
git clone <this repository> documents-manager && cd documents-manager
uv sync
cd frontend && npm ci && npm run build && cd ..
uv run python -m docflow.desktop                  # the same window as the .exe
```

To build the Windows executable: `packaging\build_windows.bat` on Windows.

## Where your data lives

Nothing you create is stored in the program's folder. In your own folder — `%LOCALAPPDATA%\DocFlow` on Windows,
`~/.config/docflow` elsewhere (override with `DOCFLOW_HOME`) — you find:

- `settings.yaml`: the folders chosen in the Settings screen.
- `learned/`: what the program learned from your corrections (company aliases, types, destinations).
- `config/` (optional): your own hand-written rule files (`companies.yaml`, `document_types.yaml`, `routing_rules.yaml`,
  `settings.yaml`); a file here replaces the generic one that ships in `config/`.

The database (`docflow.db`) holds, besides the filing history, the text read from each document so that **Search** works: give
it the same care as the documents themselves.

## Command line

```bash
uv run docflow scan --dry-run --table          # look only, nothing moves
uv run docflow scan --interactive              # files the automatic ones, asks for the rest
uv run docflow history ; uv run docflow undo [ID]
uv run docflow --sandbox ~/docflow-sandbox scan   # rehearsal: the real archive is not touched
uv run python scripts/make_sandbox.py ~/docflow-sandbox   # sample PDFs to try it on
uv run docflow --version
```

## Development

```bash
uv run pytest                                   # engine + API (the tests use their own rules and a throw-away data folder)
uv run mypy manage.py backend scripts tests
uvx ruff check backend scripts tests
cd frontend && npx tsc -b && npm run build
```

PyMuPDF is used by the tests only, to build sample PDFs; the program itself reads PDFs with PDFium (`pypdfium2`).

## License

[MIT](LICENSE). See `CHANGELOG.md` for the release notes.
