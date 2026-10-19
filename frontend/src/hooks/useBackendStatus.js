import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';

const POLL_MS = 5000;

/** Polls /status. state: 'checking' | 'ok' | 'down'. */
export function useBackendStatus() {
  const [state, setState] = useState('checking');
  const [status, setStatus] = useState(null);

  const check = useCallback(async () => {
    try {
      setStatus(await api.status());
      setState('ok');
    } catch {
      setState('down');
    }
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(check, POLL_MS);
    return () => clearInterval(id);
  }, [check]);

  return { state, status, retry: check };
}
