// A run's events, as the broadcast API serves them, turned into a playable 3D
// timeline. The API already puts every event in the broadcast frame (home
// attacks +x, away events turned round), so nothing is flipped here. Pure
// functions only.
import type { Match, ScreenEvent } from "../api";

export interface Lineup {
  player_id: string;
  team_id: string;
  name: string;
  shirt_number: number;
  position: string;
  style?: string;
  starting: boolean;
}

/** One event in absolute pitch metres: home attacks +x, x 0..105, y 0..68. */
export interface Ev {
  id: string;
  possession: string;
  at: number; // match seconds on the screen's clock (the API's t)
  t: number; // playback seconds: like `at`, with same-second events spread out
  clock: number; // match clock seconds, as the engine stamped it
  period: number;
  team: string;
  player: string;
  type: string;
  outcome: string;
  sx: number;
  sy: number;
  ex: number;
  ey: number;
  speed: number | null; // ball km/h
  xg: number | null;
  ff: Float32Array; // [x0, y0, x1, y1, ...] in slot order; NaN = not on the pitch
}

export interface Timeline {
  weather: string; // rain falls when it is "rain"
  events: Ev[];
  slots: Lineup[]; // one figure per slot
  slotOf: Map<string, number>;
  lineup: Map<string, Lineup>;
  home: string;
  away: string;
  end: number;
  score: Int16Array; // [home, away] after each event
}

export const L = 105;
export const W = 68;
export const SHOTS = new Set(["shot", "shot_freekick", "shot_penalty"]);
export const DRIBBLES = new Set(["dribble", "take_on"]);
const HIGH = new Set(["cross", "corner_crossed", "freekick_crossed", "goalkick", "clearance"]);

export const isGoal = (e: Ev) => (SHOTS.has(e.type) && e.outcome === "success") || e.outcome === "owngoal";

export function fromRun(match: Match, api: ScreenEvent[]): Timeline {
  const lineups = (match.lineups ?? []) as Lineup[];
  const slots = lineups.filter((p) => p.starting);
  const slotOf = new Map(slots.map((p, i) => [p.player_id, i]));
  // Unknown ids in a freeze frame (substitutes) take a new slot.
  for (const e of api)
    for (const p of e.freeze_frame)
      if (!slotOf.has(p.player_id)) {
        const sheet = lineups.find((l) => l.player_id === p.player_id);
        slotOf.set(p.player_id, slots.length);
        slots.push(sheet ?? { player_id: p.player_id, team_id: p.team_id, name: p.player_id, shirt_number: 0, position: "SUB", starting: false });
      }

  const events: Ev[] = api.map((e) => {
    const ff = new Float32Array(slots.length * 2).fill(NaN);
    for (const p of e.freeze_frame) {
      const k = slotOf.get(p.player_id)!;
      ff[2 * k] = p.xy[0];
      ff[2 * k + 1] = p.xy[1];
    }
    return {
      id: e.event_id,
      possession: e.possession_id,
      at: e.t,
      t: e.t,
      clock: e.minute * 60 + e.second,
      period: e.period,
      team: e.team_id,
      player: e.player_id,
      type: e.type,
      outcome: e.outcome,
      sx: e.start[0],
      sy: e.start[1],
      ex: e.end[0],
      ey: e.end[1],
      speed: e.ball_speed_kmh ?? null,
      xg: e.xg,
      ff,
    };
  });

  // The engine stamps whole seconds, so several actions share one. Spread each
  // group evenly up to the next stamp: every action gets its own screen time.
  for (let i = 0; i < events.length; ) {
    let j = i;
    while (j < events.length && events[j].t === events[i].t) j++;
    const next = j < events.length ? events[j].t : events[i].t + 2;
    const span = Math.max(0.6, next - events[i].t);
    for (let k = i; k < j; k++) events[k].t = events[i].t + ((k - i) * span) / (j - i);
    i = j;
  }
  const score = new Int16Array(events.length * 2);
  let h = 0;
  let a = 0;
  events.forEach((e, i) => {
    if (isGoal(e)) {
      const forHome = e.outcome === "owngoal" ? e.team !== match.home_team : e.team === match.home_team;
      if (forHome) h++;
      else a++;
    }
    score[2 * i] = h;
    score[2 * i + 1] = a;
  });

  return {
    weather: match.weather,
    events,
    slots,
    slotOf,
    lineup: new Map(lineups.map((p) => [p.player_id, p])),
    home: match.home_team,
    away: match.away_team,
    end: events.length ? events[events.length - 1].t + 2 : 0,
    score,
  };
}

/** The screen's clock (match seconds, `at`) as playback time. Paused, it is
 * the instant of the event the 2D pitch shows: the clicked one, else the last
 * at or before the clock. Playing, it runs between events in proportion. */
export function playbackAt(tl: Timeline, at: number, eventId: string | null = null): number {
  const { events } = tl;
  if (eventId) {
    const e = events.find((x) => x.id === eventId);
    if (e && e.at === at) return e.t;
  }
  let i = 0;
  while (i + 1 < events.length && events[i + 1].at <= at) i++;
  const e = events[i];
  const n = events[i + 1];
  if (!n || at <= e.at) return e.t;
  return e.t + ((at - e.at) / (n.at - e.at)) * (n.t - e.t);
}

/** The last event at or before t. */
export function indexAt(events: Ev[], t: number): number {
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

/** Where the ball is at t: on its way along the event's action, then rolling
 * to where the next action starts. Height h in metres above the turf. */
export interface BallState {
  x: number;
  y: number;
  h: number;
  holder: string | null; // the player it belongs to now (name tag, halo)
  kicker: string | null; // the player striking it (kick pose)
  kick: number; // 0..1 through the kick
  flight: number; // match seconds the action takes
  inNet: boolean;
}

function hash01(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return ((h >>> 0) % 1000) / 1000;
}

export function ballAt(tl: Timeline, i: number, t: number, out: BallState): BallState {
  const e = tl.events[i];
  const n = tl.events[i + 1] ?? e;
  const gap = Math.max(0.05, n.t - e.t);
  const u = Math.max(0, t - e.t);
  const dist = Math.hypot(e.ex - e.sx, e.ey - e.sy);
  out.inNet = false;
  out.kicker = null;
  out.kick = 0;

  if (DRIBBLES.has(e.type)) {
    // The ball runs with the player, a touch ahead, the whole way.
    const f = Math.min(1, u / gap);
    out.x = e.sx + (e.ex - e.sx) * f;
    out.y = e.sy + (e.ey - e.sy) * f;
    out.h = Math.abs(Math.sin(f * Math.PI * Math.max(1, dist / 3))) * 0.12;
    out.holder = e.player;
    out.flight = gap;
    return out;
  }

  const lofted = HIGH.has(e.type) || (e.type === "pass" && dist > 30);
  const v = ((e.speed ?? (lofted ? 60 : 50)) / 3.6) * (lofted ? 0.75 : 1);
  const flight = Math.min(gap * (isGoal(e) ? 0.5 : 0.85), Math.max(0.22, dist / v));
  out.flight = flight;

  if (u < flight) {
    const f = u / flight;
    const g = lofted ? f : 1 - Math.pow(1 - f, 1.7); // ground passes slow down
    out.x = e.sx + (e.ex - e.sx) * g;
    out.y = e.sy + (e.ey - e.sy) * g;
    let H = 0;
    if (lofted) H = Math.min(16, Math.max(3, dist * (e.type === "pass" ? 0.13 : 0.2)));
    else if (e.type === "throw_in") H = Math.min(3, Math.max(1, dist * 0.15));
    else if (SHOTS.has(e.type)) H = 0.4 + hash01(e.id) * 1.4;
    const endH = SHOTS.has(e.type) ? hash01(e.id + "h") * 1.9 : 0;
    out.h = 4 * H * f * (1 - f) + endH * f;
    out.holder = e.player;
    out.kicker = e.player;
    out.kick = Math.min(1, u / 0.3);
    return out;
  }

  if (isGoal(e)) {
    // In the back of the net until the restart.
    const dir = e.ex > L / 2 ? 1 : -1;
    out.x = (dir > 0 ? L : 0) + dir * 1.3;
    out.y = Math.min(W / 2 + 3, Math.max(W / 2 - 3, e.ey));
    out.h = 0;
    out.holder = null;
    out.inNet = t < n.t - 0.4;
    if (!out.inNet) {
      out.x = n.sx;
      out.y = n.sy;
    }
    return out;
  }

  const f = Math.min(1, (u - flight) / Math.max(0.05, gap - flight));
  out.x = e.ex + (n.sx - e.ex) * f;
  out.y = e.ey + (n.sy - e.ey) * f;
  out.h = 0;
  out.holder = n.player;
  return out;
}

// ---- words: plain templates from the event, no model ------------------------

export function teamName(id: string): string {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function teamCode(id: string): string {
  return teamName(id).replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
}
