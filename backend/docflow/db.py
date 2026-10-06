"""SQLite history. No OCR content is stored: only the extracted fields."""
import logging
import sqlite3
import time
from datetime import UTC, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, original_filename TEXT, final_filename TEXT, original_path TEXT,
  destination_path TEXT, sha256 TEXT NOT NULL, company TEXT, document_type TEXT, document_date TEXT,
  amount TEXT, currency TEXT, invoice_number TEXT, confidence REAL, source TEXT,
  created_at TEXT, processed_at TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_doc_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS operations (
  id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id), kind TEXT,
  src TEXT, dst TEXT, ts TEXT, undone INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_op_doc ON operations(document_id);
CREATE INDEX IF NOT EXISTS ix_doc_logical ON documents(company, invoice_number);
"""


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch the file to the write-ahead log, once. The mode is stored IN the file, so every later connection finds it set
    and only reads it. The switch itself does not honour the busy timeout when another connection is switching at the same
    moment (the first scan opens several connections together): wait a moment and look again. If it never works the
    database simply stays in the ordinary journal mode: slower under contention, never wrong."""
    for _ in range(100):
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            return
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:  # "database is locked": someone else is switching right now
            time.sleep(0.05)


def _row_id(cur: sqlite3.Cursor) -> int:
    """The id of the row an INSERT just created. sqlite3 types it `int | None` (None after anything but an INSERT): say so
    instead of returning a None that the callers would take for an id."""
    if cur.lastrowid is None:
        raise RuntimeError("the INSERT returned no row id")
    return cur.lastrowid


def now() -> str:
    """Local wall-clock time WITH its UTC offset ('2026-10-04T17:08:07-04:00'): readable as before, and the repeated hour of
    the autumn clock change stays unambiguous. Older rows are naive local times; both forms parse and display the same."""
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


class DB:
    """One SQLite connection. NOT shared between threads, by design: each thread (a web request, a scan worker)
    opens its own (see triage.services.engine_db). SQLite refuses cross-thread use of a connection, which is the
    right failure: sharing one behind a lock would only hide a design mistake."""

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # same policy as the site's connection (they share the file): wait up to 20 s for a lock instead of failing after
        # 5 s, and the write-ahead log (persistent in the file; it needs a local disk, as does SQLite's locking)
        self.c = sqlite3.connect(path, timeout=20)
        if str(path) != ":memory:":
            _enable_wal(self.c)
            self.c.execute("PRAGMA synchronous=NORMAL")
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys=ON")  # SQLite ignores REFERENCES otherwise; the setting is per connection
        self.c.executescript(SCHEMA)
        try:  # the database itself refuses a second FILED copy of the same content: two scans can both pass find_sha()
            self.c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_sha_filed ON documents(sha256) WHERE status='classified'")
        except sqlite3.IntegrityError:  # duplicates filed before this guard existed: keep working without it, never refuse to open
            log.warning("history already holds the same content filed twice: the uniqueness guard is not installed")
        self._document_columns = frozenset(r["name"] for r in self.c.execute("PRAGMA table_info(documents)"))

    def close(self) -> None:
        """Close the connection now (not when the garbage collector gets to it): it frees the file descriptor and lets SQLite
        checkpoint the write-ahead log. Closing twice is harmless."""
        self.c.close()

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def find_sha(self, sha: str):
        """Document already filed with this exact content."""
        return self.c.execute("SELECT * FROM documents WHERE sha256=? AND status='classified'", (sha,)).fetchone()

    def find_logical(self, company, invoice_number, date, amount):
        if not (company and invoice_number):
            return None
        # `IS ?` (not `= ?`) is NULL-safe: two absent dates match, and so do two absent amounts, while a ZERO amount is
        # an amount (`amount or ""` turned Decimal('0.00') into "absent")
        return self.c.execute(
            "SELECT * FROM documents WHERE status='classified' AND company=? AND invoice_number=? "
            "AND document_date IS ? AND amount IS ?",
            (company, invoice_number, date, None if amount is None else str(amount))).fetchone()

    def add_document(self, **f) -> int:
        if not f:
            raise ValueError("add_document: nothing to insert")
        unknown = sorted(set(f) - self._document_columns)
        if unknown:  # the keys become column names in the SQL text: only the table's own columns may get there
            raise ValueError(f"add_document: unknown column(s): {', '.join(unknown)}")
        f.setdefault("created_at", now())
        cols = ",".join(f)
        try:
            cur = self.c.execute(f"INSERT INTO documents ({cols}) VALUES ({','.join('?' * len(f))})", list(f.values()))
        except sqlite3.IntegrityError:  # the unique index above: another scan filed this content a moment ago
            self.c.rollback()
            raise ValueError("an identical document is already filed (SHA-256)") from None
        self.c.commit()
        return _row_id(cur)

    def add_op(self, doc_id: int, kind: str, src: str, dst: str) -> int:
        cur = self.c.execute("INSERT INTO operations (document_id,kind,src,dst,ts) VALUES (?,?,?,?,?)",
                             (doc_id, kind, src, dst, now()))
        self.c.commit()
        return _row_id(cur)

    def forget_document(self, doc_id: int) -> None:
        """Roll back a document row whose file move had to be undone (nothing references it yet)."""
        self.c.execute("DELETE FROM operations WHERE document_id=?", (doc_id,))
        self.c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        self.c.commit()

    def op(self, op_id: int | None):
        if op_id is None:
            return self.c.execute("SELECT * FROM operations WHERE undone=0 ORDER BY id DESC LIMIT 1").fetchone()
        return self.c.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()

    def document_sha(self, doc_id: int | None) -> str | None:
        """The SHA-256 recorded when the document was filed (None if the row is unknown)."""
        row = self.c.execute("SELECT sha256 FROM documents WHERE id=?", (doc_id,)).fetchone()
        return row["sha256"] if row else None

    def mark_undone(self, op: sqlite3.Row) -> None:
        cur = self.c.execute("UPDATE operations SET undone=1 WHERE id=? AND undone=0", (op["id"],))
        if cur.rowcount == 0:
            raise ValueError(f"operation {op['id']} is already undone")
        # the document stops being "filed" only once NONE of its operations is still in force
        self.c.execute(
            "UPDATE documents SET status='undone' WHERE id=? "
            "AND NOT EXISTS (SELECT 1 FROM operations WHERE document_id=? AND undone=0)",
            (op["document_id"], op["document_id"]))
        self.c.commit()

    def history(self, n: int = 20):
        return self.c.execute("SELECT o.id,o.kind,o.ts,o.undone,o.src,o.dst FROM operations o ORDER BY o.id DESC LIMIT ?",
                              (n,)).fetchall()
