import { useState } from 'react';
import { CheckIcon, WarningIcon } from './Icons';
import { Term } from './Term';

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
const NEAR_MISS = 0.25;
const MODES = [
  ['predictive', 'Predictive', 'circle'],
  ['reactive', 'Reactive baseline', 'diamond'],
];

function Marker({ shape, x, y, mode }) {
  return shape === 'circle' ? (
    <circle cx={x} cy={y} r="5" className={`ev-mark ev-${mode}`} />
  ) : (
    <rect x={x - 4.5} y={y - 4.5} width="9" height="9" transform={`rotate(45 ${x} ${y})`} className={`ev-mark ev-${mode}`} />
  );
}

/** Closest approach to the crossing person, per run variant, for both modes. */
function ClearanceChart({ runs, variants }) {
  const [hover, setHover] = useState(null);
  const keys = [];
  variants.person_speed_m_s.forEach((s) => variants.start_offset_s.forEach((o) => keys.push([s, o])));
  const find = (mode, s, o) => runs.find((r) => r.mode === mode && r.person_speed === s && r.start_offset_s === o);
  const values = runs.map((r) => r.min_moving_clearance_m).filter((v) => v != null);
  const yMax = Math.max(1, Math.ceil(Math.max(...values) * 2) / 2);
  const yMin = Math.min(-0.25, Math.floor(Math.min(...values) * 4) / 4);
  const W = 640;
  const H = 260;
  const pad = { l: 44, r: 12, t: 14, b: 46 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const x = (i) => pad.l + ((i + 0.5) / keys.length) * iw;
  const y = (v) => pad.t + ((yMax - v) / (yMax - yMin)) * ih;
  const ticks = [];
  for (let v = Math.ceil(yMin * 2) / 2; v <= yMax + 1e-9; v += 0.5) ticks.push(Number(v.toFixed(2)));
  return (
    <figure className="ev-chart">
      <figcaption className="ev-chart-title">
        <strong>Closest approach to the crossing person, per run</strong>
        <span className="muted small">Higher is safer. Below 0 m the robot touched the person (collision); below {NEAR_MISS} m counts as a near miss.</span>
      </figcaption>
      <ul className="ev-legend" aria-label="Legend">
        {MODES.map(([mode, label, shape]) => (
          <li key={mode}>
            <svg width="14" height="14" aria-hidden="true">
              <Marker shape={shape} x={7} y={7} mode={mode} />
            </svg>
            {label}
          </li>
        ))}
      </ul>
      <div className="ev-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Scatter of closest approach per run variant for predictive and reactive modes; the per-run table below lists every value.">
          <rect x={pad.l} y={y(0)} width={iw} height={y(yMin) - y(0)} className="ev-band-collision" />
          <rect x={pad.l} y={y(NEAR_MISS)} width={iw} height={y(0) - y(NEAR_MISS)} className="ev-band-near" />
          <text x={W - pad.r - 4} y={y(yMin) - 6} className="ev-band-label" textAnchor="end">
            collision
          </text>
          <text x={W - pad.r - 4} y={y(0) - 5} className="ev-band-label" textAnchor="end">
            near miss
          </text>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className={v === 0 ? 'ev-zero' : 'ev-grid'} />
              <text x={pad.l - 8} y={y(v) + 4} className="ev-tick" textAnchor="end">
                {v.toFixed(1)}
              </text>
            </g>
          ))}
          <text x={12} y={pad.t + ih / 2} className="ev-axis-label" transform={`rotate(-90 12 ${pad.t + ih / 2})`} textAnchor="middle">
            metres
          </text>
          {keys.map(([s, o], i) => (
            <g key={`${s}-${o}`}>
              <text x={x(i)} y={H - pad.b + 16} className="ev-tick" textAnchor="middle">
                {s} m/s
              </text>
              <text x={x(i)} y={H - pad.b + 30} className="ev-tick ev-tick-faint" textAnchor="middle">
                +{o} s
              </text>
              {MODES.map(([mode, label, shape], k) => {
                const r = find(mode, s, o);
                if (!r || r.min_moving_clearance_m == null) return null;
                const cx = x(i) + (k === 0 ? -7 : 7);
                const cy = y(Math.max(yMin, r.min_moving_clearance_m));
                return (
                  <g
                    key={mode}
                    tabIndex={0}
                    className="ev-hit"
                    onMouseEnter={() => setHover({ r, label, cx, cy })}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover({ r, label, cx, cy })}
                    onBlur={() => setHover(null)}
                  >
                    <circle cx={cx} cy={cy} r="11" className="ev-hit-area" />
                    <Marker shape={shape} x={cx} y={cy} mode={mode} />
                  </g>
                );
              })}
            </g>
          ))}
          <text x={pad.l + iw / 2} y={H - 4} className="ev-axis-label" textAnchor="middle">
            person speed and start offset (9 variants)
          </text>
        </svg>
        {hover && (
          <div className="ev-tip" role="tooltip" style={{ left: `${(hover.cx / W) * 100}%`, top: `${(hover.cy / H) * 100}%` }}>
            <strong>{hover.label}</strong>
            <span>
              Person {hover.r.person_speed} m/s, start +{hover.r.start_offset_s} s
            </span>
            <span className="mono">closest {hover.r.min_moving_clearance_m.toFixed(2)} m</span>
            <span>
              {hover.r.status.replace('_', ' ')} &middot; {hover.r.collisions} collisions &middot; {hover.r.time_s} s
            </span>
          </div>
        )}
      </div>
    </figure>
  );
}

function Headline({ label, pred, reac, tip }) {
  return (
    <div className="ev-stat">
      <dt>{tip ? <Term tip={tip}>{label}</Term> : label}</dt>
      <dd>
        <span className="ev-val ev-val-predictive">
          <span className="ev-swatch ev-predictive" aria-hidden="true" />
          <span className="sr-only">Predictive: </span>
          <strong className="mono">{pred ?? '—'}</strong>
        </span>
        <span className="ev-val ev-val-reactive">
          <span className="ev-swatch ev-reactive" aria-hidden="true" />
          <span className="sr-only">Reactive baseline: </span>
          <strong className="mono">{reac ?? '—'}</strong>
        </span>
      </dd>
    </div>
  );
}

/** Predictive vs reactive comparison from the recorded evaluation (python -m app.evaluation). */
export function EvaluationPanel({ online, evaluation }) {
  const { data, error, loading, reload } = evaluation;
  const cmp = data?.comparison;
  const P = cmp?.predictive;
  const R = cmp?.reactive;
  const dt = P && R && P.time_mean_s != null && R.time_mean_s != null ? (P.time_mean_s - R.time_mean_s).toFixed(1) : null;
  return (
    <section className="panel evaluation" id="evaluation" aria-labelledby="evaluation-title">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2 id="evaluation-title">Evaluation: predictive vs reactive</h2>
        </div>
        <button type="button" className="btn btn-sm" onClick={reload} disabled={!online || loading}>
          Refresh results
        </button>
      </div>
      {error && (
        <p className={error.status === 404 ? 'empty' : 'feedback-msg feedback-error'}>
          {error.status === 404 ? 'No recorded results yet. Run ' : 'Results unavailable: '}
          {error.status === 404 ? <code>python -m app.evaluation</code> : error.message}
          {error.status === 404 ? ' in backend/ (about 4 minutes).' : ''}
        </p>
      )}
      {!data && !error && <p className="empty">{online ? 'Loading recorded results...' : 'Connect to the backend to load the recorded evaluation.'}</p>}
      {data && cmp && (
        <>
          <p className="ev-provenance small">
            <span className="chip">Recorded evaluation</span> Generated {data.generated_at.replace('T', ' ').slice(0, 19)} UTC by{' '}
            <code>{data.command}</code>. Scenario <code>{cmp.scenario}</code>, <strong>{P.runs} runs per mode</strong>: a person
            crossing at {cmp.variants.person_speed_m_s.join(', ')} m/s, starting {cmp.variants.start_offset_s.join(', ')} s early. Same
            seeds and variants for both modes.
          </p>
          <div className="ev-top">
            <dl className="ev-stats">
              <div className="ev-stats-head" aria-hidden="true">
                <span />
                <span>
                  <span className="ev-swatch ev-predictive" />
                  Predictive
                </span>
                <span>
                  <span className="ev-swatch ev-reactive" />
                  Reactive
                </span>
              </div>
              <Headline label="Goal completion" pred={P.goal_completion} reac={R.goal_completion} />
              <Headline label="Collisions" pred={P.collisions_total} reac={R.collisions_total} />
              <Headline label={`Near misses (< ${NEAR_MISS} m)`} pred={P.near_misses_total} reac={R.near_misses_total} />
              <Headline
                label="Worst closest approach"
                pred={P.min_clearance_worst_m != null ? `${P.min_clearance_worst_m.toFixed(2)} m` : null}
                reac={R.min_clearance_worst_m != null ? `${R.min_clearance_worst_m.toFixed(2)} m` : null}
                tip="The smallest distance between the robot's and the person's footprints over all runs. Negative means they overlapped (a collision)."
              />
              <Headline label="Mean duration" pred={P.time_mean_s != null ? `${P.time_mean_s} s` : null} reac={R.time_mean_s != null ? `${R.time_mean_s} s` : null} />
              <Headline label="Mean path length" pred={P.path_length_mean_m != null ? `${P.path_length_mean_m} m` : null} reac={R.path_length_mean_m != null ? `${R.path_length_mean_m} m` : null} />
            </dl>
            {cmp.runs?.length ? <ClearanceChart runs={cmp.runs} variants={cmp.variants} /> : null}
          </div>
          {dt !== null && (
            <p className="ev-takeaway">
              In these runs, predictive navigation took {Number(dt) >= 0 ? `${dt} s longer` : `${Math.abs(dt)} s less`} per mission on average and kept
              a worst-case clearance of {P.min_clearance_worst_m?.toFixed(2)} m, against {R.min_clearance_worst_m?.toFixed(2)} m for the reactive baseline.
            </p>
          )}
          <details className="ev-more">
            <summary>All metrics, every run and scenario checks</summary>
            <div className="table-wrap">
              <table className="data">
                <caption className="sr-only">Summary metrics per mode</caption>
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
                      <td className="mono">{P[key] ?? '—'}</td>
                      <td className="mono">{R[key] ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {cmp.runs?.length ? (
              <div className="table-wrap">
                <table className="data">
                  <caption className="sr-only">Every run</caption>
                  <thead>
                    <tr>
                      <th scope="col">Mode</th>
                      <th scope="col">Person speed</th>
                      <th scope="col">Start offset</th>
                      <th scope="col">Result</th>
                      <th scope="col">Time</th>
                      <th scope="col">Replans</th>
                      <th scope="col">Collisions</th>
                      <th scope="col">Closest approach</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cmp.runs.map((r) => (
                      <tr key={`${r.mode}-${r.person_speed}-${r.start_offset_s}`}>
                        <th scope="row">{r.mode}</th>
                        <td className="mono">{r.person_speed} m/s</td>
                        <td className="mono">{r.start_offset_s} s</td>
                        <td>{r.status.replace('_', ' ')}</td>
                        <td className="mono">{r.time_s} s</td>
                        <td className="mono">{r.replans}</td>
                        <td className="mono">{r.collisions}</td>
                        <td className="mono">{r.min_moving_clearance_m ?? '—'} m</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
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
            <p className="muted small">
              Reproduce with <code>python -m app.evaluation</code> in <code>backend/</code> (about 4 minutes); the results file and this
              panel update together.
            </p>
          </details>
          <p className="muted small">
            One simulated scenario family with scripted pedestrian motion and simulated sensors. These numbers compare two strategies under
            identical conditions; they are not a measure of real-world safety.
          </p>
        </>
      )}
    </section>
  );
}
