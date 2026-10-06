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

## Requirements

- Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/) (or pip).
- [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) with the language packs you need (`fra`, `eng`, …)
  for scanned documents. Without it, only PDFs that already contain text are read.
- Node.js 20+ only to build the web interface from source.

## Install and run

```bash
git clone <this repository> documents-manager && cd documents-manager
uv sync
cd frontend && npm ci && npm run build && cd ..          # builds the interface into frontend/dist
uv run python manage.py migrate                          # creates the database
uv run python manage.py createsuperuser                  # your login
uv run gunicorn webapp.wsgi:application --bind 127.0.0.1:8420
```

Open `http://127.0.0.1:8420`, sign in. On the first run the **Settings** screen opens: choose the folder to watch (the inbox)
and the folder documents are filed into (the library). Then press **Scan inbox** in **To file**.

By default the site answers to `localhost` only. To reach it from another computer, set `DOCFLOW_HOSTS` (comma separated host
names or addresses) before starting it, and keep it on a trusted network: it has no protection against the open internet.

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

## Backup

`uv run python manage.py backup` writes a dated, consistent snapshot of the database and your learned rules under `backup.dir`
(set it in `config/settings.yaml` of your own folder, e.g. `backup:` then `dir: /path/to/backups`; it adds to the shipped settings) and keeps the newest `backup.keep`. It refuses to run if that folder's parent does not exist
(an unmounted share). `--restore FOLDER` puts one back (stop the service first). `deploy/docflow-backup.timer` runs it nightly.

## Running as a service

`deploy/` holds systemd unit templates (`docflow-web`, `docflow-backup`): adapt the user and the paths, copy them to
`/etc/systemd/system/`, then `systemctl enable --now docflow-web`. Update: stop the service, `git pull`, `uv sync`,
`uv run python manage.py migrate`, rebuild the interface, start it. Run `migrate` before the workers start.

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
