import { gunzipSync } from "node:zlib";
import type { APIRequestContext } from "@playwright/test";

/** Where the recorded movement (engine/core/trackfile.py) has the ball at
 * screen time `t`: at an event's second the track's sample for that event,
 * in between in proportion from one event's sample to the next. The ball
 * moves between events (a pass is struck at the passer's feet and arrives
 * later), so this, not the event's end point, is where it must be. */
export async function recordedBall(
  request: APIRequestContext,
  events: { event_id: string; t: number }[],
): Promise<(t: number) => [number, number]> {
  const head: { n: number; values_per_sample: number; events: Record<string, number> } =
    await (await request.get("/api/runs/e2e/tracks")).json();
  let body = await (await request.get("/api/runs/e2e/tracks.bin")).body();
  if (body[0] === 0x1f && body[1] === 0x8b) body = gunzipSync(body); // served gzip-encoded
  const { n, values_per_sample: w } = head;
  const period = body.subarray(4 * n, 5 * n);
  const start = 6 * n + ((6 * n) % 2);
  const at = (k: number, j: number) => body.readInt16LE(start + 2 * (k * w + j)) / 100;
  const sample = (e: { event_id: string }) => Math.max(0, Math.min(n - 1, head.events[e.event_id])); // kick-off: -1
  const timed = events.filter((e) => head.events[e.event_id] !== undefined);
  return (t) => {
    let i = 0;
    while (i + 1 < timed.length && timed[i + 1].t <= t) i++;
    const [e, next] = [timed[i], timed[i + 1]];
    const s = next && next.t > e.t ? sample(e) + ((t - e.t) / (next.t - e.t)) * (sample(next) - sample(e)) : sample(e);
    const a = Math.floor(s);
    const b = Math.min(n - 1, a + 1);
    const u = period[a] === period[b] ? s - a : 0; // no gliding across half-time
    return [at(a, 0) + (at(b, 0) - at(a, 0)) * u, at(a, 1) + (at(b, 1) - at(a, 1)) * u];
  };
}
