import logging
import os
import re
import secrets
import time
from enum import Enum
from datetime import datetime, timezone
import sys # Import sys for SystemExit
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from bson import ObjectId
from passlib.context import CryptContext

try:
    from backend.legacy_configs import CLIENT_CONFIGS, DEFAULT_SLUG, DEMO_SLUGS
except ModuleNotFoundError:
    from legacy_configs import CLIENT_CONFIGS, DEFAULT_SLUG, DEMO_SLUGS

# Setup Logging - Clean, Production Ready
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("whasabi")

# Load Env Vars
ROOT_DIR = Path(__file__).resolve().parent # Use .resolve() for robustness
load_dotenv(ROOT_DIR / '.env')

# Environment variables - Make critical ones mandatory
# ---------------------------------------------------

# MONGO_URL (Critical)
MONGO_URL = os.environ.get('MONGO_URL')
if not MONGO_URL:
    logger.critical("Environment variable MONGO_URL is not set. This is critical for database connection.")
    sys.exit("Error: MONGO_URL environment variable is not set. Please configure your MongoDB connection string.")

# DB_NAME (Default is acceptable for now, not a security risk)
DB_NAME = os.environ.get('DB_NAME', 'whasabi_db')

# DEEPSEEK_API_KEY (Critical)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    logger.critical("Environment variable DEEPSEEK_API_KEY is not set. The AI chat functionality will not work.")
    sys.exit("Error: DEEPSEEK_API_KEY environment variable is not set. Please provide your DeepSeek API key.")

# CORS_ORIGINS (Critical for security, must be explicitly set)
CORS_ORIGINS_RAW = os.environ.get('CORS_ORIGINS')
if not CORS_ORIGINS_RAW:
    logger.critical("Environment variable CORS_ORIGINS is not set. This is critical for security.")
    sys.exit("Error: CORS_ORIGINS environment variable is not set. Please specify allowed origins (e.g., 'http://localhost:3000,https://your-frontend.com') or '*' for development (use with caution).")
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS_RAW.split(',') if origin.strip()]

# PORT (Default is acceptable and Render compatible)
PORT = int(os.environ.get('PORT', 8001))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    logger.critical("Environment variable ADMIN_PASSWORD is not set. This is critical for CRM access security.")
    sys.exit("Error: ADMIN_PASSWORD environment variable is not set. Please set a strong password for CRM access.")

crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


def _parse_bool_env_flag(key: str, default: bool) -> bool:
    raw_value = os.environ.get(key)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int_env_flag(key: str, default: int) -> int:
    raw_value = os.environ.get(key)
    if raw_value is None:
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Using default=%d", key, raw_value, default)
        return default
    if parsed_value <= 0:
        logger.warning("Non-positive integer for %s=%r. Using default=%d", key, raw_value, default)
        return default
    return parsed_value


LEGACY_FALLBACK_ENABLED = _parse_bool_env_flag("LEGACY_FALLBACK_ENABLED", True)
RATE_LIMIT_WINDOW_SECONDS = _parse_int_env_flag("RATE_LIMIT_WINDOW_SECONDS", 60)
CHAT_RATE_LIMIT_PER_WINDOW = _parse_int_env_flag("CHAT_RATE_LIMIT_PER_WINDOW", 30)
AUTH_RATE_LIMIT_PER_WINDOW = _parse_int_env_flag("AUTH_RATE_LIMIT_PER_WINDOW", 5)
rate_limit_events: Dict[str, list[float]] = {}


def _log_migration_event(
    endpoint: str,
    slug: Optional[str],
    source: str,
    legacy_auth: Optional[bool] = None,
    **extra_fields: Any
) -> None:
    slug_tag = _format_slug_for_log(slug)
    components = [
        f"endpoint={endpoint}",
        f"slug={slug_tag}",
        f"source={source}"
    ]
    if legacy_auth is not None:
        components.append(f"legacy_auth={'true' if legacy_auth else 'false'}")
    for key, value in extra_fields.items():
        components.append(f"{key}={value}")
    logger.info(" ".join(components))


def normalize_slug(value: str) -> str:
    return value.strip().lower()


def ensure_valid_slug(value: str) -> str:
    normalized = normalize_slug(value)
    if not normalized or not SLUG_PATTERN.match(normalized):
        raise HTTPException(status_code=400, detail="El slug debe tener solo minúsculas, números y guiones.")
    return normalized

def _format_slug_for_log(slug: Optional[str]) -> str:
    return slug if slug else "None"


def get_default_system_prompt() -> str:
    return CLIENT_CONFIGS[DEFAULT_SLUG]["system_prompt"]


def _matches_global_admin_password(provided_password: Optional[str]) -> bool:
    return bool(provided_password) and secrets.compare_digest(provided_password, ADMIN_PASSWORD)


def _is_tenant_active(tenant: Dict[str, Any]) -> bool:
    return tenant.get("is_active", True)


def _get_request_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop

    client_host = getattr(request.client, "host", None)
    return client_host or "unknown"


def _prune_rate_limit_bucket(bucket_key: str, now: Optional[float] = None) -> list[float]:
    current_time = now if now is not None else time.monotonic()
    window_start = current_time - RATE_LIMIT_WINDOW_SECONDS
    recent_events = [event_ts for event_ts in rate_limit_events.get(bucket_key, []) if event_ts > window_start]
    if recent_events:
        rate_limit_events[bucket_key] = recent_events
    else:
        rate_limit_events.pop(bucket_key, None)
    return recent_events


def _raise_rate_limit(detail: str, retry_after_seconds: int) -> None:
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(max(retry_after_seconds, 1))},
    )


def _get_rate_limit_retry_after(bucket_key: str, limit: int) -> Optional[int]:
    recent_events = _prune_rate_limit_bucket(bucket_key)
    if len(recent_events) < limit:
        return None

    oldest_relevant_event = recent_events[0]
    elapsed = time.monotonic() - oldest_relevant_event
    return max(int(RATE_LIMIT_WINDOW_SECONDS - elapsed) + 1, 1)


def _log_rate_limit_event(
    endpoint: str,
    slug: Optional[str],
    scope: str,
    request: Optional[Request],
    limit: int,
    retry_after_seconds: int,
) -> None:
    _log_migration_event(
        endpoint,
        slug,
        "RATE_LIMIT",
        scope=scope,
        ip=_get_request_ip(request),
        limit=limit,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        retry_after_seconds=retry_after_seconds,
    )


def _enforce_rate_limit(
    *,
    bucket_key: str,
    limit: int,
    detail: str,
    endpoint: str,
    slug: Optional[str],
    scope: str,
    request: Optional[Request],
) -> None:
    retry_after_seconds = _get_rate_limit_retry_after(bucket_key, limit)
    if retry_after_seconds is None:
        return

    _log_rate_limit_event(
        endpoint=endpoint,
        slug=slug,
        scope=scope,
        request=request,
        limit=limit,
        retry_after_seconds=retry_after_seconds,
    )
    _raise_rate_limit(detail, retry_after_seconds)


def _record_rate_limit_event(bucket_key: str) -> None:
    recent_events = _prune_rate_limit_bucket(bucket_key)
    recent_events.append(time.monotonic())
    rate_limit_events[bucket_key] = recent_events


def _clear_rate_limit_bucket(bucket_key: str) -> None:
    rate_limit_events.pop(bucket_key, None)


def _auth_rate_limit_key(slug: Optional[str], request: Optional[Request], scope: str) -> str:
    normalized_slug = normalize_slug(slug) if slug else "-"
    return f"auth:{scope}:{normalized_slug}:{_get_request_ip(request)}"


def _enforce_auth_rate_limit(slug: Optional[str], request: Optional[Request], scope: str) -> str:
    bucket_key = _auth_rate_limit_key(slug, request, scope)
    endpoint = "internal_admin_auth" if scope == "internal" else "tenant_admin_auth"
    _enforce_rate_limit(
        bucket_key=bucket_key,
        limit=AUTH_RATE_LIMIT_PER_WINDOW,
        detail="Demasiados intentos de autenticaci?n. Intenta de nuevo en un momento.",
        endpoint=endpoint,
        slug=slug,
        scope=scope,
        request=request,
    )
    return bucket_key


def _chat_rate_limit_key(slug: Optional[str], request: Optional[Request]) -> str:
    normalized_slug = normalize_slug(slug) if slug else DEFAULT_SLUG
    return f"chat:{normalized_slug}:{_get_request_ip(request)}"


async def verify_tenant_admin_password(
    slug: Optional[str],
    provided_password: Optional[str],
    request: Optional[Request] = None,
) -> None:
    auth_bucket_key = _enforce_auth_rate_limit(slug, request, "tenant")

    if not provided_password:
        _record_rate_limit_event(auth_bucket_key)
        _log_migration_event(
            "tenant_admin_auth",
            slug,
            "LEGACY_GLOBAL",
            legacy_auth=False,
            reason="missing_password"
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    if slug:
        tenant = await get_tenant_by_slug(slug)
        if tenant:
            if not _is_tenant_active(tenant):
                _record_rate_limit_event(auth_bucket_key)
                _log_migration_event(
                    "tenant_admin_auth",
                    slug,
                    "MONGO",
                    legacy_auth=False,
                    result="failure",
                    reason="inactive_tenant"
                )
                raise HTTPException(status_code=401, detail="Unauthorized")
            admin_config = tenant.get("admin_config", {})
            password_hash = admin_config.get("password_hash")
            if password_hash:
                if crypt_context.verify(provided_password, password_hash):
                    _clear_rate_limit_bucket(auth_bucket_key)
                    _log_migration_event(
                        "tenant_admin_auth",
                        slug,
                        "MONGO",
                        legacy_auth=False,
                        result="success"
                    )
                    return
                _record_rate_limit_event(auth_bucket_key)
                _log_migration_event(
                    "tenant_admin_auth",
                    slug,
                    "MONGO",
                    legacy_auth=False,
                    result="failure",
                    reason="invalid_password"
                )
                raise HTTPException(status_code=401, detail="Unauthorized")
            _log_migration_event(
                "tenant_admin_auth",
                slug,
                "NOT_FOUND",
                legacy_auth=False,
                reason="missing_admin_config"
            )
        else:
            _log_migration_event(
                "tenant_admin_auth",
                slug,
                "NOT_FOUND",
                legacy_auth=False,
                reason="missing_tenant"
            )

    fallback_requested = _matches_global_admin_password(provided_password)
    if fallback_requested:
        if LEGACY_FALLBACK_ENABLED:
            _clear_rate_limit_bucket(auth_bucket_key)
            _log_migration_event(
                "tenant_admin_auth",
                slug,
                "LEGACY_GLOBAL",
                legacy_auth=True,
                result="success"
            )
            return
        _record_rate_limit_event(auth_bucket_key)
        _log_migration_event(
            "tenant_admin_auth",
            slug,
            "LEGACY_GLOBAL",
            legacy_auth=True,
            result="failure",
            fallback_disabled="true"
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    _record_rate_limit_event(auth_bucket_key)
    _log_migration_event(
        "tenant_admin_auth",
        slug,
        "LEGACY_GLOBAL",
        legacy_auth=False,
        result="failure",
        reason="invalid_global_password"
    )
    raise HTTPException(status_code=401, detail="Unauthorized")


async def verify_admin_password(
    slug: Optional[str],
    x_admin_password: Optional[str],
    request: Optional[Request] = None,
) -> None:
    await verify_tenant_admin_password(slug, x_admin_password, request=request)


async def verify_internal_admin_password(
    provided_password: Optional[str],
    request: Optional[Request] = None,
) -> None:
    auth_bucket_key = _enforce_auth_rate_limit(None, request, "internal")

    if not provided_password:
        _record_rate_limit_event(auth_bucket_key)
        _log_migration_event(
            "internal_admin_auth",
            None,
            "LEGACY_GLOBAL",
            reason="missing_password"
        )
        raise HTTPException(status_code=401, detail="Cabecera x-admin-password requerida.")

    if _matches_global_admin_password(provided_password):
        _clear_rate_limit_bucket(auth_bucket_key)
        _log_migration_event(
            "internal_admin_auth",
            None,
            "LEGACY_GLOBAL",
            result="success"
        )
        return

    _record_rate_limit_event(auth_bucket_key)
    _log_migration_event(
        "internal_admin_auth",
        None,
        "LEGACY_GLOBAL",
        result="failure",
        reason="invalid_global_password"
    )
    raise HTTPException(status_code=401, detail="Unauthorized")


async def ensure_internal_admin(x_admin_password: Optional[str], request: Optional[Request] = None) -> None:
    await verify_internal_admin_password(x_admin_password, request=request)

# MongoDB connection
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def ensure_mongo_indexes() -> None:
    """
    Asegura índices útiles para la estrategia multi-tenant sin romper documentos legacy.
    """
    try:
        tenant_idx = await db.tenants.create_index(
            "slug",
            unique=True,
            name="tenant_slug_unique",
            background=True,
            partialFilterExpression={"slug": {"$exists": True}}
        )
        logger.info("Índice creado tenants.slug unique=%s", tenant_idx)
    except Exception as exc:
        logger.warning("No se pudo crear índice tenants.slug único: %s", exc)

    index_defs = [
        {
            "keys": [("tenant_id", 1)],
            "name": "leads_tenant_id",
            "partialFilterExpression": {"tenant_id": {"$exists": True}},
        },
        {
            "keys": [("slug", 1)],
            "name": "leads_slug",
            "partialFilterExpression": {"slug": {"$exists": True}},
        },
        {
            "keys": [("tenant_id", 1), ("created_at", -1)],
            "name": "leads_tenant_created",
            "partialFilterExpression": {"tenant_id": {"$exists": True}},
        },
        {
            "keys": [("created_at", -1)],
            "name": "leads_created_at",
        },
    ]

    for index in index_defs:
        try:
            idx_name = await db.leads.create_index(
                index["keys"],
                name=index["name"],
                background=True,
                partialFilterExpression=index.get("partialFilterExpression"),
            )
            logger.info("Índice creado leads.%s (%s)", index["name"], idx_name)
        except Exception as exc:
            logger.warning("Fallo al crear índice leads.%s : %s", index["name"], exc)

# =============================================================================
# MULTI-TENANT SUPPORT (MIGRACIÓN INCREMENTAL)
# =============================================================================

async def get_tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """
    Busca un tenant en la colección 'tenants' por slug.
    Retorna None si no existe.
    """
    normalized_slug = normalize_slug(slug) if slug else ""
    if not normalized_slug:
        return None
    
    tenant_doc = await db.tenants.find_one({"slug": normalized_slug})
    if tenant_doc:
        tenant_doc["id"] = str(tenant_doc.pop("_id"))
        logger.info("Tenant encontrado en Mongo: slug=%s", normalized_slug)
        return tenant_doc
    
    logger.debug("Tenant NO encontrado en Mongo: slug=%s (usando fallback)", normalized_slug)
    return None


async def get_tenant_by_id(tenant_id: Any) -> Optional[Dict[str, Any]]:
    if not tenant_id:
        return None

    tenant_object_id: Optional[ObjectId] = None
    if isinstance(tenant_id, ObjectId):
        tenant_object_id = tenant_id
    elif isinstance(tenant_id, str) and ObjectId.is_valid(tenant_id):
        tenant_object_id = ObjectId(tenant_id)

    if tenant_object_id is None:
        return None

    tenant_doc = await db.tenants.find_one({"_id": tenant_object_id})
    if tenant_doc:
        tenant_doc["id"] = str(tenant_doc.pop("_id"))
        logger.info("Tenant encontrado en Mongo por id=%s", tenant_doc["id"])
        return tenant_doc

    logger.debug("Tenant NO encontrado en Mongo por id=%s", tenant_id)
    return None


def build_public_business_config(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """
    Construye la configuración pública para el frontend desde un documento tenant.
    Solo expone campos seguros para el cliente.
    """
    return {
        "business_name": tenant.get("business_name", "Negocio"),
        "phone": tenant.get("phone", ""),
        "hours": tenant.get("hours", ""),
        "address": tenant.get("address", ""),
        "avatar": tenant.get("avatar", ""),
        "image": tenant.get("image", ""),
        "greeting": tenant.get("greeting", "Hola, ¿en qué puedo ayudarte?"),
    }

app = FastAPI(title="WHASABI API")

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Inicializando índices de MongoDB...")
    await ensure_mongo_indexes()

api_router = APIRouter(prefix="/api")

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Lo siento, en este momento tengo problemas técnicos. ¿Podrías intentar de nuevo en un momento?"}
    )

# In-memory store for chat history and lead state
chat_sessions: Dict[str, Dict[str, Any]] = {}

def _build_chat_config_from_tenant(tenant: Dict[str, Any]) -> Dict[str, Any]:
    config = build_public_business_config(tenant)
    config["system_prompt"] = tenant.get("system_prompt") or get_default_system_prompt()
    return config


def build_public_business_config_from_legacy(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "business_name": config.get("business_name", "Negocio"),
        "phone": config.get("phone", ""),
        "hours": config.get("hours", ""),
        "address": config.get("address", ""),
        "avatar": config.get("avatar", ""),
        "image": config.get("image", ""),
        "greeting": config.get("greeting", "Hola, ¿en qué puedo ayudarte?"),
    }


def _chat_session_key(session_id: str, resolved_slug: str) -> str:
    return f"{resolved_slug}:{session_id}"


def _build_lead_scope_filter(slug: str, tenant: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if tenant:
        return {
            "$or": [
                {"tenant_id": tenant["id"]},
                {"slug": slug, "tenant_id": None},
                {"slug": slug, "tenant_id": {"$exists": False}},
            ]
        }
    return {"slug": slug}


async def _resolve_lead_owner_slug(lead_doc: Dict[str, Any]) -> Optional[str]:
    tenant = await get_tenant_by_id(lead_doc.get("tenant_id"))
    if tenant:
        return tenant["slug"]
    lead_slug = lead_doc.get("slug")
    return normalize_slug(lead_slug) if lead_slug else None


async def _resolve_chat_config(raw_slug: Optional[str]) -> Tuple[Dict[str, Any], str, Optional[str], str]:
    slug = normalize_slug(raw_slug) if raw_slug else ""
    if slug:
        tenant = await get_tenant_by_slug(slug)
        if tenant:
            if not _is_tenant_active(tenant):
                _log_migration_event("chat_config", slug, "MONGO", reason="inactive_tenant")
                raise HTTPException(
                    status_code=404,
                    detail="Configuración de chat no encontrada para el slug solicitado."
                )
            config = _build_chat_config_from_tenant(tenant)
            _log_migration_event("chat_config", slug, "MONGO")
            return config, slug, tenant["id"], "MONGO"

        if slug in DEMO_SLUGS:
            _log_migration_event("chat_config", slug, "DEFAULT_ONLY_WHEN_ALLOWED")
            return dict(CLIENT_CONFIGS[DEFAULT_SLUG]), DEFAULT_SLUG, None, "DEFAULT_ONLY_WHEN_ALLOWED"

        legacy_config = CLIENT_CONFIGS.get(slug)
        if legacy_config:
            if not LEGACY_FALLBACK_ENABLED:
                _log_migration_event(
                    "chat_config",
                    slug,
                    "LEGACY_FALLBACK",
                    fallback_disabled="true"
                )
                raise HTTPException(
                    status_code=404,
                    detail="Legacy chat configuration is temporarily disabled."
                )
            _log_migration_event("chat_config", slug, "LEGACY_FALLBACK")
            return dict(legacy_config), slug, None, "LEGACY_FALLBACK"

        _log_migration_event("chat_config", slug, "NOT_FOUND", reason="missing_config")
        raise HTTPException(status_code=404, detail="Configuración de chat no encontrada para el slug solicitado.")

    _log_migration_event("chat_config", "<empty>", "DEFAULT_ONLY_WHEN_ALLOWED")
    return dict(CLIENT_CONFIGS[DEFAULT_SLUG]), DEFAULT_SLUG, None, "DEFAULT_ONLY_WHEN_ALLOWED"

NAME_PATTERNS = [
    re.compile(r"(?:me llamo|mi nombre es|soy)\s+([^\W\d_]+(?:\s+[^\W\d_]+){0,3})", re.IGNORECASE),
]

INTENT_KEYWORDS = {
    "agendar", "agenda", "cita", "citas", "consulta", "consultas", "precio",
    "precios", "cotizacion", "informacion", "servicio", "servicios",
    "tratamiento", "tratamientos", "horario", "horarios", "ubicacion",
    "quiero", "necesito", "busco"
}


def extract_name(text: str, lower_text: str) -> Optional[str]:
    if re.search(r"\d", text):
        return None

    for pattern in NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip(" .,;:!?")

    words = text.split()
    if not 2 <= len(words) <= 4:
        return None

    if any(keyword in lower_text for keyword in INTENT_KEYWORDS):
        return None

    cleaned_words = [word.strip(" .,;:!?") for word in words]
    if all(word and word.replace("'", "").isalpha() for word in cleaned_words):
        return text.strip(" .,;:!?")

    return None
class ChatMessage(BaseModel):
    text: str = Field(..., max_length=1500, description="User message text")
    session_id: str = Field(..., max_length=100)
    slug: Optional[str] = Field("default", max_length=50)


class LeadStatus(str, Enum):
    nuevo = "nuevo"
    contactado = "contactado"
    en_proceso = "en_proceso"
    perdido = "perdido"
    cerrado = "cerrado"
    descartado = "descartado"


class LeadUpdate(BaseModel):
    status: Optional[LeadStatus] = Field(None, description="Estado administrativo del lead")
    notes: Optional[str] = Field(None, max_length=4000, description="Notas internas sobre el lead")


class TenantCreate(BaseModel):
    slug: str = Field(..., max_length=50, description="Identificador único del tenant")
    business_name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field("", max_length=80, description="Teléfono visible del negocio")
    hours: str = Field("", max_length=120, description="Horarios del negocio")
    address: str = Field("", max_length=255, description="Dirección del negocio")
    avatar: str = Field("", max_length=500, description="URL de avatar")
    image: str = Field("", max_length=500, description="URL de imagen de portada")
    greeting: str = Field("", max_length=500, description="Saludo inicial del asistente")
    system_prompt: Optional[str] = Field(None, max_length=2500, description="Prompt interno del asistente")
    admin_password: str = Field(..., min_length=8, description="Contraseña para admin")
    is_active: bool = Field(True, description="Si el tenant está activo")


class TenantUpdate(BaseModel):
    business_name: Optional[str] = Field(None, max_length=120, description="Nombre del negocio")
    phone: Optional[str] = Field(None, max_length=80)
    hours: Optional[str] = Field(None, max_length=120)
    address: Optional[str] = Field(None, max_length=255)
    avatar: Optional[str] = Field(None, max_length=500)
    image: Optional[str] = Field(None, max_length=500)
    greeting: Optional[str] = Field(None, max_length=500)
    system_prompt: Optional[str] = Field(None, max_length=2500)
    admin_password: Optional[str] = Field(None, min_length=8)
    is_active: Optional[bool] = Field(None, description="Activa/desactiva tenant")


def serialize_lead(doc: Dict[str, Any]) -> Dict[str, Any]:
    lead = doc.copy()
    lead["id"] = str(lead.get("_id"))
    lead.pop("_id", None)
    return lead


def tenant_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc.get("_id")),
        "slug": doc.get("slug"),
        "business_name": doc.get("business_name"),
        "phone": doc.get("phone"),
        "hours": doc.get("hours"),
        "address": doc.get("address"),
        "avatar": doc.get("avatar"),
        "image": doc.get("image"),
        "greeting": doc.get("greeting"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "has_password": bool(doc.get("admin_config", {}).get("password_hash")),
    }


def tenant_internal(doc: Dict[str, Any]) -> Dict[str, Any]:
    tenant = tenant_public(doc)
    tenant["system_prompt"] = doc.get("system_prompt") or get_default_system_prompt()
    return tenant


@api_router.get("/health")
async def health_check(): # Added "service" for consistency with test results
    return {"status": "ok", "service": "whasabi-api"}

@api_router.get("/business/{slug}")
async def get_business(slug: str):
    """
    Obtiene configuración del negocio.
    ESTRATEGIA DE MIGRACIÓN:
    1. Intenta buscar en Mongo (colección 'tenants')
    2. Si no existe, usa fallback a CLIENT_CONFIGS (legacy)
    3. Si tampoco está en legacy, responde con 404
    """
    # --- INTENTO 1: Buscar en MongoDB (NUEVO) ---
    normalized_slug = normalize_slug(slug)
    tenant = await get_tenant_by_slug(normalized_slug)
    if tenant:
        if not _is_tenant_active(tenant):
            _log_migration_event("get_business", normalized_slug, "MONGO", reason="inactive_tenant")
            raise HTTPException(status_code=404, detail="Configuración no encontrada para ese negocio")
        config = build_public_business_config(tenant)
        _log_migration_event("get_business", normalized_slug, "MONGO")
        return config
    
    # --- INTENTO 2: Fallback a CLIENT_CONFIGS (LEGACY - TEMPORAL) ---
    legacy_config = CLIENT_CONFIGS.get(normalized_slug)
    if legacy_config:
        if not LEGACY_FALLBACK_ENABLED:
            _log_migration_event(
                "get_business",
                normalized_slug,
                "LEGACY_FALLBACK",
                fallback_disabled="true"
            )
            raise HTTPException(
                status_code=404,
                detail="Legacy business configuration is temporarily disabled."
            )
        _log_migration_event("get_business", normalized_slug, "LEGACY_FALLBACK")
        return build_public_business_config_from_legacy(legacy_config)

    _log_migration_event("get_business", normalized_slug, "NOT_FOUND", reason="missing_config")
    raise HTTPException(status_code=404, detail="Configuración no encontrada para ese negocio")

@api_router.get("/leads/{identifier}")
async def get_leads(
    identifier: str,
    request: Request,
    x_admin_password: Optional[str] = Header(None)
):
    if "password" in request.query_params:
        raise HTTPException(status_code=400, detail="Usa la cabecera x-admin-password.")

    normalized_identifier = normalize_slug(identifier)
    tenant = await get_tenant_by_slug(normalized_identifier)
    if tenant or normalized_identifier in CLIENT_CONFIGS:
        await verify_admin_password(normalized_identifier, x_admin_password, request=request)
        leads = await db.leads.find(
            _build_lead_scope_filter(normalized_identifier, tenant),
            {"_id": 0},
        ).sort("created_at", -1).to_list(1000)
        return leads

    if ObjectId.is_valid(identifier):
        logger.info("Read lead id=%s", identifier)
        lead_doc = await db.leads.find_one({"_id": ObjectId(identifier)})
        if not lead_doc:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        owner_slug = await _resolve_lead_owner_slug(lead_doc)
        await verify_admin_password(owner_slug, x_admin_password, request=request)
        return serialize_lead(lead_doc)

    await verify_admin_password(normalized_identifier, x_admin_password, request=request)
    leads = await db.leads.find({"slug": normalized_identifier}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return leads


@api_router.get("/leads")
async def list_leads(
    request: Request,
    q: Optional[str] = None,
    status: Optional[LeadStatus] = None,
    slug: Optional[str] = None,
    limit: int = 200,
    x_admin_password: Optional[str] = Header(None)
):
    normalized_slug = normalize_slug(slug) if slug else None
    await verify_admin_password(normalized_slug, x_admin_password, request=request)
    filters: Dict[str, Any] = {}
    if normalized_slug:
        tenant = await get_tenant_by_slug(normalized_slug)
        filters.update(_build_lead_scope_filter(normalized_slug, tenant))
    if status:
        filters["status"] = status.value
    if q:
        escaped_query = re.escape(q.strip())
        if escaped_query:
            filters["$or"] = [
                {"nombre": {"$regex": escaped_query, "$options": "i"}},
                {"telefono": {"$regex": escaped_query, "$options": "i"}},
                {"consulta": {"$regex": escaped_query, "$options": "i"}},
            ]

    safe_limit = min(max(limit, 1), 500)
    logger.info("List leads slug=%r status=%r q=%r limit=%d", normalized_slug, status, q, safe_limit)

    cursor = (
        db.leads.find(filters)
        .sort("created_at", -1)
        .limit(safe_limit)
    )
    lead_docs = await cursor.to_list(length=safe_limit)
    return [serialize_lead(doc) for doc in lead_docs]


@api_router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    request: Request,
    x_admin_password: Optional[str] = Header(None)
):
    try:
        oid = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")

    lead_doc = await db.leads.find_one({"_id": oid})
    if not lead_doc:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    owner_slug = await _resolve_lead_owner_slug(lead_doc)
    await verify_admin_password(owner_slug, x_admin_password, request=request)

    update_fields: Dict[str, Any] = {}
    if payload.status is not None:
        update_fields["status"] = payload.status.value
    if payload.notes is not None:
        update_fields["notes"] = payload.notes

    if not update_fields:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos válidos")

    logger.info("Update lead id=%s fields=%s", lead_id, ", ".join(update_fields.keys()))
    result = await db.leads.update_one({"_id": oid}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    updated_doc = await db.leads.find_one({"_id": oid})
    return serialize_lead(updated_doc)


@api_router.get("/internal/tenants")
async def list_internal_tenants(request: Request, x_admin_password: Optional[str] = Header(None)):
    await ensure_internal_admin(x_admin_password, request=request)
    cursor = db.tenants.find().sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [tenant_public(doc) for doc in docs]


@api_router.post("/internal/tenants")
async def create_internal_tenant(
    payload: TenantCreate,
    request: Request,
    x_admin_password: Optional[str] = Header(None)
):
    await ensure_internal_admin(x_admin_password, request=request)
    slug = ensure_valid_slug(payload.slug)
    if await db.tenants.find_one({"slug": slug}):
        raise HTTPException(status_code=400, detail="El slug ya existe.")
    now = datetime.now(timezone.utc).isoformat()
    tenant_doc = {
        "slug": slug,
        "business_name": payload.business_name.strip(),
        "phone": payload.phone.strip(),
        "hours": payload.hours.strip(),
        "address": payload.address.strip(),
        "avatar": payload.avatar.strip(),
        "image": payload.image.strip(),
        "greeting": payload.greeting.strip(),
        "system_prompt": (payload.system_prompt or "").strip() or get_default_system_prompt(),
        "is_active": payload.is_active,
        "admin_config": {"password_hash": crypt_context.hash(payload.admin_password)},
        "created_at": now,
        "updated_at": now,
    }
    await db.tenants.insert_one(tenant_doc)
    created = await db.tenants.find_one({"slug": slug})
    return tenant_internal(created)


@api_router.get("/internal/tenants/{slug}")
async def get_internal_tenant(slug: str, request: Request, x_admin_password: Optional[str] = Header(None)):
    await ensure_internal_admin(x_admin_password, request=request)
    normalized_slug = ensure_valid_slug(slug)
    tenant_doc = await db.tenants.find_one({"slug": normalized_slug})
    if not tenant_doc:
        raise HTTPException(status_code=404, detail="Tenant no encontrado.")
    return tenant_internal(tenant_doc)


@api_router.patch("/internal/tenants/{slug}")
async def update_internal_tenant(
    slug: str,
    payload: TenantUpdate,
    request: Request,
    x_admin_password: Optional[str] = Header(None)
):
    await ensure_internal_admin(x_admin_password, request=request)
    normalized_slug = ensure_valid_slug(slug)
    existing = await db.tenants.find_one({"slug": normalized_slug})
    if not existing:
        raise HTTPException(status_code=404, detail="Tenant no encontrado.")
    update_fields: Dict[str, Any] = {}

    def _set_field(field_name: str, value: Optional[str]) -> None:
        if value is not None:
            update_fields[field_name] = value.strip()

    _set_field("business_name", payload.business_name)
    _set_field("phone", payload.phone)
    _set_field("hours", payload.hours)
    _set_field("address", payload.address)
    _set_field("avatar", payload.avatar)
    _set_field("image", payload.image)
    _set_field("greeting", payload.greeting)
    if payload.system_prompt is not None:
        update_fields["system_prompt"] = payload.system_prompt.strip() or get_default_system_prompt()

    if payload.admin_password:
        update_fields["admin_config.password_hash"] = crypt_context.hash(payload.admin_password)

    if payload.is_active is not None:
        update_fields["is_active"] = payload.is_active

    if not update_fields:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos para actualizar.")

    update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.tenants.update_one({"slug": normalized_slug}, {"$set": update_fields})
    updated = await db.tenants.find_one({"slug": normalized_slug})
    return tenant_internal(updated)

@api_router.post("/chat")
async def handle_chat(message: ChatMessage, request: Request):
    session_id = message.session_id
    text = message.text.strip()
    lower_text = text.lower()
    normalized_chat_slug = normalize_slug(message.slug) if message.slug else DEFAULT_SLUG
    chat_bucket_key = _chat_rate_limit_key(message.slug, request)
    _enforce_rate_limit(
        bucket_key=chat_bucket_key,
        limit=CHAT_RATE_LIMIT_PER_WINDOW,
        detail="Demasiados mensajes en poco tiempo. Intenta de nuevo en un momento.",
        endpoint="chat",
        slug=normalized_chat_slug,
        scope="chat",
        request=request,
    )
    _record_rate_limit_event(chat_bucket_key)

    # ESTRATEGIA DE MIGRACIÓN: Primero Mongo, luego fallback a legacy
    config, resolved_slug, resolved_tenant_id, config_source = await _resolve_chat_config(message.slug)
    logger.info(
        "Session association session_id=%s slug=%s tenant_id=%s source=%s",
        session_id,
        resolved_slug,
        resolved_tenant_id or "legacy",
        config_source,
    )
    session_key = _chat_session_key(session_id, resolved_slug)

    # Initialize session state if not exists
    if session_key not in chat_sessions:
        chat_sessions[session_key] = {
            "messages": [{"role": "system", "content": config["system_prompt"]}],
            "nombre": None,
            "telefono": None,

            "consulta": None,
            "leadSaved": False,
            "slug": resolved_slug,
            "tenant_id": resolved_tenant_id,
            "tenant_source": config_source,
        }
    
    state = chat_sessions[session_key]
    state["slug"] = resolved_slug
    state["tenant_id"] = resolved_tenant_id
    state["tenant_source"] = config_source
    state["messages"].append({"role": "user", "content": text})
    
    # --- LEAD EXTRACTION LOGIC ---
    logger.info("Lead extraction attempt session_id=%s", session_id)
    
    # 1. Phone (10 digits)
    extracted_phone = None
    if not state["telefono"]:
        digits_only = re.sub(r'\D', '', text)
        if len(digits_only) >= 10:
            match = re.search(r'\d{10}', digits_only)
            if match:
                extracted_phone = match.group(0)
                state["telefono"] = extracted_phone
                
    # 2. Name
    extracted_name = None
    if not state["nombre"]:
        extracted_name = extract_name(text, lower_text)
        if extracted_name:
            state["nombre"] = extracted_name

    # 3. Consulta (First meaningful request)
    greetings = ['hola', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches', 'que tal', 'hola!', 'hola!!', 'holii']
    if not state["consulta"]:
        if lower_text not in greetings and not extracted_phone and not extracted_name:
            state["consulta"] = text

    logger.info(
        "Lead data extracted session_id=%s nombre=%r telefono=%r consulta=%r",
        session_id,
        state["nombre"],
        state["telefono"],
        state["consulta"]
    )
                    
    # --- SAVE LEAD TO MONGODB ---
    if state["nombre"] and state["telefono"] and state["consulta"] and not state["leadSaved"]:
        lead_doc = {
            "slug": state["slug"],
            "tenant_id": state.get("tenant_id"),
            "nombre": state["nombre"],
            "telefono": state["telefono"],
            "consulta": state["consulta"],
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        lead_doc["status"] = state.get("status") or "nuevo"
        notes = state.get("notes")
        if notes is not None:
            lead_doc["notes"] = notes
        try:
            logger.info(
                "Lead insert attempt session_id=%s slug=%s tenant_id=%s source=%s collection=leads",
                session_id,
                lead_doc["slug"],
                lead_doc.get("tenant_id") or "legacy",
                state.get("tenant_source", "legacy"),
            )
            result = await db.leads.insert_one(lead_doc)
            state["leadSaved"] = True
            logger.info(
                "Lead insert success session_id=%s tenant_id=%s inserted_id=%s",
                session_id,
                lead_doc.get("tenant_id") or "legacy",
                result.inserted_id,
            )
        except Exception:
            logger.exception("Lead insert error session_id=%s", session_id)

    # --- CALL DEEPSEEK API ---
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": state["messages"],
                    "temperature": 0.7,
                    "max_tokens": 150
                },
                timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            
            ai_reply = data["choices"][0]["message"]["content"]
            
            # Append AI reply to history
            state["messages"].append({"role": "assistant", "content": ai_reply})
            
            return {
                "reply": ai_reply,
                "session_id": session_id
            }
            
    except Exception as e:
        logger.error(f"Error calling DeepSeek API: {str(e)}")
        fallback_msg = "Lo siento, en este momento tengo problemas técnicos. ¿Podrías intentar de nuevo en un momento?"
        return {
            "reply": fallback_msg,
            "session_id": session_id
        }

cors_kwargs = {
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

# Si el wildcard '*' está explícitamente en la lista de orígenes
if "*" in CORS_ORIGINS:
    logger.warning("CORS_ORIGINS está configurado para permitir '*', lo cual es INSEGURO para entornos de producción. Úsalo con extrema precaución.")
    cors_kwargs["allow_origins"] = ["*"]
    # allow_credentials no puede ser True cuando allow_origins es ["*"]
else:
    cors_kwargs["allow_origins"] = CORS_ORIGINS
    cors_kwargs["allow_credentials"] = True
    
app.add_middleware(CORSMiddleware, **cors_kwargs)

app.include_router(api_router)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT)
