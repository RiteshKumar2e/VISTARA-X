"""Local speech recognition with faster-whisper (OpenAI Whisper weights, CTranslate2).

Audio never leaves the machine. The browser records a short clip (WebM/Opus, OGG or
WAV); PyAV decodes it, Whisper detects the language and transcribes. Only English and
Hindi are accepted for commands because the command parser supports exactly those.
Whisper often labels spoken Hindi as Urdu (same spoken language, different script);
such clips are re-transcribed as Hindi so the text comes out in Devanagari, and the
original detection is reported alongside.
"""

from __future__ import annotations

import io
import logging
import threading
import time

log = logging.getLogger("vistara.speech")

SUPPORTED = {"en": "English", "hi": "Hindi"}
HINDI_LIKE = {"ur", "hi", "pa", "ne", "mr"}  # often confused with spoken Hindi
MAX_SECONDS = 15.0
MIN_SECONDS = 0.3
MAX_BYTES = 3 * 1024 * 1024


class SpeechError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


class SpeechRecognizer:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model = None
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self.load_seconds: float | None = None
        try:
            import faster_whisper  # noqa: F401

            self.available, self.reason = True, "ready"
        except Exception:  # pragma: no cover - depends on environment
            self.available, self.reason = False, "faster-whisper is not installed (pip install faster-whisper)"

    def status(self) -> dict:
        return {
            "engine": "faster-whisper (local, offline)",
            "available": self.available and self.load_error is None,
            "reason": self.load_error or self.reason,
            "model": self.model_size,
            "loaded": self._model is not None,
            "load_seconds": self.load_seconds,
            "languages": SUPPORTED,
            "max_seconds": MAX_SECONDS,
        }

    def _load(self):
        if self._model is None:
            if not self.available:
                raise SpeechError("speech_unavailable", self.reason, 503)
            from faster_whisper import WhisperModel

            started = time.perf_counter()
            try:
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            except Exception as exc:
                self.load_error = f"Could not load Whisper '{self.model_size}': {type(exc).__name__}: {exc}"[:240]
                raise SpeechError("speech_unavailable", self.load_error, 503) from exc
            self.load_seconds = round(time.perf_counter() - started, 1)
            log.info("Loaded Whisper %s in %.1f s", self.model_size, self.load_seconds)
        return self._model

    def warm_up(self) -> dict:
        with self._lock:
            self._load()
        return self.status()

    def _decode(self, data: bytes):
        from faster_whisper import decode_audio

        try:
            return decode_audio(io.BytesIO(data), sampling_rate=16000)
        except Exception as exc:
            raise SpeechError("bad_audio", f"Could not decode the audio clip ({type(exc).__name__})") from exc

    def _run(self, model, audio, language):
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        return text, segs, info

    def transcribe(self, data: bytes, language: str | None = None) -> dict:
        """``language`` ('en' / 'hi') skips Whisper's language detection, which halves the
        processing time on a slow CPU; None lets Whisper detect it."""
        if language is not None and language not in SUPPORTED:
            raise SpeechError("unsupported_language", f"Language hint must be one of {', '.join(SUPPORTED)}")
        if len(data) > MAX_BYTES:
            raise SpeechError("audio_too_large", "Audio clip is larger than 3 MB", 413)
        if not data:
            raise SpeechError("no_audio", "No audio was received")
        audio = self._decode(data)
        duration = len(audio) / 16000
        if duration < MIN_SECONDS:
            raise SpeechError("too_short", "The recording is too short; hold the button while speaking")
        if duration > MAX_SECONDS:
            raise SpeechError("too_long", f"Recordings are limited to {MAX_SECONDS:.0f} s")
        with self._lock:
            model = self._load()
            started = time.perf_counter()
            hint = language
            text, segs, info = self._run(model, audio, hint)
            detected, prob = info.language, round(float(info.language_probability), 3)
            language, retried = detected, False
            if hint is not None:
                detected, prob = None, None  # not detected: given by the user
            elif detected not in SUPPORTED and detected in HINDI_LIKE:
                text, segs, info = self._run(model, audio, "hi")
                language, retried = "hi", True
            ms = round((time.perf_counter() - started) * 1000)
        no_speech = max((float(s.no_speech_prob) for s in segs), default=1.0)
        avg_logprob = round(sum(float(s.avg_logprob) for s in segs) / len(segs), 3) if segs else None
        if not text:
            status = "no_speech"
        elif language not in SUPPORTED:
            status = "unsupported_language"
        else:
            status = "ok"
        return {
            "status": status,
            "text": text,
            "language": language,
            "language_name": SUPPORTED.get(language, language),
            "detected_language": detected,
            "language_probability": prob,
            "language_hint": hint,
            "retranscribed_as_hindi": retried,
            "avg_logprob": avg_logprob,
            "no_speech_prob": round(no_speech, 3),
            "duration_s": round(duration, 2),
            "processing_ms": ms,
            "model": self.model_size,
            "engine": "faster-whisper",
        }
