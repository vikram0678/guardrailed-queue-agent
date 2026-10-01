import json
import os
import tempfile
import pytest

from src.database import init_db, get_db_connection
from src.operations import (
    execute_mutation,
    restore_from_log,
    insert_queue_item,
    fetch_all_queue_items,
    get_trust_score,
    increment_trust,
    set_trust_score,
)


@pytest.fixture
def temp_db():
    # Temporary database per test run
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_database_schema_integrity(temp_db):
    conn = get_db_connection(temp_db)
    cursor = conn.cursor()

    # Check table existence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r["name"] for r in cursor.fetchall()}
    assert {"content_queue", "action_log", "trust_metrics"}.issubset(tables)

    # Validate column definitions
    cursor.execute("PRAGMA table_info(content_queue)")
    cq_cols = {r["name"] for r in cursor.fetchall()}
    assert {"id", "content", "status", "created_at"}.issubset(cq_cols)

    cursor.execute("PRAGMA table_info(action_log)")
    al_cols = {r["name"] for r in cursor.fetchall()}
    assert {"action_id", "action_type", "target_row_id", "previous_state_json", "executed_at"}.issubset(al_cols)

    cursor.execute("PRAGMA table_info(trust_metrics)")
    tm_cols = {r["name"] for r in cursor.fetchall()}
    assert {"action_type", "successful_executions"}.issubset(tm_cols)
    conn.close()


def test_pre_mutation_logging_and_restore_deletion(temp_db):
    row_id = "post-001"
    content = "Critical announcement"
    status = "pending"
    ts = "2026-09-27 10:00:00"

    # Insert test record
    insert_queue_item(row_id, content, status, ts, db_path=temp_db)

    # Execute purge mutation
    action_id = execute_mutation("purge", row_id, db_path=temp_db)
    assert action_id is not None

    # Verify pre-mutation JSON was logged before delete
    conn = get_db_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM action_log WHERE action_id = ?", (action_id,))
    log = cursor.fetchone()
    assert log is not None
    assert log["action_type"] == "purge"
    assert log["target_row_id"] == row_id

    saved = json.loads(log["previous_state_json"])
    assert saved == {"id": row_id, "content": content, "status": status, "created_at": ts}

    # Verify record was deleted from active queue
    cursor.execute("SELECT * FROM content_queue WHERE id = ?", (row_id,))
    assert cursor.fetchone() is None
    conn.close()

    # Revert delete and verify original row is back
    assert restore_from_log(action_id, db_path=temp_db) is True
    items = fetch_all_queue_items(temp_db)
    assert len(items) == 1
    assert items[0] == {"id": row_id, "content": content, "status": status, "created_at": ts}


def test_restore_from_update(temp_db):
    row_id = "post-002"
    insert_queue_item(row_id, "Update test", "pending", db_path=temp_db)

    # Transition to posted
    action_id = execute_mutation("mark_posted", row_id, db_path=temp_db)
    assert action_id is not None
    assert fetch_all_queue_items(temp_db)[0]["status"] == "posted"

    # Rollback status change back to pending
    assert restore_from_log(action_id, db_path=temp_db) is True
    assert fetch_all_queue_items(temp_db)[0]["status"] == "pending"


def test_restore_invalid_action_id(temp_db):
    # Non-existent action ID should fail gracefully
    assert restore_from_log("invalid-id", db_path=temp_db) is False


def test_trust_metrics_tracking(temp_db):
    set_trust_score("purge", 0, db_path=temp_db)
    assert get_trust_score("purge", temp_db) == 0

    # Ensure counter increments sequentially
    assert increment_trust("purge", temp_db) == 1
    assert get_trust_score("purge", temp_db) == 1

    assert increment_trust("purge", temp_db) == 2
    assert get_trust_score("purge", temp_db) == 2
