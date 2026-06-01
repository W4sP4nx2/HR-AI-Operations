# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Email the maintainer
(add your address here) with details and steps to reproduce. We aim to acknowledge
within 72 hours.

## Security posture

This project is designed to be **safe by default for local development** and
**hardenable for production** via configuration.

### Authentication & authorization
- **JWT** bearer tokens (`core/security.py`); bcrypt password hashing with the
  72-byte truncation bcrypt requires.
- **RBAC**: `viewer → analyst → manager → admin`. Sensitive routes (policy
  ingest/delete, approvals) require `manager+`.
- **`AUTH_ENFORCE`** (default `false`): advisory mode keeps the zero-secret demo
  usable. **Set `AUTH_ENFORCE=true` in production** to enforce 401/403.
- **`JWT_SECRET`**: a long random value is **required** in production. The app logs
  a warning at startup if enforcement is on while the insecure default is in use.
- **Google OAuth** via Authlib when `GOOGLE_CLIENT_ID/SECRET` are set.

### Inbound webhooks
- `WEBHOOK_SECRET` gates `/webhooks/*`. Two verification modes:
  - **HMAC** (recommended): `X-Webhook-Signature: sha256=<hexdigest>` over the raw
    body, constant-time compared.
  - **Shared secret**: `X-Webhook-Secret: <secret>` (simple/back-compat).
- With no secret configured (dev), verification is skipped.

### Transport & headers
- Security headers on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.
- **CORS** is restricted to `CORS_ORIGINS` (default `localhost:3000`); lock this to
  your real dashboard origin in production. Terminate **TLS** at the gateway/LB.

### Data
- No secrets are hardcoded; all config comes from the environment
  (`pydantic-settings`). `.gitignore` excludes `.env*`, `*.db`, and `sample_data/`.
- Immutable **audit log** of every agent action and human decision (approve/reject).

## Production hardening checklist
- [ ] `AUTH_ENFORCE=true` and a strong, rotated `JWT_SECRET`.
- [ ] `WEBHOOK_SECRET` set; webhook senders use HMAC signatures.
- [ ] `CORS_ORIGINS` locked to your domain(s); TLS terminated upstream.
- [ ] `DATABASE_URL` → PostgreSQL; backups configured.
- [ ] Secret scanning in CI (e.g. `gitleaks`); confirm no secrets in git history.
- [ ] Rate limiting at the gateway (token bucket per user/tenant).
- [ ] Restrict scraper egress (allowlist domains) for URL intake.
