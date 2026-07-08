from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from flask import Flask, jsonify


if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.api.admin_routes import admin_bp
from backend.api.auth_routes import auth_bp
from backend.api.chat_routes import chat_bp
from backend.api.contract_routes import contracts_bp
from backend.config import Config
from backend.models.database import init_db
from backend.services.seed_service import seed_admin_user


def create_app(config: Config | None = None) -> Flask:
    logging.basicConfig(level=logging.INFO)
    app_config = config or Config.from_env()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = app_config.flask_secret_key
    app.config["APP_CONFIG"] = app_config

    init_db(app_config.sqlite_db_path)
    seed_admin_user(app_config)

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(contracts_bp)

    @app.get("/api/v1/health")
    def health_check():
        return jsonify(
            {
                "status": "ok",
                "app_env": app_config.app_env,
                "sqlite_db_path": app_config.sqlite_db_path,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    flask_debug = os.getenv("FLASK_DEBUG", "0").strip().lower()
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=flask_debug in {"1", "true", "yes", "on"},
    )
