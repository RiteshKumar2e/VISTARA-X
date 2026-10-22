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

// Optional access key (only needed when the backend has VISTARA_OPERATOR_KEY / VISTARA_ADMIN_KEY set).
// Kept in this browser only; never put a key in VITE_* variables.
export function getAccessKey() {
  try {
    return window.localStorage.getItem('vistara.apiKey') || '';
  } catch {
    return '';
  }
}
export function setAccessKey(key) {
  try {
    if (key) window.localStorage.setItem('vistara.apiKey', key);
    else window.localStorage.removeItem('vistara.apiKey');
  } catch {
    /* not remembered */
  }
}
client.interceptors.request.use((cfg) => {
  const key = getAccessKey();
  if (key) cfg.headers['X-API-Key'] = key;
  return cfg;
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

async function request(method, url, data, extra = {}) {
  try {
    const res = await client.request({ method, url, data, ...extra });
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
  // Always succeeds: halts the robot whether or not a mission is running.
  emergencyStop: () => request('post', '/navigation/estop'),
  reset: (scenario) => request('post', '/simulation/reset', { scenario }),
  configure: (params) => request('post', '/simulation/config', params),
  addObstacle: (x, y, opts = {}) => request('post', '/obstacles', { x, y, ...opts }),
  injectObstacle: () => request('post', '/obstacles/inject'),
  moveObstacle: (id, x, y) => request('post', `/obstacles/${encodeURIComponent(id)}/move`, { x, y }),
  clearObstacles: () => request('delete', '/obstacles'),
  setDetector: (mode) => request('post', '/perception/mode', { mode }),
  configurePerception: (params) => request('post', '/perception/config', params),
  sensors: () => request('get', '/sensors'),
  configureSensor: (sensor, body) => request('post', '/sensors/configure', { sensor, ...body }),
  models: () => request('get', '/models'),
  selectModels: (body) => request('post', '/models/select', body),
  removeObstacle: (id) => request('delete', `/simulation/obstacles/${encodeURIComponent(id)}`),
  frameUrl: (seq) => `${API_BASE_URL}/perception/frame?f=${seq}`,
  // Mapping and localisation
  mapping: (which = 'slam') => request('get', `/mapping?which=${which}`),
  explore: () => request('post', '/mapping/explore'),
  mappingControl: (body) => request('post', '/mapping/control', body),
  setPlannerMap: (source) => request('post', '/mapping/planner', { source }),
  saveMap: (name) => request('post', '/mapping/save', { name }),
  loadMap: (name) => request('post', '/mapping/load', { name }),
  importMap: (name, yaml, pgmBase64) => request('post', '/mapping/import', { name, yaml, pgm_base64: pgmBase64 }),
  exportUrl: (file) => `${API_BASE_URL}/mapping/export?file=${file}`,
  evaluation: () => request('get', '/evaluation'),
  // Delivery operations
  operations: () => request('get', '/operations'),
  createTask: (body) => request('post', '/operations/tasks', body),
  taskLoaded: (id, by) => request('post', `/operations/tasks/${id}/loaded`, { by }),
  taskDeliver: (id, pin) => request('post', `/operations/tasks/${id}/deliver`, { pin }),
  taskCancel: (id) => request('post', `/operations/tasks/${id}/cancel`),
  opsDock: () => request('post', '/operations/dock'),
  opsConfig: (body) => request('post', '/operations/config', body),
  opsReport: () => request('get', '/operations/report'),
  reportCsvUrl: () => `${API_BASE_URL}/operations/report.csv`,
  authStatus: () => request('get', '/auth/status'),
  audit: () => request('get', '/audit'),
  // Places, commands and speech
  places: () => request('get', '/places'),
  interpret: (text, source = 'text', { trusted = false, speech = null } = {}) =>
    request('post', '/commands/interpret', { text, source, trusted, ...(speech ? { speech } : {}) }),
  confirmCommand: (id) => request('post', `/commands/${id}/confirm`),
  cancelCommand: (id) => request('post', `/commands/${id}/cancel`),
  commands: () => request('get', '/commands'),
  speechStatus: () => request('get', '/speech/status'),
  speechLoad: () => request('post', '/speech/load', undefined, { timeout: 120000 }),
  // Whisper on a laptop CPU takes seconds per clip (longer on first use while the model loads).
  transcribe: (blob, language) =>
    request('post', `/speech/transcribe${language ? `?language=${language}` : ''}`, blob, {
      headers: { 'Content-Type': blob.type || 'audio/webm' },
      timeout: 120000,
    }),
};
