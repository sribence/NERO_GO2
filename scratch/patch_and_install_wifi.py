import sys
import paramiko

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def run_remote_python_script():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print("Connecting to Jetson at 192.168.123.18...")
        ssh.connect('192.168.123.18', username='unitree', password='123', timeout=60)
        
        remote_script = """
import os
import re
import subprocess

print("=== Step 1: Modifying Makefile for CONFIG_POWER_SAVING=n ===")
makefile_path = '/home/unitree/rtl8821cu_clean/Makefile'
with open(makefile_path, 'r') as f:
    content = f.read()

content = re.sub(r'^CONFIG_POWER_SAVING\s*=\s*y', 'CONFIG_POWER_SAVING = n', content, flags=re.MULTILINE)

with open(makefile_path, 'w') as f:
    f.write(content)

print("Makefile updated.")

print("=== Step 2: Adding 2c4e:0107 device ID to os_dep/linux/usb_intf.c ===")
usb_intf_path = '/home/unitree/rtl8821cu_clean/os_dep/linux/usb_intf.c'
with open(usb_intf_path, 'r') as f:
    intf_content = f.read()

target = '{USB_DEVICE_AND_INTERFACE_INFO(USB_VENDER_ID_REALTEK, 0xb82b, 0xff, 0xff, 0xff), .driver_info = RTL8821C},'
new_entries = target + '\\n\\t{USB_DEVICE_AND_INTERFACE_INFO(0x2c4e, 0x0107, 0xff, 0xff, 0xff), .driver_info = RTL8821C}, /* 2c4e:0107 */\\n\\t{USB_DEVICE(0x2c4e, 0x0107), .driver_info = RTL8821C},'

if '0x2c4e' not in intf_content:
    if target in intf_content:
        intf_content = intf_content.replace(target, new_entries)
        with open(usb_intf_path, 'w') as f:
            f.write(intf_content)
        print("usb_intf.c patched with 2c4e:0107!")
    else:
        print("Target line not found in usb_intf.c")
else:
    print("0x2c4e already in usb_intf.c")

print("=== Step 3: Setting /etc/modprobe.d/8821cu.conf ===")
conf_cmd = "echo 'options 8821cu rtw_power_mgnt=0 rtw_led_ctrl=1' | echo 123 | sudo -S tee /etc/modprobe.d/8821cu.conf"
subprocess.run(conf_cmd, shell=True, check=True)

print("=== Step 4: Unloading current 8821cu module ===")
subprocess.run("echo 123 | sudo -S modprobe -r 8821cu", shell=True, check=False)

print("=== Step 5: Compiling driver ===")
os.chdir('/home/unitree/rtl8821cu_clean')
subprocess.run("make clean", shell=True, check=False)
res = subprocess.run("make -j$(nproc)", shell=True)
if res.returncode != 0:
    print("Compilation failed!")
    exit(1)

print("=== Step 6: Installing driver module ===")
subprocess.run("echo 123 | sudo -S make install", shell=True, check=True)
subprocess.run("echo 123 | sudo -S depmod -a", shell=True, check=True)

print("=== Step 7: Loading patched 8821cu module ===")
subprocess.run("echo 123 | sudo -S modprobe 8821cu", shell=True, check=True)
subprocess.run("echo 123 | sudo -S rfkill unblock wifi", shell=True, check=False)

print("=== Step 8: Checking network interfaces ===")
subprocess.run("ip link", shell=True)
"""
        
        stdin, stdout, stderr = ssh.exec_command("cat << 'EOF' > /tmp/patch_driver.py\n" + remote_script + "\nEOF\npython3 /tmp/patch_driver.py")
        
        while True:
            line = stdout.readline()
            if not line:
                break
            print(line, end='')
        err = stderr.read().decode('utf-8', errors='replace')
        if err:
            print("STDERR:\n", err)

    except Exception as e:
        print(f"SSH Error: {e}")
    finally:
        ssh.close()

if __name__ == '__main__':
    run_remote_python_script()
