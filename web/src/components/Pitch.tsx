import type { LineupPlayer, ScreenEvent } from "../api";
import { surname, teamName } from "../api";
import { teamCode } from "../theme";

const L = 105;
const W = 68;
const STRIPES = 12;

interface Props {
  event: ScreenEvent | undefined; // the current action
  frame: ScreenEvent | undefined; // the latest event with positions
  path: ScreenEvent[]; // recent actions, oldest first; the last is current
  homeTeam: string;
  lineup: Map<string, LineupPlayer>;
  highlighted: Set<string>; // player ids lit by the evidence
}

/** The scene: home attacks left to right. Player positions from the event's
 * freeze frame; the current action as a solid arrow, the previous ones faded
 * and numbered; the player on the ball and anyone in the evidence named. */
export function Pitch({ event, frame, path, homeTeam, lineup, highlighted }: Props) {
  const players = frame?.freeze_frame ?? [];
  const actors = new Set(path.map((e) => e.player_id));
  const y = (v: number) => W - v;
  const holder = event ? inPossession(event, players) : null;
  const possession = holder ? teamName(holder) : null;
  const tags = placeTags(
    players
      .filter((p) => highlighted.has(p.player_id) || event?.player_id === p.player_id || actors.has(p.player_id))
      .filter((p) => lineup.has(p.player_id))
      .map((p) => ({ id: p.player_id, x: p.xy[0], y: y(p.xy[1]), text: surname(lineup.get(p.player_id)!) })),
  );
  return (
    <div className="pitch-scene">
      <svg className="pitch" viewBox={`-2 -2 ${L + 4} ${W + 4}`} role="img" aria-label="pitch">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="arrow-head" />
          </marker>
          <marker id="arrow-hot" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="arrow-head hot" />
          </marker>
        </defs>
        <rect x={0} y={0} width={L} height={W} className="turf" />
        {Array.from({ length: STRIPES }, (_, i) =>
          i % 2 ? <rect key={i} x={(i * L) / STRIPES} y={0} width={L / STRIPES} height={W} className="stripe" /> : null,
        )}
        <g className="lines">
          <rect x={0} y={0} width={L} height={W} />
          <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
          <circle cx={L / 2} cy={W / 2} r={9.15} />
          <circle cx={L / 2} cy={W / 2} r={0.3} className="spot" />
          <rect x={0} y={W / 2 - 20.16} width={16.5} height={40.32} />
          <rect x={L - 16.5} y={W / 2 - 20.16} width={16.5} height={40.32} />
          <rect x={0} y={W / 2 - 9.16} width={5.5} height={18.32} />
          <rect x={L - 5.5} y={W / 2 - 9.16} width={5.5} height={18.32} />
          <circle cx={11} cy={W / 2} r={0.3} className="spot" />
          <circle cx={L - 11} cy={W / 2} r={0.3} className="spot" />
          <path d={`M16.5,${W / 2 - 7.3} A9.15,9.15 0 0,1 16.5,${W / 2 + 7.3}`} />
          <path d={`M${L - 16.5},${W / 2 - 7.3} A9.15,9.15 0 0,0 ${L - 16.5},${W / 2 + 7.3}`} />
          <rect x={-1.6} y={W / 2 - 3.66} width={1.6} height={7.32} className="goal" />
          <rect x={L} y={W / 2 - 3.66} width={1.6} height={7.32} className="goal" />
        </g>

        <g className="actions">
          {path.map((e, k) => {
            const current = k === path.length - 1;
            const hot = highlighted.has(e.player_id);
            const moved = Math.hypot(e.end[0] - e.start[0], e.end[1] - e.start[1]) > 0.5;
            return (
              <g key={e.event_id} className={current ? "action current" : "action previous"} opacity={current ? 1 : 0.35 + (0.5 * k) / path.length}>
                {moved && (
                  <line
                    x1={e.start[0]}
                    y1={y(e.start[1])}
                    x2={e.end[0]}
                    y2={y(e.end[1])}
                    className={hot ? "hot" : ""}
                    markerEnd={`url(#${hot ? "arrow-hot" : "arrow"})`}
                  />
                )}
                {!current && (
                  <text x={e.start[0]} y={y(e.start[1]) - 1.2} className="step">
                    {k + 1}
                  </text>
                )}
              </g>
            );
          })}
        </g>

        {players.map((p) => {
          const sheet = lineup.get(p.player_id);
          const home = p.team_id === homeTeam;
          const hot = highlighted.has(p.player_id);
          const onBall = event?.player_id === p.player_id;
          const tag = tags.get(p.player_id);
          const [px, py] = [p.xy[0], y(p.xy[1])];
          return (
            <g
              key={p.player_id}
              className={`player ${home ? "home" : "away"}${hot ? " highlighted" : ""}${onBall ? " on-ball" : ""}`}
              data-testid={`player-${p.player_id}`}
            >
              {(hot || onBall) && <circle cx={px} cy={py} r={2.6} className="halo" />}
              <circle cx={px} cy={py} r={1.55} className="dot" />
              <text x={px} y={py + 0.6} className="shirt">
                {sheet?.shirt_number ?? ""}
              </text>
              {tag && (
                <text x={tag.x} y={tag.y} className={`tag${hot ? " highlighted" : ""}`} data-testid={`tag-${p.player_id}`}>
                  {tag.text}
                </text>
              )}
            </g>
          );
        })}
        {event && <circle cx={event.end[0]} cy={y(event.end[1])} r={0.75} className="ball" />}
      </svg>
      {possession && (
        <div className="possession" data-testid="possession">
          <span className={holder === homeTeam ? "kit home" : "kit away"} />
          {teamCode(possession)} on the ball
        </div>
      )}
      <div className="attack-dir">
        <span>{teamCode(teamName(homeTeam))} attack →</span>
      </div>
      <div className="legend">
        <span className="key current" /> current action <span className="key previous" /> previous actions (1 = oldest)
      </div>
    </div>
  );
}

interface Tag {
  id: string;
  x: number;
  y: number;
  text: string;
}

/** Name tags above their players; a tag that would overlap one already placed
 * moves up a line, or below the player if there is no room above. */
function placeTags(wanted: Tag[]): Map<string, Tag> {
  const placed: Tag[] = [];
  const width = (t: Tag) => t.text.length * 1.25;
  const clash = (a: Tag) =>
    placed.some((b) => Math.abs(a.x - b.x) < (width(a) + width(b)) / 2 && Math.abs(a.y - b.y) < 2.4);
  for (const w of [...wanted].sort((a, b) => a.y - b.y)) {
    const tries = [w.y - 2.9, w.y - 5.4, w.y - 7.9, w.y + 4.4, w.y + 6.9];
    const spot = tries.map((ty) => ({ ...w, y: ty })).find((t) => t.y > 1.5 && !clash(t)) ?? { ...w, y: w.y - 2.9 };
    placed.push(spot);
  }
  return new Map(placed.map((t) => [t.id, t]));
}

// Actions by the team WITHOUT the ball: the other team is in possession.
const OUT_OF_POSSESSION = new Set(["foul"]);

/** The team on the ball after this event. */
export function inPossession(e: ScreenEvent, players: { team_id: string }[]): string {
  if (!OUT_OF_POSSESSION.has(e.type)) return e.team_id;
  return players.find((p) => p.team_id !== e.team_id)?.team_id ?? e.team_id;
}
