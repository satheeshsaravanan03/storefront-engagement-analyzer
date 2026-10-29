'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Loader2, Trash2, X, Download, RefreshCw, Plus, Film, AlertTriangle, Search,
} from 'lucide-react';
import clsx from 'clsx';
import { listJobs, deleteJob, getJobStatus, type JobSummary, type AnalysisResult } from '@/lib/api';
import { EngagementResults } from '@/components/EngagementResults';
import { AppShell } from '@/components/AppShell';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

type Filter = 'all' | 'done' | 'processing' | 'error';

const PILL: Record<Filter, { label: string; cls: string; dot: string }> = {
  all:        { label: 'All',        cls: '', dot: '' },
  done:       { label: 'Done',       cls: 'bg-cv-green/10 text-cv-green', dot: 'bg-cv-green' },
  processing: { label: 'Processing', cls: 'bg-cv-cyan/10 text-cv-cyan',   dot: 'bg-cv-cyan' },
  error:      { label: 'Failed',     cls: 'bg-cv-red/10 text-cv-red',     dot: 'bg-cv-red' },
};
const bucket = (j: JobSummary): Filter => (j.status === 'queued' ? 'processing' : j.status);

/* ── Side drawer: viewers of one job ──────────────────────── */
function JobDrawer({ job, onClose }: { job: JobSummary; onClose: () => void }) {
  const [detail, setDetail] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null); setError(null);
    getJobStatus(job.job_id)
      .then(setDetail)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load job'));
  }, [job.job_id]);

  // Freeze the page behind the drawer, and close on Escape
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const { body, documentElement: html } = document;
    const prev = { overflow: body.style.overflow, pad: body.style.paddingRight };
    const scrollbar = window.innerWidth - html.clientWidth;
    body.style.overflow = 'hidden';
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`; // avoid a layout jump
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeRef.current(); };
    window.addEventListener('keydown', onKey);
    return () => {
      body.style.overflow = prev.overflow;
      body.style.paddingRight = prev.pad;
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  // Thresholds this job was processed with (read-only)
  const thr = {
    glance: detail?.stats?.glance_sec ?? 2,
    engage: detail?.stats?.engage_sec ?? 5,
    strong: detail?.stats?.strong_sec ?? 10,
  };

  return (
    <>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose} className="fixed inset-0 bg-black/50 z-40 overscroll-contain" />
      <motion.aside
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'tween', duration: 0.25 }}
        className="fixed top-0 right-0 h-full w-full max-w-3xl bg-cv-surface border-l border-cv-border z-50 overflow-y-auto overscroll-contain"
      >
        <div className="sticky top-0 bg-cv-surface/95 backdrop-blur border-b border-cv-border px-6 py-4 flex items-center gap-3 z-10">
          <div className="min-w-0">
            <p className="font-semibold text-cv-text truncate">{job.filename}</p>
            <p className="text-cv-sub text-xs font-mono">Job {job.job_id} · {new Date(job.created_at * 1000).toLocaleString()}</p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {job.status === 'done' && (
              <a href={`${BACKEND}/api/download/${job.job_id}/zip`}
                className="flex items-center gap-1.5 bg-cv-accent hover:bg-cv-accentL text-white text-xs font-semibold px-3 py-2 rounded-xl transition-colors">
                <Download size={13} /> ZIP
              </a>
            )}
            <button onClick={onClose} className="text-cv-sub hover:text-cv-text transition-colors"><X size={18} /></button>
          </div>
        </div>

        <div className="p-6 space-y-4">
          {!detail && !error && (
            <div className="flex items-center gap-2 text-cv-sub text-sm"><Loader2 size={14} className="animate-spin" /> Loading viewers...</div>
          )}
          {error && <p className="text-cv-red text-sm font-mono">{error}</p>}
          {detail?.status === 'error' && (
            <div className="glow-border bg-cv-red/5 border-cv-red/30 rounded-2xl p-4 flex gap-3">
              <AlertTriangle size={18} className="text-cv-red flex-shrink-0" />
              <p className="text-cv-sub text-xs font-mono whitespace-pre-wrap">{detail.error}</p>
            </div>
          )}
          {detail?.status === 'done' && (
            <>
              <div className="glow-border bg-cv-card rounded-2xl p-4 flex items-center gap-6 flex-wrap text-sm text-cv-sub">
                <span className="text-xs font-mono">THRESHOLDS USED</span>
                <span>Looked from <span className="font-mono text-cv-text">{thr.glance} s</span></span>
                <span>Engaged from <span className="font-mono text-cv-text">{thr.engage} s</span></span>
                <span>Strong from <span className="font-mono text-cv-text">{thr.strong} s</span></span>
              </div>
              <EngagementResults
                viewers={detail.viewers ?? []}
                glanceSec={thr.glance} engageSec={thr.engage} strongSec={thr.strong}
                durationSec={detail.stats?.duration_sec ?? 0}
                ignored={detail.stats?.ignored ?? 0}
                csvUrl={detail.viewers_url}
                jsonUrl={detail.engaged_json_url}
                imageBase={`${BACKEND}/api/file/${job.job_id}/`}
                jobId={job.job_id}
              />
            </>
          )}
        </div>
      </motion.aside>
    </>
  );
}

/* ── Jobs page ────────────────────────────────────────────── */
export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');

  const refresh = useCallback(() => {
    listJobs().then(j => { setJobs(j); setError(null); })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load jobs'));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Keep running jobs fresh
  useEffect(() => {
    if (!jobs?.some(j => j.status === 'queued' || j.status === 'processing')) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [jobs, refresh]);

  const handleDelete = async (j: JobSummary) => {
    if (!window.confirm(`Delete job ${j.job_id} (${j.filename}) and all its files?`)) return;
    setBusy(j.job_id);
    try {
      await deleteJob(j.job_id);
      if (selected?.job_id === j.job_id) setSelected(null);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setBusy(null);
    }
  };

  const all = jobs ?? [];
  const done = all.filter(j => j.status === 'done');
  const viewers = done.reduce((n, j) => n + j.viewers, 0);
  const engaged = done.reduce((n, j) => n + j.engaged + j.strong, 0);
  const rate = viewers ? Math.round((engaged / viewers) * 100) : 0;
  const count = (f: Filter) => (f === 'all' ? all.length : all.filter(j => bucket(j) === f).length);

  const q = query.trim().toLowerCase();
  const rows = all.filter(j =>
    (filter === 'all' || bucket(j) === filter) &&
    (!q || j.filename.toLowerCase().includes(q) || j.job_id.toLowerCase().includes(q)));

  const kpis = [
    { label: 'Videos analysed',  value: done.length, accent: false },
    { label: 'Viewers detected', value: viewers,     accent: false },
    { label: 'Engaged or more',  value: engaged,     accent: true  },
    { label: 'Engagement rate',  value: `${rate}%`,  accent: false },
  ];

  return (
    <AppShell>
      <div>
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-wider text-cv-accent mb-2">HISTORY</p>
            <h1 className="font-display text-4xl text-cv-text mb-2">Uploaded videos</h1>
            <p className="text-cv-sub">One record per analysed video. Select a row to see its viewers.</p>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <button onClick={refresh}
              className="glow-border bg-cv-card text-cv-text hover:border-cv-accent/40 px-4 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2 transition-colors">
              <RefreshCw size={14} /> Refresh
            </button>
            <Link href="/dashboard"
              className="bg-cv-accent hover:bg-cv-accentL text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors">
              <Plus size={15} /> New video
            </Link>
          </div>
        </div>

        {error && <p className="text-cv-red text-sm font-mono mb-4">{error}</p>}

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {kpis.map(k => (
            <div key={k.label} className="glow-border bg-cv-card p-5">
              <p className="text-cv-sub text-sm mb-2">{k.label}</p>
              <p className={clsx('font-display text-4xl', k.accent ? 'text-cv-accent' : 'text-cv-text')}>{k.value}</p>
            </div>
          ))}
        </div>

        <div className="glow-border bg-cv-card overflow-hidden">
          <div className="p-5 flex items-center gap-3 flex-wrap">
            {(['all', 'done', 'processing', 'error'] as Filter[]).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={clsx('px-4 py-2 rounded-full text-sm font-medium border transition-colors flex items-center gap-2',
                  filter === f ? 'bg-cv-accent text-white border-cv-accent' : 'bg-cv-card text-cv-text border-cv-border hover:border-cv-accent/40')}>
                {PILL[f].label}
                <span className={clsx('text-xs', filter === f ? 'text-white/80' : 'text-cv-sub')}>{count(f)}</span>
              </button>
            ))}
            <div className="relative ml-auto w-full sm:w-72">
              <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-cv-sub" />
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search file or job ID"
                className="w-full pl-10 pr-3 py-2.5 rounded-xl border border-cv-border bg-cv-card text-sm text-cv-text placeholder:text-cv-sub focus:outline-none focus:border-cv-accent" />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-cv-black text-cv-sub text-xs font-semibold tracking-wider">
                <tr className="border-y border-cv-border">
                  <th className="text-left px-5 py-3 font-semibold">VIDEO</th>
                  <th className="text-left px-3 py-3 font-semibold">UPLOADED</th>
                  <th className="text-left px-3 py-3 font-semibold">STATUS</th>
                  <th className="text-right px-3 py-3 font-semibold">LENGTH</th>
                  <th className="text-right px-3 py-3 font-semibold">VIEWERS</th>
                  <th className="text-right px-3 py-3 font-semibold">ENGAGED+</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody>
                {jobs === null && !error && (
                  <tr><td colSpan={7} className="px-5 py-10 text-center text-cv-sub text-sm">
                    <Loader2 size={14} className="animate-spin inline mr-2" />Loading...
                  </td></tr>
                )}
                {jobs && rows.length === 0 && (
                  <tr><td colSpan={7} className="px-5 py-12 text-center text-cv-sub text-sm">
                    {all.length === 0
                      ? <>No videos yet. <Link href="/dashboard" className="text-cv-accent font-medium">Upload one</Link>.</>
                      : 'No jobs match this filter.'}
                  </td></tr>
                )}
                {rows.map(j => {
                  const b = bucket(j);
                  const finished = j.status === 'done';
                  const pct = finished && j.viewers ? Math.round(((j.engaged + j.strong) / j.viewers) * 100) : 0;
                  const d = new Date(j.created_at * 1000);
                  return (
                    <tr key={j.job_id} onClick={() => setSelected(j)}
                      className={clsx('border-b border-cv-border/60 text-cv-text cursor-pointer hover:bg-cv-black/70 transition-colors',
                        selected?.job_id === j.job_id && 'bg-cv-accent/5')}>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-lg bg-cv-accent/10 flex items-center justify-center flex-shrink-0">
                            <Film size={15} className="text-cv-accent" />
                          </div>
                          <div className="min-w-0">
                            <p className="font-medium truncate max-w-[230px]">{j.filename}</p>
                            <p className="text-cv-sub text-xs font-mono">{j.job_id}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3.5 whitespace-nowrap">
                        <p className="font-medium">{d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</p>
                        <p className="text-cv-sub text-xs">{d.toLocaleTimeString('en-US')}</p>
                      </td>
                      <td className="px-3 py-3.5">
                        <span className={clsx('inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full', PILL[b].cls)}>
                          <span className={clsx('w-1.5 h-1.5 rounded-full', PILL[b].dot)} />{PILL[b].label}
                        </span>
                        {b === 'processing' && (
                          <div className="flex items-center gap-2 mt-1.5">
                            <div className="h-1 w-24 bg-cv-border rounded-full overflow-hidden">
                              <div className="h-full bg-cv-cyan" style={{ width: `${Math.round(j.progress)}%` }} />
                            </div>
                            <span className="text-cv-cyan text-[11px] font-medium">{Math.round(j.progress)}%</span>
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-3.5 text-right">{j.duration_sec != null ? `${j.duration_sec.toFixed(0)}s` : '—'}</td>
                      <td className="px-3 py-3.5 text-right">{finished ? j.viewers : '—'}</td>
                      <td className="px-3 py-3.5">
                        <div className="flex items-center justify-end gap-3">
                          <div className="h-1.5 w-16 bg-cv-border rounded-full overflow-hidden">
                            <div className="h-full bg-cv-accent" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="font-semibold text-cv-accent w-5 text-right">{finished ? j.engaged + j.strong : '—'}</span>
                        </div>
                      </td>
                      <td className="px-5 py-3.5 text-right whitespace-nowrap">
                        <button onClick={e => { e.stopPropagation(); setSelected(j); }}
                          className="text-cv-accent hover:text-cv-accentL text-sm font-semibold mr-3">View</button>
                        <button onClick={e => { e.stopPropagation(); handleDelete(j); }}
                          disabled={busy === j.job_id || b === 'processing'}
                          className="text-cv-sub hover:text-cv-red disabled:opacity-40 disabled:cursor-not-allowed transition-colors align-middle"
                          title="Delete">
                          {busy === j.job_id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="px-5 py-3.5 flex items-center justify-between text-sm text-cv-sub">
            <span>Showing {rows.length} of {all.length} jobs</span>
            <span>Newest first</span>
          </div>
        </div>
      </div>

      <AnimatePresence>
        {selected && <JobDrawer key={selected.job_id} job={selected} onClose={() => setSelected(null)} />}
      </AnimatePresence>
    </AppShell>
  );
}
