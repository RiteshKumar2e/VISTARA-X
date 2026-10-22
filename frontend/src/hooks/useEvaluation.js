import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';

/** Stored results of `python -m app.evaluation`, fetched from GET /evaluation. */
export function useEvaluation(online) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(() => {
    setLoading(true);
    return api
      .evaluation()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (online) reload();
  }, [online, reload]);

  return { data, error, loading, reload };
}
