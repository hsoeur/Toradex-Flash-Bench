#!/bin/sh

# ═══════════════════════════════════════════════════════
# prepare.sh — Toradex post-flash script
#
# Executed on the board at the end of TEZI image installation.
# 1. Requests a MAC address from the external API
# 2. Validates & injects the MAC via U-Boot env
# 3. Notifies the FlashBench backend for traceability
#    (the backend enriches with operator/order context
#     and forwards to the external traceability API)
# 4. Reboots
# ═══════════════════════════════════════════════════════

API_URL="http://192.168.10.1:10000"
BACKEND_URL="http://192.168.10.1:5001"
LOG_HOST="192.168.10.1"
LOG_PORT="5000"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | nc $LOG_HOST $LOG_PORT
}

# Arguments TEZI
PRODUCT_ID=$1
BOARD_REV=$2
SERIAL=$3
IMAGE_FOLDER=$4

log "START | Serial=$SERIAL | Product=$PRODUCT_ID | Rev=$BOARD_REV"

# =========================
# 1️⃣ DEMANDE MAC
# =========================
MAC_RESPONSE=$(curl -s -m 5 "$API_URL/api/MacAddresses/next-mac")
CURL_EXIT=$?

if [ $CURL_EXIT -ne 0 ]; then
    log "ERROR | API unreachable (next-mac) | Serial=$SERIAL"
    exit 1
fi

MAC_ID=$(echo "$MAC_RESPONSE" | sed -n 's/.*"macId":[ ]*\([0-9]*\).*/\1/p')
CLIENT_MAC=$(echo "$MAC_RESPONSE" | sed -n 's/.*"macAddress":[ ]*"\([^"]*\)".*/\1/p')

if [ -z "$CLIENT_MAC" ] || [ -z "$MAC_ID" ]; then
    log "ERROR | Invalid MAC response | Serial=$SERIAL | Response=$MAC_RESPONSE"
    exit 1
fi

log "MAC_RECEIVED | Id=$MAC_ID | MAC=$CLIENT_MAC"

# =========================
# 2️⃣ VALIDATION MAC
# =========================
echo "$CLIENT_MAC" | grep -Eq '^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$'
if [ $? -ne 0 ]; then
    log "ERROR | Invalid MAC format | Serial=$SERIAL | MAC=$CLIENT_MAC"
    exit 1
fi

# =========================
# 3️⃣ DETECTION INTERFACE
# =========================
IFACE=$(ip route | awk '/default/ {print $5}' | head -n 1)
[ -z "$IFACE" ] && IFACE="eth0"

IP_ADDR=$(ip -4 addr show "$IFACE" | awk '/inet / {print $2}' | cut -d/ -f1)
FACTORY_MAC=$(cat /sys/class/net/$IFACE/address)

log "FACTORY_MAC | $FACTORY_MAC"
log "IP_BEFORE_REBOOT | $IP_ADDR"

# =========================
# 4️⃣ INJECTION
# =========================
fw_setenv ethaddr "$CLIENT_MAC"
if [ $? -ne 0 ]; then
    log "ERROR | fw_setenv failed | Serial=$SERIAL"
    exit 1
fi

WRITTEN_MAC=$(fw_printenv -n ethaddr)
if [ "$WRITTEN_MAC" != "$CLIENT_MAC" ]; then
    log "ERROR | MAC verification failed | Serial=$SERIAL"
    exit 1
fi

log "MAC_INJECTION_OK"

# =========================
# 5️⃣ TRACEABILITY (via FlashBench backend)
# =========================
TRACE_RESPONSE=$(curl -s -m 10 -w "\n%{http_code}" \
  -X POST "$BACKEND_URL/api/traceability/notify" \
  -H "Content-Type: application/json" \
  -d "{
        \"serialNumber\":\"$SERIAL\",
        \"macId\":$MAC_ID,
        \"clientMac\":\"$CLIENT_MAC\",
        \"factoryMac\":\"$FACTORY_MAC\",
        \"ipBeforeReboot\":\"$IP_ADDR\",
        \"boardRevision\":\"$BOARD_REV\",
        \"productId\":\"$PRODUCT_ID\",
        \"imageFolder\":\"$IMAGE_FOLDER\"
      }")

HTTP_CODE=$(echo "$TRACE_RESPONSE" | tail -n 1)
RESPONSE_BODY=$(echo "$TRACE_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    log "ERROR | Traceability failed | Serial=$SERIAL | HTTP=$HTTP_CODE | Response=$RESPONSE_BODY"
    exit 1
fi

log "TRACEABILITY_OK | Serial=$SERIAL"
log "END | Rebooting"

sync
sleep 1
reboot -f
