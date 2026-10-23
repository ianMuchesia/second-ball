import { NavLink, Outlet } from "react-router-dom";
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
  const m = runQ.data.meta;
  return (
    <div className="app">
      <nav className="tabs">
        <NavLink to={paths.run(run)} end>
          Broadcast
        </NavLink>
        <NavLink to={paths.producer(run)} data-testid="tab-producer">
          Producer
        </NavLink>
        <span className="small judge" title={m.how}>
          Judge mode: recorded run “{m.name}”, model {m.model}, {m.model_calls} model calls when recorded, 0
          now.
        </span>
      </nav>
      <Outlet />
    </div>
  );
}
