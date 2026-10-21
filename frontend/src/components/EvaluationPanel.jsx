import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { CheckIcon, WarningIcon } from './Icons';

const ROWS = [
  ['Goal completion', 'goal_completion'],
  ['Collisions (total)', 'collisions_total'],
  ['Near misses (< 0.25 m)', 'near_misses_total'],
  ['Closest approach, worst run (m)', 'min_clearance_worst_m'],
  ['Closest approach, mean (m)', 'min_clearance_mean_m'],
  ['Task duration, mean (s)', 'time_mean_s'],
  ['Path length, mean (m)', 'path_length_mean_m'],
  ['Replans per run, mean', 'replans_mean'],
  ['1 s prediction error, mean (m)', 'prediction_error_1s_mean_m'],
];

/** Stored results of `python -m app.evaluation`: predictive vs reactive, and scenario checks. */
export function EvaluationPanel({ online }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const load = () =>
    api
      .evaluation()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e));

  useEffect(() => {
    if (online) load();
  }, [online]);

  return (
    <section className="panel" id="evaluation" aria-labelledby="evaluation-title">
      <div className="panel-head">
        <h2 id="evaluation-title">Evaluation: predictive vs reactive</h2>
        <button type="button" className="btn btn-sm" onClick={load} disabled={!online}>
          Refresh results
        </button>
      </div>
      {error && (
        <p className={error.status === 404 ? 'empty' : 'feedback-msg feedback-error'}>
          {error.status === 404 ? 'No results yet. Run ' : 'Results unavailable: '}
          {error.status === 404 ? <code>python -m app.evaluation</code> : error.message}
          {error.status === 404 ? ' in backend/ (about 3-5 minutes).' : ''}
        </p>
      )}
      {data && (
        <>
          <p className="muted small">
            Generated {data.generated_at.replace('T', ' ')} by <code>{data.command}</code> on {data.machine}. Scenario{' '}
            <code>{data.comparison.scenario}</code>, {data.comparison.predictive.runs} runs per mode (crossing person at{' '}
            {data.comparison.variants.person_speed_m_s.join(', ')} m/s, three start times). {data.simulation}.
          </p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Predictive</th>
                  <th scope="col">Reactive baseline</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(([label, key]) => (
                  <tr key={key}>
                    <th scope="row">{label}</th>
                    <td className="mono">{data.comparison.predictive[key] ?? '—'}</td>
                    <td className="mono">{data.comparison.reactive[key] ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3 className="sub">Scenario checks</h3>
          <ul className="eval-checks">
            {data.scenario_checks.map((c) => (
              <li key={c.check} className={c.passed ? 'ok' : 'bad'}>
                {c.passed ? <CheckIcon size={14} /> : <WarningIcon size={14} />}
                <span>
                  <strong>{c.passed ? 'Pass' : 'Fail'}:</strong> {c.check}. <span className="muted">{c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted small">One simulated environment with simple motion models; these numbers are not a measure of real-world safety.</p>
        </>
      )}
    </section>
  );
}
