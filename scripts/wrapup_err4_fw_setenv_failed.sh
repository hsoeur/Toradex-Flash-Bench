#!/bin/sh
#
# wrapup_err4_fw_setenv_failed.sh
# Simule : fw_setenv failed
# La MAC est valide mais l'écriture U-Boot échoue
#

BACKEND_URL="http://192.168.10.1:5001"
LOG_HOST="192.168.10.1"
LOG_PORT="5000"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | nc $LOG_HOST $LOG_PORT
}

PRODUCT_ID=$1
BOARD_REV=$2
SERIAL=$3
IMAGE_FOLDER=$4

IFACE=$(ip route | awk '/default/ {print $5}' | head -n 1)
[ -z "$IFACE" ] && IFACE="eth0"
IP_ADDR=$(ip -4 addr show "$IFACE" | awk '/inet / {print $2}' | cut -d/ -f1)
FACTORY_MAC=$(cat /sys/class/net/$IFACE/address)

log "START | Serial=$SERIAL | Product=$PRODUCT_ID | Rev=$BOARD_REV"

sleep 1

# ✅ MAC reçue OK
CLIENT_MAC="00:14:2D:AA:BB:CC"
log "MAC_RECEIVED | Id=42 | MAC=$CLIENT_MAC"

sleep 0.5

log "FACTORY_MAC | $FACTORY_MAC"
log "IP_BEFORE_REBOOT | $IP_ADDR"

sleep 0.5

# ❌ fw_setenv échoue
log "ERROR | fw_setenv failed | Serial=$SERIAL"
exit 1
