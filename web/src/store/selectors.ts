// Derived view state: memoised, so a playback frame recomputes only what the
// clock changed.
import { createSelector } from "@reduxjs/toolkit";
import type { IndicatorRow, LineupPlayer, Overlay, Run, ScreenEvent, Timed } from "../api";
import { indexAt, momentIdOf, SHOTS } from "../api";
import type { Marker } from "../components/Broadcast";
import type { RootState } from ".";

export const selectT = (s: RootState) => s.playback.t;
export const selectPlayback = (s: RootState) => s.playback;

const PATH_EVENTS = 6; // the ball's last few touches
const LINE_SHOWN_S = 45; // a narrative stays up this many match seconds
const RECAP_SHOWN_S = 120;

export const lineupOf = (run: Run) =>
  new Map<string, LineupPlayer>((run.match.lineups ?? []).map((p) => [p.player_id, p]));

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

/** At playback time t: the current event index, the ball path, the line on
 * air (persona), the latest stat card and recap, and the indicator row. */
export function viewAt(
  run: Run,
  events: ScreenEvent[],
  t: number,
  persona: string,
  focusEventId: string | null,
) {
  const i = indexAt(events, t);
  let frameAt = i;
  while (frameAt > 0 && events[frameAt].freeze_frame.length === 0) frameAt--;
  const focus = focusEventId ? events.find((e) => e.event_id === focusEventId) : undefined;
  const aired = (slot: string, within: number, mine: (o: Overlay) => boolean) =>
    latest(run.overlays.filter((o) => o.status === "aired" && o.slot === slot && mine(o)), t, within);
  const line = aired("narrative", LINE_SHOWN_S, (o) => o.overlay_id.endsWith(`-${persona}`));
  const recap = aired("recap", RECAP_SHOWN_S, (o) => o.overlay_id.endsWith(`-${persona}`));
  const card = aired("stat_card", 20, () => true);
  const row = latest(run.indicators as Timed<IndicatorRow>[], t, Infinity);
  return {
    index: i,
    frame: events[frameAt],
    path: focus ? [focus] : events.slice(Math.max(0, i - PATH_EVENTS + 1), i + 1),
    line: recap ?? line,
    card,
    row,
    lineMoment: (recap ?? line) ? momentIdOf((recap ?? line)!.overlay_id) : null,
  };
}

function latest<T extends { t: number }>(xs: T[], t: number, within: number): T | undefined {
  let best: T | undefined;
  for (const x of xs) if (x.t <= t && t - x.t <= within && (!best || x.t >= best.t)) best = x;
  return best;
}

export const selectPersona = (s: RootState) => s.playback.persona;
export const makeViewSelector = () =>
  createSelector(
    [
      (_: RootState, run: Run) => run,
      (_: RootState, __: Run, events: ScreenEvent[]) => events,
      selectT,
      selectPersona,
      (s: RootState) => s.playback.focusEventId,
    ],
    viewAt,
  );
