import os
import wave
import pydub

sounds_dir = r"c:\Users\user\NERO_GO2\src\go2-hardware-bridge\webrtc_bridge\sounds"

for filename in os.listdir(sounds_dir):
    if filename.endswith(".wav") or filename.endswith(".mp3"):
        path = os.path.join(sounds_dir, filename)
        print(f"Processing {filename}...")
        sound = pydub.AudioSegment.from_file(path)
        sound = sound.set_frame_rate(16000).set_channels(1)
        out_path = os.path.join(sounds_dir, filename.split('.')[0] + ".wav")
        sound.export(out_path, format="wav")
        print(f"  Converted {filename} -> {out_path} (16kHz, mono, duration: {sound.duration_seconds:.2f}s)")

