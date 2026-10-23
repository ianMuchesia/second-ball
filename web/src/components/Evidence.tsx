import type { LineupPlayer, Moment, Narration, Overlay, ScreenEvent, Timed } from "../api";
import { latencyText, plural, surname } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { actions } from "../store/playback";
import type { Evidence } from "../store/selectors";
import { useEvidenceQuery, useRuleQuery } from "../store/serverApi";

/** Why a line said what it said: the claim, the Verifier's verdict (with any
 * rejected drafts), what code knew, the events in order (for a goal: the
 * whole possession from the regain), and the rule or metric used. Clicking
 * an event jumps the pitch there with its players lit. Loaded on demand. */
export default function EvidenceDrawer({
  moment,
  overlays,
  narrations,
  persona,
  evidence,
  lineup,
}: {
  moment: Timed<Moment>;
  overlays: Timed<Overlay>[];
  narrations: Narration[];
  persona: string;
  evidence: Evidence;
  lineup: Map<string, LineupPlayer>;
}) {
  const dispatch = useAppDispatch();
  const run = useRun();
  const { data: events = [] } = useEvidenceQuery({ run, ids: evidence.ids });
  const { data: rule } = useRuleQuery(moment.kind);
  const exposed = evidence.exposedId ? lineup.get(evidence.exposedId) : undefined;
  const focus = (e: ScreenEvent, players: string[]) =>
    dispatch(actions.focusEvent({ t: e.t, eventId: e.event_id, players }));
  const onJump = (e: ScreenEvent) => focus(e, [e.player_id, ...(exposed ? [exposed.player_id] : [])]);
  const regain = events.find((e) => e.event_id === evidence.regainId);
  const onClose = () => dispatch(actions.closeDrawer());

  const mine = narrations.filter((x) => x.overlay_id.startsWith(moment.moment_id));
  const n = mine.find((x) => x.persona === persona) ?? mine[0];
  const aired = overlays.find((o) => o.overlay_id === n?.overlay_id && o.status === "aired");
  const values = { ...flatten(moment.metrics_before, "before"), ...flatten(moment.metrics_after, "after") };
  const facts = Object.entries(n?.facts ?? {}).filter(([k]) => k !== "side" && k !== "claim");
  const latency = n ? latencyText(n) : null;
  return (
    <aside className="drawer" data-testid="evidence-drawer" aria-label="evidence">
      <header>
        <h3>
          Evidence: {moment.kind.replace(/_/g, " ")} ({moment.clock.minute}')
        </h3>
        <button onClick={onClose} aria-label="close">
          ×
        </button>
      </header>
      <div className="evidence-facts">
        <span className={n && !n.fallback ? "status verified" : "status template"}>
          {n ? (n.fallback ? "Template" : "✓ Verified") : "Stat card"}
        </span>
        <span>{plural(evidence.ids.length, "linked event")}</span>
        <span>{plural(evidence.players.length, "player")}</span>
        <span>
          {plural(Object.keys(moment.metrics_before).length + Object.keys(moment.metrics_after).length, "metric")}
        </span>
        {latency && <span className={latency.ok ? "latency ok" : "latency late"}>{latency.text}</span>}
      </div>

      {n ? (
        <section>
          <h4>Claim</h4>
          <p>{n.insight?.claim ?? "–"}</p>
          <h4>Verdict</h4>
          <p data-testid="verdict">
            {n.fallback
              ? latency?.text === "template, no model"
                ? "No model answer (out of time, quota or budget): the code template aired."
                : "Every draft was rejected: the code template aired."
              : n.attempts === 1
                ? "Passed the Verifier on the first draft."
                : `Passed the Verifier on draft ${n.attempts}.`}
          </p>
          {aired && <blockquote>{aired.text.en}</blockquote>}
          {n.verdicts
            .filter((v) => !v.passed && v.text)
            .map((v, i) => (
              <div key={i} className="rejected">
                <span className="badge">rejected draft</span> “{v.text}”
                <ul>
                  {v.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            ))}
        </section>
      ) : (
        <p className="small">Stat card only: below the narration threshold, no AI line.</p>
      )}

      {facts.length > 0 && (
        <>
          <h4>What code knew</h4>
          <ul className="known">
            {facts.map(([k, v]) => (
              <li key={k}>
                <span>{k.replace(/_/g, " ")}</span> {v}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>{evidence.regainId ? "How it happened (the whole move, in order)" : "Supporting events"}</h4>
      <ol className="events chain" data-testid="evidence-events">
        {events.map((e) => (
          <li key={e.event_id}>
            <button onClick={() => onJump(e)} data-testid={`evidence-${e.event_id}`}>
              {e.event_id === evidence.regainId && <span className="badge">regain</span>} {e.words}
            </button>
          </li>
        ))}
      </ol>
      {regain && exposed && (
        <button
          className="freeze"
          data-testid="freeze-regain"
          onClick={() => focus(regain, [regain.player_id, exposed.player_id])}
        >
          Freeze frame at the regain: where was {surname(exposed)}? ›
        </button>
      )}

      <h4>Metric / rule used</h4>
      {Object.keys(values).length > 0 && (
        <table className="values">
          <tbody>
            {Object.entries(values).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rule && (
        <p className="small">
          Detector rule <code>{moment.kind}</code> (importance {String(rule.importance)}), thresholds{" "}
          <code>{JSON.stringify(rule.thresholds)}</code> from <code>{String(rule.source)}</code>.
        </p>
      )}
      {n && <p className="small">Trace: {n.trace_id}</p>}
    </aside>
  );
}

function flatten(m: Moment["metrics_before"], when: string): Record<string, number> {
  return Object.fromEntries(Object.entries(m).map(([k, v]) => [`${k} (${when})`, v.value]));
}
