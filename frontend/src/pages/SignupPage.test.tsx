import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@wavedesk/api-client';
import SignupPage from './SignupPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: {
    signup: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/signup']}>
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/onboarding" element={<div>ONBOARDING PROBE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Your name'), 'Asha Patel');
  await user.type(screen.getByLabelText('Work email'), 'asha@newco.test');
  await user.type(screen.getByLabelText('Password'), 'brand-new-pass1');
  await user.type(screen.getByLabelText('Confirm password'), 'brand-new-pass1');
}

describe('SignupPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('signs up and lands on onboarding', async () => {
    vi.mocked(client.signup).mockResolvedValue({ user: 'U-1', email: 'asha@newco.test' });
    const user = userEvent.setup();
    renderPage();
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await waitFor(() => {
      expect(client.signup).toHaveBeenCalledWith(
        'asha@newco.test',
        'brand-new-pass1',
        'Asha Patel',
      );
    });
    expect(await screen.findByText('ONBOARDING PROBE')).toBeInTheDocument();
  });

  it('rejects mismatched passwords client-side', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Your name'), 'Asha');
    await user.type(screen.getByLabelText('Work email'), 'asha@newco.test');
    await user.type(screen.getByLabelText('Password'), 'brand-new-pass1');
    await user.type(screen.getByLabelText('Confirm password'), 'different-pass');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument();
    expect(client.signup).not.toHaveBeenCalled();
  });

  it('shows a friendly message for an already-registered email', async () => {
    vi.mocked(client.signup).mockRejectedValue(new ApiError(409, 'exists'));
    const user = userEvent.setup();
    renderPage();
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(
      await screen.findByText(/already exists — log in instead/),
    ).toBeInTheDocument();
  });
});
