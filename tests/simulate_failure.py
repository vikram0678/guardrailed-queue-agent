import os
import sys
import tempfile
import uuid

# Add root directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.types import Command
from src.database import init_db
from src.graph import build_graph
from src.operations import (
    fetch_all_queue_items,
    insert_queue_item,
    restore_from_log,
    set_trust_score,
    get_trust_score,
)


def run_simulation() -> None:
    # Set up isolated test database
    fd, temp_db = tempfile.mkstemp(suffix="_sim.db")
    os.close(fd)
    init_db(temp_db)

    # Seed 10 sample posts
    initial_items = [
        (f"post-{i:03d}", f"Queue post #{i}", "failed" if i % 2 == 0 else "pending")
        for i in range(1, 11)
    ]
    for p_id, content, status in initial_items:
        insert_queue_item(p_id, content, status, db_path=temp_db)

    assert len(fetch_all_queue_items(temp_db)) == 10

    # Force low trust to test human approval requirement
    set_trust_score("purge", 0, db_path=temp_db)
    assert get_trust_score("purge", temp_db) == 0

    # Run ambiguous cleanup prompt through agent
    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    state = {
        "messages": [{"role": "user", "content": "Cleanup the queue, remove anything stale or old."}],
        "db_path": temp_db,
        "trust_threshold": 3,
    }

    graph.invoke(state, config=config)

    # Ensure graph paused at human review and left queue untouched
    cur_state = graph.get_state(config)
    assert cur_state.next and "human_review_node" in cur_state.next
    assert len(fetch_all_queue_items(temp_db)) == 10

    # Resume graph execution with operator approval
    graph.invoke(Command(resume="Y"), config=config)

    final_state = graph.get_state(config)
    results = final_state.values.get("execution_results", [])
    assert len(results) > 0
    assert len(fetch_all_queue_items(temp_db)) == 0

    # Revert all deletions using undo log
    action_ids = [r["action_id"] for r in results]
    for aid in action_ids:
        assert restore_from_log(aid, db_path=temp_db) is True

    restored = fetch_all_queue_items(temp_db)
    assert len(restored) == 10
    assert {r["id"] for r in restored} == {item[0] for item in initial_items}

    # Verify high-trust actions execute without pausing
    set_trust_score("purge", 5, db_path=temp_db)
    auto_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    auto_state = {
        "messages": [{"role": "user", "content": "Cleanup stale items"}],
        "db_path": temp_db,
        "trust_threshold": 3,
    }
    graph.invoke(auto_state, config=auto_config)
    assert not graph.get_state(auto_config).next

    # Clean up test database file
    if os.path.exists(temp_db):
        os.remove(temp_db)

    print("All simulation safety checks passed successfully.")


if __name__ == "__main__":
    run_simulation()
