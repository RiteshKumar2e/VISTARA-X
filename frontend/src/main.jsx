import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MotionConfig } from 'framer-motion';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ScrollToTop } from './components/ScrollToTop';
import './styles/tokens.css';
import './styles/app.css';
import './styles/pages.css';
import './styles/viewport.css';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* Animations honour the OS "reduce motion" setting. */}
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <ScrollToTop />
        <App />
      </BrowserRouter>
    </MotionConfig>
  </StrictMode>,
);
