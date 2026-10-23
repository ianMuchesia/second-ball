import type { ScreenEvent } from "../api";
import type { Marker } from "../store/selectors";

const TICKS: [number, number, string][] = [
  [1, 0, "0'"],
  [1, 15, "15'"],
  [1, 30, "30'"],
  [2, 45, "HT"],
  [2, 60, "60'"],
  [2, 75, "75'"],
  [2, 90, "90'"],
];

/** The match on one line: minute ticks, goals and red cards above, other key
 * moments below. Click a marker (or anywhere) to jump. */
export function Timeline({
  events,
  end,
  t,
  markers,
  onJump,
}: {
  events: ScreenEvent[];
  end: number;
  t: number;
  markers: Marker[];
  onJump: (m: Marker | null, t: number) => void;
}) {
  const pct = (x: number) => `${(100 * x) / Math.max(end, 1)}%`;
  const ticks = TICKS.map(([period, minute, label]) => {
    const e = events.find((x) => x.period === period && x.minute >= minute);
    return e ? { label, t: e.t } : null;
  }).filter((x) => x !== null);
  return (
    <div className="timeline-wrap">
      <div
        className="timeline"
        onClick={(ev) => {
          const r = ev.currentTarget.getBoundingClientRect();
          onJump(null, ((ev.clientX - r.left) / r.width) * end);
        }}
      >
        <div className="played" style={{ width: pct(t) }} />
        {ticks.map((k) => (
          <span key={k.label} className="tick" style={{ left: pct(k.t) }} />
        ))}
        {markers.map((m) => (
          <button
            key={m.id}
            className={`marker ${m.kind}`}
            style={{ left: pct(m.t) }}
            title={m.label}
            aria-label={m.label}
            data-testid={`marker-${m.kind}-${m.id}`}
            onClick={(ev) => {
              ev.stopPropagation();
              onJump(m, m.t);
            }}
          />
        ))}
      </div>
      <div className="tick-labels">
        {ticks.map((k) => (
          <span key={k.label} style={{ left: pct(k.t) }}>
            {k.label}
          </span>
        ))}
      </div>
    </div>
  );
}
