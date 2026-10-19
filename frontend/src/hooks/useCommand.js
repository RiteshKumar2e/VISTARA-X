import { useCallback, useRef, useState } from 'react';

/**
 * Runs backend commands and tracks which one is pending plus the last outcome,
 * so every control can show loading, success and error feedback.
 */
export function useCommand() {
  const [pending, setPending] = useState(null);
  const [feedback, setFeedback] = useState(null); // { kind: 'success'|'error', text }
  const timer = useRef();

  const run = useCallback(async (name, fn, successText) => {
    setPending(name);
    clearTimeout(timer.current);
    try {
      const result = await fn();
      if (successText) setFeedback({ kind: 'success', text: successText(result) });
      return result;
    } catch (error) {
      setFeedback({ kind: 'error', text: error.message, details: error.details });
      return null;
    } finally {
      setPending(null);
      timer.current = setTimeout(() => setFeedback(null), 6000);
    }
  }, []);

  return { pending, feedback, run, clearFeedback: () => setFeedback(null) };
}
