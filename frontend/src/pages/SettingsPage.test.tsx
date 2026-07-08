import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WdWorkspaceSettings } from '@wavedesk/api-client';
import SettingsPage from './SettingsPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    getWorkspaceSettings: vi.fn(),
    updateWorkspaceSettings: vi.fn(),
    listLabels: vi.fn(),
    createLabel: vi.fn(),
    updateLabel: vi.fn(),
    deleteLabel: vi.fn(),
    listCanned: vi.fn(),
    createCanned: vi.fn(),
    updateCanned: vi.fn(),
    deleteCanned: vi.fn(),
  },
}));

function settings(overrides: Partial<WdWorkspaceSettings> = {}): WdWorkspaceSettings {
  return {
    workspace: 'WS-1',
    workspace_name: 'Asha & Co',
    role: 'Owner',
    mask_numbers: false,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue(settings());
    vi.mocked(client.listLabels).mockResolvedValue([
      { name: 'LBL-1', title: 'vip', color: '#ff5533', description: null },
    ]);
    vi.mocked(client.listCanned).mockResolvedValue([
      { name: 'CANNED-1', shortcode: 'greet', content: 'Namaste {{contact.name}}!' },
    ]);
  });

  it('renders labels, canned responses, and the masking toggle', async () => {
    renderPage();
    expect(await screen.findByText('Asha & Co')).toBeInTheDocument();
    expect(await screen.findByText('vip')).toBeInTheDocument();
    expect(screen.getByText('/greet')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Mask customer numbers for agents'),
    ).not.toBeChecked();
  });

  it('toggling masking calls the settings API', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(
      settings({ mask_numbers: true }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Mask customer numbers for agents'));
    expect(client.updateWorkspaceSettings).toHaveBeenCalledWith({ mask_numbers: true });
  });

  it('creates a label from the form', async () => {
    vi.mocked(client.createLabel).mockResolvedValue({
      name: 'LBL-2',
      title: 'billing',
      color: '#1f93ff',
      description: null,
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText('Label title'), 'billing');
    const submit = screen.getAllByRole('button', { name: 'Add' })[0];
    if (!submit) {
      throw new Error('expected an Add button in the labels card');
    }
    await user.click(submit);
    await waitFor(() => {
      expect(client.createLabel).toHaveBeenCalledWith('billing', '#1f93ff');
    });
  });

  it('creates a canned response from the form', async () => {
    vi.mocked(client.createCanned).mockResolvedValue({
      name: 'CANNED-2',
      shortcode: 'closing',
      content: 'Anything else?',
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText('Canned shortcode'), 'closing');
    await user.type(screen.getByLabelText('Canned content'), 'Anything else?');
    const addButtons = screen.getAllByRole('button', { name: 'Add' });
    const submit = addButtons[addButtons.length - 1];
    if (!submit) {
      throw new Error('expected an Add button in the canned card');
    }
    await user.click(submit);
    await waitFor(() => {
      expect(client.createCanned).toHaveBeenCalledWith('closing', 'Anything else?');
    });
  });

  it('deleting a label calls the API', async () => {
    vi.mocked(client.deleteLabel).mockResolvedValue({ deleted: 'LBL-1' });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText('Delete label vip'));
    expect(client.deleteLabel).toHaveBeenCalledWith('LBL-1');
  });

  it('agents get a read-only page', async () => {
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue(settings({ role: 'Agent' }));
    renderPage();
    expect(await screen.findByText('vip')).toBeInTheDocument();
    expect(screen.getByLabelText('Mask customer numbers for agents')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Delete label vip')).not.toBeInTheDocument();
  });
});
