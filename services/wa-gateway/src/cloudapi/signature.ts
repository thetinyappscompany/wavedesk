/** Meta webhook signature validation (ported from the Cloud API reference design:
 * docs/reference/cloud-api-integration-design.md). Meta signs every POST body with
 * HMAC-SHA256 keyed by the app secret → X-Hub-Signature-256: sha256=<hex>. */
import { createHmac, timingSafeEqual } from 'node:crypto';

export function verifyMetaSignature(
  rawBody: Buffer,
  signatureHeader: string | undefined,
  appSecret: string | undefined,
): boolean {
  if (!appSecret) {
    // Unlike the Python starter, missing secret does NOT skip validation in
    // WaveDesk — refuse everything instead (fail closed).
    return false;
  }
  if (!signatureHeader?.startsWith('sha256=')) {
    return false;
  }
  const expected = createHmac('sha256', appSecret).update(rawBody).digest();
  const received = Buffer.from(signatureHeader.slice('sha256='.length), 'hex');
  return received.length === expected.length && timingSafeEqual(received, expected);
}
