import asyncio
import os
import sys
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub

async def test():
    ip = os.environ.get("UNITREE_ROBOT_IP", "192.168.123.161")
    aes_key = os.environ.get("UNITREE_AES_128_KEY", "7c5a74e640766444cc26b19990968133")
    print(f"Connecting to {ip}...")
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip, aes_128_key=aes_key)
    await conn.connect()
    print("conn.isConnected:", conn.isConnected)
    print("conn.datachannel:", conn.datachannel)
    if hasattr(conn.datachannel, "channel"):
        print("datachannel.channel:", conn.datachannel.channel)
        if conn.datachannel.channel:
            print("channel.readyState:", conn.datachannel.channel.readyState)
    
    # Wait for datachannel readyState if needed
    for i in range(10):
        if hasattr(conn.datachannel, "channel") and conn.datachannel.channel and conn.datachannel.channel.readyState == "open":
            print(f"Datachannel open after {i*0.5}s!")
            break
        await asyncio.sleep(0.5)
        
    hub = WebRTCAudioHub(conn)
    print("Querying audio list (api_id 1001)...")
    res1 = await hub.data_channel.pub_sub.publish_request_new("rt/api/audiohub/request", {"api_id": 1001, "parameter": "{}"})
    print("Audio List Result:", res1)

    print("Playing sound 3001 (obstacle_avoidance)...")
    res2 = await hub.data_channel.pub_sub.publish_request_new("rt/api/audiohub/request", {"api_id": 3001, "parameter": "{}"})
    print("Play 3001 Result:", res2)

    await conn.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
