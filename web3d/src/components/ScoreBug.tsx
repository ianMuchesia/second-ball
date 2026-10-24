import { clockText, teamCode, teamName, type Timeline } from "../match";
import { Crest } from "./Crest";

/** The score bug: angled team blocks, score, running clock, half. */
export function ScoreBug({ tl, index, clock }: { tl: Timeline; index: number; clock: number }) {
  const h = tl.score[2 * index];
  const a = tl.score[2 * index + 1];
  const period = tl.events[index]?.period ?? 1;
  const team = (id: string, side: "home" | "away") => (
    <span className={`bug-team ${side}`} title={teamName(id)}>
      <Crest team={id} side={side} size={18} />
      {teamCode(id)}
    </span>
  );
  return (
    <div className="scorebug">
      {team(tl.home, "home")}
      <span className="bug-score">
        {h}
        <span className="dash">–</span>
        {a}
      </span>
      {team(tl.away, "away")}
      <span className="bug-clock">{clockText(clock)}</span>
      <span className="bug-half">{period === 1 ? "1st" : "2nd"}</span>
    </div>
  );
}
