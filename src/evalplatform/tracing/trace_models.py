"""Pydantic models for eval tracing."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TraceSpan(BaseModel):
    span_id: str
    parent_id: str | None = None
    name: str
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    status: str = "ok"
    children: list[TraceSpan] = Field(default_factory=list)


# Required for forward reference in children field
TraceSpan.model_rebuild()


class EvalTrace(BaseModel):
    run_id: uuid.UUID
    root_span: TraceSpan
    total_spans: int
    total_duration_ms: float
