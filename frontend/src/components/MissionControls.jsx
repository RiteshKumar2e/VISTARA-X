import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { api } from '../services/api';
import {
  ClearIcon,
  CloseIcon,
  CrosshairIcon,
  ObstacleIcon,
  PauseIcon,
  PlayIcon,
  ResetIcon,
  SpinnerIcon,
  StopIcon,
} from './Icons';

const ACTIVE = new Set(['planning', 'navigating']);

export function CommandButton({ name, pending, icon: Icon, children, className = 'btn', ...props }) {
  const busy = pending === name;
  return (
    <button type="button" className={className} aria-busy={busy || undefined} {...props}>
      {busy ? <SpinnerIcon size={15} /> : Icon && <Icon size={15} />}
      {children}
    </button>
  );
}

export function validateTarget(xRaw, yRaw, world, margin) {
  const errors = {};
  const x = Number(xRaw);
  const y = Number(yRaw);
  const check = (key, raw, v, max) => {
    if (String(raw).trim() === '' || !Number.isFinite(v)) errors[key] = 'Enter a number in metres.';
    else if (v < margin || v > max - margin)
      errors[key] = `Must be between ${margin.toFixed(2)} and ${(max - margin).toFixed(2)}.`;
  };
  check('x', xRaw, x, world.width);
  check('y', yRaw, y, world.height);
  return { errors, x, y };
}

export function MissionControls({ telemetry, command, online, scenarios, world, clickMode, setClickMode, onRestartDemo }) {
  const { pending, feedback, run, clearFeedback } = command;
  const status = telemetry?.mission?.status;
  const waiting = telemetry?.mission?.waiting;
  const target = telemetry?.target;
  const margin = telemetry?.safety?.inflation ?? 0.45;
  const disabled = !online || !telemetry;

  const [form, setForm] = useState({ x: '', y: '' });
  const [errors, setErrors] = useState({});
  const [scenario, setScenario] = useState('warehouse');
  const [params, setParams] = useState(null);
  const [paramsDirty, setParamsDirty] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const confirmTimer = useRef();

  useEffect(() => {
    if (telemetry?.params && !paramsDirty) setParams(telemetry.params);
  }, [telemetry?.params, paramsDirty]);

  useEffect(() => {
    if (telemetry?.scenario) setScenario(telemetry.scenario);
  }, [telemetry?.scenario]);

  useEffect(() => () => clearTimeout(confirmTimer.current), []);

  const running = ACTIVE.has(status) || waiting;
  const canStart = !disabled && !!target && !running && status !== 'paused';
  const canPause = !disabled && running;
  const canResume = !disabled && status === 'paused';
  const canStop = !disabled && (running || status === 'paused');

  const submitTarget = async (event) => {
    event.preventDefault();
    const { errors: errs, x, y } = validateTarget(form.x, form.y, world, margin);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    await run('target', () => api.setTarget(x, y), () => `Target set to (${x.toFixed(2)}, ${y.toFixed(2)})`);
  };

  const reset = async () => {
    if (running && !confirmReset) {
      setConfirmReset(true);
      clearTimeout(confirmTimer.current);
      confirmTimer.current = setTimeout(() => setConfirmReset(false), 4000);
      return;
    }
    setConfirmReset(false);
    await run('reset', () => api.reset(scenario), () => 'Simulation reset');
  };

  const applyParams = async (event) => {
    event.preventDefault();
    const ok = await run('config', () => api.configure(params), () => 'Parameters applied');
    if (ok) setParamsDirty(false);
  };

  const setParam = (key, value) => {
    setParams((p) => ({ ...p, [key]: value }));
    setParamsDirty(true);
  };

  return (
    <section className="panel controls" aria-labelledby="controls-title">
      <div className="panel-head">
        <h2 id="controls-title">Mission controls</h2>
      </div>

      <div className="control-group">
        <div className="button-row">
          <CommandButton
            name="start"
            pending={pending}
            icon={PlayIcon}
            className="btn btn-primary btn-wide"
            disabled={!canStart || !!pending}
            onClick={() => run('start', () => api.navigate(), () => 'Mission started')}
          >
            Start mission
          </CommandButton>
          {status === 'paused' ? (
            <CommandButton
              name="resume"
              pending={pending}
              icon={PlayIcon}
              disabled={!canResume || !!pending}
              onClick={() => run('resume', api.resume, () => 'Mission resumed')}
            >
              Resume
            </CommandButton>
          ) : (
            <CommandButton
              name="pause"
              pending={pending}
              icon={PauseIcon}
              disabled={!canPause || !!pending}
              onClick={() => run('pause', api.pause, () => 'Mission paused')}
            >
              Pause
            </CommandButton>
          )}
          <CommandButton
            name="stop"
            pending={pending}
            icon={StopIcon}
            disabled={!canStop || !!pending}
            title="Stops immediately (no confirmation): the robot halts safely and the mission can be restarted."
            onClick={() => run('stop', api.stop, () => 'Mission stopped; robot halted')}
          >
            Stop
          </CommandButton>
          <CommandButton
            name="reset"
            pending={pending}
            icon={ResetIcon}
            className={confirmReset ? 'btn btn-danger' : 'btn'}
            disabled={disabled || !!pending}
            onClick={reset}
          >
            {confirmReset ? 'Confirm reset' : 'Reset'}
          </CommandButton>
        </div>
        {!target && telemetry && <p className="hint">Select a target on the map or below to enable Start mission.</p>}
        <div className="feedback" role="status" aria-live="polite">
          <AnimatePresence initial={false}>
            {feedback && (
              <motion.div
                key={feedback.text}
                className={`feedback-msg feedback-${feedback.kind} dismissible`}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <p>
                  <strong>{feedback.kind === 'error' ? 'Error: ' : 'Done: '}</strong>
                  {feedback.text}
                </p>
                <button type="button" className="icon-btn" onClick={clearFeedback} aria-label="Dismiss message">
                  <CloseIcon size={14} />
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <form className="control-group" onSubmit={submitTarget} noValidate>
        <h3>Target</h3>
        <p className="muted small">
          Current:{' '}
          <span className="mono">{target ? `x ${target.x.toFixed(2)}, y ${target.y.toFixed(2)} m` : 'none'}</span>
        </p>
        <div className="field-row">
          {['x', 'y'].map((axis) => (
            <div className="field" key={axis}>
              <label htmlFor={`target-${axis}`}>
                {axis.toUpperCase()} (m)
              </label>
              <input
                id={`target-${axis}`}
                inputMode="decimal"
                autoComplete="off"
                value={form[axis]}
                placeholder={axis === 'x' ? `0 - ${world.width}` : `0 - ${world.height}`}
                aria-invalid={errors[axis] ? 'true' : undefined}
                aria-describedby={errors[axis] ? `target-${axis}-error` : undefined}
                onChange={(e) => setForm((f) => ({ ...f, [axis]: e.target.value }))}
              />
              {errors[axis] && (
                <span className="field-error" id={`target-${axis}-error`}>
                  {errors[axis]}
                </span>
              )}
            </div>
          ))}
          <CommandButton
            name="target"
            pending={pending}
            icon={CrosshairIcon}
            className="btn field-submit"
            type="submit"
            disabled={disabled || !!pending}
          >
            Set target
          </CommandButton>
        </div>
        <fieldset className="segmented">
          <legend>Map click action</legend>
          {[
            ['target', 'Set target'],
            ['obstacle', 'Place obstacle'],
          ].map(([value, label]) => (
            <label key={value} className={clickMode === value ? 'active' : ''}>
              <input
                type="radio"
                name="click-mode"
                value={value}
                checked={clickMode === value}
                onChange={() => setClickMode(value)}
              />
              {label}
            </label>
          ))}
        </fieldset>
      </form>

      <div className="control-group">
        <h3>Obstacles</h3>
        <p className="hint hint-top">
          Use <strong>Place obstacle</strong> above to add one by clicking the map, or click an added obstacle to select it and
          click again elsewhere to move it.
        </p>
        <div className="button-row">
          <CommandButton
            name="inject"
            pending={pending}
            icon={ObstacleIcon}
            disabled={disabled || status !== 'navigating' || !!pending}
            onClick={() => run('inject', api.injectObstacle, (r) => `Obstacle ${r.obstacle.id} placed on the route`)}
          >
            Drop obstacle on route
          </CommandButton>
          <CommandButton
            name="clear"
            pending={pending}
            icon={ClearIcon}
            disabled={disabled || !!pending}
            onClick={() => run('clear', api.clearObstacles, (r) => `Removed ${r.removed} added obstacle(s)`)}
          >
            Clear added
          </CommandButton>
        </div>
        <p className="hint">Dropping an obstacle requires a running mission; it lands a few metres ahead on the active route.</p>
      </div>

      <div className="control-group">
        <h3>Demo</h3>
        <button type="button" className="btn" disabled={disabled || !!pending} onClick={onRestartDemo}>
          <ResetIcon size={15} />
          Restart guided demo
        </button>
        <p className="hint">Resets the warehouse scenario and replays the judging walkthrough on the live simulation.</p>
      </div>

      <div className="control-group">
        <h3>Scenario</h3>
        <div className="field-row">
          <div className="field field-grow">
            <label htmlFor="scenario">Environment</label>
            <select id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {(scenarios.length ? scenarios : [{ key: 'warehouse', name: 'Warehouse aisle' }]).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <CommandButton
            name="scenario"
            pending={pending}
            className="btn field-submit"
            disabled={disabled || !!pending}
            onClick={() => run('scenario', () => api.reset(scenario), () => 'Scenario loaded')}
          >
            Load
          </CommandButton>
        </div>
        <p className="hint">{scenarios.find((s) => s.key === scenario)?.description}</p>
      </div>

      {params && (
        <form className="control-group" onSubmit={applyParams}>
          <h3>Parameters</h3>
          <div className="field">
            <label htmlFor="max-speed">
              Max speed <span className="mono">{Number(params.max_speed).toFixed(1)} m/s</span>
            </label>
            <input
              id="max-speed"
              type="range"
              min="0.2"
              max="1.5"
              step="0.1"
              value={params.max_speed}
              onChange={(e) => setParam('max_speed', Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="safety-margin">
              Safety margin <span className="mono">{Number(params.safety_margin).toFixed(2)} m</span>
            </label>
            <input
              id="safety-margin"
              type="range"
              min="0.05"
              max="0.6"
              step="0.05"
              value={params.safety_margin}
              onChange={(e) => setParam('safety_margin', Number(e.target.value))}
            />
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={params.moving_obstacles}
              onChange={(e) => setParam('moving_obstacles', e.target.checked)}
            />
            Moving obstacles (patrolling person)
          </label>
          <CommandButton name="config" pending={pending} type="submit" disabled={disabled || !paramsDirty || !!pending}>
            Apply parameters
          </CommandButton>
        </form>
      )}
    </section>
  );
}
