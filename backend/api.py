from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
from mysql.connector import Error
import logging
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# HEALTH
# =========================
@app.get("/health")
def health():
    db_ok = False
    db_error: str | None = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            conn.close()
            db_ok = True
    except Error as e:
        db_error = str(e)

    body = {"status": "ok" if db_ok else "degraded", "db": "connected" if db_ok else "disconnected"}
    if db_error:
        body["db_error"] = db_error

    if not db_ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=body)

    return body


logger = logging.getLogger(__name__)

# =========================
# CONFIG DB
# =========================
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "user",
    "password": "user",
    "database": "db_production"
}

# =========================
# MAC ADDRESS GENERATION
# =========================
# OUI prefix (first 3 bytes). Change to your assigned prefix.
MAC_PREFIX = "14:2D:F5"
# First address to generate when the table is empty
MAC_START  = "14:2D:F5:00:3B:5B"


def _mac_to_int(mac: str) -> int:
    """Convert a MAC string 'AA:BB:CC:DD:EE:FF' to a 48-bit integer."""
    return int(mac.replace(":", ""), 16)


def _int_to_mac(val: int) -> str:
    """Convert a 48-bit integer back to a MAC string 'AA:BB:CC:DD:EE:FF'."""
    hex_str = f"{val:012X}"
    return ":".join(hex_str[i:i+2] for i in range(0, 12, 2))


# =========================
# GET NEXT MAC (generated on-the-fly)
# =========================
@app.get("/next-mac")
def get_next_mac():
    """
    Generate the next MAC address sequentially.
    - If the table is empty, start from MAC_START.
    - Otherwise increment the highest existing MAC by 1.
    - INSERT the new MAC as RESERVED and return it.
    No pre-filled pool required.
    """
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        conn.start_transaction()

        # Find the highest MAC already in the table
        cursor.execute("""
            SELECT MacAddress
            FROM MacAddresses
            ORDER BY Id DESC
            LIMIT 1
            FOR UPDATE
        """)
        row = cursor.fetchone()

        if row:
            last_int = _mac_to_int(row["MacAddress"])
            next_int = last_int + 1
        else:
            next_int = _mac_to_int(MAC_START)

        new_mac = _int_to_mac(next_int)

        # Validate the prefix is still correct (overflow protection)
        if not new_mac.startswith(MAC_PREFIX):
            conn.rollback()
            logger.error(f"MAC range exhausted: {new_mac} no longer matches prefix {MAC_PREFIX}")
            raise HTTPException(status_code=500, detail="MAC address range exhausted")

        # Insert the newly generated MAC
        cursor.execute("""
            INSERT INTO MacAddresses (MacAddress, Status, ReservedAt, CreatedAt)
            VALUES (%s, 'RESERVED', NOW(), NOW())
        """, (new_mac,))

        mac_id = cursor.lastrowid
        conn.commit()

        logger.info(f"MAC generated -> Id={mac_id} Address={new_mac}")

        return {
            "macId": mac_id,
            "macAddress": new_mac
        }

    except Error as e:
        if 'conn' in locals():
            conn.rollback()
        logger.error(f"Database error in /next-mac: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()


# =========================
# PROGRAM BOARD
# =========================
class ProgrammedBoardRequest(BaseModel):
    serialNumber: str
    productId: str
    boardRevision: str
    factoryMac: str
    macId: int
    productionOrder: str
    operatorId: str
    imageFolder: str
    ipBeforeReboot: str
    status: str


@app.post("/programmed-board")
def save_programmed_board(data: ProgrammedBoardRequest):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        conn.start_transaction()

        cursor.execute("""
            SELECT MacAddress, Status
            FROM MacAddresses
            WHERE Id = %s
            FOR UPDATE
        """, (data.macId,))

        mac = cursor.fetchone()

        if not mac:
            conn.rollback()
            logger.warning(f"MAC Id={data.macId} not found")
            raise HTTPException(status_code=404, detail="MAC not found")

        if mac["Status"] not in ("AVAILABLE", "RESERVED"):
            conn.rollback()
            logger.warning(f"MAC Id={data.macId} already used (status={mac['Status']})")
            raise HTTPException(status_code=400, detail="MAC already used")

        client_mac = mac["MacAddress"]

        cursor.execute("""
            UPDATE MacAddresses
            SET Status = 'USED',
                UsedAt = NOW()
            WHERE Id = %s
        """, (data.macId,))

        cursor.execute("""
            INSERT INTO ProgrammedBoards (
                SerialNumber,
                ProductId,
                BoardRevision,
                FactoryMac,
                ClientMac,
                MacAddressId,
                ProductionOrder,
                OperatorId,
                ImageFolder,
                IpBeforeReboot,
                ProgrammingStatus
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.serialNumber,
            data.productId,
            data.boardRevision,
            data.factoryMac,
            client_mac,
            data.macId,
            data.productionOrder,
            data.operatorId,
            data.imageFolder,
            data.ipBeforeReboot,
            data.status
        ))

        conn.commit()

        logger.info(
            f"Board programmed SUCCESS | SN={data.serialNumber} | MAC={client_mac} | OF={data.productionOrder}"
        )

        return {
            "message": "Board programmed",
            "clientMac": client_mac
        }

    except Error as e:
        conn.rollback()
        logger.error(f"Database error in /programmed-board: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()


# =========================
# LIST TODAY'S BOARDS
# =========================
@app.get("/programmed-boards/today")
def get_today_boards():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                Id,
                SerialNumber,
                ProductId,
                BoardRevision,
                FactoryMac,
                ClientMac,
                ProductionOrder,
                OperatorId,
                ImageFolder,
                IpBeforeReboot,
                ProgrammingStatus,
                ProgrammedAt
            FROM ProgrammedBoards
            WHERE DATE(ProgrammedAt) = CURDATE()
            ORDER BY ProgrammedAt DESC
        """)

        boards = cursor.fetchall()

        logger.info(f"Today's boards requested -> count={len(boards)}")

        return {
            "date": __import__("datetime").date.today().isoformat(),
            "count": len(boards),
            "boards": boards
        }

    except Error as e:
        logger.error(f"Database error in /programmed-boards/today: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
