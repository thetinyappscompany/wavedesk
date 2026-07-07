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
}

interface SendMessageBody {
  to: string;
  text: string;
}

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

  app.delete<{ Params: { id: string } }>('/sessions/:id', async (request, reply) => {
    const removed = await manager.destroy(request.params.id);
    if (!removed) {
      return reply.code(404).send({ error: 'session not found' });
    }
    return reply.code(204).send();
  });

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
