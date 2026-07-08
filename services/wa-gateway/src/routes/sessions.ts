import type { FastifyInstance, FastifyReply } from 'fastify';
import { toDataURL } from 'qrcode';
import {
  SessionExistsError,
  SessionNotFoundError,
  type SessionManager,
} from '../baileys/sessionManager.js';

interface CreateSessionBody {
  session_id: string;
  workspace: string;
  /** stream:false → plain JSON response (Frappe-driven polling instead of SSE). */
  stream?: boolean;
}

interface SendMessageBody {
  to: string;
  text: string;
}

interface GroupParticipantsBody {
  participants: string[];
  action: 'add' | 'remove' | 'promote' | 'demote';
}

interface GroupMetaBody {
  subject?: string;
  description?: string | null;
}

const PARTICIPANT_ACTIONS = new Set(['add', 'remove', 'promote', 'demote']);
const SUBJECT_MAX = 100;

function sseWrite(reply: FastifyReply, data: unknown): void {
  reply.raw.write(`data: ${JSON.stringify(data)}\n\n`);
}

export function registerSessionRoutes(app: FastifyInstance, manager: SessionManager): void {
  // POST /sessions — create a session; response is an SSE stream of QR frames
  // (base64 data-URL) + status updates, ending once connected.
  app.post<{ Body: CreateSessionBody }>('/sessions', async (request, reply) => {
    const { session_id, workspace } = request.body;
    if (!session_id || !workspace) {
      return reply.code(422).send({ error: 'session_id and workspace are required' });
    }

    let handle;
    try {
      handle = await manager.create(session_id, workspace);
    } catch (err) {
      if (err instanceof SessionExistsError) {
        return reply.code(409).send({ error: 'session already exists' });
      }
      throw err;
    }

    if (request.body.stream === false) {
      return reply.code(201).send({ session: handle.info, restored: handle.credsExisted });
    }

    reply.raw.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
    });

    // Serialize writes: QR→PNG encoding is async, and the terminal 'connected'
    // status must not close the stream while a QR frame is still encoding.
    let writes: Promise<void> = Promise.resolve();
    const enqueue = (work: () => Promise<void> | void): void => {
      writes = writes.then(work).catch(() => undefined);
    };

    const onQr = (qr: string): void => {
      enqueue(async () => {
        const dataUrl = await toDataURL(qr).catch(() => null);
        sseWrite(reply, { type: 'qr', qr: dataUrl });
      });
    };
    const onStatus = (status: string): void => {
      enqueue(() => {
        sseWrite(reply, { type: 'status', status });
      });
      if (status === 'connected') {
        enqueue(() => {
          cleanup();
          reply.raw.end();
        });
      }
    };
    const cleanup = (): void => {
      handle.emitter.off('qr', onQr);
      handle.emitter.off('status', onStatus);
    };

    handle.emitter.on('qr', onQr);
    handle.emitter.on('status', onStatus);
    request.raw.on('close', cleanup);

    sseWrite(reply, {
      type: 'status',
      status: handle.info.status,
      restored: handle.credsExisted,
    });
    if (handle.info.status === 'connected') {
      cleanup();
      reply.raw.end();
    }
    return reply;
  });

  app.get('/sessions', () => ({ sessions: manager.list() }));

  // Status + current QR (base64 data-URL) — polled by Frappe for the SPA,
  // which never talks to the gateway directly (master doc §2.6).
  app.get<{ Params: { id: string } }>('/sessions/:id', async (request, reply) => {
    const handle = manager.get(request.params.id);
    if (!handle) {
      return reply.code(404).send({ error: 'session not found' });
    }
    const qr = handle.lastQr ? await toDataURL(handle.lastQr).catch(() => null) : null;
    return { session: handle.info, qr, restored: handle.credsExisted };
  });

  app.post<{ Params: { id: string } }>('/sessions/:id/disconnect', (request, reply) => {
    if (!manager.disconnect(request.params.id)) {
      return reply.code(404).send({ error: 'session not found' });
    }
    return reply.code(204).send();
  });

  app.post<{ Params: { id: string } }>('/sessions/:id/reconnect', async (request, reply) => {
    try {
      const handle = await manager.reconnect(request.params.id);
      return { session: handle.info, restored: handle.credsExisted };
    } catch (err) {
      if (err instanceof SessionNotFoundError) {
        return reply.code(404).send({ error: 'session not found' });
      }
      throw err;
    }
  });

  app.delete<{ Params: { id: string } }>('/sessions/:id', async (request, reply) => {
    const removed = await manager.destroy(request.params.id);
    if (!removed) {
      return reply.code(404).send({ error: 'session not found' });
    }
    return reply.code(204).send();
  });

  // --- group actions (P2.3) — called by Frappe's audited action layer only.
  app.post<{ Params: { id: string; jid: string }; Body: GroupParticipantsBody }>(
    '/sessions/:id/groups/:jid/participants',
    async (request, reply) => {
      const { participants, action } = request.body;
      if (!Array.isArray(participants) || participants.length === 0) {
        return reply.code(422).send({ error: 'participants must be a non-empty array' });
      }
      if (!PARTICIPANT_ACTIONS.has(action)) {
        return reply.code(422).send({ error: 'invalid participant action' });
      }
      try {
        await manager.groupParticipants(request.params.id, request.params.jid, participants, action);
        return { ok: true };
      } catch (err) {
        if (err instanceof SessionNotFoundError) {
          return reply.code(404).send({ error: 'session not found' });
        }
        throw err;
      }
    },
  );

  app.patch<{ Params: { id: string; jid: string }; Body: GroupMetaBody }>(
    '/sessions/:id/groups/:jid',
    async (request, reply) => {
      const { subject, description } = request.body;
      if (subject === undefined && description === undefined) {
        return reply.code(422).send({ error: 'subject or description is required' });
      }
      if (subject !== undefined && (!subject.trim() || subject.length > SUBJECT_MAX)) {
        return reply.code(422).send({ error: `subject must be 1-${String(SUBJECT_MAX)} chars` });
      }
      try {
        await manager.groupUpdateMeta(request.params.id, request.params.jid, {
          ...(subject !== undefined ? { subject: subject.trim() } : {}),
          ...(description !== undefined ? { description } : {}),
        });
        return { ok: true };
      } catch (err) {
        if (err instanceof SessionNotFoundError) {
          return reply.code(404).send({ error: 'session not found' });
        }
        throw err;
      }
    },
  );

  app.post<{ Params: { id: string; jid: string } }>(
    '/sessions/:id/groups/:jid/revoke-invite',
    async (request, reply) => {
      try {
        const code = await manager.groupRevokeInvite(request.params.id, request.params.jid);
        return { invite_code: code };
      } catch (err) {
        if (err instanceof SessionNotFoundError) {
          return reply.code(404).send({ error: 'session not found' });
        }
        throw err;
      }
    },
  );

  // Stub-level send (Session 0.6). The production path is Frappe's queued,
  // rate-limited pipeline (Phase 1) — root non-negotiable #7.
  app.post<{ Params: { id: string }; Body: SendMessageBody }>(
    '/sessions/:id/messages',
    async (request, reply) => {
      const { to, text } = request.body;
      if (!to || !text) {
        return reply.code(422).send({ error: 'to and text are required' });
      }
      try {
        const result = await manager.sendText(request.params.id, to, text);
        return { queued: true, ...result };
      } catch (err) {
        if (err instanceof SessionNotFoundError) {
          return reply.code(404).send({ error: 'session not found' });
        }
        throw err;
      }
    },
  );
}
