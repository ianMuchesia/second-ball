import { useEffect } from "react";
import type { LineupPlayer, Narration, NumberRow, Overlay, RunMoment, ScreenEvent, Timed } from "../api";
import { clockText, evidenceCounts, latencyText, plural, surname } from "../api";
import { kindLabel } from "./MomentCard";
import { useRun } from "../hooks/useRun";
import { useAppDispatch } from "../store";
import { actions } from "../store/playback";
import type { Evidence } from "../store/selectors";
import { useEvidenceQuery, useRuleQuery } from "../store/serverApi";

/** Why a line said what it said: the claim, the Verifier's verdict (with any
 * rejected drafts), what code knew, then the evidence in two layers: the move
 * (the smallest run of events that proves it, from the regain) and the
 * numbers (each metric summarised, collapsed: its window is context, not
 * part of the move). Clicking an action shows the pitch at that instant. */
export default function EvidenceDrawer({
  moment,
  overlays,
  narrations,
  persona,
  evidence,
  lineup,
}: {
  moment: RunMoment;
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
  const onClose = () => dispatch(actions.closeDrawer(moment.moment_id));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && dispatch(actions.closeDrawer(moment.moment_id));
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch, moment.moment_id]);

  const mine = narrations.filter((x) => x.overlay_id.startsWith(moment.moment_id));
  const n = mine.find((x) => x.persona === persona) ?? mine[0];
  const aired = overlays.find((o) => o.overlay_id === n?.overlay_id && o.status === "aired");
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
        {evidenceCounts(evidence.ids.length, evidence.players.length, moment.numbers.length).map((x) => (
          <span key={x}>{x}</span>
        ))}
        {latency && <span className={latency.ok ? "latency ok" : "latency late"}>{latency.text}</span>}
      </div>

      {n ? (
        <section>
          <h4>Claim</h4>
          <p data-testid="claim">{n.insight?.claim ?? "–"}</p>
          {n.claim_reasons && n.claim_reasons.length > 0 && (
            <p className="small" data-testid="claim-replaced">
              The model's claim failed the Verifier ({n.claim_reasons.join("; ")}), so code's claim is shown.
            </p>
          )}
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

      <h4>The move</h4>
      <ol className="events chain" data-testid="evidence-events">
        {events.map((e) => (
          <li key={e.event_id}>
            <button onClick={() => onJump(e)} data-testid={`evidence-${e.event_id}`}>
              {e.event_id === evidence.regainId && <span className="badge">regain</span>}{" "}
              {e.words}
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

      <h4>The numbers</h4>
      <ul className="numbers" data-testid="evidence-numbers">
        {moment.numbers.map((x) => (
          <li key={`${x.metric}-${x.when}`}>
            <Number row={x} />
          </li>
        ))}
      </ul>
      {rule && (
        <p className="small">
          Detector rule <code>{moment.kind}</code> (importance {String(rule.importance)}):{" "}
          {Object.keys(rule.thresholds).length ? (
            <>
              thresholds <code>{JSON.stringify(rule.thresholds)}</code>
            </>
          ) : (
            `${kindLabel(moment.kind).toLowerCase()}s always fire (no threshold)`
          )}{" "}
          from <code>{String(rule.source)}</code>.
        </p>
      )}
      {n && <p className="small">Trace: {n.trace_id}</p>}
    </aside>
  );
}

const mmss = (t: number) => clockText(Math.floor(t / 60), Math.floor(t % 60));

/** One metric, collapsed: value, how many events, over which span. */
function Number({ row }: { row: NumberRow }) {
  const span = row.from_t !== null && row.to_t !== null ? `${mmss(row.from_t)}–${mmss(row.to_t)}` : "–";
  return (
    <details>
      <summary>
        <b>{row.label}</b> ({row.when}) <span className="value">{row.value.toFixed(3)}</span>
      </summary>
      <p className="small">
        Computed by code over {plural(row.events, "event")}, {span} of match time. These events are its window, not
        part of the move.
      </p>
    </details>
  );
}
