import { Link } from 'react-router-dom';
import { usePageMeta } from '../hooks/usePageMeta';

export default function Privacy() {
  usePageMeta('Privacy Policy | VISTARA-X', 'How the VISTARA-X prototype handles data: what it processes, what it keeps, and who to contact.');
  return (
    <article className="prose-page">
      <header className="page-hero">
        <p className="eyebrow">Draft for review</p>
        <h1>Privacy Policy</h1>
        <p className="lede">
          This draft describes how the VISTARA-X hackathon prototype actually behaves. Items marked <mark>[REVIEW]</mark> must
          be completed by the team before any public launch.
        </p>
        <p className="muted small">Last updated: [REVIEW: date of publication]</p>
      </header>

      <section>
        <h2>Who is responsible</h2>
        <p>
          VISTARA-X is built by Team Hack01 (Ritesh Kumar and Kainat Afrazi) for Hack in Hills &rsquo;26. Responsible party
          and legal entity: <mark>[REVIEW: name or entity, postal address]</mark>.
        </p>
      </section>

      <section>
        <h2>What data the prototype processes</h2>
        <ul>
          <li>
            <strong>Mission commands you send</strong>: target coordinates, obstacle placements, scenario choice and simulation
            parameters. These describe the simulated environment only.
          </li>
          <li>
            <strong>Technical request data</strong>: like any web server, the backend receives your IP address and request
            details. The development server writes request lines to its console log.
          </li>
          <li>
            <strong>No camera, microphone or location access.</strong> The &ldquo;camera&rdquo; in the console is a synthetic render
            of the simulation. No images from your device are captured or uploaded.
          </li>
          <li>We do not ask for names, email addresses, accounts or payment details.</li>
        </ul>
      </section>

      <section>
        <h2>Retention</h2>
        <p>
          Simulation state lives in server memory and is discarded when the simulation is reset or the backend restarts.
          Server logs are kept according to the hosting configuration: <mark>[REVIEW: log retention period for the deployed
          environment]</mark>.
        </p>
      </section>

      <section>
        <h2>Cookies, analytics and third parties</h2>
        <p>
          The prototype sets no cookies, uses no analytics, and loads no third-party scripts, fonts or trackers. If analytics
          are added later, they will be opt-in and this page will be updated first. Hosting provider for any public deployment:
          <mark> [REVIEW: provider and its data processing terms]</mark>.
        </p>
      </section>

      <section>
        <h2>Your choices and contact</h2>
        <p>
          Questions or requests about data: <mark>[REVIEW: team contact email]</mark>. Applicable data-protection law and your
          rights under it: <mark>[REVIEW: jurisdiction]</mark>.
        </p>
      </section>

      <p>
        <Link to="/">Back to the mission console</Link>
      </p>
    </article>
  );
}
