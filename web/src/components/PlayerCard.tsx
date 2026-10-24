import { useState } from "react";
import type { PlayerCard as Card, PlayerRecap, PlayerStat } from "../api";
import { latestAt, pct, plural, range, teamName } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppSelector } from "../store";
import { usePlayerCardQuery } from "../store/serverApi";
import { EventsModal } from "./EventsModal";

/** The followed player's card at the replay's clock: his stats by position
 * (a fan's top three; an analyst's full card with rates and Wilson 95%
 * ranges), every number openable to the events it was counted from, his
 * touch map (analyst), and the verified half-time / full-time paragraph. */
export function PlayerCard({
  playerId,
  t,
  homeTeam,
  recaps,
}: {
  playerId: string;
  t: number;
  homeTeam: string;
  recaps: PlayerRecap[];
}) {
  const { persona, lang } = useAppSelector((s) => s.profile);
  const { data: card, isError } = usePlayerCardQuery({ run: useRun(), player: playerId });
  const [open, setOpen] = useState<PlayerStat | null>(null);
  if (isError) return <p className="empty">Could not load this player.</p>;
  if (!card) return <p className="empty">Loading…</p>;
  const analyst = persona === "analyst";
  const shown = card.stats.filter((s) => analyst || s.fan);
  const recap = latestAt(
    recaps.filter((r) => r.player_id === playerId && r.persona === persona),
    t,
  );
  const p = card.player;
  return (
    <div className="player-card" data-testid="player-card">
      <header>
        <span className="shirt">{p.shirt_number}</span>
        <span className="who">
          <b>{p.name}</b>
          <small>
            {teamName(p.team_id)} · {card.group_label} ({p.position}){p.style ? ` · ${p.style}` : ""}
          </small>
        </span>
      </header>
      {recap && (
        <section className="player-recap" data-testid="player-recap">
          <span className={recap.fallback ? "status template" : "status verified"}>
            {recap.fallback ? "Template" : "✓ Verified"}
          </span>
          <p lang={recap.text[lang] ? lang : "en"}>{recap.text[lang] ?? recap.text.en}</p>
        </section>
      )}
      <ul className="player-stats">
        {shown.map((s) => (
          <li key={s.name} data-testid={`player-stat-${s.name}`}>
            <button onClick={() => setOpen(s)} title={s.definition}>
              <span className="label">{s.label}</span>
              <span className="value">{valueText(s, t, analyst)}</span>
              <span className="from">{plural(eventsUpTo(s, t).length, "event")} ›</span>
            </button>
          </li>
        ))}
      </ul>
      {analyst && <TouchMap card={card} t={t} homeTeam={homeTeam} />}
      <p className="small omitted" data-testid="omitted">
        Not shown, because the match data has no events for them:{" "}
        {Object.entries(card.omitted).map(([k, why], i) => (
          <span key={k} title={why}>
            {i ? ", " : ""}
            {k.replace(/_/g, " ")}
          </span>
        ))}
        .
      </p>
      {open && (
        <EventsModal
          title={`${p.name}: ${open.label}`}
          definition={open.definition}
          note={`Counted from: ${open.sources.join(", ").replace(/_/g, " ")}.`}
          ids={eventsUpTo(open, t)
            .flatMap((e) => e.event_ids)
            .slice(-8)}
          total={eventsUpTo(open, t).length}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

function eventsUpTo(s: PlayerStat, t: number) {
  return s.events.filter((e) => e.t <= t);
}

/** A stat at t as the persona reads it. */
function valueText(s: PlayerStat, t: number, analyst: boolean): string {
  const snap = latestAt(s.snapshots, t);
  if (!snap || snap.value === null) return s.rate ? "–" : "0";
  if (s.rate) {
    const n = `${snap.numerator}/${snap.denominator}`;
    return analyst && snap.interval ? `${pct(snap.value)} (${range(snap.interval)}) · ${n}` : pct(snap.value);
  }
  if (s.of) return `${snap.numerator} of ${snap.denominator}`;
  if (s.unit === "xG") return snap.value.toFixed(2);
  return String(Math.round(snap.value));
}

const L = 105;
const W = 68;

/** Where he was involved: every action of his so far, on the broadcast pitch
 * (home attacks left to right). */
function TouchMap({ card, t, homeTeam }: { card: Card; t: number; homeTeam: string }) {
  const touches = card.touches.filter((x) => x.t <= t);
  const home = card.player.team_id === homeTeam;
  return (
    <figure className="touch-map" data-testid="touch-map">
      <svg viewBox={`-1 -1 ${L + 2} ${W + 2}`} role="img" aria-label={`${card.player.name}: touch map`}>
        <rect x={0} y={0} width={L} height={W} className="turf" />
        <g className="lines">
          <rect x={0} y={0} width={L} height={W} />
          <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
          <rect x={0} y={W / 2 - 20.16} width={16.5} height={40.32} />
          <rect x={L - 16.5} y={W / 2 - 20.16} width={16.5} height={40.32} />
        </g>
        {touches.map((x) => (
          <circle
            key={x.event_id}
            cx={x.xy[0]}
            cy={W - x.xy[1]}
            r={1.3}
            className={home ? "touch home" : "touch away"}
          />
        ))}
      </svg>
      <figcaption className="small">
        {plural(touches.length, "action")} so far · {teamName(card.player.team_id)} attack{" "}
        {home ? "→" : "←"}
      </figcaption>
    </figure>
  );
}
