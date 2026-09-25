import asyncio
import os
import sys
import wave
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub

def get_wav_duration(path):
    try:
        with wave.open(path, 'rb') as f:
            frames = f.getnframes()
            rate = f.getframerate()
            return frames / float(rate)
    except Exception:
        return 3.0

async def main():
    ip = os.environ.get("UNITREE_ROBOT_IP", "192.168.123.161")
    aes_key = os.environ.get("UNITREE_AES_128_KEY", "7c5a74e640766444cc26b19990968133")
    wav_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test.wav"
    
    duration = get_wav_duration(wav_path)
    print(f"File {wav_path} duration: {duration:.2f} seconds")
    
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip, aes_128_key=aes_key)
    await conn.connect()
    print("Connected to Go2:", conn.isConnected)
    
    hub = WebRTCAudioHub(conn)
    
    print("Entering Megaphone mode...")
    await hub.enter_megaphone()
    await asyncio.sleep(0.5)
    
    print("Uploading file to Megaphone...")
    res = await hub.upload_megaphone(wav_path)
    print("Upload completed:", res)
    
    wait_time = max(duration + 1.5, 3.0)
    print(f"Waiting {wait_time:.2f}s for robot speaker to finish playing...")
    await asyncio.sleep(wait_time)
    
    print("Exiting Megaphone mode...")
    await hub.exit_megaphone()
    await conn.disconnect()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
