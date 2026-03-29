import unittest
from unittest.mock import patch

from backend.tests.support import create_client, make_tenant, server


GLOBAL_PASSWORD = "GlobalPass123!"
TENANT_PASSWORD = "TenantPass123!"


class AuthAndTenantsTests(unittest.TestCase):
    def test_internal_admin_auth_still_works_when_legacy_is_disabled(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=False)

        response = client.get("/api/internal/tenants", headers={"x-admin-password": GLOBAL_PASSWORD})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["slug"], "mongo-tenant")

    def test_global_password_no_longer_authenticates_tenant_routes_when_legacy_is_disabled(self):
        client, _, _ = create_client(legacy_enabled=False)

        response = client.get("/api/leads", params={"slug": "cafe-minima"}, headers={"x-admin-password": GLOBAL_PASSWORD})

        self.assertEqual(response.status_code, 401)

    def test_inactive_tenant_is_blocked_on_public_chat_and_crm(self):
        inactive_tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD, is_active=False)
        client, fake_db, _ = create_client(tenants=[inactive_tenant], legacy_enabled=True)

        business_response = client.get("/api/business/mongo-tenant")
        chat_response = client.post(
            "/api/chat",
            json={"text": "Necesito una cita", "session_id": "inactive-session", "slug": "mongo-tenant"},
        )
        crm_response = client.get("/api/leads", params={"slug": "mongo-tenant"}, headers={"x-admin-password": TENANT_PASSWORD})

        self.assertEqual(business_response.status_code, 404)
        self.assertEqual(chat_response.status_code, 404)
        self.assertEqual(crm_response.status_code, 401)
        self.assertEqual(fake_db.leads.docs, [])

    def test_public_business_payload_hides_internal_fields_for_legacy_and_mongo(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD, system_prompt="Prompt secreto")
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=True)

        legacy_response = client.get("/api/business/cafe-minima")
        mongo_response = client.get("/api/business/mongo-tenant")

        self.assertEqual(legacy_response.status_code, 200)
        self.assertNotIn("system_prompt", legacy_response.json())
        self.assertNotIn("_source", legacy_response.json())

        self.assertEqual(mongo_response.status_code, 200)
        self.assertNotIn("_source", mongo_response.json())
        self.assertEqual(mongo_response.json()["business_name"], "Tenant Demo")

    def test_legacy_business_returns_404_when_fallback_is_disabled(self):
        client, _, _ = create_client(legacy_enabled=False)

        response = client.get("/api/business/cafe-minima")

        self.assertEqual(response.status_code, 404)

    def test_business_lookup_normalizes_slug_case(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=True)

        response = client.get("/api/business/MONGO-TENANT")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["business_name"], "Tenant Demo")

    def test_internal_tenant_create_assigns_safe_default_system_prompt(self):
        client, fake_db, server = create_client(legacy_enabled=True)

        response = client.post(
            "/api/internal/tenants",
            headers={"x-admin-password": GLOBAL_PASSWORD},
            json={
                "slug": "tenant-nuevo",
                "business_name": "Tenant Nuevo",
                "phone": "+52 55 9999 9999",
                "hours": "9:00 - 18:00",
                "address": "CDMX",
                "avatar": "https://example.com/avatar.png",
                "image": "https://example.com/image.png",
                "greeting": "Hola",
                "admin_password": TENANT_PASSWORD,
                "is_active": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        created = next(doc for doc in fake_db.tenants.docs if doc["slug"] == "tenant-nuevo")
        self.assertEqual(created["system_prompt"], server.get_default_system_prompt())
        self.assertEqual(response.json()["system_prompt"], server.get_default_system_prompt())

    def test_internal_tenant_detail_returns_system_prompt_for_authorized_ui(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD, system_prompt="Prompt interno")
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=True)

        response = client.get(
            "/api/internal/tenants/mongo-tenant",
            headers={"x-admin-password": GLOBAL_PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["system_prompt"], "Prompt interno")

    def test_failed_admin_auth_is_rate_limited(self):
        tenant = make_tenant("mongo-tenant", password=TENANT_PASSWORD)
        client, _, _ = create_client(tenants=[tenant], legacy_enabled=True, auth_limit=1)

        with patch.object(server.logger, "info") as info_mock:
            first = client.get(
                "/api/leads",
                params={"slug": "mongo-tenant"},
                headers={"x-admin-password": "wrong-password"},
            )
            second = client.get(
                "/api/leads",
                params={"slug": "mongo-tenant"},
                headers={"x-admin-password": "wrong-password"},
            )

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.headers.get("Retry-After"), "60")
        self.assertTrue(
            any(
                "endpoint=tenant_admin_auth" in call.args[0]
                and "source=RATE_LIMIT" in call.args[0]
                and "scope=tenant" in call.args[0]
                for call in info_mock.call_args_list
            )
        )

    def test_internal_admin_rate_limit_is_logged(self):
        client, _, _ = create_client(legacy_enabled=True, auth_limit=1)

        with patch.object(server.logger, "info") as info_mock:
            first = client.get(
                "/api/internal/tenants",
                headers={"x-admin-password": "wrong-password"},
            )
            second = client.get(
                "/api/internal/tenants",
                headers={"x-admin-password": "wrong-password"},
            )

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 429)
        self.assertTrue(
            any(
                "endpoint=internal_admin_auth" in call.args[0]
                and "source=RATE_LIMIT" in call.args[0]
                and "scope=internal" in call.args[0]
                for call in info_mock.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
