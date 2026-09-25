import inspect
import unitree_webrtc_connect
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub, AUDIO_API

print("=== AUDIO_API ===")
for k, v in AUDIO_API.items():
    print(f"  {k}: {v}")

print("\n=== WebRTCAudioHub Methods ===")
for name, member in inspect.getmembers(WebRTCAudioHub, predicate=inspect.iscoroutinefunction):
    print(f"  {name}: {inspect.signature(member)}")

print("\n=== unitree_webrtc_connect topics ===")
if hasattr(unitree_webrtc_connect, "RTC_TOPIC"):
    for k, v in unitree_webrtc_connect.RTC_TOPIC.items():
        if "audio" in k.lower() or "voice" in k.lower() or "tts" in k.lower() or "speech" in k.lower():
            print(f"  {k}: {v}")
