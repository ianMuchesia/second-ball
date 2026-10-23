import { teamCode } from "../theme";

/** An invented club crest: a shield in the club's kit colour with its code.
 * Fictional clubs only; no real badge is imitated. */
export function Crest({ name, side, size = 22 }: { name: string; side: "home" | "away"; size?: number }) {
  return (
    <svg className={`crest ${side}`} width={size} height={size * 1.15} viewBox="0 0 20 23" aria-hidden="true">
      <path d="M10 1 L19 4 V11 C19 17 14.5 20.5 10 22 C5.5 20.5 1 17 1 11 V4 Z" className="shield" />
      <path d="M10 3.2 L17 5.6 V11 C17 15.8 13.6 18.6 10 19.8 C6.4 18.6 3 15.8 3 11 V5.6 Z" className="inner" />
      <text x="10" y="13.6" textAnchor="middle" className="code">
        {teamCode(name)}
      </text>
    </svg>
  );
}
