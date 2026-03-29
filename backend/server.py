import logging
import os
import re
from datetime import datetime, timezone
import sys # Import sys for SystemExit
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from bson import ObjectId

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

def verify_admin_password(x_admin_password: Optional[str], password_query: Optional[str] = None):
    provided = x_admin_password if x_admin_password is not None else password_query
    if provided != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")

# MongoDB connection
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="WHASABI API")
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


def serialize_lead(doc: Dict[str, Any]) -> Dict[str, Any]:
    lead = doc.copy()
    lead["id"] = str(lead.get("_id"))
    lead.pop("_id", None)
    return lead

@api_router.get("/health")
async def health_check(): # Added "service" for consistency with test results
    return {"status": "ok", "service": "whasabi-api"}

@api_router.get("/business/{slug}")
async def get_business(slug: str):
    config = CLIENT_CONFIGS.get(slug, CLIENT_CONFIGS["default"])
    return config

@api_router.get("/leads/{identifier}")
async def get_leads(
    identifier: str,
    password: Optional[str] = None,
    x_admin_password: Optional[str] = Header(None)
):
    verify_admin_password(x_admin_password, password)

    if ObjectId.is_valid(identifier) and password is None:
        logger.info("Read lead id=%s", identifier)
        lead_doc = await db.leads.find_one({"_id": ObjectId(identifier)})
        if not lead_doc:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        return serialize_lead(lead_doc)

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
    verify_admin_password(x_admin_password)
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
    verify_admin_password(x_admin_password)
    try:
        oid = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")

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

@api_router.post("/chat")
async def handle_chat(message: ChatMessage):
    session_id = message.session_id
    text = message.text.strip()
    lower_text = text.lower()
    
    slug = message.slug if message.slug and message.slug in CLIENT_CONFIGS else "default"
    config = CLIENT_CONFIGS[slug]
    
    # Initialize session state if not exists
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "messages": [{"role": "system", "content": config["system_prompt"]}],
            "nombre": None,
            "telefono": None,
            "consulta": None,
            "leadSaved": False,
            "slug": slug
        }
    
    state = chat_sessions[session_id]
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
            logger.info("Lead insert attempt session_id=%s collection=leads", session_id)
            result = await db.leads.insert_one(lead_doc)
            state["leadSaved"] = True
            logger.info("Lead insert success session_id=%s inserted_id=%s", session_id, result.inserted_id)
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
