#!/bin/sh
#
# wrapup_err6_traceability_failed.sh
# Simule : Traceability failed
# Tout est OK jusqu'à l'appel traçabilité qui retourne une erreur HTTP
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

# ✅ Injection OK
log "MAC_INJECTION_OK"

sleep 0.5

# ❌ Traçabilité échoue (502 de l'API externe)
log "ERROR | Traceability failed | Serial=$SERIAL | HTTP=502 | Response={\"error\":\"External traceability API unreachable\"}"
exit 1
