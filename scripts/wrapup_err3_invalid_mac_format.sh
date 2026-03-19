#!/bin/sh
#
# wrapup_err3_invalid_mac_format.sh
# Simule : Invalid MAC format
# L'API retourne une MAC mais son format est invalide
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

log "START | Serial=$SERIAL | Product=$PRODUCT_ID | Rev=$BOARD_REV"

sleep 1

# ✅ MAC reçue (mais format pourri)
CLIENT_MAC="ZZZZ-invalid-mac"
log "MAC_RECEIVED | Id=42 | MAC=$CLIENT_MAC"

sleep 0.5

# ❌ Validation regex échoue
log "ERROR | Invalid MAC format | Serial=$SERIAL | MAC=$CLIENT_MAC"
exit 1
