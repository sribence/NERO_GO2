#!/usr/bin/env bash
# NERO GO2 System Auto-Healing Watchdog
# Runs periodically via systemd timer to ensure zero downtime.

LOG_FILE="/var/log/nero_watchdog.log"
COMPOSE_DIR="/home/unitree/NERO_GO2"

REQUIRED_CONTAINERS=(
    "nero_go2_webrtc_bridge_1"
    "nero_go2_web_dashboard_1"
    "nero_go2_go2_console_1"
    "nero_go2_mc_audio_1"
    "nero_go2_mission_control_1"
    "nero_go2_mc_motion"
    "nero_go2_hesai_bridge"
    "nero_go2_perception"
)

timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

log() {
    echo "[$(timestamp)] $1" >> "$LOG_FILE"
}

RECOVER_NEEDED=0

for container in "${REQUIRED_CONTAINERS[@]}"; do
    STATUS=$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null)
    if [ "$STATUS" != "true" ]; then
        log "WARNING: Container '$container' is not running (State: $STATUS)."
        RECOVER_NEEDED=1
    fi
done

if [ "$RECOVER_NEEDED" -eq 1 ]; then
    log "ACTION: Triggering auto-recovery..."
    cd "$COMPOSE_DIR" || exit 1
    docker-compose up -d --no-build >> "$LOG_FILE" 2>&1

    # Ensure individual stopped containers are started
    for container in "${REQUIRED_CONTAINERS[@]}"; do
        STATUS=$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null)
        if [ "$STATUS" != "true" ]; then
            log "ACTION: Forcing start of '$container'..."
            docker start "$container" >> "$LOG_FILE" 2>&1
        fi
    done
    log "INFO: Auto-recovery completed."
fi
