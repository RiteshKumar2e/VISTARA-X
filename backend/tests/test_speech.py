"""Speech recognition on synthetic speech clips (Windows TTS, see fixtures/README.md).

Skipped when faster-whisper or the Whisper model is not available offline.
"""

from pathlib import Path

import pytest

from app.commands.parser import parse
from app.commands.speech import SpeechError, SpeechRecognizer
from app.simulation.scenarios import SCENARIOS

FIXTURES = Path(__file__).parent / "fixtures"


def _model_cached(size: str) -> bool:
    try:
        from faster_whisper.utils import download_model

        download_model(size, local_files_only=True)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _model_cached("base"), reason="faster-whisper 'base' model not downloaded")


@pytest.fixture(scope="module")
def rec():
    return SpeechRecognizer("base")


def test_english_command_end_to_end(rec):
    out = rec.transcribe((FIXTURES / "tts_en_storage_room.wav").read_bytes(), language="en")
    assert out["status"] == "ok"
    assert "storage room" in out["text"].lower()
    cmd = parse(out["text"], SCENARIOS["warehouse"].places)
    assert cmd.intent == "navigate" and cmd.destination["key"] == "storage"


def test_language_detection_on_speech(rec):
    out = rec.transcribe((FIXTURES / "tts_en_stop.wav").read_bytes())
    assert out["detected_language"] == "en" and out["language_probability"] > 0.5
    assert parse(out["text"], SCENARIOS["warehouse"].places).intent == "stop"


def test_bad_inputs_are_rejected(rec):
    with pytest.raises(SpeechError) as err:
        rec.transcribe(b"")
    assert err.value.code == "no_audio"
    with pytest.raises(SpeechError) as err:
        rec.transcribe(b"not audio at all" * 10)
    assert err.value.code == "bad_audio"
    with pytest.raises(SpeechError) as err:
        rec.transcribe(b"x", language="fr")
    assert err.value.code == "unsupported_language"
