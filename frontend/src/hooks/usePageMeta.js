import { useEffect } from 'react';

function setMeta(name, content) {
  let el = document.querySelector(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('name', name);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
  return el;
}

/** Unique title + description per route; optional noindex (used by the 404 page). */
export function usePageMeta(title, description, { noindex = false } = {}) {
  useEffect(() => {
    document.title = title;
    if (description) setMeta('description', description);
    const robots = noindex ? setMeta('robots', 'noindex') : null;
    return () => robots?.remove();
  }, [title, description, noindex]);
}
