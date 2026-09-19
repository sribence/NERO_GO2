import sys
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

cmd = """python3 -c "
with open('/home/unitree/.bash_history', 'rb') as f:
    text = f.read().decode('latin1', errors='ignore')
for line in text.splitlines():
    if any(k in line.lower() for k in ['aes', 'key', 'unitree', 'token', 'fetch', 'export', 'env']):
        print(line)
" """

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', errors='replace'))
ssh.close()
