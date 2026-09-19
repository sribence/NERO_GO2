import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

# 1. Check state
stdin, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:9200/api/state')
print('=== STATE ===')
print(stdout.read().decode('utf-8', errors='replace')[:400])

# 2. Post valid ARM request
stdin, stdout, stderr = ssh.exec_command('python3 -c "import requests; print(requests.post(\'http://127.0.0.1:9200/api/arm\', json={\'armed\': True}).json())"')
print('=== ARM RESPONSE ===')
print(stdout.read().decode('utf-8', errors='replace')[:400])
print(stderr.read().decode('utf-8', errors='replace'))

ssh.close()
