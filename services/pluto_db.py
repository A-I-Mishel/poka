"""Per-user SQLite vault database: an app-like store for the agent.

One file per user (`pluto.db` in their vault, created lazily on first
write — never on mere store construction). The agent reads with plain
SELECT and writes through a confirmation-gated path. Containment rules:

- Table/column identifiers are validated ([A-Za-z_][A-Za-z0-9_]*);
  anything else is rejected before touching SQLite.
- The read path accepts a single SELECT/WITH/EXPLAIN statement only.
- ATTACH/DETACH are rejected everywhere (no vault escape).
- One short-lived connection per operation (thread-safe by construction).
- Failures return structured errors; this module never raises into tools.
"""

import csv
import io
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from services.obs import event as obs_event
from services.storage import user_dir

DB_FILENAME = "pluto.db"
MAX_ROWS = 5000
MAX_CELL_CHARS = 10000
MAX_TABLES_LISTED = 100

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ATTACH_RE = re.compile(r"\b(attach|detach)\b", re.IGNORECASE)
_READ_RE = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE | re.DOTALL)


def _db_path(user_id: Any) -> Path:
    return user_dir(str(user_id or ""), create=False) / DB_FILENAME


def _safe_db_error(action: str, exc: Exception) -> str:
    """User-safe DB failure (never echoes SQL, paths, or driver detail)."""
    obs_event("database.error", action=action, errkind=type(exc).__name__)
    return "Database %s failed (check table/column names and syntax)." % action


def valid_identifier(name: Any) -> str:
    """Validated table/column name, or "" when unsafe."""
    text = str(name or "")
    if len(text) > 64 or not _IDENT_RE.match(text):
        return ""
    return text


def _connect(user_id: Any) -> sqlite3.Connection:
    path = _db_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def list_tables(user_id: Any) -> List[str]:
    """User table names (never raises; [] when empty/missing)."""
    try:
        path = _db_path(user_id)
        if not path.exists():
            return []
        with _connect(user_id) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT ?",
                (MAX_TABLES_LISTED,),
            ).fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        return []


def describe_table(user_id: Any, table: str) -> Dict[str, Any]:
    """Columns + row count for one table (validated name)."""
    name = valid_identifier(table)
    if not name:
        return {"error": "Unsafe table name rejected."}
    try:
        with _connect(user_id) as conn:
            cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
            if not cols:
                return {"error": "Unknown table."}
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
        return {
            "name": name,
            "columns": [{"name": str(c[1]), "type": str(c[2] or "")} for c in cols],
            "rows": int(count[0]) if count else 0,
        }
    except Exception as e:
        return {"error": _safe_db_error("describe", e)}


def query(user_id: Any, sql: str, max_rows: int = 200) -> Dict[str, Any]:
    """Read-only query: single SELECT/WITH/EXPLAIN, capped rows."""
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return {"error": "Empty query."}
    if _ATTACH_RE.search(text):
        return {"error": "ATTACH/DETACH are not allowed."}
    if not _READ_RE.match(text):
        return {"error": "Read path accepts SELECT/WITH/EXPLAIN only."}
    try:
        with _connect(user_id) as conn:
            cur = conn.execute(text)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max(1, min(int(max_rows or 200), MAX_ROWS)))
        return {
            "columns": [str(c) for c in cols],
            "rows": [[_cell(v) for v in r] for r in rows],
        }
    except Exception as e:
        return {"error": _safe_db_error("query", e)}


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    text = str(value)
    return text[:MAX_CELL_CHARS] if len(text) > MAX_CELL_CHARS else text


def execute_write(user_id: Any, sql: str) -> Dict[str, Any]:
    """Run one write statement (CREATE/INSERT/UPDATE/DELETE/...).

    Single statement only; ATTACH/DETACH rejected. Returns rowcount.
    The tool layer gates on explicit user confirmation.
    """
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return {"error": "Empty statement."}
    if _ATTACH_RE.search(text):
        return {"error": "ATTACH/DETACH are not allowed."}
    if _READ_RE.match(text):
        return {"error": "Use the read path for SELECT queries."}
    try:
        with _connect(user_id) as conn:
            cur = conn.execute(text)
            conn.commit()
            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        return {"ok": True, "affected": int(affected)}
    except Exception as e:
        return {"error": _safe_db_error("write", e)}


def _affinity(values: List[str]) -> str:
    """SQLite column affinity from sample values (INTEGER/REAL/TEXT)."""
    INTEGER_RE = re.compile(r"^[+-]?\d+$")
    REAL_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
    kind = "INTEGER"
    for v in values:
        if v == "" or v is None:
            continue
        if kind == "INTEGER" and INTEGER_RE.match(v):
            continue
        if REAL_RE.match(v):
            kind = "REAL"
            continue
        return "TEXT"
    return kind


def import_csv(user_id: Any, table: str, data: bytes) -> Dict[str, Any]:
    """Create/replace a table from CSV bytes. Returns {table, rows, columns}."""
    name = valid_identifier(table)
    if not name:
        return {"error": "Unsafe table name rejected."}
    try:
        text = bytes(data or b"").decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return {"error": "CSV is empty."}
        columns = []
        for i, raw in enumerate(header):
            clean = re.sub(r"[^A-Za-z0-9_]", "_", str(raw or "").strip())
            if not clean or (not clean[0].isalpha() and clean[0] != "_"):
                clean = ("c_%d_%s" % (i, clean)) if clean else ("c_%d" % i)
            columns.append(clean[:64])
        if len(set(columns)) != len(columns):
            return {"error": "Duplicate column names after sanitizing."}
        rows = [r for r in reader if any((c or "").strip() for c in r)]
        rows = rows[:MAX_ROWS]
        affinities = [_affinity([r[i] if i < len(r) else "" for r in rows]) for i in range(len(columns))]
        padded = [[(r[i] if i < len(r) else "") for i in range(len(columns))] for r in rows]
        with _connect(user_id) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
            conn.execute(
                "CREATE TABLE %s (%s)" % (
                    name, ", ".join('%s %s' % (c, a) for c, a in zip(columns, affinities))))
            conn.executemany(
                "INSERT INTO %s VALUES (%s)" % (name, ", ".join("?" * len(columns))), padded)
            conn.commit()
        return {"table": name, "rows": len(padded), "columns": columns}
    except Exception as e:
        return {"error": _safe_db_error("import", e)}
