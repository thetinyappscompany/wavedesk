# WhatsApp Cloud API Integration — Technical Design

This document describes how to connect your product to WhatsApp so your
customers can message you (and you can message them) using Meta's **WhatsApp
Cloud API**. It covers the architecture, credentials and auth model, the
message and webhook flow, the setup steps in Meta's dashboard, and how to grow
from a single number to letting each of your customers connect their own
WhatsApp account.

Note on terminology: Meta's on-premise WhatsApp Business API was deprecated in
October 2025, so the Cloud API (Meta-hosted) is the only supported path and the
one used here. All Graph API calls in the starter target `v23.0`; bump this in
`.env` as Meta releases new versions.

## Architecture overview

There are three moving parts. Meta hosts the WhatsApp infrastructure and your
phone number. Your backend (the FastAPI service in this project) is the bridge:
it receives events from Meta over a webhook and sends messages back through the
Graph API. Your product's existing application logic talks to that backend
whenever it needs to send a message or react to an incoming one.

The flow looks like this. When an end user sends a WhatsApp message to your
business number, Meta delivers it to your backend as an HTTP POST to
`/webhook`. Your backend validates the request signature, acknowledges it with
a `200` immediately, and then routes the message into your product. When your
product wants to send a message, it calls your backend's `/send` endpoint,
which in turn calls Meta's Graph API messages endpoint at
`https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages`.

```
End user  ──WhatsApp──▶  Meta Cloud API  ──POST /webhook──▶  Your backend  ──▶  Your product
End user  ◀──WhatsApp──  Meta Cloud API  ◀──Graph API POST──  Your backend  ◀──  Your product (/send)
```

Acknowledge webhooks fast. Meta expects a `200` quickly and will retry a failed
delivery with decreasing frequency for up to seven days. Do any slow work
(database writes, bot replies, third-party calls) asynchronously — push the
event onto a queue and return `200` right away. The starter does the parsing
inline for clarity, but the `_handle_payload` function is the seam where you
would enqueue instead.

## Credentials and the auth model

Every outbound call to the Graph API carries a bearer **access token** in the
`Authorization` header. For production you want a permanent System User token
(generated in Meta Business Settings) rather than the 24-hour temporary token
shown on the dashboard's API Setup tab, which is only good for testing. The
token is scoped to a WhatsApp Business Account (WABA) and its phone number.

Four identifiers matter, all set in `.env`:

- **Access token** (`WHATSAPP_TOKEN`) — authorizes Graph API calls.
- **Phone number ID** (`WHATSAPP_PHONE_NUMBER_ID`) — the specific number you
  send from; it goes in the messages URL. This is *not* the display phone
  number, it's Meta's internal ID for it.
- **WhatsApp Business Account ID** (`WHATSAPP_BUSINESS_ACCOUNT_ID`) — the WABA
  that owns the number; needed for template management and Embedded Signup.
- **App secret** (`APP_SECRET`) — used to verify that incoming webhooks are
  really from Meta.

Inbound webhooks are secured two ways. During the one-time subscription
handshake, Meta sends a `GET /webhook` with a `hub.verify_token` that must
match your `WEBHOOK_VERIFY_TOKEN` (a string you invent). On every subsequent
`POST`, Meta signs the raw body with HMAC-SHA256 keyed by your app secret and
sends it in the `X-Hub-Signature-256` header; `app/security.py` recomputes and
compares it so forged requests are rejected.

## Sending messages and the 24-hour window

WhatsApp draws a hard line between replying and initiating. Once a user
messages you, a rolling 24-hour **customer service window** opens during which
you can send free-form messages of any type. To start a conversation, or to
message someone after that window closes, you must send a **pre-approved
message template** instead of free text. Templates are created and approved in
the Meta dashboard (or via API) and can contain variables.

The starter reflects this split. `send_text()` posts a `type: "text"` message
for use inside the window, and `send_template()` posts a `type: "template"`
message for initiating contact. The `/send` endpoint picks one based on whether
the request includes a `body` or a `template_name`. Meta's pricing is
per-conversation and depends on the template category (marketing, utility,
authentication, service), which is worth modeling if cost matters.

## Setup walkthrough (Meta dashboard)

Create a Meta app at developers.facebook.com, choosing the Business type, and
add the WhatsApp product to it. That gives you a test phone number and a
temporary token on the API Setup tab, which is enough to send your first
message to a verified test recipient. To go live you then register your own
phone number, verify your business, and generate a permanent System User token.

Configure the webhook under WhatsApp → Configuration. Point the callback URL at
your backend's public `/webhook` endpoint (use an `ngrok` tunnel in
development), enter your verify token, and subscribe to the `messages` field so
you receive inbound messages and delivery statuses. Meta immediately calls
`GET /webhook` to complete the handshake — if your service is running and the
token matches, it verifies. From then on, messages arrive as `POST /webhook`.

The end-to-end test is: send a template from `/send` to your own phone,
reply from WhatsApp, and confirm the reply shows up in your backend logs via
the webhook. Once that round-trips, the integration is working.

## Letting each customer connect their own WhatsApp (multi-tenant)

The starter assumes one business phone number — yours. If "so that customers
can connect" means you want *your* customers (other businesses) to plug their
own WhatsApp accounts into your product, you graduate to Meta's **Embedded
Signup** flow and register as a Tech Provider / Solution Partner. Embedded
Signup drops a Facebook Login popup into your onboarding UI; the customer
authorizes your app, and you receive their WABA ID, phone number ID, and a
token scoped to their account. You store those per-tenant (encrypted) and use
the same send/receive code, selecting the right credentials per customer.

Practically, that means turning the single values in `config.py` into a
per-tenant lookup: the `/send` handler and the webhook router resolve which
customer a request belongs to (webhooks include the phone number ID in the
payload) and load that tenant's token and phone number ID. The Graph API calls
themselves are unchanged. This is the standard way SaaS products offer "connect
your WhatsApp" as a feature, but it requires Meta's Tech Provider verification
and App Review, so it's a larger undertaking than the single-number setup and
worth sequencing as a phase two.

## What the starter does and does not include

The code is a working skeleton: webhook verification and signature checking,
inbound message/status parsing, and text plus template sending, all verified
with a local test client. It deliberately leaves out anything product-specific
— persistence, a message queue, ret/rate-limit handling, media messages,
interactive buttons/lists, and multi-tenancy — because those depend on your
stack. The `_handle_payload` seam and the `whatsapp.py` client are where you
extend it.
