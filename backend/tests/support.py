import copy
import os
import re
from types import SimpleNamespace

from bson import ObjectId
from fastapi.testclient import TestClient


os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "whasabi_test_db")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ADMIN_PASSWORD", "GlobalPass123!")

import backend.server as server


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, field, direction):
        reverse = direction == -1
        self.docs = sorted(self.docs, key=lambda doc: doc.get(field) or "", reverse=reverse)
        return self

    def limit(self, size):
        self.docs = self.docs[:size]
        return self

    async def to_list(self, length=None):
        if length is None:
            return [copy.deepcopy(doc) for doc in self.docs]
        return [copy.deepcopy(doc) for doc in self.docs[:length]]


def _matches_condition(value, condition, *, field_exists):
    if isinstance(condition, dict):
        if "$regex" in condition:
            pattern = condition["$regex"]
            flags = re.IGNORECASE if "i" in condition.get("$options", "") else 0
            return re.search(pattern, str(value or ""), flags) is not None
        if "$exists" in condition:
            return field_exists is bool(condition["$exists"])
    return value == condition


def _matches_query(doc, query):
    for key, condition in query.items():
        if key == "$or":
            if not any(_matches_query(doc, option) for option in condition):
                return False
            continue

        if not _matches_condition(doc.get(key), condition, field_exists=(key in doc)):
            return False
    return True


def _apply_projection(doc, projection):
    projected = copy.deepcopy(doc)
    if not projection:
        return projected

    for field, include in projection.items():
        if include == 0:
            projected.pop(field, None)

    return projected


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [copy.deepcopy(doc) for doc in (docs or [])]
        self.created_indexes = []

    async def create_index(self, keys, **kwargs):
        name = kwargs.get("name") or str(keys)
        self.created_indexes.append((keys, kwargs))
        return name

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if _matches_query(doc, query):
                return _apply_projection(doc, projection)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        matched = [_apply_projection(doc, projection) for doc in self.docs if _matches_query(doc, query)]
        return FakeCursor(matched)

    async def insert_one(self, doc):
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return FakeInsertResult(stored["_id"])

    async def update_one(self, query, update):
        matched_count = 0
        for doc in self.docs:
            if _matches_query(doc, query):
                matched_count += 1
                for field, value in update.get("$set", {}).items():
                    target = doc
                    parts = field.split(".")
                    for part in parts[:-1]:
                        target = target.setdefault(part, {})
                    target[parts[-1]] = value
                break
        return FakeUpdateResult(matched_count)


class FakeAsyncClient:
    def __init__(self, reply="Respuesta de prueba"):
        self.reply = reply

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": self.reply}}]},
        )


def make_password_hash(password="TenantPass123!"):
    return server.crypt_context.hash(password)


def make_tenant(
    slug,
    *,
    password="TenantPass123!",
    is_active=True,
    business_name="Tenant Demo",
    system_prompt="Prompt demo",
):
    return {
        "_id": ObjectId(),
        "slug": slug,
        "business_name": business_name,
        "system_prompt": system_prompt,
        "phone": "+52 55 5555 5555",
        "hours": "9:00 - 18:00",
        "address": "CDMX",
        "avatar": "https://example.com/avatar.png",
        "image": "https://example.com/image.png",
        "greeting": "Hola desde tenant",
        "is_active": is_active,
        "admin_config": {"password_hash": make_password_hash(password)},
        "created_at": "2026-03-29T00:00:00+00:00",
        "updated_at": "2026-03-29T00:00:00+00:00",
    }


def make_lead(
    *,
    slug,
    tenant_id=None,
    nombre="Ana",
    telefono="5512345678",
    consulta="Necesito una cita",
    status="nuevo",
    session_id="session-1",
    _id=None,
):
    return {
        "_id": _id or ObjectId(),
        "slug": slug,
        "tenant_id": tenant_id,
        "nombre": nombre,
        "telefono": telefono,
        "consulta": consulta,
        "status": status,
        "session_id": session_id,
        "created_at": "2026-03-29T00:00:00+00:00",
    }


def create_client(
    *,
    tenants=None,
    leads=None,
    legacy_enabled=True,
    deepseek_reply="Respuesta IA",
    chat_limit=None,
    auth_limit=None,
):
    fake_db = SimpleNamespace(
        tenants=FakeCollection(tenants),
        leads=FakeCollection(leads),
        client=SimpleNamespace(close=lambda: None),
    )

    async def _noop_indexes():
        return None

    server.db = fake_db
    server.chat_sessions.clear()
    server.rate_limit_events.clear()
    server.LEGACY_FALLBACK_ENABLED = legacy_enabled
    server.CHAT_RATE_LIMIT_PER_WINDOW = chat_limit or 30
    server.AUTH_RATE_LIMIT_PER_WINDOW = auth_limit or 5
    server.ensure_mongo_indexes = _noop_indexes
    server.httpx.AsyncClient = lambda: FakeAsyncClient(deepseek_reply)

    return TestClient(server.app), fake_db, server
