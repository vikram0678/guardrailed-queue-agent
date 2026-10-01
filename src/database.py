import os
import sqlite3
from contextlib import contextmanager

DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "app.db")


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db_cursor(db_path: str = DEFAULT_DB_PATH):
    # Auto-commit and clean connection handling
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    # Initialize queue, action log, and trust metrics tables
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content_queue (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS action_log (
                action_id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target_row_id TEXT NOT NULL,
                previous_state_json TEXT NOT NULL,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trust_metrics (
                action_type TEXT PRIMARY KEY,
                successful_executions INTEGER DEFAULT 0
            );
            """
        )

        # Seed initial trust counters at 0
        for action_type in ("purge", "mark_posted", "retry"):
            cursor.execute(
                """
                INSERT OR IGNORE INTO trust_metrics (action_type, successful_executions)
                VALUES (?, 0)
                """,
                (action_type,),
            )


if __name__ == "__main__":
    db_file = os.getenv("DATABASE_PATH", "app.db")
    init_db(db_file)
    print(f"Database initialized at {db_file}")
