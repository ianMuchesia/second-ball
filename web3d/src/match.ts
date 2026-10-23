// The engine's match file (Match line, then one MatchEvent per line) turned
// into a playable timeline. Pure functions only: the 3D stage and the HUD both
// read from here, so the picture and the numbers are always of the same instant.

export interface Lineup {
  player_id: string;
  team_id: string;
  name: string;
  shirt_number: number;
  position: string;
  style?: string;
  starting: boolean;
}

export interface MatchMeta {
  match_id: string;
  home_team: string;
  away_team: string;
  venue: string;
  competition: string;
  kickoff: string;
  weather: string;
  mode: string;
  seed: number;
  lineups: Lineup[];
}

interface RawEvent {
  event_id: string;
  possession_id: string;
  period: number;
  minute: number;
  second: number;
  team_id: string;
  player_id: string;
  type: string;
  outcome: string;
  start_x: number;
  start_y: number;
  end_x: number;
  end_y: number;
  ball_speed_kmh: number | null;
  qualifiers: Record<string, unknown>;
  freeze_frame: { player_id: string; team_id: string; x: number; y: number }[];
}

/** One event in absolute pitch metres: home attacks +x, x 0..105, y 0..68. */
export interface Ev {
  id: string;
  possession: string;
  t: number; // playback seconds (same-second events spread out)
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
  meta: MatchMeta;
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

export async function loadMatch(url: string): Promise<Timeline> {
  // Match files are generated, never committed (the repo ignores *.jsonl). A
  // missing one comes back as a 404, or as the app's own page from the dev server.
  const res = await fetch(url);
  const text = res.ok ? await res.text() : "";
  if (!text || text.trimStart().startsWith("<")) throw new Error("No match file yet: run `npm run matches` in web3d/ (needs uv and the engine)");
  const lines = text.trim().split("\n").map((l) => JSON.parse(l));
  return build(lines[0] as MatchMeta, lines.slice(1) as RawEvent[]);
}

export function build(meta: MatchMeta, raw: RawEvent[]): Timeline {
  const slots = meta.lineups.filter((p) => p.starting);
  const slotOf = new Map(slots.map((p, i) => [p.player_id, i]));
  // Unknown ids in a freeze frame (substitutes) take a new slot.
  for (const e of raw)
    for (const p of e.freeze_frame)
      if (!slotOf.has(p.player_id)) {
        const sheet = meta.lineups.find((l) => l.player_id === p.player_id);
        slotOf.set(p.player_id, slots.length);
        slots.push(sheet ?? { player_id: p.player_id, team_id: p.team_id, name: p.player_id, shirt_number: 0, position: "SUB", starting: false });
      }

  // Engine coordinates are the acting team's view (it attacks +x): turn the
  // away team's events round so one pitch shows both.
  const turn = (team: string) => team === meta.away_team;
  const px = (x: number, t: boolean) => (t ? L - x : x);
  const py = (y: number, t: boolean) => (t ? W - y : y);

  // The second half starts at 45:00 again; first-half stoppage time must not run backwards.
  const lastFirst = Math.max(0, ...raw.filter((e) => e.period === 1).map((e) => e.minute * 60 + e.second));
  const shift2 = Math.max(0, lastFirst + 20 - 45 * 60);
  const clockOf = (e: RawEvent) => e.minute * 60 + e.second;
  const playT = (e: RawEvent) => clockOf(e) + (e.period >= 2 ? shift2 : 0);

  const events: Ev[] = raw.map((e) => {
    const t = turn(e.team_id);
    const ff = new Float32Array(slots.length * 2).fill(NaN);
    for (const p of e.freeze_frame) {
      const k = slotOf.get(p.player_id)!;
      ff[2 * k] = px(p.x, t);
      ff[2 * k + 1] = py(p.y, t);
    }
    const xg = e.qualifiers?.xg;
    return {
      id: e.event_id,
      possession: e.possession_id,
      t: playT(e),
      clock: clockOf(e),
      period: e.period,
      team: e.team_id,
      player: e.player_id,
      type: e.type,
      outcome: e.outcome,
      sx: px(e.start_x, t),
      sy: py(e.start_y, t),
      ex: px(e.end_x, t),
      ey: py(e.end_y, t),
      speed: e.ball_speed_kmh,
      xg: typeof xg === "number" ? xg : null,
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
      const forHome = e.outcome === "owngoal" ? e.team !== meta.home_team : e.team === meta.home_team;
      if (forHome) h++;
      else a++;
    }
    score[2 * i] = h;
    score[2 * i + 1] = a;
  });

  return {
    meta,
    events,
    slots,
    slotOf,
    lineup: new Map(meta.lineups.map((p) => [p.player_id, p])),
    home: meta.home_team,
    away: meta.away_team,
    end: events.length ? events[events.length - 1].t + 2 : 0,
    score,
  };
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

/** The match clock at t (seconds), running smoothly between stamps. */
export function clockAt(tl: Timeline, i: number, t: number): number {
  const e = tl.events[i];
  const n = tl.events[i + 1];
  if (!n || n.period !== e.period || n.t <= e.t) return e.clock;
  return e.clock + ((t - e.t) / (n.t - e.t)) * (n.clock - e.clock);
}

export const clockText = (s: number) => {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

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

export const surname = (p: Lineup | undefined) => (p ? p.name.split(" ").slice(-1)[0] : "");

export function teamName(id: string): string {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function teamCode(id: string): string {
  return teamName(id).replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
}

export interface Line {
  kind: string; // the strip label
  text: string;
  hot: boolean; // goal or card: amber
}

export function describe(tl: Timeline, i: number): Line {
  const e = tl.events[i];
  const n = tl.events[i + 1];
  const who = tl.lineup.get(e.player)?.name ?? e.player;
  const to = n && n.team === e.team && n.player !== e.player ? tl.lineup.get(n.player)?.name : undefined;
  const xg = e.xg !== null ? ` · xG ${e.xg.toFixed(2)}` : "";
  const saved = n?.type === "keeper_save";
  switch (`${e.type}/${e.outcome}`) {
    case "pass/success":
      return { kind: "Pass", text: to ? `${who} finds ${to}` : `${who} plays it on`, hot: false };
    case "pass/fail":
      return { kind: "Pass", text: `${who}'s pass is cut out`, hot: false };
    case "dribble/success":
      return { kind: "Carry", text: `${who} drives forward`, hot: false };
    case "take_on/success":
      return { kind: "Take-on", text: `${who} skips past a defender`, hot: false };
    case "take_on/fail":
      return { kind: "Take-on", text: `${who} is stopped`, hot: false };
    case "bad_touch/fail":
      return { kind: "Touch", text: `Heavy touch from ${who}`, hot: false };
    case "interception/success":
      return { kind: "Interception", text: `${who} reads it and intercepts`, hot: false };
    case "tackle/success":
      return { kind: "Tackle", text: `${who} wins it back`, hot: false };
    case "clearance/success":
      return { kind: "Clearance", text: `${who} clears the danger`, hot: false };
    case "cross/success":
      return { kind: "Cross", text: `${who} whips it in, and it's met`, hot: false };
    case "cross/fail":
      return { kind: "Cross", text: `${who}'s cross is dealt with`, hot: false };
    case "keeper_save/success":
      return { kind: "Save", text: `Save from ${who}`, hot: false };
    case "throw_in/success":
    case "throw_in/fail":
      return { kind: "Throw-in", text: `${who} takes the throw`, hot: false };
    case "goalkick/success":
    case "goalkick/fail":
      return { kind: "Goal kick", text: `${who} goes long`, hot: false };
    case "freekick_short/success":
      return { kind: "Free kick", text: `${who} takes it short`, hot: false };
    case "freekick_crossed/success":
    case "freekick_crossed/fail":
      return { kind: "Free kick", text: `${who} swings it into the box`, hot: false };
    case "corner_crossed/success":
    case "corner_crossed/fail":
      return { kind: "Corner", text: `${who} delivers the corner`, hot: false };
    case "foul/fail":
      return { kind: "Foul", text: `Foul by ${who}`, hot: false };
    case "foul/yellow_card":
      return { kind: "Yellow card", text: `${who} goes into the book`, hot: true };
    case "foul/red_card":
      return { kind: "Red card", text: `${who} is sent off`, hot: true };
  }
  if (isGoal(e))
    return e.outcome === "owngoal"
      ? { kind: "Own goal", text: `${who} turns it into their own net`, hot: true }
      : { kind: "Goal", text: `${who} scores for ${teamName(e.team)}${xg}`, hot: true };
  if (SHOTS.has(e.type)) return { kind: e.type === "shot_freekick" ? "Free-kick shot" : "Shot", text: `${who} ${saved ? "forces a save" : "shoots, off target"}${xg}`, hot: false };
  return { kind: e.type.replace(/_/g, " "), text: who, hot: false };
}

// ---- stats and key moments, counted from the events up to now ---------------

export interface Stats {
  actions: [number, number];
  shots: [number, number];
  onTarget: [number, number];
  passes: [number, number];
  passPct: [number, number];
  corners: [number, number];
  fouls: [number, number];
  yellows: [number, number];
  xg: [number, number];
}

export function statsAt(tl: Timeline, upto: number): Stats {
  const z = (): [number, number] => [0, 0];
  const s: Stats = { actions: z(), shots: z(), onTarget: z(), passes: z(), passPct: z(), corners: z(), fouls: z(), yellows: z(), xg: z() };
  const tried: [number, number] = [0, 0];
  for (let i = 0; i <= upto && i < tl.events.length; i++) {
    const e = tl.events[i];
    const k = e.team === tl.home ? 0 : 1;
    s.actions[k]++;
    if (SHOTS.has(e.type)) {
      s.shots[k]++;
      s.xg[k] += e.xg ?? 0;
      if (e.outcome === "success" || tl.events[i + 1]?.type === "keeper_save") s.onTarget[k]++;
    }
    if (e.type === "pass") {
      tried[k]++;
      if (e.outcome === "success") s.passes[k]++;
    }
    if (e.type === "corner_crossed") s.corners[k]++;
    if (e.type === "foul") s.fouls[k]++;
    if (e.outcome === "yellow_card") s.yellows[k]++;
  }
  s.passPct = [tried[0] ? Math.round((100 * s.passes[0]) / tried[0]) : 0, tried[1] ? Math.round((100 * s.passes[1]) / tried[1]) : 0];
  return s;
}

export interface KeyMoment {
  index: number;
  t: number;
  minute: number;
  kind: "goal" | "shot" | "chance" | "yellow" | "red";
  team: string;
  line: Line;
}

export function keyMoments(tl: Timeline): KeyMoment[] {
  const out: KeyMoment[] = [];
  tl.events.forEach((e, i) => {
    let kind: KeyMoment["kind"] | null = null;
    if (isGoal(e)) kind = "goal";
    else if (e.outcome === "red_card") kind = "red";
    else if (e.outcome === "yellow_card") kind = "yellow";
    else if (SHOTS.has(e.type)) kind = (e.xg ?? 0) >= 0.2 ? "chance" : "shot";
    if (kind) out.push({ index: i, t: e.t, minute: Math.floor(e.clock / 60) + 1, kind, team: e.team, line: describe(tl, i) });
  });
  return out;
}
