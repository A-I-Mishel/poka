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
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from services.obs import event as obs_event
from services.storage import user_dir

logger = logging.getLogger(__name__)


def _snapshot_notify() -> None:
    """Queue an R2 snapshot after a DB write (no-op; never raises)."""
    try:
        from services.snapshots import notify as _snapshots_notify

        _snapshots_notify()
    except Exception:
        logger.debug("snapshot notify failed", exc_info=True)


DB_FILENAME = "pluto.db"
MAX_ROWS = 5000
MAX_CELL_CHARS = 10000
MAX_TABLES_LISTED = 100

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ATTACH_RE = re.compile(r"\b(attach|detach)\b", re.IGNORECASE)
_READ_RE = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE | re.DOTALL)
_WRITE_RE = re.compile(r"^\s*(create|insert|update|delete|drop|alter|replace|truncate)\b", re.IGNORECASE)
# For read-path hardening: any of these outside string literals means non-SELECT.
_WRITE_TOKENS_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|pragma|vacuum|reindex|analyze)\b",
    re.IGNORECASE,
)


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


def _connect(user_id: Any, read_only: bool = False) -> sqlite3.Connection:
    path = _db_path(user_id)
    if read_only:
        # Reads must not create vault files for ephemeral users.
        if not path.exists():
            raise FileNotFoundError("no database")
        uri = "file:%s?mode=ro" % path.as_uri().split("file:", 1)[-1]
        try:
            conn = sqlite3.connect(uri, timeout=10.0, uri=True)
        except Exception:
            conn = sqlite3.connect(str(path), timeout=10.0)
        try:
            conn.execute("PRAGMA query_only=ON")
        except Exception:
            logger.debug("query_only pragma failed", exc_info=True)
        return conn
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


def _quote_ident(name: str) -> str:
    """Quote a validated identifier for use in SQL (defense-in-depth)."""
    # valid_identifier guarantees [A-Za-z_][A-Za-z0-9_]* so quoting is trivial
    return '"' + name.replace('"', '""') + '"'


def describe_table(user_id: Any, table: str) -> Dict[str, Any]:
    """Columns + row count for one table (validated name)."""
    name = valid_identifier(table)
    if not name:
        return {"error": "Unsafe table name rejected."}
    try:
        with _connect(user_id, read_only=True) as conn:
            # PRAGMA table_info does not support ? placeholder — use quoted ident
            qname = _quote_ident(name)
            cols = conn.execute(f"PRAGMA table_info({qname})").fetchall()  # noqa: S608 (validated + quoted identifier; PRAGMA takes no placeholders)
            if not cols:
                return {"error": "Unknown table."}
            count = conn.execute(f"SELECT COUNT(*) FROM {qname}").fetchone()  # noqa: S608 (validated + quoted identifier; values use placeholders)
        return {
            "name": name,
            "columns": [{"name": str(c[1]), "type": str(c[2] or "")} for c in cols],
            "rows": int(count[0]) if count else 0,
        }
    except Exception as e:
        return {"error": _safe_db_error("describe", e)}


def _strip_sql_literals(sql: str) -> str:
    """Return sql with string literals and comments replaced by spaces (for safe token checks)."""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        # single-quoted string '' escapes as ''
        if c == "'":
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # double-quoted identifier "" escapes as ""
        if c == '"':
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # line comment -- until newline (not inside strings, handled above)
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            out.append("  ")
            i += 2
            while i < n and sql[i] != "\n":
                i += 1
            continue
        # block comment /* ... */
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n:
                if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    i += 2
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _is_safe_read_sql(sql: str) -> str:
    """Validate read-only SQL. Returns "" when safe, else error message."""
    stripped = _strip_sql_literals(sql)
    # reject multi-statement (semicolon outside literals/comments)
    if ";" in stripped:
        return "Multiple statements are not allowed."
    if _ATTACH_RE.search(stripped):
        return "ATTACH/DETACH are not allowed."
    if not _READ_RE.match(stripped):
        return "Read path accepts SELECT/WITH/EXPLAIN only."
    # Peel leading WITH ... to find the outer verb; if WITH present, ensure
    # the final statement is SELECT/EXPLAIN SELECT and no write tokens appear
    # outside the CTE definitions in a way that indicates DML.
    # Simplest robust rule: after stripping literals, a read query must not
    # contain write verbs at all — a pure SELECT/WITH...SELECT never needs them.
    # This blocks WITH x AS (SELECT ...) DELETE ... and friends.
    # Allow only SELECT/EXPLAIN as top-level; write verbs inside strings already stripped.
    # Check for write tokens anywhere — safe because a legitimate SELECT never
    # contains DELETE/INSERT/UPDATE/etc as keywords outside strings.
    # Exception: allow the word inside CTE's inner SELECT's column aliases? Those would be quoted/aliases.
    # Keep strict: if any write token found, reject.
    if _WRITE_TOKENS_RE.search(stripped):
        # Need to distinguish CTE's inner SELECTs which are fine: they contain SELECT but not write verbs.
        # If a write verb appears, it's an injection like WITH ... DELETE or WITH ... PRAGMA.
        # Re-check more precisely: normal SELECT with a column named pragmatically safe?
        # Column names with those words would be without word boundaries due to underscore, so not matched.
        return "Read path does not allow write operations (use the approved write path)."
    # Final verb after optional WITH ... must be SELECT or EXPLAIN
    # Remove leading WITH ... by finding the last top-level SELECT/EXPLAIN
    # Heuristic: if stripped starts with WITH, ensure it contains a SELECT keyword after the CTEs
    lower = stripped.strip().lower()
    if lower.startswith("with"):
        # Must contain a SELECT after the CTE definitions; crude but effective:
        # locate the last occurrence of ') select' or 'select' that starts a query
        if not re.search(r"\bselect\b", stripped, re.IGNORECASE):
            return "WITH queries must end with SELECT."
        # Ensure after the final CTE's closing paren, the remainder starts with SELECT/EXPLAIN
        # For simplicity, ensure no write verb was found (already checked) — accept.
        pass
    # Additional: EXPLAIN must explain a SELECT, not a write
    if re.match(r"^\s*explain\b", stripped, re.IGNORECASE):
        after_explain = re.sub(r"^\s*explain(\s+query\s+plan)?\s+", "", stripped, flags=re.IGNORECASE)
        if _WRITE_TOKENS_RE.search(after_explain):
            return "EXPLAIN may only explain SELECT."
        if not re.match(r"^\s*(select|with)\b", after_explain, re.IGNORECASE):
            return "EXPLAIN may only explain SELECT."
    return ""


def query(user_id: Any, sql: str, max_rows: int = 200) -> Dict[str, Any]:
    """Read-only query: single SELECT/WITH/EXPLAIN, capped rows."""
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return {"error": "Empty query."}
    err = _is_safe_read_sql(text)
    if err:
        return {"error": err}
    try:
        with _connect(user_id, read_only=True) as conn:
            try:
                def _authorizer(action: int, _a: Any, _b: Any, _dbname: Any, _src: Any) -> int:
                    # Allow SELECT (21), READ (20), and EXPLAIN's internal reads.
                    # Deny everything else: INSERT/UPDATE/DELETE/DROP/etc.
                    # SQLITE_SELECT=21, SQLITE_READ=20 exist in stdlib sqlite3.
                    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}
                    # SQLITE_PRAGMA is not allowed on read path (except internal PRAGMA journal_mode elsewhere)
                    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

                conn.set_authorizer(_authorizer)  # type: ignore[arg-type]
            except Exception as e:
                return {"error": _safe_db_error("query (authorizer setup failed)", e)}
            cur = conn.execute(text)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max(1, min(int(max_rows or 200), MAX_ROWS)))
        return {
            "columns": [str(c) for c in cols],
            "rows": [[_cell(v) for v in r] for r in rows],
        }
    except Exception as e:
        # Authorizer denial surfaces as DatabaseError — map to user-safe message.
        if "not authorized" in str(e).lower() or "authorizer" in str(e).lower():
            return {"error": "Read path does not allow write operations (use the approved write path)."}
        return {"error": _safe_db_error("query", e)}


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    text = str(value)
    return text[:MAX_CELL_CHARS] if len(text) > MAX_CELL_CHARS else text


def execute_write(user_id: Any, sql: str) -> Dict[str, Any]:
    """Run one write statement (CREATE/INSERT/UPDATE/DELETE/...).

    Single statement only; ATTACH/DETACH rejected. PRAGMA/VACUUM and
    other non-DML verbs are rejected — allowlist only. Returns rowcount.
    The tool layer gates on explicit user confirmation.
    """
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        return {"error": "Empty statement."}
    stripped = _strip_sql_literals(text)
    if ";" in stripped:
        return {"error": "Multiple statements are not allowed."}
    if _ATTACH_RE.search(stripped):
        return {"error": "ATTACH/DETACH are not allowed."}
    if _READ_RE.match(stripped):
        return {"error": "Use the read path for SELECT queries."}
    if not _WRITE_RE.match(stripped):
        return {"error": "Write path accepts CREATE/INSERT/UPDATE/DELETE/DROP/ALTER/REPLACE/TRUNCATE only (PRAGMA/VACUUM not allowed)."}
    try:
        with _connect(user_id) as conn:
            cur = conn.execute(text)
            conn.commit()
            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        _snapshot_notify()
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
    from services.limits import MAX_CSV_PARSE_BYTES, MAX_CSV_COLUMNS

    name = valid_identifier(table)
    if not name:
        return {"error": "Unsafe table name rejected."}
    raw = bytes(data or b"")
    if len(raw) > MAX_CSV_PARSE_BYTES:
        return {"error": f"CSV too large (max {MAX_CSV_PARSE_BYTES} bytes)."}
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return {"error": "CSV is empty."}
        if len(header) > MAX_CSV_COLUMNS:
            return {"error": f"Too many columns (max {MAX_CSV_COLUMNS})."}
        columns = []
        for i, raw in enumerate(header):
            clean = re.sub(r"[^A-Za-z0-9_]", "_", str(raw or "").strip())
            if not clean or (not clean[0].isalpha() and clean[0] != "_"):
                clean = ("c_%d_%s" % (i, clean)) if clean else ("c_%d" % i)
            columns.append(clean[:64])
        if len(set(columns)) != len(columns):
            return {"error": "Duplicate column names after sanitizing."}
        rows: list = []
        for r in reader:
            if not any((c or "").strip() for c in r):
                continue
            rows.append(r)
            if len(rows) >= MAX_ROWS:
                break
        affinities = [_affinity([r[i] if i < len(r) else "" for r in rows]) for i in range(len(columns))]
        padded = [[(r[i] if i < len(r) else "") for i in range(len(columns))] for r in rows]
        with _connect(user_id) as conn:
            qname = _quote_ident(name)
            qcols = [_quote_ident(c) for c in columns]
            conn.execute(f"DROP TABLE IF EXISTS {qname}")
            conn.execute(
                f"CREATE TABLE {qname} ({', '.join(f'{qc} {a}' for qc, a in zip(qcols, affinities, strict=True))})")
            conn.executemany(
                f"INSERT INTO {qname} VALUES ({', '.join('?' * len(columns))})", padded  # noqa: S608 (validated + quoted identifier; values are placeholders)
            )
            conn.commit()
        _snapshot_notify()
        return {"table": name, "rows": len(padded), "columns": columns}
    except Exception as e:
        return {"error": _safe_db_error("import", e)}
