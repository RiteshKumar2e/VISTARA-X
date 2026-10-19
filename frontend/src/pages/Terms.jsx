import { Link } from 'react-router-dom';
import { usePageMeta } from '../hooks/usePageMeta';

export default function Terms() {
  usePageMeta('Terms of Use | VISTARA-X', 'Terms of use for the VISTARA-X autonomous navigation simulation prototype.');
  return (
    <article className="prose-page">
      <header className="page-hero">
        <p className="eyebrow">Draft for review</p>
        <h1>Terms of Use</h1>
        <p className="lede">
          Plain-language draft terms for the VISTARA-X hackathon prototype. Items marked <mark>[REVIEW]</mark> need the
          team&rsquo;s input, and ideally legal review, before any public launch.
        </p>
        <p className="muted small">Last updated: [REVIEW: date of publication]</p>
      </header>

      <section>
        <h2>What this is</h2>
        <p>
          VISTARA-X is a research and demonstration prototype that simulates a robot navigating a virtual environment. It
          does not control physical hardware.
        </p>
      </section>

      <section>
        <h2>No safety certification</h2>
        <p>
          The software is not certified for, and must not be used to operate, real robots, vehicles or safety-critical
          systems. Simulation results, including routes, clearances and detections, may not reflect real-world behaviour.
        </p>
      </section>

      <section>
        <h2>Acceptable use</h2>
        <ul>
          <li>Do not attempt to disrupt the service, overload it, or bypass its rate limits.</li>
          <li>Do not attempt to access data or systems you are not authorised to access.</li>
          <li>The shared demo simulation can be reset by any visitor; do not rely on it to keep state.</li>
        </ul>
      </section>

      <section>
        <h2>Provided as is</h2>
        <p>
          The prototype is provided &ldquo;as is&rdquo;, without warranties of any kind, to the extent permitted by law.
          Limitation of liability and governing law: <mark>[REVIEW: jurisdiction and wording]</mark>.
        </p>
      </section>

      <section>
        <h2>Licence and third-party components</h2>
        <p>
          Project source licence: <mark>[REVIEW: choose a licence]</mark>. Optional YOLOv8 support uses Ultralytics, which is
          distributed under the AGPL-3.0 licence; review its terms before distributing a build that includes it.
        </p>
      </section>

      <section>
        <h2>Contact</h2>
        <p>
          <mark>[REVIEW: team contact email]</mark>
        </p>
      </section>

      <p>
        <Link to="/mission">Back to the mission console</Link>
      </p>
    </article>
  );
}
