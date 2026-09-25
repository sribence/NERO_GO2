import asyncio
import os
import sys
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub

async def main():
    ip = os.environ.get("UNITREE_ROBOT_IP", "192.168.123.161")
    aes_key = os.environ.get("UNITREE_AES_128_KEY", "7c5a74e640766444cc26b19990968133")
    sound_id = sys.argv[1] if len(sys.argv) > 1 else "3001"
    
    print(f"Connecting to {ip} with AES key {aes_key}...")
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip, aes_128_key=aes_key)
    try:
        await conn.connect()
        print("Connected:", conn.isConnected)
        hub = WebRTCAudioHub(conn)
        
        # Test 1: Query audio list
        print("--- Querying Audio List ---")
        list_res = await hub.data_channel.pub_sub.publish_request_new(
            "rt/api/audiohub/request",
            {"api_id": 1001, "parameter": "{}"}
        )
        print("Audio List response:", list_res)
        
        # Test 2: Play sound_id
        api_id = int(sound_id) if sound_id.isdigit() else 3001
        print(f"--- Playing api_id {api_id} ---")
        play_res = await hub.data_channel.pub_sub.publish_request_new(
            "rt/api/audiohub/request",
            {"api_id": api_id, "parameter": "{}"}
        )
        print("Play response:", play_res)
        
    except Exception as e:
        print("Error:", type(e), e)
    finally:
        await conn.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
