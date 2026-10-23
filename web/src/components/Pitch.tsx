import type { LineupPlayer, ScreenEvent } from "../api";
import { surname } from "../api";

const L = 105;
const W = 68;

interface Props {
  event: ScreenEvent | undefined;
  path: ScreenEvent[]; // recent events, oldest first: the ball's path
  homeTeam: string;
  lineup: Map<string, LineupPlayer>;
  highlighted: Set<string>; // player ids
}

/** 2D pitch: home attacks left to right. Player dots from the event's freeze
 * frame, the ball path, name tags for the player on the ball and anyone
 * highlighted by the evidence. */
export function Pitch({ event, path, homeTeam, lineup, highlighted }: Props) {
  const frame = event?.freeze_frame ?? [];
  return (
    <svg className="pitch" viewBox={`-3 -3 ${L + 6} ${W + 6}`} role="img" aria-label="pitch">
      <rect x={0} y={0} width={L} height={W} className="grass" />
      <g className="lines">
        <rect x={0} y={0} width={L} height={W} />
        <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
        <circle cx={L / 2} cy={W / 2} r={9.15} />
        <rect x={0} y={W / 2 - 20.16} width={16.5} height={40.32} />
        <rect x={L - 16.5} y={W / 2 - 20.16} width={16.5} height={40.32} />
        <rect x={0} y={W / 2 - 9.16} width={5.5} height={18.32} />
        <rect x={L - 5.5} y={W / 2 - 9.16} width={5.5} height={18.32} />
        <rect x={-1.5} y={W / 2 - 3.66} width={1.5} height={7.32} />
        <rect x={L} y={W / 2 - 3.66} width={1.5} height={7.32} />
      </g>
      <g className="ball-path">
        {path.map((e) => (
          <line
            key={e.event_id}
            x1={e.start[0]}
            y1={W - e.start[1]}
            x2={e.end[0]}
            y2={W - e.end[1]}
            className={highlighted.has(e.player_id) ? "path hot" : "path"}
          />
        ))}
      </g>
      {frame.map((p) => {
        const sheet = lineup.get(p.player_id);
        const home = p.team_id === homeTeam;
        const hot = highlighted.has(p.player_id);
        const onBall = event?.player_id === p.player_id;
        const [x, y] = [p.xy[0], W - p.xy[1]];
        return (
          <g
            key={p.player_id}
            className={`player ${home ? "home" : "away"}${hot ? " highlighted" : ""}`}
            data-testid={`player-${p.player_id}`}
          >
            <circle cx={x} cy={y} r={hot ? 1.9 : 1.4} />
            <text x={x} y={y + 0.55} className="shirt">
              {sheet?.shirt_number ?? ""}
            </text>
            {(hot || onBall) && sheet && (
              <text
                x={x}
                y={y - 2.4}
                className={`tag${hot ? " highlighted" : ""}`}
                data-testid={`tag-${p.player_id}`}
              >
                {surname(sheet)}
              </text>
            )}
          </g>
        );
      })}
      {event && <circle cx={event.end[0]} cy={W - event.end[1]} r={0.8} className="ball" />}
    </svg>
  );
}
