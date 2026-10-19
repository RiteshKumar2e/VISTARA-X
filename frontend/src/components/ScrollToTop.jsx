import { useEffect } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

/** Scroll to the top on forward navigation; keep the browser's position on back/forward. */
export function ScrollToTop() {
  const { pathname } = useLocation();
  const navType = useNavigationType();
  useEffect(() => {
    if (navType !== 'POP') window.scrollTo(0, 0);
  }, [pathname, navType]);
  return null;
}
