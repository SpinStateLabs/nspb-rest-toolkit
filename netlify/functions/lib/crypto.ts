/**
 * AES-256-GCM encryption for customer credentials at rest.
 *
 * The key (CREDENTIALS_ENCRYPTION_KEY, a 32-byte value, base64-encoded)
 * lives only in Netlify's environment variables -- never in the database,
 * never in this repo. Losing it means every stored credential becomes
 * unrecoverable (by design: there is no recovery path that doesn't involve
 * the key, because a recoverable-without-the-key scheme isn't actually
 * encryption). Generate it once with:
 *
 *   node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
 *
 * and set it via the connections dashboard-equivalent Netlify env var
 * (never committed, never logged, never returned by any function response).
 */

import { randomBytes, createCipheriv, createDecipheriv } from "node:crypto";

const ALGO = "aes-256-gcm";
const IV_LENGTH = 12; // 96-bit nonce, standard for GCM

function getKey(): Buffer {
  const b64 = process.env.CREDENTIALS_ENCRYPTION_KEY;
  if (!b64) {
    throw new Error(
      "CREDENTIALS_ENCRYPTION_KEY is not set -- cannot encrypt/decrypt stored credentials. " +
        "Set it as a Netlify environment variable before storing or reading any connection."
    );
  }
  const key = Buffer.from(b64, "base64");
  if (key.length !== 32) {
    throw new Error(
      `CREDENTIALS_ENCRYPTION_KEY must decode to exactly 32 bytes, got ${key.length}.`
    );
  }
  return key;
}

/** Encrypt a UTF-8 string. Returns iv || authTag || ciphertext, suitable for a BYTEA column. */
export function encryptSecret(plaintext: string): Buffer {
  const key = getKey();
  const iv = randomBytes(IV_LENGTH);
  const cipher = createCipheriv(ALGO, key, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return Buffer.concat([iv, authTag, ciphertext]);
}

/** Inverse of encryptSecret. Throws if the key is wrong or the data was tampered with. */
export function decryptSecret(stored: Buffer): string {
  const key = getKey();
  const iv = stored.subarray(0, IV_LENGTH);
  const authTag = stored.subarray(IV_LENGTH, IV_LENGTH + 16);
  const ciphertext = stored.subarray(IV_LENGTH + 16);
  const decipher = createDecipheriv(ALGO, key, iv);
  decipher.setAuthTag(authTag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}
