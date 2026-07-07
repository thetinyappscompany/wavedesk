import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginPage from './LoginPage';
import { client } from '@/lib/client';

vi.mock('@/lib/client', () => ({
  client: { login: vi.fn() },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the login form', () => {
    renderPage();
    expect(screen.getByText('WaveDesk')).toBeInTheDocument();
    expect(screen.getByLabelText('Email or username')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('shows validation errors on empty submit', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.length).toBeGreaterThanOrEqual(2);
    expect(client.login).not.toHaveBeenCalled();
  });

  it('logs in against Frappe with the entered credentials', async () => {
    vi.mocked(client.login).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Email or username'), 'owner@acme.in');
    await user.type(screen.getByLabelText('Password'), 'secret123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(client.login).toHaveBeenCalledWith('owner@acme.in', 'secret123');
  });

  it('surfaces auth failures', async () => {
    vi.mocked(client.login).mockRejectedValue(new Error('401'));
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Email or username'), 'owner@acme.in');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText(/Login failed/)).toBeInTheDocument();
  });
});
