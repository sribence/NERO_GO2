import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

cmd = """python3 -c "
import socket
for ip in ['192.168.123.161', '192.168.123.18', '192.168.123.1', '127.0.0.1']:
    for port in [8081, 9991, 8000, 5001]:
        s = socket.socket()
        s.settimeout(0.3)
        res = s.connect_ex((ip, port))
        if res == 0:
            print(f'{ip}:{port} OPEN!')
        s.close()
" """

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', errors='replace'))
print(stderr.read().decode('utf-8', errors='replace'))

ssh.close()
