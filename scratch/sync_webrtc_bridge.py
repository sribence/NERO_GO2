import os
import paramiko

local_path = os.path.abspath("src/go2-hardware-bridge/webrtc_bridge/bridge.py")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.123.18", username="unitree", password="123", timeout=10)

sftp = client.open_sftp()
sftp.put(local_path, "/home/unitree/NERO_GO2/src/go2-hardware-bridge/webrtc_bridge/bridge.py")
sftp.put(local_path, "/home/unitree/NERO_GO2/docker/webrtc_bridge/bridge.py")
sftp.close()

print("bridge.py uploaded successfully.")

aes_key = os.environ.get("UNITREE_AES_128_KEY", "")
if not aes_key and os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.startswith("UNITREE_AES_128_KEY="):
                aes_key = line.split("=", 1)[1].strip()
                break

cmd = (
    "cd /home/unitree/NERO_GO2/docker/webrtc_bridge && "
    "docker build -t nero_go2/webrtc_bridge:latest . && "
    "docker stop nero_go2_webrtc_bridge_1 || true && "
    "docker rm nero_go2_webrtc_bridge_1 || true && "
    "docker run -d --name nero_go2_webrtc_bridge_1 --restart=unless-stopped --net=host "
    f"-e UNITREE_ROBOT_IP=192.168.123.161 -e UNITREE_AES_128_KEY={aes_key} nero_go2/webrtc_bridge:latest"
)
stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())
client.close()
