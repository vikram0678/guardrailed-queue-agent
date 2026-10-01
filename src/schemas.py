from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class MarkPosted(BaseModel):
    """Marks queue items as published."""
    row_ids: List[str] = Field(description="Row IDs to mark as posted")


class RetryRow(BaseModel):
    """Resets failed queue items for retry."""
    row_ids: List[str] = Field(description="Row IDs to reset to pending")


class PurgeStale(BaseModel):
    """Deletes stale or broken rows from queue."""
    row_ids: List[str] = Field(description="Row IDs to delete")


class ActionItem(BaseModel):
    type: str
    target_row_id: str
    details: Optional[Dict[str, Any]] = None


class AgentState(TypedDict, total=False):
    messages: List[Dict[str, Any]]
    queue_items: List[Dict[str, Any]]
    proposed_actions: List[Dict[str, Any]]
    human_feedback: Optional[str]
    execution_results: List[Dict[str, Any]]
    next_node: Optional[str]
    db_path: str
    trust_threshold: int
    interrupted: bool
