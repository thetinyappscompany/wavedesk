/** Sentry for the SPA — dormant until VITE_SENTRY_DSN is set.
 * Same PII rule as the gateway: fields named phone/body/message never leave
 * the browser (dropped, not masked). Number masking itself is Phase 1. */
import * as Sentry from '@sentry/react';

const ALWAYS_FORBIDDEN = ['phone'];
const CONTENT_TOKENS = ['body', 'message'];
const SAFE_MARKERS = new Set(['id', 'ids', 'count', 'length', 'len', 'size', 'total', 'type', 'status']);

function keyTokens(key: string): string[] {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

export function isPiiFieldName(key: string): boolean {
  const tokens = keyTokens(key);
  if (ALWAYS_FORBIDDEN.some((t) => tokens.includes(t))) {
    return true;
  }
  const hasContent = CONTENT_TOKENS.some((t) => tokens.includes(t));
  return hasContent && !tokens.some((t) => SAFE_MARKERS.has(t));
}

export function scrubValue<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => scrubValue(item)) as T;
  }
  if (value !== null && typeof value === 'object') {
    const clean: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (isPiiFieldName(key)) {
        continue;
      }
      clean[key] = scrubValue(entry);
    }
    return clean as T;
  }
  return value;
}

export function scrubEvent<E extends Sentry.Event>(event: E): E {
  if (event.extra) {
    event.extra = scrubValue(event.extra);
  }
  if (event.contexts) {
    event.contexts = scrubValue(event.contexts);
  }
  if (event.user) {
    event.user = scrubValue(event.user);
  }
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map((crumb) => ({
      ...crumb,
      data: crumb.data ? scrubValue(crumb.data) : crumb.data,
    }));
  }
  return event;
}

export function initSentry(): boolean {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
  if (!dsn) {
    return false;
  }
  Sentry.init({
    dsn,
    sendDefaultPii: false,
    beforeSend: (event) => scrubEvent(event),
    beforeBreadcrumb: (crumb) => ({
      ...crumb,
      data: crumb.data ? scrubValue(crumb.data) : crumb.data,
    }),
  });
  return true;
}
