import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="text-3xl font-bold">Page not found</h1>
      <p className="mt-3 text-muted">That address does not match any page.</p>
      <Link to="/" className="btn-primary mt-6">
        Go to the home page
      </Link>
    </div>
  );
}
