import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123', timeout=15)

cmd = """export PYTHONPATH="/home/unitree/.local/lib/python3.8/site-packages:$PYTHONPATH"
cd /home/unitree/NERO_GO2/src/go2-gui-visualization/go2-console
nohup python3 run.py --host 0.0.0.0 --port 9200 --live </dev/null >/tmp/go2_console.log 2>&1 &
sleep 2
"""

stdin, stdout, stderr = ssh.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())
ssh.close()
