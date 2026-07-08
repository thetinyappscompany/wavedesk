import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

/** Phase 1 exit E2E (guide NFR): connect → receive → reply → resolve, plus the
 * onboarding wizard and canned responses — real browser + real SPA, with the
 * Frappe API mocked at the network layer so the suite is deterministic in CI. */

interface MockMessage {
  name: string;
  direction: 'in' | 'out';
  message_type: string;
  body: string;
  status: string | null;
  sender_agent: string | null;
  sender_contact: string | null;
  wa_message_id: string | null;
  quoted_message: string | null;
  quoted_body: string | null;
  creation: string;
}

function msg(name: string, direction: 'in' | 'out', body: string): MockMessage {
  return {
    name,
    direction,
    message_type: 'text',
    body,
    status: direction === 'out' ? 'sent' : null,
    sender_agent: null,
    sender_contact: null,
    wa_message_id: null,
    quoted_message: null,
    quoted_body: null,
    creation: '2026-07-08 12:00:00',
  };
}

interface MockState {
  chatStatus: string;
  messages: MockMessage[];
}

const json = (message: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ message }),
});

async function mockApi(page: Page, opts: { hasWorkspace?: boolean } = {}): Promise<MockState> {
  const state: MockState = {
    chatStatus: 'open',
    messages: [msg('M-1', 'in', 'namaste, any update on my order?')],
  };
  const api = (method: string) => `**/api/method/${method}`;

  // catch-all first — Playwright gives priority to later registrations
  await page.route('**/api/method/**', (route: Route) => route.fulfill(json(null)));
  await page.route(api('login'), (route) => route.fulfill(json('Logged In')));
  await page.route(api('frappe.auth.get_logged_user'), (route) =>
    route.fulfill(json('owner@x.test')),
  );
  await page.route(api('wavedesk.api.onboarding.onboarding_status'), (route) =>
    route.fulfill(
      json(
        opts.hasWorkspace === false
          ? { has_workspace: false }
          : {
              has_workspace: true,
              workspace: 'WS-1',
              workspace_name: 'Asha & Co',
              role: 'Owner',
              connected_numbers: 1,
              total_numbers: 1,
              members: 1,
              pending_invites: 0,
            },
      ),
    ),
  );
  await page.route(api('wavedesk.api.numbers.list_numbers'), (route) =>
    route.fulfill(
      json([
        {
          name: 'WNUM-1',
          phone: '917700000001',
          display_name: 'Sales Line',
          connection_type: 'baileys',
          status: 'connected',
          health_score: 100,
          daily_send_limit: 500,
          warmup_stage: 3,
          waba_id: null,
          phone_number_id: null,
        },
      ]),
    ),
  );
  await page.route(api('wavedesk.api.chats.list_chats'), (route) =>
    route.fulfill(
      json({
        chats: [
          {
            name: 'CHAT-1',
            chat_type: 'dm',
            status: state.chatStatus,
            number: 'WNUM-1',
            contact: 'CONT-1',
            assigned_agent: null,
            assigned_team: null,
            snoozed_until: null,
            last_message_at: '2026-07-08 12:00:00',
            unread_count: 1,
            wa_chat_id: '919111100001@s.whatsapp.net',
            contact_name: 'Asha Traders',
            contact_phone: '919111100001',
            labels: [],
          },
        ],
        total: 1,
      }),
    ),
  );
  await page.route(api('wavedesk.api.assign.list_members'), (route) =>
    route.fulfill(json([{ user: 'owner@x.test', role: 'Owner', full_name: 'Owner O' }])),
  );
  await page.route(api('wavedesk.api.labels.list_labels'), (route) => route.fulfill(json([])));
  await page.route(api('wavedesk.api.messages.list_messages'), (route) =>
    route.fulfill(json({ messages: state.messages, has_more: false, next_before: null })),
  );
  await page.route(api('wavedesk.api.messages.mark_chat_read'), (route) =>
    route.fulfill(json({ chat: 'CHAT-1', unread_count: 0 })),
  );
  await page.route(api('wavedesk.api.assign.presence_ping'), (route) =>
    route.fulfill(json({ ok: true })),
  );
  await page.route(api('wavedesk.api.canned.search_canned'), (route) =>
    route.fulfill(
      json([{ name: 'CANNED-1', shortcode: 'greet', content: 'Namaste {{contact.name}}!' }]),
    ),
  );
  await page.route(api('wavedesk.api.send.send_message'), async (route) => {
    const body = route.request().postDataJSON() as { body: string };
    state.messages = [
      ...state.messages,
      msg(`M-OUT-${String(state.messages.length)}`, 'out', body.body),
      // the customer replies before the refetch — "receive" leg of the loop
      msg(`M-IN-${String(state.messages.length + 1)}`, 'in', 'got it, dhanyavaad!'),
    ];
    await route.fulfill(json({ name: 'M-NEW', status: 'queued' }));
  });
  await page.route(api('wavedesk.api.assign.set_chat_status'), async (route) => {
    const body = route.request().postDataJSON() as { status: string };
    state.chatStatus = body.status;
    await route.fulfill(json({ chat: 'CHAT-1', status: body.status, snoozed_until: null }));
  });
  return state;
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email or username').fill('owner@x.test');
  await page.getByLabel('Password', { exact: true }).fill('secret123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/inbox$/);
}

test('connect: the paired number shows as connected', async ({ page }) => {
  await mockApi(page);
  await signIn(page);
  await page.goto('/numbers');
  await expect(page.getByText('Sales Line')).toBeVisible();
  await expect(page.getByText('connected', { exact: true })).toBeVisible();
  await expect(page.getByTestId('number-row').getByText('Linked device')).toBeVisible();
});

test('receive → reply → resolve loop', async ({ page }) => {
  await mockApi(page);
  await signIn(page);

  // receive: the inbound message is waiting in the chat
  await page.getByTestId('chat-row').click();
  await expect(page.getByRole('heading', { name: 'Asha Traders' })).toBeVisible();
  await expect(page.getByText('namaste, any update on my order?')).toBeVisible();

  // reply through the queued pipeline
  await page.getByLabel('Message').fill('On it ji — dispatching today!');
  const sendRequest = page.waitForRequest('**/api/method/wavedesk.api.send.send_message');
  await page.getByLabel('Message').press('Enter');
  await sendRequest;
  await expect(page.getByText('On it ji — dispatching today!')).toBeVisible();
  // and the customer's follow-up arrives (socket/refetch path)
  await expect(page.getByText('got it, dhanyavaad!')).toBeVisible();

  // resolve
  const resolveRequest = page.waitForRequest('**/api/method/wavedesk.api.assign.set_chat_status');
  await page.getByRole('button', { name: 'Resolve' }).click();
  await resolveRequest;
  await expect(page.getByRole('combobox', { name: 'Status' })).toHaveValue('resolved');
});

test('canned response inserts with variables filled', async ({ page }) => {
  await mockApi(page);
  await signIn(page);
  await page.getByTestId('chat-row').click();
  await page.getByLabel('Message').fill('/gr');
  await expect(page.getByTestId('canned-menu')).toBeVisible();
  await page.getByLabel('Message').press('Enter');
  await expect(page.getByLabel('Message')).toHaveValue('Namaste Asha Traders!');
});

test('first login without a workspace lands on the onboarding wizard', async ({ page }) => {
  await mockApi(page, { hasWorkspace: false });
  await page.goto('/login');
  await page.getByLabel('Email or username').fill('new@x.test');
  await page.getByLabel('Password', { exact: true }).fill('secret123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel('Name your workspace')).toBeVisible();
});
