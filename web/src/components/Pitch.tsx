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
  followed: string | null; // the followed player: his name is always on
  onPick: (playerId: string) => void; // click a player to follow him
}

/** The scene: home attacks left to right. Player positions from the event's
 * freeze frame; the current action as a solid arrow, the previous ones faded
 * and numbered; the player on the ball and anyone in the evidence named. */
export function Pitch({ event, frame, path, homeTeam, lineup, highlighted, followed, onPick }: Props) {
  const players = frame?.freeze_frame ?? [];
  const actors = new Set(path.map((e) => e.player_id));
  const y = (v: number) => W - v;
  const holder = event ? inPossession(event, players) : null;
  const possession = holder ? teamName(holder) : null;
  const tags = placeTags(
    players
      .filter(
        (p) =>
          highlighted.has(p.player_id) ||
          event?.player_id === p.player_id ||
          actors.has(p.player_id) ||
          p.player_id === followed,
      )
      .filter((p) => lineup.has(p.player_id))
      .map((p) => ({ id: p.player_id, x: p.xy[0], y: y(p.xy[1]), text: surname(lineup.get(p.player_id)!).toUpperCase() })),
    players.map((p) => ({ id: p.player_id, x: p.xy[0], y: y(p.xy[1]) })),
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
          const isFollowed = p.player_id === followed;
          const tag = tags.get(p.player_id);
          const [px, py] = [p.xy[0], y(p.xy[1])];
          return (
            <g
              key={p.player_id}
              className={`player ${home ? "home" : "away"}${hot ? " highlighted" : ""}${onBall ? " on-ball" : ""}${isFollowed ? " followed" : ""}`}
              data-testid={`player-${p.player_id}`}
              onClick={() => onPick(p.player_id)}
            >
              <title>{sheet ? `${sheet.name}: click to follow` : p.player_id}</title>
              {(hot || onBall) && <circle cx={px} cy={py} r={2.6} className="halo" />}
              {isFollowed && <circle cx={px} cy={py} r={2.2} className="follow-ring" />}
              <circle cx={px} cy={py} r={1.55} className="dot" />
              <text x={px} y={py + 0.6} className="shirt">
                {sheet?.shirt_number ?? ""}
              </text>
              {tag && Math.hypot(tag.tx! - px, tag.ty! - 0.7 - py) > 3.6 && (
                <line x1={px} y1={py} x2={tag.tx!} y2={tag.ty! - 0.7} className="leader" />
              )}
              {tag && (
                <text x={tag.tx} y={tag.ty} className={`tag${hot ? " highlighted" : ""}${isFollowed ? " followed" : ""}`} data-testid={`tag-${p.player_id}`}>
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
  x: number; // the player
  y: number;
  text: string;
  tx?: number; // where the name went (text anchor: middle, baseline)
  ty?: number;
}

const CHAR_W = 1.15; // pitch metres per character at the tag size (measured 1.05)
const TAG_ASCENT = 2.2;
const TAG_DESCENT = 0.55;
const DOT_R = 1.75;

/** Names never cover a player or another name: each tag tries spots around
 * its player (above, below, sides, further out) and takes the first free
 * one; a tag placed away from its player gets a leader line. */
function placeTags(wanted: Tag[], dots: { id: string; x: number; y: number }[]): Map<string, Tag> {
  const boxes: { x0: number; x1: number; y0: number; y1: number }[] = dots.map((d) => ({
    x0: d.x - DOT_R,
    x1: d.x + DOT_R,
    y0: d.y - DOT_R,
    y1: d.y + DOT_R,
  }));
  const out = new Map<string, Tag>();
  for (const w of [...wanted].sort((a, b) => a.y - b.y)) {
    const half = (w.text.length * CHAR_W) / 2;
    const spots: [number, number][] = [
      [0, -2.9],
      [0, 4.3],
      [half + 2.4, 0.7],
      [-half - 2.4, 0.7],
      [0, -5.6],
      [0, 7.0],
      [half + 2.4, -2.4],
      [-half - 2.4, -2.4],
      [half + 2.4, 3.8],
      [-half - 2.4, 3.8],
      [0, -8.3],
      [0, 9.7],
    ];
    // Measured in the page: the text box runs 2.1 above the baseline to 0.5 below.
    const box = (tx: number, ty: number) => ({ x0: tx - half, x1: tx + half, y0: ty - TAG_ASCENT, y1: ty + TAG_DESCENT });
    const free = (b: ReturnType<typeof box>) =>
      b.x0 > -1 && b.x1 < L + 1 && b.y0 > -1 && b.y1 < W + 1 &&
      !boxes.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0);
    const pick = spots.map(([dx, dy]) => [w.x + dx, w.y + dy] as const).find(([tx, ty]) => free(box(tx, ty)));
    const [tx, ty] = pick ?? [w.x, w.y - 2.9];
    boxes.push(box(tx, ty));
    out.set(w.id, { ...w, tx, ty });
  }
  return out;
}

// Actions by the team WITHOUT the ball: the other team is in possession.
const OUT_OF_POSSESSION = new Set(["foul"]);

/** The team on the ball after this event. */
export function inPossession(e: ScreenEvent, players: { team_id: string }[]): string {
  if (!OUT_OF_POSSESSION.has(e.type)) return e.team_id;
  return players.find((p) => p.team_id !== e.team_id)?.team_id ?? e.team_id;
}
