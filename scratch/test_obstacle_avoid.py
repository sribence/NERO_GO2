import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.123.18", username="unitree", password="123", timeout=10)

cmd = "docker run --rm nero_go2/webrtc_bridge:latest python3 -c \"import unitree_webrtc_connect as u; print('RTC_TOPIC:', u.RTC_TOPIC)\""
stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())
client.close()
