import { expect, test } from '@playwright/test';

test('login shell renders', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByText('WaveDesk')).toBeVisible();
  await expect(page.getByLabel('Email')).toBeVisible();
  await expect(page.getByLabel('Password')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
});

test('root redirects to login', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
});
