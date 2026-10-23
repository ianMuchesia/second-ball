// Derived view state: memoised, so a playback frame recomputes only what the
// clock changed. Nothing here invents a number: it picks from the run.
import { createSelector } from "@reduxjs/toolkit";
import type {
  AuditRow,
  IndicatorRow,
  LineupPlayer,
  Moment,
  Narration,
  Overlay,
  Run,
  ScreenEvent,
  Timed,
} from "../api";
import { indexAt, momentIdOf, SHOTS } from "../api";
import type { RootState } from ".";

export interface Marker {
  id: string;
  t: number;
  label: string;
  kind: "goal" | "red_card" | "moment";
  momentId: string | null;
}

export const selectT = (s: RootState) => s.playback.t;
export const selectPersona = (s: RootState) => s.playback.persona;

const CHAIN = 3; // the current possession's last actions drawn on the pitch
const LINE_SHOWN_S = 45; // a narrative stays up this many match seconds
const RECAP_SHOWN_S = 120;

export const lineupOf = (run: Run) =>
  new Map<string, LineupPlayer>((run.match.lineups ?? []).map((p) => [p.player_id, p]));

/** The producer's decisions from the audit log: lines pulled off air, and
 * held (high-risk) lines a human approved. The latest decision wins. */
export function decisionsOf(audit: AuditRow[] = []) {
  const last = new Map<string, string>();
  for (const a of audit) if (a.action === "approve" || a.action === "reject") last.set(a.overlay_id, a.action);
  const pulled = new Set([...last].filter(([, a]) => a === "reject").map(([id]) => id));
  const approved = new Set([...last].filter(([, a]) => a === "approve").map(([id]) => id));
  return { pulled, approved };
}

/** What can be on air: aired lines not pulled, plus held lines a human approved. */
export function onAir(run: Run, audit: AuditRow[] = []): Timed<Overlay>[] {
  const { pulled, approved } = decisionsOf(audit);
  const latest = new Map<string, Timed<Overlay>>();
  for (const o of run.overlays) latest.set(o.overlay_id, o);
  return [...latest.values()].filter(
    (o) => !pulled.has(o.overlay_id) && (o.status === "aired" || (o.status === "pending" && approved.has(o.overlay_id))),
  );
}

export function markersOf(run: Run, events: ScreenEvent[]): Marker[] {
  const out: Marker[] = [];
  const momentFor = (eventId: string) =>
    run.moments.find((m) => m.evidence_event_ids.includes(eventId))?.moment_id ?? null;
  for (const e of events) {
    if ((SHOTS.has(e.type) && e.outcome === "success") || e.outcome === "owngoal")
      out.push({ id: e.event_id, t: e.t, kind: "goal", label: `Goal ${e.minute}'`, momentId: momentFor(e.event_id) });
    if (e.outcome === "red_card")
      out.push({ id: e.event_id, t: e.t, kind: "red_card", label: `Red card ${e.minute}'`, momentId: momentFor(e.event_id) });
  }
  // One marker per moment: a goal or red card marker already stands for its moment.
  const linked = new Set(out.map((x) => x.momentId));
  for (const m of run.moments)
    if (m.importance >= 0.6 && m.kind !== "goal" && !linked.has(m.moment_id))
      out.push({ id: m.moment_id, t: m.t, kind: "moment", label: `${m.kind.replace(/_/g, " ")} ${m.clock.minute}'`, momentId: m.moment_id });
  return out;
}

export interface Evidence {
  ids: string[]; // in match order
  players: string[];
  regainId: string | null; // the first action of the possession (counters)
  exposedId: string | null; // the full-back a counter went behind (facts)
}

const CHAIN_KINDS = new Set(["goal", "big_chance"]);

/** The events behind a moment. For goals and chances: the whole possession
 * that led to the shot (regain -> passes/carries -> shot), and the full-back
 * the facts say was exposed. All from the recorded events and facts. */
export function evidenceOf(
  moment: Moment,
  narration: Narration | undefined,
  events: ScreenEvent[],
  byId: Map<string, ScreenEvent>,
  lineup: Map<string, LineupPlayer>,
): Evidence {
  let ids = moment.evidence_event_ids.filter((id) => byId.has(id));
  let regainId: string | null = null;
  const last = byId.get(ids[ids.length - 1]);
  if (last && CHAIN_KINDS.has(moment.kind)) {
    const i = events.indexOf(last);
    let k = i;
    while (k > 0 && events[k - 1].possession_id === last.possession_id) k--;
    ids = events.slice(k, i + 1).map((e) => e.event_id);
    regainId = ids[0];
  }
  const exposedName = narration?.facts?.exposed_player?.split(",")[0];
  const exposed = exposedName ? [...lineup.values()].find((p) => p.name === exposedName) : undefined;
  const players = [...new Set([...ids.map((id) => byId.get(id)!.player_id), ...(exposed ? [exposed.player_id] : [])])];
  return { ids, players, regainId, exposedId: exposed?.player_id ?? null };
}

export interface FeedItem {
  overlay: Timed<Overlay>;
  moment: Timed<Moment> | undefined;
  narration: Narration | undefined;
  linkedEvents: number;
  players: string[];
  metrics: number;
}

/** Key moments for a persona: every narrative or recap that can be on air,
 * with how much evidence stands behind it (counted from the run, not made up). */
export function feedOf(
  run: Run,
  events: ScreenEvent[],
  byId: Map<string, ScreenEvent>,
  lineup: Map<string, LineupPlayer>,
  persona: string,
  audit: AuditRow[] = [],
): FeedItem[] {
  return onAir(run, audit)
    .filter((o) => (o.slot === "narrative" || o.slot === "recap") && o.overlay_id.endsWith(`-${persona}`))
    .sort((a, b) => a.t - b.t)
    .map((o) => {
      const moment = run.moments.find((m) => m.moment_id === momentIdOf(o.overlay_id));
      const narration = run.narrations.find((n) => n.overlay_id === o.overlay_id);
      const ev = moment
        ? evidenceOf(moment, narration, events, byId, lineup)
        : { ids: o.evidence_event_ids.filter((id) => byId.has(id)), players: [] as string[] };
      return {
        overlay: o,
        moment,
        narration,
        linkedEvents: ev.ids.length,
        players: ev.players.length ? ev.players : [...new Set(ev.ids.map((id) => byId.get(id)!.player_id))],
        metrics: moment
          ? new Set([...Object.keys(moment.metrics_before), ...Object.keys(moment.metrics_after)]).size
          : Object.keys(o.values).length,
      };
    });
}

/** At playback time t: the current event, the ball path, the line on air,
 * the latest stat card, the indicator row. */
export function viewAt(
  run: Run,
  events: ScreenEvent[],
  airable: Timed<Overlay>[],
  t: number,
  persona: string,
  focusEventId: string | null,
) {
  const i = indexAt(events, t);
  let frameAt = i;
  while (frameAt > 0 && events[frameAt].freeze_frame.length === 0) frameAt--;
  const focus = focusEventId ? events.find((e) => e.event_id === focusEventId) : undefined;
  const pick = (slot: string, within: number, mine: (o: Overlay) => boolean) =>
    latest(airable.filter((o) => o.slot === slot && mine(o)), t, within);
  const line = pick("narrative", LINE_SHOWN_S, (o) => o.overlay_id.endsWith(`-${persona}`));
  const recap = pick("recap", RECAP_SHOWN_S, (o) => o.overlay_id.endsWith(`-${persona}`));
  const card = pick("stat_card", 20, () => true);
  const row = latest(run.indicators as Timed<IndicatorRow>[], t, Infinity);
  const shown = recap ?? line;
  return {
    index: i,
    event: events[i],
    frame: events[frameAt],
    path: focus ? [focus] : chain(events, i),
    line: shown,
    card,
    row,
    lineMoment: shown ? momentIdOf(shown.overlay_id) : null,
  };
}

/** The current possession's last few actions, oldest first. */
function chain(events: ScreenEvent[], i: number): ScreenEvent[] {
  const out: ScreenEvent[] = [];
  for (let k = i; k >= 0 && out.length < CHAIN && events[k].possession_id === events[i].possession_id; k--)
    out.unshift(events[k]);
  return out;
}

function latest<T extends { t: number }>(xs: T[], t: number, within: number): T | undefined {
  let best: T | undefined;
  for (const x of xs) if (x.t <= t && t - x.t <= within && (!best || x.t >= best.t)) best = x;
  return best;
}

export const makeViewSelector = () =>
  createSelector(
    [
      (_: RootState, run: Run) => run,
      (_: RootState, __: Run, events: ScreenEvent[]) => events,
      (_: RootState, __: Run, ___: ScreenEvent[], airable: Timed<Overlay>[]) => airable,
      selectT,
      selectPersona,
      (s: RootState) => s.playback.focusEventId,
    ],
    viewAt,
  );
