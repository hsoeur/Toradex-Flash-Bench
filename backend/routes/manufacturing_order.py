"""
routes/manufacturing_order.py — GET /api/manufacturing-order/<uid>

Validates a manufacturing order UID against the external traceability API.
Returns the order data or a 404/error if not found.
"""

from __future__ import annotations

import logging
import traceback

import requests as http_requests
from flask import Blueprint, jsonify

from config import EXTERNAL_API_URL

logger = logging.getLogger("FlashBench.Routes.ManufacturingOrder")

bp = Blueprint("manufacturing_order", __name__, url_prefix="/api/manufacturing-order")


@bp.get("/<int:uid>")
def get_manufacturing_order(uid: int):
    """
    Fetch and validate a manufacturing order from the external API.
    The UID comes from the barcode scan (e.g. "OF25000" → uid=25000).
    """
    try:
        url = f"{EXTERNAL_API_URL}/api/ManufacturingOrder/by-manufacturing-order-uid"
        resp = http_requests.get(url, params={"manufacturingOrderUid": uid}, timeout=10)

        if resp.status_code == 404:
            return jsonify({"error": f"Ordre de fabrication {uid} introuvable"}), 404

        if not resp.ok:
            logger.warning("External API returned %d for OF %d", resp.status_code, uid)
            return jsonify({"error": f"Erreur API externe ({resp.status_code})"}), 502

        data = resp.json()
        return jsonify(data), 200

    except http_requests.Timeout:
        logger.error("Timeout fetching OF %d from external API", uid)
        return jsonify({"error": "Délai dépassé lors de la validation de l'OF"}), 504

    except Exception:
        logger.error("Error fetching OF %d:\n%s", uid, traceback.format_exc())
        return jsonify({"error": "Erreur interne lors de la validation de l'OF"}), 500
