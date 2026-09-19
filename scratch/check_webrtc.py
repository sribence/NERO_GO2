import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

cmd = """docker exec nero_go2_webrtc_bridge python -c "
with open('/usr/local/lib/python3.11/site-packages/unitree_webrtc_connect/webrtc_audiohub.py') as f:
    lines = f.readlines()
    print(''.join(lines[:80]))
" """

stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
