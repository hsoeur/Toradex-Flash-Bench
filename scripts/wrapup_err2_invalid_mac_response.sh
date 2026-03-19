#!/bin/sh
#
# wrapup_err2_invalid_mac_response.sh
# Simule : Invalid MAC response
# L'API répond mais le JSON ne contient pas de MAC valide
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

# ❌ Simule une réponse API vide / invalide
MAC_RESPONSE='{"error":"no rows available"}'
log "ERROR | Invalid MAC response | Serial=$SERIAL | Response=$MAC_RESPONSE"
exit 1
