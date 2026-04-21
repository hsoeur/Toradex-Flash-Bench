"""
routes/traceability.py — POST /api/traceability/notify
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone

import requests as http_requests
from flask import Blueprint, jsonify, request as flask_request

from config import (
    EXTERNAL_API_URL,
    MACHINE_UID,
    OPERATION_NUMBER,
    PRODUCT_UID,
    TRACE_LABEL,
    TRACE_LABEL_IMAGE,
    UNIT_UID,
)
from session import get as get_session
import image_service

logger = logging.getLogger("FlashBench.Routes.Traceability")

bp = Blueprint("traceability", __name__, url_prefix="/api/traceability")

# Injected at startup via init()
_module_store = None  # type: ignore[assignment]


def init(module_store) -> None:  # noqa: ANN001
    """Inject runtime dependencies (called once at startup)."""
    global _module_store
    _module_store = module_store


@bp.post("/notify")
def notify():
    """
    Called by the on-board script after MAC injection.
    Enriches board data with the session context and forwards the
    traceability record to the external API.
    """
    try:
        body = flask_request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    required = ["serialNumber", "macId", "clientMac", "factoryMac", "imageFolder"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    ctx = get_session()
    if not ctx["operatorId"] or not ctx["orderNumber"]:
        logger.warning("Session context incomplete: %s", ctx)
        return jsonify({
            "error": "Session context incomplete — no operator/order set on the dashboard"
        }), 400

    creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    trace_payload = {
        "productUid":            PRODUCT_UID,
        "serialNumber":          int(body["serialNumber"]),
        "label":                 TRACE_LABEL,
        "value":                 body["clientMac"],
        "classification":        "OK",
        "creationDate":          creation_date,
        "operationNumber":       OPERATION_NUMBER,
        "unitUid":               UNIT_UID,
        "userUid":               ctx["operatorId"],
        "machineUid":            MACHINE_UID,
        "manufacturingOrderUid": int(ctx["orderNumber"]),
    }

    ext_url = f"{EXTERNAL_API_URL}/api/MeasurementTraceability/create-with-mac"
    logger.info(
        "Notify | serial=%s | MAC=%s | operator=%s | order=%s",
        body["serialNumber"], body["clientMac"],
        ctx["operatorId"], ctx["orderNumber"],
    )
    logger.debug("Request | URL=%s | payload=%s", ext_url, json.dumps(trace_payload, indent=2))

    try:
        resp = http_requests.post(
            ext_url,
            json=trace_payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=10,
        )
    except http_requests.RequestException as exc:
        logger.error("External API unreachable: %s", exc)
        return jsonify({"error": "External traceability API unreachable", "detail": str(exc)}), 502

    if resp.status_code != 200:
        logger.error("External API | HTTP %d | %s", resp.status_code, resp.text)
        return jsonify({
            "error":    "External traceability API returned an error",
            "httpCode": resp.status_code,
            "detail":   resp.text,
        }), 502

    # ── Second traceability record: Linux image name ──────────
    try:
        all_images = image_service.get_all_images()
        active_img = next((img for img in all_images if img["autoinstall"]), None)
        if active_img:
            img_name    = active_img["name"]
            img_version = active_img["version"]
            img_date    = active_img["release_date"]
            image_value = f"{img_name}_{img_version}_{img_date}"
        else:
            logger.warning("No active image found (autoinstall=true) — falling back to imageFolder")
            image_value = body.get("imageFolder", "unknown")
    except Exception as exc:
        logger.warning("Cannot read image list: %s — falling back to imageFolder", exc)
        image_value = body.get("imageFolder", "unknown")

    image_payload = {
        "productUid":            PRODUCT_UID,
        "serialNumber":          int(body["serialNumber"]),
        "label":                 TRACE_LABEL_IMAGE,
        "value":                 image_value,
        "classification":        "OK",
        "creationDate":          creation_date,
        "operationNumber":       OPERATION_NUMBER,
        "unitUid":               UNIT_UID,
        "userUid":               ctx["operatorId"],
        "machineUid":            MACHINE_UID,
        "manufacturingOrderUid": int(ctx["orderNumber"]),
    }

    ext_url_image = f"{EXTERNAL_API_URL}/api/MeasurementTraceability/create"
    logger.info(
        "Notify IMAGE | serial=%s | image=%s | operator=%s | order=%s",
        body["serialNumber"], body["imageFolder"],
        ctx["operatorId"], ctx["orderNumber"],
    )
    logger.debug("Request IMAGE | URL=%s | payload=%s", ext_url_image, json.dumps(image_payload, indent=2))

    try:
        resp_img = http_requests.post(
            ext_url_image,
            json=image_payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=10,
        )
    except http_requests.RequestException as exc:
        logger.error("External API unreachable (image trace): %s", exc)
        return jsonify({"error": "External traceability API unreachable (image)", "detail": str(exc)}), 502

    if resp_img.status_code != 200:
        logger.error("External API IMAGE | HTTP %d | %s", resp_img.status_code, resp_img.text)
        return jsonify({
            "error":    "External traceability API returned an error (image)",
            "httpCode": resp_img.status_code,
            "detail":   resp_img.text,
        }), 502

    logger.info("OK IMAGE | serial=%s | image=%s", body["serialNumber"], body["imageFolder"])

    board_ip = flask_request.remote_addr
    _module_store.mark_done(board_ip)

    logger.info("OK | serial=%s | MAC=%s | ip=%s", body["serialNumber"], body["clientMac"], board_ip)
    return jsonify({"ok": True, "message": "Traceability recorded (MAC + image)"})
