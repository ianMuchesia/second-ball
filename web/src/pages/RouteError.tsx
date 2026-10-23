import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";
import { paths } from "../router/routes";

/** The router's error boundary: a page that throws shows this, not a blank screen. */
export default function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Something went wrong.";
  return (
    <main className="page" role="alert">
      <h2>This page failed</h2>
      <p>{message}</p>
      <Link to={paths.home()}>Back to the runs</Link>
    </main>
  );
}
