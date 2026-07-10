import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AiCopilotBar } from './AiCopilotBar';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    aiSettings: vi.fn(),
    copilotSuggestReply: vi.fn(),
    copilotRewrite: vi.fn(),
    copilotTranslate: vi.fn(),
    copilotSummarize: vi.fn(),
  },
}));

const AI_ON = {
  has_ai: true,
  kill_switch: false,
  byok_configured: false,
  byok_provider: null,
  persona_prompt: null,
  confidence_threshold: null,
};

function renderBar(draft = '', setDraft = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AiCopilotBar chatName="CHAT-1" draft={draft} setDraft={setDraft} />
    </QueryClientProvider>,
  );
  return { setDraft };
}

describe('AiCopilotBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.aiSettings).mockResolvedValue(AI_ON);
  });

  it('renders nothing without the AI add-on', async () => {
    vi.mocked(client.aiSettings).mockResolvedValue({ ...AI_ON, has_ai: false });
    renderBar('hello');
    // Give the query a tick; the bar must never appear.
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId('copilot-bar')).not.toBeInTheDocument();
  });

  it('suggests a reply into the draft', async () => {
    vi.mocked(client.copilotSuggestReply).mockResolvedValue({ text: 'Namaste! Order ready.' });
    const { setDraft } = renderBar('');
    await userEvent.click(await screen.findByRole('button', { name: 'Suggest reply' }));
    await waitFor(() => expect(setDraft).toHaveBeenCalledWith('Namaste! Order ready.'));
    expect(client.copilotSuggestReply).toHaveBeenCalledWith('CHAT-1');
  });

  it('polishes the current draft', async () => {
    vi.mocked(client.copilotRewrite).mockResolvedValue({ text: 'Please share the details.' });
    const { setDraft } = renderBar('pls send deets');
    await userEvent.click(await screen.findByRole('button', { name: /Polish/ }));
    await waitFor(() => expect(setDraft).toHaveBeenCalledWith('Please share the details.'));
    expect(client.copilotRewrite).toHaveBeenCalledWith('pls send deets', 'polish');
  });

  it('disables draft actions when the draft is empty', async () => {
    renderBar('');
    expect(await screen.findByRole('button', { name: /Polish/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Translate/ })).toBeDisabled();
    // Suggest and Summarize do not need a draft.
    expect(screen.getByRole('button', { name: 'Suggest reply' })).toBeEnabled();
  });

  it('shows a dismissible summary panel', async () => {
    vi.mocked(client.copilotSummarize).mockResolvedValue({ text: '- customer wants stock' });
    renderBar('');
    await userEvent.click(await screen.findByRole('button', { name: /Summarize/ }));
    const panel = await screen.findByTestId('copilot-summary');
    expect(panel).toHaveTextContent('customer wants stock');
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss summary' }));
    await waitFor(() => expect(screen.queryByTestId('copilot-summary')).not.toBeInTheDocument());
  });
});
