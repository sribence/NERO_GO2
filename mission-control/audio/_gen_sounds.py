"""One-off generator for placeholder beep WAVs (run manually if sounds/ is empty).

Not imported by app.py; kept only as a convenience to regenerate/add sounds
without external assets.
"""
import math
import os
import struct
import wave

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")


def make_beep(path: str, freq_hz: float, duration_s: float, volume: float = 0.5, sample_rate: int = 44100):
    n_samples = int(duration_s * sample_rate)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            # simple attack/decay envelope so it doesn't click
            envelope = min(1.0, i / (0.01 * sample_rate)) * min(1.0, (n_samples - i) / (0.02 * sample_rate))
            sample = volume * envelope * math.sin(2 * math.pi * freq_hz * t)
            frames += struct.pack("<h", int(sample * 32767))
        wf.writeframes(bytes(frames))


if __name__ == "__main__":
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    make_beep(os.path.join(SOUNDS_DIR, "proximity_warning.wav"), freq_hz=880.0, duration_s=0.35, volume=0.6)
    make_beep(os.path.join(SOUNDS_DIR, "task_complete.wav"), freq_hz=523.25, duration_s=0.5, volume=0.5)
    make_beep(os.path.join(SOUNDS_DIR, "test.wav"), freq_hz=440.0, duration_s=0.25, volume=0.4)
    print(f"wrote sounds to {SOUNDS_DIR}")
