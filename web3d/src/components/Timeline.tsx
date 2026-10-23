import type { KeyMoment, Timeline as TL } from "../match";

const TICKS: [number, number, string][] = [
  [1, 0, "0'"],
  [1, 15, "15'"],
  [1, 30, "30'"],
  [2, 45, "HT"],
  [2, 60, "60'"],
  [2, 75, "75'"],
  [2, 90, "90'"],
];

/** The match on one line (from Second Ball): minute ticks, goals and cards
 * above, shots below. Click a marker, or anywhere, to jump. */
export function Timeline({ tl, t, moments, onJump }: { tl: TL; t: number; moments: KeyMoment[]; onJump: (t: number, m?: KeyMoment) => void }) {
  const pct = (x: number) => `${(100 * x) / Math.max(tl.end, 1)}%`;
  const ticks: { label: string; t: number }[] = [];
  for (const [period, minute, label] of TICKS) {
    const e = tl.events.find((x) => x.period === period && x.clock >= minute * 60);
    if (e) ticks.push({ label, t: e.t });
  }
  return (
    <div className="timeline-wrap">
      <div
        className="timeline"
        onClick={(ev) => {
          const r = ev.currentTarget.getBoundingClientRect();
          onJump(((ev.clientX - r.left) / r.width) * tl.end);
        }}
      >
        <div className="played" style={{ width: pct(t) }} />
        {ticks.map((k) => (
          <span key={k.label} className="tick" style={{ left: pct(k.t) }} />
        ))}
        {moments.map((m) => (
          <button
            key={m.index}
            className={`marker ${m.kind} ${m.team === tl.home ? "home" : "away"}`}
            style={{ left: pct(m.t) }}
            title={`${m.minute}' ${m.line.kind}: ${m.line.text}`}
            aria-label={`${m.minute}' ${m.line.kind}`}
            onClick={(ev) => {
              ev.stopPropagation();
              onJump(m.t, m);
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
