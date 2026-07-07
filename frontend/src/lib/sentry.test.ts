import { describe, expect, it } from 'vitest';
import { isPiiFieldName, scrubEvent, scrubValue } from './sentry';
import type * as Sentry from '@sentry/react';

describe('frontend Sentry PII scrubber', () => {
  it('classifies field names like the gateway rule', () => {
    expect(isPiiFieldName('phone')).toBe(true);
    expect(isPiiFieldName('phoneNumber')).toBe(true);
    expect(isPiiFieldName('body')).toBe(true);
    expect(isPiiFieldName('message')).toBe(true);
    expect(isPiiFieldName('wa_message_id')).toBe(false);
    expect(isPiiFieldName('body_length')).toBe(false);
    expect(isPiiFieldName('chat_id')).toBe(false);
  });

  it('drops PII deep in objects and arrays', () => {
    expect(
      scrubValue({ a: [{ phone: 'x', keep: 1 }], b: { messageBody: 'x' }, chat_id: 'c1' }),
    ).toEqual({ a: [{ keep: 1 }], b: {}, chat_id: 'c1' });
  });

  it('scrubs event extra/user/breadcrumbs', () => {
    const event = {
      extra: { phone: 'x', route: '/inbox' },
      user: { id: 'u1', phone: 'x' },
      breadcrumbs: [{ data: { body: 'x', click: 'send' } }],
    } as unknown as Sentry.Event;
    const scrubbed = scrubEvent(event);
    expect(scrubbed.extra).toEqual({ route: '/inbox' });
    expect(scrubbed.user).toEqual({ id: 'u1' });
    expect(scrubbed.breadcrumbs?.[0]?.data).toEqual({ click: 'send' });
  });
});
