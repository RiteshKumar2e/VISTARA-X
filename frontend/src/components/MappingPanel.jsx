import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { MapIcon, SpinnerIcon } from './Icons';
import { Term } from './Term';

const POLL_MS = 1000;
const CELL = { u: '#c9cdd2', f: '#f7f6f2', o: '#2f3439' };
const QUALITY = {
  good: ['ok', 'Good'],
  fair: ['warn', 'Fair'],
  poor: ['bad', 'Poor'],
  initialising: ['warn', 'Initialising'],
  dead_reckoning: ['bad', 'Odometry only (drifting)'],
  lost: ['bad', 'Lost'],
};
const STATE = { mapping: 'Mapping', paused: 'Paused (map frozen)', no_lidar: 'No LiDAR input: map not updating' };
const PLANNER = {
  simulator: 'Simulator geometry (ground truth)',
  slam: 'Live SLAM map',
  imported: 'Imported / saved map',
};

function MapCanvas({ data }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !data?.cells?.length) return;
    const px = 3;
    const rows = data.rows;
    const cols = data.cols;
    canvas.width = cols * px;
    canvas.height = rows * px;
    const ctx = canvas.getContext('2d');
    for (let r = 0; r < rows; r += 1) {
      const row = data.cells[r];
      let c = 0;
      while (c < cols) {
        // Draw runs of equal cells in one rectangle.
        const ch = row[c];
        let e = c + 1;
        while (e < cols && row[e] === ch) e += 1;
        ctx.fillStyle = CELL[ch] || '#fff';
        ctx.fillRect(c * px, (rows - 1 - r) * px, (e - c) * px, px);
        c = e;
      }
    }
    const [ox, oy] = data.origin;
    const X = (x) => ((x - ox) / data.resolution) * px;
    const Y = (y) => canvas.height - ((y - oy) / data.resolution) * px;
    const line = (pts, color, width, dash = []) => {
      if (!pts || pts.length < 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.setLineDash(dash);
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.stroke();
      ctx.setLineDash([]);
    };
    line(data.path, '#2fb8ab', 2, [6, 4]);
    line(data.truth_trajectory, '#8a8f96', 2, [3, 3]);
    line(data.trajectory, '#0f6e6a', 2.5);
    if (data.scan) {
      ctx.fillStyle = '#e0782f';
      for (const [x, y] of data.scan) ctx.fillRect(X(x) - 1.5, Y(y) - 1.5, 3, 3);
    }
    if (data.target) {
      ctx.strokeStyle = '#b07d00';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(X(data.target.x), Y(data.target.y), 6, 0, Math.PI * 2);
      ctx.stroke();
    }
    const pose = (p, fill, stroke) => {
      if (!p) return;
      const a = (-p.heading_deg * Math.PI) / 180;
      const x = X(p.x);
      const y = Y(p.y);
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(a);
      ctx.beginPath();
      ctx.moveTo(10, 0);
      ctx.lineTo(-6, 6);
      ctx.lineTo(-6, -6);
      ctx.closePath();
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      ctx.restore();
    };
    if (data.kind === 'slam') {
      pose(data.robot_truth, null, '#1b1d1f');
      pose(data.status?.estimate, '#0f6e6a', '#ffffff');
    } else {
      pose(data.robot_truth, '#1b1d1f', '#ffffff');
    }
  }, [data]);
  return (
    <canvas
      ref={ref}
      className="map-canvas"
      role="img"
      aria-label={
        data
          ? `${data.kind === 'slam' ? 'SLAM' : 'Imported'} occupancy map, ${data.cols} by ${data.rows} cells of ${data.resolution} m; ${Math.round(
              data.stats.known_fraction * 100,
            )}% known.`
          : 'Occupancy map loading'
      }
    />
  );
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function MappingPanel({ telemetry, online, command }) {
  const [view, setView] = useState('slam');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState('warehouse_map');
  const [importName, setImportName] = useState('imported_map');
  const yamlRef = useRef(null);
  const pgmRef = useRef(null);
  const status = telemetry?.mapping;
  const hasImported = !!status?.imported;
  const { run, pending } = command;
  const active = ['planning', 'navigating', 'replanning'].includes(telemetry?.mission?.status);

  useEffect(() => {
    if (!online) return undefined;
    let cancelled = false;
    const which = view === 'imported' && hasImported ? 'imported' : 'slam';
    const load = () =>
      api
        .mapping(which)
        .then((d) => {
          if (!cancelled) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => !cancelled && setError(e.message));
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [online, view, hasImported]);

  const doImport = async () => {
    const y = yamlRef.current?.files?.[0];
    const p = pgmRef.current?.files?.[0];
    if (!y || !p) {
      setError('Choose both the map .yaml file and its .pgm image.');
      return;
    }
    const [yamlText, pgmBuf] = await Promise.all([y.text(), p.arrayBuffer()]);
    const ok = await run('map-import', () => api.importMap(importName, yamlText, toBase64(pgmBuf)), (r) => `Imported map '${r.map.name}' (${r.map.width_px} x ${r.map.height_px} px at ${r.map.resolution} m)`);
    if (ok) setView('imported');
  };

  const [qTone, qLabel] = QUALITY[status?.localization?.quality] || ['warn', status?.localization?.quality ?? '...'];
  const disabled = !online || !!pending;

  return (
    <section className="panel mapping" id="mapping" aria-labelledby="mapping-title">
      <div className="panel-head">
        <h2 id="mapping-title">Mapping and localisation</h2>
        <span className="tag tag-accent">
          <span className="tag-mark" aria-hidden="true" />
          Simulation-generated
        </span>
      </div>
      <p className="hint hint-top">
        <MapIcon size={14} /> Live map built from the <strong>simulated</strong> 2D LiDAR and wheel odometry by the backend&rsquo;s
        scan-matching SLAM. It is not a map of a real building.{' '}
        <Term tip="Live SLAM on real sensors with ROS 2 (SLAM Toolbox + Nav2) needs a ROS 2 installation and a robot or recorded sensor data. Neither is present here, so that mode is not offered. See the README mapping guide for the setup.">
          ROS 2 live SLAM: not available here
        </Term>
      </p>

      <div className="tool-group map-view-toggle" role="group" aria-label="Map shown">
        <button type="button" className={`tool-btn${view === 'slam' ? ' on' : ''}`} aria-pressed={view === 'slam'} onClick={() => setView('slam')}>
          Live SLAM map
        </button>
        <button
          type="button"
          className={`tool-btn${view === 'imported' ? ' on' : ''}`}
          aria-pressed={view === 'imported'}
          disabled={!hasImported}
          onClick={() => setView('imported')}
        >
          Imported map{hasImported ? `: ${status.imported}` : ' (none)'}
        </button>
      </div>

      {error && <p className="feedback-msg feedback-error">Map unavailable: {error}</p>}
      {data ? (
        <figure className="grid-figure">
          <MapCanvas data={data} />
          <figcaption>
            <ul className="legend" aria-label="Map legend">
              <li><span className="sw" style={{ background: CELL.f, border: '1px solid #ccc' }} aria-hidden="true" />Free</li>
              <li><span className="sw" style={{ background: CELL.o }} aria-hidden="true" />Occupied</li>
              <li><span className="sw" style={{ background: CELL.u }} aria-hidden="true" />Unknown (not yet scanned)</li>
              {data.kind === 'slam' && (
                <>
                  <li><span className="sw" style={{ background: '#0f6e6a' }} aria-hidden="true" />Estimated pose and trajectory (SLAM)</li>
                  <li><span className="sw sw-dashed" aria-hidden="true" />True trajectory (simulator, for evaluation)</li>
                  <li><span className="sw" style={{ background: '#e0782f' }} aria-hidden="true" />Latest LiDAR scan</li>
                </>
              )}
              <li><span className="sw sw-path" aria-hidden="true" />Planned route</li>
            </ul>
          </figcaption>
        </figure>
      ) : (
        !error && (
          <p className="empty">
            <SpinnerIcon size={14} /> {online ? 'Loading the map...' : 'Backend offline.'}
          </p>
        )
      )}

      {status && (
        <dl className="kv-grid map-kv">
          <div className="kv">
            <dt>Mapping</dt>
            <dd>{status.exploring ? `Exploring (frontier ${status.explore_goals})` : STATE[status.state] || status.state}</dd>
          </div>
          <div className="kv">
            <dt>
              <Term tip="How well the latest LiDAR scan fits the map built so far (0-1, from the scan matcher). Computed without ground truth.">Localisation</Term>
            </dt>
            <dd>
              <span className={`sys-inline sys-${qTone === 'ok' ? 'ok' : qTone === 'bad' ? 'down' : 'degraded'}`}>{qLabel}</span>
              {status.localization.match_score != null && <span className="mono small"> score {status.localization.match_score.toFixed(2)}</span>}
            </dd>
          </div>
          <div className="kv">
            <dt>
              <Term tip="Distance between the SLAM pose estimate and the simulator's true pose. Only measurable in simulation; a real robot cannot know this.">Pose error (vs ground truth)</Term>
            </dt>
            <dd className="mono">
              {(status.pose_error_m * 100).toFixed(1)} cm, {status.heading_error_deg.toFixed(1)}° (max {(status.max_pose_error_m * 100).toFixed(0)} cm)
            </dd>
          </div>
          <div className="kv">
            <dt>Odometry-only drift</dt>
            <dd className="mono">{status.odometry_drift_m != null ? `${(status.odometry_drift_m * 100).toFixed(1)} cm` : 'odometry off'}</dd>
          </div>
          <div className="kv">
            <dt>Area known</dt>
            <dd className="mono">
              {(status.known_fraction * 100).toFixed(0)}% · {status.scans} scans
            </dd>
          </div>
          <div className="kv">
            <dt>Frame</dt>
            <dd className="small">
              {data ? `${data.resolution} m/cell, origin (${data.origin[0]}, ${data.origin[1]}), ${data.cols}×${data.rows}` : '...'}
            </dd>
          </div>
        </dl>
      )}

      <div className="button-row">
        <button type="button" className="btn btn-primary" disabled={disabled || active} onClick={() => run('explore', api.explore, () => 'Exploration started: the robot maps the area by itself')}>
          Explore and map automatically
        </button>
        <button
          type="button"
          className="btn"
          disabled={disabled}
          onClick={() => run('map-pause', () => api.mappingControl({ enabled: status?.state === 'paused' }), () => (status?.state === 'paused' ? 'Mapping resumed' : 'Mapping paused'))}
        >
          {status?.state === 'paused' ? 'Resume mapping' : 'Pause mapping'}
        </button>
        <button type="button" className="btn" disabled={disabled} onClick={() => run('map-clear', () => api.mappingControl({ clear: true }), () => 'SLAM map cleared')}>
          Clear map
        </button>
      </div>

      <div className="field">
        <label htmlFor="planner-map">
          <Term tip="Simulator: plan on the true obstacle geometry. Live SLAM: plan on what the LiDAR has mapped so far (unknown space is allowed and discovered while driving). Imported: plan on a loaded map; unknown space is not driveable and live LiDAR returns add obstacles that are not in the map.">
            Planner uses
          </Term>
        </label>
        <select
          id="planner-map"
          value={status?.planner_map ?? 'simulator'}
          disabled={disabled || active}
          onChange={(e) => run('planner-map', () => api.setPlannerMap(e.target.value), () => `Planner now uses: ${PLANNER[e.target.value]}`)}
        >
          {Object.entries(PLANNER).map(([k, v]) => (
            <option key={k} value={k} disabled={k === 'imported' && !hasImported}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <details className="explain">
        <summary>Save, load, export and import maps (ROS map_server format)</summary>
        <form
          className="map-form"
          onSubmit={(e) => {
            e.preventDefault();
            run('map-save', () => api.saveMap(name), (r) => `Map saved as '${r.map.name}'`);
          }}
        >
          <div className="field">
            <label htmlFor="map-name">Save the SLAM map as</label>
            <div className="cmd-input-row">
              <input id="map-name" value={name} maxLength={40} pattern="[A-Za-z0-9_\-]+" onChange={(e) => setName(e.target.value)} />
              <button type="submit" className="btn" disabled={disabled}>
                Save
              </button>
            </div>
          </div>
        </form>
        {data?.saved_maps?.length > 0 && (
          <ul className="map-list" aria-label="Saved maps">
            {data.saved_maps.map((m) => (
              <li key={m.name}>
                <span className="mono">{m.name}</span> <span className="muted small">{m.modified.replace('T', ' ')}</span>{' '}
                <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => run('map-load', () => api.loadMap(m.name), () => `Loaded map '${m.name}'`).then((ok) => ok && setView('imported'))}>
                  Load
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="small">
          Download the live map:{' '}
          <a href={api.exportUrl('pgm')} download="map.pgm">
            map.pgm
          </a>{' '}
          ·{' '}
          <a href={api.exportUrl('yaml')} download="map.yaml">
            map.yaml
          </a>{' '}
          (opens in ROS map_server / Nav2).
        </p>
        <div className="map-import">
          <div className="field">
            <label htmlFor="imp-yaml">Map YAML</label>
            <input id="imp-yaml" type="file" accept=".yaml,.yml" ref={yamlRef} />
          </div>
          <div className="field">
            <label htmlFor="imp-pgm">Map image (PGM)</label>
            <input id="imp-pgm" type="file" accept=".pgm" ref={pgmRef} />
          </div>
          <div className="field">
            <label htmlFor="imp-name">Name</label>
            <input id="imp-name" value={importName} maxLength={40} onChange={(e) => setImportName(e.target.value)} />
          </div>
          <button type="button" className="btn" disabled={disabled} onClick={doImport}>
            Import map
          </button>
        </div>
        <p className="muted small">
          Imported maps are interpreted with their own resolution, origin and thresholds (trinary: occupied, free, unknown).
          A floor-plan picture is not a metric map: convert it to an occupancy grid with the correct scale first.
        </p>
      </details>
    </section>
  );
}
