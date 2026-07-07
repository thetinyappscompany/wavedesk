import { describe, expect, it } from 'vitest';
import { assertLoggable, logFields, PiiLogFieldError, REDACT_PATHS } from '../src/logger.js';

describe('assertLoggable / logFields', () => {
  it('allows safe fields, including derived message/body identifiers and metrics', () => {
    expect(() =>
      logFields({
        sessionId: 'abc',
        wa_message_id: 'X1',
        message_count: 3,
        body_length: 42,
        message_type: 'text',
        contact_ref: 'c-1',
      }),
    ).not.toThrow();
  });

  it('still bans phone even in identifier form', () => {
    expect(() => assertLoggable({ phone_id: 'x' })).toThrow(PiiLogFieldError);
  });

  it('refuses top-level phone/body/message fields', () => {
    expect(() => assertLoggable({ phone: '+919999999999' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ body: 'hi' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ message: 'secret text' })).toThrow(PiiLogFieldError);
  });

  it('refuses casing and separator variants', () => {
    expect(() => assertLoggable({ Phone: 'x' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ phoneNumber: 'x' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ phone_number: 'x' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ messageBody: 'x' })).toThrow(PiiLogFieldError);
    expect(() => assertLoggable({ waPhone: 'x' })).toThrow(PiiLogFieldError);
  });

  it('refuses nested and array-nested PII fields', () => {
    expect(() => assertLoggable({ event: { payload: { phone: 'x' } } })).toThrow(
      PiiLogFieldError,
    );
    expect(() => assertLoggable({ items: [{ ok: 1 }, { body: 'x' }] })).toThrow(PiiLogFieldError);
  });

  it('does not flag unrelated words containing substrings', () => {
    // "phonetic" tokenizes to ["phonetic"], not ["phone"] — allowed.
    expect(() => assertLoggable({ phonetic: 'x', embodyment: 'y' })).not.toThrow();
  });

  it('reports the offending key path', () => {
    try {
      assertLoggable({ event: { phone: 'x' } });
      expect.unreachable();
    } catch (err) {
      expect((err as PiiLogFieldError).keyPath).toBe('event.phone');
    }
  });
});

describe('pino redact config', () => {
  it('covers phone/body/message at top and nested levels', () => {
    for (const field of ['phone', 'body', 'message']) {
      expect(REDACT_PATHS).toContain(field);
      expect(REDACT_PATHS).toContain(`*.${field}`);
    }
  });
});
