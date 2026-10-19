import { useEffect, useId, useRef, useState } from 'react';

/**
 * Accessible tooltip for technical terms. Opens on hover, keyboard focus or tap;
 * Escape or a second tap closes it. The explanation is linked via aria-describedby.
 */
export function Term({ children, tip }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', onDown);
    };
  }, [open]);

  return (
    <span className={`term${open ? ' open' : ''}`} ref={ref}>
      <button
        type="button"
        className="term-btn"
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {children}
      </button>
      <span role="tooltip" id={id} className="term-tip">
        {tip}
      </span>
    </span>
  );
}
