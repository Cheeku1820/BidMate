import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>That page isn't available</h1>
      <p>The link may be out of date, or the project may have been archived.</p>
      <Link className="btn btn--primary" to="/projects">
        Back to projects
      </Link>
    </div>
  );
}
