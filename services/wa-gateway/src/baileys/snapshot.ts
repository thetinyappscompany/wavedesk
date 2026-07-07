/** Encrypted session snapshots (master doc §2.2): survive restarts/pod loss
 * without QR re-scan. Hot state lives in Redis; snapshots are the S3 backstop. */
import {
  DeleteObjectCommand,
  GetObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import type { S3Config } from '../config.js';

export interface SnapshotStorage {
  put(sessionId: string, encryptedBlob: string): Promise<void>;
  get(sessionId: string): Promise<string | null>;
  remove(sessionId: string): Promise<void>;
}

export class S3SnapshotStorage implements SnapshotStorage {
  private readonly client: S3Client;

  constructor(private readonly config: S3Config) {
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

  private key(sessionId: string): string {
    return `session-snapshots/${sessionId}.enc`;
  }

  async put(sessionId: string, encryptedBlob: string): Promise<void> {
    await this.client.send(
      new PutObjectCommand({
        Bucket: this.config.bucket,
        Key: this.key(sessionId),
        Body: encryptedBlob,
        ContentType: 'application/octet-stream',
      }),
    );
  }

  async get(sessionId: string): Promise<string | null> {
    try {
      const result = await this.client.send(
        new GetObjectCommand({ Bucket: this.config.bucket, Key: this.key(sessionId) }),
      );
      return (await result.Body?.transformToString()) ?? null;
    } catch (err) {
      if ((err as { name?: string }).name === 'NoSuchKey') {
        return null;
      }
      throw err;
    }
  }

  async remove(sessionId: string): Promise<void> {
    await this.client.send(
      new DeleteObjectCommand({ Bucket: this.config.bucket, Key: this.key(sessionId) }),
    );
  }
}

/** In-memory storage for tests. */
export class MemorySnapshotStorage implements SnapshotStorage {
  readonly blobs = new Map<string, string>();

  put(sessionId: string, encryptedBlob: string): Promise<void> {
    this.blobs.set(sessionId, encryptedBlob);
    return Promise.resolve();
  }

  get(sessionId: string): Promise<string | null> {
    return Promise.resolve(this.blobs.get(sessionId) ?? null);
  }

  remove(sessionId: string): Promise<void> {
    this.blobs.delete(sessionId);
    return Promise.resolve();
  }
}
