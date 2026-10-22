import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { SceneAnimator } from '../simulation/renderer';
import { Sim3D } from '../simulation/scene3d';

const DRAG_THRESHOLD = 5;

/**
 * Three.js view of the backend simulation. Telemetry is interpolated by the same
 * SceneAnimator as the plan view; the render loop reads refs, so React does not
 * re-render per frame. Calls onError if WebGL cannot be initialised.
 */
const Viewport3D = forwardRef(function Viewport3D(
  { telemetry, world, onPick, onHover, layers, effects, rejected, selectedObstacle, camera, onError, label, lite, places, zones, scenario },
  ref,
) {
  const hostRef = useRef(null);
  const liteRef = useRef(lite);
  liteRef.current = lite;
  const simRef = useRef(null);
  const animRef = useRef(new SceneAnimator());
  const optsRef = useRef({});
  const downRef = useRef(null);
  const hoverAt = useRef(0);

  useImperativeHandle(ref, () => ({
    zoomIn: () => simRef.current?.zoom(0.8),
    zoomOut: () => simRef.current?.zoom(1.25),
    fit: () => simRef.current?.setView(simRef.current.mode),
    canFit: true,
    // Used by browser tests to click a known simulation coordinate.
    project: (x, y) => simRef.current?.project(x, y),
  }));

  useEffect(() => {
    let sim;
    try {
      sim = new Sim3D(hostRef.current, world);
    } catch (err) {
      console.warn('3D view unavailable, falling back to plan view:', err.message);
      onError?.(err);
      return undefined;
    }
    simRef.current = sim;
    sim.setQuality(!!liteRef.current);
    const host = hostRef.current;
    const resize = () => {
      const w = host.clientWidth;
      const h = Math.round(Math.min(Math.max(w * 0.62, 300), 680));
      sim.resize(w, h);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();

    // Plain wheel scrolls the page; Ctrl/Cmd + wheel (and trackpad pinch) zooms.
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) e.stopPropagation();
    };
    host.addEventListener('wheel', onWheel, { capture: true });

    let raf;
    let visible = true;
    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting));
    io.observe(host);
    // Cap at 30 fps (20 fps in demo mode): smooth enough, a fraction of the GPU cost.
    let last = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (!visible) return;
      const now = performance.now();
      if (now - last < 1000 / (liteRef.current ? 20 : 30)) return;
      last = now;
      const opts = optsRef.current;
      try {
        const anim = animRef.current;
        sim.update(anim.frame(now, opts.effects), { ...opts, anim }, now);
        // controls.update() reports camera movement (including damping); render on demand
        // when effects are off, every frame when they are on.
        const moved = sim.controls.update();
        if ((opts.effects && anim.animating(now)) || sim.dirty || moved) sim.render();
      } catch (err) {
        console.error('3D render failed', err);
      }
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      host.removeEventListener('wheel', onWheel, { capture: true });
      ro.disconnect();
      io.disconnect();
      sim.dispose();
      simRef.current = null;
    };
    // The scene is built once per world size.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [world]);

  useEffect(() => {
    if (telemetry) animRef.current.ingest(telemetry, performance.now());
  }, [telemetry]);

  useEffect(() => {
    optsRef.current = { layers, effects, rejected, selectedObstacle };
    if (simRef.current) simRef.current.dirty = true;
  }, [layers, effects, rejected, selectedObstacle]);

  useEffect(() => {
    simRef.current?.setView(camera);
  }, [camera]);

  useEffect(() => {
    simRef.current?.setQuality(!!lite);
  }, [lite]);

  useEffect(() => {
    if (scenario) simRef.current?.setTheme(scenario);
  }, [scenario, world]);

  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    sim.setPlaces(layers.places ? places : []);
    sim.setZones(layers.places ? zones : []);
  }, [places, zones, layers.places, world]);

  // Click (not drag) selects; orbit/pan drags are handled by OrbitControls.
  const onPointerDown = (e) => {
    downRef.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerUp = (e) => {
    const d = downRef.current;
    downRef.current = null;
    if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > DRAG_THRESHOLD || !simRef.current) return;
    onPick(simRef.current.pick(e.clientX, e.clientY));
  };
  const onPointerMove = (e) => {
    const now = performance.now();
    if (now - hoverAt.current < 60 || !simRef.current) return; // throttle raycasts
    hoverAt.current = now;
    onHover(simRef.current.pick(e.clientX, e.clientY).point);
  };

  const onKeyDown = (e) => {
    const sim = simRef.current;
    if (!sim) return;
    const actions = { '+': () => sim.zoom(0.8), '=': () => sim.zoom(0.8), '-': () => sim.zoom(1.25), 0: () => sim.setView(sim.mode) };
    if (actions[e.key]) {
      e.preventDefault();
      actions[e.key]();
    }
  };

  return (
    <div
      className="view-3d"
      ref={hostRef}
      role="img"
      tabIndex={0}
      aria-label={`${label} 3D view: drag to orbit, right-drag or two fingers to pan, scroll or pinch to zoom, zero resets.`}
      data-view="3d"
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerMove={onPointerMove}
      onPointerLeave={() => onHover(null)}
      onKeyDown={onKeyDown}
    />
  );
});

export default Viewport3D;
