import { useEffect, useState } from 'react';
import { api, getAccessKey, setAccessKey } from '../services/api';
import { CheckIcon, InfoIcon, WarningIcon } from './Icons';
import { Term } from './Term';

const STEPS = [
  ['queued', 'Queued'],
  ['to_pickup', 'To pickup'],
  ['loading', 'Loading'],
  ['to_dropoff', 'To drop-off'],
  ['awaiting_pin', 'Awaiting PIN'],
  ['delivered', 'Delivered'],
];
const STATUS_TEXT = Object.fromEntries(STEPS);
STATUS_TEXT.failed = 'Failed';
STATUS_TEXT.cancelled = 'Cancelled';
const MODE = { idle: 'Ready', task: 'On a delivery', returning: 'Returning to the dock', charging: 'Charging' };

function BatteryGauge({ battery }) {
  const level = battery.level;
  const tone = level < battery.critical ? 'bad' : level < battery.low ? 'warn' : 'ok';
  return (
    <div className="battery" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)} aria-label="Battery">
      <span className={`battery-bar battery-${tone}`}>
        <span style={{ width: `${level}%` }} />
      </span>
      <span className="mono small">
        {level.toFixed(0)}% · {battery.state}
        {battery.charge_cycles ? ` · ${battery.charge_cycles} charge cycle${battery.charge_cycles > 1 ? 's' : ''}` : ''}
      </span>
    </div>
  );
}

function TaskCard({ task, command, busy }) {
  const [pin, setPin] = useState('');
  const [loader, setLoader] = useState('');
  const idx = STEPS.findIndex(([k]) => k === task.status);
  return (
    <article className="task-card" aria-label={`Delivery ${task.id}`}>
      <header className="cmd-head">
        <strong>
          #{task.id} {task.item}
        </strong>
        <span className={`risk-tag risk-tag-${task.priority === 'urgent' ? 'high' : task.priority === 'low' ? 'low' : 'medium'}`}>{task.priority}</span>
      </header>
      <p className="small">
        {task.pickup.name} → {task.dropoff.name} · for {task.recipient} · requested by {task.requested_by}
      </p>
      <ol className="task-steps" aria-label="Delivery progress">
        {STEPS.map(([key, label], i) => (
          <li key={key} className={i < idx ? 'done' : i === idx ? 'current' : ''} aria-current={i === idx ? 'step' : undefined}>
            {label}
          </li>
        ))}
      </ol>
      {task.status === 'loading' && (
        <form
          className="cmd-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            command.run('task', () => api.taskLoaded(task.id, loader || 'staff'), () => `Delivery #${task.id}: loaded`);
          }}
        >
          <input aria-label="Loaded by" placeholder="Loaded by (name)" value={loader} onChange={(e) => setLoader(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <CheckIcon size={14} /> Confirm loaded
          </button>
        </form>
      )}
      {task.status === 'awaiting_pin' && (
        <form
          className="cmd-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            command.run('task', () => api.taskDeliver(task.id, pin), () => `Delivery #${task.id} delivered (PIN verified)`).then(() => setPin(''));
          }}
        >
          <input
            aria-label="Recipient PIN"
            inputMode="numeric"
            pattern="[0-9]{4}"
            maxLength={4}
            placeholder="Recipient PIN"
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
          />
          <button type="submit" className="btn btn-primary" disabled={busy || pin.length !== 4}>
            Verify PIN and hand over
          </button>
        </form>
      )}
      <div className="button-row">
        <span className="muted small mono">{task.distance_m.toFixed(1)} m · attempts {task.attempts}</span>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => command.run('task', () => api.taskCancel(task.id), () => `Delivery #${task.id} cancelled`)}>
          Cancel
        </button>
      </div>
    </article>
  );
}

/** Delivery operations: request, queue, battery, proof of delivery, notifications and reports. */
export function OperationsPanel({ telemetry, online, command }) {
  const ops = telemetry?.operations;
  const scenario = telemetry?.scenario;
  const [places, setPlaces] = useState([]);
  const [form, setForm] = useState({ item: 'medicine', pickup: '', dropoff: '', priority: 'normal', requested_by: 'Nurse station', recipient: 'Ward staff' });
  const [created, setCreated] = useState(null);
  const [report, setReport] = useState(null);
  const [auth, setAuth] = useState(null);
  const [key, setKey] = useState(getAccessKey());
  const busy = !online || !!command.pending;

  useEffect(() => {
    if (!online) return;
    api
      .places()
      .then((r) => {
        const usable = r.places.filter((p) => p.key !== 'charging');
        setPlaces(usable);
        setForm((f) => ({ ...f, pickup: usable[1]?.key || usable[0]?.key || '', dropoff: usable[2]?.key || usable[0]?.key || '' }));
      })
      .catch(() => {});
    api.authStatus().then(setAuth).catch(() => {});
  }, [online, scenario]);

  if (!ops) {
    return (
      <section className="panel" id="operations" aria-labelledby="operations-title">
        <div className="panel-head">
          <h2 id="operations-title">Delivery operations</h2>
        </div>
        <p className="empty">Waiting for telemetry.</p>
      </section>
    );
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const create = async (e) => {
    e.preventDefault();
    const r = await command.run('task', () => api.createTask(form), (res) => `Delivery #${res.task.id} queued`);
    if (r) setCreated(r.task);
  };
  const loadReport = () => api.opsReport().then(setReport).catch(() => {});

  return (
    <section className="panel operations" id="operations" aria-labelledby="operations-title">
      <div className="panel-head">
        <h2 id="operations-title">Delivery operations</h2>
        <span className="muted small">{MODE[ops.mode] || ops.mode}</span>
      </div>

      <div className="ops-top">
        <BatteryGauge battery={ops.battery} />
        <div className="button-row">
          <button type="button" className="btn btn-sm" disabled={busy || !ops.dock || ops.mode === 'task'} onClick={() => command.run('ops', api.opsDock, () => 'Returning to the charging dock')}>
            Return to dock
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            onClick={() => command.run('ops', () => api.opsConfig({ battery: 25 }), () => 'Battery set to 25% (demo)')}
          >
            Simulate low battery
          </button>
          {/* The explanation sits beside the button: a tooltip button inside a button is invalid HTML. */}
          <Term tip="Demo control: sets the simulated charge to 25% so you can watch the robot finish its job, return to the dock and charge.">
            <span aria-hidden="true">?</span>
            <span className="sr-only">About simulate low battery</span>
          </Term>
        </div>
      </div>
      <p className="muted small">{ops.battery.rates}</p>

      <div className="cmd-options">
        <label className="check">
          <input type="checkbox" checked={ops.auto_dispatch} disabled={busy} onChange={(e) => command.run('ops', () => api.opsConfig({ auto_dispatch: e.target.checked }), () => (e.target.checked ? 'Delivery queue running' : 'Delivery queue paused'))} />
          Run the delivery queue automatically
        </label>
        <label className="check">
          <input type="checkbox" checked={ops.auto_load} disabled={busy} onChange={(e) => command.run('ops', () => api.opsConfig({ auto_load: e.target.checked }), () => 'Auto-load updated')} />
          Auto-confirm loading after 3 s (demo; normally staff confirm)
        </label>
      </div>

      <form className="ops-form" onSubmit={create}>
        <h3 className="sub">New delivery</h3>
        <div className="field-row">
          <div className="field">
            <label htmlFor="ops-item">Item</label>
            <input id="ops-item" value={form.item} maxLength={60} onChange={set('item')} />
          </div>
          <div className="field">
            <label htmlFor="ops-priority">Priority</label>
            <select id="ops-priority" value={form.priority} onChange={set('priority')}>
              <option value="urgent">Urgent</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="ops-pickup">Pickup</label>
            <select id="ops-pickup" value={form.pickup} onChange={set('pickup')}>
              {places.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ops-dropoff">Drop-off</label>
            <select id="ops-dropoff" value={form.dropoff} onChange={set('dropoff')}>
              {places.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="ops-by">Requested by</label>
            <input id="ops-by" value={form.requested_by} maxLength={40} onChange={set('requested_by')} />
          </div>
          <div className="field">
            <label htmlFor="ops-to">Recipient</label>
            <input id="ops-to" value={form.recipient} maxLength={40} onChange={set('recipient')} />
          </div>
        </div>
        <button type="submit" className="btn btn-primary" disabled={busy || !form.pickup || form.pickup === form.dropoff}>
          Request delivery
        </button>
        {created && (
          <p className="feedback-msg feedback-success" role="status">
            Delivery #{created.id} queued. Give the recipient this PIN: <strong className="mono pin">{created.pin}</strong>. Spoken requests work too:
            &ldquo;Pharmacy se Ward B tak dawai le jao&rdquo;.
          </p>
        )}
      </form>

      <h3 className="sub">Current delivery</h3>
      {ops.active ? <TaskCard task={ops.active} command={command} busy={busy} /> : <p className="empty">No delivery in progress.</p>}

      <h3 className="sub">Queue ({ops.queue.length})</h3>
      {ops.queue.length ? (
        <ol className="ops-list">
          {ops.queue.map((t) => (
            <li key={t.id}>
              <span className={`risk-tag risk-tag-${t.priority === 'urgent' ? 'high' : t.priority === 'low' ? 'low' : 'medium'}`}>{t.priority}</span> #{t.id}{' '}
              {t.item}: {t.pickup.name} → {t.dropoff.name}
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => command.run('task', () => api.taskCancel(t.id), () => `Delivery #${t.id} cancelled`)}>
                Cancel
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty">The queue is empty.</p>
      )}

      <details className="explain">
        <summary>Recent deliveries and notifications</summary>
        <ul className="ops-list">
          {ops.recent.map((t) => (
            <li key={t.id}>
              #{t.id} {t.item}: {t.pickup.name} → {t.dropoff.name} · <strong>{STATUS_TEXT[t.status] || t.status}</strong>
              {t.proof ? ` · ${t.proof.duration_s} s, PIN verified` : ''}
            </li>
          ))}
        </ul>
        <h4 className="sub">Notifications {ops.webhook ? '(also sent to the configured webhook)' : '(in-app only; set VISTARA_WEBHOOK_URL to forward)'}</h4>
        <ul className="ops-list">
          {ops.notifications.map((n) => (
            <li key={n.id}>
              {n.level === 'success' ? <CheckIcon size={12} /> : n.level === 'warning' || n.level === 'error' ? <WarningIcon size={12} /> : <InfoIcon size={12} />}{' '}
              <span className="muted small">to {n.to}:</span> {n.text}
              {n.webhook && <span className="muted small"> [{n.webhook}]</span>}
            </li>
          ))}
        </ul>
      </details>

      <details className="explain" onToggle={(e) => e.target.open && loadReport()}>
        <summary>Operations report</summary>
        {report ? (
          <>
            <dl className="kv-grid map-kv">
              {[
                ['Delivered', report.delivered],
                ['Failed', report.failed],
                ['Cancelled', report.cancelled],
                ['Mean delivery time', report.mean_delivery_time_s != null ? `${report.mean_delivery_time_s} s` : '—'],
                ['Distance driven', `${report.total_distance_m} m`],
                ['Collisions', report.collisions],
                ['Near misses', report.near_misses],
                ['Charge cycles', report.charge_cycles],
              ].map(([k, v]) => (
                <div className="kv" key={k}>
                  <dt>{k}</dt>
                  <dd className="mono">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="small">
              <a href={api.reportCsvUrl()} download>
                Download CSV
              </a>{' '}
              · <button type="button" className="btn btn-sm" onClick={loadReport}>Refresh</button>
            </p>
            <p className="muted small">{report.note}</p>
          </>
        ) : (
          <p className="empty">Loading…</p>
        )}
      </details>

      {auth?.enabled && (
        <details className="explain">
          <summary>Access key (role: {auth.role})</summary>
          <form
            className="cmd-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              setAccessKey(key.trim());
              api.authStatus().then(setAuth).catch(() => {});
            }}
          >
            <input type="password" aria-label="Access key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Operator or admin key" />
            <button type="submit" className="btn btn-sm">
              Save
            </button>
          </form>
          <p className="muted small">Viewing needs no key. Changes need an operator key; resets and settings need the admin key. The emergency stop never needs a key.</p>
        </details>
      )}
    </section>
  );
}
