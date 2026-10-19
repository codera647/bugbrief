import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, Check, CheckCheck, ChevronLeft, ChevronRight, Clipboard, FilePlus2, FileText, Layers3, LogOut, Menu, Search, ShieldCheck, Sparkles, X } from 'lucide-react';
import { Api, ApiError, supabase } from './api';
import type { Config, DraftChecks, Example, Job, SavedTicket, Session, Summary, Workspace } from './api';
import type { Ticket } from './generated/schema';
import { PRODUCT_AREAS } from './generated/schema';
import { Alert, Dialog } from './components';
import { TicketEditor } from './TicketEditor';

type Modal = 'save' | 'review' | 'delete' | 'copy' | null;
const message = (error: unknown) => error instanceof Error ? error.message : 'This action failed. Try again.';

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [samples, setSamples] = useState<Example[]>([]);
  const [phase, setPhase] = useState<'loading' | 'login' | 'workspace' | 'denied'>('loading');
  const [api, setApi] = useState<Api | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [view, setView] = useState<'new' | 'history'>('new');
  const [report, setReport] = useState('');
  const [draft, setDraft] = useState<Ticket | null>(null);
  const [saved, setSaved] = useState<SavedTicket | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [details, setDetails] = useState<Array<{ field: string; message: string }>>([]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<Modal>(null);
  const [saveSource, setSaveSource] = useState(false);
  const [copyText, setCopyText] = useState('');
  const [conflict, setConflict] = useState<SavedTicket | null>(null);
  const [items, setItems] = useState<Summary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [search, setSearch] = useState('');
  const [area, setArea] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [more, setMore] = useState(false);
  const [menu, setMenu] = useState(false);
  const [checks, setChecks] = useState<DraftChecks | null>(null);
  const [checksError, setChecksError] = useState('');
  const [checking, setChecking] = useState(false);
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
  const epoch = useRef(0);
  const currentUser = useRef<string | null>(null);
  const currentWorkspace = useRef<string | null>(null);
  const operation = useRef(crypto.randomUUID());
  const saveOperation = useRef(crypto.randomUUID());
  const activeDraftId = useRef<string | null>(null);
  const historyRequest = useRef(0);

  const clearDraft = useCallback(() => {
    setReport(''); setDraft(null); setSaved(null); setJob(null); setReceipt(null);
    setDirty(false); setError(''); setDetails([]); setNotice(''); setConflict(null);
    setModal(null); setCopyText(''); setSaveSource(false); setBusy(false); activeDraftId.current = null;
    operation.current = crypto.randomUUID(); saveOperation.current = crypto.randomUUID();
    setChecks(null); setChecksError(''); setChecking(false); setReviewAcknowledged(false);
  }, []);

  const connect = useCallback(async (token: string) => {
    const version = epoch.current;
    const client = new Api(token);
    try {
      const who = await client.request<Session>('/v1/session');
      if (version !== epoch.current) return;
      if (currentUser.current !== who.user_id || currentWorkspace.current !== who.workspaces[0].id) {
        epoch.current++; clearDraft(); setView(who.workspaces[0].role === 'viewer' ? 'history' : 'new'); setItems([]); setSearch(''); setArea(''); setStatus(''); setPage(0);
      }
      currentUser.current = who.user_id; currentWorkspace.current = who.workspaces[0].id;
      const ws = who.workspaces[0];
      setSession(who); setWorkspace(ws); setApi(new Api(token, ws.id)); setPhase('workspace');
      if (ws.role === 'viewer') setView('history');
    } catch (err) {
      if (version !== epoch.current) return;
      setError(message(err)); setPhase(err instanceof ApiError && err.status === 403 ? 'denied' : 'login');
    }
  }, [clearDraft]);

  useEffect(() => {
    let live = true;
    const boot = async () => {
      try {
        const publicApi = new Api('');
        const [cfg, examples] = await Promise.all([publicApi.request<Config>('/v1/config'), publicApi.request<Example[]>('/v1/examples')]);
        if (!live) return;
        setConfig(cfg); setSamples(examples);
        if (cfg.mode === 'production' && supabase) {
          const { data, error: authError } = await supabase.auth.getSession();
          if (authError) throw authError;
          if (data.session) { await connect(data.session.access_token); return; }
        }
        setPhase('login');
      } catch (err) { if (live) { setError(message(err)); setPhase('login'); } }
    };
    void boot();
    return () => { live = false; };
  }, [connect]);

  useEffect(() => {
    if (config?.inference.state !== 'loading') return;
    let stopped = false;
    const timer = window.setInterval(() => {
      void new Api('').request<Config>('/v1/config').then(next => { if (!stopped) { setConfig(next); setError(previous => previous.startsWith('Model status: ') ? '' : previous); } }).catch(err => { if (!stopped) setError('Model status: ' + message(err)); });
    }, 3000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [config?.inference.state]);

  useEffect(() => {
    setChecks(null); setChecksError(''); setReviewAcknowledged(false);
    if (!api || !draft || (!saved && !job)) { setChecking(false); return; }
    let stopped = false;
    setChecking(true);
    const timer = window.setTimeout(() => {
      void api.send<DraftChecks>('/draft-checks', { payload: draft, ...(job?.status === 'succeeded' ? { job_id: job.id } : { ticket_id: saved?.id }) })
        .then(result => { if (!stopped) setChecks(result); })
        .catch(err => { if (!stopped) setChecksError(message(err)); })
        .finally(() => { if (!stopped) setChecking(false); });
    }, 350);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [api, draft, saved?.id, job?.id]);

  useEffect(() => {
    if (!supabase || config?.mode !== 'production') return;
    const { data } = supabase.auth.onAuthStateChange((event, authSession) => {
      if (event === 'SIGNED_OUT') {
        epoch.current++; currentUser.current = null; currentWorkspace.current = null; clearDraft(); setApi(null); setSession(null); setWorkspace(null); setItems([]); setPhase('login');
      } else if (authSession && (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED')) {
        // Avoid doing Supabase calls synchronously inside its auth callback.
        const version = epoch.current;
        window.setTimeout(() => { if (version === epoch.current) void connect(authSession.access_token); }, 0);
      }
    });
    return () => data.subscription.unsubscribe();
  }, [config?.mode, connect, clearDraft]);

  useEffect(() => {
    if (!menu) return;
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenu(false); document.querySelector<HTMLButtonElement>('.mobile-menu')?.focus(); } };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [menu]);

  const creating = workspace?.role !== 'viewer';
  const active = !!job && ['queued', 'running', 'cancel_requested'].includes(job.status);
  const reviewed = !!draft && !dirty && (saved ? saved.status === 'reviewed' && saved.reviewed_revision === saved.revision : !!receipt);
  const source = saved?.source_report || report || null;
  const canDelete = saved && creating && (workspace?.role === 'owner' || saved.created_by === session?.user_id);

  useEffect(() => {
    if (!active || !api || !job) return;
    let stopped = false;
    let timer: number;
    const version = epoch.current;
    const id = job.id;
    const poll = async () => {
      try {
        const next = await api.request<Job>(api.path(`/generation-jobs/${id}`));
        if (stopped || version !== epoch.current || activeDraftId.current !== id) return;
        setJob(next);
        if (next.status === 'succeeded' && next.payload) {
          setDraft(next.payload); setSaved(null); setReceipt(null); setDirty(false); setNotice('Draft ready. Compare it with the customer report.');
        } else if (next.status === 'failed') { operation.current = crypto.randomUUID(); setError(next.error?.message || 'Drafting failed. Your report is still here.'); }
        else if (next.status === 'cancelled') { operation.current = crypto.randomUUID(); setNotice('Generation cancelled. Your report is still here.'); }
        else timer = window.setTimeout(poll, document.hidden ? 10000 : 1500);
      } catch (err) { if (!stopped && version === epoch.current) { setError(message(err)); timer = window.setTimeout(poll, 10000); } }
    };
    timer = window.setTimeout(poll, 200);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [api, active, job?.id]);

  const loadHistory = useCallback(async () => {
    if (!api) return;
    const version = epoch.current;
    const request = ++historyRequest.current;
    setHistoryLoading(true); setHistoryError('');
    try {
      const query = new URLSearchParams({ search, area, status, page: String(page) });
      const result = await api.request<{ items: Summary[]; has_more: boolean }>(api.path('/tickets?' + query));
      if (version !== epoch.current || request !== historyRequest.current) return;
      setItems(result.items); setMore(result.has_more);
    } catch (err) { if (version === epoch.current && request === historyRequest.current) setHistoryError(message(err)); }
    finally { if (version === epoch.current && request === historyRequest.current) setHistoryLoading(false); }
  }, [api, search, area, status, page]);

  useEffect(() => {
    if (view !== 'history') return;
    historyRequest.current++;
    const timer = window.setTimeout(() => void loadHistory(), 250);
    return () => window.clearTimeout(timer);
  }, [view, loadHistory]);

  useEffect(() => {
    if (!dirty && !active) return;
    const leave = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', leave);
    return () => window.removeEventListener('beforeunload', leave);
  }, [dirty, active]);

  const fail = (err: unknown) => {
    setError(message(err));
    setDetails(err instanceof ApiError ? err.details : []);
  };

  const action = async (work: () => Promise<unknown>) => {
    const version = epoch.current;
    setBusy(true); setError(''); setDetails([]); setNotice('');
    try { await work(); } catch (err) { if (version === epoch.current) fail(err); } finally { if (version === epoch.current) setBusy(false); }
  };

  const newTicket = () => {
    if ((dirty || active || report || draft) && !window.confirm('Start a new ticket? Unsaved report and ticket edits will be lost.')) return;
    if (active && api && job) void api.request(api.path(`/generation-jobs/${job.id}`), { method: 'DELETE' }).catch(fail);
    epoch.current++; clearDraft(); setView('new'); setMenu(false);
  };

  const changeDraft = (value: Ticket) => {
    setDraft(value); setDirty(true); setReceipt(null); setNotice(''); setError(''); setDetails([]);
    setReviewAcknowledged(false);
  };

  const generate = () => {
    if (!api) return;
    if (draft && !window.confirm('Replace this draft? Your unsaved ticket edits will be lost.')) return;
    if (job && !active) operation.current = crypto.randomUUID();
    const version = epoch.current;
    void action(async () => {
      const next = await api.send<Job>('/generation-jobs', { report, operation_id: operation.current });
      if (version !== epoch.current) return;
      activeDraftId.current = next.id; setJob(next); setError(''); setConflict(null);
      if (next.status === 'succeeded' && next.payload) { setDraft(next.payload); setSaved(null); setReceipt(null); setDirty(false); }
    });
  };

  const save = async () => {
    if (!api || !draft) return;
    const version = epoch.current;
    try {
      const next = saved
        ? await api.send<SavedTicket>(`/tickets/${saved.id}`, { payload: draft, expected_revision: saved.revision }, 'PATCH')
        : await api.send<SavedTicket>('/tickets', { payload: draft, operation_id: saveOperation.current, job_id: job?.id || null, save_source: saveSource });
      if (version !== epoch.current) return;
      setSaved(next); setDraft(next.payload); setReceipt(null); setDirty(false); setModal(null); setConflict(null);
      setNotice('Draft saved to LedgerFlow.');
      return next;
    } catch (err) {
      if (version === epoch.current && err instanceof ApiError && err.status === 409 && saved) {
        const latest = await api.request<SavedTicket>(api.path(`/tickets/${saved.id}`));
        if (version === epoch.current) { setConflict(latest); setModal(null); }
      }
      throw err;
    }
  };

  const confirmReview = async () => {
    if (!api || !draft) return;
    const version = epoch.current;
    if (saved) {
      let candidate = saved;
      if (dirty) {
        const next = await save();
        if (!next) return;
        candidate = next;
        if (version !== epoch.current) return;
      }
      const next = await api.send<SavedTicket>(`/tickets/${candidate.id}/review`, { expected_revision: candidate.revision });
      if (version !== epoch.current) return;
      setSaved(next); setDraft(next.payload); setDirty(false);
    } else {
      const result = await api.send<{ receipt_id: string }>('/session-reviews', { payload: draft, job_id: job?.id });
      if (version !== epoch.current) return;
      setReceipt(result.receipt_id); setDirty(false);
    }
    setModal(null); setNotice('Current ticket version reviewed. You can export it now.');
  };

  const doExport = (format: 'json' | 'text') => void action(async () => {
    if (!api || !draft) return;
    const version = epoch.current;
    let data: string;
    try { data = await api.export(draft, saved, receipt, format); }
    catch (err) {
      if (version === epoch.current && err instanceof ApiError && err.code === 'review_required') {
        setReceipt(null);
        if (saved) {
          const latest = await api.request<SavedTicket>(api.path(`/tickets/${saved.id}`));
          if (version === epoch.current) { if (latest.revision === saved.revision) setSaved(latest); else setConflict(latest); }
        }
      }
      throw err;
    }
    if (version !== epoch.current) return;
    if (format === 'text') {
      try { await navigator.clipboard.writeText(data); if (version === epoch.current) setNotice('Ticket copied.'); }
      catch { if (version === epoch.current) { setCopyText(data); setModal('copy'); } }
    } else {
      const blob = new Blob([data], { type: 'application/json' });
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = 'bugbrief-ticket.json'; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice('Download started.');
    }
  });

  const openTicket = (id: string) => void action(async () => {
    if (!api) return;
    if ((dirty || active || (!saved && (report || draft))) && !window.confirm('Open this ticket? Unsaved work will be lost.')) return;
    const version = epoch.current;
    if (active && job) await api.request(api.path(`/generation-jobs/${job.id}`), { method: 'DELETE' });
    const next = await api.request<SavedTicket>(api.path(`/tickets/${id}`));
    if (version !== epoch.current) return;
    epoch.current++; clearDraft(); setSaved(next); setDraft(next.payload); setReport(next.source_report || ''); setView('new');
  });

  const signOut = () => void action(async () => {
    if ((dirty || active) && !window.confirm('Sign out? Unsaved work will be lost.')) return;
    if (active && api && job) await api.request(api.path(`/generation-jobs/${job.id}`), { method: 'DELETE' });
    if (config?.mode === 'production' && supabase) {
      const { error: signoutError } = await supabase.auth.signOut(); if (signoutError) throw signoutError;
    }
    epoch.current++; currentUser.current = null; currentWorkspace.current = null; clearDraft(); setItems([]); setSession(null); setApi(null); setWorkspace(null); setPhase('login');
  });

  const changedFields = useMemo(() => conflict && draft ? Object.keys(draft).filter(key => JSON.stringify(draft[key as keyof Ticket]) !== JSON.stringify(conflict.payload[key as keyof Ticket])) : [], [conflict, draft]);

  if (phase !== 'workspace') return <main className="login-page">
    <div className="login-brand"><span className="brand-icon"><FileText size={23} /></span>BugBrief<span className="pilot-label">LedgerFlow pilot</span></div>
    <div className="login-panel"><div className="eyebrow">YOUR SUPPORT WORKSPACE</div><h1>{phase === 'denied' ? 'Access not granted' : 'A clearer handoff starts here.'}</h1><p>{phase === 'denied' ? 'Your account does not have access to this workspace. Contact your workspace owner.' : 'Turn customer reports into tickets your team can review.'}</p>
      {error && <Alert>{error}</Alert>}
      {phase === 'loading' ? <p role="status">Loading your workspace…</p> : <>
        <button className="primary login-action" disabled={busy || !supabase || config?.mode !== 'production'} onClick={() => void action(async () => { const { error: loginError } = await supabase!.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin + '/auth/callback' } }); if (loginError) throw loginError; })}><ShieldCheck size={18} />Continue with Google<ArrowRight size={18} /></button>
        {config?.mode === 'demo' && <><div className="login-divider"><span>local development</span></div><button className="secondary login-action" disabled={busy} onClick={() => void action(() => connect('local-demo'))}>Open local workspace<ArrowRight size={18} /></button><p className="small">Local access without Google authentication. {config.inference.trained ? 'Drafts use the trained experimental adapter when it is ready.' : 'Drafting uses fixed synthetic examples.'}</p></>}
        {config?.mode === 'production' && !supabase && <p className="small">Configure the frontend Supabase URL and publishable key to enable sign-in.</p>}
        {!config && <button className="secondary" onClick={() => window.location.reload()}>Retry connection</button>}
        {phase === 'denied' && <button className="text-button" onClick={signOut}>Use another account</button>}
      </>}
      <div className="login-note"><span className="status-dot" />Invite-only workspace. Saved tickets are shared with your team.</div>
    </div><div className="login-footer">BugBrief · synthetic LedgerFlow pilot</div>
  </main>;

  return <div className="app-shell">
    <aside id="workspace-navigation" className={`sidebar ${menu ? 'is-open' : ''}`}><a className="brand" aria-label="BugBrief" href="#" onClick={e => { e.preventDefault(); if (creating) newTicket(); }}><span className="brand-icon"><FileText size={21} /></span><span className="brand-name">BugBrief</span></a>
      <div className="workspace-switch"><span className="workspace-avatar">L</span><div><strong>{workspace?.name}</strong><span>Team workspace</span></div></div>
      <div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">
        {creating && <button aria-label="New ticket" className={view === 'new' && !saved ? 'selected' : ''} onClick={newTicket}><FilePlus2 size={18} /><span>New ticket</span></button>}
        <button aria-label="Team tickets" className={view === 'history' || !!saved ? 'selected' : ''} onClick={() => { setView('history'); setMenu(false); }}><Layers3 size={18} /><span>Team tickets</span></button>
      </nav>
      <div className="sidebar-bottom"><div className="pilot-badge"><span className="status-dot" />{config?.inference.trained ? 'V2 pilot' : 'Sample pilot'}</div><span className="sidebar-caption">LedgerFlow · English reports</span><button aria-label="Sign out" className="account-button" disabled={busy} onClick={signOut}><span className="user-avatar">{config?.mode === 'demo' ? 'D' : 'U'}</span><div><strong>{config?.mode === 'demo' ? 'Local member' : 'Your account'}</strong><span>{workspace?.role}</span></div><LogOut size={17} /></button></div>
    </aside>
    {menu && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setMenu(false)} />}
    <div className="main-column"><header className="topbar"><button className="icon-button mobile-menu" aria-label={menu ? "Close navigation" : "Open navigation"} aria-controls="workspace-navigation" aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? <X size={20} /> : <Menu size={20} />}</button><div className="breadcrumb">LedgerFlow<ChevronRight size={13} /><span>{view === 'history' ? 'Team tickets' : saved ? 'Saved ticket' : 'New ticket'}</span></div><span className="topbar-meta"><ShieldCheck size={14} />Invite-only workspace</span></header>
      <main className="page-content">
        {(config?.mode === 'demo' || config?.inference.experimental) && <div className="demo-banner"><span className="demo-tag">{config?.mode === 'demo' ? 'LOCAL WORKSPACE' : 'EXPERIMENTAL DRAFTS'}</span><span>{config?.inference.trained ? `${config.inference.profile || 'Trained adapter'} is experimental. Check titles, observed behavior, and inferred goals before export.` : 'Drafting uses fixed synthetic examples.'}{config?.mode === 'demo' ? ' Saving, review, and export work on this computer.' : ' Save a draft explicitly when it is ready for team review.'}</span></div>}
        <div className="page-heading"><div><div className="eyebrow">{view === 'history' ? 'SHARED HANDOFFS' : saved ? 'TEAM TICKET' : 'REPORT TO TICKET'}</div><h1>{view === 'history' ? 'Team tickets' : saved ? 'Review saved ticket' : 'New ticket'}</h1><p>{view === 'history' ? 'Saved tickets are visible to members of LedgerFlow.' : 'Keep the facts. Make the missing details clear.'}</p></div>{view === 'history' && creating && <button className="primary" onClick={newTicket}><PlusIcon />New ticket</button>}{view === 'new' && saved && <span className="revision-label">Revision {saved.revision}</span>}</div>
        {view === 'history' ? <>
          <div className="history-filters"><div className="search-field"><Search size={17} /><input aria-label="Search ticket titles" placeholder="Search ticket titles…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /></div><select aria-label="Filter product area" value={area} onChange={e => { setArea(e.target.value); setPage(0); }}><option value="">All areas</option>{PRODUCT_AREAS.map(a => <option key={a}>{a}</option>)}</select><select aria-label="Filter status" value={status} onChange={e => { setStatus(e.target.value); setPage(0); }}><option value="">All statuses</option><option value="draft">Draft</option><option value="reviewed">Reviewed</option></select></div>
          {historyError && <Alert>{historyError}<button className="text-button" onClick={() => void loadHistory()}>Retry</button></Alert>}
          <div className="ticket-table"><div className="table-head"><span>Ticket</span><span>Product area</span><span>Status</span><span>Updated</span></div>{historyLoading && <div className="table-message" role="status">Loading team tickets…</div>}{!historyLoading && !historyError && items.length === 0 && <div className="table-empty"><FileText size={30} /><h2>{search || area || status ? 'No tickets match these filters.' : 'No tickets saved yet.'}</h2><p>{search || area || status ? 'Try a different search or clear the filters.' : 'Save a draft when you want your team to review it.'}</p>{(search || area || status) && <button className="secondary" onClick={() => { setSearch(''); setArea(''); setStatus(''); setPage(0); }}>Clear filters</button>}</div>}{items.map(item => <button key={item.id} className="ticket-row" disabled={busy} onClick={() => openTicket(item.id)}><span className="row-title"><FileText size={17} /><strong>{item.title}</strong></span><span>{item.product_area}</span><span className={`status-pill ${item.status}`}>{item.status === 'reviewed' ? 'Reviewed' : 'Draft'}</span><time>{new Date(item.updated_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</time></button>)}</div>
          <div className="pagination"><button className="secondary" disabled={page === 0 || historyLoading} onClick={() => setPage(p => p - 1)}><ChevronLeft size={16} />Previous</button><span>Page {page + 1}</span><button className="secondary" disabled={!more || historyLoading} onClick={() => setPage(p => p + 1)}>Next<ChevronRight size={16} /></button></div>
        </> : <>
          {error && <Alert>{error}{details.length > 0 && <ul>{details.map(d => <li key={d.field}>{d.field.replaceAll('_', ' ')}: {d.message}</li>)}</ul>}</Alert>}
          {conflict && <div className="conflict-notice"><h2>Someone updated this ticket.</h2><p>Your edits are kept here. The shared ticket is now revision {conflict.revision}.</p><details><summary>Compare changed fields ({changedFields.length})</summary>{changedFields.map(key => <div className="compare-field" key={key}><strong>{key.replaceAll('_', ' ')}</strong><div><span>Your version</span><pre>{JSON.stringify(draft?.[key as keyof Ticket], null, 2)}</pre></div><div><span>Latest saved version</span><pre>{JSON.stringify(conflict.payload[key as keyof Ticket], null, 2)}</pre></div></div>)}</details><div className="button-row"><button className="secondary" onClick={() => { if (window.confirm('Replace your edits with the latest saved version?')) { setSaved(conflict); setDraft(conflict.payload); setDirty(false); setConflict(null); setError(''); } }}>Load latest version</button><button className="secondary" onClick={() => { setSaved(conflict); setConflict(null); setNotice('Your edits are kept. Save again to apply them to the latest revision.'); setError(''); }}>Keep my edits</button></div></div>}
          <div className="editor-grid"><section className="source-pane"><div className="pane-header"><div className="pane-icon"><FileText size={18} /></div><h2>Customer report</h2><span className="pane-meta">SOURCE</span></div>
            {saved ? <div className="saved-source">{source ? <><p>{source}</p>{!saved.source_report && <p className="hint">Original report available only in this session. It was not saved.</p>}</> : <div className="source-unavailable"><FileText size={25} /><h3>Original report not saved</h3><p>This ticket retains the extracted details. The original report is not available for comparison.</p></div>}</div> : <>
              <label className="sr-only" htmlFor="report">Customer report</label><textarea id="report" className="report-input" placeholder="Paste the customer's report in their own words…" value={report} maxLength={4000} readOnly={active || busy || !!draft} onChange={e => { setReport(e.target.value); operation.current = crypto.randomUUID(); }} />
              {draft && <p className="hint">This report belongs to the current draft. Start a new ticket to use a different report.</p>}<div className="report-count"><span>One short report at a time</span><span>{report.length.toLocaleString()} / 4,000</span></div>
              <div className="sample-control"><label htmlFor="example">Try a synthetic example</label><select id="example" defaultValue="" disabled={active || busy} onChange={e => { const example = samples.find(s => s.id === e.target.value); if (example && (!report || window.confirm('Replace your current report and draft with this synthetic example?'))) { clearDraft(); setReport(example.report); } e.target.value = ''; }}><option value="" disabled>Choose an example</option>{samples.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></div>
              <div className="source-actions"><button className="primary draft-button" disabled={!creating || report.trim().length < 10 || active || busy || !config?.drafting_available} onClick={generate}><Sparkles size={17} />{busy ? 'Submitting…' : active ? job?.status === 'queued' ? 'Report queued' : 'Preparing draft…' : 'Draft ticket'}<ArrowRight size={17} /></button>{active && <button className="text-button" disabled={job?.status === 'cancel_requested'} onClick={() => void action(async () => { if (api && job) { const version = epoch.current; const next = await api.request<Job>(api.path(`/generation-jobs/${job.id}`), { method: 'DELETE' }); if (version === epoch.current) setJob(next); } })}>{job?.status === 'cancel_requested' ? 'Cancelling…' : 'Cancel generation'}</button>}</div>
              {!config?.drafting_available && <p className="hint" role="status">{config?.inference.state === 'loading' ? 'Loading the model. First startup can take several minutes; saved tickets remain available.' : config?.inference.state === 'failed' ? 'The model could not start. Check the API log and restart the server; saved tickets remain available.' : 'Connect the model to enable drafting. Saved tickets remain available.'}</p>}
            </>}
            <div className="source-note"><ShieldCheck size={16} /><p>Unsaved reports stay out of ticket history. Choose whether to include the original when you save.</p></div>
          </section>
          <section className="draft-pane"><div className="pane-header"><div className="pane-icon"><CheckCheck size={18} /></div><h2>Ticket draft</h2><span className={`status-pill ${reviewed ? 'reviewed' : 'draft'}`}>{reviewed ? <><Check size={12} />Reviewed</> : dirty ? 'Needs review' : 'Draft'}</span></div>
            {!draft ? <div className="draft-empty"><span className="empty-icon"><FileText size={30} /></span><h3>{active ? 'Preparing your draft…' : 'Your ticket starts with the report.'}</h3><p>{active ? 'Your report is queued or being processed. You can cancel while you wait.' : 'Paste a report or choose an example. Then review the facts and fill in the gaps.'}</p><div className="empty-steps"><span><span>1</span>Add a report</span><span><span>2</span>Review the draft</span><span><span>3</span>Export the ticket</span></div></div> : <>
              <div className="draft-checks" aria-live="polite"><h3>Source comparison</h3>{checking ? <p className="hint">Checking this draft against the available report…</p> : checksError ? <p className="hint">Automated checks are unavailable: {checksError} Compare the fields manually.</p> : checks && <><p className="hint">{checks.findings.length ? 'Check these possible issues. Automated checks can miss errors.' : 'No issues flagged by these limited checks. Compare all facts with the report.'}</p>{checks.findings.length > 0 && <ul>{checks.findings.map(finding => <li key={finding.code + finding.field}><strong>{finding.field.replaceAll('_', ' ').replaceAll('.', ' · ')}</strong><span>{finding.message}</span></li>)}</ul>}</>}</div>
              <TicketEditor ticket={draft} onChange={changeDraft} readOnly={!creating || busy || active} source={source} />
              <div className="review-actions"><p><ShieldCheck size={16} />{reviewed ? 'This exact version has been reviewed.' : creating ? 'Compare the draft with the source before exporting.' : 'A contributor must review this version before export.'}</p><div className="button-row">{creating && <><button className="secondary" disabled={busy || active || (!dirty && !!saved)} onClick={() => { setSaveSource(false); setModal('save'); }}>Save draft</button><button className="primary" disabled={busy || active || reviewed || !!conflict} onClick={() => setModal('review')}><CheckCheck size={17} />Review ticket</button></>}<button className="secondary" disabled={busy || active || !reviewed} onClick={() => doExport('text')}><Clipboard size={16} />Copy ticket</button><button className="secondary" disabled={busy || active || !reviewed} onClick={() => doExport('json')}><ArrowDownToLine size={16} />JSON</button></div>{canDelete && <button className="text-button danger" disabled={busy} onClick={() => setModal('delete')}>Delete saved ticket</button>}</div>
            </>}
          </section></div>
          <div className="workspace-footnote"><span>Review is always a human decision.</span><span>Authentication · Billing · Dashboard · Integrations</span></div>
        </>}
        {notice && <div className="notice" role="status"><Check size={17} />{notice}<button className="icon-button" aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={16} /></button></div>}
      </main>
    </div>
    {modal && <Dialog title={{ save: 'Save to your workspace', review: 'Review this ticket', delete: 'Delete saved ticket', copy: 'Select and copy ticket' }[modal]} onClose={() => { if (!busy) setModal(null); }}>
      {modal === 'save' && <><p>This ticket will be visible to members of LedgerFlow. Extracted details and evidence are saved with the ticket.</p>{!saved && <label className="checkbox-row"><input type="checkbox" checked={saveSource} onChange={e => setSaveSource(e.target.checked)} />Also save the original customer report</label>}<p className="hint">Saving a draft does not mark it as reviewed.</p><div className="dialog-actions"><button className="secondary" disabled={busy} onClick={() => setModal(null)}>Cancel</button><button className="primary" disabled={busy} onClick={() => void action(save)}>{busy ? 'Saving…' : 'Save draft'}</button></div></>}
      {modal === 'review' && <><p>Compare the title and actual behavior with the report, including words such as lost, retained, and not. Verify expectation labels, environment, and reported steps.</p><div className="review-summary"><strong>{draft?.title}</strong><span>{draft?.product_area} · {saved ? `Revision ${saved.revision}${dirty ? ' with your edits' : ''}` : 'Current draft'}</span><span>Expected behavior: {draft?.expected_behavior_basis}</span></div>{checks?.findings.length ? <p className="hint">{checks.findings.length} possible issue(s) flagged. Resolve them in the editor or verify the wording against the source.</p> : null}{!source && <p className="hint">The original report is unavailable. This confirmation cannot establish source fidelity.</p>}<label className="checkbox-row"><input type="checkbox" checked={reviewAcknowledged} onChange={e => setReviewAcknowledged(e.target.checked)} />I checked the meaning of the current title and observed behavior, expectation basis, environment, and reported steps.</label><div className="dialog-actions"><button className="secondary" disabled={busy} onClick={() => setModal(null)}>Keep editing</button><button className="primary" disabled={busy || checking || !reviewAcknowledged} onClick={() => void action(confirmReview)}>{busy ? 'Confirming…' : 'Confirm reviewed version'}</button></div></>}
      {modal === 'delete' && <><p>Delete “{saved?.payload.title}” and its saved revisions? This cannot be undone.</p><div className="dialog-actions"><button className="secondary" disabled={busy} onClick={() => setModal(null)}>Cancel</button><button className="danger-button" disabled={busy} onClick={() => void action(async () => { if (api && saved) { const version = epoch.current; await api.request(api.path(`/tickets/${saved.id}`), { method: 'DELETE' }); if (version === epoch.current) { clearDraft(); setView('history'); } } })}>{busy ? 'Deleting…' : 'Delete ticket'}</button></div></>}
      {modal === 'copy' && <><p>Your browser did not permit clipboard access. Select this text and copy it.</p><textarea className="copy-preview" aria-label="Reviewed ticket text" readOnly value={copyText} onFocus={e => e.target.select()} /><div className="dialog-actions"><button className="primary" onClick={() => setModal(null)}>Done</button></div></>}
      {error && <Alert>{error}</Alert>}
    </Dialog>}
  </div>;
}

function PlusIcon() { return <FilePlus2 size={17} />; }
