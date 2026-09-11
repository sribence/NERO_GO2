import glob
import paramiko

pub_files = glob.glob(r'C:\Users\user\.ssh\*.pub')
keys = []
for pf in pub_files:
    with open(pf, 'r') as f:
        keys.append(f.read().strip())

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting to Jetson...")
ssh.connect('192.168.123.18', username='unitree', password='123', timeout=10)
print("Connected. Adding all keys...")

for k in keys:
    if k:
        cmd = f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '{k}' ~/.ssh/authorized_keys 2>/dev/null || echo '{k}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.read()

ssh.close()
print("All keys added!")
