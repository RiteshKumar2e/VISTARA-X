import axios from 'axios';

// Public backend URL only. Never put secrets in VITE_* variables: they ship to the browser.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(
  /\/+$/,
  '',
);

// ws:// for http backends, wss:// for https backends.
export const TELEMETRY_WS_URL = `${API_BASE_URL.replace(/^http/, 'ws')}/ws/telemetry`;

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
});

/** Normalised error with a user-facing message and optional field details. */
export class ApiError extends Error {
  constructor(message, { code = 'error', status = 0, details = null } = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function normalise(error) {
  if (error.response) {
    const body = error.response.data?.error;
    return new ApiError(body?.message || `Request failed (${error.response.status})`, {
      code: body?.code || 'http_error',
      status: error.response.status,
      details: body?.details || null,
    });
  }
  if (error.code === 'ECONNABORTED') {
    return new ApiError('The backend took too long to respond.', { code: 'timeout' });
  }
  return new ApiError('Cannot reach the VISTARA-X backend. Check that it is running.', {
    code: 'network',
  });
}

async function request(method, url, data) {
  try {
    const res = await client.request({ method, url, data });
    return res.data;
  } catch (error) {
    throw normalise(error);
  }
}

export const api = {
  health: () => request('get', '/health'),
  status: () => request('get', '/status'),
  map: () => request('get', '/map'),
  scenarios: () => request('get', '/scenarios'),
  setTarget: (x, y) => request('post', '/target', { x, y }),
  navigate: (target) => request('post', '/navigate', target ? { target } : {}),
  pause: () => request('post', '/navigation/pause'),
  resume: () => request('post', '/navigation/resume'),
  stop: () => request('post', '/navigation/stop'),
  reset: (scenario) => request('post', '/simulation/reset', { scenario }),
  configure: (params) => request('post', '/simulation/config', params),
  addObstacle: (x, y, opts = {}) => request('post', '/obstacles', { x, y, ...opts }),
  injectObstacle: () => request('post', '/obstacles/inject'),
  moveObstacle: (id, x, y) => request('post', `/obstacles/${encodeURIComponent(id)}/move`, { x, y }),
  clearObstacles: () => request('delete', '/obstacles'),
  setDetector: (mode) => request('post', '/perception/mode', { mode }),
  configurePerception: (params) => request('post', '/perception/config', params),
  frameUrl: (seq) => `${API_BASE_URL}/perception/frame?f=${seq}`,
};
