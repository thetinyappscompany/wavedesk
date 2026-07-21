# Brief: make the gateway's WhatsApp pairing survive restarts

**Status:** diagnosis complete, fix not yet implemented.
**Symptom:** a paired Baileys number goes back to needing a QR re-scan after
gateway/Redis restarts. This has happened repeatedly (first in the July 16
Docker crash, again on CapRover). It is the one thing standing between the
platform and a rock-solid WhatsApp connection.

## How persistence is designed (and where it actually breaks)

The design (master doc §2.2) is sound: hot auth state in Redis
(`src/baileys/authStore.ts`), AES-256-GCM-encrypted snapshots to the
`wavedesk-sessions` S3 bucket every 5 minutes (`src/baileys/snapshot.ts`,
`SessionManager.snapshotAll`), and boot-time `restoreAll()` so a restart never
needs a QR. Four concrete gaps defeat it in production:

### Gap 1 — snapshots silently disable themselves (most likely root cause)
`SESSION_SNAPSHOT_KEY` unset → `snapshotKey: undefined`
([index.ts:24](../../services/wa-gateway/src/index.ts)) → `snapshotAll()`
returns 0 forever, and the restore branch in `startSocket` is skipped
([sessionManager.ts:125](../../services/wa-gateway/src/baileys/sessionManager.ts)).
**No warning is logged anywhere.** If that one env var is missing on
`wd-gateway`, the ONLY copy of the pairing is Redis — and gap 2 kills that.

### Gap 2 — Redis is the registry AND probably not durable
`restoreAll()` enumerates the `wa:sessions` hash **from Redis**
(sessionManager.ts:107-118). CapRover's one-click Redis ships with **no AOF
and no persistent volume** unless configured (runbook §2 asks for AOF but it's
an easily-missed manual step). A Redis restart therefore wipes both the hot
auth state and the registry — so even with valid S3 snapshots sitting in the
bucket, boot restore finds zero sessions to restore. (Undocumented escape
hatch: clicking **Reconnect** on /numbers re-registers the same session id and
DOES hit the snapshot-restore path — but nothing tells the operator that.)

### Gap 3 — a fresh pairing is unprotected for up to 5 minutes
Snapshots run on a 5-minute timer + graceful shutdown. A crash/OOM-kill (not
SIGTERM) right after pairing loses the creds entirely; mid-life it loses up to
5 minutes of signal-key churn, which can surface as a broken session after
restore.

### Gap 4 — no way to see any of this
The gateway is internal-only (`srv-captain--wd-gateway:8081`, no public DNS —
verified), so snapshot health is invisible unless you read container logs.

## The fix (gateway code, ~half-day including tests)

1. **Fail loud:** at boot, if `SESSION_SNAPSHOT_KEY` is unset, log an ERROR
   every start (or refuse to start when `NODE_ENV=production`). A silently
   disabled backstop is worse than none.
2. **Make Redis disposable:** persist the registry in S3 alongside the
   snapshots (e.g. `session-snapshots/registry.json`, updated on
   register/destroy). At boot, when the Redis registry is empty, fall back to
   the S3 registry so `restoreAll()` recovers from a total Redis wipe with no
   human action.
3. **Snapshot at the moments that matter:** trigger `snapshotAll()` (a) right
   after creds promotion — the CREDS_PROMOTE_GRACE_MS path — so a brand-new
   pairing is durable within seconds, and (b) debounced (~30s) on `saveCreds`,
   keeping the 5-min timer as the floor.
4. **Expose it:** include `snapshots_enabled` + `last_snapshot_at` in the
   GET /sessions response so the backend/admin panel can surface a
   "pairing durability at risk" warning.

## Infra checklist (founder, ~5 minutes, do BEFORE re-pairing)

- [ ] `wd-gateway` env has `SESSION_SNAPSHOT_KEY` (generate:
      `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"`),
      plus `S3_ENDPOINT` / `S3_BUCKET=wavedesk-sessions` / `S3_ACCESS_KEY` /
      `S3_SECRET_KEY` (runbook §7 table).
- [ ] `wavedesk-sessions` bucket exists in MinIO.
- [ ] Redis app: add a persistent volume AND start with `--appendonly yes`
      (runbook §2).

## Verification (after fix + checklist)

1. Pair a number (burner SIM) → wait ~1 min → check gateway logs for a
   snapshot write.
2. CapRover → restart `wd-gateway` → number returns **connected with no QR**.
3. Restart the `redis` app → restart `wd-gateway` → still connected with no
   QR (this is the case that fails today; it proves gap 2 is closed).
4. Send + receive one message to confirm the restored session actually works.

**Current live state (checked 2026-07-21):** the active workspace has zero
numbers connected, so nothing is at risk this minute — which makes now the
right time to land this before the next pairing.
