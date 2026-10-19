import { Link } from 'react-router-dom';
import { StatusTag } from '../components/StatusTag';
import { LIMITATIONS, ROADMAP } from '../content/deck';
import { usePageMeta } from '../hooks/usePageMeta';

export default function Roadmap() {
  usePageMeta(
    'Future Scope | VISTARA-X',
    'The VISTARA-X roadmap from intelligent simulation to real-world autonomous robotics, and the current limitations of the prototype.',
  );
  return (
    <div className="content-page">
      <header className="page-hero">
        <p className="eyebrow">Future scope</p>
        <h1>{ROADMAP.title}</h1>
        <p className="lede">
          Phase 1 is what this prototype demonstrates. Phases 2 to 4 are planned work from the team&rsquo;s deck and are not
          implemented.
        </p>
        <ol className="journey" aria-label="Roadmap journey">
          {ROADMAP.journey.map((j) => (
            <li key={j}>{j}</li>
          ))}
        </ol>
      </header>

      <ol className="phases">
        {ROADMAP.phases.map((p) => (
          <li key={p.phase} className={`phase phase-${p.status}`}>
            <div className="phase-head">
              <span className="mono muted">{p.phase}</span>
              <h2>{p.title}</h2>
              <StatusTag status={p.status === 'implemented' ? 'implemented' : 'planned'} />
            </div>
            <ul>
              {p.items.map(([item, status]) => (
                <li key={item}>
                  <span>{item}</span>
                  <StatusTag status={status} />
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <section className="section" aria-labelledby="lim-h">
        <h2 id="lim-h">Current limitations</h2>
        <ul>
          {LIMITATIONS.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p>
          <Link to="/mission">See Phase 1 running in the live mission</Link>
        </p>
      </section>
    </div>
  );
}
