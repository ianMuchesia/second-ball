"""Typed handoffs: Moment -> Analysis (Insight + values) -> Draft -> Verdict -> Overlay.

The numbers an agent may say are in `values`, filled by code from the
Moment's before/after metrics, never by a model.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.contracts import Insight, Moment, Overlay

Persona = Literal["analyst", "casual"]
RiskTier = Literal["low", "medium", "high"]


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchContext(Part):
    """What a broadcaster knows right now: teams, score, clock, who is on the
    pitch (public squad names)."""

    match_id: str
    home: str
    away: str
    team_names: dict[str, str]  # team_id -> display name
    score: tuple[int, int]  # (home, away)
    minute: int
    players: dict[str, str] = Field(default_factory=dict)  # on the pitch: id -> name
    sent_off: dict[str, int] = Field(default_factory=dict)  # team_id -> red cards


class NarrationTask(Part):
    moment: Moment
    context: MatchContext
    persona: Persona
    languages: list[str] = Field(default_factory=lambda: ["fr", "es", "sw", "ar"])
    # Code-made words about the moment (agents/pipeline/facts.py), e.g. a
    # goal's build_up and exploited_zone.
    facts: dict[str, str] = Field(default_factory=dict)
    # Code-made counts a line may quote (digits or words): passes_in_move,
    # counter_goals, shirt_number.
    counts: dict[str, int] = Field(default_factory=dict)


class Analysis(Part):
    task: NarrationTask
    insight: Insight
    values: dict[str, float]  # code-made: name -> number the line may quote


class Draft(Part):
    analysis: Analysis
    text: str
    attempt: int  # 1 = first try; at most 3 (two retries)
    history: list["Verdict"] = Field(default_factory=list)  # earlier attempts


class Verdict(Part):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    risk_tier: RiskTier = "low"  # high = a human must approve before airing
    text: str = ""  # the draft this verdict is about (kept for evals)


class Retry(Part):
    """Verifier -> Narrator: try again, fixing these."""

    analysis: Analysis
    attempt: int  # the attempt to make next
    reasons: list[str]
    history: list["Verdict"]


class Approved(Part):
    """Verifier -> Localizer: an English line that passed (or the fallback)."""

    analysis: Analysis
    text: str
    verdict: Verdict
    fallback: bool
    attempts: int
    history: list["Verdict"]


class Narration(Part):
    """The workflow's output for one moment and persona."""

    overlay: Overlay
    fallback: bool
    attempts: int
    verdicts: list[Verdict]


Draft.model_rebuild()
Retry.model_rebuild()
Approved.model_rebuild()
