import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ForgotPasswordPage from './ForgotPasswordPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({ client: { requestPasswordReset: vi.fn() } }));

function renderPage() {
  render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  );
}

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.requestPasswordReset).mockResolvedValue({ ok: true, detail: 'sent' });
  });

  it('requests a reset link and confirms without revealing anything', async () => {
    renderPage();
    await userEvent.type(screen.getByLabelText('Email'), 'asha@acme.test');
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    await waitFor(() =>
      expect(client.requestPasswordReset).toHaveBeenCalledWith('asha@acme.test'),
    );
    expect(await screen.findByTestId('reset-sent')).toHaveTextContent(
      /If that email has a WaveDesk account/,
    );
  });

  it('shows the same confirmation even when the request fails', async () => {
    // a visible error would tell an attacker the address is (or is not) known
    vi.mocked(client.requestPasswordReset).mockRejectedValue(new Error('boom'));
    renderPage();
    await userEvent.type(screen.getByLabelText('Email'), 'ghost@acme.test');
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect(await screen.findByTestId('reset-sent')).toBeInTheDocument();
  });

  it('validates the email before calling the API', async () => {
    renderPage();
    await userEvent.type(screen.getByLabelText('Email'), 'not-an-email');
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a valid email');
    expect(client.requestPasswordReset).not.toHaveBeenCalled();
  });
});
