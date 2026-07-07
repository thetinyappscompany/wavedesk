/** Thin Graph API send client (text only in Phase 0; templates land in Phase 3). */
import type { CloudApiConfig } from './config.js';

export interface GraphSendResult {
  wa_message_id: string | null;
}

export class UnknownCloudNumberError extends Error {
  constructor(phoneNumberId: string) {
    super(`no Cloud API config for phone_number_id ${phoneNumberId}`);
    this.name = 'UnknownCloudNumberError';
  }
}

export class GraphApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`Graph API error ${String(status)}`);
    this.name = 'GraphApiError';
  }
}

interface GraphMessagesResponse {
  messages?: { id?: string }[];
}

export class GraphClient {
  constructor(
    private readonly config: CloudApiConfig,
    private readonly fetchFn: typeof fetch = fetch,
  ) {}

  workspaceFor(phoneNumberId: string): string | null {
    return this.config.numbers[phoneNumberId]?.workspace ?? null;
  }

  async sendText(phoneNumberId: string, to: string, body: string): Promise<GraphSendResult> {
    const number = this.config.numbers[phoneNumberId];
    if (!number) {
      throw new UnknownCloudNumberError(phoneNumberId);
    }
    const url = `https://graph.facebook.com/${this.config.graphApiVersion}/${phoneNumberId}/messages`;
    const response = await this.fetchFn(url, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${number.token}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        messaging_product: 'whatsapp',
        recipient_type: 'individual',
        to,
        type: 'text',
        text: { preview_url: false, body },
      }),
    });
    if (!response.ok) {
      throw new GraphApiError(response.status, await response.text());
    }
    const data = (await response.json()) as GraphMessagesResponse;
    return { wa_message_id: data.messages?.[0]?.id ?? null };
  }
}
