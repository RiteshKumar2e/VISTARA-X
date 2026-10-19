import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { SpinnerIcon } from './components/Icons';
import Overview from './pages/Overview';

// The console and secondary pages are split so each route loads only what it needs.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Architecture = lazy(() => import('./pages/Architecture'));
const Technology = lazy(() => import('./pages/Technology'));
const Roadmap = lazy(() => import('./pages/Roadmap'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Terms = lazy(() => import('./pages/Terms'));
const NotFound = lazy(() => import('./pages/NotFound'));

function PageLoading() {
  return (
    <div className="page-loading" role="status">
      <SpinnerIcon size={18} />
      Loading...
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        {[
          ['mission', Dashboard],
          ['architecture', Architecture],
          ['technology', Technology],
          ['roadmap', Roadmap],
          ['privacy', Privacy],
          ['terms', Terms],
          ['*', NotFound],
        ].map(([path, Page]) => (
          <Route
            key={path}
            path={path}
            element={
              <Suspense fallback={<PageLoading />}>
                <Page />
              </Suspense>
            }
          />
        ))}
      </Route>
    </Routes>
  );
}
