import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from langsmith import traceable

from src.database import DEFAULT_DB_PATH, get_db_connection


@traceable(name="execute_mutation")
def execute_mutation(
    action_type: str,
    target_row_id: str,
    new_data: Optional[Dict[str, Any]] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[str]:
    # Mutates row after saving pre-mutation JSON to action_log
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM content_queue WHERE id = ?", (target_row_id,))
        row = cursor.fetchone()
        if not row:
            return None

        # Capture pre-mutation state snapshot
        previous_state_json = json.dumps({
            "id": row["id"],
            "content": row["content"],
            "status": row["status"],
            "created_at": row["created_at"],
        })

        # Commit undo log entry
        action_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO action_log (action_id, action_type, target_row_id, previous_state_json)
            VALUES (?, ?, ?, ?)
            """,
            (action_id, action_type, target_row_id, previous_state_json),
        )

        # Apply state change to queue
        action = action_type.lower()
        if action in ("purge", "delete"):
            cursor.execute("DELETE FROM content_queue WHERE id = ?", (target_row_id,))
        elif action in ("mark_posted", "posted"):
            cursor.execute("UPDATE content_queue SET status = 'posted' WHERE id = ?", (target_row_id,))
        elif action in ("retry", "retry_row"):
            cursor.execute("UPDATE content_queue SET status = 'pending' WHERE id = ?", (target_row_id,))
        elif new_data:
            fields = [f"{k} = ?" for k in new_data if k != "id"]
            if fields:
                values = [new_data[k] for k in new_data if k != "id"] + [target_row_id]
                cursor.execute(f"UPDATE content_queue SET {', '.join(fields)} WHERE id = ?", tuple(values))

        conn.commit()
        return action_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@traceable(name="restore_from_log")
def restore_from_log(action_id: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    # Restores row state using historical snapshot from action_log
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT previous_state_json FROM action_log WHERE action_id = ?", (action_id,))
        result = cursor.fetchone()
        if not result:
            return False

        # Overwrite current state with historical snapshot
        state = json.loads(result["previous_state_json"])
        cursor.execute(
            """
            REPLACE INTO content_queue (id, content, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (state["id"], state["content"], state["status"], state["created_at"]),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@traceable(name="get_trust_score")
def get_trust_score(action_type: str, db_path: str = DEFAULT_DB_PATH) -> int:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT successful_executions FROM trust_metrics WHERE action_type = ?", (action_type,))
        row = cursor.fetchone()
        return int(row["successful_executions"]) if row else 0
    finally:
        conn.close()


@traceable(name="increment_trust")
def increment_trust(action_type: str, db_path: str = DEFAULT_DB_PATH) -> int:
    # Increment approved execution counter
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO trust_metrics (action_type, successful_executions)
            VALUES (?, 1)
            ON CONFLICT(action_type) DO UPDATE SET successful_executions = successful_executions + 1
            """,
            (action_type,),
        )
        conn.commit()
        cursor.execute("SELECT successful_executions FROM trust_metrics WHERE action_type = ?", (action_type,))
        row = cursor.fetchone()
        return int(row["successful_executions"]) if row else 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_trust_score(action_type: str, score: int, db_path: str = DEFAULT_DB_PATH) -> None:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO trust_metrics (action_type, successful_executions)
            VALUES (?, ?)
            ON CONFLICT(action_type) DO UPDATE SET successful_executions = ?
            """,
            (action_type, score, score),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_queue_item(
    item_id: str,
    content: str,
    status: str = "pending",
    created_at: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        if created_at:
            cursor.execute(
                "REPLACE INTO content_queue (id, content, status, created_at) VALUES (?, ?, ?, ?)",
                (item_id, content, status, created_at),
            )
        else:
            cursor.execute(
                "REPLACE INTO content_queue (id, content, status) VALUES (?, ?, ?)",
                (item_id, content, status),
            )
        conn.commit()
    finally:
        conn.close()


def fetch_all_queue_items(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, content, status, created_at FROM content_queue ORDER BY created_at ASC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
