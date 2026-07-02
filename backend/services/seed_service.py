from __future__ import annotations

import logging

from backend.config import Config
from backend.services.auth_service import AuthService, ROLE_ADMIN


logger = logging.getLogger(__name__)


def seed_admin_user(config: Config) -> None:
    if not config.admin_username or not config.admin_password:
        logger.warning(
            "ADMIN_USERNAME and ADMIN_PASSWORD are not both set; skipping admin seed."
        )
        return

    auth_service = AuthService(
        db_path=config.sqlite_db_path,
        token_ttl_hours=config.token_ttl_hours,
    )
    existing_user = auth_service.get_user_by_username(config.admin_username)
    if existing_user is not None:
        logger.info("Admin seed user already exists; skipping seed.")
        return

    auth_service.create_user(
        username=config.admin_username,
        password=config.admin_password,
        role=ROLE_ADMIN,
    )
    logger.info("Seeded initial admin user from environment.")
