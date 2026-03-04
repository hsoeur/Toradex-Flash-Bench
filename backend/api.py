from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import mysql.connector
from mysql.connector import Error
import logging
from logging.handlers import TimedRotatingFileHandler
import os

app = FastAPI()


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


# =========================
# CONFIG LOGS
# =========================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

log_handler = TimedRotatingFileHandler(
    filename=f"{LOG_DIR}/api.log",
    when="midnight",
    interval=1,
    backupCount=30
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[log_handler]
)

logger = logging.getLogger(__name__)

# =========================
# CONFIG DB
# =========================
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3307,
    "user": "macuser",
    "password": "macpassword",
    "database": "mac_database"
}

# =========================
# GET NEXT MAC
# =========================
@app.get("/next-mac")
def get_next_mac():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT Id, MacAddress
            FROM MacAddresses
            WHERE Status = 'AVAILABLE'
            LIMIT 1
        """)

        mac = cursor.fetchone()

        if not mac:
            logger.warning("No MAC available")
            raise HTTPException(status_code=404, detail="No MAC available")

        logger.info(f"MAC requested -> Id={mac['Id']} Address={mac['MacAddress']}")

        return {
            "macId": mac["Id"],
            "macAddress": mac["MacAddress"]
        }

    except Error as e:
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

        if mac["Status"] != "AVAILABLE":
            conn.rollback()
            logger.warning(f"MAC Id={data.macId} already used")
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
