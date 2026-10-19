import { STATUS } from '../content/deck';

/** Implementation-status label. Text is always present, so status never relies on colour. */
export function StatusTag({ status }) {
  const s = STATUS[status] || { label: status, tone: 'neutral' };
  return (
    <span className={`tag tag-${s.tone}`} data-impl={status}>
      <span className="tag-mark" aria-hidden="true" />
      {s.label}
    </span>
  );
}
