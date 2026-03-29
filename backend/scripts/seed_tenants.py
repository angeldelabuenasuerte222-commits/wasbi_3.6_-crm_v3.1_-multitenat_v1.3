#!/usr/bin/env python
"""
Seed script that migrates the legacy in-memory client configs into Mongo tenants.

Usage:
  SEED_PASSWORD_CAFE_MINIMA=Pass123! SEED_PASSWORD_DENTISTA_LOPEZ=Pass123! python backend/scripts/seed_tenants.py

The script is idempotent: it will not duplicate slugs that already exist in the tenants collection.
Legacy configurations without a provided password will be skipped so you can review them manually.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from passlib.context import CryptContext

from backend.server import CLIENT_CONFIGS, db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("seed-tenants")
crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

PASSWORD_ENV_MAP = {
    "cafe-minima": "SEED_PASSWORD_CAFE_MINIMA",
    "dentista-lopez": "SEED_PASSWORD_DENTISTA_LOPEZ",
    # Add more slugs here if needed
}


def _password_for_slug(slug: str) -> str | None:
    env_name = PASSWORD_ENV_MAP.get(slug)
    if env_name:
        return os.environ.get(env_name)
    return None


async def _tenant_exists(slug: str) -> bool:
    existing = await db.tenants.find_one({"slug": slug}, {"_id": 1})
    return existing is not None


async def seed_tenants():
    await db.tenants.create_index("slug", unique=True)

    for slug, config in CLIENT_CONFIGS.items():
        if slug == "default":
            logger.info("tenant skipped slug=%s reason=default fallback (legacy only)", slug)
            continue

        if await _tenant_exists(slug):
            logger.info("tenant already exists slug=%s", slug)
            continue

        password = _password_for_slug(slug)
        if not password:
            logger.warning("tenant skipped slug=%s reason=missing password env", slug)
            continue

        password_hash = crypt_context.hash(password)
        tenant_doc = {
            "slug": slug,
            "business_name": config.get("business_name", "Negocio"),
            "system_prompt": config.get("system_prompt", ""),
            "phone": config.get("phone", ""),
            "hours": config.get("hours", ""),
            "address": config.get("address", ""),
            "avatar": config.get("avatar", ""),
            "image": config.get("image", ""),
            "greeting": config.get("greeting", ""),
            "admin_config": {"password_hash": password_hash},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await db.tenants.insert_one(tenant_doc)
            logger.info("tenant created slug=%s", slug)
        except Exception as exc:
            logger.exception("error creating tenant slug=%s msg=%s", slug, exc)

    await db.client.close()


if __name__ == "__main__":
    asyncio.run(seed_tenants())
