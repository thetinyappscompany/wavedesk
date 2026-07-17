import { expect, test } from '@playwright/test';

test('login shell renders', async ({ page }) => {
  await page.goto('/login');
  // heading role, not text — "New to WaveDesk? Create an account" also matches
  await expect(page.getByRole('heading', { name: 'WaveDesk' })).toBeVisible();
  await expect(page.getByLabel('Email')).toBeVisible();
  await expect(page.getByLabel('Password')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
});

test('signup page renders from the login link', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Create an account' }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByLabel('Work email')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible();
});

test('root redirects to login', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
});
