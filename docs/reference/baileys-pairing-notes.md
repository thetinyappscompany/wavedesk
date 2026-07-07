# WhatsApp linked-device pairing — engine notes

Distilled from a reference integration (founder-supplied `notifier` Frappe app, which
uses [wuzapi](https://github.com/asternic/wuzapi) / Go `whatsmeow`) compared against our
Baileys gateway. Kept for when pairing misbehaves.

## The pairing protocol (any engine)
1. Fresh socket with no creds → server issues QR payloads (rotating ~every 20–60s).
2. Phone scans → server saves pair-success creds → **server closes the stream with
   code 515 (restart required)**.
3. Client MUST reconnect with the saved creds; only that second connection reaches
   `loggedIn`. Skipping step 3 = phone stuck on the loading spinner.

`whatsmeow` (wuzapi) does step 3 internally — that's why the notifier app's Frappe code
is so simple (connect → GET /session/qr → poll `{connected, loggedIn}`). With Baileys,
step 3 is OUR job: `SessionManager.handleClose` restarts on 515 (immediate), clears creds
on 401 (device unlinked), and otherwise retries with a 2s delay, bounded at 5 attempts.

## Failure modes we've hit (and their fixes)
| Symptom | Cause | Fix |
|---|---|---|
| "Connection Failure" before any QR | Library advertises stale WA web version; server rejects registration | `fetchLatestBaileysVersion()` per process in realSocket.ts |
| Phone hangs on loading after scan | 515 close not followed by reconnect | auto-restart in handleClose |
| Scan does nothing | QR expired (rotate ~60s) | poll keeps `lastQr` fresh; scan promptly |

## Status semantics (map to WD WhatsApp Number.status)
wuzapi distinguishes transport-`connected` from `loggedIn`. Baileys equivalent:
`connection: 'open'` only fires once actually logged in — our `connected` == their `Open`.

## Fallback engine (contingency, not a plan)
If Baileys breaks unrecoverably (protocol drift — root guide pitfall #3), the contained
swap is a wuzapi sidecar container speaking REST, adapted behind the same SocketFactory /
wa:events envelope. The notifier app's `wuzapi.py` documents the endpoint surface:
`/admin/users` (admin token), `/session/connect|qr|status|logout` (per-session token),
`/chat/send/*`, `/group/list`, webhook-per-instance. Nothing else in WaveDesk would change.
