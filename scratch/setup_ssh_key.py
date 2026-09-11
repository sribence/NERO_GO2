import paramiko

PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnXhlI536CwwM+bMZMc4sXwSaQoOTBrMFESGlpRxKJK claude-code@neonpc-localai-setup"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting to Jetson...")
ssh.connect('192.168.123.18', username='unitree', password='123', timeout=10)
print("Connected. Updating authorized_keys...")
cmd = f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '{PUBKEY}' ~/.ssh/authorized_keys 2>/dev/null || echo '{PUBKEY}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
stdin, stdout, stderr = ssh.exec_command(cmd)
stdout.read()
ssh.close()
print("SSH key added successfully!")
