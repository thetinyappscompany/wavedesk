# Manual real-number QR test (Session 0.6 exit item)

Automated tests prove the lifecycle against a mocked socket. This runbook is the
founder's REAL verification with a spare number — do not use a personal/business
number (unofficial-API ban risk).

## Prereqs
- Docker stack up: `docker compose -f deploy/compose.dev.yml up -d` (Redis + MinIO)
- MinIO bucket exists: open http://localhost:9001 (devminio/devminio123) → create
  bucket `wavedesk-sessions` (one-time)
- Generate a snapshot key (one-time, save into `services/wa-gateway/.env`):
  `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"`

## Steps

1. Start the gateway with snapshots + auth enabled:
   ```bash
   cd services/wa-gateway
   # .env: REDIS_URL=redis://localhost:6379  S3_ENDPOINT=http://localhost:9000
   #       S3_ACCESS_KEY=devminio  S3_SECRET_KEY=devminio123
   #       SESSION_SNAPSHOT_KEY=<generated>  WA_GATEWAY_INTERNAL_SECRET=dev-internal-secret
   npm run dev
   ```

2. Create a session and watch the SSE stream (keep this curl running):
   ```bash
   curl -N -X POST http://localhost:8081/sessions \
     -H "content-type: application/json" \
     -H "x-wavedesk-internal: dev-internal-secret" \
     -d '{"session_id":"test-1","workspace":"WS-00001"}'
   ```
   You'll receive `data: {"type":"qr","qr":"data:image/png;base64,..."}` frames.

3. Render the QR: paste the whole `data:image/png;base64,...` value into the
   browser address bar (or an online data-URL viewer runs offline in devtools:
   `document.body.innerHTML = '<img src="PASTE">'` in a blank tab's console).

4. On the SPARE phone: WhatsApp → Settings → Linked devices → Link a device →
   scan the QR. The SSE stream should print `{"type":"status","status":"connected"}`
   and close.

5. Verify events flow: send a WhatsApp message TO the spare number from any
   other phone, then:
   ```bash
   docker exec -it wavedesk-dev-redis-1 redis-cli XRANGE wa:events - +
   ```
   → you should see a `message.received` envelope with your message.

6. Send outbound through the gateway (replace the recipient):
   ```bash
   curl -X POST http://localhost:8081/sessions/test-1/messages \
     -H "content-type: application/json" \
     -H "x-wavedesk-internal: dev-internal-secret" \
     -d '{"to":"91XXXXXXXXXX","text":"WaveDesk gateway test"}'
   ```
   → message arrives on the recipient's WhatsApp.

7. **THE critical check — restart without re-scan:**
   - Stop the gateway with Ctrl+C (graceful shutdown → encrypted snapshot to MinIO).
   - Start it again (`npm run dev`).
   - Log line `session restore complete` with `restored_count: 1`; phone's
     Linked-devices screen still shows the device; inbound messages still land
     in `wa:events`. **No QR was scanned.** ✅

8. Bonus (S3 fallback path): stop gateway, `docker exec wavedesk-dev-redis-1
   redis-cli FLUSHALL`... **don't** — that wipes the registry too. Instead:
   `redis-cli DEL wa:auth:test-1:creds wa:auth:test-1:keys`, restart gateway →
   session must restore from the MinIO snapshot (log: "restored from encrypted
   snapshot") and stay linked.

## Exit checklist (Phase 0)
- [ ] Scan QR with test number → session connects
- [ ] Incoming WhatsApp text appears in `wa:events` within 2s
- [ ] Gateway restart → NO QR re-scan (step 7)
- [ ] Redis-loss restore from encrypted snapshot works (step 8)
