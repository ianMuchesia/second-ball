"""Metric functions and the registry (Phase 2). Events in, numbers out; no model
touches this path, and nothing here may import the engine."""

from core.metrics.events import Events
from core.metrics.registry import METRICS, WINDOWS, Metric, compute_all, get, key
from core.metrics.state import match_state, score

__all__ = [
    "METRICS",
    "WINDOWS",
    "Events",
    "Metric",
    "compute_all",
    "get",
    "key",
    "match_state",
    "score",
]
