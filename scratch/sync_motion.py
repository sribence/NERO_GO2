import os
import paramiko

local_motion = os.path.abspath("src/go2-brain-logic/mc_motion/motion.py")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.123.18", username="unitree", password="123", timeout=10)

sftp = client.open_sftp()
sftp.put(local_motion, "/home/unitree/NERO_GO2/src/go2-brain-logic/mc_motion/motion.py")
sftp.put(local_motion, "/home/unitree/NERO_GO2/docker/mc_motion/motion.py")

try:
    sftp.mkdir("/home/unitree/nero_go2_dev/mc_motion")
except Exception:
    pass
sftp.put(local_motion, "/home/unitree/nero_go2_dev/mc_motion/motion.py")
sftp.close()

print("motion.py uploaded to Jetson paths.")

cmd = "docker restart nero_go2_mc_motion"
stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())
client.close()
