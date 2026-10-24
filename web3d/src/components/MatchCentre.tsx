import { useState } from "react";
import { type KeyMoment, type Stats, teamCode, type Timeline } from "../match";

/** The right column (from Second Ball): key moments to replay, and the stats so far. */
export function MatchCentre({
  tl,
  moments,
  stats,
  index,
  onReplay,
}: {
  tl: Timeline;
  moments: KeyMoment[];
  stats: Stats;
  index: number;
  onReplay: (m: KeyMoment) => void;
}) {
  const [tab, setTab] = useState<"moments" | "stats">("moments");
  // Goals and cards are listed ahead (no spoilers in the text); plain shots once they happen.
  const shown = moments.filter((m) => m.kind !== "shot" || m.index <= index);
  return (
    <aside className="centre">
      <div className="centre-tabs">
        <button className={tab === "moments" ? "on" : ""} onClick={() => setTab("moments")}>
          Key moments
        </button>
        <button className={tab === "stats" ? "on" : ""} onClick={() => setTab("stats")}>
          Stats
        </button>
      </div>
      {tab === "moments" ? (
        <ul className="feed">
          {shown.length === 0 && <li className="empty">Nothing yet.</li>}
          {shown.map((m) => {
            const future = m.index > index;
            return (
              <li key={m.index} className={`${m.kind}${future ? " future" : ""}`}>
                <button onClick={() => onReplay(m)}>
                  <span className="minute">{m.minute}'</span>
                  <span className="body">
                    <span className="kind">
                      <i className={`pip ${m.team === tl.home ? "home" : "away"}`} />
                      {future ? "Still to come" : m.line.kind}
                      <small>{teamCode(m.team)}</small>
                    </span>
                    <span className="text">{future ? "Replay it now, or wait for it" : m.line.text}</span>
                  </span>
                  <span className="replay">Replay ›</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="stats">
          <div className="stats-head">
            <span className="home">{teamCode(tl.home)}</span>
            <span>So far</span>
            <span className="away">{teamCode(tl.away)}</span>
          </div>
          <Split name="Share of actions" v={stats.actions} pct />
          <Split name="Shots" v={stats.shots} />
          <Split name="On target" v={stats.onTarget} />
          <Split name="Expected goals" v={stats.xg} fixed={2} />
          <Split name="Passes completed" v={stats.passes} />
          <Split name="Pass accuracy %" v={stats.passPct} />
          <Split name="Corners" v={stats.corners} />
          <Split name="Fouls" v={stats.fouls} />
          <Split name="Yellow cards" v={stats.yellows} />
        </div>
      )}
    </aside>
  );
}

function Split({ name, v, pct, fixed = 0 }: { name: string; v: [number, number]; pct?: boolean; fixed?: number }) {
  const sum = v[0] + v[1];
  const share = sum ? v[0] / sum : 0.5;
  const show = (x: number) => (pct ? `${Math.round((100 * x) / Math.max(1, sum))}%` : x.toFixed(fixed));
  return (
    <div className="stat">
      <div className="split">
        <span className="num home">{show(v[0])}</span>
        <span className="stat-name">{name}</span>
        <span className="num away">{show(v[1])}</span>
      </div>
      <div className="bar">
        <span className="home" style={{ width: `${100 * share}%` }} />
        <span className="away" style={{ width: `${100 * (1 - share)}%` }} />
      </div>
    </div>
  );
}
