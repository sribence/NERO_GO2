import asyncio
import os
import sys
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub

async def main():
    ip = os.environ.get("UNITREE_ROBOT_IP", "192.168.123.161")
    aes_key = os.environ.get("UNITREE_AES_128_KEY", "7c5a74e640766444cc26b19990968133")
    wav_path = sys.argv[1] if len(sys.argv) > 1 else "/app/sounds/test.wav"
    
    print(f"Connecting to {ip}...")
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip, aes_128_key=aes_key)
    await conn.connect()
    print("Connected:", conn.isConnected)
    
    hub = WebRTCAudioHub(conn)
    print("Entering Megaphone mode...")
    await hub.enter_megaphone()
    await asyncio.sleep(0.3)
    
    print(f"Uploading and streaming {wav_path} via Megaphone...")
    res = await hub.upload_megaphone(wav_path)
    print("Upload result:", res)
    await asyncio.sleep(0.5)
    
    print("Exiting Megaphone mode...")
    await hub.exit_megaphone()
    await conn.disconnect()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
