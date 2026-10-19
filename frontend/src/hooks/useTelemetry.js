import { useEffect, useRef, useState } from 'react';
import { TELEMETRY_WS_URL } from '../services/api';
import { TELEMETRY_VERSION } from '../types/telemetry';

const STALE_AFTER_MS = 3000;
const MAX_BACKOFF_MS = 5000;
const PING_MS = 15000;

/**
 * Live telemetry over WebSocket with automatic reconnect (exponential backoff)
 * and stale-stream detection. Messages older than the last seen `seq` are dropped.
 *
 * connection: 'connecting' | 'open' | 'stale' | 'closed'
 * versionMismatch: true when the backend speaks a different telemetry version.
 */
export function useTelemetry() {
  const [telemetry, setTelemetry] = useState(null);
  const [connection, setConnection] = useState('connecting');
  const [lastMessageAt, setLastMessageAt] = useState(null);
  const [versionMismatch, setVersionMismatch] = useState(false);
  const lastSeq = useRef(-1);
  const lastAt = useRef(0);

  useEffect(() => {
    let ws;
    let retry = 0;
    let reconnectTimer;
    let pingTimer;
    let disposed = false;

    const connect = () => {
      setConnection((c) => (c === 'open' ? c : 'connecting'));
      ws = new WebSocket(TELEMETRY_WS_URL);
      ws.onopen = () => {
        retry = 0;
        lastSeq.current = -1; // the server may have restarted
        clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
        }, PING_MS);
      };
      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type === 'error') {
          console.warn('Telemetry server error:', msg.message);
          return;
        }
        if (msg.type !== 'telemetry' || msg.seq <= lastSeq.current) return;
        setVersionMismatch(msg.version !== TELEMETRY_VERSION);
        lastSeq.current = msg.seq;
        lastAt.current = Date.now();
        setTelemetry(msg);
        setLastMessageAt(lastAt.current);
        setConnection('open');
      };
      ws.onclose = () => {
        clearInterval(pingTimer);
        if (disposed) return;
        setConnection('closed');
        const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** retry);
        retry += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    const staleTimer = setInterval(() => {
      if (lastAt.current && Date.now() - lastAt.current > STALE_AFTER_MS) {
        setConnection((c) => (c === 'open' ? 'stale' : c));
      }
    }, 1000);

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      clearInterval(staleTimer);
      clearInterval(pingTimer);
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        // Closing a socket that is still connecting logs a browser warning (common with
        // React StrictMode's double mount in development); close it once it opens instead.
        if (ws.readyState === WebSocket.CONNECTING) ws.onopen = () => ws.close();
        else ws.close();
      }
    };
  }, []);

  return { telemetry, connection, lastMessageAt, versionMismatch };
}
