import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { MissionProcess } from '../components/MissionProcess';
import { StatusTag } from '../components/StatusTag';
import { APPLICATIONS, LIMITATIONS, MARKET, MISSION, PROBLEM, SOLUTION, TEAM } from '../content/deck';
import { usePageMeta } from '../hooks/usePageMeta';
import { api } from '../services/api';

/** Recorded predictive-vs-reactive results, straight from GET /evaluation. */
function HeroEvidence() {
  const [state, setState] = useState({ status: 'loading' });
  useEffect(() => {
    let cancelled = false;
    api
      .evaluation()
      .then((d) => !cancelled && setState({ status: 'ok', data: d }))
      .catch(() => !cancelled && setState({ status: 'unavailable' }));
    return () => {
      cancelled = true;
    };
  }, []);
  const cmp = state.data?.comparison;
  return (
    <aside className="hero-evidence" aria-labelledby="hero-evidence-title">
      <p className="eyebrow">Recorded evaluation</p>
      <h2 id="hero-evidence-title">Predictive vs reactive, same crossing scenario</h2>
      {state.status === 'ok' && cmp ? (
        <>
          <table className="he-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Metric</span>
                </th>
                <th scope="col">Predictive</th>
                <th scope="col">Reactive</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Goal reached</th>
                <td className="mono">{cmp.predictive.goal_completion}</td>
                <td className="mono">{cmp.reactive.goal_completion}</td>
              </tr>
              <tr>
                <th scope="row">Collisions</th>
                <td className="mono">{cmp.predictive.collisions_total}</td>
                <td className="mono">{cmp.reactive.collisions_total}</td>
              </tr>
              <tr>
                <th scope="row">Near misses</th>
                <td className="mono">{cmp.predictive.near_misses_total}</td>
                <td className="mono">{cmp.reactive.near_misses_total}</td>
              </tr>
              <tr>
                <th scope="row">Worst clearance</th>
                <td className="mono">{cmp.predictive.min_clearance_worst_m?.toFixed(2)} m</td>
                <td className="mono">{cmp.reactive.min_clearance_worst_m?.toFixed(2)} m</td>
              </tr>
            </tbody>
          </table>
          <p className="muted small">
            {cmp.predictive.runs} simulated runs per mode (person speed and timing varied), generated {state.data.generated_at.slice(0, 10)}{' '}
            by <code>{state.data.command}</code>. Simulation only; not a measure of real-world safety.
          </p>
        </>
      ) : (
        <p className="muted small">
          {state.status === 'loading'
            ? 'Loading recorded results...'
            : 'Start the backend to show the recorded results here; the live mission page also shows them.'}
        </p>
      )}
    </aside>
  );
}

export default function Overview() {
  usePageMeta(
    'VISTARA-X | Vision-Based Autonomous Navigation Prototype',
    'VISTARA-X by Team Hack01: a simulation-first robot that perceives its surroundings, plans with A* and replans around obstacles in real time.',
  );

  return (
    <div className="overview">
      <header className="hero hero-split">
        <div className="hero-copy">
          <p className="eyebrow">
            Team {TEAM.name} &middot; {TEAM.event}
          </p>
          <h1>VISTARA-X</h1>
          <p className="hero-tagline">Beyond Seeing. Into Understanding.</p>
          <p className="hero-claim">
            A robot that <strong>anticipates</strong> navigation conflicts instead of only reacting to obstacles.
          </p>
          <p className="lede">
            VISTARA-X tracks moving people with simulated LiDAR, predicts where they will be over the next three seconds, checks those
            predictions against its own route, and slows, waits, steps aside or replans before the paths meet, explaining every
            decision.
          </p>
          <div className="button-row">
            <Link className="btn btn-primary btn-lg" to="/mission">
              Open the live mission
            </Link>
            <a className="btn btn-lg" href="/mission#evaluation">
              See the evidence
            </a>
            <Link className="btn btn-lg btn-quiet" to="/architecture">
              Explore the architecture
            </Link>
          </div>
          <ol className="hero-loop" aria-label="Navigation loop">
            {['Perceive', 'Track', 'Predict', 'Assess risk', 'Decide', 'Navigate'].map((s, i) => (
              <li key={s}>
                <span className="mono">{String(i + 1).padStart(2, '0')}</span>
                {s}
              </li>
            ))}
          </ol>
        </div>
        <HeroEvidence />
      </header>

      <section className="section" aria-labelledby="problem-h">
        <div className="section-head">
          <p className="eyebrow">The problem</p>
          <h2 id="problem-h">{PROBLEM.title}</h2>
        </div>
        <div className="two-col">
          <div>
            <p className="lede-sm">{PROBLEM.statement}</p>
            <p className="muted small">Theme alignment</p>
            <ul className="chips" aria-label="Theme alignment">
              {PROBLEM.theme.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Our challenge</h3>
            <ol className="numbered">
              {PROBLEM.challenge.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ol>
          </div>
        </div>
        <details className="explain">
          <summary>Why perception and scene understanding matter</summary>
          <p>
            A robot that only follows a fixed route fails as soon as the world changes. To act safely it has to perceive what is
            around it, decide which objects matter (a person, a pallet, a shelf), keep an up-to-date map, and feed every change
            back into planning. VISTARA-X builds that loop end to end in simulation: perception produces detections, scene
            understanding turns them into navigation-relevant facts, and the planner and controller act on a continuously
            updated map.
          </p>
        </details>
      </section>

      <section className="section" aria-labelledby="solution-h">
        <div className="section-head">
          <p className="eyebrow">The solution</p>
          <h2 id="solution-h">One continuous autonomous loop</h2>
          <p className="muted">{SOLUTION.uniqueValue}</p>
        </div>
        <ol className="loop" aria-label="Solution overview">
          {SOLUTION.overview.map((s, i) => (
            <li key={s}>
              <span className="mono">{String(i + 1).padStart(2, '0')}</span>
              {s}
            </li>
          ))}
        </ol>

        <h3 className="h3-spaced">Key features and what works today</h3>
        <div className="table-wrap">
          <table className="data data-lg">
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col">Status</th>
                <th scope="col">In this prototype</th>
              </tr>
            </thead>
            <tbody>
              {SOLUTION.features.map((f) => (
                <tr key={f.title}>
                  <th scope="row">{f.title}</th>
                  <td>
                    <StatusTag status={f.status} />
                  </td>
                  <td>{f.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <details className="explain">
          <summary>Known limitations of the prototype</summary>
          <ul>
            {LIMITATIONS.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </details>
      </section>

      <section className="section" aria-labelledby="process-h">
        <div className="section-head">
          <p className="eyebrow">Mission process</p>
          <h2 id="process-h">How a mission runs</h2>
          <p className="muted">
            Select a step to see how VISTARA-X implements it. This is an explanatory diagram; the{' '}
            <Link to="/mission">live mission</Link> shows the real system running.
          </p>
        </div>
        <MissionProcess />
        <details className="explain">
          <summary>View the original slide diagram</summary>
          <img
            src="/deck/mission-process.webp"
            width="1600"
            height="588"
            loading="lazy"
            decoding="async"
            alt="Original deck diagram, Autonomous Navigation Mission Process: 01 environment detected, 02 target identified, 03 safe path generated, 04 robot starts autonomous navigation, 05 obstacle detected? If yes, 06 path automatically replanned and back to 04; if no, 07 target reached."
            className="deck-img"
          />
        </details>
      </section>

      <section className="section" aria-labelledby="market-h">
        <div className="section-head">
          <p className="eyebrow">Market research and analysis</p>
          <h2 id="market-h">Where it applies</h2>
          <p className="muted small">{MARKET.note}</p>
        </div>
        <div className="table-wrap">
          <table className="data data-lg">
            <thead>
              <tr>
                {MARKET.columns.map((c) => (
                  <th scope="col" key={c}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MARKET.rows.map((r) => (
                <tr key={r[0]}>
                  <th scope="row">{r[0]}</th>
                  {r.slice(1).map((c) => (
                    <td key={c}>{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section" id="applications" aria-labelledby="apps-h">
        <div className="section-head">
          <p className="eyebrow">Real-world applications</p>
          <h2 id="apps-h">Who it is designed for</h2>
          <p className="muted small">{APPLICATIONS.note}</p>
        </div>
        <div className="table-wrap">
          <table className="data data-lg">
            <thead>
              <tr>
                <th scope="col">Setting</th>
                <th scope="col">What the prototype demonstrates for it</th>
              </tr>
            </thead>
            <tbody>
              {APPLICATIONS.rows.map(([where, what]) => (
                <tr key={where}>
                  <th scope="row">{where}</th>
                  <td>{what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section" id="team" aria-labelledby="team-h">
        <div className="section-head">
          <p className="eyebrow">Team {TEAM.name}</p>
          <h2 id="team-h">Who built it</h2>
        </div>
        <ul className="team">
          {TEAM.members.map((m) => (
            <li key={m.name}>
              <strong>{m.name}</strong>
              <span>{m.role}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
