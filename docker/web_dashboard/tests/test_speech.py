"""Tests for the offline TTS module (speech.py) and the /api/speak route.

Follows the style of test_joint_safety.py: no real hardware, no real robot,
pure unit-level checks. The key requirement is that a missing/broken TTS
backend (pyttsx3 not installed, or installed but its native voice backend
failing, e.g. no espeak-ng on a bare Linux box) must degrade gracefully —
log and return None/503 — and never crash the process or the route.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import speech  # noqa: E402


# --- speech.speak_to_wav() ---------------------------------------------------


def test_speak_to_wav_returns_none_for_empty_text():
    assert speech.speak_to_wav("") is None
    assert speech.speak_to_wav("   ") is None
    assert speech.speak_to_wav(None) is None  # type: ignore[arg-type]


def test_speak_to_wav_returns_none_when_pyttsx3_missing():
    """Simulates the environment where `pip install pyttsx3` was never run
    (or failed) — the exact scenario this module exists to survive."""
    with mock.patch.object(speech, "pyttsx3", None):
        result = speech.speak_to_wav("Szia, ez egy teszt.")
    assert result is None


def test_speak_to_wav_survives_engine_init_raising():
    """If pyttsx3 IS importable but its native backend blows up at init
    time (e.g. no espeak-ng on a bare Linux container), speak_to_wav must
    still return None instead of propagating the exception."""
    fake_pyttsx3 = mock.Mock()
    fake_pyttsx3.init.side_effect = RuntimeError("no espeak-ng backend")
    with mock.patch.object(speech, "pyttsx3", fake_pyttsx3):
        result = speech.speak_to_wav("Szia!")
    assert result is None


def test_speak_to_wav_survives_save_to_file_raising():
    fake_engine = mock.Mock()
    fake_engine.save_to_file.side_effect = RuntimeError("synthesis failed")
    fake_pyttsx3 = mock.Mock()
    fake_pyttsx3.init.return_value = fake_engine
    with mock.patch.object(speech, "pyttsx3", fake_pyttsx3):
        result = speech.speak_to_wav("Szia!")
    assert result is None
    fake_engine.stop.assert_called_once()  # cleanup still happens on failure


def test_speak_to_wav_returns_bytes_on_success(tmp_path):
    """Mocks pyttsx3 down to "write some bytes to the path it's given" so
    this test exercises speech.py's own file-handling/cleanup logic without
    depending on a real TTS backend being installed in CI/dev sandboxes."""
    fake_audio = b"RIFF....WAVEfmt fake-wav-bytes"

    def fake_save_to_file(text, path):
        with open(path, "wb") as f:
            f.write(fake_audio)

    fake_engine = mock.Mock()
    fake_engine.save_to_file.side_effect = fake_save_to_file
    fake_pyttsx3 = mock.Mock()
    fake_pyttsx3.init.return_value = fake_engine

    with mock.patch.object(speech, "pyttsx3", fake_pyttsx3):
        result = speech.speak_to_wav("Szia, működik!")

    assert result == fake_audio
    fake_engine.runAndWait.assert_called_once()
    fake_engine.stop.assert_called_once()


def test_speak_to_wav_truncates_overlong_text():
    seen = {}

    def fake_save_to_file(text, path):
        seen["text"] = text
        with open(path, "wb") as f:
            f.write(b"x")

    fake_engine = mock.Mock()
    fake_engine.save_to_file.side_effect = fake_save_to_file
    fake_pyttsx3 = mock.Mock()
    fake_pyttsx3.init.return_value = fake_engine

    with mock.patch.object(speech, "pyttsx3", fake_pyttsx3):
        speech.speak_to_wav("a" * (speech.MAX_TEXT_LEN + 200))

    assert len(seen["text"]) == speech.MAX_TEXT_LEN


def test_is_available_reflects_pyttsx3_presence():
    with mock.patch.object(speech, "pyttsx3", None):
        assert speech.is_available() is False
    with mock.patch.object(speech, "pyttsx3", mock.Mock()):
        assert speech.is_available() is True


# --- /api/speak Flask route --------------------------------------------------
# app.py starts several background threads (SDK init, watchdog, live-map,
# etc.) at import time. We only need the Flask `app` object and its routing,
# so we set MOCK_SDK=1 first (same as the mock-mode Docker path) to keep
# those threads harmless/no-op-ish, then import app once per test module.


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("MOCK_SDK", "1")
    import app as flask_app_module

    flask_app_module.app.testing = True
    with flask_app_module.app.test_client() as c:
        yield c


def test_api_speak_rejects_missing_text(client):
    resp = client.post("/api/speak", json={})
    assert resp.status_code == 400


def test_api_speak_rejects_empty_text(client):
    resp = client.post("/api/speak", json={"text": "   "})
    assert resp.status_code == 400


def test_api_speak_returns_503_when_tts_unavailable(client):
    with mock.patch("speech.speak_to_wav", return_value=None):
        resp = client.post("/api/speak", json={"text": "Szia!"})
    assert resp.status_code == 503


def test_api_speak_returns_audio_on_success(client):
    with mock.patch("speech.speak_to_wav", return_value=b"fake-wav-bytes"):
        resp = client.post("/api/speak", json={"text": "Szia!"})
    assert resp.status_code == 200
    assert resp.mimetype == "audio/wav"
    assert resp.data == b"fake-wav-bytes"
