import os
from gtts import gTTS
import pydub

sounds_dir = r"c:\Users\user\NERO_GO2\src\go2-hardware-bridge\webrtc_bridge\sounds"
os.makedirs(sounds_dir, exist_ok=True)

phrases = {
    "proximity_warning.wav": ("Warning! Proximity alert!", "en"),
    "task_complete.wav": ("Task complete!", "en"),
    "test.wav": ("Audio system test, check okay!", "en"),
    "low_battery.wav": ("Warning, low battery!", "en"),
    "incident.wav": ("Warning, incident detected!", "en"),
}

for filename, (text, lang) in phrases.items():
    tmp_mp3 = os.path.join(sounds_dir, filename.replace(".wav", "_tmp.mp3"))
    out_wav = os.path.join(sounds_dir, filename)
    print(f"Generating spoken audio for {filename}: '{text}'...")
    
    tts = gTTS(text=text, lang=lang)
    tts.save(tmp_mp3)
    
    sound = pydub.AudioSegment.from_file(tmp_mp3)
    sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    sound.export(out_wav, format="wav")
    
    os.remove(tmp_mp3)
    print(f"  Saved {out_wav} (16kHz mono, duration: {sound.duration_seconds:.2f}s)")

print("\nAll spoken sound files generated successfully!")
