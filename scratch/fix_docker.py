import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('192.168.123.18', username='unitree', password='123', timeout=5)
    print("Checking docker processes on Jetson:")
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep docker")
    print(stdout.read().decode('utf-8', errors='replace'))
    
    print("\nKilling hanging CLI docker client processes if any...")
    stdin, stdout, stderr = ssh.exec_command("pkill -9 -f 'docker restart' || true")
    stdout.read()
    
    print("\nChecking docker container states:")
    stdin, stdout, stderr = ssh.exec_command("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Created}}'")
    print(stdout.read().decode('utf-8', errors='replace'))

except Exception as e:
    print(f"Error: {e}")
finally:
    ssh.close()
