import { Link } from 'react-router-dom';
import { StatusTag } from '../components/StatusTag';
import { TECH_STACK } from '../content/deck';
import { usePageMeta } from '../hooks/usePageMeta';

export default function Technology() {
  usePageMeta(
    'Technology Stack | VISTARA-X',
    'The VISTARA-X technology stack: React and Vite frontend, FastAPI backend, OpenCV, YOLOv8, A* navigation and PyBullet simulation.',
  );
  return (
    <div className="content-page">
      <header className="page-hero">
        <p className="eyebrow">Technology stack</p>
        <h1>What the deck planned, and what runs today</h1>
        <p className="lede">
          The left column is the stack from the team&rsquo;s deck. The right column is what this prototype actually uses,
          including where a fallback replaces an optional component.
        </p>
      </header>

      <div className="table-wrap">
        <table className="data data-lg stack-table">
          <thead>
            <tr>
              <th scope="col">Area</th>
              <th scope="col">Planned (deck)</th>
              <th scope="col">Used in this prototype</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {TECH_STACK.map((t) => (
              <tr key={t.area}>
                <th scope="row">{t.area}</th>
                <td>{t.deck}</td>
                <td>
                  {t.used}
                  {t.note && <span className="cell-note">{t.note}</span>}
                </td>
                <td>
                  <StatusTag status={t.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="section" aria-labelledby="run-h">
        <h2 id="run-h">How the pieces run</h2>
        <ul>
          <li>
            <strong>Two independent applications.</strong> The React frontend (port 5173 in development) talks to the FastAPI
            backend (port 8000) over REST for commands and a WebSocket for live telemetry.
          </li>
          <li>
            <strong>Threads, not the request path.</strong> The simulation runs on one fixed-timestep thread (20 Hz) and
            perception on another, so slow model inference never delays control or API responses.
          </li>
          <li>
            <strong>Optional components degrade honestly.</strong> Without PyBullet or YOLOv8 weights the system keeps working
            with labelled fallbacks, and the dashboard&rsquo;s System status says which are active.
          </li>
        </ul>
        <p>
          <Link to="/architecture">Explore the architecture</Link> &middot; <Link to="/mission">Open the live mission</Link>
        </p>
      </section>
    </div>
  );
}
