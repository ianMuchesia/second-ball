"""Tracing (OpenTelemetry): one trace per moment, a span per step.

    moment -> narrate -> analyst (mcp.get_sequence, llm.analyst)
                      -> narrator (llm.narrator) -> verifier   (per attempt)
                      -> localizer.<lang> (llm.localizer)
           -> producer.offer ... producer.air / producer.expire

Spans carry latency (their duration), tokens and cost (llm.* spans) and the
Verifier's reasons. Where they go is OTEL_EXPORTER:
- "none" (default): kept in memory only (RECORDER, for reports and tests);
- "console": printed;
- "otlp": to OTEL_EXPORTER_OTLP_ENDPOINT (default http://localhost:4318),
  e.g. Jaeger from `make jaeger`;
- "azure": Azure Application Insights (APPLICATIONINSIGHTS_CONNECTION_STRING);
  needs azure-monitor-opentelemetry-exporter, added in Phase 7.
"""

import os
from collections import deque
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

SERVICE = "second-ball"
KEEP_SPANS = 200_000  # the in-memory recorder keeps the most recent spans


class Recorder(SpanExporter):
    """In-memory exporter: finished spans, for the latency report and tests."""

    def __init__(self):
        self.spans: deque[ReadableSpan] = deque(maxlen=KEEP_SPANS)

    def export(self, spans) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def clear(self) -> None:
        self.spans.clear()

    def named(self, name: str) -> list[ReadableSpan]:
        return [s for s in self.spans if s.name == name]


RECORDER = Recorder()
_provider: TracerProvider | None = None


def exporter(kind: str) -> SpanExporter | None:
    if kind == "console":
        return ConsoleSpanExporter()
    if kind == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        return OTLPSpanExporter(endpoint=base.rstrip("/") + "/v1/traces")
    if kind == "azure":
        try:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorTraceExporter,
            )
        except ImportError as e:
            raise RuntimeError(
                "OTEL_EXPORTER=azure needs azure-monitor-opentelemetry-exporter "
                "(Phase 7)"
            ) from e
        return AzureMonitorTraceExporter(
            connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
        )
    if kind == "none":
        return None
    raise ValueError(f"unknown OTEL_EXPORTER {kind!r}: none, console, otlp or azure")


def setup(kind: str | None = None) -> TracerProvider:
    """Install the tracer provider once (OpenTelemetry allows one per process)."""
    global _provider
    if _provider is not None:
        return _provider
    _provider = TracerProvider(resource=Resource.create({"service.name": SERVICE}))
    _provider.add_span_processor(SimpleSpanProcessor(RECORDER))
    out = exporter(kind or os.environ.get("OTEL_EXPORTER", "none"))
    if out is not None:
        _provider.add_span_processor(BatchSpanProcessor(out))
    trace.set_tracer_provider(_provider)
    return _provider


def flush() -> None:
    if _provider is not None:
        _provider.force_flush()


tracer = trace.get_tracer(SERVICE)


@contextmanager
def step(name: str, **attributes):
    """A span for one step; None attributes are left out."""
    setup()
    with tracer.start_as_current_span(
        name, attributes={k: v for k, v in attributes.items() if v is not None}
    ) as span:
        yield span


def child_of(span_context):
    """A context whose parent is `span_context` (a span that may have ended),
    so a later step (the line airing) joins the moment's trace."""
    return trace.set_span_in_context(trace.NonRecordingSpan(span_context))
