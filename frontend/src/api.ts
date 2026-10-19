import { createClient } from '@supabase/supabase-js';
import type { Ticket } from './generated/schema';

const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
export const supabase = url && key ? createClient(url, key, { auth: { flowType: 'pkce', storage: window.sessionStorage, detectSessionInUrl: true } }) : null;

export type Role = 'viewer' | 'contributor' | 'owner';
export type Workspace = { id: string; name: string; role: Role };
export type Session = { user_id: string; workspaces: Workspace[] };
export type Config = { mode: 'demo' | 'production'; drafting_available: boolean; inference: { provider: string; trained: boolean; state?: string; profile?: string; experimental?: boolean; constrained_output?: boolean } };
export type DraftChecks = { version: string; source_available: boolean; findings: Array<{ code: string; field: string; message: string }> };
export type Example = { id: string; label: string; report: string };
export type Job = { id: string; status: string; payload: Ticket | null; error: { code: string; message: string } | null; generation_metadata: Record<string, unknown>; checks?: DraftChecks };
export type SavedTicket = { id: string; workspace_id: string; created_by: string; payload: Ticket; source_report: string | null; revision: number; status: 'draft' | 'reviewed'; reviewed_revision: number | null; reviewed_by: string | null; reviewed_at: string | null; updated_at: string; created_at: string; generation_metadata: Record<string, unknown> };
export type Summary = Pick<SavedTicket, 'id' | 'revision' | 'status' | 'updated_at' | 'created_by'> & { title: string; product_area: Ticket['product_area'] };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Array<{ field: string; message: string }> = []) { super(message); }
}

export class Api {
  constructor(public token: string, public workspaceId = '') {}

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(base + path, { ...options, headers: { 'Content-Type': 'application/json', ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}), ...options.headers } });
    } catch {
      throw new ApiError(0, 'network_error', 'Could not reach BugBrief. Your changes are still here.');
    }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new ApiError(response.status, data?.error?.code || 'request_failed', data?.error?.message || 'This action failed. Try again.', data?.error?.details || []);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  path(suffix: string) { return `/v1/workspaces/${this.workspaceId}${suffix}`; }
  send<T>(path: string, body: unknown, method = 'POST') { return this.request<T>(this.path(path), { method, body: JSON.stringify(body) }); }

  async export(payload: Ticket, saved: SavedTicket | null, receipt: string | null, format: 'json' | 'text'): Promise<string> {
    const path = saved ? this.path(`/tickets/${saved.id}/export?revision=${saved.revision}&format=${format}`) : this.path('/session-exports');
    let response: Response;
    try {
      response = await fetch(base + path, { method: saved ? 'GET' : 'POST', headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' }, ...(saved ? {} : { body: JSON.stringify({ payload, receipt_id: receipt, format }) }) });
    } catch { throw new ApiError(0, 'network_error', 'Export failed. Your ticket is still here.'); }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      throw new ApiError(response.status, data?.error?.code || 'export_failed', data?.error?.message || 'Export failed. Try again.');
    }
    return response.text();
  }
}
