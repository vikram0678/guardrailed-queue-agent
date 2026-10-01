import os
import sys
import uuid
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from langgraph.types import Command

from src.database import DEFAULT_DB_PATH, init_db
from src.graph import build_graph
from src.operations import fetch_all_queue_items, insert_queue_item, restore_from_log

load_dotenv()


def run_agent(
    prompt: str,
    db_path: str = DEFAULT_DB_PATH,
    thread_id: Optional[str] = None,
    auto_approve: Optional[bool] = None,
) -> Dict[str, Any]:
    # Run agent loop and handle HITL interrupts
    init_db(db_path)
    graph = build_graph()

    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "messages": [{"role": "user", "content": prompt}],
        "db_path": db_path,
        "trust_threshold": int(os.getenv("TRUST_THRESHOLD", "3")),
    }

    result = graph.invoke(state, config=config)

    # Prompt user if halted at human review node
    current_state = graph.get_state(config)
    if current_state.next and "human_review_node" in current_state.next:
        payload = current_state.tasks[0].interrupts[0].value if current_state.tasks and current_state.tasks[0].interrupts else {}
        print(f"\n[APPROVAL REQUIRED] {payload.get('message', 'Approval needed')}")

        if auto_approve is not None:
            decision = "Y" if auto_approve else "N"
            print(f"[DECISION] Auto: {decision}")
        else:
            decision = input("Proceed? (Y/N): ").strip()

        result = graph.invoke(Command(resume=decision), config=config)

    return result


def display_queue(db_path: str = DEFAULT_DB_PATH) -> None:
    # Print current rows in content_queue
    items = fetch_all_queue_items(db_path)
    print("\n--- Queue State ---")
    if not items:
        print(" (empty)")
    for it in items:
        print(f" [{it['id']}] status={it['status']:<8} created={it['created_at']} | {it['content']}")
    print("-------------------\n")


def seed_sample_data(db_path: str = DEFAULT_DB_PATH) -> None:
    # Insert test items for demonstration
    init_db(db_path)
    posts = [
        ("post-101", "Product launch announcement", "pending"),
        ("post-102", "Weekly engineering newsletter #14", "pending"),
        ("post-103", "Payment webhook timeout retry", "failed"),
        ("post-104", "Deprecated campaign post from Q1", "failed"),
        ("post-105", "Customer highlight story", "pending"),
    ]
    for p_id, content, status in posts:
        insert_queue_item(p_id, content, status, db_path=db_path)
    print(f"Seeded {len(posts)} items into {db_path}")


if __name__ == "__main__":
    db = os.getenv("DATABASE_PATH", "app.db")
    init_db(db)

    # Handle CLI flags
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_sample_data(db)
        display_queue(db)
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        if len(sys.argv) < 3:
            print("Usage: python -m src.agent --restore <action_id>")
            sys.exit(1)
        action_uuid = sys.argv[2]
        ok = restore_from_log(action_uuid, db)
        print(f"Restore {'succeeded' if ok else 'failed'} for {action_uuid}")
        display_queue(db)
        sys.exit(0)

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Process pending posts"
    print(f"Instruction: '{query}'")
    display_queue(db)
    run_agent(query, db_path=db)
    display_queue(db)
