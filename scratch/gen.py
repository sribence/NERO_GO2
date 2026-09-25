import os
import pydub
from gtts import gTTS

sounds_dir = "/app/sounds"
os.makedirs(sounds_dir, exist_ok=True)

phrases = {
    "proximity_warning.wav": "Warning! Proximity alert!",
    "task_complete.wav": "Task complete!",
    "test.wav": "Audio system test, check okay!",
    "low_battery.wav": "Warning, low battery!",
    "incident.wav": "Warning, incident detected!",
}

for filename, text in phrases.items():
    tmp_mp3 = f"/tmp/{filename}.mp3"
    out_wav = os.path.join(sounds_dir, filename)
    print(f"Generating spoken voice for {filename}: {text}")
    try:
        tts = gTTS(text=text, lang="en")
        tts.save(tmp_mp3)
        sound = pydub.AudioSegment.from_file(tmp_mp3)
        sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        sound.export(out_wav, format="wav")
        print(f"  Successfully generated {out_wav} (16kHz mono, duration: {sound.duration_seconds:.2f}s)")
    except Exception as e:
        print(f"  Error generating {filename}: {e}")

print("Done!")
