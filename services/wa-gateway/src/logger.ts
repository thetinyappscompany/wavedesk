import { pino, type Logger, type LoggerOptions } from 'pino';

/**
 * PII log hygiene (root CLAUDE.md non-negotiable #6, master doc §6.5a):
 * no raw phone numbers or message bodies may ever reach logs or Sentry.
 *
 * Two layers of defense:
 *  1. `assertLoggable()` — refuses (throws) any log-field object containing a key
 *     named phone/body/message (any casing, snake_case or camelCase, at any depth).
 *     Use it via `logFields()` at every structured-logging call site.
 *  2. pino `redact` paths — belt-and-braces for anything that slips through
 *     (e.g. objects logged by framework internals).
 */

/** "phone" is banned unconditionally — even IDs can correlate to a person. */
const ALWAYS_FORBIDDEN = ['phone'] as const;
/** "body"/"message" are content fields — banned unless the key is clearly a derived value. */
const CONTENT_TOKENS = ['body', 'message'] as const;
/** Tokens marking a key as an identifier/metric, not content: wa_message_id, body_length… */
const SAFE_MARKER_TOKENS = new Set([
  'id',
  'ids',
  'count',
  'length',
  'len',
  'size',
  'total',
  'type',
  'status',
]);

export class PiiLogFieldError extends Error {
  constructor(public readonly keyPath: string) {
    super(
      `Refusing to log field "${keyPath}": fields named phone/body/message are banned. ` +
        `Log a masked or derived value instead (e.g. contact_ref, message_id, body_length).`,
    );
    this.name = 'PiiLogFieldError';
  }
}

/** Split a key into lowercase word tokens: "waPhoneNumber" -> ["wa","phone","number"]. */
function keyTokens(key: string): string[] {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function isForbiddenKey(key: string): boolean {
  const tokens = keyTokens(key);
  if (ALWAYS_FORBIDDEN.some((banned) => tokens.includes(banned))) {
    return true;
  }
  const hasContentToken = CONTENT_TOKENS.some((banned) => tokens.includes(banned));
  const hasSafeMarker = tokens.some((t) => SAFE_MARKER_TOKENS.has(t));
  return hasContentToken && !hasSafeMarker;
}

/** Throws PiiLogFieldError if any key at any depth is a banned PII field name. */
export function assertLoggable(fields: Record<string, unknown>, path = ''): void {
  for (const [key, value] of Object.entries(fields)) {
    const keyPath = path ? `${path}.${key}` : key;
    if (isForbiddenKey(key)) {
      throw new PiiLogFieldError(keyPath);
    }
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      assertLoggable(value as Record<string, unknown>, keyPath);
    }
    if (Array.isArray(value)) {
      value.forEach((item, i) => {
        if (item !== null && typeof item === 'object') {
          assertLoggable(item as Record<string, unknown>, `${keyPath}[${String(i)}]`);
        }
      });
    }
  }
}

/** Validate-and-return: `logger.info(logFields({ sessionId }), 'session started')`. */
export function logFields<T extends Record<string, unknown>>(fields: T): T {
  assertLoggable(fields);
  return fields;
}

/** Redact paths as the second line of defense (framework-level logs). */
export const REDACT_PATHS: string[] = [
  'phone',
  '*.phone',
  '*.*.phone',
  'body',
  '*.body',
  '*.*.body',
  'message',
  '*.message',
  '*.*.message',
  'req.headers.authorization',
  'req.headers.cookie',
];

export function loggerOptions(level: string): LoggerOptions {
  return {
    level,
    redact: { paths: REDACT_PATHS, censor: '[redacted]' },
    base: { service: 'wa-gateway' },
    timestamp: pino.stdTimeFunctions.isoTime,
  };
}

export function createLogger(level = 'info'): Logger {
  return pino(loggerOptions(level));
}
