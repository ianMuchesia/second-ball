import { useState } from "react";
import type { Narration, Overlay, Timed } from "../api";
import { useRun } from "../hooks/useRun";
import { useAppDispatch, useAppSelector } from "../store";
import { controlActions } from "../store/control";
import { decisionsOf, onAir } from "../store/selectors";
import { useActMutation, useInjectMutation, useProducerQuery, useRunQuery } from "../store/serverApi";
import { kindLabel } from "./MomentCard";

/** The producer's desk. Decisions are real: a pulled line leaves the broadcast,
 * a held (high-risk) line airs only once approved, and with "approve before
 * air" every line waits for the producer. Locally each action lands in the
 * append-only audit log (approve/reject/inject refetch the view, RTK tags); on
 * a public server, which saves nothing, they stay in this browser. */
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
  const dispatch = useAppDispatch();
  const room = useAppSelector((s) => s.control);
  const t = useAppSelector((s) => s.playback.t);
  if (!view || !runData) return <p className="page">Loading…</p>;

  const saved = view.writes === "open";
  const audit = [...view.audit, ...room.local];
  const { pulled } = decisionsOf(audit);
  const byId = new Map(narrations.map((n) => [n.overlay_id, n]));
  const latest = new Map<string, Timed<Overlay>>();
  for (const o of runData.overlays) latest.set(o.overlay_id, o);
  const act = async (overlayId: string, action: "approve" | "reject") => {
    if (saved) await actOn({ run, overlayId, action, who, reason });
    else dispatch(controlActions.decide({ at: new Date().toISOString(), who, action, overlay_id: overlayId, reason }));
    setReason("");
  };
  // The control room: every line and stat card up to the playback clock,
  // newest first, as it arrives (nothing from later in the match).
  const airing = new Set(onAir(runData, audit, room.gate).map((o) => o.overlay_id));
  const arrived = [...latest.values()]
    .filter((o) => (o.status === "aired" || o.status === "pending") && o.t <= t)
    .sort((a, b) => b.t - a.t);
  const stateOf = (o: Overlay) =>
    pulled.has(o.overlay_id) ? "rejected" : airing.has(o.overlay_id) ? "on air" : "waiting";
  const waiting = arrived.filter((o) => stateOf(o) === "waiting").length;
  const onAirNow = arrived.filter((o) => stateOf(o) === "on air").length;
  // Overruling the AI is never silent: reject, pull and restore need a reason.
  const noReason = !reason.trim();
  const why = noReason ? "Add a reason first" : undefined;
  const what = (o: Overlay) =>
    o.slot === "narrative" ? (o.overlay_id.endsWith("-casual") ? "fan line" : "analyst line") : o.slot.replace(/_/g, " ");

  return (
    <div className="producer">
      {!saved && (
        <p className="public-note" data-testid="public-note">
          Public demo: your decisions change only your own screen and are not saved. Run Second Ball locally to keep them
          in the audit log.
        </p>
      )}
      <section className="desk">
        <label>
          Producer <input value={who} onChange={(e) => setWho(e.target.value)} />
        </label>
        <label className="grow">
          Reason (logged){" "}
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="optional to approve; needed to reject, pull or restore"
          />
        </label>
      </section>

      <section className="room" data-testid="incoming">
        <h3>
          Incoming <span className="count">{waiting} waiting</span>
          <span className="count">{onAirNow} on air</span>
        </h3>
        <label className="gate">
          <input
            type="checkbox"
            checked={room.gate}
            onChange={(e) => dispatch(controlActions.setGate(e.target.checked))}
            data-testid="gate"
          />{" "}
          Approve before air: nothing reaches the broadcast until you approve it
        </label>
        {arrived.length === 0 && <p className="empty">Play the match: lines and stat cards arrive here as they happen.</p>}
        <ul className="cards">
          {arrived.map((o) => {
            const state = stateOf(o);
            return (
              <li key={o.overlay_id} className={`line ${state === "on air" ? "live" : state === "rejected" ? "pulled" : "held"}`}>
                <span className={`chip ${state === "on air" ? "live" : state === "rejected" ? "pulled" : "held"}`}>{state}</span>
                <span className="text">
                  <b>
                    {o.t_in.match.minute}' {kindLabel(o.kind)} · {what(o)}
                    {o.risk_tier === "high" && " · high risk: never airs unapproved"}
                  </b>{" "}
                  {o.text.en}
                  {byId.get(o.overlay_id) && (
                    <small>
                      {" "}
                      · {byId.get(o.overlay_id)!.fallback ? "template" : "verified"} ·{" "}
                      {byId.get(o.overlay_id)!.latency_s.toFixed(1)} s
                    </small>
                  )}
                </span>
                <span className="actions">
                  {state === "waiting" && (
                    <>
                      <button
                        disabled={acting}
                        onClick={() => act(o.overlay_id, "approve")}
                        data-testid={`approve-${o.overlay_id}`}
                      >
                        Approve
                      </button>
                      <button disabled={acting || noReason} title={why} onClick={() => act(o.overlay_id, "reject")}>
                        Reject
                      </button>
                    </>
                  )}
                  {state === "on air" && (
                    <button
                      disabled={acting || noReason}
                      title={why}
                      onClick={() => act(o.overlay_id, "reject")}
                      data-testid={`pull-${o.overlay_id}`}
                    >
                      Pull
                    </button>
                  )}
                  {state === "rejected" && (
                    <button disabled={acting || noReason} title={why} onClick={() => act(o.overlay_id, "approve")}>
                      Restore
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
        <button disabled={injecting || !saved} onClick={() => inject({ run, who })}>
          Inject a test error
        </button>
        {!saved && <p className="small">Needs a local run: this public server saves nothing.</p>}
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
          Audit log <span className="count">{audit.length}</span>
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
            {audit.map((a, i) => (
              <tr key={i}>
                <td>{new Date(a.at).toLocaleTimeString()}</td>
                <td>
                  {a.who}
                  {i >= view.audit.length && " (this browser)"}
                </td>
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
