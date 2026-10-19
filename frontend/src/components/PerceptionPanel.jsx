import { useEffect, useState } from 'react';
import { Camera, ScanEye } from 'lucide-react';
import { api } from '../services/api';
import { Badge } from './StatusBadge';

const FRAME_EVERY = 2; // show every 2nd perception frame to limit image requests

function PerceptionSettings({ p, command, online }) {
  const [rate, setRate] = useState(p.rate_hz);
  const [conf, setConf] = useState(p.confidence_threshold);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) {
      setRate(p.rate_hz);
      setConf(p.confidence_threshold);
    }
  }, [p.rate_hz, p.confidence_threshold, dirty]);

  const disabled = !online || !!command.pending;
  const apply = async (event) => {
    event.preventDefault();
    const ok = await command.run(
      'perception',
      () => api.configurePerception({ rate_hz: rate, confidence: conf }),
      () => 'Perception settings applied',
    );
    if (ok) setDirty(false);
  };

  return (
    <form className="perception-settings" onSubmit={apply}>
      <label className="check">
        <input
          type="checkbox"
          checked={p.enabled}
          disabled={disabled}
          onChange={(e) =>
            command.run(
              'perception',
              () => api.configurePerception({ enabled: e.target.checked }),
              () => (e.target.checked ? 'Perception enabled' : 'Perception paused'),
            )
          }
        />
        Process camera frames
      </label>
      <div className="field">
        <label htmlFor="perception-rate">
          Frame rate <span className="mono">{Number(rate).toFixed(1)} Hz</span>
        </label>
        <input
          id="perception-rate"
          type="range"
          min="0.5"
          max="10"
          step="0.5"
          value={rate}
          onChange={(e) => {
            setRate(Number(e.target.value));
            setDirty(true);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="perception-conf">
          YOLOv8 confidence threshold <span className="mono">{Number(conf).toFixed(2)}</span>
        </label>
        <input
          id="perception-conf"
          type="range"
          min="0.05"
          max="0.95"
          step="0.05"
          value={conf}
          onChange={(e) => {
            setConf(Number(e.target.value));
            setDirty(true);
          }}
        />
      </div>
      <button type="submit" className="btn" disabled={disabled || !dirty}>
        Apply perception settings
      </button>
    </form>
  );
}

export function PerceptionPanel({ telemetry, command, online }) {
  const p = telemetry?.perception;
  const [frameSeq, setFrameSeq] = useState(null);
  const [frameError, setFrameError] = useState(false);

  useEffect(() => {
    if (!p?.frame_seq) return;
    if (frameSeq === null || p.frame_seq - frameSeq >= FRAME_EVERY || p.frame_seq < frameSeq) {
      setFrameSeq(p.frame_seq);
    }
  }, [p?.frame_seq, frameSeq]);

  if (!p) {
    return (
      <section className="panel" aria-labelledby="perception-title">
        <div className="panel-head">
          <h2 id="perception-title">Perception</h2>
        </div>
        <p className="empty">Waiting for the perception pipeline.</p>
      </section>
    );
  }

  const isYolo = p.mode === 'yolov8';
  const [fw, fh] = p.frame_size || [320, 180];
  const scene = p.scene || {};
  const rendererLabel = p.renderer === 'pybullet' ? 'PyBullet render' : 'ray-cast render';

  return (
    <section className="panel" aria-labelledby="perception-title">
      <div className="panel-head">
        <h2 id="perception-title">
          <ScanEye size={18} aria-hidden="true" className="icon-inline" />
          Perception
        </h2>
        <Badge tone={isYolo ? 'accent' : 'warning'}>{p.source_label}</Badge>
      </div>

      <div className="field">
        <label htmlFor="detector">Detector</label>
        <select
          id="detector"
          value={p.mode}
          disabled={!online || !!command.pending}
          onChange={(e) => command.run('detector', () => api.setDetector(e.target.value), () => 'Detector switched')}
        >
          <option value="simulated">Simulated detector (ground truth)</option>
          <option value="yolov8" disabled={!p.yolo_available}>
            YOLOv8 inference{p.yolo_available ? '' : ' (unavailable)'}
          </option>
        </select>
      </div>
      <p className="hint">
        {isYolo
          ? 'Real YOLOv8 (COCO) inference on the synthetic camera frame. The frame is a simple render, so the model may find few or no objects; results are shown unedited.'
          : `Boxes come from projecting known simulation geometry into the camera. They are not model predictions and have no confidence score.${
              p.yolo_available ? '' : ` YOLOv8 is unavailable: ${p.yolo_status}.`
            }`}
      </p>

      <figure className="camera">
        <div className="camera-frame" style={{ aspectRatio: `${fw} / ${fh}` }}>
          {p.enabled && frameSeq && !frameError ? (
            <img
              src={api.frameUrl(frameSeq)}
              width={fw}
              height={fh}
              alt={`Simulated forward camera view (${rendererLabel})`}
              onError={() => setFrameError(true)}
              onLoad={() => setFrameError(false)}
            />
          ) : (
            <span className="camera-empty">
              <Camera size={16} aria-hidden="true" />
              {!p.enabled ? 'Frame processing is paused' : frameError ? 'Camera frame unavailable' : 'Waiting for camera frame'}
            </span>
          )}
          {p.enabled && (
            <svg viewBox={`0 0 ${fw} ${fh}`} className="camera-boxes" aria-hidden="true">
              {p.detections.map((d, i) => {
                const [x1, y1, x2, y2] = d.bbox;
                return (
                  <g key={`${d.label}-${i}`}>
                    <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} />
                    <text x={x1 + 2} y={Math.max(y1 - 2, 8)}>
                      {d.label}
                      {d.confidence !== null ? ` ${(d.confidence * 100).toFixed(0)}%` : ''}
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
        <figcaption className="muted small">
          Simulated forward camera ({rendererLabel}, 70&deg; field of view), not real imagery.{' '}
          {p.processing_ms !== null && <span className="mono">Detector time {p.processing_ms} ms.</span>}
          {p.stale && <strong className="stale-note"> Results are stale.</strong>}
        </figcaption>
      </figure>

      {p.last_error && <p className="feedback-msg feedback-error">{p.last_error}</p>}
      {p.renderer_note && <p className="hint">{p.renderer_note}</p>}

      <h3 className="sub">Detections ({p.detections.length})</h3>
      {p.detections.length ? (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Class</th>
                <th scope="col">Confidence</th>
                <th scope="col">Range</th>
                <th scope="col">Bearing</th>
              </tr>
            </thead>
            <tbody>
              {p.detections.map((d, i) => (
                <tr key={`${d.label}-${i}`}>
                  <td>
                    {d.label}
                    {d.object_id ? <span className="muted"> ({d.object_id})</span> : null}
                  </td>
                  <td className="mono">{d.confidence !== null ? d.confidence.toFixed(2) : 'n/a (ground truth)'}</td>
                  <td className="mono">{d.distance !== null ? `${d.distance.toFixed(1)} m` : '—'}</td>
                  <td className="mono">{d.bearing_deg.toFixed(0)}&deg;</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty">
          {!p.enabled
            ? 'Frame processing is paused.'
            : isYolo
              ? 'YOLOv8 found no objects in the current frame.'
              : 'No objects in the camera view.'}
        </p>
      )}

      <h3 className="sub">Scene understanding</h3>
      <dl className="kv-grid">
        <div className="kv">
          <dt>Navigation-relevant</dt>
          <dd className="mono">
            {scene.relevant_count ?? 0} relevant, {scene.ignored_count ?? 0} ignored
          </dd>
        </div>
        <div className="kv">
          <dt>Nearest obstacle</dt>
          <dd className="mono">
            {scene.nearest ? `${scene.nearest.label}, ${scene.nearest.distance.toFixed(1)} m` : 'none in view'}
          </dd>
        </div>
        <div className="kv">
          <dt>Person ahead (&lt; 2.5 m)</dt>
          <dd className="mono">{scene.person_ahead ? 'yes: speed limited to 50%' : 'no'}</dd>
        </div>
        <div className="kv">
          <dt>Map observed by camera</dt>
          <dd className="mono">{Math.round((p.explored ?? 0) * 100)}%</dd>
        </div>
      </dl>

      <h3 className="sub">Tracked obstacles ({p.tracks.length})</h3>
      {p.tracks.length ? (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Track</th>
                <th scope="col">Position</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {p.tracks.map((t) => (
                <tr key={t.id}>
                  <td>
                    #{t.id} {t.label}
                  </td>
                  <td className="mono">
                    {t.x.toFixed(1)}, {t.y.toFixed(1)}
                  </td>
                  <td>{t.stale ? 'stale' : t.confirmed ? 'confirmed' : 'tentative'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty">No camera-derived tracks. Tracks expire 3 s after their last observation.</p>
      )}
      <p className="hint">Tracks are estimated from detections and shown for evaluation; collision avoidance uses simulator geometry.</p>

      <h3 className="sub">Frame processing</h3>
      <PerceptionSettings p={p} command={command} online={online} />
    </section>
  );
}
