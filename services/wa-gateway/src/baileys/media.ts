/** Inbound media pipeline (master doc §2.2, P4.5 prerequisite).
 *
 * WhatsApp media (images, video, voice notes, documents, stickers) arrives as an
 * encrypted reference — the bytes must be downloaded from WhatsApp's CDN with the
 * per-message keys Baileys holds, then parked in our own object store so Frappe
 * (which never talks to WhatsApp) can serve them to the SPA and, for voice notes,
 * hand the audio to transcription (P4.5).
 *
 * Object keys are workspace-scoped and message-addressed → idempotent: a redelivered
 * message re-uploads to the same key (harmless overwrite), never a duplicate blob. */
import {
  DeleteObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import type { S3Config } from '../config.js';
import type { InboundMessage } from './socket.js';

export type MediaType = 'image' | 'video' | 'audio' | 'document' | 'sticker';

export interface MediaMeta {
  type: MediaType;
  mimetype: string | null;
  filename: string | null;
  /** Bytes, best-effort (Baileys fileLength is a Long | number | undefined). */
  size: number | null;
  /** Duration in seconds for audio/video, else null. */
  duration: number | null;
  /** WhatsApp voice note (push-to-talk) — the P4.5 transcription target. */
  isVoice: boolean;
}

/** The stored-media reference attached to a message.received event payload. */
export interface MediaRef extends MediaMeta {
  /** Object-store key, or null when the download/upload failed (metadata still ships). */
  key: string | null;
}

export interface MediaStorage {
  /** Store bytes under `key`; overwrite is fine (idempotent by message id). */
  put(key: string, body: Buffer, contentType: string): Promise<void>;
  remove(key: string): Promise<void>;
}

// Baileys content wrappers whose real message sits one level deeper — mirror the
// Frappe consumer's unwrap so metadata and body extraction agree.
const WRAPPERS = ['ephemeralMessage', 'viewOnceMessage', 'viewOnceMessageV2'] as const;

// Baileys content key → our media type.
const MEDIA_KEYS: Record<string, MediaType> = {
  imageMessage: 'image',
  videoMessage: 'video',
  audioMessage: 'audio',
  documentMessage: 'document',
  stickerMessage: 'sticker',
};

interface BaileysMediaContent {
  mimetype?: string | null;
  fileName?: string | null;
  fileLength?: number | { toNumber?: () => number; low?: number } | null;
  seconds?: number | null;
  ptt?: boolean | null;
}

function unwrap(content: unknown): Record<string, unknown> | null {
  if (typeof content !== 'object' || content === null) {
    return null;
  }
  const record = content as Record<string, unknown>;
  for (const wrapper of WRAPPERS) {
    const inner = record[wrapper];
    if (inner && typeof inner === 'object' && 'message' in inner) {
      return unwrap(inner.message);
    }
  }
  return record;
}

/** Baileys fileLength is a protobuf Long, a number, or absent. Normalize to a
 * finite number of bytes, or null when it cannot be determined. */
function toBytes(value: BaileysMediaContent['fileLength']): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (value && typeof value === 'object') {
    if (typeof value.toNumber === 'function') {
      const n = value.toNumber();
      return Number.isFinite(n) ? n : null;
    }
    if (typeof value.low === 'number') {
      return value.low;
    }
  }
  return null;
}

/** Inspect an inbound message; return media metadata, or null for non-media
 * (text, location, reactions, protocol noise). Pure — no network. */
export function extractMediaMeta(message: InboundMessage): MediaMeta | null {
  const content = unwrap(message.message);
  if (!content) {
    return null;
  }
  for (const [rawKey, mediaType] of Object.entries(MEDIA_KEYS)) {
    const node = content[rawKey];
    if (node && typeof node === 'object') {
      const c = node as BaileysMediaContent;
      return {
        type: mediaType,
        mimetype: c.mimetype ?? null,
        filename: c.fileName ?? null,
        size: toBytes(c.fileLength),
        duration: mediaType === 'audio' || mediaType === 'video' ? (c.seconds ?? null) : null,
        isVoice: mediaType === 'audio' && Boolean(c.ptt),
      };
    }
  }
  return null;
}

export class S3MediaStorage implements MediaStorage {
  private readonly client: S3Client;

  constructor(
    private readonly config: S3Config,
    private readonly bucket: string,
  ) {
    this.client = new S3Client({
      endpoint: config.endpoint,
      region: config.region,
      forcePathStyle: true, // MinIO compatibility
      credentials: {
        accessKeyId: config.accessKey,
        secretAccessKey: config.secretKey,
      },
    });
  }

  async put(key: string, body: Buffer, contentType: string): Promise<void> {
    await this.client.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: body,
        ContentType: contentType,
      }),
    );
  }

  async remove(key: string): Promise<void> {
    await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: key }));
  }
}

/** In-memory storage for tests. */
export class MemoryMediaStorage implements MediaStorage {
  readonly blobs = new Map<string, { body: Buffer; contentType: string }>();

  put(key: string, body: Buffer, contentType: string): Promise<void> {
    this.blobs.set(key, { body, contentType });
    return Promise.resolve();
  }

  remove(key: string): Promise<void> {
    this.blobs.delete(key);
    return Promise.resolve();
  }
}

/** Workspace-scoped, message-addressed object key. Sanitized so a hostile
 * wa_message_id can't escape the media/ prefix. */
export function mediaKey(workspace: string, waMessageId: string): string {
  const safe = (s: string): string => s.replace(/[^A-Za-z0-9_-]/g, '_');
  return `media/${safe(workspace)}/${safe(waMessageId)}`;
}
