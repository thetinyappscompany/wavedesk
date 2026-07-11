import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WebhooksCard from './WebhooksCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listWebhookEndpoints: vi.fn(),
    webhookEventCatalog: vi.fn(),
    listWebhookDeliveries: vi.fn(),
    createWebhookEndpoint: vi.fn(),
    updateWebhookEndpoint: vi.fn(),
    deleteWebhookEndpoint: vi.fn(),
    redeliverWebhook: vi.fn(),
  },
}));

const ENDPOINT = {
  name: 'WHEP-1',
  label: 'CRM sync',
  url: 'https://crm.test/hook',
  signing_secret: 'abc',
  events: ['ticket.created'],
  enabled: true,
  last_status: 'delivered',
  last_delivery_at: null,
};

const DEAD_DELIVERY = {
  name: 'WHDL-1',
  endpoint: 'WHEP-1',
  event_type: 'ticket.created',
  event_id: 'e1',
  status: 'dead' as const,
  attempts: 6,
  response_code: 500,
  last_error: 'HTTP 500',
  next_attempt_at: null,
  delivered_at: null,
  creation: '2026-07-11 12:00:00',
};

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <WebhooksCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('WebhooksCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listWebhookEndpoints).mockResolvedValue([ENDPOINT]);
    vi.mocked(client.webhookEventCatalog).mockResolvedValue([
      'ticket.created',
      'chat.resolved',
      'message.received',
    ]);
    vi.mocked(client.listWebhookDeliveries).mockResolvedValue([DEAD_DELIVERY]);
  });

  it('lists endpoints and recent deliveries', async () => {
    renderCard();
    expect(await screen.findByText('CRM sync')).toBeInTheDocument();
    expect(screen.getByTestId('webhook-deliveries')).toHaveTextContent('dead');
  });

  it('creates an endpoint with selected events', async () => {
    vi.mocked(client.createWebhookEndpoint).mockResolvedValue({
      ...ENDPOINT,
      name: 'WHEP-2',
      label: 'New',
    });
    renderCard();
    await screen.findByText('CRM sync');
    await userEvent.type(screen.getByLabelText('Webhook label'), 'New');
    await userEvent.type(screen.getByLabelText('Webhook URL'), 'https://new.test/hook');
    await userEvent.click(screen.getByLabelText('chat.resolved'));
    await userEvent.click(screen.getByRole('button', { name: 'Add webhook' }));
    await waitFor(() =>
      expect(client.createWebhookEndpoint).toHaveBeenCalledWith('New', 'https://new.test/hook', [
        'chat.resolved',
      ]),
    );
  });

  it('redelivers a dead-letter delivery', async () => {
    vi.mocked(client.redeliverWebhook).mockResolvedValue({ delivery: 'WHDL-1', status: 'queued' });
    renderCard();
    await userEvent.click(await screen.findByLabelText('Redeliver WHDL-1'));
    await waitFor(() => expect(client.redeliverWebhook).toHaveBeenCalledWith('WHDL-1'));
  });

  it('hides mutations without manage rights', async () => {
    renderCard(false);
    await screen.findByText('CRM sync');
    expect(screen.queryByRole('button', { name: 'Add webhook' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Redeliver WHDL-1')).not.toBeInTheDocument();
  });
});
