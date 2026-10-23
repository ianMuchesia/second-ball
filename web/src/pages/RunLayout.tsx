import { NavLink, Outlet } from "react-router-dom";
import { plural, teamName } from "../api";
import { Crest } from "../components/Crest";
import { useRun } from "../hooks/useRun";
import { paths } from "../router/routes";
import { useEventsQuery, useRunQuery } from "../store/serverApi";

/** One run: loads it once (RTK Query caches it for both tabs), then the tab. */
export default function RunLayout() {
  const run = useRun();
  const runQ = useRunQuery(run);
  const eventsQ = useEventsQuery(run);
  if (runQ.error || eventsQ.error) return <p className="page">Could not load run “{run}”.</p>;
  if (!runQ.data || !eventsQ.data) return <p className="page">Loading {run}…</p>;
  const { meta, match } = runQ.data;
  const fake = meta.model === "fake-model";
  // Counted from the run itself, so older bundles show real numbers too.
  const ai = runQ.data.narrations.filter((n) => !n.fallback).length;
  const templates = runQ.data.narrations.length - ai;
  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <span className="wordmark">Second Ball</span>
          <span className="sub">Match centre</span>
        </div>
        <div className="fixture">
          <span className="sides">
            <Crest name={teamName(match.home_team)} side="home" /> {teamName(match.home_team)} <span className="v">v</span>{" "}
            {teamName(match.away_team)} <Crest name={teamName(match.away_team)} side="away" />
          </span>
          <small>
            {match.venue} · {match.competition}
          </small>
        </div>
        <nav className="tabs">
          <NavLink to={paths.run(run)} end>
            Broadcast
          </NavLink>
          <NavLink to={paths.producer(run)} data-testid="tab-producer">
            Producer
          </NavLink>
        </nav>
        <span className={fake ? "judge test" : "judge"} title={meta.how} data-testid="run-label">
          {fake
            ? "Test run · fake model, placeholder lines, no AI"
            : `Replay of a recorded run · ${meta.model} · ${plural(ai, "AI line")}, ${plural(templates, "template")} · no model calls now`}
        </span>
      </header>
      <Outlet />
    </div>
  );
}
