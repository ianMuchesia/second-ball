import type { Narration, Overlay, ScreenEvent, Timed } from "../api";
import { SHOTS, clockText, teamName } from "../api";

// ---- scoreboard bug --------------------------------------------------------

export function Scoreboard({
  events,
  upto,
  home,
  away,
  scripted,
}: {
  events: ScreenEvent[];
  upto: number;
  home: string;
  away: string;
  scripted: boolean;
}) {
  const goals = { [home]: 0, [away]: 0 };
  const reds = { [home]: 0, [away]: 0 };
  const yellows = { [home]: 0, [away]: 0 };
  for (const e of events.slice(0, upto + 1)) {
    if (SHOTS.has(e.type) && e.outcome === "success") goals[e.team_id] += 1;
    if (e.outcome === "owngoal") goals[e.team_id === home ? away : home] += 1;
    if (e.outcome === "red_card") reds[e.team_id] += 1;
    if (e.outcome === "yellow_card") yellows[e.team_id] += 1;
  }
  const now = events[upto];
  const cards = (t: string) => (
    <span className="cards">
      {Array.from({ length: yellows[t] }, (_, i) => (
        <i key={`y${i}`} className="card yellow" title="yellow card" />
      ))}
      {Array.from({ length: reds[t] }, (_, i) => (
        <i key={`r${i}`} className="card red" title="red card" data-testid={`red-${t}`} />
      ))}
    </span>
  );
  return (
    <div className="scoreboard" data-testid="scoreboard">
      <span className="team home">{teamName(home)}</span>
      {cards(home)}
      <span className="score" data-testid="score">
        {goals[home]}-{goals[away]}
      </span>
      {cards(away)}
      <span className="team away">{teamName(away)}</span>
      <span className="clock" data-testid="clock">
        {now ? clockText(now.minute, now.second) : "00:00"}
      </span>
      {scripted && (
        <span className="scripted" title="Scripted beats: this demo is a scenario, not a free simulation">
          SCRIPTED DEMO
        </span>
      )}
    </div>
  );
}

// ---- timeline --------------------------------------------------------------

export interface Marker {
  id: string;
  t: number;
  label: string;
  kind: "goal" | "red_card" | "moment";
  momentId: string | null;
}

export function Timeline({
  end,
  t,
  markers,
  onJump,
}: {
  end: number;
  t: number;
  markers: Marker[];
  onJump: (m: Marker | null, t: number) => void;
}) {
  const pct = (x: number) => `${(100 * x) / Math.max(end, 1)}%`;
  return (
    <div
      className="timeline"
      onClick={(ev) => {
        const r = ev.currentTarget.getBoundingClientRect();
        onJump(null, ((ev.clientX - r.left) / r.width) * end);
      }}
    >
      <div className="played" style={{ width: pct(t) }} />
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
  );
}

// ---- lower third -----------------------------------------------------------

export function LowerThird({
  overlay,
  lang,
  narration,
  onWhy,
}: {
  overlay: Timed<Overlay> | undefined;
  lang: string;
  narration: Narration | undefined;
  onWhy: () => void;
}) {
  if (!overlay) return <div className="lower-third empty" />;
  const text = overlay.text[lang] ?? overlay.text.en;
  const translated = lang !== "en" && overlay.text[lang] !== undefined;
  return (
    <div className={`lower-third ${overlay.slot}`} data-testid="lower-third">
      <p lang={translated ? lang : "en"} dir={translated && lang === "ar" ? "rtl" : "ltr"}>
        {text}
      </p>
      <div className="meta">
        {narration?.fallback && <span className="badge">template</span>}
        {narration && (
          <span className={narration.met_target ? "latency ok" : "latency late"}>
            ready in {narration.latency_s.toFixed(1)} s {narration.met_target ? "(met 8 s)" : "(missed 8 s)"}
          </span>
        )}
        <button onClick={onWhy} data-testid="why">
          Why?
        </button>
      </div>
    </div>
  );
}
