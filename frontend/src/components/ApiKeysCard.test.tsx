import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ApiKeysCard from './ApiKeysCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listApiKeys: vi.fn(),
    apiKeyScopes: vi.fn(),
    createApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
  },
}));

const KEY = {
  name: 'APIKEY-1',
  label: 'CRM sync',
  key_prefix: 'abc123',
  scopes: ['messages:write', 'contacts:read'],
  enabled: true,
  rate_limit_per_min: 120,
  last_used_at: null,
  creation: '2026-07-11 12:00:00',
};

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ApiKeysCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('ApiKeysCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listApiKeys).mockResolvedValue([KEY]);
    vi.mocked(client.apiKeyScopes).mockResolvedValue([
      'messages:write',
      'contacts:read',
      'tickets:write',
    ]);
  });

  it('lists keys with prefix and scopes', async () => {
    renderCard();
    expect(await screen.findByText('CRM sync')).toBeInTheDocument();
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
  });

  it('creates a key with selected scopes and reveals the secret once', async () => {
    vi.mocked(client.createApiKey).mockResolvedValue({
      name: 'APIKEY-2',
      label: 'New',
      prefix: 'def456',
      scopes: ['messages:write'],
      rate_limit_per_min: 120,
      full_key: 'wdk_def456_thesecret',
    });
    renderCard();
    await screen.findByText('CRM sync');
    await userEvent.type(screen.getByLabelText('API key label'), 'New');
    await userEvent.click(screen.getByLabelText('messages:write'));
    await userEvent.click(screen.getByRole('button', { name: 'Create API key' }));
    await waitFor(() =>
      expect(client.createApiKey).toHaveBeenCalledWith('New', ['messages:write']),
    );
    // one-time reveal shows the full plaintext key
    expect(await screen.findByTestId('api-key-reveal')).toHaveTextContent('wdk_def456_thesecret');
  });

  it('revokes a key', async () => {
    vi.mocked(client.revokeApiKey).mockResolvedValue({ name: 'APIKEY-1', enabled: false });
    renderCard();
    await userEvent.click(await screen.findByLabelText('Revoke CRM sync'));
    await waitFor(() => expect(client.revokeApiKey).toHaveBeenCalledWith('APIKEY-1'));
  });

  it('hides mutations without manage rights', async () => {
    renderCard(false);
    await screen.findByText('CRM sync');
    expect(screen.queryByRole('button', { name: 'Create API key' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Revoke CRM sync')).not.toBeInTheDocument();
  });
});
