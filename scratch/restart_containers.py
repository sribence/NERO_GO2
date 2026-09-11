import paramiko
import time

containers = [
    "nero_go2_hesai_bridge",
    "nero_go2_webrtc_bridge",
    "nero_go2_realsense_bridge",
    "nero_go2_web_dashboard"
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print("Connecting to Jetson Orin (192.168.123.18)...")
    ssh.connect('192.168.123.18', username='unitree', password='123', timeout=5)
    print("Connected.")

    for c in containers:
        print(f"Restarting container {c} with 2s timeout...")
        stdin, stdout, stderr = ssh.exec_command(f"docker restart -t 2 {c}", timeout=10)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        print(f"  Result for {c}: {out if out else err}")

    print("\nChecking container status:")
    stdin, stdout, stderr = ssh.exec_command("docker ps --format 'table {{.Names}}\t{{.Status}}'", timeout=5)
    print(stdout.read().decode('utf-8', errors='replace'))

except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
