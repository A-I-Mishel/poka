"""Database tools: query the user's SQLite vault, import CSVs, gated writes.

Reads are free-form SELECT (single statement, capped rows); writes run
only with a server-minted single-use approval token from the
authenticated UI — never a model-supplied flag. Table names are
validated identifiers; ATTACH/DETACH are rejected everywhere.
"""

import logging
from typing import Any

from langchain_core.tools import tool

from services import pluto_db as db
from services.files import FileStore
from tools.gating import claim_tool_slot

logger: logging.Logger = logging.getLogger(__name__)


def _gate(tool_name: str):
    """User context + rate check, or (None, error)."""
    return claim_tool_slot(tool_name, "database", "Database")


@tool
def list_tables() -> str:
    """List tables in the user's database.

    Returns:
        Table names, or a structured failure marker (never silent).
    """
    user_id, err = _gate("list_tables")
    if user_id is None:
        return err
    tables = db.list_tables(user_id)
    if not tables:
        return "STATUS=EMPTY tool=list_tables: no tables yet. Import a CSV first."
    return "Tables:\n" + "\n".join("- " + t for t in tables)


@tool
def describe_table(table: str) -> str:
    """Show a table's columns and row count.

    Args:
        table: Table name (letters, digits, underscore).

    Returns:
        Column list + row count, or a structured failure marker.
    """
    user_id, err = _gate("describe_table")
    if user_id is None:
        return err
    info = db.describe_table(user_id, str(table or ""))
    if "error" in info:
        return f"STATUS=FAILED tool=describe_table: {info['error']}"
    cols = ", ".join("%s (%s)" % (c["name"], c["type"] or "?") for c in info["columns"])
    return f"Table {info['name']}: {info['rows']} rows. Columns: {cols}"


@tool
def query_database(sql: str, max_results: int = 50) -> str:
    """Run a read-only SELECT query against the user's database.

    Single SELECT/WITH/EXPLAIN statement, capped rows. Use
    list_tables/describe_table first to learn the schema.

    Args:
        sql: The SELECT query.
        max_results: Max rows (1-200).

    Returns:
        Columns + rows, or a structured failure marker (never silent).
    """
    user_id, err = _gate("query_database")
    if user_id is None:
        return err
    try:
        max_n = max(1, min(int(max_results or 50), 200))
    except (TypeError, ValueError):
        max_n = 50
    text_sql = str(sql or "")
    # Tool-side pre-check (defense in depth; service is authoritative).
    stripped = text_sql.strip().lstrip("(").strip()
    low = stripped.lower()
    if ";" in stripped.strip().rstrip(";"):
        return "STATUS=INVALID tool=query_database: multiple statements not allowed."
    if low.startswith(("attach", "detach", "insert", "update", "delete", "drop", "alter", "create", "replace")):
        return "STATUS=INVALID tool=query_database: use the approved write path for writes."
    result = db.query(user_id, text_sql, max_n)
    if "error" in result:
        return f"STATUS=FAILED tool=query_database: {result['error']}"
    if not result["rows"]:
        return "STATUS=EMPTY tool=query_database: no rows matched."
    def _cell(v: Any) -> str:
        s = str(v if v is not None else "")
        # Neutralize prompt/display injection + bound context: one line,
        # 200 chars per cell, 4000 chars total.
        s = s.replace("\r", " ").replace("\n", " ")
        return s[:200]
    lines = [" | ".join(_cell(c) for c in result["columns"])]
    lines += [" | ".join(_cell(v) for v in row) for row in result["rows"]]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n[Note: output truncated.]"
    return text


def _execute_import_csv_table(upload_id: str, table: str) -> str:
    """Import after authorization (gate + approval already checked)."""
    user_id, err = _gate("import_csv_table")
    if user_id is None:
        return err
    try:
        path = FileStore(user_id).resolve_upload(upload_id)
    except Exception as e:
        logger.warning("CSV import resolve failed: %s", e)
        path = None
    if path is None:
        return "STATUS=FAILED tool=import_csv_table: unknown upload."
    try:
        with open(str(path), "rb") as f:
            data = f.read(25 * 1024 * 1024 + 1)
    except OSError as e:
        return f"STATUS=FAILED tool=import_csv_table: cannot read upload ({str(e)[:200]})."
    result = db.import_csv(user_id, table, data)
    if "error" in result:
        return f"STATUS=FAILED tool=import_csv_table: {result['error']}"
    return ("STATUS=OK tool=import_csv_table table=%s rows=%d columns=%s"
            % (result["table"], result["rows"], ",".join(result["columns"])))


@tool
def import_csv_table(upload_id: str, table: str, approval_token: str = "") -> str:
    """Import an uploaded CSV as a database table (replaces same name).
    UI approval required.

    Call WITHOUT approval_token first (use an upload id from the
    conversation attachments). If the result is DENIED with an
    approval_id, describe the import and ask the user to approve it in
    the UI. Never invent an approval token.

    Args:
        upload_id: The staged upload id.
        table: New table name (letters, digits, underscore).
        approval_token: Server-minted single-use token (UI only).

    Returns:
        Table summary, or a structured failure marker (never silent).
    """
    from services import approvals as approvals_svc
    from services.context import get_current_user_id
    from services.context import get_limit_key as _glk
    from services.ratelimit import get_rate_limiter as _grl

    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=DENIED tool=import_csv_table: no user context."
    upload_id = str(upload_id or "").strip()
    if not upload_id:
        return "STATUS=INVALID tool=import_csv_table: empty upload id."
    try:
        known = FileStore(user_id).resolve_upload(upload_id) is not None
    except Exception:
        known = False
    if not known:
        return "STATUS=FAILED tool=import_csv_table: unknown upload."
    if not db.valid_identifier(str(table or "")):
        return "STATUS=INVALID tool=import_csv_table: bad table name."
    action = {"upload_id": upload_id, "table": str(table or "")}
    if approval_token:
        ok, stored = approvals_svc.consume_approval(
            user_id, "import_csv_table", action, str(approval_token))
        if not ok:
            return (
                "STATUS=DENIED tool=import_csv_table: approval token "
                f"invalid, expired, or already used ({stored}). Changed nothing."
            )
        action = stored
        # Re-validate server-stored values after consume.
        if not db.valid_identifier(str(action.get("table", "") or "")):
            return "STATUS=INVALID tool=import_csv_table: bad table name."
        try:
            known2 = FileStore(user_id).resolve_upload(str(action.get("upload_id", "") or "")) is not None
        except Exception:
            known2 = False
        if not known2:
            return "STATUS=FAILED tool=import_csv_table: unknown upload."
    else:
        try:
            _v = _grl().check(_glk() or user_id, "database")
            if not _v.allowed:
                return (
                    "STATUS=DENIED tool=import_csv_table: Database rate limit "
                    f"exceeded, retry in {_v.retry_after:.0f}s."
                )
        except Exception:
            logger.debug("import_csv staging rate-check failed", exc_info=True)
        summary = (f"Import upload into table {action['table'] or '?'} "
                   "(replaces any existing table of that name)")
        approval_id, _token, _created = approvals_svc.request_approval(
            user_id, "import_csv_table", action, summary)
        if not approval_id:
            return "STATUS=FAILED tool=import_csv_table: could not stage approval."
        return (
            "STATUS=DENIED tool=import_csv_table: approval required "
            f"(approval_id={approval_id}). {summary}. Changed nothing; ask "
            "the user to approve it in the UI."
        )
    return _execute_import_csv_table(action["upload_id"], action["table"])


def _execute_write_sql(sql: str) -> str:
    """Run a write after authorization (gate + approval already checked)."""
    user_id, err = _gate("execute_sql")
    if user_id is None:
        return err
    result = db.execute_write(user_id, sql)
    if "error" in result:
        return f"STATUS=FAILED tool=execute_sql: {result['error']}"
    return f"STATUS=OK tool=execute_sql affected={result['affected']}"


@tool
def execute_sql(sql: str, approval_token: str = "") -> str:
    """Run a write statement (CREATE/INSERT/UPDATE/DELETE). UI approval required.

    Call WITHOUT approval_token first. If the result is DENIED with an
    approval_id, describe the write and ask the user to approve it in the
    UI. SELECT belongs in query_database. ATTACH/DETACH are rejected.
    Never invent an approval token.

    Args:
        sql: One write statement.
        approval_token: Server-minted single-use token (UI only).

    Returns:
        Affected-row count, or a structured failure marker.
    """
    from services import approvals as approvals_svc
    from services.context import get_current_user_id
    from services.context import get_limit_key as _glk2
    from services.ratelimit import get_rate_limiter as _grl2

    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=DENIED tool=execute_sql: no user context."
    action = {"sql": str(sql or "")}
    if not action["sql"].strip():
        return "STATUS=INVALID tool=execute_sql: empty statement."
    if approval_token:
        ok, stored = approvals_svc.consume_approval(
            user_id, "execute_sql", action, str(approval_token))
        if not ok:
            return (
                "STATUS=DENIED tool=execute_sql: approval token invalid, "
                f"expired, or already used ({stored}). Changed nothing; use "
                "query_database for reads."
            )
        action = stored
        if not str(action.get("sql", "") or "").strip():
            return "STATUS=INVALID tool=execute_sql: empty statement."
    else:
        try:
            _v2 = _grl2().check(_glk2() or user_id, "database")
            if not _v2.allowed:
                return (
                    "STATUS=DENIED tool=execute_sql: Database rate limit "
                    f"exceeded, retry in {_v2.retry_after:.0f}s."
                )
        except Exception:
            logger.debug("execute_sql staging rate-check failed", exc_info=True)
        summary = f"Run write SQL: {action['sql'][:120]}"
        approval_id, _token, _created = approvals_svc.request_approval(
            user_id, "execute_sql", action, summary)
        if not approval_id:
            return "STATUS=FAILED tool=execute_sql: could not stage approval."
        return (
            "STATUS=DENIED tool=execute_sql: approval required "
            f"(approval_id={approval_id}). {summary}. Changed nothing; ask "
            "the user to approve it in the UI, or use query_database for reads."
        )
    return _execute_write_sql(action["sql"])
