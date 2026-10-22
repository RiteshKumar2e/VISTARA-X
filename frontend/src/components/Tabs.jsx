import { useRef } from 'react';

/**
 * Accessible tabs (WAI-ARIA tabs pattern, manual activation). Panels stay mounted and are
 * hidden when inactive, so their live state and polling continue across tab switches.
 */
export function Tabs({ id, label, tabs, value, onChange, className = '' }) {
  const refs = useRef({});
  const onKey = (e, index) => {
    const step = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: tabs.length - 1 - index }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    const next = tabs[(index + step + tabs.length) % tabs.length];
    onChange(next.id);
    refs.current[next.id]?.focus();
  };
  return (
    <div className={`tabs ${className}`}>
      <div className="tab-list" role="tablist" aria-label={label}>
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${t.id}`}
            aria-selected={value === t.id}
            aria-controls={`${id}-panel-${t.id}`}
            tabIndex={value === t.id ? 0 : -1}
            className={`tab${value === t.id ? ' on' : ''}`}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
            {t.badge != null && <span className="tab-badge">{t.badge}</span>}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`${id}-panel-${t.id}`}
          aria-labelledby={`${id}-tab-${t.id}`}
          hidden={value !== t.id}
          className="tab-panel"
        >
          {t.content}
        </div>
      ))}
    </div>
  );
}
