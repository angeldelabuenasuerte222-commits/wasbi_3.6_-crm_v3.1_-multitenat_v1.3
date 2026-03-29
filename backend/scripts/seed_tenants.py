#!/usr/bin/env python
"""
Seed script that migrates the legacy in-memory client configs into Mongo tenants.

Usage:
  SEED_PASSWORD_CAFE_MINIMA=Pass123! python backend/scripts/seed_tenants.py
  SEED_PASSWORDS_FILE=backend/scripts/seed_passwords.json python backend/scripts/seed_tenants.py

Required env:
  MONGO_URL

Optional env:
  DB_NAME
  SEED_PASSWORD_<SLUG_UPPER>
  SEED_PASSWORDS_FILE

The script is idempotent: it will not duplicate slugs that already exist in the tenants collection.
Legacy configurations without a provided password will be skipped so you can review them manually.
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(BACKEND_DIR / ".env")

from backend.legacy_configs import CLIENT_CONFIGS, DEFAULT_SLUG  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("seed-tenants")
crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "whasabi_db")
PASSWORDS_FILE = os.environ.get("SEED_PASSWORDS_FILE")


def _load_passwords_from_file() -> Dict[str, str]:
    if not PASSWORDS_FILE:
        return {}

    passwords_path = Path(PASSWORDS_FILE)
    if not passwords_path.is_absolute():
        passwords_path = PROJECT_ROOT / passwords_path

    try:
        raw_data = json.loads(passwords_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("password file not found path=%s", passwords_path)
        return {}
    except json.JSONDecodeError as exc:
        logger.warning("password file is not valid json path=%s error=%s", passwords_path, exc)
        return {}

    if not isinstance(raw_data, dict):
        logger.warning("password file must be a JSON object path=%s", passwords_path)
        return {}

    return {
        str(slug).strip().lower(): str(password)
        for slug, password in raw_data.items()
        if str(slug).strip() and str(password).strip()
    }


PASSWORDS_BY_FILE = _load_passwords_from_file()


def _slug_to_env_name(slug: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_")
    return f"SEED_PASSWORD_{normalized}"


def _password_for_slug(slug: str) -> Optional[str]:
    file_password = PASSWORDS_BY_FILE.get(slug)
    if file_password:
        return file_password

    env_name = _slug_to_env_name(slug)
    password = os.environ.get(env_name)
    if password:
        return password

    return None


async def _tenant_exists(db, slug: str) -> bool:
    existing = await db.tenants.find_one({"slug": slug}, {"_id": 1})
    return existing is not None


def _build_tenant_doc(slug: str, config: Dict[str, str], password: str) -> Dict[str, object]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "slug": slug,
        "business_name": config.get("business_name", "Negocio"),
        "system_prompt": config.get("system_prompt", ""),
        "phone": config.get("phone", ""),
        "hours": config.get("hours", ""),
        "address": config.get("address", ""),
        "avatar": config.get("avatar", ""),
        "image": config.get("image", ""),
        "greeting": config.get("greeting", ""),
        "is_active": True,
        "admin_config": {"password_hash": crypt_context.hash(password)},
        "created_at": timestamp,
        "updated_at": timestamp,
    }


async def seed_tenants(db) -> None:
    await db.tenants.create_index("slug", unique=True)

    for slug, config in CLIENT_CONFIGS.items():
        if slug == DEFAULT_SLUG:
            logger.info("tenant skipped slug=%s reason=default fallback (legacy only)", slug)
            continue

        if await _tenant_exists(db, slug):
            logger.info("tenant already exists slug=%s", slug)
            continue

        password = _password_for_slug(slug)
        if not password:
            logger.warning(
                "tenant skipped slug=%s reason=missing password source expected_env=%s",
                slug,
                _slug_to_env_name(slug),
            )
            continue

        tenant_doc = _build_tenant_doc(slug, config, password)

        try:
            await db.tenants.insert_one(tenant_doc)
            logger.info("tenant created slug=%s", slug)
        except Exception as exc:
            logger.exception("error creating tenant slug=%s msg=%s", slug, exc)


async def main() -> None:
    if not MONGO_URL:
        raise SystemExit("Error: MONGO_URL environment variable is required to seed tenants.")

    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await seed_tenants(client[DB_NAME])
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
