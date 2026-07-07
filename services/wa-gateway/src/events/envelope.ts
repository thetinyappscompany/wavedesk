/** Unified event envelope (master doc §2.2): Frappe never cares which transport
 * a message came from. Same shape for Baileys and Cloud API. */

export type WaTransport = 'baileys' | 'cloud_api';

export type WaEventType = 'message.received' | 'message.status' | 'session.status';

export interface WaEvent {
  transport: WaTransport;
  type: WaEventType;
  /** Workspace the owning session/number belongs to (resolved fully in Frappe). */
  workspace_hint: string | null;
  wa_chat_id: string | null;
  wa_message_id: string | null;
  payload: unknown;
  /** ISO-8601 producer timestamp. */
  ts: string;
}

export const WA_EVENTS_STREAM = 'wa:events';

export function makeEvent(
  fields: Omit<WaEvent, 'ts'> & Partial<Pick<WaEvent, 'ts'>>,
): WaEvent {
  return { ts: new Date().toISOString(), ...fields };
}
