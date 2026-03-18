from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
from mysql.connector import Error
import logging
from logging.handlers import TimedRotatingFileHandler
import os

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


# =========================
# CONFIG LOGS
# =========================
# CONFIG LOGS
# =========================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _make_api_log_handler() -> TimedRotatingFileHandler:
    from datetime import datetime
    today    = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(LOG_DIR, f"{today}_api.log")
    handler  = TimedRotatingFileHandler(
        filename=filepath,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    def _namer(default_name: str) -> str:
        base, _sep, date_suffix = default_name.rpartition(".")
        log_dir  = os.path.dirname(base)
        basename = os.path.basename(base)
        parts    = basename.split("_", 1)
        pure_stem = parts[1] if len(parts) == 2 else basename
        return os.path.join(log_dir, f"{date_suffix}_{pure_stem}")
    handler.namer = _namer
    return handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[_make_api_log_handler()],
)

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
