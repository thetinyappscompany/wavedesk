import { WaveDeskClient } from '@wavedesk/api-client';

/** Single client instance; same-origin — Vite dev proxy / nginx route to Frappe. */
export const client = new WaveDeskClient({ baseUrl: '' });
