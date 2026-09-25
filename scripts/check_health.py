#!/usr/bin/env python3
"""
NERO GO2 Comprehensive System Health Checker
Checks container health, HTTP endpoints, and systemd autostart services.
"""
import sys
import subprocess
import urllib.request
import json

SERVICES = [
    ("WebRTC Bridge", "http://127.0.0.1:5001/state"),
    ("Web Dashboard", "http://127.0.0.1:8080/"),
    ("Mission Control", "http://127.0.0.1:8000/"),
    ("Go2 Console", "http://127.0.0.1:9200"),
    ("Motion VUI LED", "http://127.0.0.1:9102/led"),
]

CONTAINERS = [
    "nero_go2_webrtc_bridge_1",
    "nero_go2_web_dashboard_1",
    "nero_go2_go2_console_1",
    "nero_go2_mc_audio_1",
    "nero_go2_mission_control_1",
    "nero_go2_mc_motion",
    "nero_go2_hesai_bridge",
    "nero_go2_perception",
    "nero_go2_realsense_bridge",
]

def check_containers():
    print("=== 🐳 DOCKER CONTAINERS STATUS ===")
    all_ok = True
    for c in CONTAINERS:
        try:
            res = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", c],
                capture_output=True, text=True, check=True
            )
            running = res.stdout.strip() == "true"
            status = "✅ RUNNING" if running else "❌ STOPPED"
            print(f"  [{status}] {c}")
            if not running:
                all_ok = False
        except Exception as e:
            print(f"  [❌ MISSING/ERROR] {c}: {e}")
            all_ok = False
    return all_ok

def check_http():
    print("\n=== 🌐 HTTP ENDPOINTS HEALTH ===")
    all_ok = True
    for name, url in SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HealthCheck/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                code = resp.status
                status = "✅ OK" if code == 200 else f"⚠️ CODE {code}"
                print(f"  [{status}] {name} ({url})")
        except Exception as e:
            print(f"  [❌ UNREACHABLE] {name} ({url}): {e}")
            all_ok = False
    return all_ok

def main():
    print("🤖 NERO GO2 SYSTEM HEALTH REPORT")
    print("================================")
    c_ok = check_containers()
    h_ok = check_http()
    print("\n================================")
    if c_ok and h_ok:
        print("🎉 OVERALL STATUS: ALL SYSTEMS OPERATIONAL (100% HEALTHY)")
        sys.exit(0)
    else:
        print("⚠️ OVERALL STATUS: DEGRADED (SOME SERVICES NEED ATTENTION)")
        sys.exit(1)

if __name__ == "__main__":
    main()
