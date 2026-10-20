import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Term } from './Term';

const n = (v, d = 1, unit = '') => (v === null || v === undefined ? 'Unavailable' : `${Number(v).toFixed(d)}${unit}`);

const STATUS = { loaded: 'Loaded', available: 'Not loaded yet', error: 'Unavailable' };

export function ModelsPanel({ telemetry, command, online }) {
  const reg = telemetry?.perception?.models;
  const [form, setForm] = useState(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (reg && !dirty) {
      const p = reg.policy;
      setForm({
        primary: p.primary,
        secondary: p.secondary ?? '',
        mode: p.mode,
        confidence: p.confidence,
        iou: p.iou,
        latency_budget_ms: p.latency_budget_ms,
      });
    }
  }, [reg, dirty]);

  if (!reg || !form) {
    return (
      <section className="panel" aria-labelledby="models-title">
        <div className="panel-head">
          <h2 id="models-title">Detection models</h2>
        </div>
        <p className="empty">Waiting for the model registry.</p>
      </section>
    );
  }

  const usable = reg.models.filter((m) => m.status !== 'error');
  const realModels = usable.filter((m) => m.key !== 'simulated');
  const set = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
  };
  const apply = async (e) => {
    e.preventDefault();
    const body = {
      primary: form.primary,
      mode: form.secondary ? form.mode : 'single',
      confidence: form.confidence,
      iou: form.iou,
      latency_budget_ms: form.latency_budget_ms,
      ...(form.secondary ? { secondary: form.secondary } : { clear_secondary: true }),
    };
    const ok = await command.run('models', () => api.selectModels(body), () => 'Model policy applied');
    if (ok) setDirty(false);
  };
  const rt = reg.runtime;
  const disabled = !online || !!command.pending;

  return (
    <section className="panel" aria-labelledby="models-title">
      <div className="panel-head">
        <h2 id="models-title">Detection models</h2>
        <span className="muted small">{reg.ultralytics === 'ready' ? 'Ultralytics installed' : reg.ultralytics}</span>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Status</th>
              <th scope="col">Task / device</th>
              <th scope="col">
                <Term tip="Measured on this machine by the backend: last and mean inference time over the latest 50 runs.">Latency</Term>
              </th>
            </tr>
          </thead>
          <tbody>
            {reg.models.map((m) => (
              <tr key={m.key}>
                <th scope="row">
                  {m.key}
                  {m.file && <span className="muted small"> ({m.file})</span>}
                </th>
                <td>
                  {m.key === 'simulated' ? 'Ground truth, not a model' : STATUS[m.status] || m.status}
                  {m.error && <span className="field-error"> {m.error}</span>}
                </td>
                <td className="small">
                  {m.task || 'unknown until loaded'} &middot; {m.device}
                </td>
                <td className="mono small">
                  {m.latency_ms?.samples ? `${n(m.latency_ms.last, 0)} / ${n(m.latency_ms.mean, 0)} ms (${m.runs} runs)` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!realModels.length && (
        <p className="hint">
          No usable YOLO weights. Place <code>.pt</code> files in <code>backend/models/</code> and restart the backend.
        </p>
      )}

      <form className="model-form" onSubmit={apply}>
        <div className="field-row">
          <div className="field field-grow">
            <label htmlFor="model-primary">Primary model</label>
            <select id="model-primary" value={form.primary} disabled={disabled} onChange={(e) => set('primary', e.target.value)}>
              {usable.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.key === 'simulated' ? 'Simulated (ground truth)' : m.key}
                </option>
              ))}
            </select>
          </div>
          <div className="field field-grow">
            <label htmlFor="model-secondary">Secondary model</label>
            <select
              id="model-secondary"
              value={form.secondary}
              disabled={disabled || realModels.length < 2}
              onChange={(e) => set('secondary', e.target.value)}
            >
              <option value="">None (single-model mode)</option>
              {realModels
                .filter((m) => m.key !== form.primary)
                .map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.key}
                  </option>
                ))}
            </select>
          </div>
        </div>
        {realModels.length < 2 && <p className="hint hint-top">A secondary model needs a second compatible weight file.</p>}
        <div className="field">
          <label htmlFor="model-mode">
            <Term tip="Single: primary only. Cascade: the secondary runs only when the primary sees a trigger class (person) or a detection with confidence between 0.25 and 0.5. Multi: the secondary also runs on every Nth frame. Results are merged with class-aware NMS; agreement is reported but confidence is not raised.">
              Execution policy
            </Term>
          </label>
          <select id="model-mode" value={form.secondary ? form.mode : 'single'} disabled={disabled || !form.secondary} onChange={(e) => set('mode', e.target.value)}>
            <option value="single">Single model</option>
            <option value="cascade">Cascade (verify on trigger)</option>
            <option value="multi">Multi-model on selected frames</option>
          </select>
        </div>
        {[
          ['confidence', 'Confidence threshold', 0.05, 0.95, 0.05, ''],
          ['iou', 'IoU threshold (NMS / fusion)', 0.1, 0.95, 0.05, ''],
          ['latency_budget_ms', 'Latency budget', 50, 1000, 25, ' ms'],
        ].map(([key, text, min, max, step, unit]) => (
          <div className="field" key={key}>
            <label htmlFor={`model-${key}`}>
              {text} <span className="mono">{form[key]}{unit}</span>
            </label>
            <input
              id={`model-${key}`}
              type="range"
              min={min}
              max={max}
              step={step}
              value={form[key]}
              disabled={disabled}
              onChange={(e) => set(key, Number(e.target.value))}
            />
          </div>
        ))}
        <button type="submit" className="btn" disabled={disabled || !dirty}>
          Apply model policy
        </button>
      </form>

      <h3 className="sub">Runtime (measured)</h3>
      <dl className="kv-grid">
        <div className="kv">
          <dt>
            <Term tip="Process every k-th camera frame. Raised automatically when the average frame time exceeds the latency budget.">Frame stride</Term>
          </dt>
          <dd className="mono">{rt.stride}</dd>
        </div>
        <div className="kv">
          <dt>Average frame time</dt>
          <dd className="mono">{n(rt.ema_frame_ms, 1, ' ms')}</dd>
        </div>
        <div className="kv">
          <dt>Frames processed / skipped</dt>
          <dd className="mono">
            {rt.frames_processed} / {rt.frames_skipped}
          </dd>
        </div>
        <div className="kv">
          <dt>Secondary model</dt>
          <dd className="mono">
            {reg.policy.secondary ? (rt.secondary_suspended ? 'suspended (over budget)' : rt.last_secondary_reason || 'idle') : 'not configured'}
          </dd>
        </div>
      </dl>
    </section>
  );
}
