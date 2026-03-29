import logging
import os
import re
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


LEGACY_FALLBACK_ENABLED = _parse_bool_env_flag("LEGACY_FALLBACK_ENABLED", True)


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

async def verify_tenant_admin_password(slug: Optional[str], provided_password: Optional[str]) -> None:
    if not provided_password:
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
            admin_config = tenant.get("admin_config", {})
            password_hash = admin_config.get("password_hash")
            if password_hash:
                if crypt_context.verify(provided_password, password_hash):
                    _log_migration_event(
                        "tenant_admin_auth",
                        slug,
                        "MONGO",
                        legacy_auth=False,
                        result="success"
                    )
                    return
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

    fallback_requested = provided_password == ADMIN_PASSWORD
    if fallback_requested:
        if LEGACY_FALLBACK_ENABLED:
            _log_migration_event(
                "tenant_admin_auth",
                slug,
                "LEGACY_GLOBAL",
                legacy_auth=True,
                result="success"
            )
            return
        _log_migration_event(
            "tenant_admin_auth",
            slug,
            "LEGACY_GLOBAL",
            legacy_auth=True,
            result="failure",
            fallback_disabled="true"
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

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
    password_query: Optional[str] = None
) -> None:
    provided = x_admin_password if x_admin_password is not None else password_query
    await verify_tenant_admin_password(slug, provided)


async def ensure_internal_admin(x_admin_password: Optional[str]) -> None:
    if not x_admin_password:
        raise HTTPException(status_code=401, detail="Cabecera x-admin-password requerida.")
    await verify_admin_password(None, x_admin_password)

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
    if not slug:
        return None
    
    tenant_doc = await db.tenants.find_one({"slug": slug})
    if tenant_doc:
        tenant_doc["id"] = str(tenant_doc.pop("_id"))
        logger.info("Tenant encontrado en Mongo: slug=%s", slug)
        return tenant_doc
    
    logger.debug("Tenant NO encontrado en Mongo: slug=%s (usando fallback)", slug)
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
        "_source": "mongo"  # Flag para debugging
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

# Multi-client mock configuration
# Legacy placeholder configs (temporary compat layer, remove once Mongo has every tenant).
CLIENT_CONFIGS = {
    "cafe-minima": {
        "business_name": "Café Mínima",
        "system_prompt": "Eres el asistente virtual de Café Mínima en México. Eres amigable, respondes dudas sobre el menú, horarios y ubicación. Tu objetivo es ayudar y guiar al usuario para que comparta su nombre y teléfono de manera natural. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 1234 5678",
        "hours": "8:00 AM - 6:00 PM",
        "address": "Roma Norte, CDMX",
        "avatar": "https://images.unsplash.com/photo-1550567433-89a8ed4b23fa?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBtaW5pbWFsJTIwY2FmZSUyMHN0b3JlZnJvbnR8ZW58MHx8fHwxNzc0NTAyNTg0fDA&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1752754331999-a20ee211ec20?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwyfHxtb2Rlcm4lMjBtaW5pbWFsJTIwY2FmZSUyMHN0b3JlZnJvbnR8ZW58MHx8fHwxNzc0NTAyNTg0fDA&ixlib=rb-4.1.0&q=85",
        "greeting": "¡Hola! Soy el asistente virtual de Café Mínima. ¿En qué te puedo ayudar hoy?"
    },
    "dentista-lopez": {
        "business_name": "Dentista López",
        "system_prompt": "Eres el recepcionista virtual del consultorio Dentista López en México. Eres profesional y empático. Ayudas a los pacientes a resolver dudas sobre servicios dentales y buscar agendar citas. Tu objetivo es obtener su nombre y teléfono para que el doctor los contacte. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 9876 5432",
        "hours": "9:00 AM - 7:00 PM",
        "address": "Polanco, CDMX",
        "avatar": "https://images.unsplash.com/photo-1598256989800-fea5ce514169?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxkZW50aXN0fGVufDB8fHx8MTY4MzY0MzUzM3ww&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1606811841689-23dfddce3e95?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwyfHxkZW50aXN0JTIwb2ZmaWNlfGVufDB8fHx8MTY4MzY0MzU0Mnww&ixlib=rb-4.1.0&q=85",
        "greeting": "¡Hola! Bienvenido al consultorio Dentista López. ¿En qué puedo ayudarte?"
    },
    "default": {
        "business_name": "Negocio Demo",
        "system_prompt": "Eres un asistente virtual profesional para un negocio local en México. Tu objetivo es ayudar a los clientes y guiarlos para que dejen su nombre y teléfono. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 0000 0000",
        "hours": "Lunes a Viernes, 9AM - 5PM",
        "address": "Centro Histórico, CDMX",
        "avatar": "https://images.unsplash.com/photo-1497366216548-37526070297c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxidXNpbmVzc3xlbnwwfHx8fDE2ODM2NDM1NTZ8MA&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1497366216548-37526070297c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxidXNpbmVzc3xlbnwwfHx8fDE2ODM2NDM1NTZ8MA&ixlib=rb-4.1.0&q=85",
        "greeting": "Hola, soy el asistente virtual de este negocio. ¿Cómo puedo ayudarte?"
    }
}

DEFAULT_SLUG = "default"
DEMO_SLUGS = {DEFAULT_SLUG}


def _build_chat_config_from_tenant(tenant: Dict[str, Any]) -> Dict[str, Any]:
    config = build_public_business_config(tenant)
    config["system_prompt"] = tenant.get("system_prompt", "")
    return config


async def _resolve_chat_config(raw_slug: Optional[str]) -> Tuple[Dict[str, Any], str, Optional[str], str]:
    slug = raw_slug.strip() if raw_slug else ""
    if slug:
        tenant = await get_tenant_by_slug(slug)
        if tenant:
            config = _build_chat_config_from_tenant(tenant)
            _log_migration_event("chat_config", slug, "MONGO")
            return config, slug, tenant["id"], "MONGO"

        if slug in DEMO_SLUGS:
            _log_migration_event("chat_config", slug, "DEFAULT_ONLY_WHEN_ALLOWED")
            default_config = dict(CLIENT_CONFIGS[DEFAULT_SLUG])
            default_config["_source"] = "default_only_when_allowed"
            return default_config, DEFAULT_SLUG, None, "DEFAULT_ONLY_WHEN_ALLOWED"

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
            return {**legacy_config, "_source": "legacy_fallback"}, slug, None, "LEGACY_FALLBACK"

        _log_migration_event("chat_config", slug, "NOT_FOUND", reason="missing_config")
        raise HTTPException(status_code=404, detail="Configuración de chat no encontrada para el slug solicitado.")

    _log_migration_event("chat_config", "<empty>", "DEFAULT_ONLY_WHEN_ALLOWED")
    default_config = dict(CLIENT_CONFIGS[DEFAULT_SLUG])
    default_config["_source"] = "default_only_when_allowed"
    return default_config, DEFAULT_SLUG, None, "DEFAULT_ONLY_WHEN_ALLOWED"

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

class LeadUpdate(BaseModel):
    status: Optional[str] = Field(None, description="Estado administrativo del lead")
    notes: Optional[str] = Field(None, description="Notas internas sobre el lead")


class TenantCreate(BaseModel):
    slug: str = Field(..., description="Identificador único del tenant")
    business_name: str = Field(..., min_length=1)
    phone: str = Field("", description="Teléfono visible del negocio")
    hours: str = Field("", description="Horarios del negocio")
    address: str = Field("", description="Dirección del negocio")
    avatar: str = Field("", description="URL de avatar")
    image: str = Field("", description="URL de imagen de portada")
    greeting: str = Field("", description="Saludo inicial del asistente")
    admin_password: str = Field(..., min_length=8, description="Contraseña para admin")
    is_active: bool = Field(True, description="Si el tenant está activo")


class TenantUpdate(BaseModel):
    business_name: Optional[str] = Field(None, description="Nombre del negocio")
    phone: Optional[str] = Field(None)
    hours: Optional[str] = Field(None)
    address: Optional[str] = Field(None)
    avatar: Optional[str] = Field(None)
    image: Optional[str] = Field(None)
    greeting: Optional[str] = Field(None)
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
    tenant = await get_tenant_by_slug(slug)
    if tenant:
        config = build_public_business_config(tenant)
        _log_migration_event("get_business", slug, "MONGO")
        return config
    
    # --- INTENTO 2: Fallback a CLIENT_CONFIGS (LEGACY - TEMPORAL) ---
    legacy_config = CLIENT_CONFIGS.get(slug)
    if legacy_config:
        if not LEGACY_FALLBACK_ENABLED:
            _log_migration_event(
                "get_business",
                slug,
                "LEGACY_FALLBACK",
                fallback_disabled="true"
            )
            raise HTTPException(
                status_code=404,
                detail="Legacy business configuration is temporarily disabled."
            )
        _log_migration_event("get_business", slug, "LEGACY_FALLBACK")
        return {**legacy_config, "_source": "legacy_fallback"}

    _log_migration_event("get_business", slug, "NOT_FOUND", reason="missing_config")
    raise HTTPException(status_code=404, detail="Configuración no encontrada para ese negocio")

@api_router.get("/leads/{identifier}")
async def get_leads(
    identifier: str,
    password: Optional[str] = None,
    x_admin_password: Optional[str] = Header(None)
):
    if ObjectId.is_valid(identifier) and password is None:
        logger.info("Read lead id=%s", identifier)
        lead_doc = await db.leads.find_one({"_id": ObjectId(identifier)})
        if not lead_doc:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        await verify_admin_password(lead_doc.get("slug"), x_admin_password, password)
        return serialize_lead(lead_doc)

    await verify_admin_password(identifier, x_admin_password, password)
    leads = await db.leads.find({"slug": identifier}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return leads


@api_router.get("/leads")
async def list_leads(
    q: Optional[str] = None,
    status: Optional[str] = None,
    slug: Optional[str] = None,
    limit: int = 200,
    x_admin_password: Optional[str] = Header(None)
):
    await verify_admin_password(slug, x_admin_password)
    filters: Dict[str, Any] = {}
    if slug:
        filters["slug"] = slug
    if status:
        filters["status"] = status
    if q:
        filters["$or"] = [
            {"nombre": {"$regex": q, "$options": "i"}},
            {"telefono": {"$regex": q, "$options": "i"}},
            {"consulta": {"$regex": q, "$options": "i"}},
        ]

    safe_limit = min(max(limit, 1), 500)
    logger.info("List leads slug=%r status=%r q=%r limit=%d", slug, status, q, safe_limit)

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
    x_admin_password: Optional[str] = Header(None)
):
    try:
        oid = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")

    lead_doc = await db.leads.find_one({"_id": oid})
    if not lead_doc:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    await verify_admin_password(lead_doc.get("slug"), x_admin_password)

    update_fields: Dict[str, Any] = {}
    if payload.status is not None:
        update_fields["status"] = payload.status
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
async def list_internal_tenants(x_admin_password: Optional[str] = Header(None)):
    await ensure_internal_admin(x_admin_password)
    cursor = db.tenants.find().sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [tenant_public(doc) for doc in docs]


@api_router.post("/internal/tenants")
async def create_internal_tenant(
    payload: TenantCreate,
    x_admin_password: Optional[str] = Header(None)
):
    await ensure_internal_admin(x_admin_password)
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
        "is_active": payload.is_active,
        "admin_config": {"password_hash": crypt_context.hash(payload.admin_password)},
        "created_at": now,
        "updated_at": now,
    }
    await db.tenants.insert_one(tenant_doc)
    created = await db.tenants.find_one({"slug": slug})
    return tenant_public(created)


@api_router.get("/internal/tenants/{slug}")
async def get_internal_tenant(slug: str, x_admin_password: Optional[str] = Header(None)):
    await ensure_internal_admin(x_admin_password)
    normalized_slug = ensure_valid_slug(slug)
    tenant_doc = await db.tenants.find_one({"slug": normalized_slug})
    if not tenant_doc:
        raise HTTPException(status_code=404, detail="Tenant no encontrado.")
    return tenant_public(tenant_doc)


@api_router.patch("/internal/tenants/{slug}")
async def update_internal_tenant(
    slug: str,
    payload: TenantUpdate,
    x_admin_password: Optional[str] = Header(None)
):
    await ensure_internal_admin(x_admin_password)
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

    if payload.admin_password:
        update_fields["admin_config.password_hash"] = crypt_context.hash(payload.admin_password)

    if payload.is_active is not None:
        update_fields["is_active"] = payload.is_active

    if not update_fields:
        raise HTTPException(status_code=400, detail="No se proporcionaron campos para actualizar.")

    update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.tenants.update_one({"slug": normalized_slug}, {"$set": update_fields})
    updated = await db.tenants.find_one({"slug": normalized_slug})
    return tenant_public(updated)

@api_router.post("/chat")
async def handle_chat(message: ChatMessage):
    session_id = message.session_id
    text = message.text.strip()
    lower_text = text.lower()

    # ESTRATEGIA DE MIGRACIÓN: Primero Mongo, luego fallback a legacy
    config, resolved_slug, resolved_tenant_id, config_source = await _resolve_chat_config(message.slug)
    logger.info(
        "Session association session_id=%s slug=%s tenant_id=%s source=%s",
        session_id,
        resolved_slug,
        resolved_tenant_id or "legacy",
        config_source,
    )

    # Initialize session state if not exists
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "messages": [{"role": "system", "content": config["system_prompt"]}],
            "nombre": None,
            "telefono": None,

            "consulta": None,
            "leadSaved": False,
            "slug": resolved_slug,
            "tenant_id": resolved_tenant_id,
            "tenant_source": config_source,
        }
    
    state = chat_sessions[session_id]
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
