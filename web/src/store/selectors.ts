// Derived view state: memoised, so a playback frame recomputes only what the
// clock changed. Nothing here invents a number: it picks from the run.
import { createSelector } from "@reduxjs/toolkit";
import type {
  AuditRow,
  IndicatorRow,
  LineupPlayer,
  Narration,
  Overlay,
  Run,
  RunMoment,
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
export const selectPersona = (s: RootState) => s.profile.persona;

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

/** What can be on air: aired lines not pulled, plus held lines a human
 * approved. With the gate on (approve before air), every line waits for a
 * producer's approval. */
export function onAir(run: Run, audit: AuditRow[] = [], gate = false): Timed<Overlay>[] {
  const { pulled, approved } = decisionsOf(audit);
  const latest = new Map<string, Timed<Overlay>>();
  for (const o of run.overlays) latest.set(o.overlay_id, o);
  return [...latest.values()].filter(
    (o) =>
      !pulled.has(o.overlay_id) &&
      ((o.status === "aired" && (!gate || approved.has(o.overlay_id))) ||
        (o.status === "pending" && approved.has(o.overlay_id))),
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
  ids: string[]; // the move, in match order
  players: string[]; // only players in the move (+ the exposed full-back)
  regainId: string | null; // where the team won the ball
  exposedId: string | null; // the full-back a counter went behind (facts)
}

/** The evidence for a moment: the move the API computed (never a metric's
 * window), and the full-back the facts say was exposed. */
export function evidenceOf(
  moment: RunMoment,
  narration: Narration | undefined,
  lineup: Map<string, LineupPlayer>,
): Evidence {
  const exposedName = narration?.facts?.exposed_player?.split(",")[0];
  const exposed = exposedName ? [...lineup.values()].find((p) => p.name === exposedName) : undefined;
  return {
    ids: moment.move.ids,
    players: [...new Set([...moment.move.players, ...(exposed ? [exposed.player_id] : [])])],
    regainId: moment.move.regain_id,
    exposedId: exposed?.player_id ?? null,
  };
}

export interface FeedItem {
  overlay: Timed<Overlay>;
  moment: RunMoment | undefined;
  narration: Narration | undefined;
  linkedEvents: number;
  players: string[];
  metrics: number;
}

export interface Ranking {
  favouriteClub: string | null; // its moments first within a tier
  followedPlayer: string | null; // moments he is in, first within a tier
}

/** Key moments for a persona: every narrative or recap that can be on air,
 * with how much evidence stands behind it (counted from the run, not made
 * up), ranked: most important tier first; within a tier, the followed
 * player's moments, then the favourite club's, then the latest. Ranking
 * changes the order, never the content. */
export function feedOf(
  run: Run,
  byId: Map<string, ScreenEvent>,
  lineup: Map<string, LineupPlayer>,
  persona: string,
  audit: AuditRow[] = [],
  rank: Ranking = { favouriteClub: null, followedPlayer: null },
  gate = false, // approve before air: only approved lines
): FeedItem[] {
  const items = onAir(run, audit, gate)
    .filter((o) => (o.slot === "narrative" || o.slot === "recap") && o.overlay_id.endsWith(`-${persona}`))
    .map((o) => {
      const moment = run.moments.find((m) => m.moment_id === momentIdOf(o.overlay_id));
      const narration = run.narrations.find((n) => n.overlay_id === o.overlay_id);
      const ev = moment
        ? evidenceOf(moment, narration, lineup)
        : { ids: o.evidence_event_ids.filter((id) => byId.has(id)), players: [] as string[] };
      return {
        overlay: o,
        moment,
        narration,
        linkedEvents: ev.ids.length,
        players: ev.players.length ? ev.players : [...new Set(ev.ids.map((id) => byId.get(id)!.player_id))],
        metrics: moment ? moment.numbers.length : Object.keys(o.values).length,
      };
    });
  const first = (yes: boolean) => (yes ? 0 : 1);
  const key = (i: FeedItem) => [
    -i.overlay.priority,
    first(!!rank.followedPlayer && i.players.includes(rank.followedPlayer)),
    first(!!rank.favouriteClub && i.moment?.team === rank.favouriteClub),
    -i.overlay.t,
  ];
  return items.sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    for (let k = 0; k < x.length; k++) if (x[k] !== y[k]) return x[k] - y[k];
    return 0;
  });
}

/** At playback time t: the current event, the ball path, the line on air,
 * the latest stat card, the indicator row. Positions, ball and arrows are
 * always of the same instant: while a move is open, the arrows are the move's
 * actions up to now; a clicked evidence event is that instant exactly. */
export function viewAt(
  run: Run,
  events: ScreenEvent[],
  airable: Timed<Overlay>[],
  t: number,
  persona: string,
  focusEventId: string | null,
  move: string[] | null,
) {
  let i = indexAt(events, t);
  // Several events can share a second: the clicked one is the instant shown.
  const focus = focusEventId ? events.findIndex((e) => e.event_id === focusEventId) : -1;
  if (focus >= 0 && events[focus].t === t) i = focus;
  let frameAt = i;
  while (frameAt > 0 && events[frameAt].freeze_frame.length === 0) frameAt--;
  const inMove = move ? new Set(move) : null;
  const path = inMove?.has(events[i].event_id)
    ? events.slice(0, i + 1).filter((e) => inMove.has(e.event_id))
    : chain(events, i);
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
    path,
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
      (s: RootState) => s.playback.move,
    ],
    viewAt,
  );
