"""Database tests: lazy vaults, gated SQL, CSV import (all local)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services import pluto_db as db
from services.files import FileStore
from tools.database_tool import (
    describe_table,
    execute_sql,
    import_csv_table,
    list_tables,
    query_database,
)

CSV_BYTES = b"name,age,score\namy,30,9.5\nbob,25,8.0\n"


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("db-user")
    ctx.set_limit_key("db-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


def _db_file(tmp_path):
    return tmp_path / "data" / "users" / "db-user" / "pluto.db"


def test_lazy_no_file_until_write(tmp_path):
    assert db.list_tables("db-user") == []
    assert not _db_file(tmp_path).exists()


def test_import_csv_types_and_counts():
    res = db.import_csv("db-user", "people", CSV_BYTES)
    assert res == {"table": "people", "rows": 2, "columns": ["name", "age", "score"]}
    info = db.describe_table("db-user", "people")
    assert info["rows"] == 2
    types = {c["name"]: c["type"] for c in info["columns"]}
    assert types == {"name": "TEXT", "age": "INTEGER", "score": "REAL"}


def test_query_select_and_caps():
    db.import_csv("db-user", "people", CSV_BYTES)
    res = db.query("db-user", "SELECT name, age FROM people WHERE age > 26")
    assert res["columns"] == ["name", "age"]
    assert res["rows"] == [["amy", 30]]
    res = db.query("db-user", "SELECT * FROM people", max_rows=1)
    assert len(res["rows"]) == 1


def test_read_path_rejects_writes_and_attach():
    db.import_csv("db-user", "people", CSV_BYTES)
    assert "error" in db.query("db-user", "DROP TABLE people")
    assert "error" in db.query("db-user", "ATTACH 'x.db' AS x")
    assert db.list_tables("db-user") == ["people"]


def test_write_path_and_gates():
    db.import_csv("db-user", "people", CSV_BYTES)
    ok = db.execute_write("db-user", "INSERT INTO people VALUES ('cid', 40, 7.5)")
    assert ok == {"ok": True, "affected": 1}
    assert "error" in db.execute_write("db-user", "SELECT * FROM people")
    assert "error" in db.execute_write("db-user", "ATTACH 'x.db' AS x")
    assert "error" in db.execute_write("db-user", "")


def test_identifier_validation():
    assert db.valid_identifier("ok_name_1") == "ok_name_1"
    assert db.valid_identifier("x; DROP TABLE t") == ""
    assert db.valid_identifier("../vault") == ""
    assert db.describe_table("db-user", "x; DROP TABLE people")["error"].startswith("Unsafe")
    assert "error" in db.import_csv("db-user", "bad-name!", CSV_BYTES)


def test_per_user_isolation():
    db.import_csv("db-user", "people", CSV_BYTES)
    assert db.list_tables("other-user") == []
    assert db.query("other-user", "SELECT * FROM people")["error"].startswith("Database query failed")


def test_tool_flow_end_to_end():
    meta = FileStore("db-user").save_upload(CSV_BYTES, "team.csv")
    out = import_csv_table.invoke({"upload_id": meta.id, "table": "team"})
    assert "rows=2" in out
    out = list_tables.invoke({})
    assert "team" in out
    out = describe_table.invoke({"table": "team"})
    assert "2 rows" in out and "age" in out
    out = query_database.invoke({"sql": "SELECT name FROM team WHERE age < 28"})
    assert "bob" in out and "amy" not in out
    denied = execute_sql.invoke({"sql": "DELETE FROM team"})
    assert denied.startswith("STATUS=DENIED")
    ok = execute_sql.invoke({"sql": "DELETE FROM team WHERE age < 28", "confirm": True})
    assert "affected=1" in ok
    assert query_database.invoke({"sql": "SELECT COUNT(*) FROM team"}) is not None


def test_tool_unknown_upload():
    assert import_csv_table.invoke(
        {"upload_id": "deadbeefdeadbeef", "table": "t"}).startswith("STATUS=FAILED")


def test_no_user_denied():
    ctx.set_current_user_id(None)
    assert list_tables.invoke({}).startswith("STATUS=DENIED")
