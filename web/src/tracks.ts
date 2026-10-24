// The engine's 10 Hz movement (engine/core/trackfile.py), played back by the
// 2D and 3D pitches. Nothing here moves anyone: it reads where the engine put
// them. At an event's instant the track IS that event's freeze frame.
import type { ScreenEvent } from "./api";
import { indexAt } from "./api";

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

/** The sample (fractional) the screen's clock `t` corresponds to: an event's
 * own instant at its time (or the clicked one), and in between, in proportion
 * from one event's instant to the next. */
export function sampleAt(tr: Tracks, events: ScreenEvent[], t: number, focusId: string | null = null): number {
  if (focusId && tr.events[focusId] !== undefined) {
    const f = events.find((e) => e.event_id === focusId);
    if (f && f.t === t) return tr.events[focusId];
  }
  const i = indexAt(events, t);
  const e = events[i];
  const k = tr.events[e.event_id] ?? 0;
  const n = events[i + 1];
  if (!n || t <= e.t || tr.events[n.event_id] === undefined) return k;
  return k + ((t - e.t) / (n.t - e.t)) * (tr.events[n.event_id] - k);
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
