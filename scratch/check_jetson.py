import urllib.request
import paramiko
import subprocess
import trace

print("--- 1. Ping check ---")
res = subprocess.run(["ping", "-n", "1", "192.168.123.18"], capture_output=True, text=True)
print("Ping exit code:", res.returncode)

print("\n--- 2. SSH Docker status ---")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('192.168.123.18', username='unitree', password='123', timeout=5)
    stdin, stdout, stderr = ssh.exec_command("docker ps --format 'table {{.Names}}\t{{.Status}}'", timeout=5)
    print(stdout.read().decode('utf-8'))
    ssh.close()
except Exception as e:
    print(f"SSH status error ({type(e).__name__}): {e}")

print("\n--- 3. Web Dashboard HTTP status ---")
try:
    with urllib.request.urlopen("http://192.168.123.18:5002/", timeout=5) as resp:
        print("HTTP Status Code:", resp.getcode())
except Exception as e:
    print(f"HTTP fetch error ({type(e).__name__}): {e}")
