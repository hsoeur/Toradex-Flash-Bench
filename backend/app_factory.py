"""
app_factory.py — Flask + SocketIO application factory.
"""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from config import SECRET_KEY


def create_app() -> tuple[Flask, SocketIO]:
    """Create and return the Flask app and SocketIO instance."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    CORS(app, resources={r"/*": {"origins": "*"}})

    sio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    return app, sio
