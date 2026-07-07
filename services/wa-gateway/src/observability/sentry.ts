/** Sentry wiring WITH PII scrubbing (launch-gate item; non-negotiable #6).
 * Dormant until SENTRY_DSN is set. The scrubber DROPS any property named
 * phone/body/message (same token rule as logFields) before events leave the box. */
import * as Sentry from '@sentry/node';
import type { Logger } from 'pino';
import { isPiiFieldName } from '../logger.js';

export function scrubValue<T>(value: T): T {
  if (Array.isArray(value)) {
    return (value as unknown[]).map((item) => scrubValue(item)) as T;
  }
  if (value !== null && typeof value === 'object') {
    const clean: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (isPiiFieldName(key)) {
        continue; // dropped, not masked — nothing PII-shaped leaves the process
      }
      clean[key] = scrubValue(entry);
    }
    return clean as T;
  }
  return value;
}

function scrubBreadcrumb(crumb: Sentry.Breadcrumb): Sentry.Breadcrumb {
  if (!crumb.data) {
    return crumb;
  }
  return { ...crumb, data: scrubValue(crumb.data) };
}

export function scrubEvent<E extends Sentry.Event>(event: E): E {
  if (event.extra) {
    event.extra = scrubValue(event.extra);
  }
  if (event.contexts) {
    event.contexts = scrubValue(event.contexts);
  }
  if (event.request) {
    // Request bodies/cookies can carry message text and phone numbers wholesale.
    delete event.request.data;
    delete event.request.cookies;
    if (event.request.headers) {
      event.request.headers = scrubValue(event.request.headers);
    }
  }
  if (event.user) {
    event.user = scrubValue(event.user);
  }
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map(scrubBreadcrumb);
  }
  return event;
}

export function initSentry(dsn: string | undefined, logger: Logger): boolean {
  if (!dsn) {
    logger.info('SENTRY_DSN not set — Sentry disabled');
    return false;
  }
  Sentry.init({
    dsn,
    sendDefaultPii: false,
    beforeSend: (event) => scrubEvent(event),
    beforeBreadcrumb: (crumb) => scrubBreadcrumb(crumb),
  });
  logger.info('Sentry initialized with PII scrubbing');
  return true;
}
