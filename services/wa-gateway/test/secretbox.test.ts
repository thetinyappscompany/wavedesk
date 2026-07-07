import { randomBytes } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { decrypt, encrypt, parseKey } from '../src/crypto/secretbox.js';

describe('secretbox (AES-256-GCM)', () => {
  const key = randomBytes(32);

  it('round-trips', () => {
    const plaintext = JSON.stringify({ creds: 'secret-session-material', n: 42 });
    expect(decrypt(encrypt(plaintext, key), key)).toBe(plaintext);
  });

  it('produces distinct ciphertexts per call (fresh IV)', () => {
    expect(encrypt('same', key)).not.toBe(encrypt('same', key));
  });

  it('rejects tampered ciphertext', () => {
    const blob = Buffer.from(encrypt('payload', key), 'base64');
    blob[blob.length - 1] = blob[blob.length - 1]! ^ 0xff;
    expect(() => decrypt(blob.toString('base64'), key)).toThrow();
  });

  it('rejects the wrong key', () => {
    const blob = encrypt('payload', key);
    expect(() => decrypt(blob, randomBytes(32))).toThrow();
  });

  it('parseKey enforces 32 bytes', () => {
    expect(() => parseKey(Buffer.from('short').toString('base64'))).toThrow(/32 bytes/);
    expect(parseKey(randomBytes(32).toString('base64')).length).toBe(32);
  });
});
