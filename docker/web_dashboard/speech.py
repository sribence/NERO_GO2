"""Offline text-to-speech for the NERO_GO2 dashboard.

Uses `pyttsx3` (offline, no cloud API, no network dependency) — the whole
point of this module is that "the robot can speak" must keep working even
when the Jetson/dock has no internet connection.

IMPORTANT — hardware status (2026-09-17, honestly, not aspirationally):
there is NO confirmed physical speaker wired to the robot or to the dock in
this repo. `app.py`'s `_mock_play_audio()` (the security-mode "intruder"
sound) is a log-line stand-in with an explicit "holnap: valós audio-hívás"
("tomorrow: real audio call") comment — nobody has built or tested a real
audio-output path yet. So this module generates a WAV file and hands the
*bytes* back to the caller; the Flask route in app.py returns those bytes to
the browser, which plays them through whatever audio output the machine
running the browser has. That is the simplest thing that could plausibly be
re-pointed at a speaker wired to the Jetson/dock tomorrow (swap the "return
bytes to browser" step for "write to a local ALSA/PulseAudio sink"), without
pretending robot-mounted hardware exists today.

Degrades gracefully: if `pyttsx3` (or its platform TTS backend, e.g. espeak
on Linux) is not installed/available, `speak_to_wav()` logs a warning and
returns None instead of raising — a missing optional dependency must never
crash the dashboard or any route that calls into this module.
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger("nero_go2.web_dashboard.speech")

try:
    import pyttsx3

    _IMPORT_ERROR = None
except Exception as exc:  # ImportError, or platform backend init errors on import
    pyttsx3 = None
    _IMPORT_ERROR = exc


MAX_TEXT_LEN = 500  # a runaway/garbage request should not hang the TTS engine for ages


def is_available() -> bool:
    """True if the pyttsx3 package itself imported. Does not guarantee a
    working voice backend on this machine (see `speak_to_wav`'s own
    try/except for that) — Docker/Linux may still lack espeak, headless
    Windows may still lack SAPI5, etc."""
    return pyttsx3 is not None


def speak_to_wav(text: str) -> bytes | None:
    """Synthesize `text` to WAV audio bytes using an offline TTS engine.

    Returns None (and logs, never raises past this function) if the TTS
    library is missing, the text is invalid, or synthesis fails for any
    reason — callers must treat None as "no audio available" and degrade
    the route response accordingly, not as an exception to propagate.
    """
    if not text or not isinstance(text, str) or not text.strip():
        logger.warning("speak_to_wav: empty/invalid text, nothing to synthesize")
        return None
    text = text.strip()[:MAX_TEXT_LEN]

    if pyttsx3 is None:
        logger.warning(
            "speak_to_wav: pyttsx3 not available (%s) — TTS disabled, "
            "install it with `pip install pyttsx3` (Linux also needs the "
            "`espeak`/`espeak-ng` system package)",
            _IMPORT_ERROR,
        )
        return None

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        engine = pyttsx3.init()
        try:
            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
        finally:
            # pyttsx3 engines can hold onto native (COM/espeak) resources —
            # always tear this one down, even if synthesis raised above.
            try:
                engine.stop()
            except Exception:
                pass

        with open(tmp_path, "rb") as f:
            data = f.read()
        if not data:
            logger.warning("speak_to_wav: engine produced an empty WAV file for text=%r", text)
            return None
        return data
    except Exception:
        logger.exception("speak_to_wav: TTS synthesis failed for text=%r", text)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
