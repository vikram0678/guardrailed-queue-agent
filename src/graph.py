import os
from typing import Any, Dict, List, Literal, Optional
from langsmith import traceable
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from src.database import DEFAULT_DB_PATH
from src.operations import (
    execute_mutation,
    fetch_all_queue_items,
    get_trust_score,
    increment_trust,
)
from src.schemas import AgentState, MarkPosted, RetryRow, PurgeStale

DEFAULT_TRUST_THRESHOLD = int(os.getenv("TRUST_THRESHOLD", "3"))


def get_configured_llm():
    # Detect OpenAI or OpenRouter based on environment keys
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if openai_key.startswith("sk-or-"):
        openrouter_key = openai_key
        openai_key = ""

    if openai_key and openai_key.startswith("sk-") and not openai_key.endswith("your_openai_api_key_here"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
                api_key=openai_key,
                temperature=0,
            )
        except Exception:
            pass

    if openrouter_key and not openrouter_key.startswith("your_"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.getenv("OPENROUTER_MODEL_NAME", "meta-llama/llama-3.3-70b-instruct:free"),
                api_key=openrouter_key,
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                temperature=0,
            )
        except Exception:
            pass

    return None


@traceable(name="perceive_node")
def perceive_node(state: AgentState) -> Dict[str, Any]:
    # Read active queue items from database
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    return {"queue_items": fetch_all_queue_items(db_path)}


def _plan_fallback(prompt: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Fallback heuristic parser when no LLM is configured
    p = prompt.lower()
    proposed = []
    if any(k in p for k in ("cleanup", "purge", "delete", "remove", "stale", "clean")):
        for item in items:
            if item.get("status") in ("failed", "stale", "pending") or "cleanup" in p or "all" in p:
                proposed.append({"type": "purge", "target_row_id": item["id"]})
    elif any(k in p for k in ("post", "mark_posted", "publish")):
        for item in items:
            if item.get("status") == "pending":
                proposed.append({"type": "mark_posted", "target_row_id": item["id"]})
    elif "retry" in p:
        for item in items:
            if item.get("status") == "failed":
                proposed.append({"type": "retry", "target_row_id": item["id"]})
    return proposed


@traceable(name="plan_node")
def plan_node(state: AgentState) -> Dict[str, Any]:
    messages = state.get("messages", [])
    queue_items = state.get("queue_items", [])
    human_feedback = state.get("human_feedback")

    # Halt if operator rejected previous plan
    if human_feedback and "rejected" in human_feedback.lower():
        return {
            "proposed_actions": [],
            "messages": messages + [{"role": "assistant", "content": "Action proposal rejected by operator."}]
        }

    user_prompt = ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            user_prompt = msg.get("content", "")
            break
        elif hasattr(msg, "content"):
            user_prompt = str(msg.content)
            break

    llm = get_configured_llm()
    proposed_actions = []

    # Propose tool actions using LLM or heuristic fallback
    if llm is not None:
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            llm_with_tools = llm.bind_tools([MarkPosted, RetryRow, PurgeStale])

            system_msg = (
                f"Active queue state:\n{queue_items}\n"
                "Select appropriate tools (PurgeStale, MarkPosted, RetryRow) based on user instructions."
            )
            res = llm_with_tools.invoke([
                SystemMessage(content=system_msg),
                HumanMessage(content=user_prompt)
            ])

            if hasattr(res, "tool_calls") and res.tool_calls:
                for tc in res.tool_calls:
                    name = tc["name"]
                    row_ids = tc.get("args", {}).get("row_ids", [])
                    action_type = "purge" if name == "PurgeStale" else ("mark_posted" if name == "MarkPosted" else "retry")
                    for r_id in row_ids:
                        proposed_actions.append({"type": action_type, "target_row_id": str(r_id)})

            if not proposed_actions:
                proposed_actions = _plan_fallback(user_prompt, queue_items)
        except Exception:
            proposed_actions = _plan_fallback(user_prompt, queue_items)
    else:
        proposed_actions = _plan_fallback(user_prompt, queue_items)

    return {"proposed_actions": proposed_actions, "human_feedback": None}


@traceable(name="check_trust_node")
def check_trust_node(state: AgentState) -> Dict[str, Any]:
    proposed = state.get("proposed_actions", [])
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    threshold = state.get("trust_threshold", DEFAULT_TRUST_THRESHOLD)

    if not proposed:
        return {"next_node": "execute_node"}

    # Route to human review if any action is below trust threshold
    requires_approval = any(
        get_trust_score(act.get("type", ""), db_path) < threshold
        for act in proposed
    )
    return {"next_node": "human_review_node" if requires_approval else "execute_node"}


def route_trust_gate(state: AgentState) -> Literal["human_review_node", "execute_node"]:
    return state.get("next_node", "human_review_node")  # type: ignore


@traceable(name="human_review_node")
def human_review_node(state: AgentState) -> Dict[str, Any]:
    # Pause execution until operator approval is received
    actions = state.get("proposed_actions", [])
    decision = interrupt({
        "message": f"Action approval required for: {actions}. Proceed? (Y/N)",
        "proposed_actions": actions,
        "options": ["Y", "N"]
    })

    if str(decision).strip().upper() in ("Y", "YES", "APPROVED"):
        return {"next_node": "execute_node", "human_feedback": "approved"}
    return {"next_node": "plan_node", "human_feedback": "rejected by user"}


def route_human_review(state: AgentState) -> Literal["execute_node", "plan_node"]:
    return state.get("next_node", "execute_node")  # type: ignore


@traceable(name="execute_node")
def execute_node(state: AgentState) -> Dict[str, Any]:
    proposed = state.get("proposed_actions", [])
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    human_feedback = state.get("human_feedback")

    results = []
    executed_types = set()

    # Execute mutations with pre-mutation logging
    for act in proposed:
        action_type = act.get("type", "")
        row_id = act.get("target_row_id", "")
        details = act.get("details")

        action_id = execute_mutation(action_type, row_id, details, db_path)
        if action_id:
            results.append({
                "action_id": action_id,
                "action_type": action_type,
                "target_row_id": row_id,
                "status": "success",
            })
            executed_types.add(action_type)

    # Increment trust after approved execution
    if human_feedback == "approved":
        for a_type in executed_types:
            increment_trust(a_type, db_path)

    return {
        "execution_results": results,
        "queue_items": fetch_all_queue_items(db_path),
        "next_node": "END"
    }


def build_graph(checkpointer: Optional[Any] = None) -> StateGraph:
    # Construct LangGraph state machine
    builder = StateGraph(AgentState)

    builder.add_node("perceive_node", perceive_node)
    builder.add_node("plan_node", plan_node)
    builder.add_node("check_trust_node", check_trust_node)
    builder.add_node("human_review_node", human_review_node)
    builder.add_node("execute_node", execute_node)

    builder.add_edge(START, "perceive_node")
    builder.add_edge("perceive_node", "plan_node")
    builder.add_edge("plan_node", "check_trust_node")

    builder.add_conditional_edges(
        "check_trust_node",
        route_trust_gate,
        {"human_review_node": "human_review_node", "execute_node": "execute_node"},
    )

    builder.add_conditional_edges(
        "human_review_node",
        route_human_review,
        {"execute_node": "execute_node", "plan_node": "plan_node"},
    )

    builder.add_edge("execute_node", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())
