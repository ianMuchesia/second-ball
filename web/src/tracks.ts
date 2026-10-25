// The engine's 10 Hz movement (engine/core/trackfile.py), played back by the
// 2D and 3D pitches. Nothing here moves anyone: it reads where the engine put
// them. At an event's instant the track IS that event's freeze frame.
import type { ScreenEvent } from "./api";

export interface TrackHeader {
  hz: number;
  n: number;
  slots: string[]; // player_id per slot
  events: Record<string, number>; // event_id -> sample index
  values_per_sample: number;
}

export interface Tracks extends TrackHeader {
  t: Float32Array; // engine seconds per sample
  period: Uint8Array;
  dead: Uint8Array; // 1 while the ball is out of play
  v: Int16Array; // per sample: ball x, y, h (cm), then per slot x, y (cm), facing (0.1 deg)
}

const MISSING = -32768;
export const REFEREE = "referee";
const SHOT_TYPES = new Set(["shot", "shot_penalty", "shot_freekick"]); // the engine's referee, one more slot when the run has him

export function parseTracks(header: TrackHeader, body: ArrayBuffer): Tracks {
  const n = header.n;
  const t = new Float32Array(body.slice(0, 4 * n));
  const period = new Uint8Array(body, 4 * n, n);
  const dead = new Uint8Array(body, 5 * n, n);
  const start = 6 * n + ((6 * n) % 2);
  const v = new Int16Array(body.slice(start, start + 2 * n * header.values_per_sample));
  return { ...header, t, period, dead, v };
}

export interface Placed {
  x: number; // pitch metres, home attacks +x
  y: number;
  vx: number; // m/s
  vy: number;
  facing: number; // degrees, 0 = +x, anticlockwise
}

export interface Scene {
  ball: [number, number, number]; // x, y, height (m)
  players: Map<string, Placed>; // only those on the pitch
  dead: boolean;
}

type Anchor = [number, number]; // [screen time, sample]
const anchorCache = new WeakMap<ScreenEvent[], WeakMap<Tracks, Anchor[]>>();

/** Each event's exact moment on the screen's clock: events carry whole
 * seconds, the track has tenths, so the event sits at its second plus the
 * track's fraction. Anchored there, playback runs at the engine's own speed. */
function anchors(tr: Tracks, events: ScreenEvent[]): Anchor[] {
  let byTrack = anchorCache.get(events);
  if (!byTrack) anchorCache.set(events, (byTrack = new WeakMap()));
  let out = byTrack.get(tr);
  if (!out) {
    out = [];
    for (const e of events) {
      const k = tr.events[e.event_id];
      if (k === undefined) continue;
      const at = e.t + (tr.t[k] - Math.floor(tr.t[k]));
      if (!out.length || at >= out[out.length - 1][0]) out.push([at, k]);
    }
    byTrack.set(tr, out);
  }
  return out;
}

/** The sample (fractional) the screen's clock `t` corresponds to: a clicked
 * event's own instant, otherwise real time between the events' exact
 * moments (and running on before the first and after the last). */
export function sampleAt(tr: Tracks, events: ScreenEvent[], t: number, focusId: string | null = null): number {
  if (focusId && tr.events[focusId] !== undefined) {
    const f = events.find((e) => e.event_id === focusId);
    if (f && f.t === t) return tr.events[focusId];
  }
  const a = anchors(tr, events);
  if (!a.length) return Math.max(0, Math.min(tr.n - 1, t * tr.hz));
  if (t < a[0][0]) return Math.max(0, a[0][1] - (a[0][0] - t) * tr.hz);
  let lo = 0;
  let hi = a.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (a[mid][0] <= t) lo = mid;
    else hi = mid - 1;
  }
  const [t0, k0] = a[lo];
  const next = a[lo + 1];
  if (!next) return Math.min(tr.n - 1, k0 + (t - t0) * tr.hz);
  if (next[0] === t0) return k0;
  return k0 + ((t - t0) / (next[0] - t0)) * (next[1] - k0);
}

/** For each goal (a shot that went in) the engine timed: the screen time the
 * ball crossed the line (its strike's exact moment + `goal_line_s`). The
 * score changes then, not at the strike. */
export function goalLineAt(tr: Tracks, events: ScreenEvent[]): Map<string, number> {
  const out = new Map<string, number>();
  const w = tr.values_per_sample;
  for (const e of events) {
    const k = tr.events[e.event_id];
    if (k === undefined || e.outcome !== "success" || !SHOT_TYPES.has(e.type)) continue;
    let line = e.goal_line_s;
    if (typeof line !== "number") {
      // Not timed by the engine: find it in the track (the ball over a goal
      // line between the posts), within 6 s of the strike.
      for (let j = k + 1; j < Math.min(tr.n, k + 60); j++) {
        const x = tr.v[j * w] / 100;
        const y = tr.v[j * w + 1] / 100;
        if ((x <= 0 || x >= 105) && Math.abs(y - 34) <= 3.66) {
          line = tr.t[j] - tr.t[k];
          break;
        }
      }
    }
    if (typeof line !== "number") continue;
    out.set(e.event_id, e.t + (tr.t[k] - Math.floor(tr.t[k])) + line);
  }
  return out;
}

/** The screen time the track ends at: it may run on after the last event. */
export function trackEnd(tr: Tracks, events: ScreenEvent[]): number {
  const a = anchors(tr, events);
  if (!a.length) return events.length ? events[events.length - 1].t : 0;
  const [t0, k0] = a[a.length - 1];
  return t0 + (tr.n - 1 - k0) / tr.hz;
}

/** Everyone and the ball at (fractional) sample `s`, interpolated between the
 * two samples around it (0.1 s apart). */
export function sceneAt(tr: Tracks, s: number): Scene {
  const a = Math.max(0, Math.min(tr.n - 1, Math.floor(s)));
  const b = Math.min(tr.n - 1, a + 1);
  const u = tr.period[a] === tr.period[b] ? s - a : 0;
  const w = tr.values_per_sample;
  const at = (k: number, j: number) => tr.v[k * w + j];
  const lerp = (j: number) => (at(a, j) + (at(b, j) - at(a, j)) * u) / 100;
  const dt = Math.max(1e-3, tr.t[b] - tr.t[a]) || 0.1;
  const players = new Map<string, Placed>();
  tr.slots.forEach((id, slot) => {
    const j = 3 + slot * 3;
    if (at(a, j) === MISSING) return;
    if (at(b, j) === MISSING) {
      players.set(id, { x: at(a, j) / 100, y: at(a, j + 1) / 100, vx: 0, vy: 0, facing: at(a, j + 2) / 10 });
      return;
    }
    const fa = at(a, j + 2) / 10;
    const fb = at(b, j + 2) / 10;
    const turn = ((fb - fa + 540) % 360) - 180;
    players.set(id, {
      x: lerp(j),
      y: lerp(j + 1),
      vx: (at(b, j) - at(a, j)) / 100 / dt,
      vy: (at(b, j + 1) - at(a, j + 1)) / 100 / dt,
      facing: (fa + turn * u + 360) % 360,
    });
  });
  return { ball: [lerp(0), lerp(1), Math.max(0, lerp(2))], players, dead: tr.dead[a] === 1 };
}
