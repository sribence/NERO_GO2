import wave
import os

sounds_dir = "/home/unitree/NERO_GO2/src/go2-brain-logic/mission_control/audio/sounds"
for f in ["proximity_warning.wav", "task_complete.wav", "test.wav"]:
    p = os.path.join(sounds_dir, f)
    if os.path.isfile(p):
        w = wave.open(p, "rb")
        print(f"{f}: Channels={w.getnchannels()}, Rate={w.getframerate()}Hz, Width={w.getsampwidth()}B, Frames={w.getnframes()}, Duration={w.getnframes()/float(w.getframerate()):.2f}s")
    else:
        print(f"{f}: FILE NOT FOUND!")
