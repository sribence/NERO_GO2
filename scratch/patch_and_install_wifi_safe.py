import sys
import paramiko

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def run_remote():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print("Connecting to Jetson at 192.168.123.18...")
        ssh.connect('192.168.123.18', username='unitree', password='123', timeout=15)
        
        commands = [
            # 1. Modify Makefile explicitly using sed
            "sed -i 's/CONFIG_POWER_SAVING = y/CONFIG_POWER_SAVING = n/g' /home/unitree/rtl8821cu_clean/Makefile",
            "grep 'CONFIG_POWER_SAVING = n' /home/unitree/rtl8821cu_clean/Makefile",
            
            # 2. Check usb_intf.c patch
            "grep -q '0x2c4e' /home/unitree/rtl8821cu_clean/os_dep/linux/usb_intf.c || sed -i '/USB_DEVICE_AND_INTERFACE_INFO.*b82b/a \\t{USB_DEVICE_AND_INTERFACE_INFO(0x2c4e, 0x0107, 0xff, 0xff, 0xff), .driver_info = RTL8821C},\\n\\t{USB_DEVICE(0x2c4e, 0x0107), .driver_info = RTL8821C},' /home/unitree/rtl8821cu_clean/os_dep/linux/usb_intf.c",
            
            # 3. Create modprobe config
            "echo 123 | sudo -S sh -c 'echo \"options 8821cu rtw_power_mgnt=0 rtw_led_ctrl=1\" > /etc/modprobe.d/8821cu.conf'",
            
            # 4. Rebuild driver
            "cd /home/unitree/rtl8821cu_clean && make clean && make -j$(nproc)",
            
            # 5. Install & depmod
            "cd /home/unitree/rtl8821cu_clean && echo 123 | sudo -S make install && echo 123 | sudo -S depmod -a",
            
            # 6. Load module
            "echo 123 | sudo -S modprobe 8821cu",
            "echo 123 | sudo -S rfkill unblock wifi",
            "sleep 2",
            "ip link show wlan0"
        ]
        
        full_cmd = " && ".join(commands)
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        
        print("=== STDOUT ===")
        print(out)
        if err:
            print("=== STDERR ===")
            print(err)

    except Exception as e:
        print(f"SSH Connection Failed: {e}")
    finally:
        ssh.close()

if __name__ == '__main__':
    run_remote()
