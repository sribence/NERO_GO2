import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

cmd = """docker exec nero_go2_webrtc_bridge python -c "
import asyncio, json
from unitree_webrtc_connect import UnitreeWebRTCConnection, WebRTCConnectionMethod
from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub

async def test_voice():
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.123.18')
    await conn.connect()
    hub = WebRTCAudioHub(conn.datachannel)
    print('Connected to Unitree Go2 WebRTC!')
    
    # 1. Get audio list
    try:
        res = await conn.datachannel.pub_sub.publish_request_new(
            'rt/api/audiohub/request',
            {'api_id': 1001, 'parameter': json.dumps({})}
        )
        print('AUDIO LIST RESPONSE:', res)
    except Exception as e:
        print('Audio list err:', e)

    # 2. Try play sound
    try:
        res = await conn.datachannel.pub_sub.publish_request_new(
            'rt/api/audiohub/request',
            {'api_id': 1002, 'parameter': json.dumps({'play_id': '1'})}
        )
        print('PLAY RESPONSE:', res)
    except Exception as e:
        print('Play err:', e)

    await conn.disconnect()

asyncio.run(test_voice())
" """

stdin, stdout, stderr = ssh.exec_command(cmd)
print('STDOUT:', stdout.read().decode('utf-8', errors='replace'))
print('STDERR:', stderr.read().decode('utf-8', errors='replace'))

ssh.close()
