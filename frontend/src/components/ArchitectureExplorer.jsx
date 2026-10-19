import { useRef, useState } from 'react';
import { ARCHITECTURE, ARCHITECTURE_LAYERS, STAGE_LIMITS } from '../content/deck';
import { StatusTag } from './StatusTag';

const n = (v, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));

/** Live values for a stage, read from current telemetry. Returns [label, value] rows. */
function liveRows(key, t) {
  if (!t) return null;
  const p = t.perception;
  switch (key) {
    case 'camera':
      return [
        ['Renderer', p.renderer === 'pybullet' ? 'PyBullet TinyRenderer' : 'Analytic ray casting'],
        ['Frames processed', p.frame_seq],
        ['Frame rate setting', `${p.rate_hz} Hz${p.enabled ? '' : ' (paused)'}`],
      ];
    case 'detector':
      return [
        ['Active detector', p.source_label],
        ['YOLOv8', p.yolo_available ? 'available' : `unavailable (${p.yolo_status})`],
        ['Detections in last frame', p.detections.length],
      ];
    case 'scene':
      return [
        ['Relevant / ignored', `${p.scene.relevant_count ?? 0} / ${p.scene.ignored_count ?? 0}`],
        ['Obstacle tracks', p.tracks.length],
        ['Map observed by camera', `${Math.round((p.explored ?? 0) * 100)}%`],
      ];
    case 'target':
      return [['Target', t.target ? `x ${n(t.target.x)}, y ${n(t.target.y)} m` : 'none selected']];
    case 'mission':
      return [
        ['Mission status', t.mission.status.replace('_', ' ')],
        ['Detail', t.mission.reason || '—'],
      ];
    case 'plan':
      return t.last_plan
        ? t.last_plan.success
          ? [
              ['Route length', `${n(t.last_plan.length)} m`],
              ['Waypoints', t.last_plan.waypoints],
              ['Nodes expanded', t.last_plan.expanded],
              ['Planning time', `${n(t.last_plan.planning_ms, 1)} ms`],
            ]
          : [['Last plan', `failed (${t.last_plan.reason})`]]
        : [['Last plan', 'none yet']];
    case 'replans':
      return [
        ['Replans this mission', t.mission.replans],
        ['Safety stops', t.mission.safety_stops],
      ];
    case 'robot':
      return [
        ['Pose', `x ${n(t.robot.x)}, y ${n(t.robot.y)} m, ${t.robot.heading_deg}°`],
        ['Command', `${n(t.robot.v)} m/s, ${n(t.robot.w)} rad/s`],
      ];
    case 'grid':
      return [
        ['Planner inflation', `${n(t.safety.inflation)} m (radius + margin)`],
        ['Obstacles rasterised', t.obstacles.length],
        ['Map observed by camera', `${Math.round((t.perception.explored ?? 0) * 100)}%`],
      ];
    case 'telemetry':
      return [
        ['Telemetry version', t.version],
        ['Sequence number', t.seq],
        ['Events in snapshot', t.events.length],
      ];
    case 'safety':
      return [
        ['Collision backend', t.safety.physics === 'pybullet' ? 'PyBullet' : 'analytic 2D'],
        ['Clearance', `${n(Math.max(t.safety.clearance, 0))} m to ${t.safety.nearest}`],
        ['Collisions', t.safety.collisions],
        ['Telemetry seq', t.seq],
      ];
    default:
      return null;
  }
}

export function ArchitectureExplorer({ telemetry, connection }) {
  const [selected, setSelected] = useState('2.3');
  const buttons = useRef([]);
  const stage = ARCHITECTURE.find((s) => s.id === selected);
  const rows = stage.live ? liveRows(stage.live, telemetry) : null;

  const onKey = (event, index) => {
    const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
    if (!(event.key in keys) && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    let next = index + (keys[event.key] || 0);
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = ARCHITECTURE.length - 1;
    next = (next + ARCHITECTURE.length) % ARCHITECTURE.length;
    buttons.current[next]?.focus();
    setSelected(ARCHITECTURE[next].id);
  };

  return (
    <div className="arch">
      <div className="arch-diagram" role="group" aria-label="Architecture stages. Use arrow keys to move between stages.">
        {ARCHITECTURE_LAYERS.map((layer, li) => (
          <div className={`arch-layer arch-${layer.id}`} key={layer.id}>
            <h3 className="arch-layer-title">
              {li + 1}. {layer.title}
            </h3>
            <ol>
              {ARCHITECTURE.filter((s) => s.layer === layer.id).map((s) => {
                const index = ARCHITECTURE.indexOf(s);
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      ref={(el) => (buttons.current[index] = el)}
                      className={`arch-stage${selected === s.id ? ' selected' : ''}`}
                      aria-pressed={selected === s.id}
                      aria-controls="arch-detail"
                      tabIndex={selected === s.id ? 0 : -1}
                      onClick={() => setSelected(s.id)}
                      onKeyDown={(e) => onKey(e, index)}
                    >
                      <span className="arch-id mono">{s.id}</span>
                      <span className="arch-text">
                        <span className="arch-title">{s.title}</span>
                        <span className="arch-deck">{s.deck}</span>
                      </span>
                      <span className={`arch-dot dot-${s.status}`} title={s.status} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
        <p className="arch-loop">
          <span aria-hidden="true">&#8634;</span> Environment feedback loops back to obstacle avoidance and path planning:
          continuous replanning.
        </p>
      </div>

      <section id="arch-detail" className="arch-detail panel" aria-live="polite" aria-labelledby="arch-detail-title">
        <div className="panel-head">
          <h3 id="arch-detail-title">
            <span className="mono muted">{stage.id}</span> {stage.title}
          </h3>
          <StatusTag status={stage.status} />
        </div>
        <p className="lead-small">{stage.purpose}</p>
        <dl className="kv-grid arch-io">
          <div className="kv">
            <dt>Inputs</dt>
            <dd>{stage.inputs}</dd>
          </div>
          <div className="kv">
            <dt>Outputs</dt>
            <dd>{stage.outputs}</dd>
          </div>
        </dl>
        <h4 className="sub">How it is implemented</h4>
        <p>{stage.implementation}</p>
        <p className="muted small">
          Code: {stage.modules.map((m, i) => (
            <span key={m}>
              {i ? ', ' : ''}
              <code>{m}</code>
            </span>
          ))}
        </p>
        <h4 className="sub">Limitations</h4>
        <p>{STAGE_LIMITS[stage.id]}</p>
        <h4 className="sub">Live from the backend</h4>
        {rows ? (
          <dl className="kv-grid">
            {rows.map(([label, value]) => (
              <div className="kv" key={label}>
                <dt>{label}</dt>
                <dd className="mono">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="empty">
            {stage.live
              ? connection === 'closed'
                ? 'Backend offline: live data is unavailable. Start the backend to see real values here.'
                : 'Connecting to live telemetry...'
              : 'This stage has no separate live metric.'}
          </p>
        )}
      </section>
    </div>
  );
}
