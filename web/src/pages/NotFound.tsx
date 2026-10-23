import { Link } from "react-router-dom";
import { paths } from "../router/routes";

export default function NotFound() {
  return (
    <main className="page">
      <p>No such page.</p>
      <Link to={paths.home()}>Back to the runs</Link>
    </main>
  );
}
