import { useState } from "react";
import type { Narration } from "../api";
import { useRun } from "../hooks/useRun";
import { useActMutation, useInjectMutation, useProducerQuery } from "../store/serverApi";

/** The producer's desk: lines waiting for approval, the real drafts the
 * Verifier rejected, the audit log, and a clearly labelled test error.
 * Loaded on demand (lazy). Approve/reject/inject refetch the view (RTK tags). */
export default function ProducerTab({ narrations }: { narrations: Narration[] }) {
  const run = useRun();
  const { data: view } = useProducerQuery(run);
  const [actOn] = useActMutation();
  const [inject, { data: test }] = useInjectMutation();
  const [who, setWho] = useState("Ian");
  const [reason, setReason] = useState("");
  const act = async (overlayId: string, action: "approve" | "reject") => {
    await actOn({ run, overlayId, action, who, reason });
    setReason("");
  };
  const latency = new Map(narrations.map((n) => [n.overlay_id, n]));
  if (!view) return <p>Loading…</p>;
  return (
    <div className="producer">
      <section>
        <h3>Waiting for approval ({view.queue.length})</h3>
        <p className="small">
          High-risk lines (injury or referee talk) never air until a human approves.
        </p>
        <label>
          You: <input value={who} onChange={(e) => setWho(e.target.value)} />
        </label>{" "}
        <label>
          Reason: <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {view.queue.length === 0 && <p className="small">Nothing waiting in this run.</p>}
        <ul>
          {view.queue.map((o) => (
            <li key={o.overlay_id}>
              <span className={`badge risk-${o.risk_tier}`}>{o.risk_tier}</span> {o.text.en}{" "}
              {latency.get(o.overlay_id) && (
                <span className="small">(ready in {latency.get(o.overlay_id)!.latency_s.toFixed(1)} s)</span>
              )}
              <button onClick={() => act(o.overlay_id, "approve")}>Approve</button>
              <button onClick={() => act(o.overlay_id, "reject")}>Reject</button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Drafts the Verifier rejected ({view.rejected_drafts.length})</h3>
        <p className="small">Real model outputs from this run, with the reasons sent back to the Narrator.</p>
        <ul data-testid="rejected-drafts">
          {view.rejected_drafts.map((d, i) => (
            <li key={i}>
              <strong>
                {d.kind.replace(/_/g, " ")} · {d.persona} · draft {d.attempt}
                {d.final_fallback && " · template aired"}
              </strong>
              <div>“{d.text || "(no answer)"}”</div>
              <ul>
                {d.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </section>

      <section className="test-error">
        <h3>Test the Verifier</h3>
        <button onClick={() => inject({ run, who })}>Inject a test error</button>
        {test && (
          <div className="injection" data-testid="injection">
            <p className="badge warn">{test.label}</p>
            <p>Original: “{test.original}”</p>
            <p>Injected: “{test.injected}”</p>
            <p>
              Verifier: {test.verdict.passed ? "passed (it should not have)" : "rejected"}:{" "}
              {test.verdict.reasons.join("; ")}
            </p>
          </div>
        )}
      </section>

      <section>
        <h3>Audit log ({view.audit.length})</h3>
        <p className="small">Append-only: who did what, when, and why.</p>
        <table className="audit">
          <tbody>
            {view.audit.map((a, i) => (
              <tr key={i}>
                <td>{new Date(a.at).toLocaleTimeString()}</td>
                <td>{a.who}</td>
                <td>{a.action}</td>
                <td className="small">{a.overlay_id}</td>
                <td className="small">{a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
