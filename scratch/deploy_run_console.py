import paramiko

script_content = """#!/bin/bash
export PYTHONPATH="/home/unitree/.local/lib/python3.8/site-packages:$PYTHONPATH"
cd /home/unitree/NERO_GO2/src/go2-gui-visualization/go2-console
exec python3 run.py --host 0.0.0.0 --port 9200 --live
"""

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123', timeout=15)

sftp = ssh.open_sftp()
with sftp.file('/home/unitree/run_console.sh', 'w') as f:
    f.write(script_content)
sftp.chmod('/home/unitree/run_console.sh', 0o755)
sftp.close()

stdin, stdout, stderr = ssh.exec_command("pkill -f 'go2-console/run.py'; nohup /home/unitree/run_console.sh > /tmp/go2_console.log 2>&1 & sleep 3; netstat -tulpn | grep 9200; head -n 20 /tmp/go2_console.log")
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())

ssh.close()
