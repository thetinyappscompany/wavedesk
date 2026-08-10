import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ResetPasswordPage from './ResetPasswordPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({ client: { resetPassword: vi.fn() } }));

function renderPage(search = '?token=tok-123') {
  render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div>sign in</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.resetPassword).mockResolvedValue({ email: 'asha@acme.test' });
  });

  it('sets a new password using the token from the link', async () => {
    renderPage();
    await userEvent.type(screen.getByLabelText('New password'), 'brand-new-pass');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'brand-new-pass');
    await userEvent.click(screen.getByRole('button', { name: 'Update password' }));
    await waitFor(() =>
      expect(client.resetPassword).toHaveBeenCalledWith('tok-123', 'brand-new-pass'),
    );
    expect(await screen.findByTestId('reset-done')).toBeInTheDocument();
  });

  it('rejects mismatched confirmations before calling the API', async () => {
    renderPage();
    await userEvent.type(screen.getByLabelText('New password'), 'brand-new-pass');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'something-else');
    await userEvent.click(screen.getByRole('button', { name: 'Update password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match');
    expect(client.resetPassword).not.toHaveBeenCalled();
  });

  it('explains an expired or used link', async () => {
    vi.mocked(client.resetPassword).mockRejectedValue(new Error('400'));
    renderPage();
    await userEvent.type(screen.getByLabelText('New password'), 'brand-new-pass');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'brand-new-pass');
    await userEvent.click(screen.getByRole('button', { name: 'Update password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or has expired/);
  });

  it('handles a link with no token at all', () => {
    renderPage('');
    expect(screen.getByRole('alert')).toHaveTextContent('missing its token');
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  });
});
