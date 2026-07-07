import type { Redis } from 'ioredis';
import type { Logger } from 'pino';
import { logFields } from '../logger.js';
import { WA_EVENTS_STREAM, type WaEvent } from './envelope.js';

/** Publishes unified events to the Redis Stream `wa:events` (consumer-group ready:
 * consumers create their groups with XGROUP CREATE; XADD here needs no knowledge of them). */
export class EventPublisher {
  constructor(
    private readonly redis: Redis,
    private readonly logger: Logger,
  ) {}

  async publish(event: WaEvent): Promise<string> {
    const id = await this.redis.xadd(WA_EVENTS_STREAM, '*', 'event', JSON.stringify(event));
    this.logger.debug(
      logFields({
        event_type: event.type,
        transport: event.transport,
        wa_message_id: event.wa_message_id,
        stream_id: id,
      }),
      'published wa:events entry',
    );
    return id as string;
  }
}
