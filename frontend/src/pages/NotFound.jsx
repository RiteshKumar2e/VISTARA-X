import { Link, useLocation } from 'react-router-dom';
import { usePageMeta } from '../hooks/usePageMeta';

export default function NotFound() {
  const { pathname } = useLocation();
  usePageMeta('Page not found | VISTARA-X', 'This page does not exist.', { noindex: true });
  return (
    <section className="prose-page not-found" aria-labelledby="nf-title">
      <p className="eyebrow mono">404</p>
      <h1 id="nf-title">No route to this page</h1>
      <p className="lede">
        The planner searched, but <span className="mono">{pathname}</span> is not on the map.
      </p>
      <p className="button-row">
        <Link className="btn btn-primary" to="/mission">
          Back to the mission console
        </Link>
        <Link className="btn" to="/">
          Overview
        </Link>
      </p>
    </section>
  );
}
