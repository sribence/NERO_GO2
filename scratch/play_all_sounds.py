import requests
import time

BRIDGE_URL = "http://127.0.0.1:5001"
MC_AUDIO_URL = "http://127.0.0.1:9107"

sounds_to_test = [
    ("1. Proximity warning (WAV fájl)", "/audio/play/proximity_warning"),
    ("2. Task complete (WAV fájl)", "/audio/play/task_complete"),
    ("3. Test audio (WAV fájl)", "/audio/play/test"),
    ("4. Low battery (TTS angolul)", "/audio/play/low_battery"),
    ("5. Incident alert (TTS angolul)", "/audio/play/incident"),
    ("6. Obstacle avoidance (Beépített gyári hang)", "/audio/play/obstacle_avoidance"),
    ("7. Companion mode (Beépített gyári hang)", "/audio/play/companion_mode"),
]

print("==================================================")
print("🔊 INDÍTJUK AZ ÖSSZES HANG TESTETSOROZATÁT A ROBOTON 🔊")
print("==================================================\n")

for label, endpoint in sounds_to_test:
    print(f"▶ [{label}] Lejátszása indítva...")
    try:
        r = requests.post(f"{BRIDGE_URL}{endpoint}", timeout=10.0)
        print(f"  Válasz status: {r.status_code}, payload: {r.json()}")
    except Exception as e:
        print(f"  Hiba: {e}")
    print("  [Várakozás 4 másodpercig, amíg a robot hangszórója lejátsza...]\n")
    time.sleep(4.5)

print("▶ [8. Egyedi magyar TTS beszéd teszt] Lejátszása indítva...")
try:
    payload = {"text": "A robot audió rendszere sikeresen letesztelve. Minden hangminta megfelelően működik.", "lang": "hu"}
    r = requests.post(f"{BRIDGE_URL}/api/speak", json=payload, timeout=15.0)
    print(f"  Válasz status: {r.status_code}, payload: {r.json()}")
except Exception as e:
    print(f"  Hiba: {e}")

print("\n==================================================")
print("✅ TESZTSOROZAT BEFEJEZŐDÖTT!")
print("==================================================")
