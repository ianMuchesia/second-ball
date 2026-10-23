import { Link, Navigate } from "react-router-dom";
import { DEFAULT_RUN, paths } from "../router/routes";
import { useRunsQuery } from "../store/serverApi";

/** Recorded runs on the server; straight to the demo when it is there. */
export default function RunsPage() {
  const { data: runs, isLoading, error } = useRunsQuery();
  if (isLoading) return <p className="page">Loading runs…</p>;
  if (error) return <p className="page">The API is not reachable (start it: make api).</p>;
  if (runs?.some((r) => r.name === DEFAULT_RUN)) return <Navigate to={paths.run(DEFAULT_RUN)} replace />;
  return (
    <main className="page">
      <h1>Second Ball</h1>
      {runs?.length ? (
        <ul>
          {runs.map((r) => (
            <li key={r.name}>
              <Link to={paths.run(r.name)}>{r.name}</Link> ({r.model}, {r.languages.join("/")})
            </li>
          ))}
        </ul>
      ) : (
        <p>No recorded runs yet: make record MATCH=demo</p>
      )}
    </main>
  );
}
