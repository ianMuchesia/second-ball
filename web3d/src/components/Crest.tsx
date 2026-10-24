import { teamCode } from "../match";

/** An invented club crest (from Second Ball): a shield in the kit colour with its code. */
export function Crest({ team, side, size = 22 }: { team: string; side: "home" | "away"; size?: number }) {
  return (
    <svg className={`crest ${side}`} width={size} height={size * 1.15} viewBox="0 0 20 23" aria-hidden="true">
      <path d="M10 1 L19 4 V11 C19 17 14.5 20.5 10 22 C5.5 20.5 1 17 1 11 V4 Z" className="shield" />
      <path d="M10 3.2 L17 5.6 V11 C17 15.8 13.6 18.6 10 19.8 C6.4 18.6 3 15.8 3 11 V5.6 Z" className="inner" />
      <text x="10" y="13.6" textAnchor="middle" className="code">
        {teamCode(team)}
      </text>
    </svg>
  );
}
