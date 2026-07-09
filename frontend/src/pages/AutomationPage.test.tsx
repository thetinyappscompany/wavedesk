import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdAutomationLog, WdAutomationRule } from '@wavedesk/api-client';
import AutomationPage from './AutomationPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    listAutomationRules: vi.fn(),
    listAutomationLogs: vi.fn(),
    createAutomationRule: vi.fn(),
    updateAutomationRule: vi.fn(),
    deleteAutomationRule: vi.fn(),
  },
}));
vi.mock('@/lib/realtime', () => ({
  useWorkspaceEvents: vi.fn(),
}));

function rule(overrides: Partial<WdAutomationRule> = {}): WdAutomationRule {
  return {
    name: 'AUTO-1',
    rule_name: 'Auto greet',
    enabled: true,
    trigger_event: 'chat_created',
    conditions: [],
    actions: [{ type: 'auto_reply', body: 'hi' }],
    run_count: 4,
    ...overrides,
  };
}

function log(overrides: Partial<WdAutomationLog> = {}): WdAutomationLog {
  return {
    name: 'ALOG-1',
    rule: 'AUTO-1',
    rule_name: 'Auto greet',
    trigger_event: 'chat_created',
    chat: 'CHAT-1',
    outcome: 'fired',
    detail: null,
    creation: '2026-07-09 18:00:00',
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AutomationPage />
    </QueryClientProvider>,
  );
}

describe('AutomationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listAutomationRules).mockResolvedValue([rule()]);
    vi.mocked(client.listAutomationLogs).mockResolvedValue([log()]);
  });

  it('lists rules with run counts and the execution log', async () => {
    renderPage();
    expect(await screen.findByTestId('rule-row')).toHaveTextContent('Auto greet');
    expect(screen.getByText(/fired 4×/)).toBeInTheDocument();
    expect(screen.getByTestId('log-row')).toHaveTextContent('fired');
  });

  it('builds and saves a rule with a condition and actions', async () => {
    vi.mocked(client.createAutomationRule).mockResolvedValue(rule());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'New rule' }));
    await user.type(screen.getByLabelText('Rule name'), 'Refund router');
    await user.selectOptions(screen.getByLabelText('Trigger'), 'message_received');

    await user.click(screen.getByLabelText('Add condition'));
    await user.type(screen.getByLabelText('Condition 1 value'), 'refund');

    // default action row is auto_reply — fill its body
    await user.type(screen.getByLabelText('Action 1 value'), 'On it!');
    await user.click(screen.getByRole('button', { name: 'Save rule' }));

    await waitFor(() => {
      expect(client.createAutomationRule).toHaveBeenCalledWith({
        rule_name: 'Refund router',
        trigger_event: 'message_received',
        conditions: [{ type: 'keyword', value: 'refund' }],
        actions: [{ type: 'auto_reply', body: 'On it!' }],
      });
    });
  });

  it('toggles and deletes a rule', async () => {
    vi.mocked(client.updateAutomationRule).mockResolvedValue(rule({ enabled: false }));
    vi.mocked(client.deleteAutomationRule).mockResolvedValue({ deleted: 'AUTO-1' });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Enable Auto greet'));
    expect(client.updateAutomationRule).toHaveBeenCalledWith('AUTO-1', { enabled: false });
    await user.click(screen.getByLabelText('Delete Auto greet'));
    expect(client.deleteAutomationRule).toHaveBeenCalledWith('AUTO-1');
  });

  it('shows empty states', async () => {
    vi.mocked(client.listAutomationRules).mockResolvedValue([]);
    vi.mocked(client.listAutomationLogs).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No rules yet/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing has fired yet/)).toBeInTheDocument();
  });
});
