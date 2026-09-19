import os
import tarfile
import paramiko

local_dir = r"c:\Users\user\NERO_GO2\src\go2-gui-visualization\go2-console"
tar_path = r"c:\Users\user\NERO_GO2\scratch\go2_console.tar.gz"

print("Creating tar archive of go2-console...")
with tarfile.open(tar_path, "w:gz") as tar:
    tar.add(local_dir, arcname="go2-console")
print("Archive created.")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.123.18', username='unitree', password='123', timeout=30)

sftp = ssh.open_sftp()
remote_tar = "/tmp/go2_console.tar.gz"
print(f"Uploading to {remote_tar}...")
sftp.put(tar_path, remote_tar)
sftp.close()

target_dest = "/home/unitree/NERO_GO2/src/go2-gui-visualization"
cmd = f"rm -rf {target_dest}/go2-console && tar -xzf {remote_tar} -C {target_dest} && ls -la {target_dest}/go2-console"
print(f"Extracting on Jetson: {cmd}")
stdin, stdout, stderr = ssh.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())

ssh.close()
print("Done!")
