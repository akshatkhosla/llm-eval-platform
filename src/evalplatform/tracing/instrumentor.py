"""In-process tracer: records spans during an eval run and builds a trace tree."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime

from evalplatform.tracing.trace_models import EvalTrace, TraceSpan


@dataclass
class SpanData:
    """Mutable span state while recording is in progress."""

    span_id: str
    parent_id: str | None
    name: str
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    status: str = "ok"


class Tracer:
    """Records spans in memory and exports a complete trace tree.

    Usage::

        tracer = Tracer(run_id)
        async with tracer.span("eval_run", provider="gemini") as root:
            async with tracer.span("sample_execution", sample_index=0):
                async with tracer.span("llm_call") as llm_span:
                    resp = await provider.generate(...)
                    llm_span.attributes["input_tokens"] = resp.input_tokens

        trace = tracer.build_trace()
    """

    def __init__(self, run_id: uuid.UUID) -> None:
        self._run_id = run_id
        self._spans: dict[str, SpanData] = {}
        self._span_order: list[str] = []
        # Per-task context: each concurrent asyncio Task has its own copy
        self._current_span_id: ContextVar[str | None] = ContextVar(
            f"current_span_{run_id}", default=None
        )

    @asynccontextmanager
    async def span(self, name: str, **attributes: object) -> AsyncIterator[SpanData]:
        """Open a span, making it the current span for nested calls.

        The span automatically closes (with timing) when the context exits.
        On exception the span status is set to ``"error"``.
        """
        span_id = str(uuid.uuid4())
        parent_id = self._current_span_id.get()

        span_data = SpanData(
            span_id=span_id,
            parent_id=parent_id,
            name=name,
            start_time=datetime.now(UTC),
            attributes=dict(attributes),
        )
        self._spans[span_id] = span_data
        self._span_order.append(span_id)

        token = self._current_span_id.set(span_id)
        try:
            yield span_data
        except Exception as exc:
            span_data.status = "error"
            span_data.attributes.setdefault("error", str(exc))
            raise
        finally:
            span_data.end_time = datetime.now(UTC)
            span_data.duration_ms = (
                span_data.end_time - span_data.start_time
            ).total_seconds() * 1000
            self._current_span_id.reset(token)

    def build_trace(self) -> EvalTrace:
        """Build and return the complete EvalTrace tree from all recorded spans.

        Raises RuntimeError if no spans have been recorded or no root span exists.
        """
        if not self._spans:
            raise RuntimeError("No spans recorded — call span() at least once before build_trace()")

        # First pass: create TraceSpan objects (no children yet)
        trace_spans: dict[str, TraceSpan] = {
            sid: TraceSpan(
                span_id=sd.span_id,
                parent_id=sd.parent_id,
                name=sd.name,
                start_time=sd.start_time,
                end_time=sd.end_time,
                duration_ms=sd.duration_ms,
                attributes=dict(sd.attributes),
                status=sd.status,
            )
            for sid, sd in self._spans.items()
        }

        # Second pass: wire parent→child relationships (in insertion order)
        root: TraceSpan | None = None
        for sid in self._span_order:
            ts = trace_spans[sid]
            if ts.parent_id is None:
                root = ts
            else:
                parent = trace_spans.get(ts.parent_id)
                if parent is not None:
                    parent.children.append(ts)

        if root is None:
            raise RuntimeError("No root span found — every span has a parent_id")

        return EvalTrace(
            run_id=self._run_id,
            root_span=root,
            total_spans=len(self._spans),
            total_duration_ms=root.duration_ms or 0.0,
        )
