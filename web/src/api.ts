// Types of the broadcast API (stream/api) and helpers over a run. Contract
// types are generated from core/contracts (make contracts); the rest mirror
// the API's JSON. Fetching is RTK Query: store/serverApi.ts.
import type { LineupPlayer, Match, Moment, Overlay } from "./types/contracts";

export type { LineupPlayer, Match, Moment, Overlay };

export interface Meta {
  name: string;
  match_id: string;
  mode: "scenario" | "free_simulation";
  model: string;
  languages: string[];
  shipped_languages: string[];
  model_calls: number;
  ai_lines?: number;
  template_lines?: number;
  usd: number;
  kes: number;
  how: string;
}

export interface FramePlayer {
  player_id: string;
  team_id: string;
  xy: [number, number];
  facing_deg: number;
}

// An event with absolute coordinates (home attacks left to right) and t,
// match seconds on the pipeline's clock.
export interface ScreenEvent {
  event_id: string;
  possession_id: string;
  t: number;
  period: number;
  minute: number;
  second: number;
  team_id: string;
  player_id: string;
  type: string;
  outcome: string;
  start: [number, number];
  end: [number, number];
  xg: number | null;
  freeze_frame: FramePlayer[];
  words?: string;
}

export interface Verdict {
  passed: boolean;
  reasons: string[];
  risk_tier: "low" | "medium" | "high";
  text: string;
}

export interface Narration {
  overlay_id: string;
  kind: string;
  persona: string;
  fallback: boolean;
  attempts: number;
  verdicts: Verdict[];
  insight: { claim: string; mechanism: string; confidence: number } | null;
  latency_s: number;
  met_target: boolean;
  trace_id: string;
  facts?: Record<string, string>; // what code knew (agents/pipeline/facts.py)
  counts?: Record<string, number>;
}

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The same counting words on the lower third, the feed and the drawer. */
export const evidenceCounts = (actions: number, players: number, numbers: number) => [
  `${plural(actions, "action")} in the move`,
  plural(players, "player"),
  plural(numbers, "number"),
];

/** How a line's timing reads: honest about templates and missed targets. */
export function latencyText(n: Narration): { text: string; ok: boolean } {
  if (n.fallback) {
    const noModel = n.verdicts.every((v) => v.reasons.some((r) => r.includes("no answer")) || !v.text);
    return { text: noModel ? "template, no model" : "template after rejected drafts", ok: false };
  }
  return n.met_target
    ? { text: `AI latency ${n.latency_s.toFixed(1)} s · within 8 s`, ok: true }
    : { text: `AI latency ${n.latency_s.toFixed(1)} s · missed 8 s target`, ok: false };
}

export interface IndicatorValue {
  value: number;
  evidence_event_ids: string[];
}

export interface IndicatorRow {
  period: number;
  minute: number;
  t: number;
  [key: string]: number | IndicatorValue | null;
}

export interface AuditRow {
  at: string;
  who: string;
  action: string;
  overlay_id: string;
  reason: string;
}

export type Timed<T> = T & { t: number };

/** The smallest run of events that proves a moment (stream/api/moves.py):
 * for a goal, chance or red card, the possession plus the regain. */
export interface Move {
  ids: string[]; // in match order
  regain_id: string | null; // the action that won the ball, if in open play
  players: string[];
  team: string | null;
}

/** A metric the moment quotes, summarised: never merged into the move. */
export interface NumberRow {
  metric: string;
  label: string; // the registry's name for it ("xG", "Control index")
  when: "before" | "after";
  value: number;
  events: number; // how many events it was computed over
  from_t: number | null; // the span those events cover (match seconds)
  to_t: number | null;
}

export type RunMoment = Timed<Moment> & { move: Move; numbers: NumberRow[] };

export interface Run {
  meta: Meta;
  match: Match;
  moments: RunMoment[];
  overlays: Timed<Overlay>[];
  narrations: Narration[];
  indicators: IndicatorRow[];
  audit: AuditRow[];
}

export interface MetricInfo {
  name: string;
  definition: string;
  grain: string;
  unit: string;
  display_name: Record<string, string>;
  formula: string;
}

export interface ProducerView {
  queue: Overlay[];
  rejected_drafts: {
    overlay_id: string;
    kind: string;
    persona: string;
    attempt: number;
    text: string;
    reasons: string[];
    final_fallback: boolean;
  }[];
  audit: AuditRow[];
}

export interface Injection {
  label: string;
  overlay_id: string;
  original: string;
  injected: string;
  verdict: Verdict;
}

// ---- helpers over the run --------------------------------------------------

export const SHOTS = new Set(["shot", "shot_penalty", "shot_freekick"]);

/** Index of the last event at or before t (events sorted by t). */
export function indexAt(events: ScreenEvent[], t: number): number {
  let lo = 0;
  let hi = events.length - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (events[mid].t <= t) {
      best = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best;
}

export function teamName(id: string): string {
  const known: Record<string, string> = { riverside_athletic: "Riverside", harbour_town: "Harbour" };
  return known[id] ?? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function surname(p: LineupPlayer): string {
  return p.name.split(" ").slice(-1)[0];
}

/** The moment an overlay was made for (overlay ids are "<moment_id>-<persona>"). */
export function momentIdOf(overlayId: string): string {
  return overlayId.replace(/-(casual|analyst|card)$/, "");
}

export function clockText(minute: number, second: number): string {
  return `${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}`;
}
