# Merge & Staging Runbook (Phase 5 close-out)

Generated 2026-07-13. Reflects the verified git state at that time.

## 1. Where things actually are

- **`origin/main` is at P3.2** (`4a2e854`, "Merge pull request #1"). Only the
  routing epic's code is on `main`.
- **Everything else — P3.3 → P5 (44 commits)** lives on the stacked feature
  branches, tip = **`feat/p5-ip-allowlist`**. It is a **linear, CI-green**
  superset of all epics P3.3 through the P5 IP-allowlist.
- PRs **#16–#22 are OPEN**; #2–#15 show "MERGED" but they merged into their
  *intermediate base branches*, not into `main` — so their code reached `main`
  only as far as P3.2. (This is the stacked-PR-on-feature-branch trap; see §4.)
- **Verified 2026-07-13:** `feat/p5-ip-allowlist` merges into `origin/main`
  with **zero conflicts**.

## 2. Recommended path — one consolidation PR (clean, fast)

Because the tip branch is linear, CI-green, and merges cleanly, land it all in a
single reviewed PR:

```bash
git fetch origin
gh pr create --base main --head feat/p5-ip-allowlist \
  --title "Land Phase 3.3 → Phase 5 (P5 close-out)" \
  --body "Consolidates all epics P3.3 → P5 IP-allowlist. CI green; merges clean."
# review, then:
gh pr merge <that-PR#> --merge     # or --squash for a single commit
```

Then close the now-superseded open PRs (their content is included):

```bash
for n in 16 17 18 19 20 21 22; do gh pr close $n \
  --comment "Superseded by the consolidation PR into main."; done
```

Pull `main` locally afterwards: `git checkout main && git pull`.

## 3. Alternative — merge #16–#22 individually (preserves per-PR review)

Each open PR's base still points at the *prior* feature branch, so they must be
merged **bottom-up** and each retargeted to `main` as the one below it lands:

```bash
for n in 16 17 18 19 20 21 22; do
  gh pr edit $n --base main          # retarget onto main
  gh pr merge $n --merge             # merge; resolve any conflict, then continue
done
```

Slower and more conflict-prone than §2 (retargeting a stacked PR onto a moved
base can surface merge noise). Prefer §2 unless you specifically want each epic
as its own merge commit on `main`.

## 4. Lesson for next time

Stack PRs **on `main`**, not on the previous feature branch — or use a tool like
Graphite. Merging a chain whose bases are feature branches records "MERGED" while
the code only advances the intermediate branch, which is what produced the
"merged but not on main" confusion here.

---

## 5. Staging bring-up checklist (unblocks every mocked round-trip)

Everything below is currently mocked in tests and **unproven live**. Bringing up
staging lets each be verified for real.

### Infra
- [ ] Provision a staging VM (Mumbai region for DPDP data residency).
- [ ] Install Docker + Docker Compose; `docker compose -f deploy/compose.dev.yml up`
      brings up MariaDB, Redis, MinIO, Qdrant, **whisper** (now a real
      faster-whisper image), wa-gateway, frontend.
- [ ] Public HTTPS URL (Caddy/Traefik + Let's Encrypt) → needed for the Zoho and
      Meta webhooks that cannot reach localhost.

### Secrets (env only — never commit)
- [ ] `WAVEDESK_AI_SECRET` (AES key for BYOK + 2FA secrets), `NVIDIA_API_KEY`,
      `ANTHROPIC_API_KEY` (**rotate the pasted keys first**).
- [ ] `ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN/ORG_ID`, `ZOHO_WEBHOOK_TOKEN`
      (self-client refresh token still needed).
- [ ] `SESSION_SNAPSHOT_KEY`, `S3_*` (MinIO creds), gateway `WA_GATEWAY_INTERNAL_SECRET`.
- [ ] `WHISPER_URL` (defaults to `http://whisper:9010` in compose).

### Live verifications to run once staging is up
- [ ] **Media pipeline (P4.5):** inbound image/voice → gateway downloads → MinIO
      → `api/media.media_url` presigns → bubble renders; voice note → whisper
      transcript stored → re-run through flagging/auto-ticket.
- [ ] **RAG (P4.3):** Qdrant/NVIDIA round-trip — ingest a KB doc, ask a question,
      confirm answer-or-handoff.
- [ ] **Zoho billing (P5):** register the webhook at the public URL; run
      signup → checkout → `subscription_activation` webhook → entitlement flips;
      `payment_success` top-up → idempotent wallet credit; nightly
      `reconcile_all` clean for 14 days (exit criterion).
- [ ] **Wallet:** top-up → AI overage deduction → low-balance → double-charge
      test under forced RQ retries.

### Meta Business Verification (critical path — start now)
- [ ] Complete Meta Business Verification for REFORMIQO Pvt Ltd → unlocks Cloud
      API embedded signup + template submission (P3.8 tail) and the only
      sanctioned at-scale broadcast path. **Never test on a real personal SIM.**

### Production-hardening (Phase 5 remainder, staging-gated)
- [ ] Zapier/Slack/Sheets connectors (need their OAuth app creds).
- [ ] Load test (500 agents, 200 msg/s), OWASP ZAP pen-test, K8s HPA/PDB,
      public status page, backup-restore drill (RPO ≤ 15m / RTO ≤ 1h).
