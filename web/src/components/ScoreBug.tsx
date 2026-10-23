import type { ScreenEvent } from "../api";
import { SHOTS, clockText, teamName } from "../api";
import { teamCode } from "../theme";
import { Crest } from "./Crest";

/** The score bug: angled team blocks, score, clock, cards. */
export function ScoreBug({
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
  for (const e of events.slice(0, upto + 1)) {
    if (SHOTS.has(e.type) && e.outcome === "success") goals[e.team_id] += 1;
    if (e.outcome === "owngoal") goals[e.team_id === home ? away : home] += 1;
    if (e.outcome === "red_card") reds[e.team_id] += 1;
  }
  const now = events[upto];
  const team = (id: string, side: "home" | "away") => (
    <span className={`bug-team ${side}`} title={teamName(id)}>
      <Crest name={teamName(id)} side={side} size={18} />
      {teamCode(teamName(id))}
      {Array.from({ length: reds[id] }, (_, i) => (
        <i key={i} className="red-card" title="red card" data-testid={`red-${id}`} />
      ))}
    </span>
  );
  return (
    <div className="scorebug" data-testid="scoreboard">
      {team(home, "home")}
      <span className="bug-score" data-testid="score">
        {goals[home]}
        <span className="dash">–</span>
        {goals[away]}
      </span>
      {team(away, "away")}
      <span className="bug-clock" data-testid="clock">
        {now ? clockText(now.minute, now.second) : "00:00"}
      </span>
      {scripted && (
        <span className="bug-flag" title="Scripted beats: a demo scenario, not a free simulation">
          Scripted demo
        </span>
      )}
    </div>
  );
}
