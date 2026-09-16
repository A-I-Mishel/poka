"""Database tools: query the user's SQLite vault, import CSVs, gated writes.

Reads are free-form SELECT (single statement, capped rows); writes
need confirm=true, set only on explicit user request. Table names are
validated identifiers; ATTACH/DETACH are rejected everywhere.
"""

import logging

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
    result = db.query(user_id, str(sql or ""), max_n)
    if "error" in result:
        return f"STATUS=FAILED tool=query_database: {result['error']}"
    if not result["rows"]:
        return "STATUS=EMPTY tool=query_database: no rows matched."
    lines = [" | ".join(result["columns"])]
    lines += [" | ".join(str(v) for v in row) for row in result["rows"]]
    return "\n".join(lines)


@tool
def import_csv_table(upload_id: str, table: str) -> str:
    """Import an uploaded CSV as a database table (replaces same name).

    Use an upload id from the conversation attachments.

    Args:
        upload_id: The staged upload id.
        table: New table name (letters, digits, underscore).

    Returns:
        Table summary, or a structured failure marker (never silent).
    """
    user_id, err = _gate("import_csv_table")
    if user_id is None:
        return err
    if not str(upload_id or "").strip():
        return "STATUS=INVALID tool=import_csv_table: empty upload id."
    try:
        path = FileStore(user_id).resolve_upload(str(upload_id).strip())
    except Exception as e:
        logger.warning("CSV import resolve failed: %s", e)
        path = None
    if path is None:
        return "STATUS=FAILED tool=import_csv_table: unknown upload."
    try:
        with open(str(path), "rb") as f:
            data = f.read()
    except OSError as e:
        return f"STATUS=FAILED tool=import_csv_table: cannot read upload ({e})."
    result = db.import_csv(user_id, str(table or ""), data)
    if "error" in result:
        return f"STATUS=FAILED tool=import_csv_table: {result['error']}"
    return ("STATUS=OK tool=import_csv_table table=%s rows=%d columns=%s"
            % (result["table"], result["rows"], ",".join(result["columns"])))


@tool
def execute_sql(sql: str, confirm: bool = False) -> str:
    """Run a write statement (CREATE/INSERT/UPDATE/DELETE). confirm=true required.

    Set confirm=true ONLY when the user explicitly asked for that
    write. SELECT belongs in query_database. ATTACH/DETACH are rejected.

    Args:
        sql: One write statement.
        confirm: Must be true; false refuses safely.

    Returns:
        Affected-row count, or a structured failure marker.
    """
    user_id, err = _gate("execute_sql")
    if user_id is None:
        return err
    if confirm is not True:
        return (
            "STATUS=DENIED tool=execute_sql: writes need explicit user "
            "confirmation (confirm=true). Changed nothing; use "
            "query_database for reads."
        )
    result = db.execute_write(user_id, str(sql or ""))
    if "error" in result:
        return f"STATUS=FAILED tool=execute_sql: {result['error']}"
    return f"STATUS=OK tool=execute_sql affected={result['affected']}"
