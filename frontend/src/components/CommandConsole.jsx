import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { CheckIcon, MicIcon, SendIcon, SpinnerIcon, StopIcon, WarningIcon } from './Icons';

const LANG = { en: 'English', hi: 'Hindi (हिन्दी)', 'hi-Latn': 'Hinglish (romanised Hindi)' };
const STATUS = {
  executed: ['ok', 'Executed'],
  awaiting_confirmation: ['warn', 'Waiting for your confirmation'],
  needs_clarification: ['warn', 'Needs clarification'],
  rejected: ['bad', 'Not executed'],
  failed: ['bad', 'Failed'],
  cancelled: ['muted', 'Cancelled'],
};
const INTENT = {
  navigate: 'Go to a destination',
  return_home: 'Return to the starting point',
  stop: 'Stop',
  pause: 'Pause',
  resume: 'Resume',
  unknown: 'Not understood',
};
const EXAMPLES = [
  'Robot ko reception tak le jao',
  'Take the robot to the storage room',
  'Find a safe route to the exit',
  'रोबोट को चार्जिंग डॉक तक ले जाओ',
  'थोड़ा रुको',
  'Resume',
  'वापस जाओ',
  'Take the robot to the cafeteria',
];
const MAX_RECORD_MS = 8000;

const BrowserRecognition = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

function readFlag(key) {
  try {
    return window.localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}
function writeFlag(key, on) {
  try {
    window.localStorage.setItem(key, on ? '1' : '0');
  } catch {
    /* not remembered */
  }
}

/** Speaks a response when the user asked for spoken feedback. The same text is always on screen. */
function speak(text, lang) {
  if (!window.speechSynthesis) return 'Spoken feedback is not supported by this browser.';
  const want = lang === 'hi' ? 'hi' : 'en';
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(want));
  if (lang === 'hi' && !voice) return 'No Hindi voice is installed on this device; the response is shown as text only.';
  const u = new SpeechSynthesisUtterance(text);
  if (voice) u.voice = voice;
  u.lang = voice?.lang || (want === 'hi' ? 'hi-IN' : 'en-IN');
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
  return null;
}

function CommandCard({ rec, onConfirm, onCancel, busy, confirmRef }) {
  const [tone, label] = STATUS[rec.status] || ['muted', rec.status];
  const d = rec.intent.destination;
  const v = rec.validation;
  return (
    <article className={`cmd-card cmd-${tone}`} aria-label={`Command ${rec.id}`}>
      <header className="cmd-head">
        <span className={`cmd-status cmd-status-${tone}`}>
          {tone === 'ok' ? <CheckIcon size={14} /> : tone === 'bad' || tone === 'warn' ? <WarningIcon size={14} /> : null}
          {label}
        </span>
        <span className="muted small mono">
          #{rec.id} · {rec.time} · {rec.source === 'speech' ? 'Whisper speech' : rec.source === 'browser_speech' ? 'browser speech' : rec.source}
        </span>
      </header>
      <p className="cmd-transcript">
        <span className="sr-only">Transcript: </span>&ldquo;{rec.transcript}&rdquo;
      </p>
      <dl className="cmd-facts">
        <div>
          <dt>Language</dt>
          <dd>{LANG[rec.language] || rec.language}</dd>
        </div>
        <div>
          <dt>Intent</dt>
          <dd>{INTENT[rec.intent.type] || rec.intent.type}</dd>
        </div>
        {d && (
          <div>
            <dt>Destination</dt>
            <dd>
              {d.name ? `${d.name} (${d.name_hi})` : 'Coordinates'} <span className="mono small">x {d.x}, y {d.y}</span>
            </dd>
          </div>
        )}
        {Object.keys(rec.intent.constraints || {}).length > 0 && (
          <div>
            <dt>Constraints</dt>
            <dd>{Object.keys(rec.intent.constraints).join(', ')}</dd>
          </div>
        )}
        {v && (
          <div>
            <dt>Validation</dt>
            <dd>
              {!v.valid ? v.message : v.reachable ? `Route found, ${v.length} m (${v.planner_map} map)` : 'No collision-free route right now'}
            </dd>
          </div>
        )}
        {rec.speech && (
          <div>
            <dt>Recognition</dt>
            <dd className="small">
              {rec.speech.engine}
              {rec.speech.model ? ` ${rec.speech.model}` : ''}
              {rec.speech.language_probability != null ? `, language confidence ${Math.round(rec.speech.language_probability * 100)}%` : ''}
              {rec.speech.confidence != null ? `, confidence ${Math.round(rec.speech.confidence * 100)}%` : ''}
              {rec.speech.processing_ms != null ? `, ${(rec.speech.processing_ms / 1000).toFixed(1)} s` : ''}
            </dd>
          </div>
        )}
      </dl>
      {rec.response && (
        <p className="cmd-response" lang={rec.response.language === 'hi' ? 'hi' : 'en'}>
          <strong>Robot: </strong>
          {rec.response.text}
        </p>
      )}
      {rec.status === 'awaiting_confirmation' && (
        <div className="button-row">
          <button type="button" className="btn btn-primary" ref={confirmRef} disabled={busy} onClick={() => onConfirm(rec)}>
            <CheckIcon size={14} />
            Confirm and go
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => onCancel(rec)}>
            Cancel
          </button>
        </div>
      )}
    </article>
  );
}

export function CommandConsole({ telemetry, online, command }) {
  const [text, setText] = useState('');
  const [places, setPlaces] = useState([]);
  const [placeKey, setPlaceKey] = useState('');
  const [current, setCurrent] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [trusted, setTrusted] = useState(() => readFlag('vistara.trusted'));
  const [spoken, setSpoken] = useState(() => readFlag('vistara.spoken'));
  const [speechNote, setSpeechNote] = useState(null);
  const [engine, setEngine] = useState('whisper');
  const [langHint, setLangHint] = useState('');
  const [speech, setSpeech] = useState(null);
  const [rec, setRec] = useState(null); // { since, level } while recording
  const [phase, setPhase] = useState(null); // 'transcribing' | 'loading'
  const recorder = useRef(null);
  const resultRef = useRef(null);
  const confirmRef = useRef(null);
  const scenario = telemetry?.scenario;

  useEffect(() => {
    if (!online) return;
    api.places().then((r) => setPlaces(r.places)).catch(() => {});
    api.commands().then((r) => setHistory(r.commands)).catch(() => {});
    api.speechStatus().then(setSpeech).catch(() => {});
  }, [online, scenario]);

  const show = useCallback(
    (r) => {
      setCurrent(r);
      setHistory((h) => [...h.filter((x) => x.id !== r.id), r].slice(-50));
      if (spoken && r.response) setSpeechNote(speak(r.response.text, r.response.language));
    },
    [spoken],
  );

  // Bring a new result into view; a command waiting for confirmation gets keyboard focus
  // on its Confirm button, so Enter confirms it.
  useEffect(() => {
    if (!current) return;
    resultRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    if (current.status === 'awaiting_confirmation') confirmRef.current?.focus({ preventScroll: true });
  }, [current?.id, current?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (value, source = 'text', meta = null) => {
    const t = value.trim();
    if (!t) {
      setError('Type a command first, for example "Take the robot to the reception".');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      show(await api.interpret(t, source, { trusted, speech: meta }));
      if (source === 'text') setText('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      show(await fn());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Emergency stop: a direct API call, independent of speech, language or parsing.
  const emergencyStop = () =>
    command.run('stop', api.emergencyStop, (r) => r.message).then(() => setError(null));

  // ------------------------------------------------------------ microphone (Whisper)
  const startWhisper = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('This browser cannot record audio. Type the command instead.');
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setError(
        e.name === 'NotAllowedError'
          ? 'Microphone permission was denied. Allow it in the browser, or type the command.'
          : `No microphone available (${e.name}). Type the command instead.`,
      );
      return;
    }
    const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((m) => MediaRecorder.isTypeSupported?.(m));
    const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = ctx.createAnalyser();
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    const since = performance.now();
    let raf;
    const meter = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      setRec({ since, level: Math.min(1, Math.sqrt(sum / buf.length) * 4), elapsed: (performance.now() - since) / 1000 });
      raf = requestAnimationFrame(meter);
    };
    meter();
    const timer = setTimeout(() => mr.state === 'recording' && mr.stop(), MAX_RECORD_MS);
    mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    mr.onstop = async () => {
      clearTimeout(timer);
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      setRec(null);
      recorder.current = null;
      const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
      setPhase(speech?.loaded ? 'transcribing' : 'loading');
      try {
        const out = await api.transcribe(blob, langHint || undefined);
        setSpeech((s) => (s ? { ...s, loaded: true } : s));
        if (out.status === 'no_speech') {
          setError('No speech was recognised in the recording. Try again closer to the microphone, or type the command.');
          return;
        }
        if (out.status === 'unsupported_language') {
          setError(`Recognised language "${out.detected_language}" is not supported. Speak English or Hindi, or type the command.`);
          return;
        }
        const meta = {
          engine: 'faster-whisper',
          model: out.model,
          language: out.language,
          language_probability: out.language_probability,
          no_speech_prob: out.no_speech_prob,
          processing_ms: out.processing_ms,
        };
        await submit(out.text, 'speech', meta);
      } catch (e) {
        setError(`Speech recognition failed: ${e.message}`);
      } finally {
        setPhase(null);
      }
    };
    recorder.current = mr;
    mr.start();
  };

  // ------------------------------------------------------------ microphone (browser API)
  const startBrowser = () => {
    setError(null);
    const r = new BrowserRecognition();
    r.lang = langHint === 'hi' ? 'hi-IN' : 'en-IN';
    r.interimResults = false;
    r.maxAlternatives = 1;
    setRec({ since: performance.now(), level: null, elapsed: 0 });
    r.onresult = (e) => {
      const alt = e.results[0][0];
      submit(alt.transcript, 'browser_speech', {
        engine: 'browser speech recognition',
        language: r.lang,
        confidence: typeof alt.confidence === 'number' && alt.confidence > 0 ? Math.round(alt.confidence * 1000) / 1000 : null,
      });
    };
    r.onerror = (e) =>
      setError(e.error === 'not-allowed' ? 'Microphone permission was denied.' : e.error === 'no-speech' ? 'No speech was recognised.' : `Browser speech recognition failed (${e.error}).`);
    r.onend = () => {
      setRec(null);
      recorder.current = null;
    };
    recorder.current = r;
    r.start();
  };

  const toggleMic = () => {
    if (recorder.current) {
      recorder.current.stop();
      return;
    }
    if (engine === 'browser') startBrowser();
    else startWhisper();
  };

  const recording = !!rec;
  const status = telemetry?.mission?.status;

  return (
    <section className="panel commands" id="commands" aria-labelledby="commands-title">
      <div className="panel-head">
        <h2 id="commands-title">Voice and text commands</h2>
        <span className="muted small">English · हिन्दी · Hinglish</span>
      </div>

      <div className="estop-row">
        <button type="button" className="btn btn-danger btn-estop" onClick={emergencyStop} disabled={!online}>
          <StopIcon size={18} />
          Emergency stop
        </button>
        <p className="muted small">
          Direct stop: does not depend on speech recognition, language or the command parser. Robot status:{' '}
          <strong>{status ? status.replace('_', ' ') : 'unknown'}</strong>
        </p>
      </div>

      <form
        className="cmd-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        <label htmlFor="cmd-text">Type a command</label>
        <div className="cmd-input-row">
          <input
            id="cmd-text"
            type="text"
            value={text}
            maxLength={300}
            autoComplete="off"
            placeholder="e.g. Robot ko reception tak le jao"
            onChange={(e) => setText(e.target.value)}
            disabled={!online}
          />
          <button type="submit" className="btn btn-primary" disabled={!online || busy}>
            {busy ? <SpinnerIcon size={14} /> : <SendIcon size={14} />}
            Send
          </button>
        </div>
        <div className="cmd-examples" aria-label="Example commands">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip-btn" disabled={!online || busy} onClick={() => submit(ex)} lang={/[ऀ-ॿ]/.test(ex) ? 'hi' : 'en'}>
              {ex}
            </button>
          ))}
        </div>
      </form>

      {/* The result of the latest command sits directly under the input, so the Confirm
          button is never off screen. */}
      <div className="cmd-result" ref={resultRef}>
        {error && (
          <p className="feedback-msg feedback-error" role="alert">
            <WarningIcon size={14} /> {error}
          </p>
        )}
        {speechNote && <p className="hint">{speechNote}</p>}
        <div aria-live="polite">
          {current && (
            <CommandCard
              rec={current}
              busy={busy}
              confirmRef={confirmRef}
              onConfirm={(r) => act(() => api.confirmCommand(r.id))}
              onCancel={(r) => act(() => api.cancelCommand(r.id))}
            />
          )}
        </div>
      </div>

      <div className="cmd-voice">
        <div className="field-row">
          <div className="field">
            <label htmlFor="speech-engine">Speech engine</label>
            <select id="speech-engine" value={engine} onChange={(e) => setEngine(e.target.value)} disabled={recording}>
              <option value="whisper">Whisper (local)</option>
              {BrowserRecognition && <option value="browser">Browser (online)</option>}
            </select>
          </div>
          <div className="field">
            <label htmlFor="speech-lang">Spoken language</label>
            <select id="speech-lang" value={langHint} onChange={(e) => setLangHint(e.target.value)} disabled={recording}>
              <option value="">{engine === 'browser' ? 'English (India)' : 'Auto-detect'}</option>
              <option value="en">English</option>
              <option value="hi">Hindi (हिन्दी)</option>
            </select>
          </div>
        </div>
        <div className="mic-row">
          <button
            type="button"
            className={`btn btn-mic${recording ? ' on' : ''}`}
            onClick={toggleMic}
            disabled={!online || busy || !!phase || (engine === 'whisper' && speech && !speech.available)}
            aria-pressed={recording}
          >
            <MicIcon size={18} />
            {recording ? 'Stop recording' : 'Speak a command'}
          </button>
          <div className="mic-state" role="status" aria-live="polite">
            {recording && (
              <>
                <span className="rec-dot" aria-hidden="true" />
                <span>Listening{rec.elapsed ? ` ${rec.elapsed.toFixed(1)} s` : ''} (stops by itself after {MAX_RECORD_MS / 1000} s)</span>
                {rec.level != null && (
                  <span className="level" aria-hidden="true">
                    <span style={{ width: `${Math.round(rec.level * 100)}%` }} />
                  </span>
                )}
              </>
            )}
            {phase && (
              <>
                <SpinnerIcon size={14} />
                <span>
                  {phase === 'loading'
                    ? `Loading Whisper ${speech?.model ?? ''} and transcribing (first use can take a while)...`
                    : `Transcribing with Whisper ${speech?.model ?? ''} on the CPU (a few seconds)...`}
                </span>
              </>
            )}
            {!recording && !phase && engine === 'whisper' && speech && !speech.available && <span className="field-error">Whisper unavailable: {speech.reason}</span>}
          </div>
        </div>
        <p className="muted small">
          {engine === 'whisper'
            ? 'Audio is transcribed by faster-whisper on the backend; it is not sent to any cloud service. The microphone is used only while recording.'
            : 'Browser speech recognition is provided by the browser (in Chrome, audio is sent to Google). Use Whisper to keep audio local.'}
        </p>
      </div>

      <div className="cmd-select">
        <label htmlFor="cmd-place">Or choose a destination</label>
        <div className="cmd-input-row">
          <select id="cmd-place" value={placeKey} onChange={(e) => setPlaceKey(e.target.value)} disabled={!online}>
            <option value="">Select a place...</option>
            {places.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name} / {p.name_hi} (x {p.x}, y {p.y})
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn"
            disabled={!online || busy || !placeKey}
            onClick={() => {
              const p = places.find((x) => x.key === placeKey);
              if (p) submit(`Go to the ${p.name.toLowerCase()}`, 'selector');
            }}
          >
            Go
          </button>
        </div>
      </div>

      <div className="cmd-options">
        <label className="check">
          <input
            type="checkbox"
            checked={trusted}
            onChange={(e) => {
              setTrusted(e.target.checked);
              writeFlag('vistara.trusted', e.target.checked);
            }}
          />
          Trusted mode: start valid destinations without asking to confirm
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={spoken}
            onChange={(e) => {
              setSpoken(e.target.checked);
              writeFlag('vistara.spoken', e.target.checked);
              if (!e.target.checked) window.speechSynthesis?.cancel();
            }}
          />
          Speak responses aloud (the text is always shown)
        </label>
      </div>


      <h3 className="sub">Transcript history ({history.length})</h3>
      {history.length ? (
        <ol className="cmd-history" reversed>
          {[...history].reverse().map((h) => {
            const [tone, label] = STATUS[h.status] || ['muted', h.status];
            return (
              <li key={h.id}>
                <span className="mono small muted">{h.time}</span>{' '}
                <span lang={h.language === 'hi' ? 'hi' : 'en'}>&ldquo;{h.transcript}&rdquo;</span>{' '}
                <span className={`cmd-status cmd-status-${tone}`}>{label}</span>
                {h.response && (
                  <span className="cmd-history-reply" lang={h.response.language === 'hi' ? 'hi' : 'en'}>
                    {h.response.text}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="empty">No commands yet. Type one, pick an example, or speak.</p>
      )}
    </section>
  );
}
