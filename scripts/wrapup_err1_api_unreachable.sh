#!/bin/sh
#
# wrapup_err1_api_unreachable.sh
# Simule : API unreachable (next-mac)
# L'API MAC n'est pas joignable → erreur immédiate après START
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

# ❌ Simule un curl qui échoue (API injoignable)
log "ERROR | API unreachable (next-mac) | Serial=$SERIAL"
exit 1
