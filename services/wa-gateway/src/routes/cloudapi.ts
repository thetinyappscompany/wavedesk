import type { FastifyInstance } from 'fastify';
import type { CloudApiConfig } from '../cloudapi/config.js';
import {
  GraphApiError,
  UnknownCloudNumberError,
  type GraphClient,
} from '../cloudapi/graphClient.js';
import { verifyMetaSignature } from '../cloudapi/signature.js';
import { makeEvent } from '../events/envelope.js';
import type { EventPublisher } from '../events/publisher.js';
import { logFields } from '../logger.js';

export const META_WEBHOOK_PATH = '/webhooks/meta';

/** Meta webhook envelope subset (see docs/reference/cloud-api-integration-design.md). */
interface MetaWebhookPayload {
  entry?: {
    changes?: {
      value?: {
        metadata?: { phone_number_id?: string };
        messages?: {
          from?: string;
          id?: string;
          type?: string;
          timestamp?: string;
          text?: { body?: string };
        }[];
        statuses?: { id?: string; status?: string; recipient_id?: string }[];
      };
    }[];
  }[];
}

export interface CloudApiDeps {
  config: CloudApiConfig;
  client: GraphClient;
  publisher: EventPublisher;
}

export function registerCloudApiRoutes(app: FastifyInstance, deps: CloudApiDeps): void {
  const { config, client } = deps;

  // --- Meta webhook verification handshake (one-time GET when subscribing) ---
  app.get<{ Querystring: Record<string, string> }>(META_WEBHOOK_PATH, (request, reply) => {
    const mode = request.query['hub.mode'];
    const token = request.query['hub.verify_token'];
    const challenge = request.query['hub.challenge'];
    if (mode === 'subscribe' && config.verifyToken && token === config.verifyToken) {
      return reply.type('text/plain').send(challenge ?? '');
    }
    return reply.code(403).send();
  });

  // --- Inbound messages & statuses. ACK 200 fast; never let handler errors 5xx. ---
  app.post(META_WEBHOOK_PATH, async (request, reply) => {
    const rawBody = request.rawBody;
    const signature = request.headers['x-hub-signature-256'];
    if (
      !rawBody ||
      !verifyMetaSignature(rawBody, typeof signature === 'string' ? signature : undefined, config.appSecret)
    ) {
      // Redacted by design: no payload contents in the log (non-negotiable #6).
      request.log.warn(
        logFields({ signature_present: typeof signature === 'string' }),
        'rejected Meta webhook with invalid signature',
      );
      return reply.code(403).send({ error: 'invalid signature' });
    }

    try {
      await publishNormalized(request.body as MetaWebhookPayload, deps);
    } catch (err) {
      request.log.error(
        logFields({ err_type: err instanceof Error ? err.name : 'unknown' }),
        'error handling Meta webhook payload',
      );
    }
    return reply.code(200).send();
  });

  // --- Outbound text via Graph API (stub-level; queued pipeline lands in Phase 1) ---
  app.post<{ Params: { phoneNumberId: string }; Body: { to?: string; text?: string } }>(
    '/cloud/:phoneNumberId/messages',
    async (request, reply) => {
      const { to, text } = request.body;
      if (!to || !text) {
        return reply.code(422).send({ error: 'to and text are required' });
      }
      try {
        const result = await client.sendText(request.params.phoneNumberId, to, text);
        return { queued: true, ...result };
      } catch (err) {
        if (err instanceof UnknownCloudNumberError) {
          return reply.code(404).send({ error: 'unknown phone_number_id' });
        }
        if (err instanceof GraphApiError) {
          return reply.code(502).send({ error: 'graph api error', status: err.status });
        }
        throw err;
      }
    },
  );
}

/** Normalize Meta's webhook envelope into the SAME wa:events shape as Baileys
 * (master doc §2.2: Frappe never cares which transport a message came from). */
async function publishNormalized(payload: MetaWebhookPayload, deps: CloudApiDeps): Promise<void> {
  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value;
      if (!value) {
        continue;
      }
      const phoneNumberId = value.metadata?.phone_number_id ?? null;
      const workspace = phoneNumberId ? deps.client.workspaceFor(phoneNumberId) : null;

      for (const message of value.messages ?? []) {
        await deps.publisher.publish(
          makeEvent({
            transport: 'cloud_api',
            type: 'message.received',
            workspace_hint: workspace,
            wa_chat_id: message.from ?? null,
            wa_message_id: message.id ?? null,
            payload: {
              phone_number_id: phoneNumberId,
              from: message.from ?? null,
              message_type: message.type ?? 'text',
              text: message.text?.body ?? null,
              timestamp: message.timestamp ?? null,
              raw: message,
            },
          }),
        );
      }

      for (const status of value.statuses ?? []) {
        await deps.publisher.publish(
          makeEvent({
            transport: 'cloud_api',
            type: 'message.status',
            workspace_hint: workspace,
            wa_chat_id: status.recipient_id ?? null,
            wa_message_id: status.id ?? null,
            payload: { phone_number_id: phoneNumberId, status: status.status ?? null },
          }),
        );
      }
    }
  }
}
