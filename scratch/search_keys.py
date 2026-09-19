import sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123')

cmd = """python3 -c "
import os, re
pattern = re.compile(r'[a-fA-F0-9]{32}')
for root, dirs, files in os.walk('/home/unitree/NERO_GO2'):
    if '.git' in root or 'node_modules' in root: continue
    for fname in files:
        if fname.endswith(('.log', '.txt', '.env', '.json', '.sh', '.md')):
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', errors='ignore') as f:
                    for i, line in enumerate(f):
                        if 'aes_128' in line.lower() or 'unitree_aes' in line.lower() or pattern.search(line):
                            print(f'{fpath}:{i+1}: {line.strip()}')
            except Exception: pass
" """

stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
print(out)
ssh.close()
