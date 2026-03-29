# Release Checklist

## Before Release

- Confirm `main` is green locally:
  - `py -m unittest discover -s backend/tests -v`
  - `npm ci`
  - `npm run build`
- Confirm `LEGACY_FALLBACK_ENABLED=true` for this release unless you explicitly close the legacy cutover checklist.
- Confirm backend secrets exist in the deploy provider:
  - `MONGO_URL`
  - `DB_NAME`
  - `DEEPSEEK_API_KEY`
  - `CORS_ORIGINS`
  - `PORT`
  - `ADMIN_PASSWORD`
- Confirm optional hardening envs are set or intentionally omitted:
  - `RATE_LIMIT_WINDOW_SECONDS`
  - `CHAT_RATE_LIMIT_PER_WINDOW`
  - `AUTH_RATE_LIMIT_PER_WINDOW`
- Confirm frontend env:
  - `REACT_APP_BACKEND_URL`

## Backend Deploy

- Deploy the backend first.
- Verify startup succeeds and Mongo indexes initialize.
- Verify `/api/health` returns `200`.
- Verify CORS matches the real frontend origins.
- Verify structured logs appear for normal traffic.

## Frontend Deploy

- Deploy the frontend after backend is healthy.
- Confirm SPA routing fallback is enabled.
- Confirm `REACT_APP_BACKEND_URL` resolves to the backend serving `/api`.
- Open:
  - `/:slug`
  - `/crm`
  - `/crm/:slug`
  - `/internal/tenants`

## Manual Smoke Test After Deploy

- Public tenant:
  - `GET /api/business/{slug_mongo}` -> `200`
  - chat replies
  - lead is stored with `slug` and `tenant_id`
- CRM tenant:
  - login with tenant password
  - list leads
  - open detail
  - update status
  - save notes
- Internal panel:
  - login with global password
  - list tenants
  - edit tenant
  - change `system_prompt`
  - activate/deactivate tenant
- Legacy path:
  - `GET /api/business/{slug_legacy}` -> `200`
  - chat replies
  - lead is stored without `tenant_id`

## Security Checks Before Marking Release Good

- Invalid slug returns `404` in public route and CRM route.
- `is_active=false` blocks public business, chat and tenant CRM auth.
- `/api/internal/tenants` still works with global password even if legacy fallback is disabled.
- Public business payload does not expose `system_prompt`.
- `?password=` is rejected on lead endpoints.
- Invalid lead status returns `422`.
- Auth/chat rate limiting returns `429` and logs `source=RATE_LIMIT`.

## Legacy Cutover Checklist

Do not disable legacy until all of these are true:

- Mongo tenants cover every active production slug that still matters.
- CRM tenant login works for migrated tenants.
- Internal tenant panel works with `LEGACY_FALLBACK_ENABLED=false`.
- Legacy slugs intentionally return `404` when fallback is off.
- Logs confirm no required traffic still depends on legacy fallback.

## Rollback Triggers

Rollback or pause release if any of these happen:

- `/api/health` fails after deploy.
- Public tenant pages stop loading.
- Chat stops responding for Mongo tenants.
- CRM auth fails for valid tenant passwords.
- Internal tenant panel becomes inaccessible.
- Unexpected `401`, `404` or `429` spikes appear in logs.

## Rollback Actions

- Revert frontend to the previous stable build if the issue is UI-only.
- Revert backend to the previous stable build if public/chat/CRM/API behavior changed unexpectedly.
- Re-enable `LEGACY_FALLBACK_ENABLED=true` if a legacy traffic path was disabled too early.
- Keep notes of the exact failing slug, endpoint and timestamp before retrying deploy.
