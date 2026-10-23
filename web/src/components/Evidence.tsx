import type { Moment, Narration, Overlay, ScreenEvent, Timed } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { actions } from "../store/playback";
import { useEvidenceQuery, useRuleQuery } from "../store/serverApi";

/** Why a line said what it said: the claim, the Verifier's verdict (with any
 * rejected drafts), the events behind it in plain words, and the rule or
 * metric used. Clicking an event jumps the pitch there and highlights it.
 * Loaded on demand (lazy). */
export default function EvidenceDrawer({
  moment,
  overlays,
  narrations,
  persona,
}: {
  moment: Timed<Moment>;
  overlays: Timed<Overlay>[];
  narrations: Narration[];
  persona: string;
}) {
  const dispatch = useAppDispatch();
  const { data: events = [] } = useEvidenceQuery({ run: useRun(), ids: moment.evidence_event_ids });
  const { data: rule } = useRuleQuery(moment.kind);
  const players = [...new Set(events.map((e) => e.player_id))];
  const onJump = (e: ScreenEvent) =>
    dispatch(actions.focusEvent({ t: e.t, eventId: e.event_id, players }));
  const onClose = () => dispatch(actions.closeDrawer());
  const mine = narrations.filter((n) => n.overlay_id.startsWith(moment.moment_id));
  const n = mine.find((x) => x.persona === persona) ?? mine[0];
  const aired = overlays.find(
    (o) => o.overlay_id === n?.overlay_id && o.status === "aired",
  );
  const values = { ...flatten(moment.metrics_before, "before"), ...flatten(moment.metrics_after, "after") };
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
        <span>
          <b>{moment.evidence_event_ids.length}</b> linked events
        </span>
        <span>
          <b>{players.length}</b> players
        </span>
        <span>
          <b>{new Set([...Object.keys(moment.metrics_before), ...Object.keys(moment.metrics_after)]).size}</b> metrics
        </span>
        {n && (
          <span className={n.met_target ? "latency ok" : "latency late"}>
            <b>{n.latency_s.toFixed(1)} s</b> AI latency
          </span>
        )}
      </div>
      {n ? (
        <section>
          <h4>Claim</h4>
          <p>{n.insight?.claim ?? "–"}</p>
          {n.insight?.mechanism && <p className="small">Why: {n.insight.mechanism}</p>}
          <h4>Verdict</h4>
          <p data-testid="verdict">
            {n.fallback
              ? "No AI line passed; the code template aired."
              : n.attempts === 1
                ? "Passed the Verifier on the first draft."
                : `Passed the Verifier on draft ${n.attempts}.`}{" "}
            <span className={n.met_target ? "latency ok" : "latency late"}>
              Ready {n.latency_s.toFixed(1)} s after the event ({n.met_target ? "met" : "missed"} the 8 s
              target).
            </span>
          </p>
          {aired && <blockquote>{aired.text.en}</blockquote>}
          {n.verdicts
            .filter((v) => !v.passed)
            .map((v, i) => (
              <div key={i} className="rejected">
                <span className="badge">rejected draft</span> “{v.text || "(no answer)"}”
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

      <h4>Supporting events</h4>
      <ul className="events">
        {events.map((e) => (
          <li key={e.event_id}>
            <button onClick={() => onJump(e)} data-testid={`evidence-${e.event_id}`}>
              {e.words}
            </button>
          </li>
        ))}
      </ul>

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
