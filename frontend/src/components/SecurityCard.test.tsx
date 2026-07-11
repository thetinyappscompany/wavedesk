import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SecurityCard from './SecurityCard';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    twofaStatus: vi.fn(),
    listSessions: vi.fn(),
    twofaBeginEnroll: vi.fn(),
    twofaConfirm: vi.fn(),
    twofaDisable: vi.fn(),
    revokeSession: vi.fn(),
    revokeOtherSessions: vi.fn(),
  },
}));

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SecurityCard />
    </QueryClientProvider>,
  );
}

describe('SecurityCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.twofaStatus).mockResolvedValue(false);
    vi.mocked(client.listSessions).mockResolvedValue([
      { sid_tail: 'aaa111', ip: '1.2.3.4', last_active: null, status: 'Active', current: true },
      { sid_tail: 'bbb222', ip: '5.6.7.8', last_active: null, status: 'Active', current: false },
    ]);
  });

  it('enrolls in 2FA and reveals recovery codes', async () => {
    vi.mocked(client.twofaBeginEnroll).mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXP',
      otpauth_uri: 'otpauth://totp/WaveDesk:me?secret=JBSWY3DPEHPK3PXP',
    });
    vi.mocked(client.twofaConfirm).mockResolvedValue({
      enabled: true,
      recovery_codes: ['R1', 'R2', 'R3'],
    });
    renderCard();
    await userEvent.click(await screen.findByRole('button', { name: 'Enable 2FA' }));
    expect(await screen.findByTestId('twofa-enroll')).toHaveTextContent('JBSWY3DPEHPK3PXP');
    await userEvent.type(screen.getByLabelText('2FA code'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(client.twofaConfirm).toHaveBeenCalledWith('123456'));
    expect(await screen.findByTestId('recovery-codes')).toHaveTextContent('R1');
  });

  it('shows a disable control when 2FA is enabled', async () => {
    vi.mocked(client.twofaStatus).mockResolvedValue(true);
    vi.mocked(client.twofaDisable).mockResolvedValue({ enabled: false });
    renderCard();
    await userEvent.type(await screen.findByLabelText('2FA disable code'), '654321');
    await userEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await waitFor(() => expect(client.twofaDisable).toHaveBeenCalledWith('654321'));
  });

  it('lists sessions and revokes a non-current one', async () => {
    vi.mocked(client.revokeSession).mockResolvedValue({ revoked: 'bbb222' });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId('session-list')).toHaveTextContent('this device'),
    );
    await userEvent.click(screen.getByLabelText('Revoke session bbb222'));
    await waitFor(() => expect(client.revokeSession).toHaveBeenCalledWith('bbb222'));
    // the current session has no revoke button
    expect(screen.queryByLabelText('Revoke session aaa111')).not.toBeInTheDocument();
  });
});
