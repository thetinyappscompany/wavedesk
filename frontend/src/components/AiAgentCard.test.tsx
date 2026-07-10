import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AiAgentCard from './AiAgentCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    aiSettings: vi.fn(),
    getAgentConfig: vi.fn(),
    listKnowledge: vi.fn(),
    listTeams: vi.fn(),
    updateAgentConfig: vi.fn(),
    createKnowledge: vi.fn(),
    deleteKnowledge: vi.fn(),
    previewAnswer: vi.fn(),
  },
}));

const CONFIG = {
  name: 'AGENTCFG-1',
  enabled: false,
  persona_prompt: 'Be friendly.',
  confidence_threshold: 0.6,
  handoff_team: null,
  after_hours_only: false,
  greeting: null,
};

function renderCard(canManage = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AiAgentCard canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('AiAgentCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.aiSettings).mockResolvedValue({
      has_ai: true, kill_switch: false, byok_configured: false,
      byok_provider: null, persona_prompt: null, confidence_threshold: null,
    });
    vi.mocked(client.getAgentConfig).mockResolvedValue(CONFIG);
    vi.mocked(client.listKnowledge).mockResolvedValue([
      { name: 'KDOC-1', title: 'Returns', source_type: 'text', source_ref: null, embedding_status: 'embedded', chunk_count: 2 },
    ]);
    vi.mocked(client.listTeams).mockResolvedValue([]);
  });

  it('locks without the AI add-on', async () => {
    vi.mocked(client.aiSettings).mockResolvedValue({
      has_ai: false, kill_switch: false, byok_configured: false,
      byok_provider: null, persona_prompt: null, confidence_threshold: null,
    });
    renderCard();
    expect(await screen.findByText(/Locked — requires the AI add-on/)).toBeInTheDocument();
  });

  it('saves config changes', async () => {
    vi.mocked(client.updateAgentConfig).mockResolvedValue({ ...CONFIG, enabled: true });
    renderCard();
    const toggle = await screen.findByLabelText('Enabled');
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(client.updateAgentConfig).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true, confidence_threshold: 0.6 }),
      ),
    );
  });

  it('lists knowledge and adds a document', async () => {
    vi.mocked(client.createKnowledge).mockResolvedValue({ name: 'KDOC-2', embedding_status: 'pending' });
    renderCard();
    expect(await screen.findByText('Returns')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Knowledge title'), 'Shipping');
    await userEvent.type(screen.getByLabelText('Knowledge content'), 'We ship in 3 days.');
    await userEvent.click(screen.getByRole('button', { name: 'Add document' }));
    await waitFor(() =>
      expect(client.createKnowledge).toHaveBeenCalledWith('Shipping', 'We ship in 3 days.'),
    );
  });

  it('previews an answer', async () => {
    vi.mocked(client.previewAnswer).mockResolvedValue({ action: 'reply', text: 'We ship in 3 days.' });
    renderCard();
    await userEvent.type(await screen.findByLabelText('Test question'), 'shipping time?');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByTestId('preview-result')).toHaveTextContent('We ship in 3 days.');
  });

  it('hides mutations when the user cannot manage', async () => {
    renderCard(false);
    await screen.findByTestId('ai-agent-card');
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add document' })).not.toBeInTheDocument();
  });
});
