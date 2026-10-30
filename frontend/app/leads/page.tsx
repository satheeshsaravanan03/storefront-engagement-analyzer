'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ImageOff, Loader2, Plus, RefreshCw, Search, Upload, X } from 'lucide-react';
import clsx from 'clsx';
import { listRegistry, registerLead, type RegisteredProfile } from '@/lib/api';
import { Avatar } from '@/components/MatchedLeads';
import { AppShell } from '@/components/AppShell';

const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '–';

const noPhoto = (p: RegisteredProfile) => p.photo_status !== 'ok';

function RegisterModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !formRef.current) { setError('Attach a photo of the face'); return; }
    const form = new FormData(formRef.current);
    form.set('photo', file);
    setBusy(true); setError(null);
    try { await registerLead(form); onDone(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not register the lead'); }
    finally { setBusy(false); }
  };

  const input = 'w-full bg-cv-surface border border-cv-border rounded-xl px-3 py-2.5 text-sm text-cv-text focus:outline-none focus:border-cv-accent';
  const label = 'block text-xs font-semibold text-cv-sub mb-1.5';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <form ref={formRef} onSubmit={submit}
        className="relative bg-cv-surface border border-cv-border rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 space-y-4">
        <div className="flex items-center">
          <h2 className="font-display text-2xl text-cv-text">Register lead</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="ml-auto text-cv-sub hover:text-cv-text"><X size={18} /></button>
        </div>
        <p className="text-cv-sub text-sm -mt-2">
          Only register people who agreed to be recognised at the event. The face in the photo is compared with visitors in analysed videos.
        </p>

        <div>
          <span className={label}>Photo (clear, front-facing face)</span>
          <label className="flex items-center gap-4 border border-dashed border-cv-border rounded-xl p-3 cursor-pointer hover:border-cv-accent/50">
            {preview
              // eslint-disable-next-line @next/next/no-img-element
              ? <img src={preview} alt="" className="w-16 h-16 rounded-lg object-cover object-top" />
              : <div className="w-16 h-16 rounded-lg bg-cv-black flex items-center justify-center"><Upload size={18} className="text-cv-sub" /></div>}
            <span className="text-sm text-cv-sub truncate">{file ? file.name : 'Choose an image…'}</span>
            <input type="file" accept="image/*" className="sr-only" onChange={e => setFile(e.target.files?.[0] ?? null)} />
          </label>
        </div>

        <div><label className={label} htmlFor="name">Name *</label>
          <input id="name" name="name" required maxLength={120} className={input} /></div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div><label className={label} htmlFor="email">Email</label>
            <input id="email" name="email" type="email" maxLength={160} className={input} /></div>
          <div><label className={label} htmlFor="phone">Phone</label>
            <input id="phone" name="phone" maxLength={40} className={input} /></div>
          <div><label className={label} htmlFor="role">Role</label>
            <input id="role" name="role" maxLength={120} className={input} /></div>
          <div><label className={label} htmlFor="company">Company</label>
            <input id="company" name="company" maxLength={120} className={input} /></div>
        </div>

        {error && <p className="text-sm text-cv-red bg-cv-red/10 rounded-xl px-3 py-2">{error}</p>}

        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose}
            className="px-4 py-2.5 rounded-xl text-sm font-medium text-cv-sub hover:text-cv-text">Cancel</button>
          <button type="submit" disabled={busy}
            className="bg-cv-accent hover:bg-cv-accentL disabled:opacity-60 text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors">
            {busy && <Loader2 size={14} className="animate-spin" />} Register
          </button>
        </div>
      </form>
    </div>
  );
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<RegisteredProfile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [adding, setAdding] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true); setError(null);
    try { setLeads(await listRegistry()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to load leads'); }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (leads ?? []).filter(p => !q || [p.name, p.company, p.id, p.role, p.email].some(v => v?.toLowerCase().includes(q)));
  }, [leads, query]);
  const missing = (leads ?? []).filter(noPhoto).length;

  return (
    <AppShell>
      <div>
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div className="max-w-xl">
            <p className="text-xs font-semibold tracking-wider text-cv-accent mb-2">REGISTRY</p>
            <h1 className="font-display text-4xl text-cv-text mb-2">Registered leads</h1>
            <p className="text-cv-sub">
              People registered with their photo and contact details. Visitors recognised in analysed videos show up under each video in Jobs.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={load} disabled={refreshing}
              className="glow-border bg-cv-card text-cv-text hover:border-cv-accent/40 px-4 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2 transition-colors">
              <RefreshCw size={14} className={clsx(refreshing && 'animate-spin')} /> Refresh
            </button>
            <button onClick={() => setAdding(true)}
              className="bg-cv-accent hover:bg-cv-accentL text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors">
              <Plus size={15} /> Register lead
            </button>
          </div>
        </div>

        {error && <p className="mb-4 text-sm text-cv-red bg-cv-red/10 rounded-xl px-4 py-3">{error}</p>}
        {missing > 0 && (
          <p className="mb-5 flex items-center gap-3 text-sm text-cv-amber bg-cv-amber/10 border border-cv-amber/30 rounded-xl px-4 py-3">
            <AlertTriangle size={16} className="shrink-0" />
            <span><b>{missing} {missing === 1 ? 'lead has' : 'leads have'} no photo yet.</b> Face matching needs an image for each lead:
              use Register lead, or add <code className="font-mono text-xs">registry/photos/&lt;ID&gt;.jpg</code>.</span>
          </p>
        )}

        <div className="flex justify-end mb-4">
          <div className="relative w-full max-w-sm">
            <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-cv-sub" />
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search name, company or ID"
              className="w-full bg-cv-card border border-cv-border rounded-xl pl-10 pr-3 py-2.5 text-sm text-cv-text focus:outline-none focus:border-cv-accent" />
          </div>
        </div>

        <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[820px]">
              <thead>
                <tr className="text-left text-[11px] tracking-wider text-cv-sub bg-cv-black/60">
                  {['LEAD', 'ROLE & COMPANY', 'EMAIL', 'PHONE', 'REGISTERED AT'].map(h => (
                    <th key={h} className="px-5 py-3.5 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leads === null && !error && (
                  <tr><td colSpan={5} className="px-5 py-10 text-cv-sub"><Loader2 size={15} className="inline animate-spin mr-2" />Loading…</td></tr>
                )}
                {leads !== null && shown.length === 0 && (
                  <tr><td colSpan={5} className="px-5 py-10 text-center text-cv-sub">
                    {leads.length === 0 ? 'No leads registered yet.' : 'No lead matches your search.'}</td></tr>
                )}
                {shown.map(p => (
                  <tr key={p.id} className="border-t border-cv-border/60 text-cv-text">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar profile={p} className="w-11 h-11 rounded-xl border border-cv-border text-sm shrink-0" />
                        <div className="min-w-0">
                          <p className="font-semibold truncate">{p.name}</p>
                          <p className="text-cv-sub text-xs font-mono flex items-center gap-1.5">
                            {p.id}
                            {noPhoto(p) && <span className="inline-flex items-center gap-1 text-cv-amber font-sans"><ImageOff size={11} /> no photo</span>}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <p>{p.role || '–'}</p>
                      {p.company && <p className="text-cv-sub text-xs">{p.company}</p>}
                    </td>
                    <td className="px-5 py-3">{p.email ? <a href={`mailto:${p.email}`} className="hover:text-cv-accent">{p.email}</a> : '–'}</td>
                    <td className="px-5 py-3 whitespace-nowrap">{p.phone || '–'}</td>
                    <td className="px-5 py-3 text-cv-sub whitespace-nowrap">{fmtDate(p.registered_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 border-t border-cv-border text-xs text-cv-sub flex justify-between">
            <span>Showing {shown.length} of {leads?.length ?? 0} leads</span>
            <span>Sorted by ID</span>
          </div>
        </div>
      </div>
      {adding && <RegisterModal onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); }} />}
    </AppShell>
  );
}
