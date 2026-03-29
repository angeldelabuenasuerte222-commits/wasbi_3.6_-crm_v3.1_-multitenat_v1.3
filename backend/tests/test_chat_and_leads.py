import unittest

from bson import ObjectId

from backend.tests.support import create_client, make_lead, make_tenant


TENANT_PASSWORD = "TenantPass123!"


class ChatAndLeadsTests(unittest.TestCase):
    def test_chat_for_mongo_tenant_saves_lead_with_tenant_id(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        client, fake_db, _ = create_client(tenants=[tenant], legacy_enabled=True)

        steps = [
            {"text": "Necesito una cita", "session_id": "mongo-session", "slug": "mongo-tenant"},
            {"text": "Me llamo Ana", "session_id": "mongo-session", "slug": "mongo-tenant"},
            {"text": "Mi telefono es 5512345678", "session_id": "mongo-session", "slug": "mongo-tenant"},
        ]
        for payload in steps:
            response = client.post("/api/chat", json=payload)
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(fake_db.leads.docs), 1)
        lead = fake_db.leads.docs[0]
        self.assertEqual(lead["slug"], "mongo-tenant")
        self.assertTrue(lead["tenant_id"])
        self.assertEqual(lead["status"], "nuevo")

    def test_chat_for_legacy_slug_saves_lead_without_tenant_id(self):
        client, fake_db, _ = create_client(legacy_enabled=True)

        steps = [
            {"text": "Quiero informacion del menu", "session_id": "legacy-session", "slug": "cafe-minima"},
            {"text": "Me llamo Luis", "session_id": "legacy-session", "slug": "cafe-minima"},
            {"text": "Mi telefono es 5511111111", "session_id": "legacy-session", "slug": "cafe-minima"},
        ]
        for payload in steps:
            response = client.post("/api/chat", json=payload)
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(fake_db.leads.docs), 1)
        lead = fake_db.leads.docs[0]
        self.assertEqual(lead["slug"], "cafe-minima")
        self.assertIsNone(lead.get("tenant_id"))

    def test_invalid_slug_in_chat_returns_404_without_creating_lead(self):
        client, fake_db, _ = create_client(legacy_enabled=True)

        response = client.post(
            "/api/chat",
            json={"text": "Hola", "session_id": "missing-slug-session", "slug": "slug-invalido"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(fake_db.leads.docs, [])

    def test_chat_sessions_are_isolated_by_slug(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD, system_prompt="Prompt Mongo")
        client, _, server = create_client(tenants=[tenant], legacy_enabled=True)

        first = client.post("/api/chat", json={"text": "Hola", "session_id": "shared", "slug": "mongo-tenant"})
        second = client.post("/api/chat", json={"text": "Hola", "session_id": "shared", "slug": "cafe-minima"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("mongo-tenant:shared", server.chat_sessions)
        self.assertIn("cafe-minima:shared", server.chat_sessions)
        self.assertEqual(
            server.chat_sessions["mongo-tenant:shared"]["messages"][0]["content"],
            "Prompt Mongo",
        )
        self.assertNotEqual(
            server.chat_sessions["mongo-tenant:shared"]["messages"][0]["content"],
            server.chat_sessions["cafe-minima:shared"]["messages"][0]["content"],
        )

    def test_status_validation_and_query_password_are_rejected(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        lead = make_lead(slug="mongo-tenant", tenant_id="tenant-1", _id=ObjectId())
        client, _, _ = create_client(tenants=[tenant], leads=[lead], legacy_enabled=True)

        status_response = client.get(
            "/api/leads",
            params={"slug": "mongo-tenant", "status": "inventado"},
            headers={"x-admin-password": TENANT_PASSWORD},
        )
        password_query_response = client.get(
            f"/api/leads/{lead['_id']}?password={TENANT_PASSWORD}",
            headers={"x-admin-password": TENANT_PASSWORD},
        )
        patch_response = client.patch(
            f"/api/leads/{lead['_id']}",
            json={"status": "hack"},
            headers={"x-admin-password": TENANT_PASSWORD},
        )

        self.assertEqual(status_response.status_code, 422)
        self.assertEqual(password_query_response.status_code, 400)
        self.assertEqual(patch_response.status_code, 422)

    def test_list_leads_normalizes_slug_query_case(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        lead = make_lead(slug="mongo-tenant", tenant_id=str(tenant["_id"]))
        client, _, _ = create_client(tenants=[tenant], leads=[lead], legacy_enabled=True)

        response = client.get(
            "/api/leads",
            params={"slug": "MONGO-TENANT"},
            headers={"x-admin-password": TENANT_PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["slug"], "mongo-tenant")

    def test_mongo_tenant_lead_list_prefers_tenant_id_but_keeps_legacy_same_slug(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        correct_lead = make_lead(
            slug="mongo-tenant",
            tenant_id=str(tenant["_id"]),
            nombre="Propio",
        )
        legacy_lead = make_lead(
            slug="mongo-tenant",
            tenant_id=None,
            nombre="Legacy",
        )
        foreign_lead = make_lead(
            slug="mongo-tenant",
            tenant_id=str(ObjectId()),
            nombre="Ajeno",
        )
        client, _, _ = create_client(
            tenants=[tenant],
            leads=[correct_lead, legacy_lead, foreign_lead],
            legacy_enabled=True,
        )

        response = client.get(
            "/api/leads",
            params={"slug": "mongo-tenant"},
            headers={"x-admin-password": TENANT_PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        returned_names = {lead["nombre"] for lead in response.json()}
        self.assertEqual(returned_names, {"Propio", "Legacy"})

    def test_hex_slug_with_24_chars_should_resolve_as_slug_not_object_id(self):
        slug = "abcdefabcdefabcdefabcdef"
        tenant = make_tenant(slug, password=TENANT_PASSWORD)
        lead = make_lead(slug=slug, tenant_id=str(tenant["_id"]))
        client, _, _ = create_client(tenants=[tenant], leads=[lead], legacy_enabled=True)

        response = client.get(f"/api/leads/{slug}", headers={"x-admin-password": TENANT_PASSWORD})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["slug"], slug)

    def test_chat_is_rate_limited_per_client_and_slug(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=True, chat_limit=1)

        first = client.post(
            "/api/chat",
            json={"text": "Hola", "session_id": "rate-limit-session", "slug": "mongo-tenant"},
        )
        second = client.post(
            "/api/chat",
            json={"text": "Hola otra vez", "session_id": "rate-limit-session", "slug": "mongo-tenant"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.headers.get("Retry-After"), "60")

    def test_update_lead_uses_tenant_id_owner_before_slug(self):
        attacker_tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        owner_password = "OwnerPass123!"
        owner_tenant = make_tenant("owner-tenant", password=owner_password)
        foreign_owned_lead = make_lead(
            slug="mongo-tenant",
            tenant_id=str(owner_tenant["_id"]),
            _id=ObjectId(),
        )
        client, _, _ = create_client(
            tenants=[attacker_tenant, owner_tenant],
            leads=[foreign_owned_lead],
            legacy_enabled=True,
        )

        attacker_response = client.patch(
            f"/api/leads/{foreign_owned_lead['_id']}",
            json={"status": "contactado"},
            headers={"x-admin-password": TENANT_PASSWORD},
        )
        owner_response = client.patch(
            f"/api/leads/{foreign_owned_lead['_id']}",
            json={"status": "contactado"},
            headers={"x-admin-password": owner_password},
        )

        self.assertEqual(attacker_response.status_code, 401)
        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response.json()["status"], "contactado")


if __name__ == "__main__":
    unittest.main()
