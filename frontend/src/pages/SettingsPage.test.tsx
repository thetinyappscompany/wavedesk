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
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    inviteMember: vi.fn(),
    revokeInvite: vi.fn(),
    listMonitoringRules: vi.fn(),
    createMonitoringRule: vi.fn(),
    updateMonitoringRule: vi.fn(),
    deleteMonitoringRule: vi.fn(),
    listTeams: vi.fn(),
    createTeam: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn(),
    listSlaPolicies: vi.fn(),
    createSlaPolicy: vi.fn(),
    updateSlaPolicy: vi.fn(),
    deleteSlaPolicy: vi.fn(),
    getProfile: vi.fn(),
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    billingSummary: vi.fn(),
    aiUsageMeter: vi.fn(),
    twofaStatus: vi.fn(),
    listSessions: vi.fn(),
  },
}));

function settings(overrides: Partial<WdWorkspaceSettings> = {}): WdWorkspaceSettings {
  return {
    workspace: 'WS-1',
    workspace_name: 'Asha & Co',
    role: 'Owner',
    mask_numbers: false,
    needs_reply_minutes: 10,
    default_routing_team: null,
    business_hours: { enabled: false, timezone: 'Asia/Kolkata', days: {}, holidays: [] },
    ooo_reply_enabled: false,
    ooo_reply_message: '',
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

async function openTab(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole('tab', { name }));
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
    vi.mocked(client.listMembers).mockResolvedValue([
      { user: 'owner@x.test', role: 'Owner', full_name: 'Owner O' },
    ]);
    vi.mocked(client.listInvites).mockResolvedValue([]);
    vi.mocked(client.listMonitoringRules).mockResolvedValue([]);
    vi.mocked(client.listTeams).mockResolvedValue([]);
    vi.mocked(client.listSlaPolicies).mockResolvedValue([]);
    vi.mocked(client.getProfile).mockResolvedValue({
      email: 'owner@x.test',
      first_name: 'Owner O',
      is_platform_admin: false,
    });
    vi.mocked(client.billingSummary).mockResolvedValue({
      plan: 'Starter',
      status: 'trialing',
      ai_addon: false,
      current_period_end: '2026-08-01T00:00:00+00:00',
      wallet_balance: 250,
    });
    vi.mocked(client.aiUsageMeter).mockResolvedValue({
      has_ai: false,
      allowance_pct_used: 0,
      credits_inr: 0,
      paused: false,
      byok: false,
    });
    vi.mocked(client.twofaStatus).mockResolvedValue(false);
    vi.mocked(client.listSessions).mockResolvedValue([]);
  });

  it('shows the tab bar with the General tab active by default', async () => {
    renderPage();
    expect(await screen.findByText('Asha & Co')).toBeInTheDocument();
    const general = screen.getByRole('tab', { name: 'General' });
    expect(general).toHaveAttribute('aria-selected', 'true');
    // General content mounts; other tabs' content does not
    expect(screen.getByLabelText(/Needs Reply after/)).toBeInTheDocument();
    expect(screen.queryByText('vip')).not.toBeInTheDocument();
  });

  it('Inbox tab renders labels and canned responses', async () => {
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Inbox');
    expect(await screen.findByText('vip')).toBeInTheDocument();
    expect(screen.getByText('/greet')).toBeInTheDocument();
  });

  it('toggling masking (Privacy & Data tab) calls the settings API', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(
      settings({ mask_numbers: true }),
    );
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Privacy & Data');
    await user.click(await screen.findByLabelText('Mask customer numbers for agents'));
    expect(client.updateWorkspaceSettings).toHaveBeenCalledWith({ mask_numbers: true });
  });

  it('saving the needs-reply threshold calls the settings API', async () => {
    vi.mocked(client.updateWorkspaceSettings).mockResolvedValue(
      settings({ needs_reply_minutes: 30 }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Asha & Co'); // settings loaded → input mounted enabled
    const input = screen.getByLabelText(/Needs Reply after/);
    await user.clear(input);
    await user.type(input, '30');
    await user.tab(); // blur commits
    await waitFor(() => {
      expect(client.updateWorkspaceSettings).toHaveBeenCalledWith({
        needs_reply_minutes: 30,
      });
    });
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
    await openTab(user, 'Inbox');
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
    await openTab(user, 'Inbox');
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

  it('creates a monitoring rule from the form', async () => {
    vi.mocked(client.createMonitoringRule).mockResolvedValue({
      name: 'MRULE-1',
      rule_name: 'Competitor watch',
      enabled: true,
      rule_type: 'keyword',
      group: null,
      keywords: 'scam',
      notify_agents: true,
      notify_slack_url: null,
      notify_webhook_url: null,
    });
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Inbox');
    await user.type(await screen.findByLabelText('Rule name'), 'Competitor watch');
    await user.type(screen.getByLabelText('Rule keywords'), 'scam, competitorx');
    await user.click(screen.getByRole('button', { name: 'Add rule' }));
    await waitFor(() => {
      expect(client.createMonitoringRule).toHaveBeenCalledWith({
        rule_name: 'Competitor watch',
        rule_type: 'keyword',
        keywords: 'scam, competitorx',
      });
    });
  });

  it('deleting a label calls the API', async () => {
    vi.mocked(client.deleteLabel).mockResolvedValue({ deleted: 'LBL-1' });
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Inbox');
    await user.click(await screen.findByLabelText('Delete label vip'));
    expect(client.deleteLabel).toHaveBeenCalledWith('LBL-1');
  });

  it('team tab lists members, invites, and revokes', async () => {
    vi.mocked(client.listInvites).mockResolvedValue([
      {
        name: 'INV-1',
        email: 'riya@x.test',
        role: 'Agent',
        status: 'pending',
        expires_at: null,
        invite_url: 'http://x/invite/tok',
      },
    ]);
    vi.mocked(client.inviteMember).mockResolvedValue({
      name: 'INV-2',
      email: 'dev@x.test',
      role: 'Admin',
      status: 'pending',
      expires_at: null,
      invite_url: 'http://x/invite/tok2',
    });
    vi.mocked(client.revokeInvite).mockResolvedValue({ invite: 'INV-1', status: 'revoked' });
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Team & Routing');
    expect(await screen.findByTestId('member-row')).toHaveTextContent('Owner O');
    expect(await screen.findByTestId('invite-row')).toHaveTextContent('riya@x.test');

    await user.type(screen.getByLabelText('Invite email'), 'dev@x.test');
    await user.selectOptions(screen.getByLabelText('Invite role'), 'Admin');
    await user.click(screen.getByRole('button', { name: 'Invite' }));
    await waitFor(() => {
      expect(client.inviteMember).toHaveBeenCalledWith('dev@x.test', 'Admin');
    });

    await user.click(screen.getByLabelText('Revoke invite for riya@x.test'));
    expect(client.revokeInvite).toHaveBeenCalledWith('INV-1');
  });

  it('account tab shows the profile and changes the password', async () => {
    vi.mocked(client.changePassword).mockResolvedValue({ ok: true, revoked_sessions: 1 });
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Account');
    expect(await screen.findByLabelText('Email')).toHaveValue('owner@x.test');
    expect(screen.getByLabelText('Display name')).toHaveValue('Owner O');

    await user.type(screen.getByLabelText('Current password'), 'old-secret-1');
    await user.type(screen.getByLabelText('New password'), 'new-secret-9');
    await user.type(screen.getByLabelText('Confirm new password'), 'new-secret-9');
    await user.click(screen.getByRole('button', { name: 'Update password' }));
    await waitFor(() => {
      expect(client.changePassword).toHaveBeenCalledWith('old-secret-1', 'new-secret-9');
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Password updated');
  });

  it('billing tab shows plan, status and wallet balance for managers', async () => {
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Billing');
    expect(await screen.findByText('Starter')).toBeInTheDocument();
    expect(screen.getByText('trialing')).toBeInTheDocument();
    expect(screen.getByText('₹250')).toBeInTheDocument();
    // no AI add-on → plain note, no usage meter
    expect(screen.getByText(/AI add-on: not enabled/)).toBeInTheDocument();
  });

  it('billing tab shows the AI usage meter when the add-on is active', async () => {
    vi.mocked(client.aiUsageMeter).mockResolvedValue({
      has_ai: true,
      allowance_pct_used: 62,
      credits_inr: 130,
      paused: false,
      byok: false,
    });
    const user = userEvent.setup();
    renderPage();
    await openTab(user, 'Billing');
    expect(
      await screen.findByText(/62% of the monthly allowance used/),
    ).toBeInTheDocument();
    expect(screen.getByText(/₹130 extra from wallet/)).toBeInTheDocument();
  });

  it('billing tab is hidden behind a note for agents', async () => {
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue(settings({ role: 'Agent' }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Asha & Co');
    await openTab(user, 'Billing');
    expect(
      await screen.findByText('Only workspace owners and admins can view billing.'),
    ).toBeInTheDocument();
    expect(client.billingSummary).not.toHaveBeenCalled();
  });

  it('agents get a read-only page', async () => {
    vi.mocked(client.getWorkspaceSettings).mockResolvedValue(settings({ role: 'Agent' }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Asha & Co');
    await openTab(user, 'Inbox');
    expect(await screen.findByText('vip')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Delete label vip')).not.toBeInTheDocument();
    await openTab(user, 'Privacy & Data');
    expect(
      await screen.findByLabelText('Mask customer numbers for agents'),
    ).toBeDisabled();
  });
});
