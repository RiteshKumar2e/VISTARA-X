import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';

const NAV = [
  { to: '/', label: 'Mission console', end: true },
  { to: '/about', label: 'How it works' },
];

function Header() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link to="/" className="brand" aria-label="VISTARA-X home">
          <img src="/favicon.svg" width="28" height="28" alt="" />
          <span className="brand-name">VISTARA-X</span>
          <span className="brand-tag">Vision-Based Autonomous Navigation</span>
        </Link>
        <button
          type="button"
          className="menu-toggle"
          aria-expanded={open}
          aria-controls="site-nav"
          onClick={() => setOpen((o) => !o)}
        >
          <span className="menu-icon" aria-hidden="true" />
          <span>{open ? 'Close' : 'Menu'}</span>
        </button>
        <nav id="site-nav" className={`site-nav${open ? ' open' : ''}`} aria-label="Main">
          <ul>
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <p>
          VISTARA-X by Team Hack01 for Hack in Hills &rsquo;26. Simulation prototype, not a certified safety system.
        </p>
        <nav aria-label="Footer">
          <ul>
            <li>
              <Link to="/about">How it works</Link>
            </li>
            <li>
              <Link to="/privacy">Privacy</Link>
            </li>
            <li>
              <Link to="/terms">Terms</Link>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}

export function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Header />
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <Footer />
    </>
  );
}
