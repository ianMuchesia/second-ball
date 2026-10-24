import { useState } from "react";
import type { Narration, Overlay, Timed } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppSelector } from "../store";
import { decisionsOf } from "../store/selectors";
import { useActMutation, useInjectMutation, useProducerQuery, useRunQuery } from "../store/serverApi";
import { kindLabel } from "./MomentCard";

/** The producer's desk. Decisions are real: a pulled line leaves the broadcast,
 * a held (high-risk) line airs only once approved, and every action lands in
 * the append-only audit log. Approve/reject/inject refetch the view (RTK tags). */
export default function ProducerTab({ narrations }: { narrations: Narration[] }) {
  const run = useRun();
  // The favourite club's held lines first within a priority (order only).
  const favourite = useAppSelector((s) => s.profile.favouriteClub);
  const { data: view } = useProducerQuery({ run, favourite });
  const { data: runData } = useRunQuery(run);
  const [actOn, { isLoading: acting }] = useActMutation();
  const [inject, { data: test, isLoading: injecting }] = useInjectMutation();
  const [who, setWho] = useState("Ian");
  const [reason, setReason] = useState("");
  if (!view || !runData) return <p className="page">Loading…</p>;

  const { pulled, approved } = decisionsOf(view.audit);
  const byId = new Map(narrations.map((n) => [n.overlay_id, n]));
  const latest = new Map<string, Timed<Overlay>>();
  for (const o of runData.overlays) latest.set(o.overlay_id, o);
  const lines = [...latest.values()].filter((o) => o.slot === "narrative" && o.status === "aired");
  const live = lines.filter((o) => !pulled.has(o.overlay_id)).length;
  const act = async (overlayId: string, action: "approve" | "reject") => {
    await actOn({ run, overlayId, action, who, reason });
    setReason("");
  };

  return (
    <div className="producer">
      <section className="desk">
        <label>
          Producer <input value={who} onChange={(e) => setWho(e.target.value)} />
        </label>
        <label className="grow">
          Reason (logged) <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="optional" />
        </label>
      </section>

      <section>
        <h3>
          Held for approval <span className="count">{view.queue.length}</span>
        </h3>
        <p className="small">Lines that mention an injury or the referee never air until a human approves them.</p>
        {view.queue.length === 0 && <p className="empty">Nothing held in this run.</p>}
        <ul className="cards">
          {view.queue.map((o) => {
            const state = pulled.has(o.overlay_id) ? "rejected" : approved.has(o.overlay_id) ? "approved" : "held";
            return (
              <li key={o.overlay_id} className={`line ${state}`}>
                <span className={`chip ${state}`}>{state}</span>
                <span className="text">{o.text.en}</span>
                <span className="actions">
                  <button disabled={acting} onClick={() => act(o.overlay_id, "approve")}>
                    Approve
                  </button>
                  <button disabled={acting} onClick={() => act(o.overlay_id, "reject")}>
                    Reject
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3>
          On air <span className="count">{live}</span>
        </h3>
        <p className="small">Pull a line and it leaves the broadcast screen; restore it to put it back.</p>
        <ul className="cards" data-testid="on-air">
          {lines.map((o) => {
            const off = pulled.has(o.overlay_id);
            const n = byId.get(o.overlay_id);
            return (
              <li key={o.overlay_id} className={`line ${off ? "pulled" : "live"}`}>
                <span className={`chip ${off ? "pulled" : "live"}`}>{off ? "pulled" : "on air"}</span>
                <span className="text">
                  <b>
                    {o.t_in.match.minute}' {kindLabel(o.kind)} · {o.overlay_id.endsWith("-casual") ? "fan" : "analyst"}
                  </b>{" "}
                  {o.text.en}
                  {n && (
                    <small>
                      {" "}
                      · {n.fallback ? "template" : "verified"} · {n.latency_s.toFixed(1)} s
                    </small>
                  )}
                </span>
                <span className="actions">
                  {off ? (
                    <button disabled={acting} onClick={() => act(o.overlay_id, "approve")}>
                      Restore
                    </button>
                  ) : (
                    <button disabled={acting} onClick={() => act(o.overlay_id, "reject")} data-testid={`pull-${o.overlay_id}`}>
                      Pull from air
                    </button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3>
          Verifier catches <span className="count">{view.rejected_drafts.length}</span>
        </h3>
        <p className="small">Real model drafts from this run that never aired, and why.</p>
        {view.rejected_drafts.length === 0 && <p className="empty">Every draft in this run passed first time.</p>}
        <ul className="cards" data-testid="rejected-drafts">
          {view.rejected_drafts.map((d, i) => (
            <li key={i} className="line caught">
              <span className="chip caught">caught</span>
              <span className="text">
                <b>
                  {kindLabel(d.kind)} · {d.persona === "casual" ? "fan" : "analyst"} · draft {d.attempt}
                  {d.final_fallback && " · template aired"}
                </b>
                <s>{d.text || "(no answer)"}</s>
                {d.reasons.map((r) => (
                  <em key={r} className="reason">
                    {r}
                  </em>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="test-error">
        <h3>Test the Verifier</h3>
        <p className="small">
          Takes a real line, changes it to be wrong, and runs it through the real Verifier. Never shown as AI output.
        </p>
        <button disabled={injecting} onClick={() => inject({ run, who })}>
          Inject a test error
        </button>
        {test && (
          <div className="injection" data-testid="injection">
            <p className="chip warn">{test.label}</p>
            <p>
              Original: <span className="quote">{test.original}</span>
            </p>
            <p>
              Injected: <s>{test.injected}</s>
            </p>
            <p>
              Verifier: <b>{test.verdict.passed ? "passed (it should not have)" : "rejected"}</b>:{" "}
              {test.verdict.reasons.join("; ")}
            </p>
          </div>
        )}
      </section>

      <section>
        <h3>
          Audit log <span className="count">{view.audit.length}</span>
        </h3>
        <p className="small">Append-only: who did what, when, and why.</p>
        <table className="audit">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>Action</th>
              <th>Line</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {view.audit.map((a, i) => (
              <tr key={i}>
                <td>{new Date(a.at).toLocaleTimeString()}</td>
                <td>{a.who}</td>
                <td>{a.action.replace(/_/g, " ")}</td>
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
