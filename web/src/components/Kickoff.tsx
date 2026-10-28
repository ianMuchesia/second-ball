/** The pre-match screen while a run loads: the pitch draws itself, the ball
 * rolls, and each step ticks only when its data has really arrived (no fake
 * progress). The same picture is in index.html, so it shows before the app's
 * code has loaded too; its styles live there for that reason. */
export interface Step {
  label: string;
  done: boolean;
}

export function Kickoff({ steps }: { steps: Step[] }) {
  const now = steps.findIndex((s) => !s.done);
  return (
    <div className="kickoff" role="status" aria-live="polite" data-testid="kickoff">
      <KickoffPitch />
      <ol className="kickoff-steps">
        {steps.map((s, i) => (
          <li key={s.label} className={s.done ? "done" : i === now ? "now" : ""}>
            {s.label}
          </li>
        ))}
      </ol>
    </div>
  );
}

function KickoffPitch() {
  return (
    <>
      <div className="kickoff-brand">
        <span className="kickoff-word">Second Ball</span>
        <span className="kickoff-sub">AI commentary · a human producer in control</span>
      </div>
      <svg className="kickoff-pitch" viewBox="0 0 124 84" aria-hidden="true">
        <rect x="2" y="2" width="120" height="80" pathLength={1} />
        <line x1="62" y1="2" x2="62" y2="82" pathLength={1} />
        <circle cx="62" cy="42" r="11" pathLength={1} />
        <rect x="2" y="24" width="18" height="36" pathLength={1} />
        <rect x="104" y="24" width="18" height="36" pathLength={1} />
        <circle className="kickoff-ball" cx="0" cy="0" r="2.4" />
      </svg>
    </>
  );
}
