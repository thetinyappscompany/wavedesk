import { describe, expect, it } from 'vitest';
import type * as Sentry from '@sentry/node';
import { scrubEvent, scrubValue } from '../src/observability/sentry.js';

describe('Sentry PII scrubber', () => {
  it('drops phone/body/message fields at any depth, keeps safe fields', () => {
    const scrubbed = scrubValue({
      session_id: 's1',
      phone: '+919999999999',
      nested: { messageBody: 'secret', wa_message_id: 'WAMID.1', list: [{ body: 'x', ok: 1 }] },
    });
    expect(scrubbed).toEqual({
      session_id: 's1',
      nested: { wa_message_id: 'WAMID.1', list: [{ ok: 1 }] },
    });
  });

  it('scrubs extra, contexts, user, breadcrumbs and strips request bodies', () => {
    const event = {
      extra: { phone: 'x', trace_id: 't1' },
      contexts: { job: { message: 'hi', queue: 'wd_realtime' } },
      user: { id: 'u1', phone: 'x' },
      request: {
        data: { body: 'whole message' },
        cookies: { sid: 'secret' },
        headers: { host: 'gw', authorization: 'Bearer x' },
      },
      breadcrumbs: [{ message: 'crumb', data: { phone: 'x', step: 2 } }],
    } as unknown as Sentry.Event;

    const scrubbed = scrubEvent(event);
    expect(scrubbed.extra).toEqual({ trace_id: 't1' });
    expect(scrubbed.contexts).toEqual({ job: { queue: 'wd_realtime' } });
    expect(scrubbed.user).toEqual({ id: 'u1' });
    expect(scrubbed.request?.data).toBeUndefined();
    expect(scrubbed.request?.cookies).toBeUndefined();
    expect(scrubbed.breadcrumbs?.[0]?.data).toEqual({ step: 2 });
  });
});
