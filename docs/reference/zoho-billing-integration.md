# Zoho Billing Integration (Phase 5 reference)

WaveDesk's subscription + wallet-top-up billing runs on **Zoho Billing** (system of
record for money) with **Razorpay** configured as the gateway inside it. WaveDesk is
the source of truth for **entitlements**, which derive **only** from verified Zoho
webhooks (root non-negotiable #3) plus a nightly API reconciliation net.

> **No secrets in this file.** All credentials live in the deployed bench's gitignored
> env only. This is the design/spec, captured so Phase 5 can be built without re-deriving it.

Deployment name/brand: **AI Assist** (`aiassist.erpera.io`); Zoho org **60040953029**, India DC.

## 1. Auth — Self Client (server-to-server)
WaveDesk makes headless API calls, so use a **Self Client** (not the web-app OAuth
redirect flow). One-time: generate a grant token (scope `ZohoBilling.fullaccess.all`,
or granular subscriptions/invoices READ + customers/hostedpages CREATE) → exchange for
a **refresh token**. Access tokens (1-hr TTL) are minted from the refresh token per call.

## 2. Endpoints (India DC)
| | Value |
|---|---|
| Token endpoint | `https://accounts.zoho.in/oauth/v2/token` |
| Billing API base | `https://www.zohoapis.in/billing/v1/` |
| Org header | `X-com-zoho-subscriptions-organizationid: 60040953029` |
| Auth header | `Authorization: Zoho-oauthtoken <access_token>` |

## 3. Env vars (deployed bench only)
`ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORG_ID=60040953029`,
`ZOHO_DC=in`, `ZOHO_WEBHOOK_TOKEN`.

## 4. Webhook (the authoritative entitlement path)
- Frappe endpoint: `wavedesk.api.billing.zoho_webhook` →
  `https://aiassist.erpera.io/api/method/wavedesk.api.billing.zoho_webhook`
- Verified via the `X-Webhook-Token` header, then processed **idempotently** (Zoho retries;
  the wallet ledger's idempotency key prevents double-credit).

| Zoho event | WaveDesk action |
|---|---|
| subscription_created / activation | `WD Subscription` → `active`; set zoho ids, `current_period_end`, `addons` |
| subscription_renewed | roll `current_period_end` |
| subscription_cancelled / expired | → `cancelled` (end-of-period access) |
| payment_declined / failed | → `past_due` (dunning grace) |
| invoice paid | wallet top-up invoice → idempotent `wallet.credit()`; else mirror to `WD Invoice Ref` |

**Add-on mapping:** the `ai-addon` code on a subscription sets
`WD Subscription.addons.ai_addon = true` → `has_feature('ai_addon')` unlocks the Phase 4 AI layer.

## 5. Nightly reconciliation (safety net)
`GET /subscriptions`, `GET /invoices` → reconcile `WD Subscription` / `WD Invoice Ref`
against Zoho. Never edits entitlements optimistically; heals drift only.

## 6. Catalog → WaveDesk mapping
`WD Plan.zoho_plan_code` / `zoho_addon_codes` map Zoho codes to WaveDesk plans. Seeded
defaults (setup/install.py): `WD-STARTER/PRO/BUSINESS`, add-ons `WD-ADDON-AI`,
`WD-ADDON-NUMBER`, `WD-ADDON-AGENT`. **Reconcile these with the real Zoho codes** the
founder creates (proposed there: `wavedesk-starter/pro/business`, `ai-addon`, `topup-500..10000`).

## 7. Non-negotiables baked in
- Entitlements activate ONLY from verified webhooks (#3); reconciliation is a net, not a source.
- Every webhook token-verified + idempotent (#2 — append-only ledger, unique idempotency key).
- Zoho = source of truth for money; WaveDesk = source of truth for entitlements.

## Status
Phase 5, **staging-gated** (Zoho can't POST to localhost). Blocked on: WaveDesk public URL
(staging VM) to register the webhook, the founder's final plan/add-on/top-up codes, and the
self-client refresh token.
